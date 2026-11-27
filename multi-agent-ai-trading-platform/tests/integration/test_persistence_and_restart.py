"""Integration test verifying SQLite persistence and clean restart recovery."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import MutableClock

from trading_platform.domain.types import ApprovalStatus, ExecutionMode, OrderStatus
from trading_platform.service import TradingPlatform


def test_restart_recovery_preserves_approvals_orders_account_and_audit_chain(
    project_root: Path,
    tmp_path: Path,
    clock: MutableClock,
) -> None:
    db_path = tmp_path / "restart_state.sqlite3"

    # Instance 1: Enable PAPER, run cycle, approve, dispatch
    p1 = TradingPlatform.from_project_root(project_root, db_path=db_path, clock=clock)
    p1.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    out1 = p1.run_cycle(symbol="AAPL")
    assert out1.approval_request is not None
    req1 = out1.approval_request
    p1.decide_approval(
        approval_id=req1.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req1.exact_action_hash,
        reason="Pre-restart approval",
    )
    ord1 = p1.dispatch_order(approval_id=req1.approval_id, idempotency_key="IDEMP-RESTART-1")
    cash_after_fill = p1.get_account_snapshot().cash_usd
    qty_after_fill = p1.get_account_snapshot().positions["AAPL"].quantity

    # Also leave a second approval pending across the restart
    out2 = p1.run_cycle(symbol="MSFT")
    assert out2.approval_request is not None
    pending_id = out2.approval_request.approval_id
    p1.close()

    # Instance 2: Cold restart pointing to the same SQLite DB
    p2 = TradingPlatform.from_project_root(project_root, db_path=db_path, clock=clock)
    try:
        assert p2.repository.get_execution_mode() == ExecutionMode.PAPER
        assert p2.get_account_snapshot().cash_usd == cash_after_fill
        assert p2.get_account_snapshot().positions["AAPL"].quantity == qty_after_fill

        # Re-sending old idempotency key after restart does NOT duplicate order
        recovered_order = p2.dispatch_order(
            approval_id=req1.approval_id,
            idempotency_key="IDEMP-RESTART-1",
        )
        assert recovered_order.order_id == ord1.order_id
        assert recovered_order.status == OrderStatus.FILLED
        assert p2.broker.total_broker_orders() == 0  # Served from persisted state

        # Pending approval survived restart and remains usable
        pending = p2.repository.get_approval(pending_id)
        assert pending is not None and pending.status == ApprovalStatus.PENDING

        # Hash-chained audit log remained unbroken across restart
        valid, count, err = p2.repository.verify_audit_chain()
        assert valid is True and count >= 10 and err is None
    finally:
        p2.close()
