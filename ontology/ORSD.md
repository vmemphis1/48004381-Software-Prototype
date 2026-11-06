# Ontology Requirements Specification Document

## 1. Purpose

The purpose of this ontology is to provide a machine-interpretable vocabulary for AI governance terminology in the financial sector. The ontology will represent key concepts, relationships, and instances used by regulators and financial institutions when describing AI safety, compliance, risk management, and governance obligations.

The ontology is intended to support a knowledge graph that can be queried to compare how firms and regulatory frameworks describe equivalent AI governance concepts. The main research problem is terminology divergence: different firms and regulators often use different terms for the same or closely related concepts, making cross-firm comparison and automated compliance analysis difficult.

## 2. Scope

### 2.1 Domain

The domain is AI governance in financial services, with emphasis on AI safety, compliance, risk, explainability, model governance, third-party AI governance, and firm-level AI oversight.

### 2.2 In Scope

- Regulatory and standards frameworks relevant to AI governance in financial services.
- Publicly available AI governance, annual report, sustainability, ESG, and risk disclosures from selected financial institutions.
- Core AI governance terminology used by regulators and firms.
- Synonyms and terminology mappings across regulators, standards, and financial institutions.
- Named individuals for selected regulatory frameworks and financial institutions.
- Object and datatype properties needed to answer the competency questions.
- Alignment with existing ontologies where appropriate, especially AIRO and FIBO.

### 2.3 Out of Scope

- Non-public internal policies or confidential firm data.
- Direct assessment of whether a firm is legally compliant.
- Full coverage of all financial institutions globally.
- Full representation of all financial instruments, contracts, or corporate entity structures already covered by FIBO.
- Real-time monitoring of regulatory changes.
- Formal legal advice or enforceable compliance certification.

## 3. Intended Users

- The researcher, for thesis development and knowledge graph evaluation.
- The project supervisor, for reviewing scope, methodology, and progress.
- Academic reviewers interested in AI governance, regulatory technology, and knowledge graphs.
- Financial-sector compliance analysts who need to compare terminology across firms and frameworks.
- Software agents or query tools that need a formal vocabulary for AI governance concepts.
- Citizens who would like to inspect a financial firm's AI policies before opening an account.
- Regulators who wish to familiarise themselves with the vocabulary firms and other regulators use.

## 4. Intended Uses

The ontology will be used to:

- Structure a glossary of AI governance terms.
- Map firm-level terminology to regulatory concepts.
- Represent selected firms and regulatory frameworks as named individuals.
- Populate a knowledge graph from public firm disclosures and regulatory documents.
- Support SPARQL query mechanisms.
- Test whether the populated knowledge graph can answer the defined competency questions.
- Identify cross-firm and cross-jurisdictional terminology alignment patterns.

## 5. Level of Formality

The ontology will use a semi-formal to formal OWL representation:

- Natural-language definitions are captured using `rdfs:comment`, `dcterms:description`, and glossary entries.
- Preferred labels use `rdfs:label`.
- Synonyms and alternative terminology use `skos:altLabel`.
- Core concepts are represented as `owl:Class`.
- Firms and regulatory frameworks are represented as `owl:NamedIndividual`.
- Relationships are represented as `owl:ObjectProperty` and `owl:DatatypeProperty`.
- Existing ontology alignment is represented through `owl:imports`, `rdfs:subClassOf`, and `owl:equivalentClass` where justified.

The ontology uses `https://w3id.org/ai-finance-governance#` as its base IRI.

## 6. Knowledge Sources

### 6.1 Regulatory and Standards Sources

- EU AI Act, Regulation (EU) 2024/1689.
- Australia's AI Ethics Principles, Department of Industry, Science and Resources.
- NIST AI Risk Management Framework 1.0 and its Generative AI Profile.
- APRA CPG 234 Information Security.
- ASIC RG 271 Internal Dispute Resolution and ASIC REP 798, where relevant to AI governance.
- OAIC guidance on commercial AI and privacy.
- Australian guidance for AI adoption.
- MAS's proposed AI Risk Management Guidelines and the archived 20 March 2026 release on the AI risk toolkit. The release records consultation responses under review; it does not establish the guidelines' later status.
- ISO/IEC 42001:2023 AI management systems.
- ISO/IEC 23894:2023 AI risk management.
- FSB work on financial stability implications of AI.

### 6.2 Firm Disclosure Sources

The initial firm sample covers seven institutions:

- Commonwealth Bank of Australia.
- National Australia Bank.
- Westpac Banking Corporation.
- ANZ Banking Group.
- JPMorgan Chase & Co.
- Goldman Sachs Group, Inc.
- HSBC Holdings plc.

Relevant document types include AI policies, annual reports, sustainability reports, ESG reports, responsible business reports, and risk disclosures.

### 6.3 Academic and Ontology Sources

- Noy and McGuinness, Ontology Development 101.
- Fernandez-Lopez et al., METHONTOLOGY.
- Iqbal et al., comparison of ontology development methodologies.
- AIRO, the AI Risks Ontology.
- FIBO, the Financial Industry Business Ontology.
- Literature on AI governance, regulatory standardisation, algorithmic audit, and knowledge graphs for regulatory compliance.

