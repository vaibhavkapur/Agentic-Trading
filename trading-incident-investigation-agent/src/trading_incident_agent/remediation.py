"""Approval-gated simulated remediation catalog, policy verifier, and recovery checker."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from trading_incident_agent.config import compute_sha256
from trading_incident_agent.errors import (
    AmbiguousRootCauseError,
    ApprovalMismatchError,
    ApprovalRequiredError,
    ForbiddenActionError,
)
from trading_incident_agent.models import (
    ActionRiskLevel,
    AgentConfig,
    HealthCheckResult,
    HypothesisEvaluation,
    IncidentReport,
    OperatorApproval,
    RecoveryVerification,
    RemediationProposal,
    RemediationReceipt,
    RemediationStatus,
    VerdictStatus,
)


@dataclass(frozen=True)
class SimulatedActionSpec:
    action_id: str
    target_service: str
    risk_level: ActionRiskLevel
    description: str
    default_parameters: dict[str, Any]
    expected_checks: list[str]
    baseline_metrics: dict[str, tuple[float, float, str]]  # metric -> (before, threshold, unit)


# Strictly bounded, offline-simulated allowlist. No live orders or production mutations exist.
ALLOWLISTED_SIM_ACTIONS: dict[str, SimulatedActionSpec] = {
    "drain_and_recycle_gateway_pool": SimulatedActionSpec(
        action_id="drain_and_recycle_gateway_pool",
        target_service="fix-gateway",
        risk_level=ActionRiskLevel.MEDIUM,
        description="Gracefully drain idle sockets and recycle simulated FIX gateway connection pool.",
        default_parameters={"pool_name": "simx_fix_pool", "target_pool_size": 96, "drain_timeout_s": 10},
        expected_checks=[
            "gateway_pool_utilization_pct < 75.0",
            "p99_ack_latency_ms < 150.0",
            "order_timeout_rate_pct < 0.5",
        ],
        baseline_metrics={
            "gateway_pool_utilization_pct": (100.0, 75.0, "percent"),
            "p99_ack_latency_ms": (2450.0, 150.0, "ms"),
            "order_timeout_rate_pct": (14.2, 0.5, "percent"),
        },
    ),
    "rebalance_oms_throttle_bucket_sim": SimulatedActionSpec(
        action_id="rebalance_oms_throttle_bucket_sim",
        target_service="oms-core",
        risk_level=ActionRiskLevel.MEDIUM,
        description="Rebalance simulated OMS token-bucket burst refill rate within pre-approved risk cap.",
        default_parameters={"bucket": "simx_burst_bucket", "refill_rps": 750, "preserve_risk_limits": True},
        expected_checks=[
            "oms_throttle_reject_rate_pct < 1.0",
            "p99_ack_latency_ms < 100.0",
        ],
        baseline_metrics={
            "oms_throttle_reject_rate_pct": (18.4, 1.0, "percent"),
            "p99_ack_latency_ms": (145.0, 100.0, "ms"),
        },
    ),
    "resync_fix_session_sequence_sim": SimulatedActionSpec(
        action_id="resync_fix_session_sequence_sim",
        target_service="fix-gateway",
        risk_level=ActionRiskLevel.MEDIUM,
        description="Perform controlled simulated FIX MsgSeqNum reconciliation without cancelling open orders.",
        default_parameters={"session": "SIMX-DROP-01", "cancel_open_orders": False},
        expected_checks=[
            "fix_seq_gap_count < 1.0",
            "p99_ack_latency_ms < 120.0",
        ],
        baseline_metrics={
            "fix_seq_gap_count": (19.0, 1.0, "messages"),
            "p99_ack_latency_ms": (880.0, 120.0, "ms"),
        },
    ),
    "shift_traffic_to_standby_oms_sim": SimulatedActionSpec(
        action_id="shift_traffic_to_standby_oms_sim",
        target_service="oms-core",
        risk_level=ActionRiskLevel.HIGH,
        description="Shift simulated order routing to standby oms-core replica while collecting heap profile.",
        default_parameters={"standby_replica": "oms-core-sim-b"},
        expected_checks=[
            "gc_pause_ms < 50.0",
            "p99_ack_latency_ms < 120.0",
        ],
        baseline_metrics={
            "gc_pause_ms": (590.0, 50.0, "ms"),
            "p99_ack_latency_ms": (620.0, 120.0, "ms"),
        },
    ),
    "enable_venue_pacing_backoff_sim": SimulatedActionSpec(
        action_id="enable_venue_pacing_backoff_sim",
        target_service="venue-adapter",
        risk_level=ActionRiskLevel.LOW,
        description="Enable smooth simulated venue pacing backoff on SIMY adapter.",
        default_parameters={"venue": "SIMY", "pacing_window_ms": 50},
        expected_checks=[
            "venue_throttle_count < 1.0",
            "p99_ack_latency_ms < 120.0",
        ],
        baseline_metrics={
            "venue_throttle_count": (12.0, 1.0, "count"),
            "p99_ack_latency_ms": (615.0, 120.0, "ms"),
        },
    ),
    "restart_risk_worker_pool_sim": SimulatedActionSpec(
        action_id="restart_risk_worker_pool_sim",
        target_service="risk-engine",
        risk_level=ActionRiskLevel.MEDIUM,
        description="Rolling restart of simulated pre-trade risk worker pool with fail-closed guard.",
        default_parameters={"fail_closed": True},
        expected_checks=["risk_check_p99_ms < 25.0"],
        baseline_metrics={"risk_check_p99_ms": (180.0, 25.0, "ms")},
    ),
    "failover_market_data_secondary_sim": SimulatedActionSpec(
        action_id="failover_market_data_secondary_sim",
        target_service="market-data-feed",
        risk_level=ActionRiskLevel.LOW,
        description="Switch simulated market-data consumer to secondary synthetic feed.",
        default_parameters={"feed": "secondary_sim"},
        expected_checks=["md_quote_age_ms < 50.0"],
        baseline_metrics={"md_quote_age_ms": (450.0, 50.0, "ms")},
    ),
}

FORBIDDEN_ACTIONS: set[str] = {
    "cancel_all_orders",
    "live_order_cancel",
    "submit_live_order",
    "disable_risk_limits",
    "disable_risk_checks",
    "modify_production_credentials",
    "export_customer_logs",
}


def compute_plan_digest(
    incident_id: str,
    remediation_id: str,
    action_id: str,
    target_service: str,
    parameters: dict[str, Any],
) -> str:
    """Compute a deterministic SHA-256 digest binding operator approval to exact remediation terms."""
    payload = {
        "incident_id": incident_id,
        "remediation_id": remediation_id,
        "action_id": action_id,
        "target_service": target_service,
        "parameters": parameters,
    }
    return compute_sha256(payload)


def propose_remediations(
    *,
    incident_id: str,
    verdict_status: VerdictStatus,
    primary: Optional[HypothesisEvaluation],
    hypotheses: list[HypothesisEvaluation],
    runbook_actions_by_id: dict[str, list[str]],
) -> list[RemediationProposal]:
    """Generate read-only remediation proposals bound by plan digests; never executes actions."""
    candidates: list[HypothesisEvaluation] = []
    if verdict_status == VerdictStatus.DETERMINED and primary is not None:
        candidates = [primary]
    elif verdict_status == VerdictStatus.AMBIGUOUS:
        candidates = hypotheses[:2]
    else:
        return []

    proposals: list[RemediationProposal] = []
    idx = 0
    for hyp in candidates:
        actions = runbook_actions_by_id.get(hyp.runbook_id or "", [])
        for action_id in actions:
            idx += 1
            remediation_id = f"REM-{incident_id}-{idx:02d}"
            if action_id in FORBIDDEN_ACTIONS or action_id not in ALLOWLISTED_SIM_ACTIONS:
                # Forbidden or unallowlisted actions are never proposed as executable plans.
                continue
            spec = ALLOWLISTED_SIM_ACTIONS[action_id]
            params = dict(spec.default_parameters)
            digest = compute_plan_digest(
                incident_id=incident_id,
                remediation_id=remediation_id,
                action_id=action_id,
                target_service=spec.target_service,
                parameters=params,
            )
            blocked_reason = (
                "Root cause verdict is AMBIGUOUS; run discriminating checks or explicitly "
                "set acknowledge_ambiguity=True in OperatorApproval."
                if verdict_status == VerdictStatus.AMBIGUOUS
                else None
            )
            proposals.append(
                RemediationProposal(
                    remediation_id=remediation_id,
                    incident_id=incident_id,
                    action_id=action_id,
                    target_service=spec.target_service,
                    risk_level=spec.risk_level,
                    parameters=params,
                    rationale=(
                        f"{spec.description} Proposed for hypothesis '{hyp.failure_mode}' "
                        f"(confidence={hyp.confidence:.2f}, runbook={hyp.runbook_id})."
                    ),
                    expected_recovery_checks=list(spec.expected_checks),
                    plan_digest=digest,
                    blocked_reason=blocked_reason,
                )
            )
    return proposals


class SimulatedTradingEnvironment:
    """In-memory deterministic simulated trading environment for approval-gated remediation."""

    def __init__(self, *, seed: int = 42, force_recovery_failure: bool = False) -> None:
        self.seed = seed
        self.force_recovery_failure = force_recovery_failure
        self.applied_actions: list[dict[str, Any]] = []
        self.mutation_count: int = 0

    def execute_and_verify(
        self,
        *,
        report: IncidentReport,
        proposal: RemediationProposal,
        approval: Optional[OperatorApproval],
        config: AgentConfig,
        now_utc: Optional[datetime] = None,
    ) -> RemediationReceipt:
        """Validate explicit approval and policy boundaries, then apply simulated remediation."""
        ts = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        receipt_id = f"RCPT-{compute_sha256({'rem': proposal.remediation_id, 'ts': ts.isoformat()})[:12]}"

        # 1. Forbidden / unallowlisted action check (cannot be bypassed even with approval)
        if proposal.action_id in FORBIDDEN_ACTIONS or proposal.action_id not in ALLOWLISTED_SIM_ACTIONS:
            raise ForbiddenActionError(
                f"Action '{proposal.action_id}' is forbidden or not in the simulated remediation allowlist.",
                details={"action_id": proposal.action_id},
            )

        # 2. Explicit approval presence check
        if approval is None:
            raise ApprovalRequiredError(
                f"Explicit operator approval is required before executing simulated remediation '{proposal.remediation_id}'.",
                details={"remediation_id": proposal.remediation_id, "action_id": proposal.action_id},
            )

        # 3. Role authorization check
        if approval.approver_role not in config.allowed_approver_roles:
            raise ApprovalMismatchError(
                f"Approver role '{approval.approver_role}' is not authorized; allowed roles: {config.allowed_approver_roles}.",
                details={"approver_role": approval.approver_role},
            )

        # 4. Binding checks (incident_id, remediation_id, cryptographic plan_digest)
        expected_digest = compute_plan_digest(
            incident_id=proposal.incident_id,
            remediation_id=proposal.remediation_id,
            action_id=proposal.action_id,
            target_service=proposal.target_service,
            parameters=proposal.parameters,
        )
        if (
            approval.incident_id != report.incident_id
            or approval.remediation_id != proposal.remediation_id
            or approval.plan_digest != proposal.plan_digest
            or approval.plan_digest != expected_digest
        ):
            raise ApprovalMismatchError(
                "OperatorApproval binding mismatch (incident_id, remediation_id, or plan_digest does not match proposal).",
                details={
                    "expected_digest": expected_digest,
                    "provided_digest": approval.plan_digest,
                },
            )

        # 5. Expiry check
        if approval.expires_at_utc < ts:
            raise ApprovalMismatchError(
                f"OperatorApproval '{approval.approval_id}' expired at {approval.expires_at_utc.isoformat()}.",
                details={"expires_at_utc": approval.expires_at_utc.isoformat(), "now_utc": ts.isoformat()},
            )

        # 6. Ambiguity guard
        if report.verdict_status == VerdictStatus.AMBIGUOUS and not approval.acknowledge_ambiguity:
            raise AmbiguousRootCauseError(
                "Cannot execute remediation for an AMBIGUOUS root-cause verdict unless "
                "OperatorApproval explicitly sets acknowledge_ambiguity=True.",
                details={"incident_id": report.incident_id, "verdict": report.verdict_status.value},
            )

        # 7. Execute bounded simulated state change & deterministic post-remediation verification
        spec = ALLOWLISTED_SIM_ACTIONS[proposal.action_id]
        self.mutation_count += 1
        self.applied_actions.append(
            {
                "remediation_id": proposal.remediation_id,
                "action_id": proposal.action_id,
                "target_service": proposal.target_service,
                "parameters": proposal.parameters,
                "approval_id": approval.approval_id,
                "approver_id": approval.approver_id,
                "executed_at_utc": ts.isoformat(),
            }
        )

        rng = random.Random(self.seed)
        checks: list[HealthCheckResult] = []
        for metric_name, (before_val, threshold, unit) in spec.baseline_metrics.items():
            if self.force_recovery_failure:
                # Simulated degraded recovery where metric remains above threshold
                after_val = round(threshold * rng.uniform(1.25, 1.80), 3)
            else:
                if threshold <= 1.0 and before_val >= 1.0 and unit in {"messages", "count"}:
                    after_val = 0.0
                else:
                    after_val = round(threshold * rng.uniform(0.30, 0.65), 3)
            passed = after_val < threshold
            checks.append(
                HealthCheckResult(
                    metric_name=metric_name,
                    before_value=before_val,
                    after_value=after_val,
                    threshold=threshold,
                    unit=unit,
                    passed=passed,
                )
            )

        all_passed = all(c.passed for c in checks)
        verification = RecoveryVerification(
            verified=all_passed,
            seed=self.seed,
            checks=checks,
            summary=(
                f"Simulated recovery verified: all {len(checks)} post-remediation health checks passed."
                if all_passed
                else "Simulated recovery verification FAILED: one or more health checks remained above threshold; rollback recommended."
            ),
            rollback_recommended=not all_passed,
        )

        return RemediationReceipt(
            receipt_id=receipt_id,
            incident_id=report.incident_id,
            remediation_id=proposal.remediation_id,
            action_id=proposal.action_id,
            status=(
                RemediationStatus.EXECUTED_RECOVERED
                if all_passed
                else RemediationStatus.EXECUTED_RECOVERY_FAILED
            ),
            approval_id=approval.approval_id,
            approver_id=approval.approver_id,
            executed_in_simulation=True,
            state_mutated=True,
            denial_reason=None,
            verification=verification,
            executed_at_utc=ts,
        )
