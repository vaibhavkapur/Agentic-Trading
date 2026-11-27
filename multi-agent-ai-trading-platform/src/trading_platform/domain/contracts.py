"""Typed domain contracts for agents, evidence, proposals, risk, approvals, OMS, and audit."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_platform.domain.types import (
    AgentRole,
    ApprovalStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    ResearchStance,
    RiskStatus,
    RunStatus,
    TimeInForce,
    compute_exact_action_hash,
    ensure_utc,
)


class QuoteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    bid: Decimal = Field(gt=Decimal("0"))
    ask: Decimal = Field(gt=Decimal("0"))
    last: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    quote_timestamp_utc: datetime
    source: str = Field(min_length=1, max_length=64)

    @field_validator("quote_timestamp_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _check_spread(self) -> QuoteSnapshot:
        if self.ask < self.bid:
            raise ValueError("ask cannot be lower than bid")
        return self

    @property
    def mid(self) -> Decimal:
        return ((self.bid + self.ask) / Decimal("2")).quantize(Decimal("0.0001"))


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    pe_ratio: float = Field(ge=0.0)
    revenue_growth_yoy: float
    momentum_20d: float
    volatility_20d: float = Field(ge=0.0)
    available_at_utc: datetime

    @field_validator("available_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class NewsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    headline: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1, max_length=4000)
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    published_at_utc: datetime
    available_at_utc: datetime
    source: str = Field(min_length=1, max_length=64)

    @field_validator("published_at_utc", "available_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class PositionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    quantity: int = Field(ge=0)
    avg_cost_usd: Decimal = Field(ge=Decimal("0"))


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=64)
    cash_usd: Decimal = Field(ge=Decimal("0"))
    positions: dict[str, PositionSnapshot] = Field(default_factory=dict)
    as_of_utc: datetime

    @field_validator("as_of_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class AgentPermissionScope(BaseModel):
    """Explicit capability scope assigned to an agent role. Execution tools are never granted."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=64)
    role: AgentRole
    allowed_tools: list[str]
    can_submit_orders: bool = False
    can_approve_orders: bool = False
    can_override_policy: bool = False
    max_tool_calls: int = Field(ge=1, le=50)

    @model_validator(mode="after")
    def _enforce_hard_boundaries(self) -> AgentPermissionScope:
        if self.role in {AgentRole.RESEARCH_AGENT, AgentRole.PORTFOLIO_AGENT, AgentRole.RISK_SERVICE}:
            if self.can_submit_orders:
                raise ValueError(f"Agent role {self.role} cannot have can_submit_orders=True")
            if self.can_approve_orders:
                raise ValueError(f"Agent role {self.role} cannot have can_approve_orders=True")
            if self.can_override_policy:
                raise ValueError(f"Agent role {self.role} cannot have can_override_policy=True")
            forbidden_tools = {"submit_order", "cancel_order", "approve_order", "override_policy", "set_execution_mode"}
            overlap = forbidden_tools.intersection(self.allowed_tools)
            if overlap:
                raise ValueError(f"Agent role {self.role} cannot be granted forbidden tools: {sorted(overlap)}")
        return self


