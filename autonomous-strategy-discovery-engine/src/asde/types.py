"""Canonical domain contracts, UTC time helpers, and deterministic fingerprinting."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional


def canonical_json(obj: Any) -> str:
    """Serialize any JSON-compatible object deterministically."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_canonical(obj: Any) -> str:
    """Compute SHA-256 fingerprint of a canonical JSON structure."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp string and enforce UTC timezone."""
    normalized = ts.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must include explicit UTC timezone: {ts!r}")
    return dt.astimezone(timezone.utc)


def format_utc(dt: datetime) -> str:
    """Format a datetime as canonical ISO-8601 UTC with Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class MarketBar:
    """Point-in-time market bar with explicit event and availability timestamps in UTC."""

    symbol: str
    event_time_utc: str
    available_time_utc: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    currency: str = "USD"

    def validate(self) -> None:
        ev = parse_utc(self.event_time_utc)
        av = parse_utc(self.available_time_utc)
        if av < ev:
            raise ValueError(
                f"available_time_utc ({self.available_time_utc}) cannot precede "
                f"event_time_utc ({self.event_time_utc}) for {self.symbol}"
            )
        if min(self.open, self.high, self.low, self.close) <= 0.0:
            raise ValueError(f"Prices must be strictly positive for {self.symbol} at {self.event_time_utc}")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError(f"High price inconsistent for {self.symbol} at {self.event_time_utc}")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError(f"Low price inconsistent for {self.symbol} at {self.event_time_utc}")
        if self.volume < 0.0:
            raise ValueError(f"Volume must be non-negative for {self.symbol} at {self.event_time_utc}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetManifest:
    """Immutable provenance and integrity manifest for a market dataset."""

    dataset_id: str
    schema_version: str
    source_type: str  # "synthetic" or "permitted_historical"
    entitlement: str
    license_note: str
    currency: str
    frequency: str
    symbols: List[str]
    start_time_utc: str
    end_time_utc: str
    row_count: int
    data_file: str
    data_sha256: str
    seed: Optional[int] = None

    def fingerprint(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetSnapshot:
    """In-memory chronological aligned market bars bound to a verified manifest."""

    manifest: DatasetManifest
    timestamps_utc: List[str]
    symbols: List[str]
    bars_by_symbol: Dict[str, List[MarketBar]]

    @property
    def num_bars(self) -> int:
        return len(self.timestamps_utc)

    @property
    def fingerprint(self) -> str:
        return self.manifest.fingerprint()


@dataclass
class EvaluationMetrics:
    """Risk-adjusted return, drawdown, turnover, and uncertainty summary."""

    total_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    annualized_turnover: float
    total_cost_drag: float
    gross_total_return: float
    gross_sharpe_ratio: float
    win_rate: float
    profit_factor: float
    num_bars: int
    sharpe_se: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    cagr_ci_low: float
    cagr_ci_high: float
    skewness: float
    kurtosis: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrialRecord:
    """Immutable audit record for every candidate or baseline trial, including failures."""

    trial_id: str
    run_id: str
    strategy_id: str
    family: str
    is_baseline: bool
    phase: str  # "inner_tuning", "walk_forward_validation", "holdout_test"
    status: str  # "PASSED", "REJECTED", "FAILED"
    seed: int
    parameters: Dict[str, Any]
    dataset_fingerprint: str
    split_manifest_hash: str
    cost_scenario: str
    cost_scenario_hash: str
    created_at_utc: str
    metrics: Optional[Dict[str, Any]] = None
    fold_metrics: List[Dict[str, Any]] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
