"""Structured domain errors with stable machine-readable error codes."""

from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    """Base structured error for the multi-agent trading platform."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }


class SecurityError(PlatformError):
    """Raised on prompt injection, unauthorized actor, or security invariant violation."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=403)


class ToolAccessError(PlatformError):
    """Raised when an agent attempts a disallowed tool, invalid arguments, or exceeds budget."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=403)


class PolicyViolationError(PlatformError):
    """Raised when deterministic policy blocks an action or config change."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=403)


class RiskCheckError(PlatformError):
    """Raised when independent pre-trade or pre-dispatch risk validation fails."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=422)


class ApprovalError(PlatformError):
    """Raised on missing, expired, replayed, tampered, or unauthorized approval actions."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=409)


class ConflictError(PlatformError):
    """Raised when conflicting agent proposals cannot be automatically reconciled."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=409)


class ExecutionBlockedError(PlatformError):
    """Raised when OMS dispatch is blocked (e.g., execution disabled, kill switch, broker failure)."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, details=details, http_status=409)
