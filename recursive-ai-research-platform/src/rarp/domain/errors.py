"""Structured error hierarchy for the Recursive AI Research Platform."""

from __future__ import annotations

from typing import Any, Dict, Optional


class RARPError(Exception):
    """Base structured exception with machine-readable error code and context."""

    code: str = "RARP_ERROR"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }


class RARPValidationError(RARPError):
    code = "VALIDATION_ERROR"


class LeakageError(RARPError):
    code = "LEAKAGE_DETECTED"


class DuplicateHypothesisError(RARPError):
    code = "DUPLICATE_HYPOTHESIS"


class BudgetExhaustedError(RARPError):
    code = "BUDGET_EXHAUSTED"


class WorkerCrashError(RARPError):
    code = "WORKER_CRASH"


class HallucinatedMetricError(RARPError):
    code = "HALLUCINATED_METRIC"


class HoldoutAccessError(RARPError):
    code = "HOLDOUT_ACCESS_DENIED"


class ReviewGateError(RARPError):
    code = "REVIEW_GATE_DENIED"


class ArtifactSignatureError(RARPError):
    code = "ARTIFACT_SIGNATURE_INVALID"


class PolicyViolationError(RARPError):
    code = "POLICY_VIOLATION"
