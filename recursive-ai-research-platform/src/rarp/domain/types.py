"""Shared domain primitives, enums, deterministic serialization, and UTC helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class ExecutionMode(str, Enum):
    DISABLED = "DISABLED"
    PAPER_SANDBOX = "PAPER_SANDBOX"


class PromotionTarget(str, Enum):
    PAPER_SANDBOX = "PAPER_SANDBOX"


class ReviewDecisionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED_PAPER_ONLY = "APPROVED_PAPER_ONLY"
    REJECTED = "REJECTED"


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with Z suffix."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_iso(value: str) -> dt.datetime:
    """Parse an ISO-8601 UTC timestamp strictly requiring timezone awareness."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid UTC timestamp: {value!r}")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone (UTC): {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def canonical_json(obj: Any) -> str:
    """Serialize an object to deterministic canonical JSON for hashing and signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj).encode("utf-8"))
