"""M2 tests: pure domain extraction, evidence spans, contradictory guidance, units & periods."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from earnings_call_agent.contracts import (
    AccountingBasis,
    AgentConfig,
    CanonicalUnit,
    GuidanceDirection,
)
from earnings_call_agent.ingestion import load_transcript_file
from earnings_call_agent.pipeline import analyze_transcript


class TestExtractionAndDomain(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AgentConfig.from_file(str(PROJECT_ROOT / "config" / "default.json"))
        self.fixtures = PROJECT_ROOT / "data" / "fixtures"

    def test_reference_fixture_matches_hand_calculated_oracle(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "reference_valid.json"))
        oracle = json.loads((self.fixtures / "reference_expected.json").read_text(encoding="utf-8"))

        report = analyze_transcript(raw, self.config, as_of_timestamp=oracle["as_of_timestamp"])
        seg_map = {s["segment_id"]: s["text"] for s in raw["segments"]}

        self.assertEqual(len(report.claims), oracle["expected_claim_count"])
        self.assertFalse(report.trade_action_permitted)
        self.assertEqual(report.diagnostics.claims_rejected_unverified, 0)

        # Every numerical claim must have verified verbatim evidence and normalized units
        for claim in report.claims:
            ev = claim.evidence
            self.assertTrue(ev.verified)
            self.assertEqual(seg_map[ev.segment_id][ev.char_start : ev.char_end], ev.exact_quote)

        # Verify each hand-calculated expected claim is present
        for exp in oracle["expected_claims"]:
            matched = [
                c
                for c in report.claims
                if c.metric_name == exp["metric_name"]
                and c.claim_type.value == exp["claim_type"]
                and c.fiscal_period == exp["fiscal_period"]
                and c.accounting_basis.value == exp["accounting_basis"]
                and c.normalized_unit.value == exp["normalized_unit"]
                and abs(c.normalized_low - exp["normalized_low"]) < 1e-6
                and abs(c.normalized_high - exp["normalized_high"]) < 1e-6
                and c.evidence.segment_id == exp["segment_id"]
            ]
            self.assertEqual(len(matched), 1, f"Expected claim not uniquely matched: {exp}")

        # Verify hand-calculated guidance comparisons
        for exp_g in oracle["expected_guidance_comparisons"]:
            matched_g = [
                g
                for g in report.guidance_comparisons
                if g.metric_name == exp_g["metric_name"]
                and g.fiscal_period == exp_g["fiscal_period"]
                and g.direction.value == exp_g["direction"]
                and g.contradiction_detected == exp_g["contradiction_detected"]
            ]
            self.assertEqual(len(matched_g), 1, f"Expected guidance diff missing: {exp_g}")
            comp = matched_g[0]
            self.assertAlmostEqual(comp.current_midpoint, exp_g["current_midpoint"], places=4)
            if exp_g["delta_midpoint"] is not None:
                self.assertAlmostEqual(comp.delta_midpoint, exp_g["delta_midpoint"], places=4)
            if "must_contain_flag" in exp_g:
                self.assertIn(exp_g["must_contain_flag"], comp.uncertainty_flags)

        # Verify QA answers & abstention
        qa_map = {a.question_id: a for a in report.question_answers}
        for exp_q in oracle["expected_questions"]:
            ans = qa_map[exp_q["question_id"]]
            self.assertEqual(ans.abstained, exp_q["abstained"])
            if exp_q["abstained"]:
                self.assertEqual(ans.abstention_reason.value, exp_q["abstention_reason"])
            else:
                self.assertTrue(
                    any(s.segment_id == exp_q["must_cite_segment_id"] for s in ans.evidence_spans)
                )

    def test_contradictory_guidance_mixed_units_and_fiscal_periods(self) -> None:
        raw = load_transcript_file(str(self.fixtures / "contradictory_guidance.json"))
        report = analyze_transcript(raw, self.config, as_of_timestamp="2026-02-15T12:00:00Z")

        # Revenue FY2026: CEO $2.10B-$2.20B (2100-2200M) vs CFO $1,950M-$2,020M -> CONTRADICTORY
        rev_comps = [
            g for g in report.guidance_comparisons if g.metric_name == "revenue" and g.fiscal_period == "FY2026"
        ]
        self.assertEqual(len(rev_comps), 1)
        rev_c = rev_comps[0]
        self.assertTrue(rev_c.contradiction_detected)
        self.assertEqual(rev_c.direction, GuidanceDirection.CONTRADICTORY)
        self.assertEqual(rev_c.normalized_unit, CanonicalUnit.USD_MILLIONS)
        self.assertIn("INTRA_CALL_CONTRADICTION", rev_c.uncertainty_flags)
        self.assertIn("SPEAKER_DISAGREEMENT", rev_c.uncertainty_flags)
        self.assertIn("PREPARED_VS_QA_DIVERGENCE", rev_c.uncertainty_flags)
        self.assertEqual(len(rev_c.contradicting_claim_ids), 2)

        # GAAP vs Non-GAAP operating margin kept separate
        om_comps = [g for g in report.guidance_comparisons if g.metric_name == "operating_margin"]
        self.assertEqual(len(om_comps), 2)
        om_by_basis = {g.accounting_basis: g for g in om_comps}
        self.assertEqual(om_by_basis[AccountingBasis.GAAP].direction, GuidanceDirection.NARROWED)
        self.assertEqual(om_by_basis[AccountingBasis.NON_GAAP].direction, GuidanceDirection.REAFFIRMED)

        # Distinct fiscal periods & units: CY2026 gross margin (%) vs Q1_FY2026 gross margin (bps)
        gm_claims = [c for c in report.claims if c.metric_name == "gross_margin"]
        periods_units = {(c.fiscal_period, c.normalized_unit) for c in gm_claims}
        self.assertIn(("CY2026", CanonicalUnit.PERCENT), periods_units)
        self.assertIn(("Q1_FY2026", CanonicalUnit.BPS), periods_units)

        # Single-value question abstains on contradiction; conflict-focused question answers citing both
        qa_map = {a.question_id: a for a in report.question_answers}
        self.assertTrue(qa_map["q_brrl_rev_single"].abstained)
        self.assertEqual(
            qa_map["q_brrl_rev_single"].abstention_reason.value, "AMBIGUOUS_OR_CONTRADICTORY"
        )
        self.assertFalse(qa_map["q_brrl_rev_conflict"].abstained)
        self.assertEqual(len(qa_map["q_brrl_rev_conflict"].evidence_spans), 2)


if __name__ == "__main__":
    unittest.main()
