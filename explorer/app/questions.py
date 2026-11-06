"""Read the competency questions, the query pack, and the evaluation table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
QUERY_DIR = ROOT / "queries"
ORSD = ROOT / "ontology" / "ORSD.md"
EVALUATION = ROOT / "ontology" / "competency-question-evaluation.md"
ONTOLOGY_README = ROOT / "ontology" / "README.md"


_ORSD_ITEM = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")

_EVAL_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")

_PACK_ROW = re.compile(r"^\|\s*`([\w.-]+\.rq)`\s*\|\s*(.+?)\s*\|\s*$")


def orsd_questions() -> dict[int, str]:
    """The canonical wording, verbatim from ORSD section 8."""
    if not ORSD.exists():
        return {}
    questions: dict[int, str] = {}
    inside = False
    for line in ORSD.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.startswith("## 8.")
            continue
        if not inside:
            continue
        match = _ORSD_ITEM.match(line)
        if match:
            questions[int(match.group(1))] = match.group(2)
    return questions


def evaluation_rows() -> dict[int, dict[str, str]]:
    """Status and commentary per competency question, from the evaluation table."""
    if not EVALUATION.exists():
        return {}
    rows: dict[int, dict[str, str]] = {}
    for line in EVALUATION.read_text(encoding="utf-8").splitlines():
        match = _EVAL_ROW.match(line.strip())
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(2).split("|")]
        if len(cells) < 4:
            continue
        rows[int(match.group(1))] = {
            "queryFile": cells[1].strip("`"),
            "status": cells[2],
            "notes": cells[3],
        }
    return rows


def pack_descriptions() -> dict[str, str]:
    """One-line description per query file, from the table in ontology/README.md.

    The table can supplement the descriptions in query headers when available.
    """
    if not ONTOLOGY_README.exists():
        return {}
    descriptions: dict[str, str] = {}
    for line in ONTOLOGY_README.read_text(encoding="utf-8").splitlines():
        match = _PACK_ROW.match(line.strip())
        if match:
            descriptions[match.group(1)] = match.group(2)
    return descriptions


def _split_header(text: str) -> tuple[list[str], str]:
    """Separate the leading comment block from the executable query."""
    header: list[str] = []
    lines = text.splitlines()
    index = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            header.append(stripped.lstrip("#").strip())
        elif stripped == "" and not header:
            continue
        else:
            break
    else:
        index = len(lines)
    return header, "\n".join(lines[index:]).strip()


def _first_question_line(header: list[str]) -> str | None:
    """Return the first question in a query header, if present."""
    for line in header:
        if line.endswith("?"):
            return line.strip('"').strip()
    return None


def _expected(header: list[str]) -> str | None:
    """Extract expected results from a query header, if supplied."""
    for line in header:
        if line.lower().startswith("expected:"):
            return line.split(":", 1)[1].strip()
    return None


def load_pack() -> list[dict[str, Any]]:
    """Every query file, richest metadata first, ordered CQ1..CQ10 then extras."""
    orsd = orsd_questions()
    evaluation = evaluation_rows()
    descriptions = pack_descriptions()
    pack: list[dict[str, Any]] = []

    for path in sorted(QUERY_DIR.glob("*.rq")):
        if path.stem == "_prefixes":
            continue
        text = path.read_text(encoding="utf-8")
        header, sparql = _split_header(text)

        number: int | None = None
        cq_match = re.match(r"^cq(\d+)", path.stem)
        if cq_match:
            number = int(cq_match.group(1))



        question = orsd.get(number) if number else None
        if not question:
            question = (
                _first_question_line(header)
                or descriptions.get(path.name)
                or header[0]
                if header
                else path.stem.replace("-", " ")
            )

        record = evaluation.get(number, {}) if number else {}
        pack.append(
            {
                "id": path.stem,
                "file": path.name,
                "number": number,
                "kind": "competency" if number else "supporting",
                "question": question,
                "description": descriptions.get(path.name),
                "sparql": sparql,
                "header": header,
                "expected": _expected(header),
                "expectEmpty": any(
                    "no results are currently expected" in line.lower() for line in header
                ),
                "status": record.get("status"),
                "notes": record.get("notes"),
            }
        )

    pack.sort(key=lambda item: (item["number"] is None, item["number"] or 0, item["id"]))
    return pack


def orsd_coverage_problems(pack: list[dict[str, Any]]) -> list[str]:
    """Mirror the audit's cross-check so a mismatch is visible in the interface."""
    problems = []
    numbers = {item["number"] for item in pack if item["number"]}
    for number in orsd_questions():
        if number not in numbers:
            problems.append(f"ORSD competency question {number} has no query file.")
    for number in numbers:
        if number not in orsd_questions():
            problems.append(f"Query file cq{number:02d}-* has no matching ORSD question.")
    return problems
