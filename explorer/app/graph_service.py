"""Graph loading, auto-reload, and in-process SPARQL execution.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from rdflib.plugins.sparql.results.jsonresults import JSONResultSerializer

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
        self._stamps: tuple[int, ...] = ()
        self.loaded_at: float = 0.0
        self.load_ms: float = 0.0

        self.labels: dict[str, str] = {}
        self.classes: dict[str, dict[str, Any]] = {}
        self.properties: dict[str, dict[str, Any]] = {}
        self.reload(force=True)



    def _current_stamps(self) -> tuple[int, ...]:
        """Return modification timestamps for the ontology files."""
        return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in self.sources)

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
            for source in self.sources:
                if source.exists():
                    graph.parse(source, format="turtle")
            self.graph = graph

            # Keep a separate project-only graph for figures that exclude imported AIRO.
            project = Graph()
            if self.ontology.exists():
                project.parse(self.ontology, format="turtle")
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


        for individual, cls in graph.subject_objects(RDF.type):
            iri = str(cls)
            if iri in classes:
                classes[iri]["directInstances"] += 1


        # Traverse each descendant class once, even if inheritance has multiple paths.
        # Counts sum type assertions; an individual asserted in two classes can count twice.
        for iri, record in classes.items():
            seen: set[str] = set()
            stack = [iri]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                for child, child_record in classes.items():
                    if current in child_record["parents"]:
                        stack.append(child)
            record["totalInstances"] = sum(
                classes[c]["directInstances"] for c in seen if c in classes
            )
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
            }
        return {"type": "bnode", "value": str(value)}



    def run_local(self, sparql: str) -> EngineResult:
        """Execute a SPARQL query against the local graph."""
        started = time.perf_counter()
        try:
            with self._lock:
                result = self.graph.query(sparql)
        except Exception as exc:
            return EngineResult(
                engine="rdflib",
                ok=False,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
        elapsed = (time.perf_counter() - started) * 1000

        if result.type == "ASK":
            return EngineResult(
                engine="rdflib", ok=True, boolean=bool(result), elapsed_ms=elapsed
            )
        if result.type == "CONSTRUCT":
            return EngineResult(
                engine="rdflib",
                ok=True,
                columns=["subject", "predicate", "object"],
                rows=[
                    [self._bind(s), self._bind(p), self._bind(o)]
                    for s, p, o in result.graph
                ],
                elapsed_ms=elapsed,
            )

        columns = [str(v) for v in (result.vars or [])]
        rows = [[self._bind(row[var]) for var in (result.vars or [])] for row in result]
        return EngineResult(
            engine="rdflib", ok=True, columns=columns, rows=rows, elapsed_ms=elapsed
        )



    def stats(self) -> dict[str, Any]:
        """Headline figures.

        `project` counts `ai-finance-governance.ttl` alone and therefore matches
        `scripts/audit_ontology.py` and the figures quoted in
        `ontology/competency-question-evaluation.md`. `combined` adds the imported
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
