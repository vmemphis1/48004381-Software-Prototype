"""Derived read models: resources, evidence, graph, documents.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS

from .graph_service import AFG, GraphService, curie

ROOT = Path(__file__).resolve().parents[2]

A = lambda name: URIRef(AFG + name)



_PDF_PAGE = re.compile(r"PDF page\s+(\d+)", re.IGNORECASE)

_DOC_MARKER = A("localPath")


def _confidence_band(value: str | None) -> str:
    """`high - manually verified` -> `high`. Used for colour, never for wording."""
    if not value:
        return "unknown"
    match = re.match(r"^(high|medium|low)(?:\s|$)", value, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return "review pending" if "pending" in value.lower() else "unrated"


def parse_pdf_page(page_reference: str | None) -> int | None:
    """Extract the PDF page number from an evidence reference."""
    if not page_reference:
        return None
    match = _PDF_PAGE.search(page_reference)
    return int(match.group(1)) if match else None





def document_record(service: GraphService, iri: str) -> dict[str, Any] | None:
    """A source document with its archived copy, if the IRI is one."""
    node = URIRef(iri)
    local_path = next(service.graph.objects(node, _DOC_MARKER), None)
    if local_path is None:
        return None
    relative = str(local_path)
    absolute = service.root / relative
    suffix = absolute.suffix.lower()
    return {
        "iri": iri,
        "curie": curie(iri),
        "label": service.labels.get(iri, curie(iri)),
        "localPath": relative,
        "exists": absolute.exists(),
        "sizeBytes": absolute.stat().st_size if absolute.exists() else None,
        "format": "pdf" if suffix == ".pdf" else ("html" if suffix in (".html", ".htm") else suffix.lstrip(".")),
        "documentURL": _one(service, node, A("documentURL")),
        "documentType": _one(service, node, A("documentType")),
        "documentDate": _one(service, node, A("documentDate")),
        "retrievalDate": _one(service, node, A("retrievalDate")),
        "sha256": _one(service, node, A("sha256")),
        "relatedResources": sorted({str(s) for predicate in (DCTERMS.source, A('hasGovernanceDisclosure'))
                                    for s in service.graph.subjects(predicate, node)}),
    }


def _one(service: GraphService, subject: URIRef, predicate: URIRef) -> str | None:
    """Return the first value of a predicate as text, if present."""
    value = next(service.graph.objects(subject, predicate), None)
    return str(value) if value is not None else None


def documents(service: GraphService) -> list[dict[str, Any]]:
    """Return the recorded source documents for display."""
    records = []
    for subject in set(service.graph.subjects(_DOC_MARKER, None)):
        record = document_record(service, str(subject))
        if record:
            records.append(record)
    records.sort(key=lambda item: item["label"])
    return records





def evidence_snippet(service: GraphService, iri: str) -> dict[str, Any]:
    """Build the display record for an evidence snippet."""
    node = URIRef(iri)
    page_reference = _one(service, node, A("pageReference"))
    document_iri = next(service.graph.objects(node, A("extractedFrom")), None)
    confidence = _one(service, node, A("confidenceLevel"))
    return {
        "iri": iri,
        "curie": curie(iri),
        "label": service.labels.get(iri, curie(iri)),
        "exactText": _one(service, node, A("exactText")),
        "pageReference": page_reference,
        "pdfPage": parse_pdf_page(page_reference),
        "sectionReference": _one(service, node, A("sectionReference")),
        "confidenceLevel": confidence,
        "confidenceBand": _confidence_band(confidence),
        "extractionDate": _one(service, node, A("extractionDate")),
        "document": document_record(service, str(document_iri)) if document_iri else None,
        "supports": [
            service.describe_term(str(target))
            for target in service.graph.objects(node, A("supportsAssertion"))
        ],
    }


def evidence_for(service: GraphService, iri: str) -> list[dict[str, Any]]:
    """Snippets backing a claim, from either direction of the evidence link.

    `:hasEvidence` points claim -> snippet and `:supportsAssertion` points
    snippet -> claim. The graph uses both, so a one-directional lookup would
    silently drop provenance that is genuinely present.
    """
    node = URIRef(iri)
    found: dict[str, dict[str, Any]] = {}
    for snippet in service.graph.objects(node, A("hasEvidence")):
        found[str(snippet)] = evidence_snippet(service, str(snippet))
    for snippet in service.graph.subjects(A("supportsAssertion"), node):
        found[str(snippet)] = evidence_snippet(service, str(snippet))
    return sorted(found.values(), key=lambda item: item["label"])


def all_evidence(service: GraphService) -> list[dict[str, Any]]:
    """Return display records for all evidence snippets."""
    snippets = [
        evidence_snippet(service, str(subject))
        for subject in set(service.graph.subjects(RDF.type, A("EvidenceSnippet")))
    ]
    snippets.sort(key=lambda item: item["label"])
    return snippets





def _most_specific_types(service: GraphService, node: URIRef) -> list[str]:
    """Drop `owl:NamedIndividual` and any type that a narrower asserted type implies."""
    types = {
        str(t)
        for t in service.graph.objects(node, RDF.type)
        if isinstance(t, URIRef) and t != OWL.NamedIndividual
    }
    specific = set(types)
    for candidate in types:
        for other in types:
            if other == candidate:
                continue
            record = service.classes.get(other)
            if record and candidate in record["parents"]:
                specific.discard(candidate)
    return sorted(specific or types)


def resource(service: GraphService, iri: str) -> dict[str, Any]:
    """Return the details and relationships of a graph resource."""
    node = URIRef(iri)
    outgoing: list[dict[str, Any]] = []
    grouped: dict[str, list[Any]] = {}
    for predicate, obj in service.graph.predicate_objects(node):
        if predicate == RDF.type and obj == OWL.NamedIndividual:
            continue
        grouped.setdefault(str(predicate), []).append(obj)
    for predicate, values in sorted(grouped.items()):
        outgoing.append(
            {
                "predicate": service.describe_term(predicate),
                "values": [service._bind(value) for value in values],
            }
        )

    incoming_grouped: dict[str, list[Any]] = {}
    for subject, predicate in service.graph.subject_predicates(node):
        incoming_grouped.setdefault(str(predicate), []).append(subject)
    incoming = [
        {
            "predicate": service.describe_term(predicate),
            "values": [service._bind(value) for value in values],
        }
        for predicate, values in sorted(incoming_grouped.items())
    ]

    types = _most_specific_types(service, node)
    is_class = (node, RDF.type, OWL.Class) in service.graph
    return {
        "iri": iri,
        "curie": curie(iri),
        "label": service.labels.get(iri, curie(iri)),
        "comment": _one(service, node, RDFS.comment),
        "definition": _one(service, node, URIRef("http://purl.org/dc/terms/description")),
        "types": [service.describe_term(t) for t in types],
        "isClass": is_class,
        "outgoing": outgoing,
        "incoming": incoming,
        "evidence": evidence_for(service, iri),
        "relatedEvidence": related_evidence(service, iri),
        "document": document_record(service, iri),
        "tripleCount": len(outgoing) + len(incoming),
    }





def _node_payload(service: GraphService, iri: str) -> dict[str, Any]:
    """Build the display payload for a graph node."""
    node = URIRef(iri)
    types = _most_specific_types(service, node)
    primary = types[0] if types else None
    return {
        "id": iri,
        "curie": curie(iri),
        "label": service.labels.get(iri, curie(iri)),
        "type": primary,
        "typeLabel": service.labels.get(primary, curie(primary)) if primary else "Untyped",
        "isClass": (node, RDF.type, OWL.Class) in service.graph,
        "hasEvidence": bool(evidence_for(service, iri)),
        "degree": sum(1 for _ in service.graph.predicate_objects(node))
        + sum(1 for _ in service.graph.subject_predicates(node)),
    }


_STRUCTURAL = {str(RDF.type), str(RDFS.subClassOf), str(RDFS.label), str(RDFS.comment)}


def _object_links(service: GraphService, node: URIRef) -> list[tuple[str, str, str]]:
    """Individual-to-individual links, excluding schema scaffolding."""
    links = []
    for predicate, obj in service.graph.predicate_objects(node):
        if not isinstance(obj, URIRef) or str(predicate) in _STRUCTURAL:
            continue
        if str(predicate) not in service.properties:
            continue
        links.append((str(node), str(predicate), str(obj)))
    return links


def graph_view(
    service: GraphService,
    mode: str = "instances",
    focus: str | None = None,
    depth: int = 1,
) -> dict[str, Any]:
    """Nodes and edges for the graph explorer.

    `instances` is the populated knowledge graph, `schema` is the class hierarchy,
    and `focus` is the neighbourhood of one resource expanded to `depth` hops.
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(iri: str) -> None:
        """Add a graph node once."""
        if iri not in nodes:
            nodes[iri] = _node_payload(service, iri)

    def add_edge(subject: str, predicate: str, obj: str) -> None:
        """Add a graph edge between the supplied resources."""
        key = (subject, predicate, obj)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            {
                "id": f"e{len(seen_edges)}",
                "source": subject,
                "target": obj,
                "predicate": predicate,
                "label": service.labels.get(predicate, curie(predicate)),
            }
        )

    if mode == "schema":
        for iri, record in service.classes.items():
            if not iri.startswith(AFG) and record["totalInstances"] == 0:
                continue
            add_node(iri)
        for iri in list(nodes):
            for parent in service.classes.get(iri, {}).get("parents", []):
                add_node(parent)
                add_edge(iri, str(RDFS.subClassOf), parent)
        return {"mode": mode, "nodes": list(nodes.values()), "edges": edges}

    if mode == "focus" and focus:
        frontier = {focus}
        add_node(focus)
        for _ in range(max(1, min(depth, 3))):
            next_frontier: set[str] = set()
            for iri in frontier:
                node = URIRef(iri)
                for subject, predicate, obj in _object_links(service, node):
                    add_node(obj)
                    add_edge(subject, predicate, obj)
                    next_frontier.add(obj)
                for subject, predicate in service.graph.subject_predicates(node):
                    if not isinstance(subject, URIRef):
                        continue
                    if str(predicate) in _STRUCTURAL or str(predicate) not in service.properties:
                        continue
                    add_node(str(subject))
                    add_edge(str(subject), str(predicate), iri)
                    next_frontier.add(str(subject))
            frontier = next_frontier - set()
        return {"mode": mode, "focus": focus, "nodes": list(nodes.values()), "edges": edges}

    for individual in set(service.graph.subjects(RDF.type, OWL.NamedIndividual)):
        add_node(str(individual))
    for iri in list(nodes):
        for subject, predicate, obj in _object_links(service, URIRef(iri)):
            if obj in nodes:
                add_edge(subject, predicate, obj)
    return {"mode": "instances", "nodes": list(nodes.values()), "edges": edges}





