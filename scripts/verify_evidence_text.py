#!/usr/bin/env python3
"""Verify that every evidence quote is really on the page it cites.

The evidence model promises that any claim in the knowledge graph can be traced
to a page of a specific archived file, and the explorer makes good on that by
opening the file at `:pageReference` and highlighting `:exactText`. That promise
was previously only checkable by hand, one click at a time, and only for the
snippets someone happened to open.

This script checks all of them headlessly. For each `:EvidenceSnippet` it
resolves the archived file, extracts the text of the cited page, and confirms
the quoted sentence is present. A quote that is in the document but on a
different page is reported with the page it was actually found on, because that
is a correctable provenance error rather than a fabricated claim.

Matching mirrors `explorer/static/js/viewer.js`: quotes, dashes and ligatures are
normalised, whitespace is collapsed, and hyphenation across a line break is
repaired, so a pass here predicts a successful highlight in the interface.

    python3 scripts/verify_evidence_text.py           # all snippets
    python3 scripts/verify_evidence_text.py --verbose # show every snippet

Exit status is non-zero if any quote could not be found on its cited page.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import re
import sys
from pathlib import Path

try:
    from rdflib import Graph, Namespace, RDF
except ImportError:
    sys.exit("rdflib is required: python3 -m pip install -r scripts/requirements.txt")

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pypdf is required: python3 -m pip install -r scripts/requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
AFG = Namespace("https://w3id.org/ai-finance-governance#")





NEARBY = 3


def normalise(text: str) -> str:
    """Mirror the viewer's normalisation so this check predicts the highlight."""
    text = (
        text.replace("‘", "'").replace("’", "'").replace("ʼ", "'")
        .replace("“", '"').replace("”", '"')
        .replace("ﬁ", "fi").replace("ﬂ", "fl")
        .replace(" ", " ")
    )
    text = re.sub(r"[‐-―−]", "-", text)

    text = re.sub(r"-\s*\n\s*", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def page_number(reference: str) -> int | None:
    """The PDF page a `:pageReference` points at, or None if it names no page.

    Recorded references take three shapes: "PDF page 103 (report page 99)",
    where the first number is the one to open; "Form 10-K page 124", which is a
    printed page in an HTML filing and has no PDF page; and "Not paginated".
    Only the first is a PDF page, so match it specifically rather than taking
    whatever integer appears first.
    """
    match = re.search(r"PDF page\s+(\d+)", reference, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None




UNREADABLE = "\x00unreadable"


class PdfPages:
    """Extract only the cited pages, unless a mismatch requires a wider search."""
    def __init__(self, path: Path):
        self.reader = PdfReader(path)
        self.cache = {}

    def __len__(self):
        return len(self.reader.pages)

    def __getitem__(self, index):
        if index < 0 or index >= len(self):
            raise IndexError(index)
        if index not in self.cache:
            try:
                self.cache[index] = normalise(self.reader.pages[index].extract_text() or "")
            except Exception:
                self.cache[index] = UNREADABLE
        return self.cache[index]


class ArchiveText(HTMLParser):
    """Collect text from the same HTML elements that the preview can highlight."""
    skip = {"head", "script", "style", "template", "noscript", "ix:hidden"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.ignored = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.void and (self.ignored or tag in self.skip or "hidden" in dict(attrs)):
            self.ignored.append(tag)

    def handle_endtag(self, tag):
        if tag in self.ignored:
            while self.ignored.pop() != tag:
                pass

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def html_text(path: Path) -> str:
    parser = ArchiveText()
    parser.feed(path.read_text(encoding="utf-8-sig", errors="replace"))
    parser.close()
    return normalise(" ".join(parser.parts))


def fragments(quote: str) -> list[str]:
    """Split an elided quote into the runs that must each appear, in order.

    Some recorded quotes join non-adjacent text with an ellipsis, because the
    claim rests on two parts of one list -- "Governing Policies: ... Group
    Artificial Intelligence Policy". No contiguous run of the page equals that
    string, so treating it as one substring reports a true quote as missing.
    """
    parts = [part.strip(" ;:,") for part in re.split(r"\.\.\.|…", quote)]
    return [part for part in parts if part]


def contains(haystack: str, quote: str) -> bool:
    """Require the complete quote; elided fragments must occur in order.

    Whitespace differences tolerate PDF text layout.
    """
    parts = fragments(quote.strip())
    if not parts:
        return False
    compact = re.sub(r"\s+", "", haystack)
    cursor = 0
    for part in parts:
        needle = re.sub(r"\s+", "", part)
        found = compact.find(needle, cursor)
        if found < 0:
            return False
        cursor = found + len(needle)
    return True


def main() -> int:
    """Check evidence quotations against their archived source documents."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="list every snippet")
    args = parser.parse_args()

    graph = Graph()
    graph.parse(ROOT / "ontology" / "ai-finance-governance.ttl", format="turtle")

    text_cache: dict[Path, PdfPages | str] = {}
    results: list[tuple[str, str, str]] = []

    for snippet in sorted(graph.subjects(RDF.type, AFG.EvidenceSnippet)):
        label = str(graph.value(snippet, AFG.exactText) or "")
        name = str(snippet).rsplit("#", 1)[-1]
        quote = normalise(label)
        reference = str(graph.value(snippet, AFG.pageReference) or "")
        document = graph.value(snippet, AFG.extractedFrom)

        if document is None:
            results.append(("FAIL", name, "no :extractedFrom document"))
            continue

        local = graph.value(document, AFG.localPath)
        if local is None:
            results.append(("FAIL", name, "source document records no :localPath"))
            continue

        path = ROOT / str(local)
        if not path.exists():
            results.append(("FAIL", name, f"archived file missing: {local}"))
            continue

        # Several snippets often cite one report; extract each archived file once.
        if path not in text_cache:
            text_cache[path] = PdfPages(path) if path.suffix.lower() == ".pdf" else html_text(path)
        content = text_cache[path]



        if isinstance(content, str):
            status = "OK" if contains(content, quote) else "FAIL"
            detail = reference or "whole document" if status == "OK" else "quote not in file"
            results.append((status, name, detail))
            continue

        wanted = page_number(reference)
        if wanted is None:
            results.append(("FAIL", name, f"{reference or 'no page reference'}; specify a PDF page"))
            continue

        if not 1 <= wanted <= len(content):
            results.append(("FAIL", name,
                            f"cites PDF page {wanted}, file has {len(content)} pages"))
            continue

        if content[wanted - 1] == UNREADABLE:
            results.append(("UNREADABLE", name,
                            f"{reference}; pypdf cannot decode this page's fonts"))
            continue

        if contains(content[wanted - 1], quote):
            results.append(("OK", name, reference))
            continue



        # Prefer nearby matches to help correct common PDF/report page offsets;
        # only search the full document if none is close to the cited page.
        nearby = [i + 1 for i in range(max(0, wanted - 1 - NEARBY),
                                       min(len(content), wanted + NEARBY))
                  if contains(content[i], quote)]
        if nearby:
            results.append(("WRONG PAGE", name,
                            f"cites PDF page {wanted}, found on {', '.join(map(str, nearby))}"))
            continue
        elsewhere = [i + 1 for i, page in enumerate(content) if contains(page, quote)]
        if elsewhere:
            results.append(("WRONG PAGE", name,
                            f"cites PDF page {wanted}, found on {', '.join(map(str, elsewhere[:5]))}"))
        else:
            results.append(("FAIL", name, f"quote not found anywhere in {path.name}"))

    failures = [r for r in results if r[0] not in ("OK", "UNREADABLE")]
    unreadable = [r for r in results if r[0] == "UNREADABLE"]
    for status, name, detail in results:
        if args.verbose or status != "OK":
            print(f"{status:<11} {name}  ({detail})")

    print()
    verified = len(results) - len(failures) - len(unreadable)
    print(f"{len(results)} evidence snippets checked, "
          f"{verified} quotes verified on the cited page.")
    if unreadable:
        print(f"{len(unreadable)} could not be checked here because pypdf cannot decode "
              "the page. Inspect these references in the explorer.")
    # Unreadable is distinct from a missing quotation, but neither verifies it.
    if failures or unreadable:
        print(f"{len(failures) + len(unreadable)} need attention.")
        return 1
    print("PASS: every checkable evidence quote is present on the page it cites.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
