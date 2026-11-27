"""Independent human review and paper-sandbox-only promotion gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from rarp.domain.errors import PolicyViolationError, ReviewGateError
from rarp.domain.types import (
    ExecutionMode,
    PromotionTarget,
    ReviewDecisionStatus,
    RunStatus,
    sha256_json,
    utc_now_iso,
)
from rarp.governance.signing import ArtifactSigner, SignedResearchArtifact
from rarp.registry.store import RunRegistry


@dataclass(frozen=True)
class ReviewDecision:
    decision_id: str
    run_id: str
    hypothesis_id: str
    proposer_id: str
    reviewer_id: str
    decision: str
    target_environment: str
    notes: str
    critic_report_id: str
    critic_report_sha256: str
    artifact_id: Optional[str]
    decided_at_utc: str
    decision_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperSandboxPackage:
    package_id: str
    run_id: str
    hypothesis_id: str
    proposer_id: str
    reviewer_id: str
    decision_id: str
    execution_mode: str
    order_execution_enabled: bool
    live_deployment_prohibited: bool
    data_manifest_id: str
    data_manifest_sha256: str
    split_sha256: str
    config_sha256: str
    experiment_spec: Dict[str, Any]
    metrics: Dict[str, float]
    critic_report_sha256: str
    signed_artifact: SignedResearchArtifact

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["signed_artifact"] = self.signed_artifact.to_dict()
        return data


class PromotionGate:
    """Enforces independent human review and strictly restricts promotions to PAPER_SANDBOX."""

    def __init__(self, registry: RunRegistry, signer: ArtifactSigner) -> None:
        self._registry = registry
        self._signer = signer

    def submit_decision(
        self,
        run_id: str,
        reviewer_id: str,
        approve: bool,
        target_environment: str = PromotionTarget.PAPER_SANDBOX.value,
        notes: str = "",
        signed_artifact: Optional[SignedResearchArtifact] = None,
    ) -> tuple[ReviewDecision, Optional[PaperSandboxPackage]]:
        """Record an independent human review decision and emit a paper-only package on approval."""
        # Hard policy ban: live/production promotion is never allowed by this platform.
        if target_environment != PromotionTarget.PAPER_SANDBOX.value:
            self._registry.record_audit_event(
                event_type="PROMOTION_TARGET_BLOCKED",
                actor_id=reviewer_id or "unknown",
                details={"run_id": run_id, "target_environment": target_environment},
            )
            raise PolicyViolationError(
                f"Promotion target '{target_environment}' is prohibited; only PAPER_SANDBOX is permitted. "
                "Live deployment requires a separate external governance approval.",
                {"run_id": run_id, "target_environment": target_environment},
            )

        run = self._registry.get_run(run_id)
        if run is None:
            raise ReviewGateError(f"Run '{run_id}' not found in immutable registry", {"run_id": run_id})

        if run.status != RunStatus.SUCCEEDED.value:
            raise ReviewGateError(
                f"Run '{run_id}' has status '{run.status}' and cannot be promoted",
                {"run_id": run_id, "status": run.status},
            )

        proposer_id = str(run.experiment_spec["hypothesis"]["proposer_id"])
        if not reviewer_id or not reviewer_id.strip():
            raise ReviewGateError("A non-empty independent reviewer_id is required")
        if reviewer_id == proposer_id or reviewer_id.startswith("auto_") or reviewer_id.startswith("agent_"):
            self._registry.record_audit_event(
                event_type="REVIEW_SEPARATION_OF_DUTIES_VIOLATION",
                actor_id=reviewer_id,
                details={"run_id": run_id, "proposer_id": proposer_id, "reviewer_id": reviewer_id},
            )
            raise ReviewGateError(
                f"Independent human reviewer required: reviewer '{reviewer_id}' cannot approve proposer '{proposer_id}'",
                {"run_id": run_id, "proposer_id": proposer_id, "reviewer_id": reviewer_id},
            )

        critic_report = self._registry.get_critic_report_for_run(run_id)
        if critic_report is None or not critic_report.get("verified", False):
            raise ReviewGateError(
                f"Run '{run_id}' lacks a verified evidence-linked CriticReport",
                {"run_id": run_id},
            )

        if signed_artifact is not None:
            self._signer.verify(signed_artifact)

        decided_at = utc_now_iso()
        status = (
            ReviewDecisionStatus.APPROVED_PAPER_ONLY.value
            if approve
            else ReviewDecisionStatus.REJECTED.value
        )

        body = {
            "run_id": run_id,
            "hypothesis_id": run.hypothesis_id,
            "proposer_id": proposer_id,
            "reviewer_id": reviewer_id,
            "decision": status,
            "target_environment": target_environment,
            "notes": notes,
            "critic_report_id": critic_report["report_id"],
            "critic_report_sha256": critic_report["report_sha256"],
            "artifact_id": signed_artifact.artifact_id if signed_artifact else None,
            "decided_at_utc": decided_at,
        }
        decision_hash = sha256_json(body)
        decision_id = f"rev_{decision_hash[:12]}"

        decision = ReviewDecision(
            decision_id=decision_id,
            run_id=run_id,
            hypothesis_id=run.hypothesis_id,
            proposer_id=proposer_id,
            reviewer_id=reviewer_id,
            decision=status,
            target_environment=target_environment,
            notes=notes,
            critic_report_id=critic_report["report_id"],
            critic_report_sha256=critic_report["report_sha256"],
            artifact_id=signed_artifact.artifact_id if signed_artifact else None,
            decided_at_utc=decided_at,
            decision_sha256=decision_hash,
        )
        self._registry.store_review_decision(decision.to_dict())

        if not approve:
            return decision, None

        package_payload = {
            "run_id": run.run_id,
            "hypothesis_id": run.hypothesis_id,
            "proposer_id": proposer_id,
            "reviewer_id": reviewer_id,
            "decision_id": decision_id,
            "execution_mode": ExecutionMode.DISABLED.value,
            "target_environment": PromotionTarget.PAPER_SANDBOX.value,
            "order_execution_enabled": False,
            "live_deployment_prohibited": True,
            "data_manifest_id": run.data_manifest_id,
            "data_manifest_sha256": run.data_manifest_sha256,
            "split_sha256": run.split_sha256,
            "config_sha256": run.config_sha256,
            "experiment_spec": run.experiment_spec,
            "metrics": run.metrics,
            "critic_report_sha256": critic_report["report_sha256"],
        }
        pkg_signed = self._signer.sign("paper_sandbox_package", package_payload)
        pkg = PaperSandboxPackage(
            package_id=f"paperpkg_{pkg_signed.payload_sha256[:12]}",
            run_id=run.run_id,
            hypothesis_id=run.hypothesis_id,
            proposer_id=proposer_id,
            reviewer_id=reviewer_id,
            decision_id=decision_id,
            execution_mode=ExecutionMode.DISABLED.value,
            order_execution_enabled=False,
            live_deployment_prohibited=True,
            data_manifest_id=run.data_manifest_id,
            data_manifest_sha256=run.data_manifest_sha256,
            split_sha256=run.split_sha256,
            config_sha256=run.config_sha256,
            experiment_spec=run.experiment_spec,
            metrics=run.metrics,
            critic_report_sha256=critic_report["report_sha256"],
            signed_artifact=pkg_signed,
        )
        self._registry.put_artifact(f"promotions/{pkg.package_id}.json", pkg.to_dict())
        return decision, pkg
