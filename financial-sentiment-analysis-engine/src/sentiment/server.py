"""Loopback-only read service. Request routing is independent of its HTTP adapter."""
import base64
import binascii
import hmac
import json
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .dashboard import render
from .domain import Invalid, instant
from .evaluation import evaluate


class Service:
    def __init__(self, engine, reader, reviewer, catalog=None):
        if not reader or not reviewer or reader == reviewer:
            raise Invalid("missing_credentials", "Set distinct nonempty reader and reviewer tokens")
        self.keys = {"reader": reader.encode(), "reviewer": reviewer.encode()}
        self.catalog = engine.reference if catalog is None else catalog
        self.engine = engine
        self.report = evaluate(engine)
        self.lock = threading.Lock()
        self.requests = Counter()
        self.decisions = Counter()

    def role(self, header):
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "basic":
            return None
        try:
            name, token = base64.b64decode(value, validate=True).split(b":", 1)
            role = name.decode("ascii")
        except (ValueError, UnicodeError, binascii.Error):
            return None
        if role in self.keys and hmac.compare_digest(token, self.keys[role]):
            return role
        return None

    def get(self, url, auth=""):
        path = urlsplit(url)
        content_type = "application/json"
        if path.path == "/health":
            return 200, content_type, {"status":"ready"}
        role = self.role(auth)
        if not role:
            return 401, content_type, {"error":"authentication_required"}
        if path.path in ("/dashboard", "/v1/evaluation", "/v1/metrics") and role != "reviewer":
            return 403, content_type, {"error":"reviewer_required"}
        if path.path == "/v1/features":
            try:
                params = parse_qs(path.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
                if set(params) - {"as_of", "window_end", "issuer"} or any(len(v)!=1 for v in params.values()):
                    raise Invalid("invalid_query", "Unexpected or repeated query parameters")
                as_of = instant(params.get("as_of", [None])[0])
                end = instant(params.get("window_end", params["as_of"])[0])
                feed = self.engine.feed(as_of, end, params.get("issuer", [None])[0], self.catalog)
                with self.lock:
                    self.decisions.update(row["abstain_reason"] or "scored" for row in feed["decisions"])
                return 200, content_type, feed
            except Invalid as exc:
                return 400, content_type, {"error":exc.code, "detail":str(exc)}
            except ValueError:
                return 400, content_type, {"error":"invalid_query"}
        if path.path == "/dashboard":
            return 200, "text/html; charset=utf-8", render(self.report)
        if path.path == "/v1/evaluation":
            return 200, content_type, self.report
        if path.path == "/v1/metrics":
            with self.lock:
                counts = dict(self.requests)
                decisions = dict(self.decisions)
            return 200, content_type, dict(
                http_responses=counts,
                returned_decisions=decisions,
                duplicates=len(self.catalog.copies),
                linking_issues=sum(bool(issues) for issues in self.catalog.issues.values()),
            )
        return 404, content_type, {"error":"unknown_route"}

    def handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    status, kind, obj = service.get(self.path, self.headers.get("Authorization", ""))
                except ValueError:
                    status, kind, obj = 400, "application/json", {"error":"invalid_request"}
                body = (json.dumps(obj) if kind == "application/json" else obj).encode()
                with service.lock:
                    service.requests[str(status)] += 1
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
                if status == 401:
                    self.send_header("WWW-Authenticate", 'Basic realm="Sentiment research"')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass  # Aggregate statuses without retaining query strings or credentials.

        return Handler


def serve(engine, port, catalog=None):
    service = Service(engine, os.getenv("SENTIMENT_READER_TOKEN"), os.getenv("SENTIMENT_REVIEWER_TOKEN"), catalog)
    with ThreadingHTTPServer(("127.0.0.1", port), service.handler()) as server:
        print(f"Serving research dashboard at http://127.0.0.1:{server.server_port}/dashboard", flush=True)
        server.serve_forever()