## 7. Existing Ontology Reuse Decisions

### 7.1 AIRO

AIRO is reused as the main base ontology for AI risk concepts. The ontology imports AIRO using:

```turtle
owl:imports <https://w3id.org/airo> ;
```

The reused classes are:

- `airo:Risk`
- `airo:AISystem`

AIRO is not sufficient on its own because it does not provide financial-sector firm concepts, firm-level governance bodies, cross-jurisdictional regulatory comparison, or disclosure-specific terminology mappings.

### 7.2 FIBO

FIBO is identified for reuse where financial entity concepts are needed. Relevant modules include:

- FND: Foundations.
- BE: Business Entities.
- FBC: Financial Business and Commerce.

FIBO is reused **by mapping rather than by import**.

Only one FIBO term is actually reused: `fibo-fbc-fct-fse:FinancialInstitution`.

The term is declared locally as a minimal external reference, following the MIREOT
pattern of importing only the terms actually needed. The declaration carries the
authoritative FIBO label and definition, `rdfs:isDefinedBy`, the source module IRI, the
retrieval date, and the SHA-256 checksum of the FIBO module the definition was taken
from.

`scripts/audit_ontology.py` enforces this: it checks the declaration, the alignment
axiom, the provenance annotations, and that no FIBO `owl:imports` has been reintroduced.

AIRO is small and remains a normal `owl:imports`, with `airo.ttl` loaded alongside the
main file.

FIBO is not sufficient on its own because it does not model AI-specific governance, safety, explainability, or AI risk concepts.

### 7.3 New Concepts Required

The project must define financial AI governance concepts not directly available in AIRO or FIBO, including:

- AI governance policy.
- AI governance body.
- Model risk as used in financial institutions.
- Explainability obligation.
- Third-party AI governance.
- AI deployment approval process.
- Risk tier.
- Firm-to-framework terminology mappings.

## 8. Competency Questions

The ontology and populated knowledge graph must be able to answer the following competency questions:

1. Which financial firms operating in Australia have published a formal AI governance policy?
2. What term does each firm use to describe the risk that an AI model behaves unexpectedly, such as model risk, algorithmic risk, AI risk, or model governance risk?
3. Which regulatory frameworks explicitly require an AI explainability obligation for firms operating in the Australian financial sector?
4. How does a firm's stated definition of AI align with the definition in the EU AI Act, the NIST AI RMF, and the Australian government's AI Ethics Principles?
5. Which firms describe an internal review or approval process before deploying an AI system?
6. What governance body, such as a board committee or risk committee, is responsible for AI oversight at each firm?
7. Which international AI governance frameworks are explicitly referenced in each firm's AI policy?
8. Is there a common vocabulary for high-risk AI across regulators and firms, or do firms use their own risk tiering language?
9. Which firms explicitly address third-party AI vendor governance?
10. How do the terms used by Australian firms compare with those used by European and US counterparts for the same governance concepts?

## 9. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Represent regulatory frameworks as named individuals. | Must |
| FR-02 | Represent financial institutions as named individuals. | Must |
| FR-03 | Represent core AI governance concepts as OWL classes. | Must |
| FR-04 | Represent firm-to-framework relationships. | Must |
| FR-05 | Represent governance policies, governance bodies, and approval processes. | Must |
| FR-06 | Capture terminology divergence using labels, alternative labels, and mappings. | Must |
| FR-07 | Support queries over firms, frameworks, governance policies, and risk terminology. | Must |
| FR-08 | Support later population with evidence extracted from public documents. | Must |
| FR-09 | Align AI risk concepts with AIRO where reuse is justified. | Should |
| FR-10 | Align financial institution concepts with FIBO where reuse is justified. | Should |
| FR-11 | Record source URLs or document references for firm-level assertions. | Should |
| FR-12 | Support evaluation against all competency questions. | Must |

## 10. Non-Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| NFR-01 | The ontology must be editable as Turtle in a plain text editor and loadable into a standard RDF store. It is authored in VS Code and queried locally through rdflib and the explorer. | Must |
| NFR-02 | The ontology should use standard RDF, RDFS, OWL, SKOS, and Dublin Core vocabulary where appropriate. | Must |
| NFR-03 | The ontology should remain small enough for iterative manual development during the thesis timeline. | Must |
| NFR-04 | Terms must be traceable to a regulatory source, firm disclosure, or academic source. | Must |
| NFR-05 | The ontology should be modular enough to extend with additional firms and frameworks. | Should |
| NFR-06 | Labels and comments should be human-readable and suitable for thesis presentation. | Should |
| NFR-07 | The ontology should avoid duplicating detailed financial entity modelling already provided by FIBO. | Should |
| NFR-08 | The ontology should avoid overclaiming legal compliance beyond what public documents support. | Must |

## 11. Conceptual Coverage

The populated ontology includes the following:

