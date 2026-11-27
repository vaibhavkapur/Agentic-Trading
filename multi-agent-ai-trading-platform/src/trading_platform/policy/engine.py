"""Deterministic PolicyEngine: final authority over proposals, conflicts, and execution mode."""

from __future__ import annotations

from dataclasses import dataclass

from trading_platform.domain.config import PolicyConfig
from trading_platform.domain.contracts import (
    ConflictRecord,
    PortfolioProposal,
    RiskAssessment,
)
from trading_platform.domain.errors import PolicyViolationError
from trading_platform.domain.types import (
    ConflictResolutionMode,
    ExecutionMode,
    PolicyDecisionStatus,
    RiskStatus,
)


@dataclass(frozen=True)
class PolicyEvaluationResult:
    status: PolicyDecisionStatus
    policy_version: str
    reason_code: str
    message: str
    exact_action_hash: str | None = None


class PolicyEngine:
    """Deterministic policy gate; no agent may modify or bypass its rules."""

    def __init__(self, config: PolicyConfig) -> None:
        self._config = config

    @property
    def policy_version(self) -> str:
        return self._config.policy_version

    @property
    def config(self) -> PolicyConfig:
        return self._config

    def validate_execution_mode_change(self, *, requested_mode: str, actor_id: str) -> ExecutionMode:
        actor_role = self._config.authorized_approvers.get(actor_id)
        if actor_role is None or actor_role in self._config.forbidden_approver_roles:
            raise PolicyViolationError(
                "UNAUTHORIZED_MODE_CHANGE",
                f"Actor '{actor_id}' is not authorized to change execution mode.",
                details={"actor_id": actor_id},
            )
        normalized = requested_mode.strip().upper()
        if normalized == "LIVE":
            raise PolicyViolationError(
                "LIVE_TRADING_FORBIDDEN",
                "LIVE execution mode is permanently disabled in this prototype.",
                details={"requested_mode": requested_mode},
            )
        try:
            return ExecutionMode(normalized)
        except ValueError as exc:
            raise PolicyViolationError(
                "INVALID_EXECUTION_MODE",
                f"Unsupported execution mode '{requested_mode}'. Allowed: DISABLED, PAPER.",
                details={"requested_mode": requested_mode},
            ) from exc

    def reject_agent_override_attempt(self, *, agent_id: str, requested_change: str) -> None:
        raise PolicyViolationError(
            "AGENT_POLICY_OVERRIDE_FORBIDDEN",
            f"Agent '{agent_id}' is forbidden from overriding deterministic policy ({requested_change}).",
            details={"agent_id": agent_id, "requested_change": requested_change},
        )

    def evaluate_conflict(self, conflict: ConflictRecord) -> PolicyEvaluationResult:
        if self._config.conflict_resolution_mode == ConflictResolutionMode.BLOCK_AND_ESCALATE:
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.CONFLICT_ESCALATED,
                policy_version=self._config.policy_version,
                reason_code="AGENT_CONFLICT_BLOCKED",
                message=(
                    f"Conflicting agent stances detected for {conflict.symbol}; "
                    f"policy {self._config.policy_version} requires escalation and blocks order proposal."
                ),
            )
        return PolicyEvaluationResult(
            status=PolicyDecisionStatus.PENDING_APPROVAL,
            policy_version=self._config.policy_version,
            reason_code="CONFLICT_RESOLVED_BY_POLICY",
            message=f"Conflict on {conflict.symbol} resolved via {self._config.conflict_resolution_mode.value}.",
        )

    def evaluate_proposal(
        self,
        *,
        proposal: PortfolioProposal,
        risk_assessment: RiskAssessment,
    ) -> PolicyEvaluationResult:
        intent = proposal.order_intent

        if proposal.policy_version != self._config.policy_version:
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.REJECTED,
                policy_version=self._config.policy_version,
                reason_code="POLICY_VERSION_MISMATCH",
                message=(
                    f"Proposal policy_version '{proposal.policy_version}' does not match "
                    f"active policy '{self._config.policy_version}'."
                ),
            )

        if intent.symbol not in self._config.allowed_symbols:
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.REJECTED,
                policy_version=self._config.policy_version,
                reason_code="SYMBOL_NOT_ALLOWED",
                message=f"Symbol '{intent.symbol}' is not permitted under policy {self._config.policy_version}.",
            )

        if intent.order_type not in self._config.allowed_order_types:
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.REJECTED,
                policy_version=self._config.policy_version,
                reason_code="ORDER_TYPE_NOT_ALLOWED",
                message=f"Order type '{intent.order_type.value}' is not permitted.",
            )

        if intent.time_in_force not in self._config.allowed_time_in_force:
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.REJECTED,
                policy_version=self._config.policy_version,
                reason_code="TIME_IN_FORCE_NOT_ALLOWED",
                message=f"Time-in-force '{intent.time_in_force.value}' is not permitted.",
            )

        if not proposal.evidence_ids:
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.REJECTED,
                policy_version=self._config.policy_version,
                reason_code="MISSING_PROVENANCE_EVIDENCE",
                message="Proposal must trace to at least one captured evidence item.",
            )

        if risk_assessment.status != RiskStatus.APPROVED:
            failed_codes = [c.code for c in risk_assessment.failed_checks]
            return PolicyEvaluationResult(
                status=PolicyDecisionStatus.REJECTED,
                policy_version=self._config.policy_version,
                reason_code=failed_codes[0] if failed_codes else "RISK_REJECTED",
                message=(
                    f"Independent risk assessment {risk_assessment.assessment_id} rejected proposal: "
                    f"{', '.join(failed_codes)}."
                ),
            )

        return PolicyEvaluationResult(
            status=PolicyDecisionStatus.PENDING_APPROVAL,
            policy_version=self._config.policy_version,
            reason_code="POLICY_PASSED_REQUIRES_APPROVAL",
            message=(
                f"Proposal {proposal.proposal_id} satisfied policy {self._config.policy_version} "
                f"and requires exact-action human approval before OMS dispatch."
            ),
            exact_action_hash=proposal.exact_action_hash(),
        )
