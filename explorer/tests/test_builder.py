"""Regression tests against the actual corpus and the browser's query compiler.

Run: python3 -m unittest discover -s explorer/tests -v
Requires Node.js for the same JavaScript compiler the UI uses.
"""
import json
from pathlib import Path
import subprocess
import sys
import unittest

EXPLORER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPLORER))
from app.graph_service import AFG, GraphService
from app.views import builder_options


def compile_plans(plans):
    """Compile builder plans using the JavaScript implementation."""
    script = """
import {compile} from './explorer/static/js/views/builder-model.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
console.log(JSON.stringify(JSON.parse(input).map(p => compile(p))));
"""
    output = subprocess.check_output(
        ['node', '--input-type=module', '-e', script],
        input=json.dumps(plans).encode(), cwd=EXPLORER.parent,
    )
    return json.loads(output)


def plan(root='FinancialInstitution', steps=None):
    """Create a builder plan for a root class and steps."""
    return {'rootClass': AFG + root, 'steps': steps or []}


def relation(option, source='record', step_id=1):
    """Create a relationship step for a builder plan."""
    return {'id': step_id, 'kind': 'relation', 'from': source,
            'property': option['property'], 'range': option['range']}


class BuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load shared fixtures for this test class."""
        cls.service = GraphService()

    def options(self, p):
        """Return builder options for a compiled plan."""
        return builder_options(self.service, compile_plans([p])[0]['sparql'])

    def test_firms_do_not_offer_unrecorded_direct_evidence(self):
        """Check that firms do not offer unrecorded direct evidence."""
        choices = self.options(plan())
        expected = self.service.run_local('SELECT DISTINCT ?f WHERE { ?f rdf:type/rdfs:subClassOf* :FinancialInstitution }')
        self.assertTrue(expected.ok, expected.error)
        self.assertEqual(choices['count'], expected.count)
        props = {o['property'] for o in choices['nodes']['record']['relationships']}
        direct = self.service.run_local('ASK { ?f rdf:type/rdfs:subClassOf* :FinancialInstitution ; :hasEvidence ?s }')
        self.assertEqual(AFG + 'hasEvidence' in props, direct.boolean)
        self.assertIn(AFG + 'hasGovernancePolicy', props)

    def test_every_offered_choice_has_the_advertised_matches(self):
        """Check that every offered choice has the advertised matches."""
        candidates = []
        expected = []

        firm_options = self.options(plan())['nodes']['record']['relationships']
        policy = next(o for o in firm_options if o['property'] == AFG + 'hasGovernancePolicy' and o['range'] is None)
        prefixes = [plan(), plan('EvidenceSnippet'), plan('AIFinanceGovernanceConcept'),
                    plan(steps=[relation(policy)])]
        for prefix in prefixes:
            options = self.options(prefix)
            for variable, choices in options['nodes'].items():
                for option in choices['relationships']:
                    candidates.append({**prefix, 'steps': prefix['steps'] + [relation(option, variable, 8)]})
                    expected.append(option['count'])
                for field in choices['fields']:
                    base = {'kind': 'value', 'id': 9, 'from': variable, 'property': field['property']}
                    operations = [('present', None, field['present']), ('show', None, options['count'])]
                    if field['absent']:
                        operations.append(('absent', None, field['absent']))
                    operations += [('is', value['value'], value['count']) for value in field['values']]
                    for op, value, count in operations:
                        candidates.append({**prefix, 'steps': prefix['steps'] + [{**base, 'op': op, 'value': value}]})
                        expected.append(count)
        self.assertGreater(len(candidates), 100)
        for compiled, count in zip(compile_plans(candidates), expected):
            with self.subTest(query=compiled['sparql']):
                result = self.service.run_local(compiled['sparql'])
                self.assertTrue(result.ok, result.error)
                # A root may produce several rows, but choices count distinct roots.
                roots = {row[0]['value'] for row in result.rows}
                self.assertEqual(len(roots), count)
                self.assertGreater(len(roots), 0)

    def test_step_ids_and_exact_literal_escaping(self):

        """Check that step ids and exact literal escaping."""
        from rdflib import Literal, URIRef
        subject = URIRef(AFG + 'CommonwealthBank')
        prop = URIRef(AFG + 'testBuilderValue')
        for value in ['', 'A "quoted" value\\with\na newline', '  spaced  ']:
            self.service.graph.add((subject, prop, Literal(value)))
            p = plan(steps=[{'kind': 'value', 'id': 42, 'from': 'record',
                             'property': str(prop), 'op': 'is', 'value': value}])
            built = compile_plans([p])[0]
            result = self.service.run_local(built['sparql'])
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.count, 1)
            self.assertEqual(result.rows[0][1]['value'], value)
            self.assertEqual(built['values'][0]['var'], 'field42')
            self.service.graph.remove((subject, prop, None))

    def test_graph_results_and_unbound_solutions(self):
        for sparql in ('DESCRIBE <urn:subject> WHERE {}',
                       'CONSTRUCT { <urn:s> <urn:p> "value" } WHERE {}'):
            result = self.service.run_local(sparql)
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.columns, ['subject', 'predicate', 'object'])
        describe = self.service.run_local(f'DESCRIBE <{AFG}HSBC>')
        self.assertGreater(describe.count, 0)
        self.assertTrue(all(len(row) == 3 for row in describe.rows))
        self.assertEqual(self.service.run_local('SELECT ?missing WHERE {}').rows, [[None]])

    def test_external_sparql_clauses_are_rejected_before_evaluation(self):
        for query in ('ASK { SERVICE <urn:remote> { ?s ?p ?o } }',
                      'ASK { FILTER EXISTS { SERVICE SILENT <urn:remote> { ?s ?p ?o } } }',
                      'SELECT * FROM NAMED <urn:remote> WHERE { ?s ?p ?o }'):
            result = self.service.run_local(query)
            self.assertFalse(result.ok)
            self.assertIn('local graph', result.error)
        self.assertTrue(self.service.run_local('SELECT ("SERVICE and FROM" AS ?text) WHERE {}').ok)

    def test_viewer_requires_all_quote_fragments_in_order(self):
        script = """
import assert from 'node:assert/strict';
import {quoteRanges} from './explorer/static/js/quote-match.js';
const parts = ['The bank tests its AI models ', 'before use.'];
assert.deepEqual(quoteRanges(parts, '…'), []);
assert.deepEqual(quoteRanges(parts, 'The bank tests its AI models before use and guarantees fairness'), []);
assert.deepEqual(quoteRanges(parts, 'before use ... the bank'), []);
assert.deepEqual(quoteRanges(parts, 'models … use'), [
  {index: 0, start: 22, end: 28}, {index: 1, start: 7, end: 10},
]);
assert.deepEqual(quoteRanges(['The  ﬁrm'], 'firm'), [{index: 0, start: 5, end: 8}]);
"""
        subprocess.run(['node', '--input-type=module', '-e', script], cwd=EXPLORER.parent, check=True)

    def test_invalid_query_is_an_error_not_empty_choices(self):
        """Check that invalid query is an error not empty choices."""
        with self.assertRaises(ValueError):
            builder_options(self.service, 'not a query')


if __name__ == '__main__':
    unittest.main()
