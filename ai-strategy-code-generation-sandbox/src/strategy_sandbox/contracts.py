"""Typed Pydantic v2 data contracts for the AI Strategy Code Generation Sandbox.

All monetary amounts are in USD, rates/costs are in basis points (bps) or fractions
as explicitly named, and all timestamps are timezone-aware UTC ISO-8601 datetimes.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .hashing import compute_dataset_bars_hash, sha256_text

SCHEMA_VERSION = "1.0.0"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware (UTC ISO-8601)")
    return dt.astimezone(timezone.utc)


def _require_finite(val: float, field_name: str) -> float:
    if not math.isfinite(val):
        raise ValueError(f"{field_name} must be finite")
    return val


class StrictModel(BaseModel):
    """Base model forbidding unexpected fields and non-finite floats."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AssetBar(StrictModel):
    """Single OHLCV market bar with strict timestamp and price invariants."""

    timestamp: datetime = Field(description="Bar close timestamp in UTC ISO-8601 format.")
    symbol: str = Field(description="Uppercase synthetic or approved instrument symbol.")
    open: float = Field(gt=0.0, description="Bar open price in USD.")
    high: float = Field(gt=0.0, description="Bar high price in USD.")
    low: float = Field(gt=0.0, description="Bar low price in USD.")
    close: float = Field(gt=0.0, description="Bar close price in USD.")
    volume: float = Field(ge=0.0, description="Bar traded volume in shares/units.")
    note: str | None = Field(
        default=None,
        max_length=256,
        description="Optional untrusted metadata note (screened before execution).",
    )

    @field_validator("timestamp")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        if not _SYMBOL_RE.match(v):
            raise ValueError(f"Invalid symbol '{v}': must match {_SYMBOL_RE.pattern}")
        return v

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def _validate_finite(cls, v: float, info: Any) -> float:
        return _require_finite(v, str(info.field_name))

    @model_validator(mode="after")
    def _validate_ohlc(self) -> "AssetBar":
        if self.high < max(self.open, self.close):
            raise ValueError("high must be >= max(open, close)")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= min(open, close)")
        if self.low > self.high:
            raise ValueError("low must be <= high")
        return self


