"""Read-only loopback transport. Authentication precedes all data access."""
import hmac
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .domain import Fault, Principal, require
from .service import dispatch
from .store import read_json

LOG = logging.getLogger("finrag")


def credentials(path):
    data = read_json(path)
    require(isinstance(data, dict) and data, "Empty credential file")
    require(all(token.isascii() and token.isalnum() and len(token) >= 32 for token in data),
            "Expected random alphanumeric tokens of at least 32 characters")
    return {token: Principal.parse(value) for token, value in data.items()}


def handler(db, identities):
    class Reader(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log bearer tokens, request paths, queries or passages.

        def reply(self, status, result):
            body = json.dumps(result, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "alive"})
            else:
                self.reply(404, {"error": "not_found"})

        def do_POST(self):
            start = time.monotonic()
            decision = "invalid_input"
            route = self.path.removeprefix("/v1/")
            try:
                raw = self.headers.get("Authorization", "")
                principal = next((p for t, p in identities.items()
                                  if hmac.compare_digest(raw.encode(), ("Bearer " + t).encode())), None)
                require(principal is not None, "Authentication required", "unauthorized")
                require(self.path in ("/v1/search", "/v1/answer", "/v1/resolve"), "Unknown operation", "not_found")
                size = int(self.headers.get("Content-Length", "0"))
                require(0 < size <= 16384, "Expected bounded JSON body")
                req = json.loads(self.rfile.read(size))
                result = dispatch(db, principal, route, req)
                decision = result.get("reason", result.get("status", "ok"))
                self.reply(200, result)
            except Fault as e:
                decision = e.code
                self.reply({"unauthorized": 401, "not_found": 404, "unavailable": 503}.get(e.code, 400),
                           {"error": e.code, "message": str(e)})
            except (ValueError, RecursionError):
                self.reply(400, {"error": "invalid_input"})
            finally:
                LOG.info(json.dumps({"operation": route if route in ("search","resolve","answer") else "unknown",
                                     "decision": decision, "elapsed_ms": round((time.monotonic()-start)*1000, 2)}))
    return Reader


def serve(db, path, port):
    identities = credentials(path)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with ThreadingHTTPServer(("127.0.0.1", port), handler(db, identities)) as server:
        server.serve_forever()
