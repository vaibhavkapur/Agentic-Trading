"""Canonical serialization, SHA-256 hashing, and runtime metadata capture."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize an object to canonical, deterministic UTF-8 JSON."""

    def _default(value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("Naive datetime cannot be canonically serialized")
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=_default,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_object(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def compute_dataset_bars_hash(bars: list[dict[str, Any]]) -> str:
    """Compute canonical SHA-256 over dataset bar records."""
    return sha256_object(bars)


def runtime_environment_snapshot(sandbox_backend: str = "subprocess_isolated") -> dict[str, Any]:
    """Record reproducible runtime environment metadata without host secrets."""
    packages: dict[str, str] = {}
    for pkg in ("pydantic", "pytest"):
        try:
            packages[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            packages[pkg] = "not-installed"

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sandbox_backend": sandbox_backend,
        "packages": packages,
        "executable_basename": sys.executable.rsplit("/", 1)[-1],
    }
