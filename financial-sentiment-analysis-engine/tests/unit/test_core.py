import math
import unittest
from dataclasses import replace

from tests.support import build, inputs
from sentiment.domain import Article, Invalid, LABELS, canonicalize, instant
from sentiment.models import decision, softmax
from sentiment.evaluation import metrics


class Contracts(unittest.TestCase):
    def test_strict_utc_and_chronology(self):
        for value in ["2025-02-30T00:00:00Z", "2025-01-01", "2025-01-01T00:00:00+01:00", None]:
            with self.subTest(value=value), self.assertRaises(Invalid):
                instant(value)
        row = inputs()[1][0]
        with self.assertRaisesRegex(Invalid, "precedes"):
            Article.parse(dict(row, available_at="2000-01-01T00:00:00Z"))
        for patch in [dict(headline=" "), dict(schema_version="v0"), dict(body=12), dict(extra=0)]:
            with self.assertRaises(Invalid):
                Article.parse(dict(row, **patch))

    def test_replay_conflicting_id_and_normalized_copy(self):
        a = Article.parse(inputs()[1][0])
        b = replace(a, id="z", headline=a.headline.upper()+"  ")
        self.assertEqual(canonicalize([b, a, a]), ([a], {"z":a.id}))
        with self.assertRaisesRegex(Invalid, "Conflicting"):
            canonicalize([a, replace(a, body="revision")])

    def test_confidence_and_probabilities(self):
        p = softmax([1001, 999, 1000, 998], 0.5)
        self.assertAlmostEqual(sum(p), 1)
        self.assertTrue(all(0 < v < 1 for v in p))
        self.assertEqual(decision([.25]*4, None, .48), ("uncertain", "low_confidence"))
        self.assertEqual(decision([0,0,0,1], None, .48), ("uncertain","uncertain_class"))

    def test_perfect_and_wrong_predictions(self):
        rows = [(y,y,[int(k==y) for k in LABELS]) for y in LABELS]
        ideal = metrics(rows)
        self.assertEqual((ideal["macro_f1"],ideal["brier"],ideal["ece"]), (1,0,0))
        y, _, p = rows[0]
        rows[0] = (y,"positive",[0,0,1,0])
        flawed = metrics(rows)
        self.assertAlmostEqual(flawed["ece"], .25)
        self.assertAlmostEqual(flawed["brier"], .5)
        self.assertTrue(math.isfinite(flawed["nll"]))

    def test_model_reproducibility_and_calibration_selection(self):
        a, b = build(), build(lambda articles, labels: labels.reverse())
        self.assertEqual(a.version, b.version)
        self.assertEqual(a.temperature, b.temperature)
        trials = dict(a.trials)
        self.assertEqual(trials[a.temperature], min(trials.values()))

    def test_annotation_integrity(self):
        for patch in [dict(label="bull"), dict(issuer="???"), dict(annotated_at="2000-01-01T00:00:00Z")]:
            with self.subTest(patch=patch), self.assertRaises(Invalid):
                build(lambda a, labels: labels[0].update(patch))
