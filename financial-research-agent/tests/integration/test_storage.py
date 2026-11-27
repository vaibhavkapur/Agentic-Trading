import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from research.domain import ROOT, Problem
from research.ingest import ingest
from research.store import connect
from research.workflow import decide, get_brief, source
from tests.support import AS_OF, DatabaseCase, MANIFEST


class Storage(DatabaseCase):
    def test_idempotent_and_reopened(self):
        self.assertEqual(ingest(self.db, MANIFEST), {"added": 0, "unchanged": 5})
        a = self.query()
        b = self.query(subject="DEMO:ALDR")
        self.assertEqual(a, b)
        c = a["result"]["items"][0]["citations"][0]
        with closing(connect(self.path)) as db:
            self.assertEqual(source(db, c["document"], c["line"])["text"], c["passage"])
            self.assertEqual(get_brief(db, a["id"]), a)

    def test_manifest_atomic_on_failure(self):
        path = self.inject_manifest(lambda m: None)
        batch = json.loads(path.read_text())
        batch["documents"].append(dict(batch["documents"][0], id="fork", revision=2))
        path.write_text(json.dumps(batch))
        with self.assertRaises(Problem) as error:
            ingest(self.db, path)
        self.assertEqual(error.exception.code, "invalid_revision")
        self.assertFalse(self.db.execute("SELECT id FROM documents WHERE id='extra'").fetchone())

    def test_entitlement_digest_path(self):
        for change, expected in [({"license": "unknown"}, "unentitled"), ({"path": "../other.txt"}, "invalid_path"),
                                 ({"sha256": "0" * 64}, "integrity_error")]:
            with self.subTest(change=change):
                path = self.inject_manifest(lambda m: m.update(change))
                with self.assertRaises(Problem) as error:
                    ingest(self.db, path)
                self.assertEqual(error.exception.code, expected)

    def test_replacement_can_withdraw_metric(self):
        path = self.inject_manifest(lambda m: m.update(series="alder-annual", revision=3, supersedes="alder-annual-v2",
                                                      published="2025-03-05T12:00:00Z", retrieved="2025-03-05T12:00:00Z"),
                                    b"Subject: issuer-alder\nFact|revenue|FY2024|118|millions|money|USD")
        ingest(self.db, path)
        self.assertEqual(self.query(metrics=["net_income"])["result"]["items"][0]["status"], "missing_evidence")

    def test_review_race(self):
        brief = self.query()
        def review(actor):
            with closing(connect(self.path)) as db:
                try:
                    decide(db, brief["id"], "approve", "Checked passage", actor)
                    return "saved"
                except Problem as error:
                    return error.code
        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(pool.map(review, ["alice", "bob"]), ["saved", "already_reviewed"])
        self.assertIn(get_brief(self.db, brief["id"])["review"]["actor"], ["alice", "bob"])

    def test_cli_from_outside_checkout(self):
        run = subprocess.run([str(ROOT / "bin/research"), "--db", str(self.path), "ask", "Northland", "2025-03-12",
                              "What was policy rate?", "--as-of", AS_OF], cwd=self.base, capture_output=True, check=True)
        item = json.loads(run.stdout)["result"]["items"][0]
        self.assertEqual((item["value"], item["unit"], item["currency"]), ("3.25", "percent", None))
