"""Integration tests for future-data leakage, determinism, and paper accounting."""

from __future__ import annotations

import json
from pathlib import Path

from strategy_sandbox import (
    DatasetManifest,
    ExperimentBudget,
    ExperimentEvaluator,
    OrderIntent,
    PaperPortfolioEngine,
    SandboxConfig,
    SandboxExecutionResult,
    StrategyProposal,
    StrategySpec,
    group_bars_by_timestamp,
    verify_accounting_invariants,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def _load_base() -> tuple[DatasetManifest, StrategySpec]:
    dataset = DatasetManifest.model_validate(
        json.loads((FIXTURES / "reference_dataset.json").read_text(encoding="utf-8"))
    )
    spec = StrategySpec.model_validate(
        json.loads((FIXTURES / "reference_spec.json").read_text(encoding="utf-8"))
    )
    return dataset, spec


class _LeakyLookaheadRunner:
    """Test-only mock runner simulating a leaky lookahead strategy or feature."""

    backend_name = "test_leaky_runner"

    def run(
        self,
        *,
        code: str,
        dataset: DatasetManifest,
        spec: StrategySpec,
        budget: ExperimentBudget,
        allowed_imports: list[str],
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        engine = PaperPortfolioEngine(spec)
        steps = group_bars_by_timestamp(dataset)
        orders_by_step: list[list[OrderIntent]] = []
        final_close = steps[-1][1]["SYNTH_A"].close

        for idx, (ts, bar_map) in enumerate(steps):
            # Lookahead bug: decides at step 1 based on the FINAL bar's close price!
            step_orders: list[OrderIntent] = []
            if idx == 1 and final_close > 150.0:
                step_orders.append(
                    OrderIntent(symbol="SYNTH_A", side="BUY", quantity=100.0, reason="lookahead_signal")
                )
            orders_by_step.append(step_orders)
            engine.process_step(step=idx, timestamp=ts, current_bars=bar_map, orders=step_orders)

        return (
            SandboxExecutionResult(
                succeeded=True,
                exit_code=0,
                wall_time_sec=0.001,
                steps_executed=len(steps),
                orders_by_step=orders_by_step,
            ),
            engine,
        )


class _NondeterministicRunner:
    """Test-only mock runner emitting different quantities across identical calls."""

    backend_name = "test_nondet_runner"

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        *,
        code: str,
        dataset: DatasetManifest,
        spec: StrategySpec,
        budget: ExperimentBudget,
        allowed_imports: list[str],
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        self.calls += 1
        engine = PaperPortfolioEngine(spec)
        steps = group_bars_by_timestamp(dataset)
        orders_by_step: list[list[OrderIntent]] = []
        # Emit identical orders on early steps (passes leakage checkpoints), diverge on final run!
        qty = 10.0 + float(self.calls)

        for idx, (ts, bar_map) in enumerate(steps):
            step_orders: list[OrderIntent] = []
            if idx == 9:
                step_orders.append(
                    OrderIntent(symbol="SYNTH_A", side="BUY", quantity=qty, reason="nondet")
                )
            orders_by_step.append(step_orders)
            engine.process_step(step=idx, timestamp=ts, current_bars=bar_map, orders=step_orders)

        return (
            SandboxExecutionResult(
                succeeded=True,
                exit_code=0,
                wall_time_sec=0.001,
                steps_executed=len(steps),
                orders_by_step=orders_by_step,
            ),
            engine,
        )


def test_future_data_leakage_detected_and_rejected() -> None:
    dataset, spec = _load_base()
    prop = StrategyProposal(
        proposal_id="prop-leaky-sim",
        spec_id=spec.spec_id,
        author_type="llm_generated",
        code="def on_bar(ctx):\n    return []\n",
    )
    evaluator = ExperimentEvaluator(config=SandboxConfig(), runner=_LeakyLookaheadRunner())
    trial = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset)

    assert trial.status == "FAILED_LEAKAGE"
    leak_chk = next(c for c in trial.checks if c.name == "future_data_leakage")
    assert not leak_chk.passed
    assert leak_chk.code == "FUTURE_DATA_LEAKAGE"


def test_nondeterministic_strategy_detected_and_rejected() -> None:
    dataset, spec = _load_base()
    prop = StrategyProposal(
        proposal_id="prop-nondet-sim",
        spec_id=spec.spec_id,
        author_type="llm_generated",
        code="def on_bar(ctx):\n    return []\n",
    )
    evaluator = ExperimentEvaluator(config=SandboxConfig(), runner=_NondeterministicRunner())
    trial = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset)

    assert trial.status == "FAILED_DETERMINISM"
    det_chk = next(c for c in trial.checks if c.name == "determinism")
    assert not det_chk.passed
    assert det_chk.code == "NONDETERMINISTIC_BEHAVIOR"


