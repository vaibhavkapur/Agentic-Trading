"""Unit tests for transaction cost models and performance/uncertainty metrics."""

from __future__ import annotations

from pathlib import Path
import unittest

from asde.errors import DataContractError
from asde.evaluation.costs import CostScenario, load_cost_scenarios
from asde.evaluation.metrics import compute_metrics

ROOT = Path(__file__).resolve().parents[2]


class TestCostsAndMetrics(unittest.TestCase):
    def test_cost_scenarios_monotonic_and_validated(self) -> None:
        scenarios = load_cost_scenarios(ROOT / "config" / "cost_scenarios.json")
        c0 = scenarios["zero_cost_reference"].bar_cost(0.5, 0.2)
        c1 = scenarios["base_institutional"].bar_cost(0.5, 0.2)
        c2 = scenarios["stressed_2x"].bar_cost(0.5, 0.2)
        c3 = scenarios["severe_3x"].bar_cost(0.5, 0.2)
        self.assertEqual(c0, 0.0)
        self.assertLess(c0, c1)
        self.assertLess(c1, c2)
        self.assertLess(c2, c3)

        bad = CostScenario("bad", "neg", -1.0, 0.0, 0.0, 0.0, 0.0)
        with self.assertRaises(DataContractError):
            bad.validate()

    def test_metrics_uncertainty_drawdown_and_determinism(self) -> None:
        rets = [0.004, -0.002, 0.003, -0.015, 0.006, 0.002, -0.001, 0.005] * 20
        gross = [r + 0.0005 for r in rets]
        turns = [0.15] * len(rets)
        costs = [0.0005] * len(rets)

        m1 = compute_metrics(
            net_returns=rets,
            gross_returns=gross,
            turnovers=turns,
            cost_drags=costs,
            seed=123,
        )
        m2 = compute_metrics(
            net_returns=rets,
            gross_returns=gross,
            turnovers=turns,
            cost_drags=costs,
            seed=123,
        )
        self.assertEqual(m1.to_dict(), m2.to_dict())
        self.assertGreater(m1.max_drawdown, 0.0)
        self.assertGreater(m1.annualized_turnover, 0.0)
        self.assertGreater(m1.gross_total_return, m1.total_return)
        self.assertLessEqual(m1.sharpe_ci_low, m1.sharpe_ci_high)
        self.assertGreater(m1.sharpe_se, 0.0)


if __name__ == "__main__":
    unittest.main()
