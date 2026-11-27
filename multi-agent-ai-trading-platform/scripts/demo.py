"""Reproducible end-to-end paper trading demo with provenance and audit verification."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from trading_platform.domain.errors import ExecutionBlockedError
from trading_platform.service import TradingPlatform

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_OUT = ROOT / "reports" / "evidence" / "demo_evidence.json"


def run_demo() -> dict:
    started = time.perf_counter()
    fixed_clock = lambda: datetime(2026, 11, 27, 14, 30, 0, tzinfo=UTC)  # noqa: E731
    platform = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=fixed_clock)
    try:
        # Step 1: Multi-agent orchestration for AAPL (execution still DISABLED by default)
        outcome = platform.run_cycle(symbol="AAPL")
        assert outcome.approval_request is not None, "Expected approval request for AAPL"
        req = outcome.approval_request

        # Step 2: Confirm agents did NOT submit orders
        assert platform.broker.total_broker_orders() == 0

        # Step 3: Human Risk Officer approves exact-action hash
        approved = platform.decide_approval(
            approval_id=req.approval_id,
            actor_id="ops_approver_1",
            approve=True,
            expected_action_hash=req.exact_action_hash,
            reason="Demo verification of AAPL exact parameters and evidence",
        )

        # Step 4: Verify default DISABLED execution mode blocks dispatch
        disabled_block_code = None
        try:
            platform.dispatch_order(approval_id=req.approval_id, idempotency_key="DEMO-IDEMP-001")
        except ExecutionBlockedError as exc:
            disabled_block_code = exc.code
        assert disabled_block_code == "EXECUTION_DISABLED"

        # Step 5: Explicitly enable PAPER mode and dispatch
        platform.set_execution_mode(
            mode="PAPER",
            actor_id="ops_approver_1",
            reason="Enable paper/sandbox broker for demo",
        )
        order = platform.dispatch_order(
            approval_id=req.approval_id,
            idempotency_key="DEMO-IDEMP-001",
            actor_id="ops_approver_1",
        )

        # Step 6: Duplicate dispatch returns same order without creating a second broker order
        dup_order = platform.dispatch_order(
            approval_id=req.approval_id,
            idempotency_key="DEMO-IDEMP-001",
            actor_id="ops_approver_1",
        )
        assert dup_order.order_id == order.order_id
        assert platform.broker.total_broker_orders() == 1

        provenance = platform.get_run_provenance(outcome.run.run_id)
        chain_valid, audit_count, chain_err = platform.repository.verify_audit_chain()
        assert chain_valid, f"Audit chain invalid: {chain_err}"

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        summary = {
            "demo_status": "PASSED",
            "elapsed_ms": elapsed_ms,
            "policy_version": platform.config.policy.policy_version,
            "default_disabled_block_code": disabled_block_code,
            "run_id": outcome.run.run_id,
            "approval_id": approved.approval_id,
            "exact_action_hash": approved.exact_action_hash,
            "order_id": order.order_id,
            "order_status": order.status.value,
            "filled_quantity": order.filled_quantity,
            "avg_fill_price": str(order.avg_fill_price),
            "broker_order_count": platform.broker.total_broker_orders(),
            "risk_stages_executed": [
                ra["stage"] for ra in (provenance or {}).get("risk_assessments", [])
            ],
            "evidence_count": len((provenance or {}).get("evidence", [])),
            "audit_chain_valid": chain_valid,
            "audit_entry_count": audit_count,
            "final_account": platform.get_account_snapshot().model_dump(mode="json"),
        }
        EVIDENCE_OUT.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary
    finally:
        platform.close()


if __name__ == "__main__":
    result = run_demo()
    print(json.dumps(result, indent=2))
