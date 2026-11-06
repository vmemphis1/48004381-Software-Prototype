"""Graph loading, auto-reload, and in-process SPARQL execution.
"""

from __future__ import annotations

from collections import Counter
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from pyparsing import ParseResults

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "ontology" / "ai-finance-governance.ttl"
AIRO = ROOT / "ontology" / "airo.ttl"
SOURCES = (ONTOLOGY, AIRO)

AFG = "https://w3id.org/ai-finance-governance#"



PREFIXES: dict[str, str] = {
    "": AFG,
    "afg": AFG,
    "airo": "https://w3id.org/airo#",
    "owl": str(OWL),
    "rdf": str(RDF),
    "rdfs": str(RDFS),
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "fibo-fbc-fct-fse": (
        "https://spec.edmcouncil.org/fibo/ontology/FBC/FunctionalEntities/"
        "FinancialServicesEntities/"
    ),
}
_SHORTEN_ORDER = sorted(
    ((p, ns) for p, ns in PREFIXES.items() if p != ""),
    key=lambda item: -len(item[1]),
)


def curie(iri: str) -> str:
    """Abbreviate an IRI for display. Falls back to the IRI itself."""
    for prefix, namespace in _SHORTEN_ORDER:
        if iri.startswith(namespace):
            local = iri[len(namespace) :]
            return f":{local}" if namespace == AFG else f"{prefix}:{local}"
    return iri


@dataclass
class EngineResult:
    """One engine's answer to one query."""

    engine: str
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[dict[str, Any]]] = field(default_factory=list)
    boolean: bool | None = None
    elapsed_ms: float = 0.0
    error: str | None = None

    @property
    def count(self) -> int:
        """Return the number of query result rows."""
        return len(self.rows)

    def as_dict(self) -> dict[str, Any]:
        """Convert the query result to its API representation."""
        return {
            "engine": self.engine,
            "ok": self.ok,
            "columns": self.columns,
            "rows": self.rows,
            "boolean": self.boolean,
            "elapsedMs": round(self.elapsed_ms, 1),
            "count": self.count,
            "error": self.error,
        }


def _require_local_query(node) -> None:
    """Inspect syntax before translation, including patterns nested in FILTER EXISTS."""
    if isinstance(node, CompValue):
        if node.name in ("ServiceGraphPattern", "DatasetClause"):
            raise ValueError("This explorer queries the local graph. SERVICE and FROM are unavailable.")
        children = node.values()
    elif isinstance(node, (ParseResults, list, tuple)):
        children = node
    else:
        return
    for child in children:
        _require_local_query(child)


