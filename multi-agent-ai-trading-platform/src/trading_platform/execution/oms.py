"""Idempotent OMS enforcing execution mode, exact-action approvals, pre-dispatch risk re-check, and fill deduplication."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from trading_platform.agents.risk_agent import IndependentRiskService
from trading_platform.domain.contracts import (
    FillRecord,
    OrderIntent,
    OrderRecord,
)
from trading_platform.domain.errors import ExecutionBlockedError, RiskCheckError
from trading_platform.domain.types import (
    ExecutionMode,
    OrderStatus,
    RiskStatus,
    RunStatus,
    canonical_hash,
)
from trading_platform.execution.broker import BrokerTimeoutError, PaperBroker
from trading_platform.policy.approvals import ExactActionApprovalService
from trading_platform.storage.event_bus import EventBus
from trading_platform.storage.repository import StateRepository
from trading_platform.tools.market_tools import MarketDataProvider


class IdempotentOMS:
    """Single authorized gateway to the paper broker; agents never have access to this service."""

    def __init__(
        self,
        *,
        repository: StateRepository,
        event_bus: EventBus,
        market_data: MarketDataProvider,
        risk_service: IndependentRiskService,
        approval_service: ExactActionApprovalService,
        broker: PaperBroker,
        policy_version: str,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._market_data = market_data
        self._risk_service = risk_service
        self._approval_service = approval_service
        self._broker = broker
        self._policy_version = policy_version

    def dispatch_approved_order(
        self,
        *,
        approval_id: str,
        idempotency_key: str,
        actor_id: str = "OMS_DISPATCHER",
        order_intent_override: OrderIntent | None = None,
    ) -> OrderRecord:
        now_utc = self._market_data.now()

        # 1. Idempotency check: duplicate messages never create duplicate orders
        existing = self._repository.get_order_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.status == OrderStatus.UNCERTAIN_TIMEOUT:
                return self.reconcile_uncertain_order(order_id=existing.order_id, actor_id=actor_id)
            self._repository.append_audit(
                actor_id=actor_id,
                actor_role="OMS",
                action="OMS_DUPLICATE_DISPATCH_IGNORED",
                outcome="IDEMPOTENT_HIT",
                policy_version=self._policy_version,
                run_id=existing.run_id,
                entity_type="order",
                entity_id=existing.order_id,
                evidence_ids=existing.evidence_ids,
                payload={"idempotency_key": idempotency_key},
                timestamp_utc=now_utc,
            )
            return existing

        # 2. Operational controls: kill switch & execution mode
        if self._repository.get_kill_switch():
            self._repository.append_audit(
                actor_id=actor_id,
                actor_role="OMS",
                action="OMS_DISPATCH",
                outcome="BLOCKED_KILL_SWITCH",
                policy_version=self._policy_version,
                entity_type="approval",
                entity_id=approval_id,
                payload={"idempotency_key": idempotency_key},
                timestamp_utc=now_utc,
            )
            raise ExecutionBlockedError(
                "KILL_SWITCH_ACTIVE",
                "Emergency kill switch is active; all order dispatch is halted.",
            )

        exec_mode = self._repository.get_execution_mode(default=ExecutionMode.DISABLED)
        if exec_mode != ExecutionMode.PAPER:
            self._repository.append_audit(
                actor_id=actor_id,
                actor_role="OMS",
                action="OMS_DISPATCH",
                outcome="BLOCKED_EXECUTION_DISABLED",
                policy_version=self._policy_version,
                entity_type="approval",
                entity_id=approval_id,
                payload={"execution_mode": exec_mode.value},
                timestamp_utc=now_utc,
            )
            raise ExecutionBlockedError(
                "EXECUTION_DISABLED",
                f"Order execution is disabled (execution_mode={exec_mode.value}). Explicitly enable PAPER mode first.",
                details={"execution_mode": exec_mode.value},
            )

        # 3. Validate exact-action approval (exists, APPROVED, unexpired, unconsumed, exact hash match)
        approval_record = self._repository.get_approval(approval_id)
        if approval_record is None:
            # Delegate to approval_service so error code is consistent
            self._approval_service.validate_for_dispatch(
                approval_id=approval_id,
                order_intent=order_intent_override
                or OrderIntent(
                    account_id="UNKNOWN",
                    symbol="AAPL",
                    side="BUY",
                    quantity=1,
                    order_type="MARKET",
                ),
                now_utc=now_utc,
            )
        assert approval_record is not None
        effective_intent = order_intent_override or approval_record.order_intent
        approval = self._approval_service.validate_for_dispatch(
            approval_id=approval_id,
            order_intent=effective_intent,
            now_utc=now_utc,
        )

        # 4. MANDATORY Pre-dispatch risk re-validation against fresh quotes & current account state
        proposal = self._repository.get_proposal(approval.proposal_id)
        if proposal is None:
            raise ExecutionBlockedError(
                "PROPOSAL_NOT_FOUND",
                f"Proposal '{approval.proposal_id}' missing for approval '{approval_id}'.",
            )
        account = self._repository.load_account_snapshot() or self._market_data.initial_account
        quotes = self._market_data.get_all_quotes()
        pre_dispatch_risk = self._risk_service.evaluate(
            proposal=proposal,
            account=account,
            quotes=quotes,
            now_utc=now_utc,
            stage="PRE_DISPATCH",
        )
        self._repository.save_risk_assessment(pre_dispatch_risk)
        if pre_dispatch_risk.status != RiskStatus.APPROVED:
            failed = [c.code for c in pre_dispatch_risk.failed_checks]
            self._repository.append_audit(
                actor_id="RISK_SERVICE",
                actor_role="RISK_SERVICE",
                action="PRE_DISPATCH_RISK_CHECK",
                outcome="REJECTED",
                policy_version=self._policy_version,
                run_id=approval.run_id,
                entity_type="risk_assessment",
                entity_id=pre_dispatch_risk.assessment_id,
                evidence_ids=approval.evidence_ids,
                payload={"approval_id": approval_id, "failed_checks": failed},
                timestamp_utc=now_utc,
            )
            self._event_bus.publish(
                event_type="risk.pre_dispatch_rejected",
                policy_version=self._policy_version,
                run_id=approval.run_id,
                payload={
                    "approval_id": approval_id,
                    "assessment_id": pre_dispatch_risk.assessment_id,
                    "failed_checks": failed,
                },
            )
            raise RiskCheckError(
                failed[0] if failed else "PRE_DISPATCH_RISK_FAILED",
                f"Pre-dispatch risk check failed before broker submission: {', '.join(failed)}.",
                details={"assessment_id": pre_dispatch_risk.assessment_id, "failed_checks": failed},
            )

        self._repository.append_audit(
            actor_id="RISK_SERVICE",
            actor_role="RISK_SERVICE",
            action="PRE_DISPATCH_RISK_CHECK",
            outcome="APPROVED",
            policy_version=self._policy_version,
            run_id=approval.run_id,
            entity_type="risk_assessment",
            entity_id=pre_dispatch_risk.assessment_id,
            evidence_ids=approval.evidence_ids,
            payload={"approval_id": approval_id},
            timestamp_utc=now_utc,
        )

        # 5. Create persistent order & consume single-use approval BEFORE calling external broker
        order_id = f"ORD-{uuid4().hex[:10].upper()}"
        client_order_id = f"CLORD-{canonical_hash(idempotency_key)[:12].upper()}"
        order = OrderRecord(
            order_id=order_id,
            idempotency_key=idempotency_key,
            client_order_id=client_order_id,
            run_id=approval.run_id,
            proposal_id=approval.proposal_id,
            approval_id=approval.approval_id,
            exact_action_hash=approval.exact_action_hash,
            pre_dispatch_risk_id=pre_dispatch_risk.assessment_id,
            policy_version=approval.policy_version,
            evidence_ids=list(approval.evidence_ids),
            order_intent=effective_intent,
            status=OrderStatus.SUBMITTED,
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
        )
        self._repository.save_order(order)
        self._approval_service.mark_consumed(
            approval=approval,
            order_id=order_id,
            now_utc=now_utc,
        )

        # Update linked run status
        run = self._repository.get_run(approval.run_id)
        if run is not None:
            self._repository.save_run(
                run.model_copy(update={"status": RunStatus.DISPATCHED, "order_id": order_id})
            )

        # 6. Dispatch to paper broker with explicit timeout handling
        quote = quotes[effective_intent.symbol]
        try:
            broker_resp = self._broker.submit_order(
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                order_intent=effective_intent,
                quote=quote,
                now_utc=now_utc,
            )
        except BrokerTimeoutError as exc:
            uncertain = order.model_copy(
                update={
                    "status": OrderStatus.UNCERTAIN_TIMEOUT,
                    "updated_at_utc": now_utc,
                    "last_error": str(exc),
                }
            )
            self._repository.save_order(uncertain)
            self._repository.append_audit(
                actor_id="OMS",
                actor_role="OMS",
                action="OMS_BROKER_TIMEOUT",
                outcome="UNCERTAIN_TIMEOUT",
                policy_version=self._policy_version,
                run_id=order.run_id,
                entity_type="order",
                entity_id=order.order_id,
                evidence_ids=order.evidence_ids,
                payload={"client_order_id": order.client_order_id, "error": str(exc)},
                timestamp_utc=now_utc,
            )
            self._event_bus.publish(
                event_type="oms.order_timeout",
                policy_version=self._policy_version,
                run_id=order.run_id,
                payload={"order_id": order.order_id, "client_order_id": order.client_order_id},
            )
            raise ExecutionBlockedError(
                "BROKER_TIMEOUT_UNCERTAIN",
                f"Paper broker timed out for order {order.order_id}; status set to UNCERTAIN_TIMEOUT. Reconcile using the same idempotency_key.",
                details={"order_id": order.order_id, "client_order_id": order.client_order_id},
            ) from exc

        updated = order.model_copy(
            update={
                "broker_order_id": broker_resp.broker_order_id,
                "status": broker_resp.status,
                "updated_at_utc": now_utc,
            }
        )
        self._repository.save_order(updated)
        self._repository.append_audit(
            actor_id=actor_id,
            actor_role="OMS",
            action="OMS_ORDER_DISPATCHED",
            outcome=broker_resp.status.value,
            policy_version=self._policy_version,
            run_id=order.run_id,
            entity_type="order",
            entity_id=order.order_id,
            evidence_ids=order.evidence_ids,
            payload={
                "broker_order_id": broker_resp.broker_order_id,
                "client_order_id": order.client_order_id,
                "approval_id": approval.approval_id,
                "exact_action_hash": approval.exact_action_hash,
                "pre_dispatch_risk_id": pre_dispatch_risk.assessment_id,
            },
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="oms.order_dispatched",
            policy_version=self._policy_version,
            run_id=order.run_id,
            payload={
                "order_id": order.order_id,
                "broker_order_id": broker_resp.broker_order_id,
                "status": broker_resp.status.value,
            },
        )

        for fill in broker_resp.fills:
            updated, _ = self.ingest_fill(fill)

        return updated

    def reconcile_uncertain_order(self, *, order_id: str, actor_id: str = "OMS_RECONCILER") -> OrderRecord:
        """Query broker by client_order_id after timeout to recover true state without duplicate submission."""
        now_utc = self._market_data.now()
        order = self._repository.get_order(order_id)
        if order is None:
            raise ExecutionBlockedError("ORDER_NOT_FOUND", f"Order '{order_id}' not found.")

        broker_resp = self._broker.query_by_client_order_id(order.client_order_id)
        if broker_resp is None:
            # Broker never received the order; mark CANCELLED/REJECTED safely rather than blind retry
            resolved = order.model_copy(
                update={
                    "status": OrderStatus.CANCELLED,
                    "updated_at_utc": now_utc,
                    "last_error": "Reconciled: broker never accepted timed-out submission.",
                }
            )
            self._repository.save_order(resolved)
            self._repository.append_audit(
                actor_id=actor_id,
                actor_role="OMS",
                action="OMS_TIMEOUT_RECONCILED",
                outcome="NOT_ACCEPTED_BY_BROKER",
                policy_version=self._policy_version,
                run_id=order.run_id,
                entity_type="order",
                entity_id=order.order_id,
                payload={"client_order_id": order.client_order_id},
                timestamp_utc=now_utc,
            )
            return resolved

        updated = order.model_copy(
            update={
                "broker_order_id": broker_resp.broker_order_id,
                "status": broker_resp.status,
                "updated_at_utc": now_utc,
                "last_error": None,
            }
        )
        self._repository.save_order(updated)
        for fill in broker_resp.fills:
            updated, _ = self.ingest_fill(fill)

        self._repository.append_audit(
            actor_id=actor_id,
            actor_role="OMS",
            action="OMS_TIMEOUT_RECONCILED",
            outcome=updated.status.value,
            policy_version=self._policy_version,
            run_id=order.run_id,
            entity_type="order",
            entity_id=order.order_id,
            evidence_ids=order.evidence_ids,
            payload={
                "broker_order_id": broker_resp.broker_order_id,
                "filled_quantity": updated.filled_quantity,
            },
            timestamp_utc=now_utc,
        )
        return updated

    def ingest_fill(self, fill: FillRecord) -> tuple[OrderRecord, bool]:
        """Idempotently ingest a broker fill by unique broker_fill_id. Returns (order, was_new)."""
        now_utc = self._market_data.now()
        order = self._repository.get_order(fill.order_id) or self._repository.get_order_by_client_order_id(
            fill.client_order_id
        )
        if order is None:
            raise ExecutionBlockedError(
                "ORDER_NOT_FOUND_FOR_FILL",
                f"Cannot apply fill '{fill.broker_fill_id}': order '{fill.order_id}' not found.",
            )

        is_new = self._repository.save_fill_if_new(fill)
        if not is_new:
            self._repository.append_audit(
                actor_id="OMS",
                actor_role="OMS",
                action="OMS_DUPLICATE_FILL_IGNORED",
                outcome="DEDUPLICATED",
                policy_version=self._policy_version,
                run_id=order.run_id,
                entity_type="fill",
                entity_id=fill.broker_fill_id,
                payload={"order_id": order.order_id, "quantity": fill.quantity},
                timestamp_utc=now_utc,
            )
            self._event_bus.publish(
                event_type="oms.duplicate_fill_ignored",
                policy_version=self._policy_version,
                run_id=order.run_id,
                payload={"order_id": order.order_id, "broker_fill_id": fill.broker_fill_id},
            )
            return order, False

        # Recompute aggregate filled quantity & VWAP from all persisted deduplicated fills
        all_fills = self._repository.list_fills_for_order(order.order_id)
        total_qty = sum(f.quantity for f in all_fills)
        total_notional = sum(f.price * Decimal(f.quantity) for f in all_fills)
        avg_price = (total_notional / Decimal(total_qty)).quantize(Decimal("0.0001"))
        new_status = (
            OrderStatus.FILLED
            if total_qty >= order.order_intent.quantity
            else OrderStatus.PARTIALLY_FILLED
        )

        updated_order = order.model_copy(
            update={
                "filled_quantity": total_qty,
                "avg_fill_price": avg_price,
                "status": new_status,
                "updated_at_utc": now_utc,
            }
        )
        self._repository.save_order(updated_order)
        self._repository.apply_fill_to_account(fill)
        self._repository.append_audit(
            actor_id="OMS",
            actor_role="OMS",
            action="OMS_FILL_APPLIED",
            outcome=new_status.value,
            policy_version=self._policy_version,
            run_id=order.run_id,
            entity_type="fill",
            entity_id=fill.broker_fill_id,
            evidence_ids=order.evidence_ids,
            payload={
                "order_id": order.order_id,
                "fill_qty": fill.quantity,
                "fill_price": str(fill.price),
                "total_filled_qty": total_qty,
            },
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="oms.fill_applied",
            policy_version=self._policy_version,
            run_id=order.run_id,
            payload={
                "order_id": order.order_id,
                "broker_fill_id": fill.broker_fill_id,
                "fill_qty": fill.quantity,
                "status": new_status.value,
            },
        )
        return updated_order, True
