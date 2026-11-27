"""Failure-scenario validation drill executing all 7 plan.md scenarios + partial fill + restart recovery."""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_platform.agents.research_agent import MomentumNewsResearchAgent
from trading_platform.domain.errors import (
    ApprovalError,
    ExecutionBlockedError,
    RiskCheckError,
    ToolAccessError,
)
from trading_platform.domain.types import ApprovalStatus, OrderStatus, RunStatus
from trading_platform.service import TradingPlatform

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_OUT = ROOT / "reports" / "evidence" / "scenario_drill_evidence.json"
BASE_TIME = datetime(2026, 11, 27, 14, 30, 0, tzinfo=UTC)


class DrillClock:
    def __init__(self, current: datetime = BASE_TIME) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current = self.current + timedelta(seconds=seconds)


def run_all_scenarios() -> dict:
    started = time.perf_counter()
    results: list[dict] = []

    # 1. Injected instructions in news
    clock = DrillClock()
    p = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=clock)
    p.market_data.replace_news_from_fixture(ROOT / "data" / "fixtures" / "fault_injected_news.json")
    out = p.run_cycle(symbol="AAPL")
    tainted = [e for e in p.repository.list_evidence_for_run(out.run.run_id) if e.tainted_injection_detected]
    assert tainted and p.broker.total_broker_orders() == 0
    results.append(
        {
            "scenario": "Injected instructions in news",
            "status": "PASSED",
            "tainted_evidence_count": len(tainted),
            "matched_rules": tainted[0].injection_signals,
            "broker_orders": p.broker.total_broker_orders(),
        }
    )
    p.close()

    # 2. Malicious tool arguments
    clock = DrillClock()
    p = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=clock)
    scope = p.research_agents[0].scope
    codes = []
    for tool_name, args in [
        ("get_quote", {"symbol": "AAPL; DROP TABLE orders--"}),
        ("submit_order", {"symbol": "AAPL", "quantity": 5000}),
    ]:
        try:
            p.tool_gateway.invoke(run_id="DRILL-MAL", scope=scope, tool_name=tool_name, arguments=args)
        except ToolAccessError as exc:
            codes.append(exc.code)
    assert codes == ["MALICIOUS_TOOL_ARGUMENTS", "AGENT_EXECUTION_FORBIDDEN"]
    results.append(
        {
            "scenario": "Malicious tool arguments",
            "status": "PASSED",
            "rejection_codes": codes,
        }
    )
    p.close()

    # 3. Approval replay & parameter tampering
    clock = DrillClock()
    p = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=clock)
    p.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    out = p.run_cycle(symbol="AAPL")
    assert out.approval_request is not None
    req = out.approval_request
    p.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Drill approval",
    )
    tamper_code = None
    try:
        p.dispatch_order(
            approval_id=req.approval_id,
            idempotency_key="DRILL-TAMPER",
            order_intent_override=req.order_intent.model_copy(
                update={"quantity": req.order_intent.quantity + 5}
            ),
        )
    except ApprovalError as exc:
        tamper_code = exc.code
    order = p.dispatch_order(approval_id=req.approval_id, idempotency_key="DRILL-VALID")
    replay_code = None
    try:
        p.dispatch_order(approval_id=req.approval_id, idempotency_key="DRILL-REPLAY-NEW-KEY")
    except ApprovalError as exc:
        replay_code = exc.code
    assert tamper_code == "APPROVAL_PARAMETER_MISMATCH"
    assert replay_code == "APPROVAL_ALREADY_CONSUMED"
    assert p.broker.total_broker_orders() == 1
    results.append(
        {
            "scenario": "Approval replay",
            "status": "PASSED",
            "tamper_rejection_code": tamper_code,
            "replay_rejection_code": replay_code,
            "consumed_by_order_id": order.order_id,
            "broker_orders": p.broker.total_broker_orders(),
        }
    )
    p.close()

    # 4. Conflicting agents
    clock = DrillClock()
    p = TradingPlatform.from_project_root(
        ROOT,
        db_path=":memory:",
        clock=clock,
        research_agents=[
            MomentumNewsResearchAgent(agent_id="research-bull-desk", focus_source="SYNTHETIC_BULL_DESK"),
            MomentumNewsResearchAgent(agent_id="research-bear-desk", focus_source="SYNTHETIC_BEAR_DESK"),
        ],
    )
    p.market_data.replace_news_from_fixture(ROOT / "data" / "fixtures" / "fault_conflicting_signals.json")
    out = p.run_cycle(symbol="NVDA")
    assert out.run.status == RunStatus.BLOCKED_CONFLICT and len(out.conflicts) == 1
    results.append(
        {
            "scenario": "Conflicting agents",
            "status": "PASSED",
            "run_status": out.run.status.value,
            "conflict_id": out.conflicts[0].conflict_id,
            "stances": {k: v.value for k, v in out.conflicts[0].stances.items()},
        }
    )
    p.close()

    # 5. Stale quote (pre-approval and pre-dispatch)
    clock = DrillClock()
    p = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=clock)
    p.market_data.apply_quote_overrides_from_fixture(ROOT / "data" / "fixtures" / "fault_stale_quotes.json")
    out_stale = p.run_cycle(symbol="AAPL")
    assert out_stale.run.status == RunStatus.BLOCKED_RISK
    p.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    out_msft = p.run_cycle(symbol="MSFT", approval_ttl_seconds=600)
    assert out_msft.approval_request is not None
    req_m = out_msft.approval_request
    p.decide_approval(
        approval_id=req_m.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req_m.exact_action_hash,
        reason="Fresh at approval time",
    )
    clock.advance(120)
    pre_disp_code = None
    try:
        p.dispatch_order(approval_id=req_m.approval_id, idempotency_key="DRILL-STALE-DISP")
    except RiskCheckError as exc:
        pre_disp_code = exc.code
    assert pre_disp_code == "STALE_MARKET_DATA"
    results.append(
        {
            "scenario": "Stale quote",
            "status": "PASSED",
            "pre_approval_run_status": out_stale.run.status.value,
            "pre_dispatch_rejection_code": pre_disp_code,
            "broker_orders": p.broker.total_broker_orders(),
        }
    )
    p.close()

    # 6. Broker timeout & reconciliation
    clock = DrillClock()
    p = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=clock)
    p.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    out = p.run_cycle(symbol="AAPL")
    assert out.approval_request is not None
    req = out.approval_request
    p.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_1",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Timeout drill",
    )
    p.broker.fail_next_submit_with_timeout = True
    p.broker.accept_order_before_timeout = True
    timeout_code = None
    try:
        p.dispatch_order(approval_id=req.approval_id, idempotency_key="DRILL-TIMEOUT")
    except ExecutionBlockedError as exc:
        timeout_code = exc.code
    reconciled = p.dispatch_order(approval_id=req.approval_id, idempotency_key="DRILL-TIMEOUT")
    assert timeout_code == "BROKER_TIMEOUT_UNCERTAIN"
    assert reconciled.status == OrderStatus.FILLED
    assert p.broker.total_broker_orders() == 1
    results.append(
        {
            "scenario": "Broker timeout",
            "status": "PASSED",
            "timeout_code": timeout_code,
            "reconciled_status": reconciled.status.value,
            "broker_submit_attempts": p.broker.submit_attempt_count,
            "broker_orders": p.broker.total_broker_orders(),
        }
    )
    p.close()

    # 7. Duplicate fill & partial fill
    clock = DrillClock()
    p = TradingPlatform.from_project_root(ROOT, db_path=":memory:", clock=clock)
    p.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    p.broker.partial_fill_ratio = 0.5
    out = p.run_cycle(symbol="AAPL", override_quantity=20)
    assert out.approval_request is not None
    req = out.approval_request
    p.decide_approval(
        approval_id=req.approval_id,
        actor_id="ops_approver_2",
        approve=True,
        expected_action_hash=req.exact_action_hash,
        reason="Partial + duplicate fill drill",
    )
    partial = p.dispatch_order(approval_id=req.approval_id, idempotency_key="DRILL-PARTIAL")
    leg1 = p.repository.list_fills_for_order(partial.order_id)[0]
    _, dup_was_new = p.ingest_fill(leg1)
    assert dup_was_new is False
    leg2 = p.broker.complete_partial_fill(
        client_order_id=partial.client_order_id,
        now_utc=clock.current + timedelta(seconds=5),
    )
    completed, leg2_new = p.ingest_fill(leg2)
    assert leg2_new is True and completed.status == OrderStatus.FILLED and completed.filled_quantity == 20
    results.append(
        {
            "scenario": "Duplicate fill & Partial fill",
            "status": "PASSED",
            "duplicate_leg1_accepted": dup_was_new,
            "final_status": completed.status.value,
            "final_filled_qty": completed.filled_quantity,
        }
    )
    p.close()

    # 8. Cold restart recovery
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "drill_restart.sqlite3"
        clock = DrillClock()
        p1 = TradingPlatform.from_project_root(ROOT, db_path=db_path, clock=clock)
        p1.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
        out = p1.run_cycle(symbol="MSFT")
        assert out.approval_request is not None
        pending_id = out.approval_request.approval_id
        p1.close()

        p2 = TradingPlatform.from_project_root(ROOT, db_path=db_path, clock=clock)
        recovered = p2.repository.get_approval(pending_id)
        chain_valid, count, err = p2.repository.verify_audit_chain()
        assert recovered is not None and recovered.status == ApprovalStatus.PENDING
        assert chain_valid and err is None
        results.append(
            {
                "scenario": "Restart recovery",
                "status": "PASSED",
                "recovered_approval_id": pending_id,
                "audit_chain_valid": chain_valid,
                "audit_entries": count,
            }
        )
        p2.close()

    summary = {
        "drill_status": "ALL_PASSED",
        "scenarios_executed": len(results),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "results": results,
    }
    EVIDENCE_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_all_scenarios(), indent=2))