def evidence_index(service: GraphService) -> dict[str, list[str]]:
    """Every IRI that has provenance, mapped to its snippets.

    The results table needs to know which cells are evidence-backed before it can
    draw the provenance chip, and asking per row would be one request per cell.
    """
    index: dict[str, list[str]] = {}
    for snippet in set(service.graph.subjects(RDF.type, A("EvidenceSnippet"))):
        for claim in service.graph.objects(snippet, A("supportsAssertion")):
            index.setdefault(str(claim), []).append(str(snippet))
        for claim in service.graph.subjects(A("hasEvidence"), snippet):
            index.setdefault(str(claim), []).append(str(snippet))
    return {iri: sorted(set(snippets)) for iri, snippets in index.items()}


def indirect_evidence_index(service: GraphService) -> dict[str, list[str]]:
    """Evidence recorded one hop away, kept separate from direct provenance.

    CQ2 projects the firm, the term, and the concept -- but the snippet is
    attached to the :TerminologyUsage that ties those three together, not to any
    of them. Without this the headline terminology result would show no route to
    its sources at all. It is a *separate* index rather than an extension of
    `evidence_index` because "this claim is evidenced" and "something linked to
    this claim is evidenced" are different statements, and collapsing them would
    let the interface over-claim.
    """
    direct = evidence_index(service)
    indirect: dict[str, set[str]] = {}
    for claim, snippets in direct.items():
        node = URIRef(claim)
        neighbours: set[str] = set()
        for predicate, obj in service.graph.predicate_objects(node):
            if isinstance(obj, URIRef) and str(predicate) in service.properties:
                neighbours.add(str(obj))
        for subject, predicate in service.graph.subject_predicates(node):
            if isinstance(subject, URIRef) and str(predicate) in service.properties:
                neighbours.add(str(subject))
        for neighbour in neighbours:
            if neighbour in direct:
                continue
            indirect.setdefault(neighbour, set()).update(snippets)
    return {iri: sorted(snippets) for iri, snippets in indirect.items()}


