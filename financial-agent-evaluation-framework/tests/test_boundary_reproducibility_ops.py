"""Boundary, stochastic variance, reproducibility, replay, and CLI operational tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from fin_eval.agents.mock_agents import FaultyDemoAgent
from fin_eval.cli import main as cli_main
from fin_eval.graders.numeric import grade_numeric
from fin_eval.runner import (
    load_dataset,
    load_fixture_store,
    load_model_config,
    replay_evaluation,
    run_evaluation,
)
from fin_eval.schemas import AgentTrajectory, NumericClaim, NumericUnit
from fin_eval.stats import bootstrap_confidence_interval, compare_reports

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.mark.boundary
def test_numeric_exact_tolerance_boundaries_and_non_finite() -> None:
    ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    # FIN_ARITH_001: expected=25.0, abs_tol=0.01, rel_tol=0.001 -> max(0.01, 0.025) = 0.025
    task = next(t for t in ds.tasks if t.task_id == "FIN_ARITH_001")

    at_boundary = AgentTrajectory(
        run_id="bnd-001",
        task_id=task.task_id,
        agent_id="a1",
        seed=1,
        numeric_claims=[NumericClaim(field="operating_margin_pct", value=25.025, unit=NumericUnit.PERCENT)],
    )
    assert grade_numeric(task, at_boundary).passed is True

    just_outside = AgentTrajectory(
        run_id="bnd-002",
        task_id=task.task_id,
        agent_id="a1",
        seed=1,
        numeric_claims=[NumericClaim(field="operating_margin_pct", value=25.026, unit=NumericUnit.PERCENT)],
    )
    assert grade_numeric(task, just_outside).passed is False

    nan_traj = AgentTrajectory(
        run_id="bnd-003",
        task_id=task.task_id,
        agent_id="a1",
        seed=1,
        numeric_claims=[NumericClaim(field="operating_margin_pct", value=math.nan, unit=NumericUnit.PERCENT)],
    )
    assert grade_numeric(task, nan_traj).passed is False


@pytest.mark.boundary
@pytest.mark.reproducibility
def test_repeat_runs_for_stochastic_variance_and_reproducible_cis() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    stoch_cfg = load_model_config(CONFIG_DIR / "model_stochastic.json")
    seeds = [100, 101, 102, 103, 104]

    report_1, bundle_1, _ = run_evaluation(
        dataset=dev_ds,
        store=store,
        model_config=stoch_cfg,
        seeds=seeds,
    )
    report_2, _, _ = run_evaluation(
        dataset=dev_ds,
        store=store,
        model_config=stoch_cfg,
        seeds=seeds,
    )

    # Multi-run stochastic variance is captured with valid 95% confidence intervals
    assert report_1.summary.num_runs == 5
    assert report_1.summary.total_evaluations == len(dev_ds.tasks) * 5
    assert report_1.summary.mean_score.std_dev > 0.0
    assert 0.0 <= report_1.summary.pass_rate.lower <= report_1.summary.pass_rate.mean <= report_1.summary.pass_rate.upper <= 1.0
    assert 0.0 <= report_1.summary.mean_score.lower <= report_1.summary.mean_score.mean <= report_1.summary.mean_score.upper <= 1.0

    # Bootstrap CI also deterministic under fixed seed
    scores = [r.overall_score for r in report_1.task_results]
    boot_1 = bootstrap_confidence_interval(scores, seed=42)
    boot_2 = bootstrap_confidence_interval(scores, seed=42)
    assert boot_1 == boot_2

    # Same versioned inputs + fixed seeds produce identical logical report IDs and metrics
    assert report_1.report_id == report_2.report_id
    assert report_1.summary.pass_rate == report_2.summary.pass_rate
    assert report_1.summary.mean_score == report_2.summary.mean_score
    assert report_1.summary.failure_type_counts == report_2.summary.failure_type_counts

    # Offline replay reproduces exact report ID and scores without re-running agents
    replayed = replay_evaluation(bundle_1)
    assert replayed.report_id == report_1.report_id
    assert replayed.summary.pass_rate == report_1.summary.pass_rate


@pytest.mark.reproducibility
def test_baseline_comparison_detects_regression() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    det_cfg = load_model_config(CONFIG_DIR / "model_deterministic.json")

    baseline, _, _ = run_evaluation(dataset=dev_ds, store=store, model_config=det_cfg, seeds=[42])
    faulty, _, _ = run_evaluation(
        dataset=dev_ds,
        store=store,
        model_config=det_cfg,
        agent=FaultyDemoAgent("wrong_arithmetic"),
        seeds=[42],
    )

    same_cmp = compare_reports(baseline, baseline, tolerance=0.01)
    assert same_cmp.within_tolerance is True
    assert same_cmp.regressions == []

    reg_cmp = compare_reports(faulty, baseline, tolerance=0.02)
    assert reg_cmp.within_tolerance is False
    assert len(reg_cmp.regressions) >= 4
    assert reg_cmp.pass_rate_delta < 0.0


@pytest.mark.operational
def test_cli_validate_run_replay_compare_and_error_handling(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Validate clean fixtures
    rc = cli_main(
        [
            "validate",
            "--dataset",
            str(FIXTURES_DIR / "gold_tasks_dev_v1.json"),
            "--fixtures",
            str(FIXTURES_DIR / "mock_store_v1.json"),
            "--config",
            str(CONFIG_DIR / "model_deterministic.json"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "valid"

    # 2. Run and persist artifacts
    rc = cli_main(
        [
            "run",
            "--dataset",
            str(FIXTURES_DIR / "gold_tasks_dev_v1.json"),
            "--fixtures",
            str(FIXTURES_DIR / "mock_store_v1.json"),
            "--config",
            str(CONFIG_DIR / "model_deterministic.json"),
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    run_out = json.loads(capsys.readouterr().out)
    report_id = run_out["report_id"]
    report_json = tmp_path / f"{report_id}.report.json"
    bundle_json = tmp_path / f"{report_id}.replay.json"
    assert report_json.exists()
    assert bundle_json.exists()

    # 3. Replay saved bundle and confirm exact match
    rc = cli_main(
        [
            "replay",
            "--bundle",
            str(bundle_json),
            "--expected-report",
            str(report_json),
        ]
    )
    assert rc == 0
    rep_out = json.loads(capsys.readouterr().out)
    assert rep_out["matches_expected_report_id"] is True

    # 4. Compare report against itself
    rc = cli_main(
        [
            "compare",
            "--current",
            str(report_json),
            "--baseline",
            str(report_json),
        ]
    )
    assert rc == 0

    # 5. Missing config returns non-zero exit code with clear diagnostic (no silent success)
    rc = cli_main(
        [
            "validate",
            "--dataset",
            str(FIXTURES_DIR / "gold_tasks_dev_v1.json"),
            "--fixtures",
            str(FIXTURES_DIR / "mock_store_v1.json"),
            "--config",
            str(tmp_path / "missing.json"),
        ]
    )
    assert rc == 1
    assert "ConfigurationError" in capsys.readouterr().err

    # 6. Held-out dataset blocked unless --include-held-out passed
    rc = cli_main(
        [
            "validate",
            "--dataset",
            str(FIXTURES_DIR / "gold_tasks_held_out_v1.json"),
            "--fixtures",
            str(FIXTURES_DIR / "mock_store_v1.json"),
            "--config",
            str(CONFIG_DIR / "model_deterministic.json"),
        ]
    )
    assert rc == 1
    assert "HeldOutLeakageError" in capsys.readouterr().err
