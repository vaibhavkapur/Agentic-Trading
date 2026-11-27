import unittest

from research.domain import Problem, period, resolve, timestamp
from research.ingest import parse
from research.workflow import request_spec


class Contracts(unittest.TestCase):
    def test_resolver(self):
        for term in ("Demo:ALDR", "alder instruments", " ALDR ", "issuer-alder"):
            self.assertEqual(resolve(term)["id"], "issuer-alder")
        with self.assertRaises(Problem):
            resolve("AL")

    def test_dates(self):
        for invalid in ("2025-02-30T00:00:00Z", "2025-03-01", "2025-03-01T00:00:00+00:00"):
            with self.subTest(invalid=invalid), self.assertRaises(Problem):
                timestamp(invalid)
        with self.assertRaises(Problem):
            period("2025-02-29")

    def test_parser_decimal_and_share_count(self):
        def extract(row):
            return parse(("Subject: issuer-alder\nFact|" + row).encode(), resolve("ALDR"))[0]
        self.assertEqual(extract("net_income|FY2024|-0.000125|millions|money|USD")[3], "-125")
        for row in ("shares_outstanding|FY2024|0.5|ones|shares|-", "revenue|FY2024|NaN|ones|money|USD"):
            with self.subTest(row=row), self.assertRaises(Problem):
                extract(row)

    def test_request_schema(self):
        base = dict(subject="ALDR", period="FY2024", as_of="2025-03-15T00:00:00Z")
        for extra in ({}, {"metrics": []}, {"metrics": ["revenue", "revenue"]}, {"metrics": ["revenue"], "question": "x"},
                      {"metrics": ["price_target"]}, {"question": "x", "approved": True}):
            with self.subTest(extra=extra), self.assertRaises(Problem):
                request_spec(dict(base, **extra))
