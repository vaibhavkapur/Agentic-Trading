import base64
import json
import subprocess
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.support import ROOT, build, inputs
from sentiment.domain import Invalid
from sentiment.evaluation import evaluate
from sentiment.server import Service


def credentials(role):
    raw = f"{role}:{role}-test-token".encode()
    return "Basic " + base64.b64encode(raw).decode()


class Interfaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = build()
        cls.service = Service(cls.engine, "reader-test-token", "reviewer-test-token")

    def test_authentication_and_role_separation(self):
        for header in ["", "Basic !!", credentials("other"), "Basic cmVhZGVyOndyb25n"]:
            self.assertEqual(self.service.get("/v1/features",header)[0],401)
        for route in ["/dashboard", "/v1/evaluation", "/v1/metrics"]:
            self.assertEqual(self.service.get(route,credentials("reader"))[0],403)
            self.assertEqual(self.service.get(route,credentials("reviewer"))[0],200)
        for a,b in [("", "secret"), ("identical","identical")]:
            with self.assertRaises(Invalid):
                Service(self.engine, a, b)

    def test_http_adapter(self):
        with ThreadingHTTPServer(("127.0.0.1",0), self.service.handler()) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval":0.01})
            thread.start()
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request("GET","/dashboard")
                resp = conn.getresponse()
                self.assertEqual(resp.status,401)
                self.assertIn("Basic", resp.getheader("WWW-Authenticate"))
                resp.read()
                conn.request("GET","/dashboard",headers={"Authorization":credentials("reviewer")})
                resp = conn.getresponse()
                self.assertEqual(resp.status,200)
                self.assertIn(b"Confusion matrix",resp.read())
                conn.request("GET","/v1/features?as_of=2025-04-23T00:00:00Z&issuer=NVL",
                             headers={"Authorization":credentials("reader")})
                resp = conn.getresponse()
                self.assertEqual(resp.status,200)
                self.assertEqual([r["issuer"] for r in json.load(resp)["aggregates"]],["NVL"])
            finally:
                conn.close()
                server.shutdown()
                thread.join()

    def test_query_errors_and_empty_result(self):
        auth = credentials("reader")
        for query in ["", "as_of=bad", "as_of=1&as_of=2", "other=1", "as_of=2025-01-01T00:00:00Z",
                      "as_of=2025-04-23T00:00:00Z&issuer=other",
                      "as_of=2025-04-23T00:00:00Z&window_end=2025-04-24T00:00:00Z"]:
            status, _, body = self.service.get("/v1/features?"+query,auth)
            self.assertEqual(status,400,query)
            self.assertIn("error",body)
        result = self.service.get("/v1/features?as_of=2025-05-31T00:00:00Z",auth)
        self.assertEqual(result[2]["aggregates"],[])
        self.assertEqual(self.service.get("/absent",auth)[0],404)

    def test_local_article_adapter_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            row = dict(inputs()[1][0], id="new-observation", event_at="2025-05-07T12:00:00Z",
                       available_at="2025-05-07T14:00:00Z")
            path.write_text(json.dumps(row)+"\n")
            cmd = [str(ROOT/"scripts/engine"), "features", "--articles",str(path),
                   "--as-of","2025-05-08T00:00:00Z"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            feed = json.loads(result.stdout)
            self.assertEqual(feed["model_version"],self.engine.version)
            self.assertEqual([r["article_id"] for r in feed["decisions"]],["new-observation"])
            path.write_text("{broken json")
            error = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(error.returncode,0)
            self.assertEqual(json.loads(error.stderr)["error"],"invalid_json")

    def test_evidence_retains_all_raw_predictions(self):
        report = evaluate(self.engine)
        self.assertEqual(report["split_counts"],{"train":40,"calibration":16,"test":25})
        for model, summary in report["models"].items():
            self.assertEqual(summary["n"],len(report["test_predictions"]))
            self.assertEqual(sum(b["count"] for b in summary["reliability_bins"]),summary["n"])
            for row in report["test_predictions"]:
                self.assertAlmostEqual(sum(row["models"][model]["probabilities"].values()),1)