class DatasetManifest(StrictModel):
    """Versioned, checksummed offline dataset approved for paper experiments."""

    dataset_id: str = Field(description="Stable dataset identifier.")
    version: str = Field(description="Semantic version of this dataset.")
    schema_version: str = Field(default=SCHEMA_VERSION)
    provenance: Literal["synthetic_fixture", "approved_offline"] = Field(
        default="synthetic_fixture",
        description="Origin classification; live/customer feeds are excluded.",
    )
    symbols: list[str] = Field(min_length=1, description="Sorted symbols present in bars.")
    bars: list[AssetBar] = Field(min_length=2, description="Time-ordered OHLCV bars.")
    sha256: str | None = Field(
        default=None,
        description="Canonical SHA-256 digest of bars; computed if omitted, verified if provided.",
    )
    description: str = Field(default="", max_length=512)

    @field_validator("dataset_id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _IDENTIFIER_RE.match(v):
            raise ValueError(f"Invalid dataset_id '{v}'")
        return v

    @model_validator(mode="after")
    def _validate_manifest(self) -> "DatasetManifest":
        declared_symbols = set(self.symbols)
        observed_symbols: set[str] = set()
        last_ts_by_symbol: dict[str, datetime] = {}

        # Verify global non-decreasing timestamp order and per-symbol strictly increasing timestamps
        prev_global_ts: datetime | None = None
        for bar in self.bars:
            observed_symbols.add(bar.symbol)
            if bar.symbol not in declared_symbols:
                raise ValueError(
                    f"Bar symbol '{bar.symbol}' not declared in manifest symbols {sorted(declared_symbols)}"
                )
            if prev_global_ts is not None and bar.timestamp < prev_global_ts:
                raise ValueError(
                    f"Bars must be globally sorted by timestamp: {bar.timestamp.isoformat()} < {prev_global_ts.isoformat()}"
                )
            prev_global_ts = bar.timestamp
            last_sym_ts = last_ts_by_symbol.get(bar.symbol)
            if last_sym_ts is not None and bar.timestamp <= last_sym_ts:
                raise ValueError(
                    f"Duplicate or out-of-order timestamp for symbol '{bar.symbol}': {bar.timestamp.isoformat()}"
                )
            last_ts_by_symbol[bar.symbol] = bar.timestamp

        missing = declared_symbols - observed_symbols
        if missing:
            raise ValueError(f"Declared symbols missing from bars: {sorted(missing)}")

        raw_bars = [b.model_dump(mode="json") for b in self.bars]
        computed = compute_dataset_bars_hash(raw_bars)
        if self.sha256 is None:
            object.__setattr__(self, "sha256", computed)
        else:
            if not _SHA256_RE.match(self.sha256):
                raise ValueError("Dataset sha256 must be a 64-char lowercase hex string")
            if self.sha256 != computed:
                raise ValueError(
                    f"Dataset sha256 mismatch: expected {self.sha256}, computed {computed}"
                )
        return self


class StrategySpec(StrictModel):
    """Canonical experiment specification defining risk limits, costs, and seed."""

    spec_id: str = Field(description="Stable strategy specification identifier.")
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(default="1.0.0")
    description: str = Field(default="", max_length=1024)
    target_symbols: list[str] = Field(min_length=1)
    initial_cash: float = Field(gt=0.0, le=1e9, default=100_000.0, description="Starting USD cash.")
    commission_bps: float = Field(
        ge=0.0, le=500.0, default=5.0, description="Commission in basis points of notional."
    )
    slippage_bps: float = Field(
        ge=0.0, le=500.0, default=10.0, description="Execution slippage in basis points."
    )
    max_gross_leverage: float = Field(
        gt=0.0, le=2.0, default=1.0, description="Maximum gross exposure / equity."
    )
    max_position_pct: float = Field(
        gt=0.0, le=1.0, default=0.5, description="Maximum single-symbol exposure / equity."
    )
    allow_short: bool = Field(
        default=False, description="Whether paper broker permits short positions."
    )
    seed: int = Field(default=42, ge=0, le=2**31 - 1, description="Fixed PRNG seed.")
    params: dict[str, int | float | str | bool] = Field(
        default_factory=dict, description="Typed read-only strategy parameters."
    )

    @field_validator("spec_id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _IDENTIFIER_RE.match(v):
            raise ValueError(f"Invalid spec_id '{v}'")
        return v

    @field_validator("target_symbols")
    @classmethod
    def _validate_symbols(cls, v: list[str]) -> list[str]:
        for sym in v:
            if not _SYMBOL_RE.match(sym):
                raise ValueError(f"Invalid target symbol '{sym}'")
        return v

    @field_validator(
        "initial_cash", "commission_bps", "slippage_bps", "max_gross_leverage", "max_position_pct"
    )
    @classmethod
    def _validate_finite(cls, v: float, info: Any) -> float:
        return _require_finite(v, str(info.field_name))


class ExperimentBudget(StrictModel):
    """Hard resource and security bounds enforced on untrusted strategy execution."""

    max_wall_time_sec: float = Field(gt=0.05, le=60.0, default=2.0)
    max_cpu_time_sec: float = Field(gt=0.05, le=30.0, default=1.0)
    max_memory_mb: int = Field(ge=16, le=1024, default=128)
    max_output_bytes: int = Field(ge=1024, le=1_048_576, default=65_536)
    max_steps: int = Field(ge=1, le=100_000, default=10_000)
    max_code_bytes: int = Field(ge=64, le=262_144, default=32_768)
    max_ast_nodes: int = Field(ge=10, le=20_000, default=2_000)
    allow_network: Literal[False] = False
    allow_filesystem_write: Literal[False] = False
    allow_subprocess: Literal[False] = False


class StrategyProposal(StrictModel):
    """Typed proposal separating generated code from deterministic verification."""

    proposal_id: str = Field(description="Unique proposal identifier.")
    spec_id: str = Field(description="Target StrategySpec identifier.")
    author_type: Literal["llm_generated", "human", "reference_oracle"] = "llm_generated"
    model_id: str | None = Field(default=None, max_length=128)
    code: str = Field(min_length=1, description="Python source implementing on_bar(ctx).")
    code_sha256: str | None = Field(default=None)
    rationale: str = Field(
        default="",
        max_length=2048,
        description="Untrusted natural-language rationale; never executed.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("proposal_id", "spec_id")
    @classmethod
    def _validate_ids(cls, v: str) -> str:
        if not _IDENTIFIER_RE.match(v):
            raise ValueError(f"Invalid identifier '{v}'")
        return v

    @field_validator("created_at")
    @classmethod
    def _validate_created(cls, v: datetime) -> datetime:
        return _require_utc(v)

    @model_validator(mode="after")
    def _validate_code_hash(self) -> "StrategyProposal":
        computed = sha256_text(self.code)
        if self.code_sha256 is None:
            object.__setattr__(self, "code_sha256", computed)
        else:
            if not _SHA256_RE.match(self.code_sha256):
                raise ValueError("code_sha256 must be a 64-char lowercase hex string")
            if self.code_sha256 != computed:
                raise ValueError(
                    f"code_sha256 mismatch: expected {self.code_sha256}, computed {computed}"
                )
        return self


class OrderIntent(StrictModel):
    """Typed order intent returned by strategy on_bar(ctx) for paper execution."""

    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0.0)
    order_type: Literal["MARKET"] = "MARKET"
    reason: str = Field(default="", max_length=160)

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        if not _SYMBOL_RE.match(v):
            raise ValueError(f"Invalid order symbol '{v}'")
        return v

    @field_validator("quantity")
    @classmethod
    def _validate_qty(cls, v: float) -> float:
        return _require_finite(v, "quantity")


class FillRecord(StrictModel):
    """Executed paper fill produced by the deterministic paper broker."""

    step: int = Field(ge=0)
    timestamp: datetime
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0.0)
    reference_price: float = Field(gt=0.0)
    fill_price: float = Field(gt=0.0)
    notional: float = Field(gt=0.0)
    commission: float = Field(ge=0.0)
    slippage_cost: float = Field(ge=0.0)
    realized_pnl_delta: float
    reason: str = ""

    @field_validator("timestamp")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)


