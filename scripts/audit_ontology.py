#!/usr/bin/env python3
"""Run structural and provenance checks on the populated ontology."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef


ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology" / "ai-finance-governance.ttl"
ORSD = ROOT / "ontology" / "ORSD.md"
QUERY_DIR = ROOT / "queries"
AIRO_FILE = ROOT / "ontology" / "airo.ttl"




FIBO_MODULE_IRI = URIRef(
    "https://spec.edmcouncil.org/fibo/ontology/FBC/FunctionalEntities/FinancialServicesEntities/"
)
FIBO_MODULE_SHA256 = "f1047cce38f164b6f49bd6c21a340073f0168ff1b36a491e1556b79ad7d6d0da"

ONTOLOGY_IRI = URIRef("https://w3id.org/ai-finance-governance")
AFG = Namespace("https://w3id.org/ai-finance-governance#")
AIRO = Namespace("https://w3id.org/airo#")
FIBO_FSE = Namespace(
    "https://spec.edmcouncil.org/fibo/ontology/FBC/FunctionalEntities/FinancialServicesEntities/"
)

FIRMS = (
    AFG.ANZ,
    AFG.CommonwealthBank,
    AFG.GoldmanSachs,
    AFG.HSBC,
    AFG.JPMorganChase,
    AFG.NAB,
    AFG.Westpac,
)


def require(condition: bool, message: str, errors: list[str]) -> None:
    """Add an audit error when a required condition is false."""
    if not condition:
        errors.append(message)


def sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_name(value: URIRef) -> str:
    """Return the local name of an RDF IRI."""
    return str(value).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def unpopulated_local_classes(graph: Graph) -> set[URIRef]:
    """Return local classes with no direct or subclass instances."""
    classes = {
        value
        for value in graph.subjects(RDF.type, OWL.Class)
        if isinstance(value, URIRef) and str(value).startswith(str(AFG))
    }
    children: dict[URIRef, set[URIRef]] = {value: set() for value in classes}
    for child in classes:
        for parent in graph.objects(child, RDFS.subClassOf):
            if parent in classes:
                children[parent].add(child)

    def descendants(value: URIRef) -> set[URIRef]:
        """Find all subclasses reachable from a class."""
        found = {value}
        for child in children[value]:
            found.update(descendants(child))
        return found

    return {
        value
        for value in classes
        if not any(
            True
            for member in descendants(value)
            for _ in graph.subjects(RDF.type, member)
        )
    }


def check_competency_question_coverage(errors: list[str]) -> int:
    """Every competency question in ORSD section 8 must have a query file.

    A question with no query file silently drops out of the evaluation. One that
    returns nothing is still accounted for, because its file records why.
    """
    text = ORSD.read_text()
    section = text.split("## 8. Competency Questions", 1)[-1].split("## 9.", 1)[0]
    numbers = [
        int(match.group(1))
        for match in re.finditer(r"^(\d+)\.\s+\S", section, flags=re.MULTILINE)
    ]
    require(bool(numbers), "No competency questions found in ORSD section 8", errors)

    for number in numbers:
        matches = list(QUERY_DIR.glob(f"cq{number:02d}-*.rq"))
        require(
            bool(matches),
            f"Competency question {number} has no query file (expected queries/cq{number:02d}-*.rq)",
            errors,
        )

    for path in sorted(QUERY_DIR.glob("cq*.rq")):
        match = re.match(r"cq(\d+)-", path.name)
        if match:
            require(
                int(match.group(1)) in numbers,
                f"Query file has no matching ORSD competency question: {path.name}",
                errors,
            )
    return len(numbers)


def main() -> int:
    """Audit ontology structure, sources, and competency-question coverage."""
    errors: list[str] = []
    graph = Graph().parse(ONTOLOGY, format="turtle")
    airo = Graph().parse(AIRO_FILE, format="turtle")

    for invalid in (AIRO.AIRisk, AIRO.HighRiskAI, AIRO.ConformityAssessment):
        require(
            not any(invalid in triple for triple in graph),
            f"Obsolete/non-existent AIRO term still used: {invalid}",
            errors,
        )

    for imported_class in (AIRO.Risk, AIRO.AISystem):
        require(
            (imported_class, RDF.type, OWL.Class) in airo,
            f"AIRO class is not defined in the local AIRO copy: {imported_class}",
            errors,
        )


    require(
        (FIBO_FSE.FinancialInstitution, RDF.type, OWL.Class) in graph,
        "FIBO FinancialInstitution is not declared as a local external reference",
        errors,
    )
    require(
        (
            AFG.FinancialInstitution,
            RDFS.subClassOf,
            FIBO_FSE.FinancialInstitution,
        )
        in graph,
        "FIBO alignment axiom is missing on :FinancialInstitution",
        errors,
    )
    require(
        (FIBO_FSE.FinancialInstitution, RDFS.isDefinedBy, FIBO_MODULE_IRI) in graph,
        "FIBO external reference is missing rdfs:isDefinedBy provenance",
        errors,
    )
    require(
        FIBO_MODULE_SHA256
        in {str(value) for value in graph.objects(FIBO_FSE.FinancialInstitution, AFG.sha256)},
        "FIBO external reference is missing the source module checksum",
        errors,
    )
    fibo_imports = {
        str(value)
        for value in graph.objects(ONTOLOGY_IRI, OWL.imports)
        if "edmcouncil.org" in str(value)
    }
    require(
        not fibo_imports,
        f"FIBO owl:imports reintroduced, which reverses the mapping-only decision: {sorted(fibo_imports)}",
        errors,
    )
    require(
        (ONTOLOGY_IRI, OWL.imports, URIRef("https://w3id.org/airo")) in graph,
        "AIRO owl:imports is missing",
        errors,
    )
    require(
        (
            ONTOLOGY_IRI,
            OWL.versionIRI,
            URIRef("https://w3id.org/ai-finance-governance/1.6"),
        )
        in graph,
        "Version 1.6 persistent version IRI is missing",
        errors,
    )

    for removed in (
        AFG.AIUseCase,
        AFG.HallucinationRisk,
        AFG.ThirdPartyAIRisk,
        AFG.governsUseCase,
    ):
        require(
            not any(removed in triple for triple in graph),
            f"Removed unsupported term was reintroduced: {local_name(removed)}",
            errors,
        )

    expected_requirements = (
        (
            AFG.EU_AI_Act,
            AFG.requiresDataGovernance,
            AFG.EUAIActArticle10DataGovernance,
        ),
        (
            AFG.EU_AI_Act,
            AFG.requiresHumanOversight,
            AFG.EUAIActArticle14HumanOversight,
        ),
        (
            AFG.EU_AI_Act,
            AFG.requiresConformityAssessment,
            AFG.EUAIActArticle43ConformityAssessment,
        ),
    )
    for triple in expected_requirements:
        require(
            triple in graph,
            f"Missing EU AI Act process requirement: {local_name(triple[1])}",
            errors,
        )

    require(
        (
            AFG.HSBCPrinciplesEthicalUseOfDataAndAI,
            AFG.embodiesPrinciple,
            AFG.HSBCObservedExplainability,
        )
        in graph,
        "HSBC explainability principle is not linked to the published policy",
        errors,
    )

    empty_classes = unpopulated_local_classes(graph)
    expected_empty_classes = {AFG.AISystem, AFG.HighRiskAISystem}
    require(
        empty_classes == expected_empty_classes,
        "Unexpected unpopulated local classes: "
        + ", ".join(sorted(local_name(value) for value in empty_classes)),
        errors,
    )

    for firm in FIRMS:
        require(
            (firm, RDF.type, AFG.FinancialInstitution) in graph,
            f"Missing FinancialInstitution type: {local_name(firm)}",
            errors,
        )
        require(
            any(graph.objects(firm, AFG.jurisdiction)),
            f"Missing jurisdiction: {local_name(firm)}",
            errors,
        )
        require(
            any(graph.objects(firm, AFG.hasGovernanceDisclosure)),
            f"Missing firm disclosure link: {local_name(firm)}",
            errors,
        )

    source_documents = set(graph.subjects(RDF.type, AFG.SourceDocument)) | set(
        graph.subjects(RDF.type, AFG.FirmAIGovernanceDisclosure)
    )
    for document in source_documents:
        paths = list(graph.objects(document, AFG.localPath))
        require(bool(paths), f"Missing local path: {local_name(document)}", errors)
        require(
            any(graph.objects(document, AFG.documentURL)),
            f"Missing official URL: {local_name(document)}",
            errors,
        )
        require(
            any(graph.objects(document, AFG.sha256)),
            f"Missing checksum: {local_name(document)}",
            errors,
        )
        if not paths:
            continue
        path = ROOT / str(paths[0])
        require(path.is_file(), f"Source file not found: {path}", errors)
        if path.is_file():
            recorded = {str(value) for value in graph.objects(document, AFG.sha256)}
            require(
                sha256(path) in recorded,
                f"Checksum mismatch: {local_name(document)}",
                errors,
            )

    evidence = set(graph.subjects(RDF.type, AFG.EvidenceSnippet))
    for item in evidence:
        for predicate, label in (
            (AFG.extractedFrom, "source"),
            (AFG.pageReference, "page reference"),
            (AFG.confidenceLevel, "confidence"),
            (AFG.extractionDate, "extraction date"),
            (AFG.supportsAssertion, "supported assertion"),
        ):
            require(
                any(graph.objects(item, predicate)),
                f"Evidence missing {label}: {local_name(item)}",
                errors,
            )

    terminology = set(graph.subjects(RDF.type, AFG.TerminologyUsage))
    for item in terminology:
        for predicate, label in (
            (AFG.usedByActor, "actor"),
            (AFG.observedInDocument, "source document"),
            (AFG.usesTerminology, "exact term"),
            (AFG.denotesConcept, "mapped concept instance"),
            (AFG.hasEvidence, "evidence"),
        ):
            require(
                any(graph.objects(item, predicate)),
                f"Terminology usage missing {label}: {local_name(item)}",
                errors,
            )

    local_prefix = str(AFG)
    local_objects = {
        value
        for _, _, value in graph
        if isinstance(value, URIRef) and str(value).startswith(local_prefix)
    }
    for value in local_objects:
        require(
            any(graph.triples((value, None, None))),
            f"Referenced local resource has no definition: {value}",
            errors,
        )

    query_sets = {
        "firms_with_disclosures": set(
            graph.subjects(AFG.hasGovernanceDisclosure, None)
        ),
        "firms_with_published_ai_policy": set(
            graph.subjects(AFG.hasGovernancePolicy, None)
        ),
        "firms_with_approval_process": set(
            graph.subjects(AFG.hasApprovalProcess, None)
        ),
        "firms_with_governance_body": set(
            graph.subjects(AFG.hasGovernanceBody, None)
        ),
    }

    question_count = check_competency_question_coverage(errors)
    print(
        f"PASS coverage: {question_count} competency questions, "
        f"{len(list(QUERY_DIR.glob('cq*.rq')))} matching query files"
    )
    print(f"PASS parse: {len(graph)} triples")
    print(
        "PASS schema: "
        f"{len(set(graph.subjects(RDF.type, OWL.Class)))} classes, "
        f"{len(set(graph.subjects(RDF.type, OWL.ObjectProperty)))} object properties, "
        f"{len(set(graph.subjects(RDF.type, OWL.DatatypeProperty)))} data properties"
    )
    print(
        f"PASS population: {len(FIRMS)} firms, {len(source_documents)} source documents, "
        f"{len(evidence)} evidence snippets, {len(terminology)} terminology usages"
    )
    print(
        "PASS scope: intentional zero-instance classes -> "
        + ", ".join(sorted(local_name(value) for value in empty_classes))
    )
    for name, values in query_sets.items():
        labels = sorted(local_name(value) for value in values)
        print(f"QUERY {name}: {len(values)} -> {', '.join(labels) or '(none)'}")

    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS all structural and provenance checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