def test_seeded_stochastic_strategy_reproducible_across_runs() -> None:
    dataset, spec = _load_base()
    prop = StrategyProposal(
        proposal_id="prop-seeded-rng",
        spec_id=spec.spec_id,
        author_type="llm_generated",
        code=(
            "def on_bar(ctx):\n"
            "    draw = ctx.rng.random()\n"
            "    qty = ctx.position_qty('SYNTH_A')\n"
            "    if draw > 0.65 and qty == 0.0:\n"
            "        return [{'symbol': 'SYNTH_A', 'side': 'BUY', 'quantity': 50.0, 'reason': 'rng_buy'}]\n"
            "    if draw < 0.35 and qty > 0.0:\n"
            "        return [{'symbol': 'SYNTH_A', 'side': 'SELL', 'quantity': qty, 'reason': 'rng_sell'}]\n"
            "    return []\n"
        ),
    )
    evaluator = ExperimentEvaluator(config=SandboxConfig())
    trial_a = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset)
    trial_b = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset)

    assert trial_a.status == "PASSED"
    assert trial_b.status == "PASSED"
    assert trial_a.trial_id == trial_b.trial_id
    assert trial_a.output_sha256 == trial_b.output_sha256

    # Different seed changes the input bundle hash and produces a valid independent trial
    spec_alt = spec.model_copy(update={"seed": 99})
    trial_alt = evaluator.evaluate(proposal=prop, spec=spec_alt, dataset=dataset)
    assert trial_alt.status == "PASSED"
    assert trial_alt.input_bundle_sha256 != trial_a.input_bundle_sha256


def test_paper_engine_risk_rejections_and_double_entry_accounting() -> None:
    dataset, spec = _load_base()
    engine = PaperPortfolioEngine(spec)
    steps = group_bars_by_timestamp(dataset)

    # Step 0: Attempt disallowed short, unknown symbol, oversized position (>50% equity), and valid BUY
    ts0, bars0 = steps[0]
    engine.process_step(
        step=0,
        timestamp=ts0,
        current_bars=bars0,
        orders=[
            OrderIntent(symbol="SYNTH_A", side="SELL", quantity=10.0, reason="short_attempt"),
            OrderIntent(symbol="UNKNOWN", side="BUY", quantity=10.0, reason="bad_symbol"),
            OrderIntent(symbol="SYNTH_A", side="BUY", quantity=800.0, reason="exceeds_pos_pct"),
            OrderIntent(symbol="SYNTH_A", side="BUY", quantity=200.0, reason="valid_buy"),
        ],
    )
    assert len(engine.rejected_orders) == 3
    assert len(engine.fills) == 1

    # Step 1: Partial close of 50 shares
    ts1, bars1 = steps[1]
    engine.process_step(
        step=1,
        timestamp=ts1,
        current_bars=bars1,
        orders=[OrderIntent(symbol="SYNTH_A", side="SELL", quantity=50.0, reason="partial_sell")],
    )
    # Step 2: Close remaining 150 shares
    ts2, bars2 = steps[2]
    engine.process_step(
        step=2,
        timestamp=ts2,
        current_bars=bars2,
        orders=[OrderIntent(symbol="SYNTH_A", side="SELL", quantity=150.0, reason="final_sell")],
    )

    summary = engine.summarize()
    chk = verify_accounting_invariants(summary, engine.equity_curve, spec, tolerance=1e-6)
    assert chk.passed
    assert summary.max_accounting_identity_error <= 1e-9
    assert summary.ending_positions == {}
    assert summary.trade_count == 3
    assert summary.rejected_order_count == 3
