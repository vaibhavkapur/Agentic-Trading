"""Deterministic canonical JSON serialization and SHA-256 hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize an object to canonical UTF-8 JSON with sorted keys and stable separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(payload: Any) -> str:
    """Return a full SHA-256 hex digest of a canonicalized payload."""
    encoded = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_proposal_hash(proposal_dict: dict) -> str:
    """Compute canonical SHA-256 hash binding a paper proposal to human approval."""
    return sha256_hex(proposal_dict)


def compute_config_hash(config_dict: dict) -> str:
    """Compute canonical SHA-256 hash of committee configuration."""
    return sha256_hex(config_dict)


def compute_decision_id(proposal_hash: str, config_hash: str, seed: int) -> str:
    """Generate a deterministic, stable decision identifier."""
    digest = sha256_hex(
        {
            "proposal_hash": proposal_hash,
            "config_hash": config_hash,
            "seed": seed,
        }
    )
    return f"DEC-{digest[:16].upper()}"
