"""Typed domain error hierarchy for the AI Strategy Code Generation Sandbox."""

from __future__ import annotations

from typing import Any


class SandboxError(Exception):
    """Base exception for all sandbox domain and operational errors."""

    error_code: str = "SANDBOX_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ConfigurationError(SandboxError):
    error_code = "CONFIGURATION_ERROR"


class ContractValidationError(SandboxError):
    error_code = "CONTRACT_VALIDATION_ERROR"


class DatasetSafetyError(SandboxError):
    error_code = "DATASET_SAFETY_ERROR"


class StaticPolicyError(SandboxError):
    error_code = "STATIC_POLICY_ERROR"


class SandboxExecutionError(SandboxError):
    error_code = "SANDBOX_EXECUTION_ERROR"


class SandboxTimeoutError(SandboxExecutionError):
    error_code = "SANDBOX_TIMEOUT"


class ResourceLimitError(SandboxExecutionError):
    error_code = "RESOURCE_LIMIT_EXCEEDED"


class SecurityDenialError(SandboxExecutionError):
    error_code = "SECURITY_DENIAL"


class LeakageDetectedError(SandboxError):
    error_code = "FUTURE_DATA_LEAKAGE"


class DeterminismError(SandboxError):
    error_code = "NONDETERMINISTIC_BEHAVIOR"


class AccountingInvariantError(SandboxError):
    error_code = "ACCOUNTING_INVARIANT_VIOLATION"


class PromotionDeniedError(SandboxError):
    error_code = "PROMOTION_DENIED"
