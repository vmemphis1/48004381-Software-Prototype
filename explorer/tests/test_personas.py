"""Guard the new evidence paths and prevent validation from accepting partial quotes."""
from pathlib import Path
import sys
import unittest
from rdflib import Graph, Namespace, RDF, RDFS
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_evidence_text import ArchiveText, contains, normalise
A = Namespace('https://w3id.org/ai-finance-governance#')

class EvidenceMatchingTests(unittest.TestCase):
    def test_rejects_true_prefix_with_invented_tail(self):
        """Check that rejects true prefix with invented tail."""
        self.assertFalse(contains('the bank tests its ai models before use', 'the bank tests its ai models before use and guarantees no unfair outcomes'))
    def test_ellipsis_must_be_ordered(self):
        """Check that ellipsis must be ordered."""
        self.assertTrue(contains('first clause then second clause', 'first clause ... second clause'))
        self.assertFalse(contains('second clause then first clause', 'first clause ... second clause'))
    def test_empty_is_not_evidence(self):
        """Check that empty is not evidence."""
        self.assertFalse(contains('some source', ''))
        self.assertFalse(contains('some source', '... …'))
    def test_html_verifier_excludes_hidden_evidence(self):
        parser = ArchiveText()
        parser.feed('<head><title>Unseen</title></head><body><div hidden><b>Secret</b></div>'
                    '<p>Visible <em>quote</em>.</p><script>invented tail</script></body>')
        text = normalise(' '.join(parser.parts))
        self.assertTrue(contains(text, 'visible quote.'))
        for hidden in ('secret', 'unseen', 'invented tail'):
            self.assertFalse(contains(text, hidden))

    def test_layout_normalisation_is_retained(self):
        """Check that layout normalisation is retained."""
        self.assertTrue(contains(normalise('pre-\ndeployment  testing'), normalise('predeployment testing')))

class EvidenceStatusTests(unittest.TestCase):
    def test_review_pending_is_not_confidence_rating(self):
        """Check that review pending is not confidence rating."""
        sys.path.insert(0, str(ROOT / 'explorer'))
        from app.views import _confidence_band
        self.assertEqual(_confidence_band('Source text matched; AI-assisted curation; independent researcher review pending'), 'review pending')
        self.assertEqual(_confidence_band('high - manually verified'), 'high')

class PersonaEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load shared fixtures for this test class."""
        cls.g = Graph().parse(ROOT / 'ontology/ai-finance-governance.ttl')
    def test_submission_and_report_do_not_become_policy_references(self):
        """Check that submission and report do not become policy references."""
        self.assertNotIn((A.ANZGuardrailsSubmission2024,RDF.type,A.AIGovernancePolicy),self.g)
        self.assertFalse(list(self.g.objects(A.NAB2025AnnualReport,A.referencesFramework)))
        rows = self.g.query((ROOT/'queries/cq07-frameworks-referenced-by-policy.rq').read_text())
        self.assertFalse(any(row.policyLabel in {self.g.value(node, RDFS.label) for node in
                             (A.ANZGuardrailsSubmission2024, A.NAB2025AnnualReport)} for row in rows))
    def test_important_qualifiers_survive(self):
        """Check that important qualifiers survive."""
        quote=str(self.g.value(A.JPMorganApproval2025Evidence,A.exactText))
        self.assertIn('exceptions may be granted',quote)
        self.assertIn('20 March 2026',str(self.g.value(A.MASConsultationStatusStatement,A.statementText)))
    def test_richer_evidence_reaches_existing_competency_paths(self):
        """Check that richer evidence reaches existing competency paths."""
        self.assertIn((A.CommonwealthBank,A.hasGovernanceBody,A.CBAAIRiskCommittee2025),self.g)
        self.assertIn((A.CBAAISystemDefinition,A.statedBy,A.CommonwealthBank),self.g)
        rows = self.g.query((ROOT/'queries/cq08-high-risk-vocabulary.rq').read_text())
        self.assertTrue({A.EUAIActHighRiskEvidence, A.JPMorganTiering2025Evidence}
                        <= {row.evidence for row in rows})

if __name__ == '__main__': unittest.main()
