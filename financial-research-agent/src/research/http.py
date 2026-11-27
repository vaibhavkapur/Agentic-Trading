"""Loopback-only analyst console. SQLite writers serialize across requests."""
import hmac
import json
import logging
import re
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .domain import CATALOG, ID, Problem, canonical, require, resolve
from .store import connect, increment
from .workflow import decide, get_brief, recent, research, source

ASSETS = {"/": ("desk.html", "text/html"), "/desk.css": ("desk.css", "text/css"),
          "/desk.js": ("desk.js", "text/javascript")}
BRIEF = r"/api/briefs/([0-9a-f]{64})"


def credentials(reader, analyst, name):
    require(all(isinstance(k, str) and len(k) >= 24 and k.isascii() and k.isalnum() for k in (reader, analyst))
            and reader != analyst, "credentials", "Set distinct alphanumeric reader and analyst tokens of at least 24 characters.")
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", name), "credentials", "Set an analyst identifier.")
    return reader, analyst, name


def make_handler(path, keys):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Avoid logging tokens, research questions or request paths.

        def send(self, status, data, mime="application/json"):
            raw = data if isinstance(data, bytes) else canonical(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def body(self):
            require(self.headers.get_content_type() == "application/json", "content_type", "Expected application/json.", 415)
            length = self.headers.get("Content-Length", "")
            require(re.fullmatch(r"[0-9]{1,5}", length) and 0 < int(length) <= 8192, "body_size", "Expected up to 8 KiB of JSON.", 413)
            try:
                obj = json.loads(self.rfile.read(int(length)))
            except (ValueError, RecursionError) as exc:
                raise Problem("invalid_json", "Malformed JSON.") from exc
            require(isinstance(obj, dict), "invalid_json", "Expected a JSON object.")
            return obj

        def dispatch(self, db):
            method, route = self.command, self.path
            if method == "GET" and route in ASSETS:
                filename, mime = ASSETS[route]
                return self.send(200, Path(__file__).with_name(filename).read_bytes(), mime)
            if method == "GET" and route == "/health":
                db.execute("SELECT count(*) FROM documents").fetchone()
                return self.send(200, {"status": "ok", "schema": 1})
            auth = self.headers.get("Authorization", "").encode()
            analyst = hmac.compare_digest(auth, ("Bearer " + keys[1]).encode())
            require(analyst or hmac.compare_digest(auth, ("Bearer " + keys[0]).encode()),
                    "unauthorized", "Enter a valid access token.", 401)
            if method == "GET":
                if route == "/api/catalog":
                    return self.send(200, CATALOG)
                if route == "/api/metrics":
                    return self.send(200, dict(db.execute("SELECT name,count FROM counters")))
                if route == "/api/briefs":
                    return self.send(200, recent(db))
                match = re.fullmatch(BRIEF, route)
                if match:
                    return self.send(200, get_brief(db, match[1]))
                match = re.fullmatch(r"/api/sources/(%s)/([1-9][0-9]{0,6})" % ID, route)
                if match:
                    return self.send(200, source(db, match[1], int(match[2])))
            if method == "POST":
                if route == "/api/resolve":
                    return self.send(200, resolve(self.body().get("identifier")))
                if route == "/api/briefs":
                    return self.send(200, research(db, self.body()))
                match = re.fullmatch(BRIEF + "/review", route)
                if match:
                    require(analyst, "forbidden", "An analyst credential is required.", 403)
                    body = self.body()
                    require(body.keys() == {"decision", "note"}, "invalid_review", "Supply decision and note.")
                    return self.send(200, decide(db, match[1], body["decision"], body["note"], keys[2]))
            raise Problem("not_found", "Unknown endpoint.", 404)

        def handle_method(self):
            try:
                port = self.server.server_address[1]
                require(self.headers.get("Host") in ("127.0.0.1:%d" % port, "localhost:%d" % port),
                        "invalid_host", "Use the local console address.", 403)
                with closing(connect(path)) as db:
                    try:
                        self.dispatch(db)
                    except Problem as exc:
                        with db:
                            increment(db, "error_" + exc.code)
                        raise
            except Problem as exc:
                self.send(exc.status, {"error": exc.code, "message": str(exc)})
            except sqlite3.Error:
                logging.exception("Database request failed")
                self.send(503, {"error": "storage_failure", "message": "Research storage unavailable."})

        do_GET = do_POST = handle_method
    return Handler


def serve(path, port, keys):
    with ThreadingHTTPServer(("127.0.0.1", port), make_handler(path, keys)) as server:
        print("Analyst desk at http://127.0.0.1:%d" % server.server_port, flush=True)
        server.serve_forever()
