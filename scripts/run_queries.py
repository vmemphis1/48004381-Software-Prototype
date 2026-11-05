#!/usr/bin/env python3
"""Run the SPARQL query pack against the local ontology.

This is the same rdflib execution path used by the explorer, exposed as a regression
check and a reproducible way to capture every result in one command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology" / "ai-finance-governance.ttl"
AIRO = ROOT / "ontology" / "airo.ttl"
QUERY_DIR = ROOT / "queries"

def load_graph() -> Graph:
    """Load the project ontology and AIRO into one RDF graph."""
    graph = Graph()
    graph.parse(ONTOLOGY, format="turtle")
    graph.parse(AIRO, format="turtle")
    return graph


def format_table(rows: list[tuple[str, ...]], headers: list[str]) -> str:
    """Format query results as an aligned text table."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    line = "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    rule = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows
    ]
    return "\n".join([line, rule, *body])


def shorten(value: object) -> str:
    """Shorten project IRIs for display in query results."""
    text = str(value) if value is not None else ""
    if text.startswith("https://w3id.org/ai-finance-governance#"):
        return text.rsplit("#", 1)[-1]
    return text


def expects_empty(query: str) -> bool:
    """Identify a query whose description documents an expected corpus gap."""
    return any(
        "no results are currently expected" in line.strip().lower() for line in query.splitlines()
    )


def run(graph: Graph, path: Path) -> tuple[int, bool]:
    """Execute a query file, print its results, and report whether emptiness is expected."""
    query = path.read_text()
    result = graph.query(query)
    headers = [str(variable) for variable in result.vars]
    results = list(result)
    rows = [tuple(shorten(value) for value in row) for row in results]

    print(f"\n=== {path.name} ({len(rows)} rows) ===")
    for comment in query.splitlines():
        if comment.startswith("#"):
            print(comment)
        else:
            break
    if rows:
        print()
        print(format_table(rows, headers))
    else:
        print("\n(no results)")
    return len(rows), expects_empty(query)


def main() -> int:
    """Run the requested query files and report unexpected empty results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query",
        nargs="*",
        help="Query file names to run. Default: every .rq file in queries/.",
    )
    arguments = parser.parse_args()

    if arguments.query:
        paths = [QUERY_DIR / name for name in arguments.query]
        missing = [path for path in paths if not path.is_file()]
        if missing:
            for path in missing:
                print(f"Query not found: {path}", file=sys.stderr)
            return 1
    else:
        paths = sorted(
            path for path in QUERY_DIR.glob("*.rq") if not path.name.startswith("_")
        )

    graph = load_graph()
    print(f"Loaded {len(graph)} triples from ontology/ and airo.ttl")

    unexpected_empty = []
    expected_empty = []
    for path in paths:
        count, tolerated = run(graph, path)
        if count == 0:
            (expected_empty if tolerated else unexpected_empty).append(path.name)

    if expected_empty:
        print(
            f"\nNOTE: {len(expected_empty)} query is empty by design (documented corpus "
            f"gap): {', '.join(expected_empty)}"
        )
    if unexpected_empty:
        print(
            f"\nFAIL: {len(unexpected_empty)} query unexpectedly returned no rows: "
            f"{', '.join(unexpected_empty)}"
        )
        return 1
    print(f"\nPASS: all {len(paths)} queries behaved as expected (rdflib)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