class RejectedOrderRecord(StrictModel):
    """Order rejected by deterministic risk or contract checks."""

    step: int = Field(ge=0)
    timestamp: datetime
    symbol: str
    side: str
    quantity: float
    rejection_reason: str

    @field_validator("timestamp")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)


class EquityPoint(StrictModel):
    """Per-step mark-to-market portfolio snapshot."""

    step: int = Field(ge=0)
    timestamp: datetime
    cash: float
    positions_market_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    cumulative_commission: float
    gross_exposure: float
    gross_leverage: float
    identity_error: float

    @field_validator("timestamp")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)


class AccountingSummary(StrictModel):
    """Aggregate paper-experiment accounting metrics and invariant diagnostics."""

    initial_cash: float
    final_cash: float
    final_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_commission: float
    total_slippage_cost: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trade_count: int = Field(ge=0)
    rejected_order_count: int = Field(ge=0)
    turnover: float = Field(ge=0.0)
    max_observed_leverage: float = Field(ge=0.0)
    max_accounting_identity_error: float = Field(ge=0.0)
    ending_positions: dict[str, float] = Field(default_factory=dict)


class CheckResult(StrictModel):
    """Structured result for a single verification or security gate."""

    name: str
    passed: bool
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SandboxExecutionResult(StrictModel):
    """Raw output and telemetry from an isolated sandbox execution."""

    succeeded: bool
    exit_code: int | None
    timed_out: bool = False
    error_code: str | None = None
    error_message: str | None = None
    wall_time_sec: float = Field(ge=0.0)
    peak_traced_memory_bytes: int = Field(ge=0, default=0)
    output_bytes: int = Field(ge=0, default=0)
    steps_executed: int = Field(ge=0, default=0)
    orders_by_step: list[list[OrderIntent]] = Field(default_factory=list)
    isolation_capabilities: dict[str, Any] = Field(default_factory=dict)


