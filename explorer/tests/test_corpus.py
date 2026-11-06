"""Corpus writes must survive restart, retain provenance, and reject partial saves."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from email.message import Message
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace, RDF

EXPLORER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPLORER))
from app import corpus, views
from app.graph_service import GraphService
import server

A = Namespace('https://w3id.org/ai-finance-governance#')


class CorpusTests(unittest.TestCase):
    def setUp(self):
        """Set up an isolated corpus and graph for each test."""
        self.temp = tempfile.TemporaryDirectory(prefix='explorer-corpus-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'ontology').mkdir()
        for name in ('ai-finance-governance.ttl', 'airo.ttl'):
            shutil.copyfile(EXPLORER.parent / 'ontology' / name, self.root / 'ontology' / name)
        self.service = GraphService(self.root)
        self.original = self.service.ontology.read_text()

    def payload(self, text='The organisation reviews AI models before deployment.'):
        """Create a valid test document payload."""
        return {
            'title': 'Test source “with quotes”', 'documentClass': str(A.SourceDocument),
            'documentType': 'Test report', 'documentDate': '2026',
            'documentURL': 'https://example.invalid/test-report',
            'owner': {'iri': str(A.CommonwealthBank)},
            'file': {'name': 'report.html', 'content': base64.b64encode(f'<html><body>{text}</body></html>'.encode()).decode()},
            'snippets': [{'exactText': text, 'pageReference': 'Not paginated',
                          'sectionReference': 'AI review', 'target': {
                              'classIri': str(A.GovernanceStatement), 'label': 'A scoped test statement',
                              'details': {str(A.statementTopic): 'Accountability', str(A.statementStatus): 'Test source; review pending'},
                              'links': [{'property': str(A.hasStatement), 'target': '@owner', 'direction': 'in'}],
                          }}],
        }

    def archives(self):
        """List archived files in the test corpus."""
        return list((self.root / 'corpus' / 'uploads').glob('*'))

    def request(self, method, path, payload=None, origin=None, content_type='application/json'):
        """Send a test request to the explorer API."""
        body = json.dumps(payload).encode() if payload is not None else b''
        # Invoke the real handler without opening a listening socket.
        handler = object.__new__(server.Handler)
        handler.command, handler.path = method, path
        handler.request_version = 'HTTP/1.1'
        handler.requestline = f'{method} {path} HTTP/1.1'
        handler.close_connection = False
        handler.headers = Message()
        handler.headers['Content-Type'] = content_type
        handler.headers['Content-Length'] = str(len(body))
        handler.headers['Host'] = '127.0.0.1:8042'
        if origin:
            handler.headers['Origin'] = origin
        handler.rfile, handler.wfile = BytesIO(body), BytesIO()
        handler.log_message = lambda *args: None
        with patch.object(server, 'service', self.service, create=True):
            getattr(handler, 'do_' + method)()
        header, response = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
        return int(header.splitlines()[0].split()[1]), json.loads(response)

    def test_document_and_evidence_are_queryable_after_restart(self):
        """Check that document and evidence are queryable after restart."""
        payload = self.payload('A "quoted" statement\\with a newline\nand qualifications.')
        result = corpus.save_document(self.service, payload)
        document = result['document']
        archived = self.root / document['localPath']
        self.assertEqual(archived.read_bytes(), base64.b64decode(payload['file']['content']))
        self.assertEqual(document['sha256'], hashlib.sha256(archived.read_bytes()).hexdigest())
        self.assertTrue(self.service.ontology.read_text().startswith(self.original))
        restarted = GraphService(self.root)
        evidence = views.all_evidence(restarted)
        snippet = next(s for s in evidence if s['iri'] == result['snippets'][0])
        self.assertEqual(snippet['exactText'], payload['snippets'][0]['exactText'])
        self.assertEqual(snippet['document']['iri'], document['iri'])
        self.assertEqual(snippet['confidenceBand'], 'review pending')
        claim = snippet['supports'][0]['value']
        self.assertEqual(views.evidence_for(restarted, claim)[0]['iri'], snippet['iri'])
        self.assertIn((A.CommonwealthBank, A.hasStatement, Namespace('')[claim]), restarted.graph)
        query = (EXPLORER.parent / 'queries/persona-organisation.rq').read_text()
        answer = restarted.run_local(query)
        self.assertTrue(answer.ok, answer.error)
        self.assertTrue(any(any(cell and cell['value'] == claim for cell in row) for row in answer.rows))
        self.assertIn(claim, views.evidence_index(restarted))
        self.assertTrue(any(c['iri'] == str(A.GovernanceStatement) and c['totalInstances'] > 0
                            for c in restarted.classes.values()))

    def test_add_snippets_to_existing_document_and_support_existing_record(self):
        """Check that add snippets to existing document and support existing record."""
        payload = self.payload()
        payload['snippets'] = []
        saved = corpus.save_document(self.service, payload)
        policy = self.service.graph.value(A.CommonwealthBank, A.hasGovernancePolicy)
        spec = self.payload()['snippets'][0]
        spec['target'] = {'iri': str(policy)}
        result = corpus.add_snippets(self.service, saved['document']['iri'], {
            'owner': payload['owner'], 'snippets': [spec, deepcopy(spec)]})
        restarted = GraphService(self.root)
        snippets = views.evidence_for(restarted, str(policy))
        self.assertTrue(set(result['snippets']).issubset({s['iri'] for s in snippets}))
        self.assertEqual(len(self.archives()), 1)
        self.assertTrue(all(s['document']['iri'] == saved['document']['iri']
                            for s in snippets if s['iri'] in result['snippets']))

    def test_policy_and_framework_links_reach_competency_queries(self):
        """Check that policy and framework links reach competency queries."""
        payload = self.payload()
        payload['documentClass'] = str(A.FirmAIGovernanceDisclosure)
        framework = next(self.service.graph.subjects(RDF.type, A.RegulatoryFramework))
        payload['snippets'][0]['target'] = {
            'classIri': str(A.AIGovernancePolicy), 'label': 'Test policy',
            'details': {str(A.policyURL): 'https://example.invalid/policy'},
            'links': [{'property': str(A.hasGovernancePolicy), 'direction': 'in', 'target': '@owner'},
                      {'property': str(A.referencesFramework), 'direction': 'out', 'target': str(framework)}],
        }
        saved = corpus.save_document(self.service, payload)
        self.assertIn((A.CommonwealthBank, A.hasGovernanceDisclosure, Namespace('')[saved['document']['iri']]), self.service.graph)
        for name in ('cq01-formal-ai-governance-policy.rq', 'cq07-frameworks-referenced-by-policy.rq'):
            result = self.service.run_local((EXPLORER.parent / 'queries' / name).read_text())
            self.assertTrue(result.ok, result.error)
            self.assertTrue(any(any(c and c['value'] == 'Test policy' for c in row)
                                or any(c and c['value'].startswith(str(A.CorpusRecord_)) for c in row)
                                for row in result.rows))

    def test_new_organisation_is_created_and_connected(self):
        """Check that new organisation is created and connected."""
        payload = self.payload()
        payload['owner'] = {'classIri': str(A.FinancialInstitution), 'label': 'Test institution', 'jurisdiction': 'AU'}
        payload['documentClass'] = str(A.FirmAIGovernanceDisclosure)
        saved = corpus.save_document(self.service, payload)
        node = Namespace('')[saved['owner']]
        self.assertIn((node, RDF.type, A.FinancialInstitution), self.service.graph)
        self.assertIn((node, A.jurisdiction, Literal('AU')), self.service.graph)
        self.assertTrue(list(self.service.graph.objects(node, A.hasStatement)))
        self.assertTrue(list(self.service.graph.objects(node, A.hasGovernanceDisclosure)))

    def test_invalid_links_or_quotes_never_save_partial_data(self):
        """Check that invalid links or quotes never save partial data."""
        invalid = []
        p = self.payload(); p['snippets'][0]['target']['links'][0]['property'] = str(A.hasGovernancePolicy); invalid.append(p)
        p = self.payload(); p['snippets'][0]['exactText'] = ''; invalid.append(p)
        p = self.payload(); p['owner'] = {'iri': str(A.DoesNotExist)}; invalid.append(p)
        p = self.payload(); p['snippets'][0]['target']['links'] = []; invalid.append(p)
        p = self.payload(); p['snippets'][0]['target']['details'][str(A.usesTerminology)] = 'inapplicable'; invalid.append(p)
        p = self.payload(); p['snippets'][0]['pageReference'] = 'PDF page 0'; invalid.append(p)
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    corpus.save_document(self.service, payload)
                self.assertEqual(self.service.ontology.read_text(), self.original)
                self.assertFalse(self.archives())

    def test_pdf_validation_and_cited_page_bounds(self):
        from pypdf import PdfWriter
        payload = self.payload()
        upload = payload['file']
        upload.update(name='source.pdf', content=base64.b64encode(b'%PDF-invalid').decode())
        with self.assertRaisesRegex(ValueError, 'PDF could not be opened'):
            corpus.save_document(self.service, payload)
        buffer = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(buffer)
        upload['content'] = base64.b64encode(buffer.getvalue()).decode()
        snippet = payload['snippets'][0]
        snippet['pageReference'] = 'PDF page 2'
        with self.assertRaisesRegex(ValueError, 'PDF page from 1 to 1'):
            corpus.save_document(self.service, payload)
        self.assertFalse(self.archives())
        snippet['pageReference'] = 'PDF page 1'
        saved = corpus.save_document(self.service, payload)
        snippet['pageReference'] = 'Not paginated'
        with self.assertRaisesRegex(ValueError, 'PDF page'):
            corpus.add_snippets(self.service, saved['document']['iri'], payload)

    def test_filename_is_confined_and_duplicate_upload_is_rejected(self):
        """Check that filename is confined and duplicate upload is rejected."""
        payload = self.payload()
        payload['file']['name'] = '../../' + 'x' * 180 + '.html'
        saved = corpus.save_document(self.service, payload)
        path = (self.root / saved['document']['localPath']).resolve()
        self.assertTrue(path.is_relative_to(self.root / 'corpus' / 'uploads'))
        self.assertEqual(path.suffix, '.html')
        before = self.service.ontology.read_text()
        with self.assertRaisesRegex(ValueError, 'already in the corpus'):
            corpus.save_document(self.service, payload)
        self.assertEqual(self.service.ontology.read_text(), before)
        self.assertEqual(len(self.archives()), 1)

    def test_failed_commit_rolls_back_the_new_archive(self):
        """Check that failed commit rolls back the new archive."""
        with patch('app.corpus.os.replace', side_effect=OSError('test disk failure')):
            with self.assertRaises(OSError):
                corpus.save_document(self.service, self.payload())
        self.assertEqual(self.service.ontology.read_text(), self.original)
        self.assertFalse(self.archives())

    def test_concurrent_external_edit_is_preserved(self):
        """Check that concurrent external edit is preserved."""
        create_temp = tempfile.NamedTemporaryFile
        # The temporary-file hook places the edit between the read and commit.
        def edit_before_commit(*args, **kwargs):
            """Simulate an external edit before the corpus commit."""
            self.service.ontology.write_text(self.original + '\n# Concurrent external edit\n')
            return create_temp(*args, **kwargs)
        with patch('app.corpus.tempfile.NamedTemporaryFile', side_effect=edit_before_commit):
            with self.assertRaisesRegex(ValueError, 'changed while saving'):
                corpus.save_document(self.service, self.payload())
        self.assertEqual(self.service.ontology.read_text(), self.original + '\n# Concurrent external edit\n')
        self.assertFalse(self.archives())

    def test_concurrent_additions_do_not_overwrite_each_other(self):
        """Check that concurrent additions do not overwrite each other."""
        payloads = [self.payload(f'Independent statement {i}') for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda p: corpus.save_document(self.service, p), payloads))
        restarted = GraphService(self.root)
        self.assertEqual(len(self.archives()), 4)
        self.assertTrue(all(views.document_record(restarted, r['document']['iri'])['exists'] for r in results))
        self.assertTrue(all((Namespace('')[r['snippets'][0]], RDF.type, A.EvidenceSnippet) in restarted.graph for r in results))

    def test_independent_services_serialize_duplicate_uploads(self):
        other = GraphService(self.root)
        payload = self.payload()

        def save(service):
            try:
                corpus.save_document(service, payload)
            except ValueError as exc:
                return str(exc)
            return 'saved'

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(save, [self.service, other]))
        self.assertEqual(outcomes.count('saved'), 1)
        self.assertTrue(any('already in the corpus' in outcome for outcome in outcomes))
        self.assertEqual(len(self.archives()), 1)

    def test_query_api_rejects_invalid_json_shape_and_cross_origin_reads(self):
        for payload in ([], {'sparql': 123}, {'sparql': ''}):
            self.assertEqual(self.request('POST', '/api/query', payload)[0], 400)
        for endpoint in ('/api/query', '/api/builder-options', '/api/reload'):
            self.assertEqual(self.request('POST', endpoint, {'sparql': 'ASK {}'},
                                         origin='https://example.invalid')[0], 400)

    def test_open_card_runs_current_query_file(self):
        pack = self.root / 'queries'
        pack.mkdir()
        with patch('app.questions.QUERY_DIR', pack):
            query = pack / 'changing.rq'
            for word in ('old', 'new'):
                query.write_text(f'# {word} question\nSELECT ("{word}" AS ?word) WHERE {{}}')
                status, response = self.request('POST', '/api/query', {'questionId': 'changing'})
                self.assertEqual(status, 200)
                self.assertEqual(response['result']['rows'][0][0]['value'], word)
                self.assertEqual(response['question']['question'], word + ' question')
            query.unlink()
            self.assertEqual(self.request('POST', '/api/query', {'questionId': 'changing'})[0], 404)

    def test_api_creation_refreshes_documents_and_query_results(self):
        """Check that api creation refreshes documents and query results."""
        status, saved = self.request('POST', '/api/corpus/documents', self.payload(), origin='http://127.0.0.1:8042')
        self.assertEqual(status, 201, saved)
        status, result = self.request('GET', '/api/documents')
        self.assertEqual(status, 200)
        self.assertIn(saved['document']['iri'], {doc['iri'] for doc in result['documents']})
        status, result = self.request('POST', '/api/query', {'sparql':
            f'SELECT ?quote WHERE {{ <{saved["snippets"][0]}> <{A.exactText}> ?quote }}'})
        self.assertEqual(status, 200)
        self.assertTrue(result['result']['ok'], result)
        self.assertEqual(result['result']['count'], 1)
        status, options = self.request('GET', '/api/corpus/options')
        self.assertEqual(status, 200)
        self.assertTrue(options['owners'])
        self.assertTrue(options['properties'])

    def test_api_rejects_cross_origin_and_non_json_writes(self):
        """Check that api rejects cross origin and non json writes."""
        for kwargs in ({'origin': 'https://unrelated.example'}, {'content_type': 'text/plain'}):
            status, error = self.request('POST', '/api/corpus/documents', self.payload(), **kwargs)
            self.assertEqual(status, 400, error)
            self.assertEqual(self.service.ontology.read_text(), self.original)
            self.assertFalse(self.archives())


if __name__ == '__main__':
    unittest.main()
