#!/usr/bin/env python3
"""End-to-end reproducible demo for the Financial Agent Evaluation Framework.

Runs:
1. Reference deterministic baseline on dev tasks -> reports/baseline/
2. Resilience failure-injection suite (tool outage, stale evidence, prompt injection) -> reports/runs/
3. Stochastic multi-seed variance benchmark (5 repeats with 95% CIs) -> reports/runs/
4. Held-out final verification run -> reports/runs/
5. Deterministic offline replay verification of the baseline bundle
"""

from __future__ import annotations

import json
from pathlib import Path

from fin_eval.runner import (
    ReplayBundle,
    load_dataset,
    load_fixture_store,
    load_injection_profile,
    load_model_config,
    replay_evaluation,
    run_evaluation,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    fixtures_dir = PROJECT_ROOT / "data" / "fixtures"
    config_dir = PROJECT_ROOT / "config"
    baseline_dir = PROJECT_ROOT / "reports" / "baseline"
    runs_dir = PROJECT_ROOT / "reports" / "runs"

    store = load_fixture_store(fixtures_dir / "mock_store_v1.json")
    dev_dataset = load_dataset(fixtures_dir / "gold_tasks_dev_v1.json")
    held_out_dataset = load_dataset(fixtures_dir / "gold_tasks_held_out_v1.json", allow_held_out=True)

    det_cfg = load_model_config(config_dir / "model_deterministic.json")
    stoch_cfg = load_model_config(config_dir / "model_stochastic.json")
    clean_faults = load_injection_profile(config_dir / "faults_none.json")
    resilience_faults = load_injection_profile(config_dir / "faults_resilience.json")

    # 1. Deterministic baseline
    baseline_report, baseline_bundle, _ = run_evaluation(
        dataset=dev_dataset,
        store=store,
        model_config=det_cfg,
        injection_profile=clean_faults,
        seeds=[42],
        out_dir=baseline_dir,
    )

    # 2. Failure-injection resilience run compared against baseline
    resilience_report, _, _ = run_evaluation(
        dataset=dev_dataset,
        store=store,
        model_config=det_cfg,
        injection_profile=resilience_faults,
        seeds=[42],
        baseline_report=baseline_report,
        baseline_tolerance=0.02,
        out_dir=runs_dir,
    )

    # 3. Stochastic variance benchmark across 5 fixed seeds
    stochastic_report, _, _ = run_evaluation(
        dataset=dev_dataset,
        store=store,
        model_config=stoch_cfg,
        injection_profile=clean_faults,
        seeds=[100, 101, 102, 103, 104],
        baseline_report=baseline_report,
        baseline_tolerance=0.25,
        out_dir=runs_dir,
    )

    # 4. Held-out final verification
    held_out_report, _, _ = run_evaluation(
        dataset=held_out_dataset,
        store=store,
        model_config=det_cfg,
        injection_profile=clean_faults,
        seeds=[42],
        out_dir=runs_dir,
    )

    # 5. Deterministic replay verification
    bundle_file = baseline_dir / f"{baseline_report.report_id}.replay.json"
    loaded_bundle = ReplayBundle.model_validate_json(bundle_file.read_text(encoding="utf-8"))
    replayed_report = replay_evaluation(loaded_bundle)
    assert replayed_report.report_id == baseline_report.report_id, "Replay ID mismatch!"

    summary = {
        "baseline": {
            "report_id": baseline_report.report_id,
            "pass_rate": baseline_report.summary.pass_rate.mean,
            "mean_score": baseline_report.summary.mean_score.mean,
            "receipt_verification_rate": baseline_report.summary.receipt_verification_rate,
            "total_cost_usd": baseline_report.summary.total_cost_usd,
            "mean_latency_ms": baseline_report.summary.mean_latency_ms,
        },
        "resilience_injected": {
            "report_id": resilience_report.report_id,
            "pass_rate": resilience_report.summary.pass_rate.mean,
            "mean_score": resilience_report.summary.mean_score.mean,
            "faults_injected": resilience_report.diagnostic_counters.get("faults_injected", 0),
            "baseline_within_tolerance": (
                resilience_report.baseline_comparison.within_tolerance
                if resilience_report.baseline_comparison
                else None
            ),
        },
        "stochastic_5x": {
            "report_id": stochastic_report.report_id,
            "pass_rate_ci": stochastic_report.summary.pass_rate.model_dump(),
            "mean_score_ci": stochastic_report.summary.mean_score.model_dump(),
            "failure_type_counts": stochastic_report.summary.failure_type_counts,
            "total_cost_usd": stochastic_report.summary.total_cost_usd,
            "p95_latency_ms": stochastic_report.summary.p95_latency_ms,
        },
        "held_out": {
            "report_id": held_out_report.report_id,
            "pass_rate": held_out_report.summary.pass_rate.mean,
            "mean_score": held_out_report.summary.mean_score.mean,
        },
        "replay_verified": replayed_report.report_id == baseline_report.report_id,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
