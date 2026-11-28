"""Typed exceptions for the Financial Agent Evaluation Framework."""

from __future__ import annotations


class FinEvalError(Exception):
    """Base exception for all framework errors."""


class ConfigurationError(FinEvalError):
    """Raised when configuration files or settings are missing or invalid."""


class ContractValidationError(FinEvalError):
    """Raised when inputs or outputs violate typed data contracts."""


class HeldOutLeakageError(FinEvalError):
    """Raised when held-out tasks are accessed without explicit authorization."""


class UnsafeToolRequestError(FinEvalError):
    """Raised when an agent attempts to call a forbidden or non-whitelisted tool."""


class ToolBudgetExceededError(FinEvalError):
    """Raised when an agent exceeds its configured tool call or cost budget."""


class ToolExecutionError(FinEvalError):
    """Raised when a mock tool fails due to unavailability, timeout, or bad input."""


class ReceiptVerificationError(FinEvalError):
    """Raised when a tool execution receipt fails integrity verification."""


class UnsupportedOperationError(FinEvalError):
    """Raised when a requested provider, feature, or mode is explicitly unsupported."""
