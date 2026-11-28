"""M4 tests: gold fixture evaluation F1 & citation validity, stale/unanswerable boundaries, CLI."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from earnings_call_agent.cli import main as cli_main
from earnings_call_agent.contracts import AbstentionReason, AgentConfig
from earnings_call_agent.evaluation import evaluate_gold_suite, load_json_file
from earnings_call_agent.ingestion import load_transcript_file
from earnings_call_agent.pipeline import analyze_transcript


class TestEvaluationAndBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AgentConfig.from_file(str(PROJECT_ROOT / "config" / "default.json"))
        self.eval_cfg = load_json_file(str(PROJECT_ROOT / "config" / "eval.json"))
        self.fixtures = PROJECT_ROOT / "data" / "fixtures"

    def test_gold_evaluation_suite_meets_all_targets(self) -> None:
        suite = load_json_file(str(self.fixtures / "gold_eval_suite.json"))
        result = evaluate_gold_suite(suite, self.config, self.eval_cfg)

        metrics = result["summary_metrics"]
        self.assertTrue(result["all_targets_met"], f"Eval failed targets: {result['target_checks']} / {metrics}")
        self.assertGreaterEqual(metrics["extraction_f1"], 0.85)
        self.assertEqual(metrics["citation_validity_rate"], 1.0)
        self.assertEqual(metrics["qa_and_abstention_accuracy"], 1.0)
        self.assertEqual(metrics["injection_detection_accuracy"], 1.0)
        self.assertEqual(metrics["guidance_accuracy"], 1.0)

    def test_stale_source_and_unanswerable_boundary(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "stale_and_unanswerable.json"))
        # Evaluated > 650 days after publication
        report_stale = analyze_transcript(raw, self.config, as_of_timestamp="2026-02-15T12:00:00Z")

        self.assertTrue(report_stale.source_freshness["is_stale"])
        self.assertGreater(report_stale.source_freshness["age_days"], 90.0)
        self.assertTrue(any(w.startswith("STALE_SOURCE") for w in report_stale.warnings))
        for comp in report_stale.guidance_comparisons:
            self.assertIn("STALE_SOURCE", comp.uncertainty_flags)
        for ans in report_stale.question_answers:
            self.assertTrue(ans.abstained)
            self.assertEqual(ans.abstention_reason, AbstentionReason.STALE_SOURCE)

        # Evaluated on a fresh date: supported question answered, unanswerable M&A question abstained
        report_fresh = analyze_transcript(raw, self.config, as_of_timestamp="2024-05-15T12:00:00Z")
        self.assertFalse(report_fresh.source_freshness["is_stale"])
        qa_map = {a.question_id: a for a in report_fresh.question_answers}
        self.assertFalse(qa_map["q_nstl_stale_rev"].abstained)
        self.assertTrue(qa_map["q_nstl_unanswerable_ma"].abstained)
        self.assertEqual(
            qa_map["q_nstl_unanswerable_ma"].abstention_reason,
            AbstentionReason.NO_SUPPORTING_EVIDENCE,
        )

    def test_cli_operational_checks_and_no_silent_failure(self) -> None:
        # 1. Valid config
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            rc = cli_main(["validate-config", "--config", str(PROJECT_ROOT / "config" / "default.json")])
        self.assertEqual(rc, 0)
        parsed = json.loads(out_buf.getvalue())
        self.assertTrue(parsed["valid"])

        # 2. Missing config fails loudly with exit code 1 and structured JSON on stderr
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            rc_err = cli_main(["validate-config", "--config", str(PROJECT_ROOT / "config" / "missing.json")])
        self.assertEqual(rc_err, 1)
        err_parsed = json.loads(err_buf.getvalue())
        self.assertEqual(err_parsed["code"], "MISSING_CONFIG_FILE")

        # 3. Replay CLI exits 0 on valid deterministic replay
        out_replay = io.StringIO()
        with redirect_stdout(out_replay):
            rc_rep = cli_main(
                [
                    "replay",
                    "--input",
                    str(self.fixtures / "reference_valid.json"),
                    "--as-of",
                    "2026-02-15T12:00:00Z",
                ]
            )
        self.assertEqual(rc_rep, 0)
        rep_data = json.loads(out_replay.getvalue())
        self.assertTrue(rep_data["reproducible_match"])


if __name__ == "__main__":
    unittest.main()
