"""Typed exception hierarchy for the Trading Incident Investigation Agent."""

from __future__ import annotations


class IncidentAgentError(Exception):
    """Base error for all incident investigation agent failures."""

    error_code: str = "INCIDENT_AGENT_ERROR"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(IncidentAgentError):
    """Raised when configuration is missing, malformed, or violates safety invariants."""

    error_code = "CONFIGURATION_ERROR"


class InputValidationError(IncidentAgentError):
    """Raised when an incident bundle or telemetry fixture fails schema validation."""

    error_code = "INPUT_VALIDATION_ERROR"


class UnsupportedSchemaError(InputValidationError):
    """Raised when an input uses an unsupported schema version or environment."""

    error_code = "UNSUPPORTED_SCHEMA_ERROR"


class BudgetExceededError(IncidentAgentError):
    """Raised when deterministic step, tool-call, or LLM prompt budgets are exhausted."""

    error_code = "BUDGET_EXCEEDED_ERROR"


class UnauthorizedActionError(IncidentAgentError):
    """Base error for blocked or unauthorized remediation attempts."""

    error_code = "UNAUTHORIZED_ACTION_ERROR"


class ApprovalRequiredError(UnauthorizedActionError):
    """Raised when simulated remediation is attempted without explicit operator approval."""

    error_code = "APPROVAL_REQUIRED_ERROR"


class ApprovalMismatchError(UnauthorizedActionError):
    """Raised when approval digest, incident, remediation ID, role, or expiry is invalid."""

    error_code = "APPROVAL_MISMATCH_ERROR"


class ForbiddenActionError(UnauthorizedActionError):
    """Raised when an out-of-scope or forbidden operational action is requested."""

    error_code = "FORBIDDEN_ACTION_ERROR"


class AmbiguousRootCauseError(UnauthorizedActionError):
    """Raised when remediation is attempted on an ambiguous verdict without explicit override."""

    error_code = "AMBIGUOUS_ROOT_CAUSE_ERROR"
