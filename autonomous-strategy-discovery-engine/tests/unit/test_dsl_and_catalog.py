"""Unit tests for the constrained Strategy DSL, catalog validation, and compiler invariants."""

from __future__ import annotations

from pathlib import Path
import unittest

from asde.data.fixtures import generate_synthetic_dataset
from asde.dsl.catalog import build_baseline_spec, load_catalog, validate_strategy_spec
from asde.dsl.compiler import SignalCompiler
from asde.dsl.schema import StrategySpec
from asde.errors import DslValidationError, LookAheadError, UnconstrainedCodeError

ROOT = Path(__file__).resolve().parents[2]


class TestDslAndCatalog(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(ROOT / "config" / "strategy_catalog.json")
        self.dataset = generate_synthetic_dataset(seed=101, num_bars=260)
        self.compiler = SignalCompiler(self.catalog)

    def test_valid_specs_and_baselines_compile_cleanly(self) -> None:
        valid_specs = [
            StrategySpec(
                strategy_id="trend_1",
                family="trend_ma_crossover",
                dsl_version="1.0.0",
                parameters={
                    "fast_window": 10,
                    "slow_window": 50,
                    "vol_window": 20,
                    "target_vol": 0.12,
                    "rebalance_band": 0.05,
                    "signal_lag_bars": 1,
                },
            ),
            StrategySpec(
                strategy_id="mr_1",
                family="mean_reversion_zscore",
                dsl_version="1.0.0",
                parameters={
                    "lookback_window": 20,
                    "entry_z": 1.5,
                    "exit_z": 0.25,
                    "vol_window": 20,
                    "target_vol": 0.12,
                    "signal_lag_bars": 1,
                },
            ),
            StrategySpec(
                strategy_id="bo_1",
                family="volatility_breakout",
                dsl_version="1.0.0",
                parameters={
                    "breakout_window": 20,
                    "exit_window": 10,
                    "vol_window": 20,
                    "target_vol": 0.12,
                    "signal_lag_bars": 1,
                },
            ),
            StrategySpec(
                strategy_id="dm_1",
                family="dual_momentum",
                dsl_version="1.0.0",
                parameters={
                    "momentum_window": 40,
                    "top_k": 2,
                    "rebalance_every_bars": 10,
                    "signal_lag_bars": 1,
                },
            ),
        ]
        for bname in ("baseline_buy_and_hold", "baseline_cash", "baseline_risk_parity_equal_weight"):
            valid_specs.append(build_baseline_spec(bname, self.catalog))

        for spec in valid_specs:
            validate_strategy_spec(spec, self.catalog)
            compiled = self.compiler.compile(spec, self.dataset)
            self.assertEqual(len(compiled.target_weights), self.dataset.num_bars)
            # First bar must have zero weights due to signal_lag_bars >= 1
            self.assertEqual(sum(abs(v) for v in compiled.target_weights[0].values()), 0.0)
            # Gross leverage must never exceed cap
            for w in compiled.target_weights:
                self.assertLessEqual(sum(abs(v) for v in w.values()), spec.max_gross_leverage + 1e-6)

    def test_rejects_unconstrained_code_generation(self) -> None:
        bad_raw = StrategySpec(
            strategy_id="evil_1",
            family="trend_ma_crossover",
            dsl_version="1.0.0",
            parameters={
                "fast_window": 10,
                "slow_window": 50,
                "vol_window": 20,
                "target_vol": 0.12,
                "rebalance_band": 0.05,
                "signal_lag_bars": 1,
            },
            raw_code="lambda df: df['close'].shift(-1)",
        )
        with self.assertRaises(UnconstrainedCodeError):
            validate_strategy_spec(bad_raw, self.catalog)

        bad_key = StrategySpec(
            strategy_id="evil_2",
            family="trend_ma_crossover",
            dsl_version="1.0.0",
            parameters={"python": "import os"},
        )
        with self.assertRaises(UnconstrainedCodeError):
            validate_strategy_spec(bad_key, self.catalog)

    def test_rejects_parameter_bounds_and_constraints(self) -> None:
        bad_constraint = StrategySpec(
            strategy_id="bad_ma",
            family="trend_ma_crossover",
            dsl_version="1.0.0",
            parameters={
                "fast_window": 40,
                "slow_window": 30,  # violates fast_window < slow_window
                "vol_window": 20,
                "target_vol": 0.12,
                "rebalance_band": 0.05,
                "signal_lag_bars": 1,
            },
        )
        with self.assertRaises(DslValidationError):
            validate_strategy_spec(bad_constraint, self.catalog)

        bad_lag = StrategySpec(
            strategy_id="zero_lag",
            family="trend_ma_crossover",
            dsl_version="1.0.0",
            parameters={
                "fast_window": 10,
                "slow_window": 40,
                "vol_window": 20,
                "target_vol": 0.12,
                "rebalance_band": 0.05,
                "signal_lag_bars": 0,  # Look-ahead!
            },
        )
        with self.assertRaises(LookAheadError):
            validate_strategy_spec(bad_lag, self.catalog)


if __name__ == "__main__":
    unittest.main()