class EvidenceItem(BaseModel):
    """Immutable provenance record for a piece of data consumed during a run."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    symbol: str | None = Field(default=None, pattern=r"^[A-Z]{1,10}$")
    available_at_utc: datetime
    captured_at_utc: datetime
    content_hash: str = Field(min_length=64, max_length=64)
    sanitized_summary: str = Field(min_length=1, max_length=1000)
    tainted_injection_detected: bool = False
    injection_signals: list[str] = Field(default_factory=list)

    @field_validator("available_at_utc", "captured_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any]
    allowed: bool
    error_code: str | None = None
    timestamp_utc: datetime
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("timestamp_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ResearchReport(BaseModel):
    """Typed output of a read-only research agent adapter."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    stance: ResearchStance
    confidence: float = Field(ge=0.0, le=1.0)
    fair_value_usd: Decimal = Field(gt=Decimal("0"))
    thesis_summary: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1)
    injection_warnings: list[str] = Field(default_factory=list)
    created_at_utc: datetime

    @field_validator("created_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class OrderIntent(BaseModel):
    """Exact executable order specification (never directly executable by an agent)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    side: OrderSide
    quantity: int = Field(gt=0, le=1_000_000)
    order_type: OrderType
    limit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    time_in_force: TimeInForce = TimeInForce.DAY
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def _check_limit_price(self) -> OrderIntent:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT orders require a positive limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("MARKET orders must not specify a limit_price")
        return self


class PortfolioProposal(BaseModel):
    """Typed trade proposal produced by a portfolio agent. Cannot directly submit orders."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=3, max_length=64)
    order_intent: OrderIntent
    reference_price_usd: Decimal = Field(gt=Decimal("0"))
    estimated_notional_usd: Decimal = Field(gt=Decimal("0"))
    rationale: str = Field(min_length=1, max_length=1000)
    research_report_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    created_at_utc: datetime

    @field_validator("created_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    def exact_action_hash(self) -> str:
        return compute_exact_action_hash(
            account_id=self.order_intent.account_id,
            symbol=self.order_intent.symbol,
            side=self.order_intent.side,
            quantity=self.order_intent.quantity,
            order_type=self.order_intent.order_type,
            limit_price=self.order_intent.limit_price,
            time_in_force=self.order_intent.time_in_force,
            currency=self.order_intent.currency,
            policy_version=self.policy_version,
            proposal_id=self.proposal_id,
        )


class ConflictRecord(BaseModel):
    """Recorded disagreement between agents on direction or thesis."""

    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    agent_ids: list[str] = Field(min_length=2)
    stances: dict[str, ResearchStance]
    resolution: str = Field(min_length=1, max_length=128)
    blocked_execution: bool = True
    details: str = Field(min_length=1, max_length=1000)
    created_at_utc: datetime

    @field_validator("created_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class RiskCheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_name: str = Field(min_length=1, max_length=64)
    passed: bool
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    observed_value: str | None = None
    limit_value: str | None = None


class RiskAssessment(BaseModel):
    """Independent deterministic risk assessment (run both pre-approval and pre-dispatch)."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    proposal_id: str = Field(min_length=1, max_length=64)
    stage: str = Field(pattern=r"^(PRE_APPROVAL|PRE_DISPATCH)$")
    policy_version: str = Field(min_length=3, max_length=64)
    status: RiskStatus
    checks: list[RiskCheckItem] = Field(min_length=1)
    quote_timestamp_utc: datetime | None = None
    evaluated_at_utc: datetime
    nav_usd: Decimal = Field(ge=Decimal("0"))
    projected_gross_exposure_usd: Decimal = Field(ge=Decimal("0"))
    projected_position_notional_usd: Decimal = Field(ge=Decimal("0"))

    @field_validator("quote_timestamp_utc", "evaluated_at_utc")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @property
    def failed_checks(self) -> list[RiskCheckItem]:
        return [c for c in self.checks if not c.passed]


class ApprovalRequest(BaseModel):
    """Exact-action approval request bound by SHA-256 hash and strict TTL expiration."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    proposal_id: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=3, max_length=64)
    exact_action_hash: str = Field(min_length=64, max_length=64)
    order_intent: OrderIntent
    evidence_ids: list[str] = Field(min_length=1)
    risk_assessment_id: str = Field(min_length=1, max_length=64)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_by: str = Field(min_length=1, max_length=64)
    created_at_utc: datetime
    expires_at_utc: datetime
    decided_by: str | None = None
    decided_by_role: str | None = None
    decided_at_utc: datetime | None = None
    decision_reason: str | None = None
    consumed_at_utc: datetime | None = None
    consumed_by_order_id: str | None = None

    @field_validator("created_at_utc", "expires_at_utc", "decided_at_utc", "consumed_at_utc")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class ApprovalDecision(BaseModel):
    """Operator decision input to approve or reject an exact-action approval request."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1, max_length=64)
    approve: bool
    expected_action_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class OrderRecord(BaseModel):
    """Idempotent OMS order state with full provenance."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    client_order_id: str = Field(min_length=8, max_length=64)
    broker_order_id: str | None = None
    run_id: str = Field(min_length=1, max_length=64)
    proposal_id: str = Field(min_length=1, max_length=64)
    approval_id: str = Field(min_length=1, max_length=64)
    exact_action_hash: str = Field(min_length=64, max_length=64)
    pre_dispatch_risk_id: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=3, max_length=64)
    evidence_ids: list[str] = Field(min_length=1)
    order_intent: OrderIntent
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: int = Field(default=0, ge=0)
    avg_fill_price: Decimal | None = None
    created_at_utc: datetime
    updated_at_utc: datetime
    last_error: str | None = None

    @field_validator("created_at_utc", "updated_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class FillRecord(BaseModel):
    """Deduplicated execution fill from paper broker."""

    model_config = ConfigDict(extra="forbid")

    fill_id: str = Field(min_length=1, max_length=64)
    broker_fill_id: str = Field(min_length=1, max_length=64)
    order_id: str = Field(min_length=1, max_length=64)
    client_order_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    side: OrderSide
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    executed_at_utc: datetime

    @field_validator("executed_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class RunRecord(BaseModel):
    """Top-level orchestration run with linked provenance IDs."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    policy_version: str = Field(min_length=3, max_length=64)
    config_version: str = Field(min_length=1, max_length=32)
    status: RunStatus
    started_at_utc: datetime
    completed_at_utc: datetime | None = None
    tool_calls_used: int = Field(default=0, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    research_report_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    proposal_id: str | None = None
    pre_approval_risk_id: str | None = None
    approval_id: str | None = None
    order_id: str | None = None
    summary: str = Field(default="", max_length=1000)

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class AuditEntry(BaseModel):
    """Append-only SHA-256 hash-chained audit entry."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    event_id: str = Field(min_length=1, max_length=64)
    timestamp_utc: datetime
    actor_id: str = Field(min_length=1, max_length=64)
    actor_role: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=128)
    outcome: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=3, max_length=64)
    run_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str = Field(min_length=64, max_length=64)
    entry_hash: str = Field(min_length=64, max_length=64)

    @field_validator("timestamp_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class DomainEvent(BaseModel):
    """Typed event published on the internal event bus."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=128)
    timestamp_utc: datetime
    run_id: str | None = None
    policy_version: str = Field(min_length=3, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)