def related_evidence(service: GraphService, iri: str) -> list[dict[str, Any]]:
    """Snippets on directly linked statements, tagged with where they came from."""
    if evidence_for(service, iri):
        return []
    node = URIRef(iri)
    neighbours: dict[str, None] = {}
    for predicate, obj in service.graph.predicate_objects(node):
        if isinstance(obj, URIRef) and str(predicate) in service.properties:
            neighbours[str(obj)] = None
    for subject, predicate in service.graph.subject_predicates(node):
        if isinstance(subject, URIRef) and str(predicate) in service.properties:
            neighbours[str(subject)] = None

    found: dict[str, dict[str, Any]] = {}
    for neighbour in neighbours:
        for snippet in evidence_for(service, neighbour):
            record = dict(snippet)
            record["viaLabel"] = service.labels.get(neighbour, curie(neighbour))
            record["viaIri"] = neighbour
            found[snippet["iri"]] = record
    return sorted(found.values(), key=lambda item: item["label"])


def label_index(service: GraphService) -> dict[str, str]:
    """Unique `rdfs:label` -> IRI, so a label literal can be clicked through.

    Most competency queries project `?firmLabel` rather than `?firm`, which is
    what `queries/README.md` means when it says a query returning only labels is
    not directly clickable. Resolving unambiguous labels back to their resource
    restores the drill-down without editing the query pack the thesis cites.
    Labels shared by more than one resource are dropped rather than guessed at.
    """
    counts: dict[str, list[str]] = {}
    for iri, label in service.labels.items():
        counts.setdefault(label, []).append(iri)
    return {label: iris[0] for label, iris in counts.items() if len(iris) == 1}


