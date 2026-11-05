#!/usr/bin/env python3
"""Local server for the AI Finance Governance Explorer.

Start it with `explorer/run.sh`, or:

    python3 explorer/server.py [--port 8042] [--no-open]

The server reads `ontology/*.ttl`, `queries/*.rq`, and the two markdown documents
that define the competency questions straight from the working tree, and
re-reads them whenever they change on disk. Nothing is copied or cached, so the
interface cannot show an answer the repository would not also give.

Only the standard library and rdflib are needed -- rdflib is already in
`scripts/requirements.txt`, so there is nothing new to install.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import corpus, views
from app.graph_service import GraphService
from app.questions import load_pack, orsd_coverage_problems

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent






_SOURCE_FILES = sorted(HERE.rglob("*.py"))
_SOURCE_FINGERPRINT = {path: path.stat().st_mtime for path in _SOURCE_FILES}


def stale_source_files() -> list[str]:
    """Server modules that have changed on disk since this process started."""
    changed = []
    for path, loaded_mtime in _SOURCE_FINGERPRINT.items():
        try:
            if path.stat().st_mtime != loaded_mtime:
                changed.append(path.relative_to(ROOT).as_posix())
        except OSError:
            changed.append(path.relative_to(ROOT).as_posix())
    return sorted(changed)
STATIC = HERE / "static"


SERVABLE = (ROOT / "corpus", ROOT / "Sources")

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")

service: GraphService


class Handler(BaseHTTPRequestHandler):
    server_version = "AFGExplorer/1.0"
    protocol_version = "HTTP/1.1"



    def log_message(self, fmt: str, *args: Any) -> None:


        """Write a concise HTTP request log entry."""
        if self.path.startswith("/static/") or self.path.startswith("/doc"):
            return
        sys.stderr.write(f"  {self.command} {self.path}\n")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        """Send a JSON response with the given status."""
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        """Send a JSON error response."""
        self._send_json({"error": message}, status=status)

    def _query_params(self) -> dict[str, str]:
        """Parse the request query parameters."""
        parsed = urllib.parse.urlparse(self.path)
        return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def _body(self) -> dict[str, Any]:
        """Read and validate a JSON request body."""
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except json.JSONDecodeError:
            return {}

    def _corpus_body(self) -> dict[str, Any]:
        """Read and validate a corpus write request."""
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('Corpus additions require JSON data.')
        origin = self.headers.get('Origin')
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get('Host'):
            raise ValueError('Corpus additions must come from this explorer.')
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > corpus.MAX_BODY_BYTES:
            self.close_connection = True
            raise ValueError('The upload is empty or too large. Documents may be at most 25 MB.')
        payload = json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('Corpus additions require a document object.')
        return payload



    def _send_static(self, relative: str) -> None:
        """Serve a file from the explorer static directory."""
        if not relative or relative.endswith("/"):
            relative = "index.html"
        target = (STATIC / relative).resolve()
        if not target.is_relative_to(STATIC) or not target.is_file():
            self._error(f"Not found: {relative}", HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        content_type, _ = mimetypes.guess_type(target.name)
        if target.suffix == ".mjs":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))




        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_document(self) -> None:
        """Serve an archived corpus file, honouring Range requests.

        pdf.js fetches a large PDF in slices when the server advertises ranges.
        Without this the viewer would pull all 14 MB of an annual report before
        showing page 29, which is the difference between a preview that feels
        instant and one that does not.
        """
        params = self._query_params()
        relative = params.get("path", "")
        if not relative:
            self._error("Missing path")
            return
        target = (ROOT / relative).resolve()
        if not any(target.is_relative_to(base) for base in SERVABLE):
            self._error("Path is outside the corpus", HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self._error(f"No archived copy at {relative}", HTTPStatus.NOT_FOUND)
            return

        size = target.stat().st_size
        content_type, _ = mimetypes.guess_type(target.name)
        content_type = content_type or "application/octet-stream"
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False

        if range_header:
            match = _RANGE.match(range_header.strip())
            if match:
                raw_start, raw_end = match.groups()
                if raw_start:
                    start = int(raw_start)
                    end = int(raw_end) if raw_end else size - 1
                elif raw_end:
                    start = max(0, size - int(raw_end))
                if start >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                partial = True

        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if target.suffix.lower() in ('.html', '.htm'):

            self.send_header('Content-Security-Policy', "sandbox allow-same-origin; script-src 'none'; object-src 'none'; base-uri 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.end_headers()

        with target.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)



    def do_GET(self) -> None:
        """Dispatch a GET request to the appropriate handler."""
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/doc":
                self._send_document()
                return
            if path.startswith("/api/"):
                service.ensure_fresh()
                self._api_get(path)
                return
            if path == "/":
                self._send_static("index.html")
                return
            if path.startswith("/static/"):
                self._send_static(path[len("/static/") :])
                return
            self._send_static(path.lstrip("/"))
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        """Dispatch a POST request to the appropriate handler."""
        path = urllib.parse.urlparse(self.path).path
        try:
            service.ensure_fresh()
            if path in ('/api/corpus/documents', '/api/corpus/snippets'):
                try:
                    payload = self._corpus_body()
                    if path == '/api/corpus/documents':
                        result = corpus.save_document(service, payload)
                    else:
                        result = corpus.add_snippets(service, payload.get('documentIri'), payload)
                except (ValueError, UnicodeDecodeError) as exc:
                    self.close_connection = True
                    self._error(str(exc))
                    return
                self._send_json(result, status=HTTPStatus.CREATED)
                return
            if path == "/api/builder-options":
                payload = self._body()
                self._send_json(views.builder_options(service, payload.get("sparql", "")))
                return
            if path == "/api/query":
                payload = self._body()
                sparql = (payload.get("sparql") or "").strip()
                if not sparql:
                    self._error("Empty query")
                    return
                self._send_json({"result": service.run_local(sparql).as_dict()})
                return
            if path == "/api/reload":
                service.reload(force=True)
                self._send_json({"reloaded": True, "stats": service.stats()})
                return
            self._error(f"Unknown endpoint: {path}", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api_get(self, path: str) -> None:
        """Dispatch a read-only API request."""
        params = self._query_params()

        if path == '/api/corpus/options':
            self._send_json(corpus.corpus_options(service))
            return

        if path == "/api/status":
            pack = load_pack()
            self._send_json(
                {
                    "stats": service.stats(),
                    "queryCount": len(pack),
                    "integrity": orsd_coverage_problems(pack),
                    "root": str(ROOT),
                    "staleSource": stale_source_files(),
                }
            )
            return

        if path == "/api/questions":
            self._send_json({"questions": load_pack()})
            return

        if path == "/api/schema":
            classes = sorted(service.classes.values(), key=lambda c: c["label"])
            properties = sorted(service.properties.values(), key=lambda p: p["label"])
            self._send_json({"classes": classes, "properties": properties})
            return

        if path == "/api/resource":
            iri = params.get("iri")
            if not iri:
                self._error("Missing iri")
                return
            self._send_json(views.resource(service, iri))
            return

        if path == "/api/evidence":
            iri = params.get("iri")
            if iri:
                self._send_json({"evidence": views.evidence_for(service, iri)})
            else:
                self._send_json({"evidence": views.all_evidence(service)})
            return

        if path == "/api/graph":
            self._send_json(
                views.graph_view(
                    service,
                    mode=params.get("mode", "instances"),
                    focus=params.get("focus"),
                    depth=int(params.get("depth", "1") or 1),
                )
            )
            return

        if path == "/api/indexes":
            self._send_json(
                {
                    "evidence": views.evidence_index(service),
                    "indirect": views.indirect_evidence_index(service),
                    "labels": views.label_index(service),
                }
            )
            return

        if path == "/api/documents":
            self._send_json({"documents": views.documents(service)})
            return

        self._error(f"Unknown endpoint: {path}", HTTPStatus.NOT_FOUND)


def main() -> int:
    """Start the explorer HTTP server."""
    global service

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8042)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args()

    started = time.perf_counter()
    service = GraphService()
    stats = service.stats()["project"]

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"

    print("AI Finance Governance Explorer")
    print(
        f"  graph      {stats['triples']} triples, {stats['classes']} classes, "
        f"{stats['individuals']} individuals"
    )
    print(f"  queries    {len(load_pack())} files in queries/")
    print("  engine     rdflib (in process)")
    print(f"  ready in   {(time.perf_counter() - started) * 1000:.0f} ms")
    print(f"\n  {url}\n")

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
