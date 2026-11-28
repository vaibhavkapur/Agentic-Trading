"""Typed domain, validation, security, and operational exceptions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class CommitteeError(Exception):
    """Base error for AI Investment Committee."""

    error_code: str = "COMMITTEE_ERROR"

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: Dict[str, Any] = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class SchemaValidationError(CommitteeError):
    """Raised when an input or output record violates typed contract constraints."""

    error_code = "SCHEMA_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        field_errors: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        self.field_errors = field_errors or []
        super().__init__(message, details={"field_errors": self.field_errors})


class UnsupportedInputError(CommitteeError):
    """Raised for explicitly unsupported currencies, asset classes, or adapter modes."""

    error_code = "UNSUPPORTED_INPUT_ERROR"


class MissingConfigurationError(CommitteeError):
    """Raised when required configuration files or keys are absent or unreadable."""

    error_code = "MISSING_CONFIGURATION_ERROR"


class NoExecutionCapabilityError(CommitteeError):
    """Raised whenever live trading or order routing is requested or attempted."""

    error_code = "NO_EXECUTION_CAPABILITY"


class ToolAccessDeniedError(CommitteeError):
    """Raised when an agent attempts to call a tool outside its isolated role scope."""

    error_code = "TOOL_ACCESS_DENIED"


class BudgetExceededError(CommitteeError):
    """Raised when an agent exceeds its fixed tool-call, token, latency, or USD budget."""

    error_code = "BUDGET_EXCEEDED"


class AgentTimeoutError(CommitteeError):
    """Raised when an agent exceeds its wall-clock or simulated timeout limit."""

    error_code = "AGENT_TIMEOUT"


class RiskVetoBypassError(CommitteeError):
    """Raised when any actor attempts to override or approve a risk-vetoed proposal."""

    error_code = "RISK_VETO_BYPASS_FORBIDDEN"


class ProposalHashMismatchError(CommitteeError):
    """Raised when human approval hash does not match the canonical proposal hash."""

    error_code = "PROPOSAL_HASH_MISMATCH"


class DuplicateApprovalError(CommitteeError):
    """Raised when an approval ID is reused or a finalized proposal is approved again."""

    error_code = "DUPLICATE_APPROVAL"


class InvalidStateTransitionError(CommitteeError):
    """Raised when a deliberation state transition is illegal."""

    error_code = "INVALID_STATE_TRANSITION"
