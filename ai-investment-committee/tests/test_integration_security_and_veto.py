"""Integration security tests: prompt injection quarantine, non-overridable risk veto, hash-bound approval."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_investment_committee.errors import (
    ProposalHashMismatchError,
    RiskVetoBypassError,
)
from ai_investment_committee.models import CommitteeConfig, HumanApprovalRecord
from ai_investment_committee.replay import evaluate_deliberation
from ai_investment_committee.service import InvestmentCommitteeService
from ai_investment_committee.storage import DeliberationStore

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


class TestIntegrationSecurityAndVeto(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "committee.sqlite3"
        self.config = CommitteeConfig.model_validate(
            json.loads((CONFIG_DIR / "committee_default.json").read_text())
        )
        self.service = InvestmentCommitteeService(
            config=self.config,
            store=DeliberationStore(self.db_path),
        )
        self.inject_proposal_raw = json.loads(
            (FIXTURES_DIR / "prompt_injection_risk_veto.json").read_text()
        )
        self.ref_proposal_raw = json.loads(
            (FIXTURES_DIR / "valid_reference_proposal.json").read_text()
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_prompt_injection_quarantined_and_risk_veto_enforced(self) -> None:
        trace = self.service.deliberate(self.inject_proposal_raw)
        metrics = evaluate_deliberation(trace)

        # Prompt injection attempts detected & sanitized in untrusted briefs.
        self.assertGreaterEqual(metrics.prompt_injection_attempts_detected, 2)
        self.assertTrue(len(trace.decision.thesis.injection_flags) >= 2)
        self.assertTrue(all(c.is_uncertain for c in trace.decision.thesis.claims))
        self.assertTrue(metrics.all_claims_cited_or_uncertain)

        # Deterministic risk veto fires on all breached policy thresholds.
        self.assertEqual(trace.decision.risk_verdict.verdict, "VETO")
        self.assertTrue(trace.decision.risk_verdict.non_overridable)
        self.assertEqual(trace.decision.status, "VETOED")
        violated = set(trace.decision.risk_verdict.violated_rules)
        self.assertIn("MAX_SINGLE_POSITION_WEIGHT_PCT", violated)
        self.assertIn("MAX_SECTOR_WEIGHT_PCT", violated)
        self.assertIn("MIN_CASH_RESERVE_PCT", violated)
        self.assertIn("MAX_ADV_PARTICIPATION_PCT", violated)
        self.assertIn("MAX_ESTIMATED_VAR_95_PCT", violated)

        # Even a human reviewer with the exact proposal hash CANNOT bypass a deterministic VETO.
        bypass_attempt = HumanApprovalRecord(
            approval_id="APP-BYPASS-001",
            proposal_id=trace.proposal_id,
            proposal_hash=trace.proposal_hash,
            reviewer_id="human-pm-01",
            decision="APPROVE_PAPER",
            rationale="Attempting to override deterministic risk veto.",
            approved_at="2026-11-28T09:20:00Z",
        )
        with self.assertRaises(RiskVetoBypassError):
            self.service.submit_human_approval(
                decision_id=trace.decision_id,
                approval_input=bypass_attempt,
            )

        # Confirm stored status remains VETOED and no approval was persisted.
        stored_trace, _, _ = self.service.store.get_deliberation(trace.decision_id)
        self.assertEqual(stored_trace.decision.status, "VETOED")
        self.assertIsNone(stored_trace.decision.human_approval)

    def test_human_approval_bound_to_canonical_proposal_hash(self) -> None:
        trace = self.service.deliberate(self.ref_proposal_raw)
        self.assertEqual(trace.decision.status, "AWAITING_HUMAN_APPROVAL")
        self.assertEqual(trace.decision.execution_capability, "NONE_PAPER_ONLY")

        # Tampered or stale proposal hash must be rejected.
        wrong_hash_approval = HumanApprovalRecord(
            approval_id="APP-WRONG-HASH",
            proposal_id=trace.proposal_id,
            proposal_hash="0" * 64,
            reviewer_id="human-pm-01",
            decision="APPROVE_PAPER",
            rationale="Stale hash approval attempt.",
            approved_at="2026-11-28T09:21:00Z",
        )
        with self.assertRaises(ProposalHashMismatchError):
            self.service.submit_human_approval(
                decision_id=trace.decision_id,
                approval_input=wrong_hash_approval,
            )

        # Valid canonical hash succeeds and remains paper-only.
        valid_approval = HumanApprovalRecord(
            approval_id="APP-VALID-001",
            proposal_id=trace.proposal_id,
            proposal_hash=trace.proposal_hash,
            reviewer_id="human-pm-01",
            decision="APPROVE_PAPER",
            rationale="Reviewed bull, bear, portfolio, and deterministic risk checks; approved for paper ledger only.",
            approved_at="2026-11-28T09:22:00Z",
        )
        approved_trace = self.service.submit_human_approval(
            decision_id=trace.decision_id,
            approval_input=valid_approval,
        )
        self.assertEqual(approved_trace.decision.status, "APPROVED_FOR_PAPER_ONLY")
        self.assertEqual(approved_trace.decision.execution_capability, "NONE_PAPER_ONLY")
        self.assertEqual(approved_trace.decision.human_approval.approval_id, "APP-VALID-001")


if __name__ == "__main__":
    unittest.main()