class GraphService:
    """Owns the parsed graph and every derived index built from it."""

    def __init__(self, root: Path = ROOT) -> None:
        """Initialize the graph service and load its indexes."""
        self.root = Path(root)
        self.ontology = self.root / 'ontology' / ONTOLOGY.name
        self.sources = (self.ontology, self.root / 'ontology' / AIRO.name)
        self._lock = threading.RLock()
        self.graph: Graph = Graph()
        self.project_graph: Graph = Graph()
        self._stamps: tuple[tuple[int, int, int], ...] = ()
        self.loaded_at: float = 0.0
        self.load_ms: float = 0.0

        self.labels: dict[str, str] = {}
        self.classes: dict[str, dict[str, Any]] = {}
        self.properties: dict[str, dict[str, Any]] = {}
        self.reload(force=True)



    def _current_stamps(self) -> tuple[tuple[int, int, int], ...]:
        """Return modification timestamps for the ontology files."""
        return tuple((stat.st_ino, stat.st_size, stat.st_mtime_ns)
                     for stat in (path.stat() for path in self.sources))

    def reload(self, force: bool = False) -> bool:
        """Re-parse the Turtle sources if they changed. Returns True if reloaded."""
        with self._lock:
            stamps = self._current_stamps()
            if not force and stamps == self._stamps:
                return False
            started = time.perf_counter()
            graph = Graph()
            for prefix, namespace in PREFIXES.items():
                graph.bind(prefix or "afg", namespace, override=True)
            project = Graph().parse(self.ontology, format="turtle")
            graph += project
            graph.parse(self.sources[1], format="turtle")
            self.graph = graph
            self.project_graph = project
            self._stamps = stamps
            self.load_ms = (time.perf_counter() - started) * 1000
            self.loaded_at = time.time()
            self._build_indexes()
            return True

    def ensure_fresh(self) -> bool:
        """Called at the top of every request so an edit shows up on the next click."""
        return self.reload(force=False)

    def _build_indexes(self) -> None:
        """Build class, property, and label indexes from the loaded graph."""
        graph = self.graph
        self.labels = {
            str(subject): str(label)
            for subject, label in graph.subject_objects(RDFS.label)
            if isinstance(subject, URIRef)
        }

        counts = Counter(self.labels.values())
        self.unique_labels = {label: iri for iri, label in self.labels.items() if counts[label] == 1}

        classes: dict[str, dict[str, Any]] = {}
        for cls in set(graph.subjects(RDF.type, OWL.Class)):
            if not isinstance(cls, URIRef):
                continue
            iri = str(cls)
            classes[iri] = {
                "iri": iri,
                "curie": curie(iri),
                "label": self.labels.get(iri, curie(iri)),
                "comment": self._first_literal(cls, RDFS.comment),
                "parents": sorted(
                    str(parent)
                    for parent in graph.objects(cls, RDFS.subClassOf)
                    if isinstance(parent, URIRef)
                ),
                "directInstances": 0,
                "totalInstances": 0,
            }


        for iri, record in classes.items():
            cls = URIRef(iri)
            descendants = graph.transitive_subjects(RDFS.subClassOf, cls)
            record["directInstances"] = len(set(graph.subjects(RDF.type, cls)))
            record["totalInstances"] = len({subject for child in descendants
                                            for subject in graph.subjects(RDF.type, child)})
        self.classes = classes

        properties: dict[str, dict[str, Any]] = {}
        for kind, node in (("object", OWL.ObjectProperty), ("data", OWL.DatatypeProperty)):
            for prop in set(graph.subjects(RDF.type, node)):
                if not isinstance(prop, URIRef):
                    continue
                iri = str(prop)
                properties[iri] = {
                    "iri": iri,
                    "curie": curie(iri),
                    "label": self.labels.get(iri, curie(iri)),
                    "kind": kind,
                    "comment": self._first_literal(prop, RDFS.comment),
                    "domain": [
                        str(d)
                        for d in graph.objects(prop, RDFS.domain)
                        if isinstance(d, URIRef)
                    ],
                    "range": [
                        str(r)
                        for r in graph.objects(prop, RDFS.range)
                        if isinstance(r, URIRef)
                    ],
                    "uses": 0,
                }
        for prop in properties:
            properties[prop]["uses"] = sum(
                1 for _ in graph.triples((None, URIRef(prop), None))
            )
        self.properties = properties

    def _first_literal(self, subject: URIRef, predicate: URIRef) -> str | None:
        """Return the first literal value for a subject and predicate."""
        for value in self.graph.objects(subject, predicate):
            if isinstance(value, Literal):
                return str(value)
        return None



    def describe_term(self, iri: str) -> dict[str, Any]:
        """The display record the front end attaches to any IRI cell."""
        return {
            "type": "uri",
            "value": iri,
            "curie": curie(iri),
            "label": self.labels.get(iri),
        }

    def _bind(self, value: Any) -> dict[str, Any] | None:
        """Convert an RDF query value to an API binding."""
        if value is None:
            return None
        if isinstance(value, URIRef):
            return self.describe_term(str(value))
        if isinstance(value, Literal):
            return {
                "type": "literal",
                "value": str(value),
                "datatype": str(value.datatype) if value.datatype else None,
                "lang": value.language,
                "resolvedIri": self.unique_labels.get(str(value)),
            }
        return {"type": "bnode", "value": str(value)}



    def run_local(self, sparql: str) -> EngineResult:
        """Execute a SPARQL query against the local graph."""
        started = time.perf_counter()
        try:
            with self._lock:
                parsed = parseQuery(sparql)
                _require_local_query(parsed)
                prepared = translateQuery(parsed, initNs={**dict(self.graph.namespaces()), **PREFIXES})
                result = self.graph.query(prepared)
                answer = EngineResult(engine="rdflib", ok=True)
                if result.type == "ASK":
                    answer.boolean = bool(result)
                elif result.type in ("CONSTRUCT", "DESCRIBE"):
                    answer.columns = ["subject", "predicate", "object"]
                    answer.rows = [[self._bind(term) for term in triple] for triple in result.graph]
                else:
                    variables = result.vars or []
                    answer.columns = [str(var) for var in variables]
                    answer.rows = [[self._bind(binding.get(var)) for var in variables]
                                   for binding in result.bindings]
        except Exception as exc:
            answer = EngineResult(engine="rdflib", ok=False, error=f"{type(exc).__name__}: {exc}")
        answer.elapsed_ms = (time.perf_counter() - started) * 1000
        return answer

    def stats(self) -> dict[str, Any]:
        """Headline figures.

        `project` counts `ai-finance-governance.ttl` alone and therefore matches
        `scripts/audit_ontology.py`. `combined` adds the imported
        AIRO vocabulary, which is what queries actually run against.
        """
        project = self.project_graph
        return {
            "project": {
                "triples": len(project),
                "classes": len(set(project.subjects(RDF.type, OWL.Class))),
                "objectProperties": len(
                    set(project.subjects(RDF.type, OWL.ObjectProperty))
                ),
                "dataProperties": len(
                    set(project.subjects(RDF.type, OWL.DatatypeProperty))
                ),
                "individuals": len(set(project.subjects(RDF.type, OWL.NamedIndividual))),
            },
            "combined": {
                "triples": len(self.graph),
                "classes": len(self.classes),
                "objectProperties": sum(
                    1 for p in self.properties.values() if p["kind"] == "object"
                ),
                "dataProperties": sum(
                    1 for p in self.properties.values() if p["kind"] == "data"
                ),
                "individuals": len(
                    set(self.graph.subjects(RDF.type, OWL.NamedIndividual))
                ),
            },
            "loadedAt": self.loaded_at,
            "loadMs": round(self.load_ms, 1),
        }
