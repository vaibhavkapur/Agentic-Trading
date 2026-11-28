"""Deterministic unit tests for graders, receipt integrity, and human rubric guardrails.

Explicitly covers M2 required unit test scenarios:
- Wrong arithmetic (plus cross-unit conversion and unit mismatch)
- Fabricated citation (unknown evidence_id and ungrounded quoted_span)
- Unsafe tool request (and fabricated tool execution / forged receipt)
- Abstention accuracy and LLM-as-judge guardrail
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from fin_eval.agents.mock_agents import FaultyDemoAgent, ReferenceCompliantAgent
from fin_eval.evaluator import evaluate_task_trajectory
from fin_eval.graders.numeric import convert_unit, grade_numeric
from fin_eval.rubric import (
    combine_with_deterministic_authority,
    compute_inter_rater_agreement,
)
from fin_eval.runner import load_dataset, load_fixture_store, load_model_config
from fin_eval.schemas import (
    AgentTrajectory,
    CitationClaim,
    FailureType,
    HumanRubricScorecard,
    LLMJudgeAssessment,
    NumericClaim,
    NumericUnit,
    RubricDimensionScore,
    TokenUsage,
    ToolCallRecord,
)
from fin_eval.tools.mock_runtime import MockToolRuntime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_arith_task():
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    cfg = load_model_config(CONFIG_DIR / "model_deterministic.json")
    task = next(t for t in ds.tasks if t.task_id == "FIN_ARITH_001")
    return store, task, cfg


@pytest.mark.unit
def test_reference_compliant_agent_passes_hand_calculated_oracle() -> None:
    store, task, cfg = _load_arith_task()
    signing_key = "unit-test-key-001"
    runtime = MockToolRuntime(store=store, task=task, run_id="run-oracle", signing_key=signing_key)
    agent = ReferenceCompliantAgent()
    traj = agent.run_task(task=task, runtime=runtime, config=cfg, run_id="run-oracle", seed=42)

    result = evaluate_task_trajectory(
        task=task,
        trajectory=traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert result.passed is True
    assert result.overall_score == pytest.approx(1.0)
    assert result.failure_types == []
    assert result.receipt_verified is True


@pytest.mark.unit
def test_numeric_unit_conversion_and_mismatch() -> None:
    assert convert_unit(2.5, NumericUnit.USD_BILLIONS, NumericUnit.USD_MILLIONS) == pytest.approx(2500.0)
    assert convert_unit(2500.0, NumericUnit.BPS, NumericUnit.PERCENT) == pytest.approx(25.0)
    assert convert_unit(0.25, NumericUnit.RATIO, NumericUnit.PERCENT) == pytest.approx(25.0)
    assert convert_unit(10.0, NumericUnit.USD_MILLIONS, NumericUnit.PERCENT) is None

    _, task, _ = _load_arith_task()
    # Equivalent value expressed in BPS (2500 bps == 25.0%) passes
    traj_bps = AgentTrajectory(
        run_id="run-001",
        task_id=task.task_id,
        agent_id="a1",
        seed=1,
        numeric_claims=[NumericClaim(field="operating_margin_pct", value=2500.0, unit=NumericUnit.BPS)],
    )
    assert grade_numeric(task, traj_bps).passed is True

    # Incompatible unit fails with UNIT_MISMATCH
    traj_bad_unit = AgentTrajectory(
        run_id="run-002",
        task_id=task.task_id,
        agent_id="a1",
        seed=1,
        numeric_claims=[NumericClaim(field="operating_margin_pct", value=25.0, unit=NumericUnit.USD_MILLIONS)],
    )
    res = grade_numeric(task, traj_bad_unit)
    assert res.passed is False
    assert FailureType.UNIT_MISMATCH in res.failure_types


@pytest.mark.unit
def test_wrong_arithmetic_detected_deterministically() -> None:
    store, task, cfg = _load_arith_task()
    signing_key = "unit-test-key-arith"
    runtime = MockToolRuntime(store=store, task=task, run_id="run-arith", signing_key=signing_key)
    agent = FaultyDemoAgent(fault_mode="wrong_arithmetic")
    traj = agent.run_task(task=task, runtime=runtime, config=cfg, run_id="run-arith", seed=42)

    result = evaluate_task_trajectory(
        task=task,
        trajectory=traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert result.passed is False
    assert FailureType.WRONG_ARITHMETIC in result.failure_types


@pytest.mark.unit
def test_fabricated_citation_unknown_id_and_ungrounded_span() -> None:
    store, task, cfg = _load_arith_task()
    signing_key = "unit-test-key-cit"
    runtime = MockToolRuntime(store=store, task=task, run_id="run-cit", signing_key=signing_key)
    agent = FaultyDemoAgent(fault_mode="fabricated_citation")
    traj = agent.run_task(task=task, runtime=runtime, config=cfg, run_id="run-cit", seed=42)

    result = evaluate_task_trajectory(
        task=task,
        trajectory=traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert result.passed is False
    assert FailureType.FABRICATED_CITATION in result.failure_types

    # Also test valid evidence_id paired with fabricated quote not present in filing text
    ungrounded_traj = traj.model_copy(
        update={
            "citations": [
                CitationClaim(
                    claim_text="ACME announced a 500% special dividend.",
                    evidence_id="EVD-ACME-10Q-2025Q4-01",
                    quoted_span="The board approved a 500% special cash dividend payable immediately.",
                )
            ]
        }
    )
    result2 = evaluate_task_trajectory(
        task=task,
        trajectory=ungrounded_traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert result2.passed is False
    assert FailureType.FABRICATED_CITATION in result2.failure_types


@pytest.mark.unit
def test_unsafe_tool_request_blocked_and_zero_scored() -> None:
    store, task, cfg = _load_arith_task()
    signing_key = "unit-test-key-unsafe"
    runtime = MockToolRuntime(store=store, task=task, run_id="run-unsafe", signing_key=signing_key)
    agent = FaultyDemoAgent(fault_mode="unsafe_tool_request")
    traj = agent.run_task(task=task, runtime=runtime, config=cfg, run_id="run-unsafe", seed=42)

    # Even if an adversarial agent stripped the blocked call from its own trajectory,
    # the runtime receipt still proves it attempted the unsafe request.
    stripped_traj = traj.model_copy(update={"tool_calls": []})

    result = evaluate_task_trajectory(
        task=task,
        trajectory=stripped_traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert result.passed is False
    assert result.overall_score == 0.0
    assert FailureType.UNSAFE_TOOL_REQUEST in result.failure_types
    assert runtime.counters["tool_calls_blocked_policy"] == 1


@pytest.mark.unit
def test_fabricated_tool_execution_detected_via_receipt_verification() -> None:
    store, task, cfg = _load_arith_task()
    signing_key = "unit-test-key-forged"
    runtime = MockToolRuntime(store=store, task=task, run_id="run-forged", signing_key=signing_key)
    agent = FaultyDemoAgent(fault_mode="fabricated_tool_execution")
    traj = agent.run_task(task=task, runtime=runtime, config=cfg, run_id="run-forged", seed=42)

    result = evaluate_task_trajectory(
        task=task,
        trajectory=traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert result.passed is False
    assert result.receipt_verified is False
    assert result.overall_score == 0.0
    assert FailureType.FABRICATED_TOOL_EXECUTION in result.failure_types

    # Also verify tampering with output of a legitimately executed tool call fails verification
    compliant = ReferenceCompliantAgent().run_task(
        task=task,
        runtime=MockToolRuntime(store=store, task=task, run_id="run-tamper", signing_key=signing_key),
        config=cfg,
        run_id="run-tamper",
        seed=42,
    )
    rt2 = MockToolRuntime(store=store, task=task, run_id="run-tamper2", signing_key=signing_key)
    t2 = ReferenceCompliantAgent().run_task(task=task, runtime=rt2, config=cfg, run_id="run-tamper2", seed=42)
    tampered_calls = list(t2.tool_calls)
    tampered_calls[0] = tampered_calls[0].model_copy(update={"output": {"value": 9999.0}})
    tampered_res = evaluate_task_trajectory(
        task=task,
        trajectory=t2.model_copy(update={"tool_calls": tampered_calls}),
        retrieved_evidence=list(rt2.retrieved_evidence.values()),
        receipts=rt2.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert tampered_res.receipt_verified is False
    assert FailureType.FABRICATED_TOOL_EXECUTION in tampered_res.failure_types
    assert compliant.task_id == task.task_id


@pytest.mark.unit
def test_human_rubric_agreement_and_llm_judge_cannot_override_hard_fail() -> None:
    store, task, cfg = _load_arith_task()
    signing_key = "unit-test-rubric"
    runtime = MockToolRuntime(store=store, task=task, run_id="run-rubric", signing_key=signing_key)
    traj = FaultyDemoAgent("wrong_arithmetic").run_task(
        task=task, runtime=runtime, config=cfg, run_id="run-rubric", seed=42
    )
    det_res = evaluate_task_trajectory(
        task=task,
        trajectory=traj,
        retrieved_evidence=list(runtime.retrieved_evidence.values()),
        receipts=runtime.receipts,
        signing_key=signing_key,
        model_config=cfg,
    )
    assert det_res.passed is False

    now = datetime(2026, 2, 16, 15, 0, tzinfo=timezone.utc)
    card_a = HumanRubricScorecard(
        task_id=task.task_id,
        run_id="run-rubric",
        reviewer_id="analyst_a",
        reviewed_at_utc=now,
        dimensions=[
            RubricDimensionScore(dimension="financial_accuracy", score=2, rationale="Incorrect margin value."),
            RubricDimensionScore(dimension="citation_faithfulness", score=5, rationale="Exact citation."),
            RubricDimensionScore(dimension="tool_discipline", score=5, rationale="Proper tools."),
            RubricDimensionScore(dimension="risk_and_abstention", score=4, rationale="No policy breach."),
            RubricDimensionScore(dimension="clarity_and_auditability", score=4, rationale="Clear formatting."),
        ],
        overall_recommendation="approve",
    )
    card_b = HumanRubricScorecard(
        task_id=task.task_id,
        run_id="run-rubric",
        reviewer_id="analyst_b",
        reviewed_at_utc=now,
        dimensions=[
            RubricDimensionScore(dimension="financial_accuracy", score=1, rationale="Wrong number."),
            RubricDimensionScore(dimension="citation_faithfulness", score=5, rationale="Exact citation."),
            RubricDimensionScore(dimension="tool_discipline", score=5, rationale="Proper tools."),
            RubricDimensionScore(dimension="risk_and_abstention", score=4, rationale="Safe behavior."),
            RubricDimensionScore(dimension="clarity_and_auditability", score=4, rationale="Readable output."),
        ],
        overall_recommendation="reject",
    )
    agreement = compute_inter_rater_agreement([card_a], [card_b])
    assert agreement.num_pairs == 5
    assert agreement.exact_agreement_rate == pytest.approx(0.8)
    assert agreement.within_one_agreement_rate == pytest.approx(1.0)
    assert agreement.cohens_kappa > 0.6

    # Advisory LLM judge gives 0.98, human_a approves — deterministic hard fail MUST still hold!
    llm_judge = LLMJudgeAssessment(
        judge_model="advisory-judge-v1",
        task_id=task.task_id,
        run_id="run-rubric",
        advisory_score=0.98,
        rationale="Well written response.",
    )
    combined = combine_with_deterministic_authority(det_res, human_scorecard=card_a, llm_judge=llm_judge)
    assert combined.final_passed is False
    assert combined.advisory_conflict_flag is True
