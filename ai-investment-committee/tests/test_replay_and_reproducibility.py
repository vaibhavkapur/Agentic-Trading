"""Replay, reproducibility, evaluation, and CLI end-to-end tests."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_investment_committee.cli import main as cli_main
from ai_investment_committee.models import CommitteeConfig, CommitteeProposal
from ai_investment_committee.service import InvestmentCommitteeService
from ai_investment_committee.state_machine import run_deliberation

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


class TestReplayAndReproducibility(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "replay.sqlite3"
        self.config_path = CONFIG_DIR / "committee_default.json"
        self.ref_fixture_path = FIXTURES_DIR / "valid_reference_proposal.json"
        self.ref_raw = json.loads(self.ref_fixture_path.read_text())
        self.config_raw = json.loads(self.config_path.read_text())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_same_inputs_config_and_seed_produce_matching_logical_outputs(self) -> None:
        proposal = CommitteeProposal.model_validate(self.ref_raw)
        config = CommitteeConfig.model_validate(self.config_raw)

        t1 = run_deliberation(
            proposal=proposal,
            config=config,
            created_at_override="2026-11-28T09:00:00Z",
        )
        t2 = run_deliberation(
            proposal=proposal,
            config=config,
            created_at_override="2026-11-28T09:00:00Z",
        )
        self.assertEqual(t1.model_dump(), t2.model_dump())

    def test_sqlite_replay_captures_decision_and_budget(self) -> None:
        service = InvestmentCommitteeService.from_config_path(
            config_path=self.config_path,
            db_path=self.db_path,
        )
        trace = service.deliberate(self.ref_raw)
        replay_report = service.replay(trace.decision_id)

        self.assertTrue(replay_report["exact_match"])
        self.assertEqual(replay_report["mismatches"], [])
        self.assertEqual(replay_report["recorded_verdict"], "PASS")
        self.assertEqual(replay_report["replayed_verdict"], "PASS")
        self.assertGreater(replay_report["recorded_budget"]["tool_calls"], 0)
        self.assertGreater(replay_report["recorded_budget"]["tokens"], 0)
        self.assertGreater(replay_report["recorded_budget"]["cost_usd"], 0.0)
        self.assertEqual(
            replay_report["recorded_budget"],
            replay_report["replayed_budget"],
        )

        eval_metrics = service.evaluate(trace.decision_id)
        self.assertTrue(eval_metrics.all_claims_cited_or_uncertain)
        self.assertTrue(eval_metrics.dissent_present)
        self.assertEqual(eval_metrics.unsupported_claims, 0)
        self.assertEqual(eval_metrics.fabricated_citations, 0)

    def test_cli_end_to_end_run_approve_replay_evaluate_and_duplicate_error(self) -> None:
        def _invoke(argv: list) -> tuple:
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                rc = cli_main(argv)
            return rc, out_buf.getvalue(), err_buf.getvalue()

        base_args = ["--config", str(self.config_path), "--db", str(self.db_path)]
        rc, out, err = _invoke(base_args + ["run", "--proposal", str(self.ref_fixture_path)])
        self.assertEqual(rc, 0, msg=err)
        run_payload = json.loads(out)
        decision_id = run_payload["decision_id"]
        proposal_hash = run_payload["proposal_hash"]

        rc, out, err = _invoke(
            base_args
            + [
                "approve",
                "--decision-id",
                decision_id,
                "--approval-id",
                "CLI-APP-001",
                "--proposal-id",
                "PROP-2026-001",
                "--proposal-hash",
                proposal_hash,
                "--reviewer-id",
                "cli-reviewer",
                "--decision",
                "APPROVE_PAPER",
                "--rationale",
                "Verified via CLI smoke test.",
            ]
        )
        self.assertEqual(rc, 0, msg=err)
        approved_payload = json.loads(out)
        self.assertEqual(approved_payload["decision"]["status"], "APPROVED_FOR_PAPER_ONLY")

        # Duplicate approval via CLI must return non-zero exit code and structured error JSON.
        rc, out, err = _invoke(
            base_args
            + [
                "approve",
                "--decision-id",
                decision_id,
                "--approval-id",
                "CLI-APP-001",
                "--proposal-id",
                "PROP-2026-001",
                "--proposal-hash",
                proposal_hash,
                "--reviewer-id",
                "cli-reviewer",
                "--decision",
                "APPROVE_PAPER",
                "--rationale",
                "Duplicate CLI attempt.",
            ]
        )
        self.assertEqual(rc, 1)
        err_payload = json.loads(err)
        self.assertEqual(err_payload["error_code"], "DUPLICATE_APPROVAL")

        rc, out, err = _invoke(base_args + ["replay", "--decision-id", decision_id])
        self.assertEqual(rc, 0, msg=err)
        self.assertTrue(json.loads(out)["exact_match"])

        rc, out, err = _invoke(base_args + ["evaluate", "--decision-id", decision_id])
        self.assertEqual(rc, 0, msg=err)
        self.assertTrue(json.loads(out)["all_claims_cited_or_uncertain"])


if __name__ == "__main__":
    unittest.main()
