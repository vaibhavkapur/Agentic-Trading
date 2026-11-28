"""Typed error hierarchy for the Macro Intelligence Agent."""

from __future__ import annotations

from typing import Any, Dict, Optional


class MacroAgentError(Exception):
    """Base exception carrying a machine-readable error code and context."""

    code: str = "MACRO_AGENT_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.details: Dict[str, Any] = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class ConfigurationError(MacroAgentError):
    """Raised when configuration is missing, malformed, or violates safety boundaries."""

    code = "CONFIGURATION_ERROR"


class SchemaValidationError(MacroAgentError):
    """Raised when an input or output record violates typed schema contracts."""

    code = "SCHEMA_VALIDATION_ERROR"


class EmbargoViolationError(MacroAgentError):
    """Raised when a caller explicitly requests an embargoed/future release."""

    code = "EMBARGO_VIOLATION"


class UnitMismatchError(MacroAgentError):
    """Raised when incompatible units or periodicities are compared."""

    code = "UNIT_MISMATCH"


class ConflictingReportsError(MacroAgentError):
    """Raised when strict mode encounters irreconcilable figures across reports."""

    code = "CONFLICTING_REPORTS"


class UntrustedInstructionError(MacroAgentError):
    """Raised when prompt-injection or untrusted override instructions are rejected."""

    code = "UNTRUSTED_SOURCE_INSTRUCTION"


class CitationVerificationError(MacroAgentError):
    """Raised when a reported figure or quote fails deterministic citation verification."""

    code = "CITATION_VERIFICATION_FAILED"


class UnsupportedInputError(MacroAgentError):
    """Raised for unsupported document types, units, or operations."""

    code = "UNSUPPORTED_INPUT"


class BudgetExceededError(MacroAgentError):
    """Raised when an optional model adapter exceeds configured call or token budgets."""

    code = "BUDGET_EXCEEDED"
