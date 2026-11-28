"""Tests for typed data contracts, canonical hashing, valid/invalid/boundary fixtures."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_investment_committee.errors import (
    NoExecutionCapabilityError,
    SchemaValidationError,
    UnsupportedInputError,
)
from ai_investment_committee.hashing import compute_proposal_hash
from ai_investment_committee.models import Claim, CommitteeConfig, CommitteeProposal
from ai_investment_committee.state_machine import run_deliberation

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"

ERROR_MAP = {
    "NoExecutionCapabilityError": NoExecutionCapabilityError,
    "SchemaValidationError": SchemaValidationError,
    "UnsupportedInputError": UnsupportedInputError,
}


def _deep_merge(base: dict, patch: dict) -> dict:
    result = copy.deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


class TestContractsAndFixtures(unittest.TestCase):
    def setUp(self) -> None:
        self.reference_raw = json.loads((FIXTURES_DIR / "valid_reference_proposal.json").read_text())
        self.config_raw = json.loads((CONFIG_DIR / "committee_default.json").read_text())

    def test_valid_reference_fixture_and_canonical_hash_stability(self) -> None:
        proposal = CommitteeProposal.model_validate(self.reference_raw)
        self.assertEqual(proposal.proposal_id, "PROP-2026-001")
        self.assertEqual(proposal.execution_mode, "PAPER")
        self.assertEqual(proposal.candidate_position.trade_notional_usd, 50000.0)

        h1 = compute_proposal_hash(proposal.model_dump())
        reordered = {k: self.reference_raw[k] for k in reversed(list(self.reference_raw.keys()))}
        h2 = compute_proposal_hash(CommitteeProposal.model_validate(reordered).model_dump())
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_all_invalid_input_fixture_cases_raise_expected_errors(self) -> None:
        invalid_doc = json.loads((FIXTURES_DIR / "invalid_inputs.json").read_text())
        for case in invalid_doc["cases"]:
            with self.subTest(case_id=case["case_id"]):
                mutated = copy.deepcopy(self.reference_raw)
                if "patch" in case:
                    mutated = _deep_merge(mutated, case["patch"])
                for key in case.get("delete_keys", []):
                    mutated.pop(key, None)
                expected_cls = ERROR_MAP[case["expected_error"]]
                with self.assertRaises(expected_cls):
                    CommitteeProposal.model_validate(mutated)

    def test_boundary_exact_policy_limits_pass(self) -> None:
        boundary_doc = json.loads((FIXTURES_DIR / "boundary_inputs.json").read_text())
        proposal = CommitteeProposal.model_validate(boundary_doc["exact_policy_limits_proposal"])
        config = CommitteeConfig.model_validate(self.config_raw)
        trace = run_deliberation(proposal=proposal, config=config)

        metrics = trace.decision.risk_verdict.metrics
        self.assertEqual(metrics["pro_forma_ticker_weight_pct"], 10.0)
        self.assertEqual(metrics["pro_forma_sector_weight_pct"], 25.0)
        self.assertEqual(metrics["pro_forma_cash_reserve_pct"], 10.0)
        self.assertEqual(metrics["adv_participation_pct"], 5.0)
        self.assertEqual(trace.decision.risk_verdict.verdict, "PASS")
        self.assertEqual(trace.decision.status, "AWAITING_HUMAN_APPROVAL")

    def test_claim_without_citation_or_uncertainty_flag_rejected(self) -> None:
        with self.assertRaises(SchemaValidationError):
            Claim(
                claim_id="BAD-1",
                author_role="bull",
                statement="Revenue will double next quarter.",
                evidence_ids=(),
                is_uncertain=False,
            )

        with self.assertRaises(SchemaValidationError):
            Claim(
                claim_id="BAD-2",
                author_role="bull",
                statement="Revenue may accelerate.",
                evidence_ids=(),
                is_uncertain=True,
                uncertainty_reason="",
            )


if __name__ == "__main__":
    unittest.main()
