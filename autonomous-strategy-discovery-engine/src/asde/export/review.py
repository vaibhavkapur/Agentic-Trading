"""Independent review workflow and fail-safe operational controls for paper/sandbox promotion."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List

from asde.errors import GovernanceViolationError


ALLOWED_DECISIONS = {"APPROVE_PAPER_ONLY", "REJECT"}
ALLOWED_TARGETS = {"research_only", "paper_sandbox"}


@dataclass(frozen=True)
class ReviewDecision:
    """Explicit human/independent reviewer decision record."""

    reviewer_id: str
    reviewer_role: str
    decision: str  # "APPROVE_PAPER_ONLY" or "REJECT"
    rationale: str
    reviewed_at_utc: str
    checklist_verified: Dict[str, bool]
    requested_target: str = "paper_sandbox"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReviewGate:
    """Enforces independent review and keeps real-capital execution strictly disabled."""

    REQUIRED_CHECKLIST_KEYS = (
        "verified_no_holdout_leakage",
        "verified_realistic_costs",
        "verified_multiple_testing_stats",
        "verified_turnover_and_drawdown",
        "verified_data_entitlements",
    )

    def evaluate_review(
        self,
        *,
        package_manifest: Dict[str, Any],
        evaluation_evidence: Dict[str, Any],
        decision: ReviewDecision,
    ) -> Dict[str, Any]:
        """Validate a review decision against governance and fail-safe policies."""
        if decision.decision not in ALLOWED_DECISIONS:
            raise GovernanceViolationError(
                f"Invalid review decision {decision.decision!r}. Allowed: {sorted(ALLOWED_DECISIONS)}."
            )

        if decision.requested_target not in ALLOWED_TARGETS:
            raise GovernanceViolationError(
                f"Deployment target {decision.requested_target!r} is forbidden. "
                "Real-capital/live deployment requires separate legal, regulatory, broker, and risk approval."
            )

        author = package_manifest.get("produced_by", "asde_engine")
        if not decision.reviewer_id or decision.reviewer_id.strip() == author:
            raise GovernanceViolationError(
                "Independent reviewer_id must be non-empty and distinct from the automated discovery engine."
            )

        if not decision.rationale.strip():
            raise GovernanceViolationError("Review rationale is required.")

        failures: List[str] = []
        if evaluation_evidence.get("governance_status") != "ELIGIBLE_FOR_REVIEW":
            failures.append(
                f"candidate_not_eligible:{evaluation_evidence.get('governance_status')}"
            )
        if package_manifest.get("primary_cost_scenario") == "zero_cost_reference":
            failures.append("zero_cost_scenario_not_eligible_for_promotion")

        holdout_audit = evaluation_evidence.get("holdout_audit", {})
        if holdout_audit.get("holdout_reads_during_selection", 1) != 0:
            failures.append("holdout_leakage_detected_in_audit")

        if decision.decision == "APPROVE_PAPER_ONLY":
            missing_checks = [
                k for k in self.REQUIRED_CHECKLIST_KEYS if not decision.checklist_verified.get(k, False)
            ]
            if missing_checks:
                raise GovernanceViolationError(
                    "Cannot approve paper candidate with incomplete independent review checklist.",
                    details={"missing_checks": missing_checks},
                )
            if failures:
                raise GovernanceViolationError(
                    "Fail-safe gate blocked paper approval due to package compliance failures.",
                    details={"failures": failures},
                )
            return {
                "review_status": "APPROVED_FOR_PAPER_SANDBOX",
                "deployment_target": "paper_sandbox",
                "order_execution_enabled": False,
                "paper_execution_permitted": True,
                "live_execution_permitted": False,
                "decision": decision.to_dict(),
                "policy_checks_passed": True,
                "policy_failures": [],
            }

        return {
            "review_status": "REJECTED_BY_REVIEWER",
            "deployment_target": "research_only",
            "order_execution_enabled": False,
            "paper_execution_permitted": False,
            "live_execution_permitted": False,
            "decision": decision.to_dict(),
            "policy_checks_passed": len(failures) == 0,
            "policy_failures": failures,
        }
