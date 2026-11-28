"""M1 tests: canonical data contracts, validation errors, and segmented transcript ingestion."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from earnings_call_agent.contracts import (
    AgentConfig,
    BudgetExceededError,
    CanonicalUnit,
    ConfigurationError,
    EarningsCallAgentError,
    UnsupportedInputError,
    normalize_fiscal_period,
    normalize_unit_and_value,
)
from earnings_call_agent.ingestion import ingest_transcript, load_transcript_file


class TestContractsAndIngestion(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AgentConfig.from_file(str(PROJECT_ROOT / "config" / "default.json"))
        self.fixtures = PROJECT_ROOT / "data" / "fixtures"

    def test_valid_reference_ingestion_and_metadata(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "reference_valid.json"))
        ingested = ingest_transcript(raw, self.config, as_of_timestamp="2026-02-15T12:00:00Z")

        self.assertEqual(ingested.transcript.ticker, "ACME")
        self.assertEqual(ingested.transcript.fiscal_period, "Q4_FY2025")
        self.assertEqual(len(ingested.transcript.segments), 5)
        self.assertEqual(len(ingested.transcript.prior_guidance), 3)
        self.assertFalse(ingested.freshness.is_stale)
        self.assertGreater(ingested.freshness.age_days, 0.0)
        self.assertEqual(len(ingested.injection_events), 0)
        self.assertEqual(len(ingested.input_digest), 64)

    def test_invalid_inputs_raise_structured_errors(self) -> None:
        invalid_suite = json.loads((self.fixtures / "invalid_inputs.json").read_text(encoding="utf-8"))
        for case in invalid_suite["cases"]:
            with self.subTest(case=case["case_name"]):
                with self.assertRaises(EarningsCallAgentError) as ctx:
                    ingest_transcript(case["payload"], self.config)
                self.assertEqual(ctx.exception.code, case["expected_error_code"])

    def test_unit_and_period_normalization(self) -> None:
        self.assertEqual(normalize_unit_and_value("usd_billions", 1.85), (CanonicalUnit.USD_MILLIONS, 1850.0))
        self.assertEqual(normalize_unit_and_value("thousand", 500.0), (CanonicalUnit.USD_MILLIONS, 0.5))
        self.assertEqual(normalize_unit_and_value("bps", 150.0), (CanonicalUnit.BPS, 150.0))
        self.assertEqual(normalize_fiscal_period("1Q26"), "Q1_FY2026")
        self.assertEqual(normalize_fiscal_period("FY26"), "FY2026")
        self.assertEqual(normalize_fiscal_period("CY2026"), "CY2026")

        with self.assertRaises(UnsupportedInputError):
            normalize_unit_and_value("gold_bars", 10.0)
        with self.assertRaises(UnsupportedInputError):
            normalize_fiscal_period("NEXT_DECADE")

    def test_segment_budget_enforced(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "reference_valid.json"))
        tight_cfg_dict = self.config.to_dict()
        tight_cfg_dict["max_segments"] = 2
        tight_cfg = AgentConfig.from_dict(tight_cfg_dict)

        with self.assertRaises(BudgetExceededError) as ctx:
            ingest_transcript(raw, tight_cfg)
        self.assertEqual(ctx.exception.code, "SEGMENT_BUDGET_EXCEEDED")

    def test_config_safety_policy_invariants(self) -> None:
        bad_trade = self.config.to_dict()
        bad_trade["allow_trade_actions"] = True
        with self.assertRaises(ConfigurationError) as ctx:
            AgentConfig.from_dict(bad_trade)
        self.assertEqual(ctx.exception.code, "POLICY_VIOLATION")

        bad_ev = self.config.to_dict()
        bad_ev["require_verified_evidence"] = False
        with self.assertRaises(ConfigurationError):
            AgentConfig.from_dict(bad_ev)

        with self.assertRaises(ConfigurationError) as ctx2:
            AgentConfig.from_file(str(PROJECT_ROOT / "config" / "does_not_exist.json"))
        self.assertEqual(ctx2.exception.code, "MISSING_CONFIG_FILE")


if __name__ == "__main__":
    unittest.main()