def builder_options(service: GraphService, sparql: str) -> dict[str, Any]:
    """Offer only links and literal values used by the current query's bindings.

    One prefix query per step, then indexed triple lookups, rather than a query
    per possible option. Counts always mean distinct starting records. Missing
    fields describe the collected data, not the organisation's actual practice.
    """
    result = service.run_local(sparql)
    if not result.ok:
        raise ValueError(result.error)
    graph = service.graph
    roots = {row[0]["value"] for row in result.rows if row and row[0]}
    nodes = {}
    for column, variable in enumerate(result.columns):
        # Keep the roots associated with each binding so fan-out does not inflate counts.
        subjects: dict[str, set[str]] = {}
        for row in result.rows:
            cell = row[column]
            if cell and cell["type"] == "uri":
                subjects.setdefault(cell["value"], set()).add(row[0]["value"])
        if not subjects:
            continue
        relationships = {}
        fields = {}
        for iri, subject_roots in subjects.items():
            subject = URIRef(iri)
            for prop_iri, prop in service.properties.items():
                objects = list(graph.objects(subject, URIRef(prop_iri)))
                if prop["kind"] == "object":
                    for target in objects:
                        if not isinstance(target, URIRef):
                            continue
                        types = set()
                        for direct in graph.objects(target, RDF.type):
                            types.update(graph.transitive_objects(direct, RDFS.subClassOf))
                        # None offers the relationship without restricting the target class.
                        ranges = [None] + sorted(str(t) for t in types if str(t) in service.classes)
                        for range_iri in ranges:
                            key = (prop_iri, range_iri)
                            entry = relationships.setdefault(key, {
                                "property": prop_iri, "label": prop["label"],
                                "range": range_iri, "roots": set(),
                            })
                            entry["roots"].update(subject_roots)
                else:
                    entry = fields.setdefault(prop_iri, {
                        "property": prop_iri, "label": prop["label"],
                        "present": set(), "absent": set(), "values": {},
                    })
                    literals = [str(obj) for obj in objects if isinstance(obj, Literal)]
                    entry["present" if literals else "absent"].update(subject_roots)
                    for value in literals:
                        entry["values"].setdefault(value, set()).update(subject_roots)
        nodes[variable] = {
            "relationships": sorted([
                {"property": e["property"], "label": e["label"], "range": e["range"],
                 "count": len(e["roots"])} for e in relationships.values()
            ], key=lambda e: (e["label"], e["range"] or "")),

            "fields": [
                {"property": key, "label": e["label"],
                 "present": len(e["present"]), "absent": len(e["absent"]),
                 "values": [{"value": value, "count": len(found)}
                            for value, found in sorted(e["values"].items())]}
                for key, e in sorted(fields.items(), key=lambda item: item[1]["label"])
                if e["present"]
            ],
        }
    return {"count": len(roots), "nodes": nodes}
