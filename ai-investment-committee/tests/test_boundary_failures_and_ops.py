"""Boundary, failure, and operational tests: timeout, duplicate approval, missing config, restart."""

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
    AgentTimeoutError,
    DuplicateApprovalError,
    MissingConfigurationError,
    UnsupportedInputError,
)
from ai_investment_committee.models import CommitteeConfig, HumanApprovalRecord
from ai_investment_committee.service import InvestmentCommitteeService
from ai_investment_committee.storage import DeliberationStore

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


class TestBoundaryFailuresAndOps(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "committee_ops.sqlite3"
        self.config_path = CONFIG_DIR / "committee_default.json"
        self.ref_proposal_raw = json.loads(
            (FIXTURES_DIR / "valid_reference_proposal.json").read_text()
        )
        self.service = InvestmentCommitteeService.from_config_path(
            config_path=self.config_path,
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_agent_timeout_fails_explicitly_with_diagnostics(self) -> None:
        with self.assertRaises(AgentTimeoutError) as ctx:
            self.service.deliberate(
                self.ref_proposal_raw,
                simulated_role_delay_ms={"bear": 2000},
            )
        err = ctx.exception.to_dict()
        self.assertEqual(err["error_code"], "AGENT_TIMEOUT")
        self.assertEqual(err["details"]["role"], "bear")
        self.assertEqual(self.service.counters["errors_raised"], 1)
        # Ensure nothing was silently persisted as succeeded.
        self.assertEqual(self.service.store.list_deliberations(), [])

    def test_duplicate_approval_rejected_same_id_and_second_id_after_restart(self) -> None:
        trace = self.service.deliberate(self.ref_proposal_raw)
        first_approval = HumanApprovalRecord(
            approval_id="APP-DUP-001",
            proposal_id=trace.proposal_id,
            proposal_hash=trace.proposal_hash,
            reviewer_id="human-pm-01",
            decision="APPROVE_PAPER",
            rationale="Initial approval.",
            approved_at="2026-11-28T09:25:00Z",
        )
        self.service.submit_human_approval(
            decision_id=trace.decision_id,
            approval_input=first_approval,
        )

        # Duplicate with identical approval_id fails.
        with self.assertRaises(DuplicateApprovalError):
            self.service.submit_human_approval(
                decision_id=trace.decision_id,
                approval_input=first_approval,
            )

        # Simulate process restart by instantiating a brand new service over the same SQLite DB.
        restarted_service = InvestmentCommitteeService.from_config_path(
            config_path=self.config_path,
            db_path=self.db_path,
        )
        second_approval = HumanApprovalRecord(
            approval_id="APP-DUP-002",
            proposal_id=trace.proposal_id,
            proposal_hash=trace.proposal_hash,
            reviewer_id="human-pm-02",
            decision="APPROVE_PAPER",
            rationale="Second approval attempt after restart.",
            approved_at="2026-11-28T09:26:00Z",
        )
        with self.assertRaises(DuplicateApprovalError):
            restarted_service.submit_human_approval(
                decision_id=trace.decision_id,
                approval_input=second_approval,
            )

    def test_missing_or_corrupt_configuration_raises_explicit_error(self) -> None:
        with self.assertRaises(MissingConfigurationError):
            InvestmentCommitteeService.from_config_path(
                config_path=Path(self.tmpdir.name) / "nonexistent_config.json",
                db_path=self.db_path,
            )

        bad_json = Path(self.tmpdir.name) / "corrupt.json"
        bad_json.write_text("{invalid json", encoding="utf-8")
        with self.assertRaises(MissingConfigurationError):
            InvestmentCommitteeService.from_config_path(
                config_path=bad_json,
                db_path=self.db_path,
            )

    def test_unsupported_adapter_mode_and_schema_version_rejected(self) -> None:
        raw_cfg = json.loads(self.config_path.read_text())
        raw_cfg["adapter_mode"] = "live_openai_production"
        with self.assertRaises(UnsupportedInputError):
            CommitteeConfig.model_validate(raw_cfg)

        bad_schema = dict(self.ref_proposal_raw)
        bad_schema["schema_version"] = "2.0.0"
        with self.assertRaises(UnsupportedInputError):
            self.service.deliberate(bad_schema)


if __name__ == "__main__":
    unittest.main()
