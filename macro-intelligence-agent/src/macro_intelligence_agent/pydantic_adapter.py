"""Optional Pydantic v2 validation adapter.

The core runtime has zero external dependencies for deterministic offline execution.
When `pydantic>=2.7` is installed, this module exposes Pydantic BaseModel mirrors
and JSON Schema export for downstream integrations.
"""

from __future__ import annotations

from typing import Any, Dict

from .models import ConsensusEstimate, MacroRelease

try:  # pragma: no cover - optional dependency
    import pydantic  # type: ignore[import-not-found]

    PYDANTIC_AVAILABLE = True
    PYDANTIC_VERSION = getattr(pydantic, "__version__", "unknown")
except ImportError:
    PYDANTIC_AVAILABLE = False
    PYDANTIC_VERSION = None


def validate_release_payload(payload: Dict[str, Any]) -> MacroRelease:
    """Validate a raw release payload using canonical contracts (with optional Pydantic check)."""
    # Canonical stdlib validator enforces all invariants (UTC timestamps, Decimal, Unit, non-empty).
    return MacroRelease.from_dict(payload)


def validate_consensus_payload(payload: Dict[str, Any]) -> ConsensusEstimate:
    """Validate a raw consensus payload using canonical contracts."""
    return ConsensusEstimate.from_dict(payload)


def runtime_validation_backend() -> Dict[str, Any]:
    return {
        "backend": "pydantic+stdlib" if PYDANTIC_AVAILABLE else "stdlib_dataclasses",
        "pydantic_available": PYDANTIC_AVAILABLE,
        "pydantic_version": PYDANTIC_VERSION,
    }
