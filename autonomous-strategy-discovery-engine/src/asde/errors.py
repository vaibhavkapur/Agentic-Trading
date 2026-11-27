"""Structured domain errors for the Autonomous Strategy Discovery Engine."""

from __future__ import annotations

from typing import Any, Dict, Optional


class ASDEError(Exception):
    """Base structured error with machine-readable code and context."""

    code: str = "ASDE_ERROR"

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }


class DslValidationError(ASDEError):
    code = "DSL_VALIDATION_ERROR"


class UnconstrainedCodeError(DslValidationError):
    code = "UNCONSTRAINED_CODE_FORBIDDEN"


class LookAheadError(ASDEError):
    code = "LOOK_AHEAD_VIOLATION"


class HoldoutLeakageError(ASDEError):
    code = "HOLDOUT_LEAKAGE_VIOLATION"


class ManifestIntegrityError(ASDEError):
    code = "MANIFEST_INTEGRITY_ERROR"


class DataContractError(ASDEError):
    code = "DATA_CONTRACT_ERROR"


class GovernanceViolationError(ASDEError):
    code = "GOVERNANCE_VIOLATION"


class EvaluationError(ASDEError):
    code = "EVALUATION_ERROR"
