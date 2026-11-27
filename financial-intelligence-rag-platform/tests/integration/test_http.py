import io
import json
from types import SimpleNamespace

from finrag.http import credentials, handler
from finrag.domain import Fault
from tests.support import Corpus, NOW, QUESTION, PUBLIC


class Transport(Corpus):
    """Exercise raw HTTP parsing and serialization without opening a TCP port."""
    def request(self, method, path, body=None, token=None):
        wire = io.BytesIO()
        output = io.BytesIO()
        body = json.dumps(body).encode() if body is not None else b""
        headers = [f"{method} {path} HTTP/1.0", f"Content-Length: {len(body)}"]
        if token:
            headers.append("Authorization: Bearer " + token)
        wire.write(("\r\n".join(headers)+"\r\n\r\n").encode()+body)
        wire.seek(0)
        class Connection:
            def makefile(self, *args):
                return wire
            def sendall(self, data):
                output.write(data)
        handler(self.db, {"r"*32:PUBLIC})(Connection(), ("127.0.0.1", 1234), SimpleNamespace())
        head, data = output.getvalue().split(b"\r\n\r\n")
        return int(head.split()[1]), json.loads(data)

    def test_bearer_required_and_scope_server_assigned(self):
        req = {"query":QUESTION, "as_of":NOW}
        for token in (None, "wrong"):
            self.assertEqual(self.request("POST","/v1/answer",req,token)[0], 401)
        self.assertEqual(self.request("POST","/v1/search",dict(req,tenant="other-fund"),"r"*32)[0], 400)
        status, result = self.request("POST","/v1/answer",req,"r"*32)
        self.assertEqual(status, 200)
        cite = result["claims"][0]["citation"]
        self.assertEqual(self.request("POST", "/v1/resolve", {"chunk_id":cite["chunk_id"],"as_of":NOW},
                                      "r"*32)[1]["citation"], cite)
        self.assertEqual(self.request("POST","/v1/build",{},"r"*32)[0], 404)
        self.assertEqual(self.request("GET","/health"), (200, {"status":"alive"}))

    def test_credential_file_validation(self):
        path = self.folder / "keys"
        path.write_text('{"short":{"tenant":"demo-fund","groups":[]}}')
        with self.assertRaises(Fault):
            credentials(path)
        path.write_text(json.dumps({"b"*64:{"tenant":"demo-fund","groups":["researchers"]}}))
        self.assertEqual(credentials(path)["b"*64], PUBLIC)
