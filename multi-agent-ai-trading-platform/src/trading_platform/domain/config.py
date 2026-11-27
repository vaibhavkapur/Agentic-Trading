"""Versioned configuration schemas for policy, risk limits, and orchestrator budgets."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_platform.domain.types import (
    ConflictResolutionMode,
    ExecutionMode,
    OrderType,
    TimeInForce,
)


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(min_length=3, max_length=64)
    execution_mode: ExecutionMode = ExecutionMode.DISABLED
    allow_live_trading: bool = False
    require_human_approval: bool = True
    approval_ttl_seconds: int = Field(default=300, ge=5, le=86400)
    allow_agent_policy_override: bool = False
    conflict_resolution_mode: ConflictResolutionMode = ConflictResolutionMode.BLOCK_AND_ESCALATE
    allowed_symbols: list[str] = Field(min_length=1)
    allowed_order_types: list[OrderType] = Field(min_length=1)
    allowed_time_in_force: list[TimeInForce] = Field(min_length=1)
    authorized_approvers: dict[str, str] = Field(default_factory=dict)
    forbidden_approver_roles: list[str] = Field(
        default_factory=lambda: [
            "AGENT",
            "RESEARCH_AGENT",
            "PORTFOLIO_AGENT",
            "AUDITOR",
            "SYSTEM_ADMIN",
        ]
    )

    @field_validator("allow_live_trading")
    @classmethod
    def forbid_live_trading_by_default(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "allow_live_trading cannot be enabled in local/paper prototype configuration."
            )
        return value

    @field_validator("allow_agent_policy_override")
    @classmethod
    def forbid_agent_override(cls, value: bool) -> bool:
        if value:
            raise ValueError("Agents are permanently forbidden from overriding deterministic policy.")
        return value

    @field_validator("allowed_symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        return sorted({v.strip().upper() for v in values if v.strip()})


class RiskLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_quote_age_seconds: int = Field(default=60, ge=1, le=3600)
    max_order_notional_usd: Decimal = Field(gt=Decimal("0"))
    max_position_notional_usd: Decimal = Field(gt=Decimal("0"))
    max_gross_exposure_usd: Decimal = Field(gt=Decimal("0"))
    max_single_order_pct_nav: Decimal = Field(gt=Decimal("0"), le=Decimal("1"))
    max_position_pct_nav: Decimal = Field(gt=Decimal("0"), le=Decimal("1"))
    min_cash_buffer_usd: Decimal = Field(ge=Decimal("0"))
    max_price_deviation_bps: int = Field(default=250, ge=1, le=5000)


class OrchestratorBudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tool_calls_per_agent: int = Field(default=6, ge=1, le=50)
    max_total_tool_calls: int = Field(default=16, ge=1, le=200)
    max_steps_per_run: int = Field(default=12, ge=1, le=100)
    seed: int = 42


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_version: str = Field(min_length=1, max_length=32)
    environment: str = Field(default="local-prototype", min_length=1, max_length=64)
    policy: PolicyConfig
    risk_limits: RiskLimitsConfig
    orchestrator: OrchestratorBudgetConfig = Field(default_factory=OrchestratorBudgetConfig)

    @classmethod
    def from_file(cls, path: Path) -> PlatformConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(raw)
