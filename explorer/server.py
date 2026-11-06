#!/usr/bin/env python3
"""Local server for the AI Finance Governance Explorer.

Start it with `explorer/run.sh`, or:

    python3 explorer/server.py [--port 8042] [--no-open]

The server reads the ontology, query pack, and ORSD from the working tree.
Install the dependencies in scripts/requirements.txt before starting.
"""

from __future__ import annotations

import argparse
from ipaddress import ip_address
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






def _source_fingerprint():
    return {p: p.stat().st_mtime_ns for p in [HERE / "server.py", *(HERE / "app").rglob("*.py")]}


_SOURCE_FINGERPRINT = _source_fingerprint()


def stale_source_files() -> list[str]:
    """Identify changed, removed, or added server modules until the next restart."""
    current = _source_fingerprint()
    return sorted(path.relative_to(ROOT).as_posix() for path in current.keys() | _SOURCE_FINGERPRINT.keys()
                  if current.get(path) != _SOURCE_FINGERPRINT.get(path))


STATIC = HERE / "static"
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")

service: GraphService


class Handler(BaseHTTPRequestHandler):
    server_version = "AFGExplorer/1.0"
    protocol_version = "HTTP/1.1"



    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        # A browser reaching a loopback listener must have addressed it locally.
        if ip_address(self.server.server_address[0]).is_loopback:
            host = self.headers.get("Host", "").partition(":")[0].lower()
            if host not in ("localhost", self.server.server_address[0]):
                self.close_connection = True
                self._error("Invalid Host for the local explorer.", HTTPStatus.FORBIDDEN)
                return False
        return True

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

    def _body(self, max_bytes: int) -> dict[str, Any]:
        """Read a bounded, same-origin JSON object before processing any input."""
        if self.headers.get_content_type() != "application/json":
            raise ValueError("This endpoint requires JSON data.")
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            raise ValueError("Requests must come from this explorer.")
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ValueError("A single Content-Length is required.")
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= max_bytes:
            raise ValueError("The request body is empty or too large.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
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
        target = (service.root / relative).resolve()
        if not target.is_relative_to(service.root / "corpus"):
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
            match = _RANGE.fullmatch(range_header.strip())
            if match and any(match.groups()) and all(len(n) < 21 for n in match.groups()):
                raw_start, raw_end = match.groups()
                if raw_start:
                    start = int(raw_start)
                    end = min(int(raw_end), end) if raw_end else end
                else:
                    start = max(0, size - int(raw_end))
                partial = start <= end and start < size
            if not partial:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if target.suffix.lower() in ('.html', '.htm'):
            # Archived pages may contain active content; allow viewing but not scripts.
            self.send_header('Content-Security-Policy', "sandbox allow-same-origin; default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header("Cache-Control", "no-store")
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
                with service._lock:
                    service.ensure_fresh()
                    status, payload = self._api_get(path)
                self._send_json(payload, status)
                return
            if path == "/":
                self._send_static("index.html")
                return
            if path.startswith("/static/"):
                self._send_static(path[len("/static/") :])
                return
            self._send_static(path.lstrip("/"))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        """Dispatch a POST request to the appropriate handler."""
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ('/api/corpus/documents', '/api/corpus/snippets'):
                payload = self._body(corpus.MAX_BODY_BYTES)
                if path == '/api/corpus/documents':
                    result = corpus.save_document(service, payload)
                else:
                    result = corpus.add_snippets(service, payload.get('documentIri'), payload)
                self._send_json(result, status=HTTPStatus.CREATED)
                return
            if path in ("/api/builder-options", "/api/query"):
                payload = self._body(1024 * 1024)
                question = None
                if path == "/api/query" and "questionId" in payload:
                    question = next((item for item in load_pack() if item["id"] == payload["questionId"]), None)
                    if question is None:
                        self._error("This question is no longer in the query pack.", HTTPStatus.NOT_FOUND)
                        return
                sparql = question["sparql"] if question else payload.get("sparql")
                if not isinstance(sparql, str) or not sparql.strip():
                    raise ValueError("Enter a SPARQL query.")
                with service._lock:
                    service.ensure_fresh()
                    result = (views.builder_options(service, sparql) if path == "/api/builder-options"
                              else {"result": service.run_local(sparql).as_dict()})
                if question:
                    result["question"] = question
                self._send_json(result)
                return
            if path == "/api/reload":
                if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
                    raise ValueError("Requests must come from this explorer.")
                if self.headers.get("Transfer-Encoding") or int(self.headers.get("Content-Length") or 0):
                    raise ValueError("Reload takes an empty request body.")
                with service._lock:
                    service.reload(force=True)
                    stats = service.stats()
                self._send_json({"reloaded": True, "stats": stats})
                return
            self._error(f"Unknown endpoint: {path}", HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as exc:
            self.close_connection = True
            self._error(str(exc))
        except Exception as exc:
            self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api_get(self, path: str) -> tuple[int, dict[str, Any]]:
        """Build a consistent response under the graph lock; send it after release."""
        params = self._query_params()
        if path == "/api/corpus/options":
            return 200, corpus.corpus_options(service)
        if path == "/api/status":
            pack = load_pack()
            return 200, {
                "stats": service.stats(), "queryCount": len(pack),
                "integrity": orsd_coverage_problems(pack), "root": str(service.root),
                "staleSource": stale_source_files(),
            }
        if path == "/api/questions":
            return 200, {"questions": load_pack()}
        if path == "/api/schema":
            return 200, {
                "classes": sorted(service.classes.values(), key=lambda c: c["label"]),
                "properties": sorted(service.properties.values(), key=lambda p: p["label"]),
            }
        if path == "/api/resource":
            if not params.get("iri"):
                return 400, {"error": "Missing iri"}
            return 200, views.resource(service, params["iri"])
        if path == "/api/evidence":
            iri = params.get("iri")
            return 200, {"evidence": views.evidence_for(service, iri) if iri else views.all_evidence(service)}
        if path == "/api/graph":
            try:
                depth = int(params.get("depth", "1"))
            except ValueError:
                return 400, {"error": "Graph depth must be an integer."}
            return 200, views.graph_view(service, params.get("mode", "instances"), params.get("focus"), depth)
        if path == "/api/indexes":
            return 200, {
                "evidence": views.evidence_index(service), "indirect": views.indirect_evidence_index(service),
                "labels": views.label_index(service),
            }
        if path == "/api/documents":
            return 200, {"documents": views.documents(service)}
        return 404, {"error": f"Unknown endpoint: {path}"}


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
    url = f"http://{args.host}:{httpd.server_port}/"

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