- Regulatory and reference frameworks: APRA CPG 234, ASIC RG 271 and REP 798, the EU AI Act, NIST AI RMF and its Generative AI Profile, the proposed MAS AI Risk Management Guidelines, ISO/IEC 42001, ISO/IEC 23894, Australia's AI Ethics Principles and AI Adoption Guidance, OAIC AI privacy guidance, and the FSB's 2024 and 2025 AI reports.
- Financial institutions: CBA, NAB, Westpac, ANZ, JPMorgan Chase, Goldman Sachs, and HSBC, each linked to at least one collected governance disclosure.
- Core governance concepts including AI governance policy, AI governance framework, firm AI governance disclosure, model risk, AI governance body, model validation, explainability obligation, third-party AI governance, AI deployment approval process, risk tier, and high-risk AI system.
- Object properties for governance policies, framework references, governance bodies, regulatory applicability, approval processes, and risk classification.
- Datatype properties for jurisdiction, policy URL, source document, extracted term, local path, retrieval date, and SHA-256 checksum.
- Local regulatory and firm source documents with checksums, page- or section-level evidence snippets, and evidence-backed terminology usages.
- Evidence-backed governance bodies for CBA, Goldman Sachs, HSBC, and JPMorgan Chase, and evidence-backed approval/review processes for ANZ, HSBC, and JPMorgan Chase.
- Evidence-backed governance statements with a topic, summary and source status. Topics such as contestability are recorded as text on statements, rather than necessarily as distinct ontology classes; a statement's status describes the source's evidential role and does not establish implementation or compliance.

## 12. Glossary Requirements

The glossary is a human-readable, source-traceable guide to selected AI governance terms and their representation in the ontology. It supports interpretation of terminology differences and the knowledge graph; it is not an exhaustive inventory of every class, property or individual. Its definitions are explanatory and do not on their own assert equivalence between sources.

The glossary must contain, at minimum, the following fields for each entry where the information is available:

- Preferred term.
- Definition.
- Source.
- Type, such as concept, process, relation, or instance.
- Synonyms or alternative terms.
- Mapping to the ontology or an imported ontology.
- Notes on terminology divergence or unresolved scope questions.

`Ontology mapping` records full IRIs for mapped project or imported ontology resources, separated by semicolons when there is more than one. 

## 13. Data and Population Requirements

Each populated firm-level assertion should record:

- The firm.
- The source document or URL.
- The extracted term.
- The mapped ontology concept.
- The regulatory or governance context.
- Any relevant jurisdiction.

## 14. Evaluation Plan

The ontology will be evaluated by:

- Parsing `ai-finance-governance.ttl` and the pinned local `airo.ttl` copy with rdflib.
- Checking the ontology IRI, AIRO alignment, FIBO mapping-only provenance, source-file
  checksums, evidence fields, removed terms, and intentional zero-instance classes with
  `scripts/audit_ontology.py`.
- Testing the populated knowledge graph against all 10 competency questions.
- Reviewing whether terminology mappings are supported by evidence from source documents.
- Revising classes, properties, and mappings where competency questions cannot be answered.

## 15. Deliverables

The ontology work package will produce:

- `ORSD.md`: this requirements specification.
- `terms_v1.csv`: the glossary of terms.
- `ai-finance-governance.ttl`: the OWL/Turtle ontology.
- `queries/`: the SPARQL query pack implementing the competency questions.
- A curated document corpus of regulatory sources and firm disclosures.
- A populated knowledge graph with firm-level instances.
- Query and evaluation results against the competency questions.
- Thesis discussion of terminology divergence and regulatory alignment.

## 16. Assumptions

- Public documents provide enough evidence to identify meaningful firm-level AI governance terminology.
- AIRO is suitable for reuse as a base ontology for AI risk concepts.
- FIBO is suitable for mapping the financial-institution concept without importing its full module closure.
- The selected seven firms provide a sufficient initial comparison set for Australian and international terminology patterns.
- The ontology can remain focused on terminology alignment rather than full legal compliance modelling.

## 17. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Public firm disclosures may not contain enough AI governance detail. | The knowledge graph may be sparse. | Narrow the scope to firms or document types with stronger evidence, or focus more heavily on regulatory terminology. |
| Regulatory terminology may shift during the project. | Definitions and mappings may become stale. | Record source dates and use versioned regulatory documents. |
| Imported ontologies may be large or difficult to load. | Tool performance or import resolution may suffer. | Resolved in version 1.2: FIBO is mapped rather than imported, removing a 75 MB dependency used for one class. AIRO is small enough to import directly. |
| Terminology mappings may be ambiguous. | Incorrect equivalence claims could weaken the analysis. | Prefer `skos:altLabel` or explanatory mappings unless definitional equivalence is well supported. |
| Ontology scope may expand too far. | Thesis timeline may be affected. | Keep all additions traceable to competency questions. |

## 18. Change Control

Changes to the ontology should be made only when they support at least one of the following:

- Answering a competency question.
- Capturing a term found in the glossary or source corpus.
- Reusing or aligning with AIRO or FIBO.
- Correcting an error in class, property, individual, or source representation.
- Improving traceability between firm disclosures, regulatory frameworks, and ontology mappings.

Major changes should update this ORSD, the glossary, and the ontology together so the specification and implementation remain aligned.
