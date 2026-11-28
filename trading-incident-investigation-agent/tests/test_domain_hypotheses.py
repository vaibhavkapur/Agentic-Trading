"""M2 tests: runbook retrieval, hypothesis testing, missing spans, misleading logs, and budgets."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_incident_agent import (
    AgentConfig,
    BudgetExceededError,
    TradingIncidentAgent,
    VerdictStatus,
    load_incident_bundle,
)
from trading_incident_agent.models import BudgetConfig


def test_missing_spans_and_misleading_logs_scenario(
    fixtures_dir: Path, agent: TradingIncidentAgent
) -> None:
    """Domain correctness: resist red-herring logs and surface missing-span uncertainty."""
    bundle = load_incident_bundle(fixtures_dir / "inc_missing_spans_002.json")
    report = agent.investigate(bundle)

    # 1. Missing parent spans are explicitly detected and reported
    assert len(report.timeline.trace_gaps) == 2
    assert all(g.gap_type == "missing_parent_span" for g in report.timeline.trace_gaps)
    assert any("trace gap" in note.lower() for note in report.uncertainty_notes)

    # 2. Primary root cause correctly identifies OMS rate-limit throttle (not market-data red herring)
    assert report.verdict_status == VerdictStatus.DETERMINED
    assert report.primary_root_cause is not None
    assert report.primary_root_cause.failure_mode == "oms_rate_limit_throttle"
    assert report.primary_root_cause.service == "oms-core"
    assert any(
        "incomplete" in u.lower() or "trace gap" in u.lower()
        for u in report.primary_root_cause.uncertainty_factors
    )

    # 3. Confidence reflects missing-span penalty (must not be overconfident >= 0.90)
    assert 0.50 <= report.confidence <= 0.90

    # 4. Misleading market-data-feed hypothesis is ranked below and carries counterevidence
    md_hyp = next(
        (h for h in report.hypotheses if h.failure_mode == "market_data_feed_stale"), None
    )
    assert md_hyp is not None
    assert md_hyp.confidence < 0.30
    assert len(md_hyp.counterevidence) >= 1
    assert any(
        "healthy ok span" in c.rationale.lower() or "archival" in c.rationale.lower()
        for c in md_hyp.counterevidence
    )


def test_insufficient_evidence_when_no_runbooks_match(
    fixtures_dir: Path, agent: TradingIncidentAgent
) -> None:
    bundle = load_incident_bundle(fixtures_dir / "inc_ref_001_gateway_pool.json")
    stripped = bundle.model_copy(update={"runbooks": []})
    report = agent.investigate(stripped)

    assert report.verdict_status == VerdictStatus.INSUFFICIENT_EVIDENCE
    assert report.primary_root_cause is None
    assert report.proposed_remediations == []
    assert any("minimum confidence threshold" in n.lower() for n in report.uncertainty_notes)


def test_budget_exceeded_error_is_enforced(fixtures_dir: Path) -> None:
    bundle = load_incident_bundle(fixtures_dir / "inc_ref_001_gateway_pool.json")
    tight_config = AgentConfig(budgets=BudgetConfig(max_steps=2, max_tool_calls=2))
    agent = TradingIncidentAgent(config=tight_config)

    with pytest.raises(BudgetExceededError) as exc_info:
        agent.investigate(bundle)
    assert exc_info.value.error_code == "BUDGET_EXCEEDED_ERROR"
