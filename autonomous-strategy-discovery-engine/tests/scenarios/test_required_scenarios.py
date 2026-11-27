"""Scenario tests covering all 6 required verification cases from Section 5 of plan.md."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Dict, List

from asde.data.fixtures import generate_synthetic_dataset
from asde.data.splits import HoldoutGuard, SplitPolicy, build_split_manifest, verify_split_manifest
from asde.dsl.catalog import build_baseline_spec, load_catalog
from asde.dsl.compiler import SignalCompiler
from asde.dsl.schema import StrategySpec
from asde.errors import HoldoutLeakageError, LookAheadError, ManifestIntegrityError
from asde.evaluation.costs import load_cost_scenarios
from asde.evaluation.walk_forward import WalkForwardEvaluator
from asde.pipeline import DiscoveryPipeline
from asde.reporting.multiple_testing import evaluate_multiple_testing
from asde.search.generator import BoundedCandidateGenerator
from asde.types import DatasetSnapshot, format_utc, parse_utc

ROOT = Path(__file__).resolve().parents[2]


def run_all_scenarios_with_evidence() -> Dict[str, Any]:
    """Execute all 6 required scenarios and return structured verification evidence."""
    catalog = load_catalog(ROOT / "config" / "strategy_catalog.json")
    cost_scenarios = load_cost_scenarios(ROOT / "config" / "cost_scenarios.json")
    compiler = SignalCompiler(catalog)
    evaluator = WalkForwardEvaluator(compiler=compiler, bootstrap_samples=60)
    evidence: Dict[str, Any] = {"schema_version": "1.0.0", "scenarios": {}}

    # ------------------------------------------------------------------
    # Scenario 1: Look-ahead injection
    # ------------------------------------------------------------------
    ds_clean = generate_synthetic_dataset(seed=20260401, num_bars=320)
    valid_spec = StrategySpec(
        strategy_id="scen1_trend",
        family="trend_ma_crossover",
        dsl_version="1.0.0",
        parameters={
            "fast_window": 10,
            "slow_window": 40,
            "vol_window": 20,
            "target_vol": 0.12,
            "rebalance_band": 0.05,
            "signal_lag_bars": 1,
        },
    )
    # Fault A: injected look-ahead shift in compiler
    fault_a_code = None
    try:
        compiler.compile(valid_spec, ds_clean, injected_lookahead_bars=1)
    except LookAheadError as exc:
        fault_a_code = exc.code

    # Fault B: future available_time_utc on a market bar
    sym0 = ds_clean.symbols[0]
    corrupted_bars = dict(ds_clean.bars_by_symbol)
    sym_list = list(corrupted_bars[sym0])
    bad_bar = sym_list[50]
    # Make bar 50 available 3 days in the future (after bar 51 executes!)
    future_av = format_utc(parse_utc(bad_bar.event_time_utc) + timedelta(days=5))
    sym_list[50] = replace(bad_bar, available_time_utc=future_av)
    corrupted_bars[sym0] = sym_list
    ds_future_avail = DatasetSnapshot(
        manifest=ds_clean.manifest,
        timestamps_utc=ds_clean.timestamps_utc,
        symbols=ds_clean.symbols,
        bars_by_symbol=corrupted_bars,
    )
    fault_b_code = None
    try:
        compiler.compile(valid_spec, ds_future_avail)
    except LookAheadError as exc:
        fault_b_code = exc.code

    clean_ok = len(compiler.compile(valid_spec, ds_clean).target_weights) == ds_clean.num_bars
    evidence["scenarios"]["look_ahead_injection"] = {
        "passed": fault_a_code == "LOOK_AHEAD_VIOLATION" and fault_b_code == "LOOK_AHEAD_VIOLATION" and clean_ok,
        "compiler_shift_fault_code": fault_a_code,
        "future_availability_fault_code": fault_b_code,
        "clean_signal_compiled": clean_ok,
    }

    # ------------------------------------------------------------------
    # Scenario 2: Same seed rerun (bit-for-bit reproducibility)
    # ------------------------------------------------------------------
    pipeline = DiscoveryPipeline(project_root=ROOT)
    cfg = json.loads((ROOT / "config" / "default_discovery.json").read_text(encoding="utf-8"))
    cfg["search"]["max_candidates"] = 8
    cfg["search"]["max_inner_trials_per_candidate"] = 2
    cfg["evaluation"]["bootstrap_samples"] = 50
    with tempfile.TemporaryDirectory() as tmp:
        r1 = pipeline.run(config=cfg, out_dir=Path(tmp) / "run1")
        r2 = pipeline.run(config=cfg, out_dir=Path(tmp) / "run2")
        trials_1 = (Path(tmp) / "run1" / "trials.jsonl").read_text(encoding="utf-8")
        trials_2 = (Path(tmp) / "run2" / "trials.jsonl").read_text(encoding="utf-8")
        same_fp = r1.report_fingerprint == r2.report_fingerprint
        same_run_id = r1.run_id == r2.run_id
        same_trials = trials_1 == trials_2
        same_md = r1.leaderboard_markdown == r2.leaderboard_markdown
        evidence["scenarios"]["same_seed_rerun"] = {
            "passed": same_fp and same_run_id and same_trials and same_md,
            "run_id": r1.run_id,
            "report_fingerprint_run1": r1.report_fingerprint,
            "report_fingerprint_run2": r2.report_fingerprint,
            "trials_jsonl_identical": same_trials,
        }

    # ------------------------------------------------------------------
    # Scenario 3: Holdout leakage
    # ------------------------------------------------------------------
    ds_split = generate_synthetic_dataset(seed=20260401, num_bars=700)
    manifest = build_split_manifest(ds_split, SplitPolicy(walk_forward_folds=3, inner_tuning_folds=3))
    guard = HoldoutGuard(manifest)
    leak_code = None
    try:
        guard.request_slice(
            split_name="test",
            start_idx=manifest.test_start,
            end_idx=manifest.test_end,
            phase="walk_forward_validation",
            requester="scenario3_leaker",
        )
    except HoldoutLeakageError as exc:
        leak_code = exc.code

    tamper_code = None
    try:
        verify_split_manifest(replace(manifest, val_end=manifest.test_end), ds_split)
    except ManifestIntegrityError as exc:
        tamper_code = exc.code

    audit = guard.summary()
    evidence["scenarios"]["holdout_leakage"] = {
        "passed": (
            leak_code == "HOLDOUT_LEAKAGE_VIOLATION"
            and tamper_code == "MANIFEST_INTEGRITY_ERROR"
            and audit["holdout_reads_during_selection"] == 0
            and audit["blocked_attempts"] == 1
        ),
        "leak_error_code": leak_code,
        "tamper_error_code": tamper_code,
        "holdout_audit": audit,
    }

    # ------------------------------------------------------------------
    # Scenario 4: Multiple-testing inflation on pure-noise data
    # ------------------------------------------------------------------
    ds_noise = generate_synthetic_dataset(seed=99911, num_bars=650, regime="pure_noise", dataset_id="pure_noise_test")
    noise_manifest = build_split_manifest(
        ds_noise,
        SplitPolicy(walk_forward_folds=3, inner_tuning_folds=2, min_train_bars=100, min_fold_bars=30),
    )
    noise_guard = HoldoutGuard(noise_manifest)
    gen = BoundedCandidateGenerator(catalog)
    noise_cands = gen.generate(
        families=["trend_ma_crossover", "mean_reversion_zscore", "volatility_breakout", "dual_momentum"],
        max_candidates=40,
        seed=99911,
    )
    base_cost = cost_scenarios["base_institutional"]
    mt_entries: List[Dict[str, Any]] = []
    for idx, cspec in enumerate(noise_cands):
        wf = evaluator.evaluate_folds(
            spec=cspec,
            dataset=ds_noise,
            folds=noise_manifest.walk_forward_folds,
            holdout_guard=noise_guard,
            cost_scenario=base_cost,
            phase="walk_forward_validation",
            split_name="validation",
            seed=99911 + idx,
        )
        m = wf.aggregate_metrics
        mt_entries.append(
            {
                "strategy_id": cspec.strategy_id,
                "sharpe_ratio": m.sharpe_ratio,
                "num_bars": m.num_bars,
                "skewness": m.skewness,
                "kurtosis": m.kurtosis,
            }
        )
    mt_stats = evaluate_multiple_testing(
        candidate_entries=mt_entries,
        total_trials_accounted=len(mt_entries),
        fdr_alpha=0.10,
        min_dsr_prob=0.50,
    )
    best_entry = max(mt_entries, key=lambda x: x["sharpe_ratio"])
    best_mt = mt_stats[best_entry["strategy_id"]]
    fdr_survivors = sum(1 for s in mt_stats.values() if s.passes_fdr)
    evidence["scenarios"]["multiple_testing_inflation"] = {
        "passed": (
            best_mt.total_trials_accounted == len(mt_entries)
            and best_mt.expected_max_null_sharpe > 1.0
            and best_mt.dsr_probability < best_mt.psr_vs_zero
            and fdr_survivors == 0
        ),
        "num_noise_trials": len(mt_entries),
        "naive_best_sharpe": best_entry["sharpe_ratio"],
        "naive_best_psr": best_mt.psr_vs_zero,
        "expected_max_null_sharpe": best_mt.expected_max_null_sharpe,
        "deflated_sharpe_prob": best_mt.dsr_probability,
        "best_bh_fdr_q_value": best_mt.bh_fdr_q_value,
        "fdr_survivors_on_noise": fdr_survivors,
    }

    # ------------------------------------------------------------------
    # Scenario 5: Excessive turnover rejection
    # ------------------------------------------------------------------
    churn_spec = StrategySpec(
        strategy_id="high_churn_mr",
        family="mean_reversion_zscore",
        dsl_version="1.0.0",
        parameters={
            "lookback_window": 10,
            "entry_z": 1.0,
            "exit_z": 0.0,
            "vol_window": 10,
            "target_vol": 0.16,
            "signal_lag_bars": 1,
        },
    )
    cfg_churn = json.loads((ROOT / "config" / "default_discovery.json").read_text(encoding="utf-8"))
    cfg_churn["search"]["max_candidates"] = 2
    cfg_churn["search"]["max_inner_trials_per_candidate"] = 1
    cfg_churn["evaluation"]["max_annualized_turnover"] = 10.0
    cfg_churn["evaluation"]["bootstrap_samples"] = 40
    with tempfile.TemporaryDirectory() as tmp:
        r_churn = pipeline.run(
            config=cfg_churn,
            out_dir=Path(tmp) / "churn",
            extra_candidate_specs=[churn_spec],
        )
        row = next(c for c in r_churn.leaderboard["candidates"] if c["strategy_id"] == "high_churn_mr")
        has_turn_reject = any(reason.startswith("excessive_turnover:") for reason in row["rejection_reasons"])
        evidence["scenarios"]["excessive_turnover"] = {
            "passed": (
                has_turn_reject
                and row["governance_status"] == "REJECTED"
                and row["metrics"]["annualized_turnover"] > 10.0
                and row["metrics"]["total_cost_drag"] > 0.0
                and row["metrics"]["gross_total_return"] > row["metrics"]["total_return"]
            ),
            "strategy_id": row["strategy_id"],
            "annualized_turnover": row["metrics"]["annualized_turnover"],
            "turnover_limit": 10.0,
            "gross_total_return": row["metrics"]["gross_total_return"],
            "net_total_return": row["metrics"]["total_return"],
            "total_cost_drag": row["metrics"]["total_cost_drag"],
            "governance_status": row["governance_status"],
            "rejection_reasons": row["rejection_reasons"],
        }

    # ------------------------------------------------------------------
    # Scenario 6: Cost sensitivity (candidate + baseline across 4 cost tiers)
    # ------------------------------------------------------------------
    ds_cost = generate_synthetic_dataset(seed=20260401, num_bars=900)
    cost_manifest = build_split_manifest(ds_cost, SplitPolicy())
    cost_guard = HoldoutGuard(cost_manifest)
    ordered_scenarios = [
        cost_scenarios["zero_cost_reference"],
        cost_scenarios["base_institutional"],
        cost_scenarios["stressed_2x"],
        cost_scenarios["severe_3x"],
    ]
    cand_sens = evaluator.evaluate_cost_sensitivity(
        spec=churn_spec,
        dataset=ds_cost,
        folds=cost_manifest.walk_forward_folds,
        holdout_guard=cost_guard,
        scenarios=ordered_scenarios,
        phase="walk_forward_validation",
        split_name="validation",
        seed=20260401,
    )
    bh_spec = build_baseline_spec("baseline_buy_and_hold", catalog)
    base_sens = evaluator.evaluate_cost_sensitivity(
        spec=bh_spec,
        dataset=ds_cost,
        folds=cost_manifest.walk_forward_folds,
        holdout_guard=cost_guard,
        scenarios=ordered_scenarios,
        phase="walk_forward_validation",
        split_name="validation",
        seed=20260401,
    )
    cand_rets = [cand_sens[s.name]["total_return"] for s in ordered_scenarios]
    cand_drags = [cand_sens[s.name]["total_cost_drag"] for s in ordered_scenarios]
    monotonic_ret = all(cand_rets[i] > cand_rets[i + 1] for i in range(len(cand_rets) - 1))
    monotonic_drag = all(cand_drags[i] < cand_drags[i + 1] for i in range(len(cand_drags) - 1))
    matching_hashes = all(
        cand_sens[s.name]["cost_scenario_hash"] == base_sens[s.name]["cost_scenario_hash"]
        for s in ordered_scenarios
    )
    evidence["scenarios"]["cost_sensitivity"] = {
        "passed": monotonic_ret and monotonic_drag and matching_hashes,
        "monotonic_return_degradation": monotonic_ret,
        "monotonic_cost_drag_increase": monotonic_drag,
        "identical_cost_hashes_with_baseline": matching_hashes,
        "candidate_sensitivity": cand_sens,
        "baseline_sensitivity": base_sens,
    }

    evidence["all_passed"] = all(s["passed"] for s in evidence["scenarios"].values())
    return evidence


class TestRequiredScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = run_all_scenarios_with_evidence()

    def test_scenario_1_look_ahead_injection(self) -> None:
        self.assertTrue(self.evidence["scenarios"]["look_ahead_injection"]["passed"])

    def test_scenario_2_same_seed_rerun(self) -> None:
        self.assertTrue(self.evidence["scenarios"]["same_seed_rerun"]["passed"])

    def test_scenario_3_holdout_leakage(self) -> None:
        self.assertTrue(self.evidence["scenarios"]["holdout_leakage"]["passed"])

    def test_scenario_4_multiple_testing_inflation(self) -> None:
        self.assertTrue(self.evidence["scenarios"]["multiple_testing_inflation"]["passed"])

    def test_scenario_5_excessive_turnover(self) -> None:
        self.assertTrue(self.evidence["scenarios"]["excessive_turnover"]["passed"])

    def test_scenario_6_cost_sensitivity(self) -> None:
        self.assertTrue(self.evidence["scenarios"]["cost_sensitivity"]["passed"])


if __name__ == "__main__":
    unittest.main()
