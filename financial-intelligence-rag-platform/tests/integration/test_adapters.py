from concurrent.futures import ThreadPoolExecutor

from finrag.domain import Fault, digest
from finrag.service import dispatch
from tests.support import Corpus, NOW, PUBLIC


class Adapters(Corpus):
    def test_exact_version_hash_offsets_and_rebuild(self):
        before = self.ask(op="search", k=20)
        self.build()
        self.assertEqual(before, self.ask(op="search", k=20))
        for hit in before["hits"]:
            citation = self.resolve(hit)
            obj = next(e for e in self.history["events"] if e.get("sha256")==citation["sha256"])
            raw = (self.manifest.parent / obj["path"]).read_bytes()
            self.assertEqual(digest(raw), hit["sha256"])
            self.assertEqual(raw.decode()[hit["start"]:hit["end"]], hit["passage"])

    def test_rebuild_rejects_rewrites_and_rolls_back_on_bad_object(self):
        before = self.ask()
        for history in (dict(self.history, events=self.history["events"][:-1]),
                        dict(self.history, events=self.history["events"][1:])):
            with self.assertRaises(Fault):
                self.build(history)
        path = self.manifest.parent / self.history["events"][-2]["path"]
        path.write_text("tampered")
        with self.assertRaisesRegex(Fault, "hash mismatch"):
            self.build(self.history)
        self.assertEqual(self.ask(), before)

    def test_overlapping_builds_and_reads(self):
        expected = self.ask()
        with ThreadPoolExecutor(3) as pool:
            writes = [pool.submit(self.build) for _ in range(2)]
            self.assertEqual(pool.submit(self.ask).result(), expected)
            self.assertEqual(writes[0].result(), writes[1].result())
        self.assertEqual(self.ask(), expected)

    def test_metadata_filters_and_source_comparison(self):
        filters = {"issuer":"aster grid","period":"FY2024","kind":"research","doc_id":"aster-note"}
        hits = self.ask(op="search", filters=filters)["hits"]
        self.assertEqual({r["doc_id"] for r in hits}, {"aster-note"})
        question = "Compare Aster Grid's revenue in FY2024 across sources."
        result = self.ask(question)
        self.assertEqual(result["comparison"], "different_reported_values")
        self.assertEqual({c["citation"]["doc_id"] for c in result["claims"]}, {"aster-24","aster-note"})
        self.assertEqual(self.ask(question, filters=filters)["reason"], "insufficient_sources")

    def test_malformed_queries_fail_closed(self):
        for change in ({"filters":{"tenant":"other-fund"}}, {"k":True}, {"as_of":"2999-01-01T00:00:00Z"},
                       {"query":" "}, {"groups":["portfolio"]}):
            req = dict({"query":"revenue", "as_of":NOW}, **change)
            with self.assertRaises(Fault):
                dispatch(self.db, PUBLIC, "search", req)
        with self.assertRaisesRegex(Fault, "Index unavailable"):
            dispatch(self.folder/"missing", PUBLIC, "search", {"query":"revenue", "as_of":NOW})
