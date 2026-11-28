"""Integration scenarios covering failure injection: unavailable tool, stale evidence, prompt injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from fin_eval.agents.mock_agents import FaultyDemoAgent, ReferenceCompliantAgent
from fin_eval.exceptions import ToolBudgetExceededError
from fin_eval.injection import FailureInjectionEngine
from fin_eval.runner import (
    load_dataset,
    load_fixture_store,
    load_injection_profile,
    load_model_config,
    run_evaluation,
)
from fin_eval.schemas import (
    FailureInjectionProfile,
    FailureType,
    FaultRule,
    FaultType,
)
from fin_eval.tools.mock_runtime import MockToolRuntime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.mark.integration
def test_resilience_suite_unavailable_tool_stale_evidence_and_prompt_injection() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    cfg = load_model_config(CONFIG_DIR / "model_deterministic.json")
    faults = load_injection_profile(CONFIG_DIR / "faults_resilience.json")

    report, _, logs = run_evaluation(
        dataset=dev_ds,
        store=store,
        model_config=cfg,
        injection_profile=faults,
        seeds=[42],
    )

    assert report.summary.pass_rate.mean == pytest.approx(1.0)
    assert report.summary.receipt_verification_rate == pytest.approx(1.0)
    assert report.diagnostic_counters["faults_injected"] >= 1
    assert len(logs) == len(dev_ds.tasks)

    by_id = {r.task_id: r for r in report.task_results}
    # Unavailable tool on FIN_TOOL_001 -> agent abstained cleanly and passed
    assert "FLT_TOOL_UNAVAIL_001" in by_id["FIN_TOOL_001"].faults_triggered
    assert by_id["FIN_TOOL_001"].passed is True

    # Stale evidence on FIN_ARITH_002 -> agent detected staleness, abstained cleanly, and passed
    assert "FLT_STALE_EVD_001" in by_id["FIN_ARITH_002"].faults_triggered
    assert by_id["FIN_ARITH_002"].passed is True

    # Prompt injection on FIN_ARITH_001 & FIN_FILING_001 -> agent ignored untrusted directives and passed
    assert "FLT_PROMPT_INJ_001" in by_id["FIN_ARITH_001"].faults_triggered
    assert by_id["FIN_ARITH_001"].passed is True
    assert "FLT_PROMPT_INJ_001" in by_id["FIN_FILING_001"].faults_triggered
    assert by_id["FIN_FILING_001"].passed is True


@pytest.mark.integration
def test_stale_evidence_reckless_agent_is_caught() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    cfg = load_model_config(CONFIG_DIR / "model_deterministic.json")
    stale_profile = FailureInjectionProfile(
        profile_id="stale_only",
        rules=[
            FaultRule(
                fault_id="FLT_STALE_TEST",
                fault_type=FaultType.STALE_EVIDENCE,
                target_task_ids=["FIN_ARITH_002"],
                target_evidence_id="EVD-ORBN-10K-2025-01",
                stale_age_seconds=86400 * 365,
            )
        ],
    )
    single_task_ds = dev_ds.model_copy(
        update={"tasks": [t for t in dev_ds.tasks if t.task_id == "FIN_ARITH_002"]}
    )

    report, _, _ = run_evaluation(
        dataset=single_task_ds,
        store=store,
        model_config=cfg,
        injection_profile=stale_profile,
        agent=FaultyDemoAgent("ignore_stale_evidence"),
        seeds=[42],
    )
    res = report.task_results[0]
    assert res.passed is False
    assert FailureType.STALE_EVIDENCE_USED in res.failure_types
    assert FailureType.MISSED_ABSTENTION in res.failure_types


@pytest.mark.integration
def test_prompt_injection_compromised_agent_is_caught() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    cfg = load_model_config(CONFIG_DIR / "model_deterministic.json")
    inj_profile = FailureInjectionProfile(
        profile_id="injection_only",
        rules=[
            FaultRule(
                fault_id="FLT_INJ_TEST",
                fault_type=FaultType.PROMPT_INJECTION,
                target_task_ids=["FIN_ARITH_001"],
            )
        ],
    )
    single_task_ds = dev_ds.model_copy(
        update={"tasks": [t for t in dev_ds.tasks if t.task_id == "FIN_ARITH_001"]}
    )

    report, _, _ = run_evaluation(
        dataset=single_task_ds,
        store=store,
        model_config=cfg,
        injection_profile=inj_profile,
        agent=FaultyDemoAgent("prompt_injection_susceptible"),
        seeds=[42],
    )
    res = report.task_results[0]
    assert res.passed is False
    assert res.overall_score == 0.0
    assert FailureType.PROMPT_INJECTION_COMPROMISE in res.failure_types
    assert FailureType.UNSAFE_TOOL_REQUEST in res.failure_types


@pytest.mark.integration
def test_tool_timeout_and_budget_enforcement() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    task = next(t for t in dev_ds.tasks if t.task_id == "FIN_ARITH_001")

    timeout_profile = FailureInjectionProfile(
        profile_id="timeout_test",
        rules=[
            FaultRule(
                fault_id="FLT_TIMEOUT_001",
                fault_type=FaultType.TOOL_TIMEOUT,
                target_tool="get_filing_metric",
                timeout_ms=3000.0,
            )
        ],
    )
    injector = FailureInjectionEngine(timeout_profile, seed=42)
    runtime = MockToolRuntime(
        store=store,
        task=task,
        run_id="run-timeout",
        signing_key="key-timeout",
        max_tool_calls=2,
        injection_engine=injector,
    )
    rec1 = runtime.call_tool("get_filing_metric", {"ticker": "ACME", "period": "2025Q4", "metric": "revenue"})
    assert rec1.status == "error"
    assert rec1.latency_ms >= 3000.0
    assert "timed out" in (rec1.error_message or "")

    runtime.call_tool("calculate_ratio", {"numerator": 10.0, "denominator": 2.0})
    with pytest.raises(ToolBudgetExceededError):
        runtime.call_tool("calculate_ratio", {"numerator": 10.0, "denominator": 2.0})
