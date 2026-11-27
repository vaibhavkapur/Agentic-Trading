"""Exact-action human approval service with parameter hash binding, TTL expiry, and anti-replay."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from trading_platform.domain.config import PolicyConfig
from trading_platform.domain.contracts import (
    ApprovalDecision,
    ApprovalRequest,
    OrderIntent,
    PortfolioProposal,
)
from trading_platform.domain.errors import ApprovalError
from trading_platform.domain.types import ApprovalStatus, compute_exact_action_hash
from trading_platform.storage.event_bus import EventBus
from trading_platform.storage.repository import StateRepository


class ExactActionApprovalService:
    """Manages exact-action approvals bound by SHA-256 hash, TTL, RBAC, and single-use consumption."""

    def __init__(
        self,
        *,
        policy: PolicyConfig,
        repository: StateRepository,
        event_bus: EventBus,
    ) -> None:
        self._policy = policy
        self._repository = repository
        self._event_bus = event_bus

    def create_request(
        self,
        *,
        proposal: PortfolioProposal,
        risk_assessment_id: str,
        now_utc: datetime,
        ttl_seconds: int | None = None,
    ) -> ApprovalRequest:
        ttl = ttl_seconds if ttl_seconds is not None else self._policy.approval_ttl_seconds
        exact_hash = proposal.exact_action_hash()
        request = ApprovalRequest(
            approval_id=f"APR-{uuid4().hex[:10].upper()}",
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            policy_version=proposal.policy_version,
            exact_action_hash=exact_hash,
            order_intent=proposal.order_intent,
            evidence_ids=list(proposal.evidence_ids),
            risk_assessment_id=risk_assessment_id,
            status=ApprovalStatus.PENDING,
            requested_by=proposal.agent_id,
            created_at_utc=now_utc,
            expires_at_utc=now_utc + timedelta(seconds=ttl),
        )
        self._repository.save_approval(request)
        self._repository.append_audit(
            actor_id="POLICY_ENGINE",
            actor_role="POLICY_ENGINE",
            action="APPROVAL_REQUEST_CREATED",
            outcome="PENDING",
            policy_version=proposal.policy_version,
            run_id=proposal.run_id,
            entity_type="approval",
            entity_id=request.approval_id,
            evidence_ids=request.evidence_ids,
            payload={
                "proposal_id": proposal.proposal_id,
                "exact_action_hash": exact_hash,
                "expires_at_utc": request.expires_at_utc.isoformat(),
            },
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="approval.requested",
            policy_version=proposal.policy_version,
            run_id=proposal.run_id,
            payload={
                "approval_id": request.approval_id,
                "proposal_id": proposal.proposal_id,
                "exact_action_hash": exact_hash,
                "expires_at_utc": request.expires_at_utc.isoformat(),
            },
        )
        return request

    def decide(
        self,
        *,
        approval_id: str,
        decision: ApprovalDecision,
        now_utc: datetime,
    ) -> ApprovalRequest:
        approval = self._repository.get_approval(approval_id)
        if approval is None:
            raise ApprovalError(
                "APPROVAL_NOT_FOUND",
                f"Approval request '{approval_id}' does not exist.",
                details={"approval_id": approval_id},
            )

        actor_role = self._policy.authorized_approvers.get(decision.actor_id)
        if actor_role is None or actor_role in self._policy.forbidden_approver_roles:
            self._repository.append_audit(
                actor_id=decision.actor_id,
                actor_role=actor_role or "UNAUTHORIZED",
                action="APPROVAL_DECISION",
                outcome="DENIED",
                policy_version=approval.policy_version,
                run_id=approval.run_id,
                entity_type="approval",
                entity_id=approval_id,
                payload={"error_code": "APPROVER_NOT_AUTHORIZED"},
                timestamp_utc=now_utc,
            )
            raise ApprovalError(
                "APPROVER_NOT_AUTHORIZED",
                f"Actor '{decision.actor_id}' is not authorized to approve trading orders.",
                details={"actor_id": decision.actor_id, "approval_id": approval_id},
            )

        if decision.actor_id == approval.requested_by:
            raise ApprovalError(
                "MAKER_CHECKER_VIOLATION",
                "Approver cannot be the same actor who created the proposal.",
                details={"actor_id": decision.actor_id},
            )

        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalError(
                "APPROVAL_NOT_PENDING",
                f"Approval '{approval_id}' is in terminal/non-pending state '{approval.status.value}'.",
                details={"approval_id": approval_id, "status": approval.status.value},
            )

        if now_utc > approval.expires_at_utc:
            expired = approval.model_copy(update={"status": ApprovalStatus.EXPIRED})
            self._repository.save_approval(expired)
            self._repository.append_audit(
                actor_id=decision.actor_id,
                actor_role=actor_role,
                action="APPROVAL_DECISION",
                outcome="EXPIRED",
                policy_version=approval.policy_version,
                run_id=approval.run_id,
                entity_type="approval",
                entity_id=approval_id,
                payload={"expires_at_utc": approval.expires_at_utc.isoformat()},
                timestamp_utc=now_utc,
            )
            raise ApprovalError(
                "APPROVAL_EXPIRED",
                f"Approval '{approval_id}' expired at {approval.expires_at_utc.isoformat()}.",
                details={"approval_id": approval_id},
            )

        if decision.expected_action_hash != approval.exact_action_hash:
            self._repository.append_audit(
                actor_id=decision.actor_id,
                actor_role=actor_role,
                action="APPROVAL_DECISION",
                outcome="REJECTED_HASH_MISMATCH",
                policy_version=approval.policy_version,
                run_id=approval.run_id,
                entity_type="approval",
                entity_id=approval_id,
                payload={
                    "expected": decision.expected_action_hash,
                    "actual": approval.exact_action_hash,
                },
                timestamp_utc=now_utc,
            )
            raise ApprovalError(
                "APPROVAL_HASH_MISMATCH",
                "Provided expected_action_hash does not match exact order parameters.",
                details={"approval_id": approval_id},
            )

        new_status = ApprovalStatus.APPROVED if decision.approve else ApprovalStatus.REJECTED
        updated = approval.model_copy(
            update={
                "status": new_status,
                "decided_by": decision.actor_id,
                "decided_by_role": actor_role,
                "decided_at_utc": now_utc,
                "decision_reason": decision.reason,
            }
        )
        self._repository.save_approval(updated)
        self._repository.append_audit(
            actor_id=decision.actor_id,
            actor_role=actor_role,
            action="APPROVAL_DECISION",
            outcome=new_status.value,
            policy_version=updated.policy_version,
            run_id=updated.run_id,
            entity_type="approval",
            entity_id=approval_id,
            evidence_ids=updated.evidence_ids,
            payload={"reason": decision.reason, "exact_action_hash": updated.exact_action_hash},
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="approval.decided",
            policy_version=updated.policy_version,
            run_id=updated.run_id,
            payload={
                "approval_id": approval_id,
                "status": new_status.value,
                "decided_by": decision.actor_id,
            },
        )
        return updated

    def validate_for_dispatch(
        self,
        *,
        approval_id: str,
        order_intent: OrderIntent,
        now_utc: datetime,
    ) -> ApprovalRequest:
        """Verify approval is APPROVED, unexpired, unconsumed, and exact-hash matched."""
        approval = self._repository.get_approval(approval_id)
        if approval is None:
            raise ApprovalError(
                "APPROVAL_NOT_FOUND",
                f"Approval '{approval_id}' not found.",
                details={"approval_id": approval_id},
            )

        if approval.status == ApprovalStatus.CONSUMED:
            self._repository.append_audit(
                actor_id="OMS",
                actor_role="OMS",
                action="APPROVAL_REPLAY_BLOCKED",
                outcome="DENIED",
                policy_version=approval.policy_version,
                run_id=approval.run_id,
                entity_type="approval",
                entity_id=approval_id,
                payload={"consumed_by_order_id": approval.consumed_by_order_id},
                timestamp_utc=now_utc,
            )
            raise ApprovalError(
                "APPROVAL_ALREADY_CONSUMED",
                f"Approval '{approval_id}' was already consumed by order '{approval.consumed_by_order_id}'. Replay blocked.",
                details={"approval_id": approval_id, "consumed_by_order_id": approval.consumed_by_order_id},
            )

        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalError(
                "APPROVAL_NOT_APPROVED",
                f"Approval '{approval_id}' is '{approval.status.value}', not APPROVED.",
                details={"approval_id": approval_id, "status": approval.status.value},
            )

        if now_utc > approval.expires_at_utc:
            expired = approval.model_copy(update={"status": ApprovalStatus.EXPIRED})
            self._repository.save_approval(expired)
            self._repository.append_audit(
                actor_id="OMS",
                actor_role="OMS",
                action="APPROVAL_EXPIRED_AT_DISPATCH",
                outcome="DENIED",
                policy_version=approval.policy_version,
                run_id=approval.run_id,
                entity_type="approval",
                entity_id=approval_id,
                payload={"expires_at_utc": approval.expires_at_utc.isoformat()},
                timestamp_utc=now_utc,
            )
            raise ApprovalError(
                "APPROVAL_EXPIRED",
                f"Approval '{approval_id}' expired at {approval.expires_at_utc.isoformat()}.",
                details={"approval_id": approval_id},
            )

        recomputed_hash = compute_exact_action_hash(
            account_id=order_intent.account_id,
            symbol=order_intent.symbol,
            side=order_intent.side,
            quantity=order_intent.quantity,
            order_type=order_intent.order_type,
            limit_price=order_intent.limit_price,
            time_in_force=order_intent.time_in_force,
            currency=order_intent.currency,
            policy_version=approval.policy_version,
            proposal_id=approval.proposal_id,
        )
        if recomputed_hash != approval.exact_action_hash:
            self._repository.append_audit(
                actor_id="OMS",
                actor_role="OMS",
                action="APPROVAL_PARAMETER_TAMPERING_BLOCKED",
                outcome="DENIED",
                policy_version=approval.policy_version,
                run_id=approval.run_id,
                entity_type="approval",
                entity_id=approval_id,
                payload={
                    "approved_hash": approval.exact_action_hash,
                    "submitted_hash": recomputed_hash,
                },
                timestamp_utc=now_utc,
            )
            raise ApprovalError(
                "APPROVAL_PARAMETER_MISMATCH",
                "Order parameters do not match the approved exact_action_hash.",
                details={"approval_id": approval_id},
            )

        return approval

    def mark_consumed(
        self,
        *,
        approval: ApprovalRequest,
        order_id: str,
        now_utc: datetime,
    ) -> ApprovalRequest:
        consumed = approval.model_copy(
            update={
                "status": ApprovalStatus.CONSUMED,
                "consumed_at_utc": now_utc,
                "consumed_by_order_id": order_id,
            }
        )
        self._repository.save_approval(consumed)
        return consumed
