"""Integration tests for end-to-end orchestration, exact-action approvals, pre-dispatch risk, and OMS."""

from __future__ import annotations

import pytest
from tests.conftest import MutableClock

from trading_platform.domain.errors import ExecutionBlockedError
from trading_platform.domain.types import ApprovalStatus, OrderStatus, RiskStatus, RunStatus
from trading_platform.service import TradingPlatform


def test_full_paper_trading_lifecycle_with_provenance_and_idempotency(
    platform: TradingPlatform,
    clock: MutableClock,
) -> None:
    # 1. Run orchestration cycle (does NOT submit orders)
    outcome = platform.run_cycle(symbol="AAPL")
    assert outcome.run.status == RunStatus.AWAITING_APPROVAL
    assert outcome.proposal is not None
    assert outcome.risk_assessment is not None
    assert outcome.risk_assessment.stage == "PRE_APPROVAL"
    assert outcome.risk_assessment.status == RiskStatus.APPROVED
    assert outcome.approval_request is not None
    assert platform.broker.total_broker_orders() == 0

    req = outcome.approval_request
    # 2. Human operator approves exact-action hash
    approved = platform.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Reviewed AAPL thesis and risk checks",
    )
    assert approved.status == ApprovalStatus.APPROVED

    # 3. Dispatch fails while execution_mode is DISABLED (default)
    with pytest.raises(ExecutionBlockedError) as exc_dis:
        platform.dispatch_order(
            approval_id=req.approval_id,
            idempotency_key="IDEMP-AAPL-001",
        )
    assert exc_dis.value.code == "EXECUTION_DISABLED"
    assert platform.broker.total_broker_orders() == 0

    # 4. Enable PAPER mode explicitly and dispatch
    platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    order = platform.dispatch_order(
        approval_id=req.approval_id,
        idempotency_key="IDEMP-AAPL-001",
    )
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == req.order_intent.quantity
    assert platform.broker.total_broker_orders() == 1

    # 5. Verify risk checks ran TWICE (PRE_APPROVAL and PRE_DISPATCH)
    assessments = platform.repository.list_risk_assessments_for_proposal(outcome.proposal.proposal_id)
    assert [a.stage for a in assessments] == ["PRE_APPROVAL", "PRE_DISPATCH"]
    assert all(a.status == RiskStatus.APPROVED for a in assessments)

    # 6. Duplicate dispatch with same idempotency_key returns same order, no duplicate broker order
    dup_order = platform.dispatch_order(
        approval_id=req.approval_id,
        idempotency_key="IDEMP-AAPL-001",
    )
    assert dup_order.order_id == order.order_id
    assert platform.broker.total_broker_orders() == 1

    # 7. Full provenance traces order -> approval -> risk -> proposal -> research -> evidence & policy
    prov = platform.get_run_provenance(outcome.run.run_id)
    assert prov is not None
    assert prov["order"]["order_id"] == order.order_id
    assert prov["order"]["policy_version"] == platform.config.policy.policy_version
    assert len(prov["evidence"]) >= 5
    assert len(prov["fills"]) == 1

    # 8. Audit hash chain is valid
    valid, count, err = platform.repository.verify_audit_chain()
    assert valid is True and count > 8 and err is None


def test_kill_switch_halts_dispatch_even_in_paper_mode(platform: TradingPlatform) -> None:
    platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    outcome = platform.run_cycle(symbol="MSFT")
    assert outcome.approval_request is not None
    req = outcome.approval_request
    platform.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_2",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Approved prior to kill switch",
    )
    platform.set_kill_switch(active=True, actor_id="ops_approver_1", reason="Incident drill")
    with pytest.raises(ExecutionBlockedError) as exc_ks:
        platform.dispatch_order(approval_id=req.approval_id, idempotency_key="IDEMP-KS-001")
    assert exc_ks.value.code == "KILL_SWITCH_ACTIVE"
    assert platform.broker.total_broker_orders() == 0
