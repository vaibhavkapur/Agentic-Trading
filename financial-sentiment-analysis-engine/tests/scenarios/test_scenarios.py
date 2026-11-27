import unittest
from dataclasses import replace

from tests.support import build
from sentiment.domain import Invalid, instant


class Scenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = build()

    def feed(self, end, as_of=None):
        return self.engine.feed(instant(as_of or end), instant(end))

    def test_duplicate_syndicated_articles(self):
        result = self.feed("2025-04-19T00:00:00Z","2025-04-22T00:00:00Z")
        self.assertEqual(self.engine.reference.copies["note-078"], "note-077")
        self.assertEqual([r["article_id"] for r in result["decisions"]], ["note-077"])
        self.assertEqual(result["aggregates"][0]["article_count"], 1)

    def test_headline_body_disagreement(self):
        result = self.feed("2025-04-22T00:00:00Z")
        decision = next(r for r in result["decisions"] if r["article_id"]=="note-079")
        self.assertEqual(decision["abstain_reason"], "headline_body_conflict")
        self.assertIsNone(decision["sentiment"])
        agg = next(r for r in result["aggregates"] if r["issuer"]=="HBR")
        self.assertEqual(agg["used_count"], 0)
        self.assertIsNone(agg["mean_sentiment"])

    def test_entity_ambiguity_and_word_boundaries(self):
        self.assertEqual(self.engine.reference.issues["note-080"], ["ambiguous_alias"])
        self.assertFalse(self.engine.reference.mentions["note-080"])
        a = replace(self.engine.reference.articles[0],headline="Novalumex raised guidance",body="")
        self.assertEqual(self.engine.linker.link(a), ([], ["unlinked"]))
        a = replace(a, headline="NVL and HBR announce a joint surplus")
        mentions, _ = self.engine.linker.link(a)
        self.assertEqual({m.issuer for m in mentions}, {"NVL","HBR"})
        self.assertTrue(all(self.engine.score(a,m)["abstain_reason"]=="shared_clause" for m in mentions))

    def test_sarcasm(self):
        result = self.feed("2025-04-22T00:00:00Z")
        decision = next(r for r in result["decisions"] if r["article_id"]=="note-081")
        self.assertEqual((decision["label"],decision["abstain_reason"]), ("uncertain","sarcasm_cue"))

    def test_late_article_keeps_historical_snapshot(self):
        end = "2025-04-19T00:00:00Z"
        first = self.feed(end)
        self.assertFalse(first["decisions"])
        self.assertFalse(self.feed(end,"2025-04-20T11:59:59Z")["decisions"])
        new = self.feed(end,"2025-04-20T12:00:00Z")
        self.assertEqual(new["decisions"][0]["available_at"], new["available_at"])
        self.assertLess(new["decisions"][0]["event_at"], end)
        self.assertEqual(first,self.feed(end))

    def test_leakage_in_test_text_and_labels(self):
        def change(articles, labels):
            articles[-2]["body"] += " Novalume unprecedentedtestword."
            labels[-1]["label"] = "neutral"
        other = build(change)
        self.assertEqual(self.engine.version, other.version)
        self.assertEqual(self.engine.classifier.vocab, other.classifier.vocab)
        self.assertNotIn("unprecedentedtestword",other.classifier.vocab)
        self.assertEqual(self.engine.trials,other.trials)
        self.assertNotIn("note-083",[s.article.id for s in other.splits["test"]])
        with self.assertRaisesRegex(Invalid,"completed calibration"):
            self.feed("2025-03-01T00:00:00Z")

    def test_delayed_label_excluded_at_training_boundary(self):
        eng = build(lambda a, labels: labels[0].update(annotated_at="2025-03-01T00:00:00Z"))
        self.assertIn(("note-001","NVL"),eng.delayed_labels)
        self.assertEqual(len(eng.splits["train"]),39)
        self.assertFalse(any(s.article.id=="note-001" for rows in eng.splits.values() for s in rows))

    def test_multi_issuer_directions_and_window_edges(self):
        result = self.feed("2025-04-23T00:00:00Z")
        scores = {r["issuer"]:r["mean_sentiment"] for r in result["aggregates"]}
        self.assertGreater(scores["NVL"],0)
        self.assertLess(scores["HBR"],0)
        end = "2025-04-22T08:00:00Z"
        self.assertNotIn("note-082",[r["article_id"] for r in self.feed(end,"2025-04-23T09:00:00Z")["decisions"]])
        self.assertEqual(len(self.feed("2025-04-23T08:00:00Z")["decisions"]),2)
