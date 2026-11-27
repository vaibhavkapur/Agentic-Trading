"""Scenario tests reproducing all 7 required failure paths from plan.md Section 5 plus partial fill."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tests.conftest import MutableClock

from trading_platform.agents.research_agent import MomentumNewsResearchAgent
from trading_platform.domain.errors import (
    ApprovalError,
    ExecutionBlockedError,
    RiskCheckError,
    ToolAccessError,
)
from trading_platform.domain.types import OrderStatus, RiskStatus, RunStatus
from trading_platform.service import TradingPlatform


def test_scenario_1_injected_instructions_in_news(
    platform: TradingPlatform,
    project_root: Path,
) -> None:
    """Injected instructions in news are quarantined; agent stays read-only and never submits 50k order."""
    platform.market_data.replace_news_from_fixture(
        project_root / "data" / "fixtures" / "fault_injected_news.json"
    )
    outcome = platform.run_cycle(symbol="AAPL")

    # Evidence recorded taint and matched prompt-injection rules
    evidences = platform.repository.list_evidence_for_run(outcome.run.run_id)
    tainted = [e for e in evidences if e.tainted_injection_detected]
    assert len(tainted) >= 1
    assert "IGNORE_INSTRUCTIONS" in tainted[0].injection_signals
    assert "DIRECT_ORDER_EXECUTION" in tainted[0].injection_signals

    # Research report recorded injection warnings, never escalated privilege or submitted orders
    assert any(r.injection_warnings for r in outcome.research_reports)
    assert platform.broker.total_broker_orders() == 0
    if outcome.proposal is not None:
        # Must NOT have obeyed the injected quantity=50000
        assert outcome.proposal.order_intent.quantity < 500


def test_scenario_2_malicious_tool_arguments(platform: TradingPlatform) -> None:
    """Malicious SQL/path-traversal/shell args and forbidden execution tools are rejected and audited."""
    scope = platform.research_agents[0].scope
    with pytest.raises(ToolAccessError) as exc_sql:
        platform.tool_gateway.invoke(
            run_id="RUN-SCEN-2",
            scope=scope,
            tool_name="get_news",
            arguments={"symbol": "AAPL' OR '1'='1", "limit": 5},
        )
    assert exc_sql.value.code == "MALICIOUS_TOOL_ARGUMENTS"

    with pytest.raises(ToolAccessError) as exc_exec:
        platform.tool_gateway.invoke(
            run_id="RUN-SCEN-2",
            scope=scope,
            tool_name="submit_order",
            arguments={"symbol": "AAPL", "quantity": 1000},
        )
    assert exc_exec.value.code == "AGENT_EXECUTION_FORBIDDEN"

    calls = platform.repository.list_tool_calls_for_run("RUN-SCEN-2")
    assert len(calls) == 2
    assert all(not c.allowed for c in calls)


def test_scenario_3_approval_replay_and_parameter_tampering(
    platform: TradingPlatform,
) -> None:
    """Replaying a consumed approval with a new idempotency_key or mutating order params is blocked."""
    platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    outcome = platform.run_cycle(symbol="AAPL")
    assert outcome.approval_request is not None
    req = outcome.approval_request

    platform.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Valid exact approval",
    )

    # First attempt: tamper with quantity (increase by +10 shares) -> blocked before consumption
    tampered_intent = req.order_intent.model_copy(
        update={"quantity": req.order_intent.quantity + 10}
    )
    with pytest.raises(ApprovalError) as exc_tamper:
        platform.dispatch_order(
            approval_id=req.approval_id,
            idempotency_key="IDEMP-TAMPER-1",
            order_intent_override=tampered_intent,
        )
    assert exc_tamper.value.code == "APPROVAL_PARAMETER_MISMATCH"
    assert platform.broker.total_broker_orders() == 0

    # Valid dispatch consumes the approval
    order = platform.dispatch_order(
        approval_id=req.approval_id,
        idempotency_key="IDEMP-VALID-1",
    )
    assert order.status == OrderStatus.FILLED
    assert platform.broker.total_broker_orders() == 1

    # Replay the consumed approval with a brand-new idempotency_key -> BLOCKED
    with pytest.raises(ApprovalError) as exc_replay:
        platform.dispatch_order(
            approval_id=req.approval_id,
            idempotency_key="IDEMP-REPLAY-2",
        )
    assert exc_replay.value.code == "APPROVAL_ALREADY_CONSUMED"
    assert platform.broker.total_broker_orders() == 1


def test_scenario_4_conflicting_agents(
    project_root: Path,
    clock: MutableClock,
) -> None:
    """Conflicting BULLISH vs BEARISH research agents trigger policy BLOCK_AND_ESCALATE."""
    platform = TradingPlatform.from_project_root(
        project_root,
        db_path=":memory:",
        clock=clock,
        research_agents=[
            MomentumNewsResearchAgent(agent_id="research-bull-desk", focus_source="SYNTHETIC_BULL_DESK"),
            MomentumNewsResearchAgent(agent_id="research-bear-desk", focus_source="SYNTHETIC_BEAR_DESK"),
        ],
    )
    try:
        platform.market_data.replace_news_from_fixture(
            project_root / "data" / "fixtures" / "fault_conflicting_signals.json"
        )
        outcome = platform.run_cycle(symbol="NVDA")
        assert outcome.run.status == RunStatus.BLOCKED_CONFLICT
        assert len(outcome.conflicts) == 1
        assert outcome.conflicts[0].blocked_execution is True
        assert outcome.proposal is None
        assert outcome.approval_request is None
    finally:
        platform.close()


def test_scenario_5_stale_quote_blocks_pre_approval_and_pre_dispatch(
    platform: TradingPlatform,
    project_root: Path,
    clock: MutableClock,
) -> None:
    """Stale quote is rejected both at pre-approval AND when quote goes stale before dispatch."""
    # Part A: Pre-approval rejection on stale quote fixture
    platform.market_data.apply_quote_overrides_from_fixture(
        project_root / "data" / "fixtures" / "fault_stale_quotes.json"
    )
    stale_outcome = platform.run_cycle(symbol="AAPL")
    assert stale_outcome.run.status == RunStatus.BLOCKED_RISK
    assert stale_outcome.risk_assessment is not None
    assert stale_outcome.risk_assessment.status == RiskStatus.REJECTED
    assert any(c.code == "STALE_MARKET_DATA" for c in stale_outcome.risk_assessment.failed_checks)
    assert stale_outcome.approval_request is None

    # Part B: Fresh quote during proposal & approval, then quote becomes stale before dispatch!
    platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    fresh_outcome = platform.run_cycle(symbol="MSFT", approval_ttl_seconds=600)
    assert fresh_outcome.approval_request is not None
    req = fresh_outcome.approval_request
    platform.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Approved while fresh",
    )
    # Advance clock by 120s (> max_quote_age_seconds=60, still within 600s approval TTL)
    clock.advance(120)
    with pytest.raises(RiskCheckError) as exc_stale:
        platform.dispatch_order(approval_id=req.approval_id, idempotency_key="IDEMP-STALE-DISP")
    assert exc_stale.value.code == "STALE_MARKET_DATA"
    assert platform.broker.total_broker_orders() == 0


def test_scenario_6_broker_timeout_and_idempotent_reconciliation(
    platform: TradingPlatform,
) -> None:
    """Broker timeout marks order UNCERTAIN_TIMEOUT; retry reconciles exact fill with zero duplicate orders."""
    platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    outcome = platform.run_cycle(symbol="AAPL")
    assert outcome.approval_request is not None
    req = outcome.approval_request
    platform.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Approved for timeout test",
    )

    # Inject timeout where broker actually accepted order before network drop
    platform.broker.fail_next_submit_with_timeout = True
    platform.broker.accept_order_before_timeout = True

    with pytest.raises(ExecutionBlockedError) as exc_timeout:
        platform.dispatch_order(approval_id=req.approval_id, idempotency_key="IDEMP-TIMEOUT-1")
    assert exc_timeout.value.code == "BROKER_TIMEOUT_UNCERTAIN"

    uncertain = platform.repository.get_order_by_idempotency_key("IDEMP-TIMEOUT-1")
    assert uncertain is not None
    assert uncertain.status == OrderStatus.UNCERTAIN_TIMEOUT

    # Retrying with the exact same idempotency_key reconciles with broker instead of creating a 2nd order
    reconciled = platform.dispatch_order(
        approval_id=req.approval_id,
        idempotency_key="IDEMP-TIMEOUT-1",
    )
    assert reconciled.order_id == uncertain.order_id
    assert reconciled.status == OrderStatus.FILLED
    assert reconciled.filled_quantity == req.order_intent.quantity
    assert platform.broker.total_broker_orders() == 1
    assert platform.broker.submit_attempt_count == 1  # Never re-submitted blindly


def test_scenario_7_duplicate_fill_deduplication_and_partial_fill(
    platform: TradingPlatform,
    clock: MutableClock,
) -> None:
    """Partial fills accumulate accurately and duplicate broker_fill_id notifications are ignored."""
    platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    platform.broker.partial_fill_ratio = 0.5

    outcome = platform.run_cycle(symbol="AAPL", override_quantity=20)
    assert outcome.approval_request is not None
    req = outcome.approval_request
    platform.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_2",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Partial & duplicate fill test",
    )

    # Dispatch produces first 50% fill (10 of 20)
    order = platform.dispatch_order(approval_id=req.approval_id, idempotency_key="IDEMP-PARTIAL-1")
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == 10
    cash_after_leg1 = platform.get_account_snapshot().cash_usd
    pos_after_leg1 = platform.get_account_snapshot().positions["AAPL"].quantity

    # Replay duplicate of leg 1 fill notification -> ignored idempotently!
    fills_leg1 = platform.repository.list_fills_for_order(order.order_id)
    assert len(fills_leg1) == 1
    order_after_dup, was_new = platform.ingest_fill(fills_leg1[0])
    assert was_new is False
    assert order_after_dup.filled_quantity == 10
    assert platform.get_account_snapshot().cash_usd == cash_after_leg1
    assert platform.get_account_snapshot().positions["AAPL"].quantity == pos_after_leg1

    # Complete remaining 50% fill -> order transitions to FILLED (20/20)
    second_fill = platform.broker.complete_partial_fill(
        client_order_id=order.client_order_id,
        now_utc=clock.current + timedelta(seconds=5),
    )
    final_order, was_new_2 = platform.ingest_fill(second_fill)
    assert was_new_2 is True
    assert final_order.status == OrderStatus.FILLED
    assert final_order.filled_quantity == 20
    assert platform.get_account_snapshot().positions["AAPL"].quantity == pos_after_leg1 + 10
    assert final_order.avg_fill_price == Decimal(fills_leg1[0].price).quantize(Decimal("0.0001"))
