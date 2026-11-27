"""Unit tests for multiple-testing statistics (PSR, DSR, Bonferroni, Holm, BH-FDR)."""

from __future__ import annotations

import unittest

from asde.reporting.multiple_testing import (
    deflated_sharpe_ratio,
    evaluate_multiple_testing,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)


class TestMultipleTesting(unittest.TestCase):
    def test_psr_and_dsr_behavior(self) -> None:
        psr_hi = probabilistic_sharpe_ratio(sharpe_annual=1.5, benchmark_sharpe_annual=0.0, num_bars=252)
        psr_lo = probabilistic_sharpe_ratio(sharpe_annual=0.2, benchmark_sharpe_annual=0.0, num_bars=252)
        self.assertGreater(psr_hi, psr_lo)
        self.assertGreater(psr_hi, 0.90)

        sr_star_5 = expected_max_sharpe(5, 1.0)
        sr_star_100 = expected_max_sharpe(100, 1.0)
        self.assertGreater(sr_star_100, sr_star_5)

        dsr_1 = deflated_sharpe_ratio(
            sharpe_annual=1.0, num_bars=252, total_trials_n=1, trial_sharpe_std_annual=0.8
        )
        dsr_100 = deflated_sharpe_ratio(
            sharpe_annual=1.0, num_bars=252, total_trials_n=100, trial_sharpe_std_annual=0.8
        )
        self.assertLess(dsr_100["dsr_probability"], dsr_1["dsr_probability"])

    def test_p_value_adjustment_ordering(self) -> None:
        entries = [
            {"strategy_id": f"s_{i}", "sharpe_ratio": 0.2 + 0.3 * i, "num_bars": 252, "skewness": 0.0, "kurtosis": 3.0}
            for i in range(6)
        ]
        stats = evaluate_multiple_testing(
            candidate_entries=entries,
            total_trials_accounted=30,  # includes 24 additional failed/inner trials
            fdr_alpha=0.10,
            min_dsr_prob=0.50,
        )
        for st in stats.values():
            self.assertEqual(st.total_trials_accounted, 30)
            self.assertGreaterEqual(st.bonferroni_p_value, st.holm_p_value - 1e-9)
            self.assertGreaterEqual(st.holm_p_value, st.bh_fdr_q_value - 1e-9)
            self.assertGreaterEqual(st.bh_fdr_q_value, st.raw_p_value - 1e-9)


if __name__ == "__main__":
    unittest.main()
