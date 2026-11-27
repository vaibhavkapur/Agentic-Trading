import math
import unittest

from finrag.domain import Fault, Principal, utc
from finrag.index import chunks, dense
from finrag.store import config_values, inspect_manifest, read_json
from tests.support import CONFIG, ROOT


class Contracts(unittest.TestCase):
    def test_utc_normalization_and_rejection(self):
        self.assertEqual(utc("2025-02-13T03:15:12+05:30"), "2025-02-12T21:45:12.000000Z")
        for bad in ("yesterday", "2025-02-30T00:00:00Z", "2025-01-01T00:00:00",
                    "2025-01-01T00:00:00+01:75"):
            with self.subTest(bad=bad), self.assertRaises(Fault):
                utc(bad)

    def test_chunk_offsets_preserve_unicode_and_newlines(self):
        text = "  café βeta  \r\n" + "x" * 35 + "\n\n  ends."
        parts = list(chunks(text, 12))
        for start, end, piece in parts:
            self.assertEqual(piece, text[start:end])
            self.assertLessEqual(end - start, 12)
        self.assertEqual("".join(p.replace(" ", "") for _, _, p in parts), "".join(text.split()))

    def test_dense_adapter_normalized_and_synonym_aware(self):
        vector = dense("capex", 96)
        self.assertEqual(vector, dense("capital expenditure", 96))
        self.assertEqual(dense("sales", 96), dense("revenue", 96))
        self.assertAlmostEqual(math.sqrt(sum(x*x for x in vector)), 1)
        self.assertFalse(any(dense("the", 96)))

    def test_invalid_config_identity_and_manifest(self):
        for invalid in ({"dimensions": True}, {"keyword_weight": float("nan")}, {"candidate_limit": 0}):
            with self.assertRaises(Fault):
                config_values(dict(read_json(CONFIG), **invalid))
        with self.assertRaises(Fault):
            Principal.parse({"tenant": "fund", "groups": "admin"})
        manifest = ROOT / "data/fixtures/manifest.json"
        for change in ({"version": 3}, {"available_at": "2020-01-01T00:00:00Z"},
                       {"audience": "other"}, {"sha256": "no"}):
            data = read_json(manifest)
            data["events"][-2].update(change)
            with self.subTest(change=change), self.assertRaises(Fault):
                inspect_manifest(data)
