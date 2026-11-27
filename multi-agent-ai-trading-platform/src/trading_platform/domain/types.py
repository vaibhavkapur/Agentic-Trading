"""Core domain enums, UTC timestamp helpers, and canonical SHA-256 hashing utilities."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ExecutionMode(StrEnum):
    """Operational execution mode. LIVE is never enabled in this prototype."""

    DISABLED = "DISABLED"
    PAPER = "PAPER"


class AgentRole(StrEnum):
    """Explicit agent and service roles with strict capability boundaries."""

    RESEARCH_AGENT = "RESEARCH_AGENT"
    PORTFOLIO_AGENT = "PORTFOLIO_AGENT"
    RISK_SERVICE = "RISK_SERVICE"
    ORCHESTRATOR = "ORCHESTRATOR"
    POLICY_ENGINE = "POLICY_ENGINE"
    OMS = "OMS"
    OPERATOR = "OPERATOR"


class ResearchStance(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(StrEnum):
    DAY = "DAY"
    IOC = "IOC"


class RiskStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PolicyDecisionStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    CONFLICT_ESCALATED = "CONFLICT_ESCALATED"


class ConflictResolutionMode(StrEnum):
    BLOCK_AND_ESCALATE = "BLOCK_AND_ESCALATE"
    MAJORITY_CONFIDENCE = "MAJORITY_CONFIDENCE"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class OrderStatus(StrEnum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNCERTAIN_TIMEOUT = "UNCERTAIN_TIMEOUT"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED_NO_ACTION = "COMPLETED_NO_ACTION"
    BLOCKED_CONFLICT = "BLOCKED_CONFLICT"
    BLOCKED_RISK = "BLOCKED_RISK"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    DISPATCHED = "DISPATCHED"
    FAILED = "FAILED"


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware in UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return format(obj.normalize(), "f")
    if isinstance(obj, datetime):
        return ensure_utc(obj).isoformat().replace("+00:00", "Z")
    if isinstance(obj, StrEnum):
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def canonical_json(payload: Any) -> str:
    """Serialize any JSON-like payload deterministically with sorted keys."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def canonical_hash(payload: Any) -> str:
    """Compute SHA-256 hex digest of a deterministically serialized payload."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_exact_action_hash(
    *,
    account_id: str,
    symbol: str,
    side: OrderSide | str,
    quantity: int,
    order_type: OrderType | str,
    limit_price: Decimal | None,
    time_in_force: TimeInForce | str,
    currency: str,
    policy_version: str,
    proposal_id: str,
) -> str:
    """Compute canonical exact-action SHA-256 hash binding every executable order parameter."""
    normalized_price = (
        f"{Decimal(limit_price).quantize(Decimal('0.0001'))}"
        if limit_price is not None
        else None
    )
    canonical_payload = {
        "account_id": account_id,
        "currency": currency,
        "limit_price": normalized_price,
        "order_type": str(order_type.value if isinstance(order_type, StrEnum) else order_type),
        "policy_version": policy_version,
        "proposal_id": proposal_id,
        "quantity": int(quantity),
        "side": str(side.value if isinstance(side, StrEnum) else side),
        "symbol": symbol.upper(),
        "time_in_force": str(
            time_in_force.value if isinstance(time_in_force, StrEnum) else time_in_force
        ),
    }
    return canonical_hash(canonical_payload)
