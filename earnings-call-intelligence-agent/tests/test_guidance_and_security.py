"""M3 tests: prompt-injection defense, adapter verification/budgets, logs, and replay."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from earnings_call_agent.adapters import (
    MockLLMExtractor,
    ProposedClaim,
    export_research_note_envelope,
)
from earnings_call_agent.contracts import (
    AbstentionReason,
    AgentConfig,
    BudgetExceededError,
)
from earnings_call_agent.ingestion import load_transcript_file
from earnings_call_agent.pipeline import (
    analyze_transcript,
    replay_and_verify,
    report_logical_digest,
)


class TestGuidanceAndSecurity(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AgentConfig.from_file(str(PROJECT_ROOT / "config" / "default.json"))
        self.fixtures = PROJECT_ROOT / "data" / "fixtures"

    def test_prompt_injection_quarantined_and_legitimate_claims_preserved(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "prompt_injection.json"))
        report = analyze_transcript(raw, self.config, as_of_timestamp="2026-02-15T12:00:00Z")
        seg_map = {s["segment_id"]: s["text"] for s in raw["segments"]}

        # Must detect multiple injection patterns across seg_m01 and seg_m02
        self.assertGreaterEqual(len(report.prompt_injection_events), 4)
        detected_patterns = {e.pattern_name for e in report.prompt_injection_events}
        self.assertIn("IGNORE_PREVIOUS_INSTRUCTIONS", detected_patterns)
        self.assertIn("TRADE_ACTION_INJECTION", detected_patterns)
        self.assertIn("SYSTEM_PROMPT_OVERRIDE", detected_patterns)
        self.assertIn("TOOL_CALL_SPOOFING", detected_patterns)
        self.assertEqual(report.diagnostics.segments_quarantined, 1)

        # No injected fake numbers ($9,900M or $999M) may enter verified claims
        for claim in report.claims:
            self.assertNotAlmostEqual(claim.normalized_point, 9900.0, places=2)
            self.assertNotAlmostEqual(claim.normalized_point, 999.0, places=2)
            # Verbatim offset invariant must hold even in seg_m01 which had an in-segment quarantined span!
            ev = claim.evidence
            self.assertEqual(seg_map[ev.segment_id][ev.char_start : ev.char_end], ev.exact_quote)

        # Legitimate claims before and after the injection in seg_m01 are still extracted
        seg1_metrics = {(c.metric_name, c.fiscal_period, c.normalized_low) for c in report.claims if c.evidence.segment_id == "seg_m01"}
        self.assertIn(("revenue", "Q4_FY2025", 610.0), seg1_metrics)
        self.assertIn(("revenue", "Q1_FY2026", 620.0), seg1_metrics)

        # Questions targeting injected-only claims abstain with PROMPT_INJECTION_QUARANTINED
        qa_map = {a.question_id: a for a in report.question_answers}
        self.assertFalse(qa_map["q_mrdn_q1_rev"].abstained)
        self.assertTrue(qa_map["q_mrdn_injected_fy26_rev"].abstained)
        self.assertEqual(
            qa_map["q_mrdn_injected_fy26_rev"].abstention_reason,
            AbstentionReason.PROMPT_INJECTION_QUARANTINED,
        )
        self.assertTrue(qa_map["q_mrdn_injected_capex"].abstained)
        self.assertEqual(
            qa_map["q_mrdn_injected_capex"].abstention_reason,
            AbstentionReason.PROMPT_INJECTION_QUARANTINED,
        )

        # Research note adapter enforces no trade actions
        note = export_research_note_envelope(report)
        self.assertFalse(note["trade_action_permitted"])
        self.assertEqual(note["execution_mode"], "research_only_no_orders")
        self.assertTrue(note["prompt_injection_detected"])

    def test_hybrid_llm_adapter_rejects_unverified_and_enforces_budget(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "reference_valid.json"))
        hybrid_dict = self.config.to_dict()
        hybrid_dict["extraction_mode"] = "hybrid"
        hybrid_cfg = AgentConfig.from_dict(hybrid_dict)

        # Propose one hallucinated claim (bad quote) and one valid claim
        seg2_text = raw["segments"][1]["text"]
        quote = "total revenue was $420 million"
        start = seg2_text.index(quote)
        mock_provider = MockLLMExtractor(
            canned_proposals={
                "seg_002": [
                    ProposedClaim(
                        segment_id="seg_002",
                        char_start=0,
                        char_end=20,
                        quoted_text="HALLUCINATED QUOTE!!",
                        claim_type="REPORTED_METRIC",
                        metric_name="revenue",
                        fiscal_period="Q4_FY2025",
                        accounting_basis="GAAP",
                        raw_value_text="$999 million",
                        raw_unit="million",
                        value_low=999.0,
                        value_high=999.0,
                        tokens_used=200,
                    ),
                    ProposedClaim(
                        segment_id="seg_002",
                        char_start=start,
                        char_end=start + len(quote),
                        quoted_text=quote,
                        claim_type="REPORTED_METRIC",
                        metric_name="revenue",
                        fiscal_period="Q4_FY2025",
                        accounting_basis="GAAP",
                        raw_value_text="$420 million",
                        raw_unit="million",
                        value_low=420.0,
                        value_high=420.0,
                        tokens_used=200,
                    ),
                ]
            }
        )

        report = analyze_transcript(
            raw, hybrid_cfg, as_of_timestamp="2026-02-15T12:00:00Z", llm_provider=mock_provider
        )
        self.assertEqual(report.diagnostics.claims_rejected_unverified, 1)
        self.assertGreater(report.diagnostics.llm_calls_used, 0)
        self.assertFalse(any(abs(c.normalized_point - 999.0) < 1e-3 for c in report.claims))

        # Tight call budget raises BudgetExceededError
        tight_dict = hybrid_cfg.to_dict()
        tight_dict["max_llm_calls"] = 1
        tight_cfg = AgentConfig.from_dict(tight_dict)
        with self.assertRaises(BudgetExceededError) as ctx:
            analyze_transcript(
                raw, tight_cfg, as_of_timestamp="2026-02-15T12:00:00Z", llm_provider=mock_provider
            )
        self.assertEqual(ctx.exception.code, "LLM_CALL_BUDGET_EXCEEDED")

    def test_deterministic_replay_and_structured_logs(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "reference_valid.json"))
        r1 = analyze_transcript(raw, self.config, as_of_timestamp="2026-02-15T12:00:00Z")
        d1 = report_logical_digest(r1)

        replay = replay_and_verify(
            raw, self.config, expected_digest=d1, as_of_timestamp="2026-02-15T12:00:00Z"
        )
        self.assertTrue(replay["reproducible_match"])
        self.assertEqual(replay["run_id"], r1.run_id)
        self.assertEqual(replay["logical_digest"], d1)

        stages = [entry["stage"] for entry in r1.structured_logs]
        self.assertEqual(
            stages,
            [
                "ingestion",
                "security_scan",
                "extraction_and_verification",
                "guidance_comparison",
                "question_answering",
            ],
        )


if __name__ == "__main__":
    unittest.main()