class TrialRecord(StrictModel):
    """Immutable audit record of an evaluated strategy trial with artifact hashes."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    trial_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    proposal_id: str
    spec_id: str
    dataset_id: str
    dataset_version: str
    status: Literal[
        "PASSED",
        "FAILED_DATA_SAFETY",
        "FAILED_STATIC_POLICY",
        "FAILED_SANDBOX",
        "FAILED_LEAKAGE",
        "FAILED_DETERMINISM",
        "FAILED_ACCOUNTING",
        "FAILED_REFERENCE_ORACLE",
        "ERROR",
    ]
    code_sha256: str
    dataset_sha256: str
    input_bundle_sha256: str
    output_sha256: str
    checks: list[CheckResult]
    accounting: AccountingSummary | None = None
    fills: list[FillRecord] = Field(default_factory=list)
    rejected_orders: list[RejectedOrderRecord] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    runtime_env: dict[str, Any] = Field(default_factory=dict)
    structured_logs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)


class HumanReviewRecord(StrictModel):
    """Explicit human sign-off bound to immutable trial and code artifact hashes."""

    review_id: str
    trial_id: str
    reviewer: str = Field(min_length=2, max_length=128)
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    code_sha256: str
    output_sha256: str
    notes: str = Field(default="", max_length=2048)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("review_id", "trial_id")
    @classmethod
    def _validate_ids(cls, v: str) -> str:
        if not _IDENTIFIER_RE.match(v):
            raise ValueError(f"Invalid identifier '{v}'")
        return v

    @field_validator("code_sha256", "output_sha256")
    @classmethod
    def _validate_hashes(cls, v: str) -> str:
        if not _SHA256_RE.match(v):
            raise ValueError("Hash must be 64-char lowercase hex")
        return v

    @field_validator("reviewed_at")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)


class PromotionDecision(StrictModel):
    """Governance output certifying whether a trial may advance to paper-staging."""

    trial_id: str
    promoted: bool
    stage: Literal["REJECTED", "PAPER_STAGING_APPROVED"]
    code_sha256: str
    output_sha256: str
    review_id: str | None = None
    reviewer: str | None = None
    reason: str
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("decided_at")
    @classmethod
    def _validate_ts(cls, v: datetime) -> datetime:
        return _require_utc(v)


class VerificationConfig(StrictModel):
    accounting_tolerance: float = Field(gt=0.0, default=1e-6)
    reference_equity_tolerance: float = Field(gt=0.0, default=1e-6)
    determinism_repeats: int = Field(ge=2, le=5, default=2)
    leakage_checkpoint_fractions: list[float] = Field(default_factory=lambda: [0.35, 0.7])
    leakage_future_shock_multiplier: float = Field(gt=1.0, default=2.5)


class GovernanceConfig(StrictModel):
    require_all_checks_passed: bool = True
    require_human_review_for_promotion: bool = True
    allow_live_execution: Literal[False] = False


class SandboxConfig(StrictModel):
    """Top-level configuration loaded from config/default_sandbox_config.json."""

    config_version: str = Field(default="1.0.0")
    sandbox_backend: Literal["subprocess_isolated", "docker_rootless"] = "subprocess_isolated"
    default_budget: ExperimentBudget = Field(default_factory=ExperimentBudget)
    allowed_imports: list[str] = Field(default_factory=lambda: ["math", "statistics"])
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
