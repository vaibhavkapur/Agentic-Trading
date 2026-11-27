import http.client
import json
import threading
from http.server import ThreadingHTTPServer

from research.http import credentials, make_handler
from research.domain import Problem
from tests.support import AS_OF, DatabaseCase


class Api(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.reader, self.analyst, self.actor = credentials("r" * 32, "a" * 32, "fixture-reviewer")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.path, (self.reader, self.analyst, self.actor)))
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def api(self, method, path, token=None, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            conn.request(method, path, None if payload is None else json.dumps(payload), headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if "json" in response.getheader("Content-Type") else raw
        finally:
            conn.close()

    def test_analyst_workflow(self):
        self.assertEqual(self.api("GET", "/health")[1]["status"], "ok")
        self.assertIn(b"Research desk", self.api("GET", "/")[1])
        self.assertEqual(self.api("GET", "/api/briefs")[0], 401)
        self.assertEqual(self.api("POST", "/api/resolve", self.reader, {"identifier":"Demo:ALDR"})[1]["id"], "issuer-alder")
        _, brief = self.api("POST", "/api/briefs", self.reader,
                            dict(subject="Alder", period="FY2024", as_of=AS_OF, metrics=["revenue"]))
        url = "/api/briefs/" + brief["id"]
        cite = brief["result"]["items"][0]["citations"][0]
        self.assertEqual(self.api("GET", cite["href"], self.reader)[1]["text"], cite["passage"])
        review = {"decision":"approve", "note":"Verified the restated passage."}
        self.assertEqual(self.api("POST", url + "/review", self.reader, review)[0], 403)
        code, reviewed = self.api("POST", url + "/review", self.analyst, review)
        self.assertEqual((code, reviewed["review"]["actor"]), (200, self.actor))
        self.assertEqual(self.api("POST", url + "/review", self.analyst, review)[0], 409)
        self.assertEqual(self.api("GET", url, self.reader)[1], reviewed)
        self.assertEqual(self.api("GET", "/api/briefs", self.reader)[1][0]["decision"], "approve")
        self.assertEqual(self.api("GET", "/api/metrics", self.reader)[1]["review_approve"], 1)

    def test_reject_abstention_and_invalid_request(self):
        bad = self.api("POST", "/api/briefs", self.reader, {"subject":"Alder"})
        self.assertEqual((bad[0], bad[1]["error"]), (400, "invalid_request"))
        _, brief = self.api("POST", "/api/briefs", self.reader,
                            dict(subject="Alder", period="FY2024", as_of=AS_OF, question="What is the price target?"))
        url = "/api/briefs/" + brief["id"] + "/review"
        self.assertEqual(self.api("POST", url, self.analyst, {"decision":"approve","note":"test"})[0], 409)
        self.assertEqual(self.api("POST", url, self.analyst, {"decision":"reject","note":"Unanswerable"})[0], 200)

    def test_weak_or_identical_credentials(self):
        for args in [("short", self.analyst, self.actor), (self.reader, self.reader, self.actor)]:
            with self.assertRaises(Problem):
                credentials(*args)
