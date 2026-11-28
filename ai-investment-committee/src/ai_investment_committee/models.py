"""Typed, immutable data contracts for the AI Investment Committee.

Provides strict runtime validation, canonical serialization (`model_dump`),
and factory validation (`model_validate`) with zero required external dependencies.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import (
    NoExecutionCapabilityError,
    SchemaValidationError,
    UnsupportedInputError,
)

SUPPORTED_SCHEMA_VERSION = "1.0.0"
SUPPORTED_CURRENCIES = frozenset({"USD"})
ALLOWED_SIDES = frozenset({"BUY", "SELL"})
ALLOWED_STANCES = frozenset({"bullish", "bearish", "neutral"})
ALLOWED_AGENT_ROLES = frozenset({"bull", "bear", "portfolio", "risk"})
ALLOWED_VERDICTS = frozenset({"PASS", "VETO"})
ALLOWED_CITATION_STATUSES = frozenset({"VERIFIED", "UNCERTAIN", "FABRICATED"})
ALLOWED_DECISION_STATUSES = frozenset(
    {
        "VETOED",
        "AWAITING_HUMAN_APPROVAL",
        "APPROVED_FOR_PAPER_ONLY",
        "REJECTED_BY_HUMAN",
        "HALTED_ERROR",
    }
)
ALLOWED_HUMAN_DECISIONS = frozenset({"APPROVE_PAPER", "REJECT"})
EXECUTION_CAPABILITY_NONE = "NONE_PAPER_ONLY"

_UTC_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")
_TICKER_RE = re.compile(r"^[A-Z0-9._-]{1,16}$")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(
            f"Expected object at '{path}'",
            field_errors=[{"field": path, "error": "expected mapping/object"}],
        )
    return value


def _require_non_empty_str(data: Mapping[str, Any], key: str, path: str) -> str:
    if key not in data:
        raise SchemaValidationError(
            f"Missing required field '{path}'",
            field_errors=[{"field": path, "error": "missing required field"}],
        )
    val = data[key]
    if not isinstance(val, str) or not val.strip():
        raise SchemaValidationError(
            f"Field '{path}' must be a non-empty string",
            field_errors=[{"field": path, "error": "must be non-empty string"}],
        )
    return val.strip()


def _require_utc_timestamp(data: Mapping[str, Any], key: str, path: str) -> str:
    ts = _require_non_empty_str(data, key, path)
    if not _UTC_ISO_RE.match(ts):
        raise SchemaValidationError(
            f"Field '{path}' must be a UTC ISO-8601 timestamp ending in 'Z' or '+00:00'",
            field_errors=[{"field": path, "error": f"invalid UTC ISO-8601 timestamp: {ts}"}],
        )
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaValidationError(
            f"Field '{path}' is not a valid calendar timestamp: {ts}",
            field_errors=[{"field": path, "error": str(exc)}],
        ) from exc
    return ts


def _require_number(
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    gt: Optional[float] = None,
    ge: Optional[float] = None,
    le: Optional[float] = None,
    as_int: bool = False,
) -> Any:
    if key not in data:
        raise SchemaValidationError(
            f"Missing required field '{path}'",
            field_errors=[{"field": path, "error": "missing required field"}],
        )
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise SchemaValidationError(
            f"Field '{path}' must be numeric",
            field_errors=[{"field": path, "error": "must be numeric"}],
        )
    if as_int and not isinstance(val, int):
        raise SchemaValidationError(
            f"Field '{path}' must be an integer",
            field_errors=[{"field": path, "error": "must be integer"}],
        )
    fval = float(val)
    if math.isnan(fval) or math.isinf(fval):
        raise SchemaValidationError(
            f"Field '{path}' must be finite",
            field_errors=[{"field": path, "error": "must be finite"}],
        )
    if gt is not None and not (fval > gt):
        raise SchemaValidationError(
            f"Field '{path}' must be > {gt} (got {val})",
            field_errors=[{"field": path, "error": f"must be > {gt}"}],
        )
    if ge is not None and not (fval >= ge):
        raise SchemaValidationError(
            f"Field '{path}' must be >= {ge} (got {val})",
            field_errors=[{"field": path, "error": f"must be >= {ge}"}],
        )
    if le is not None and not (fval <= le):
        raise SchemaValidationError(
            f"Field '{path}' must be <= {le} (got {val})",
            field_errors=[{"field": path, "error": f"must be <= {le}"}],
        )
    return int(val) if as_int else fval


def _require_bool(data: Mapping[str, Any], key: str, path: str, *, default: Optional[bool] = None) -> bool:
    if key not in data:
        if default is not None:
            return default
        raise SchemaValidationError(
            f"Missing required boolean field '{path}'",
            field_errors=[{"field": path, "error": "missing required boolean"}],
        )
    val = data[key]
    if not isinstance(val, bool):
        raise SchemaValidationError(
            f"Field '{path}' must be a boolean",
            field_errors=[{"field": path, "error": "must be boolean"}],
        )
    return val


@dataclass(frozen=True)
class EvidenceSnippet:
    evidence_id: str
    text: str
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    unit: Optional[str] = None

    @classmethod
    def model_validate(cls, data: Any, path: str = "evidence_snippet") -> "EvidenceSnippet":
        obj = _require_mapping(data, path)
        evidence_id = _require_non_empty_str(obj, "evidence_id", f"{path}.evidence_id")
        text = _require_non_empty_str(obj, "text", f"{path}.text")
        metric_name = obj.get("metric_name")
        if metric_name is not None and (not isinstance(metric_name, str) or not metric_name.strip()):
            raise SchemaValidationError(
                f"Field '{path}.metric_name' must be a non-empty string or null",
                field_errors=[{"field": f"{path}.metric_name", "error": "invalid metric_name"}],
            )
        metric_value = obj.get("metric_value")
        if metric_value is not None:
            if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
                raise SchemaValidationError(
                    f"Field '{path}.metric_value' must be numeric or null",
                    field_errors=[{"field": f"{path}.metric_value", "error": "must be numeric"}],
                )
            metric_value = float(metric_value)
        unit = obj.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit.strip()):
            raise SchemaValidationError(
                f"Field '{path}.unit' must be a non-empty string or null",
                field_errors=[{"field": f"{path}.unit", "error": "invalid unit"}],
            )
        return cls(
            evidence_id=evidence_id,
            text=text,
            metric_name=metric_name,
            metric_value=metric_value,
            unit=unit,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "text": self.text,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class ResearchBrief:
    brief_id: str
    title: str
    source: str
    published_at: str
    stance_hint: str
    snippets: Tuple[EvidenceSnippet, ...]

    @classmethod
    def model_validate(cls, data: Any, path: str = "research_brief") -> "ResearchBrief":
        obj = _require_mapping(data, path)
        brief_id = _require_non_empty_str(obj, "brief_id", f"{path}.brief_id")
        title = _require_non_empty_str(obj, "title", f"{path}.title")
        source = _require_non_empty_str(obj, "source", f"{path}.source")
        published_at = _require_utc_timestamp(obj, "published_at", f"{path}.published_at")
        stance_hint = _require_non_empty_str(obj, "stance_hint", f"{path}.stance_hint").lower()
        if stance_hint not in ALLOWED_STANCES:
            raise SchemaValidationError(
                f"Field '{path}.stance_hint' must be one of {sorted(ALLOWED_STANCES)}",
                field_errors=[{"field": f"{path}.stance_hint", "error": f"invalid stance: {stance_hint}"}],
            )
        raw_snippets = obj.get("snippets")
        if not isinstance(raw_snippets, Sequence) or isinstance(raw_snippets, (str, bytes)) or len(raw_snippets) == 0:
            raise SchemaValidationError(
                f"Field '{path}.snippets' must be a non-empty list",
                field_errors=[{"field": f"{path}.snippets", "error": "must be non-empty list"}],
            )
        snippets = tuple(
            EvidenceSnippet.model_validate(item, f"{path}.snippets[{idx}]")
            for idx, item in enumerate(raw_snippets)
        )
        return cls(
            brief_id=brief_id,
            title=title,
            source=source,
            published_at=published_at,
            stance_hint=stance_hint,
            snippets=snippets,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "brief_id": self.brief_id,
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at,
            "stance_hint": self.stance_hint,
            "snippets": [s.model_dump() for s in self.snippets],
        }


@dataclass(frozen=True)
class CandidatePosition:
    ticker: str
    sector: str
    side: str
    quantity: int
    limit_price_usd: float
    currency: str
    horizon_days: int
    estimated_volatility_annual_pct: float
    average_daily_volume_shares: int
    thesis_summary: str

    @property
    def trade_notional_usd(self) -> float:
        return round(self.quantity * self.limit_price_usd, 4)

    @classmethod
    def model_validate(cls, data: Any, path: str = "candidate_position") -> "CandidatePosition":
        obj = _require_mapping(data, path)
        ticker = _require_non_empty_str(obj, "ticker", f"{path}.ticker").upper()
        if not _TICKER_RE.match(ticker):
            raise SchemaValidationError(
                f"Field '{path}.ticker' contains invalid characters: {ticker}",
                field_errors=[{"field": f"{path}.ticker", "error": "invalid ticker format"}],
            )
        sector = _require_non_empty_str(obj, "sector", f"{path}.sector")
        side = _require_non_empty_str(obj, "side", f"{path}.side").upper()
        if side not in ALLOWED_SIDES:
            raise SchemaValidationError(
                f"Field '{path}.side' must be one of {sorted(ALLOWED_SIDES)} (got {side})",
                field_errors=[{"field": f"{path}.side", "error": f"invalid side: {side}"}],
            )
        quantity = _require_number(obj, "quantity", f"{path}.quantity", gt=0, as_int=True)
        limit_price_usd = _require_number(obj, "limit_price_usd", f"{path}.limit_price_usd", gt=0)
        currency = _require_non_empty_str(obj, "currency", f"{path}.currency").upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise UnsupportedInputError(
                f"Unsupported currency '{currency}'. Only {sorted(SUPPORTED_CURRENCIES)} are supported in this prototype.",
                details={"field": f"{path}.currency", "currency": currency},
            )
        horizon_days = _require_number(obj, "horizon_days", f"{path}.horizon_days", gt=0, as_int=True)
        vol_pct = _require_number(
            obj,
            "estimated_volatility_annual_pct",
            f"{path}.estimated_volatility_annual_pct",
            ge=0.0,
            le=500.0,
        )
        adv = _require_number(
            obj,
            "average_daily_volume_shares",
            f"{path}.average_daily_volume_shares",
            gt=0,
            as_int=True,
        )
        thesis_summary = _require_non_empty_str(obj, "thesis_summary", f"{path}.thesis_summary")
        return cls(
            ticker=ticker,
            sector=sector,
            side=side,
            quantity=quantity,
            limit_price_usd=limit_price_usd,
            currency=currency,
            horizon_days=horizon_days,
            estimated_volatility_annual_pct=vol_pct,
            average_daily_volume_shares=adv,
            thesis_summary=thesis_summary,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "sector": self.sector,
            "side": self.side,
            "quantity": self.quantity,
            "limit_price_usd": self.limit_price_usd,
            "currency": self.currency,
            "horizon_days": self.horizon_days,
            "estimated_volatility_annual_pct": self.estimated_volatility_annual_pct,
            "average_daily_volume_shares": self.average_daily_volume_shares,
            "thesis_summary": self.thesis_summary,
        }


@dataclass(frozen=True)
class PortfolioHolding:
    ticker: str
    sector: str
    quantity: int
    market_price_usd: float
    market_value_usd: float
    volatility_annual_pct: float

    @classmethod
    def model_validate(cls, data: Any, path: str = "holding") -> "PortfolioHolding":
        obj = _require_mapping(data, path)
        ticker = _require_non_empty_str(obj, "ticker", f"{path}.ticker").upper()
        sector = _require_non_empty_str(obj, "sector", f"{path}.sector")
        quantity = _require_number(obj, "quantity", f"{path}.quantity", ge=0, as_int=True)
        market_price_usd = _require_number(obj, "market_price_usd", f"{path}.market_price_usd", gt=0)
        market_value_usd = _require_number(obj, "market_value_usd", f"{path}.market_value_usd", ge=0)
        vol = _require_number(obj, "volatility_annual_pct", f"{path}.volatility_annual_pct", ge=0, le=500.0)
        return cls(
            ticker=ticker,
            sector=sector,
            quantity=quantity,
            market_price_usd=market_price_usd,
            market_value_usd=market_value_usd,
            volatility_annual_pct=vol,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "sector": self.sector,
            "quantity": self.quantity,
            "market_price_usd": self.market_price_usd,
            "market_value_usd": self.market_value_usd,
            "volatility_annual_pct": self.volatility_annual_pct,
        }


@dataclass(frozen=True)
class PortfolioState:
    portfolio_id: str
    as_of: str
    nav_usd: float
    cash_usd: float
    current_estimated_var_95_pct: float
    holdings: Tuple[PortfolioHolding, ...]

    @classmethod
    def model_validate(cls, data: Any, path: str = "portfolio_state") -> "PortfolioState":
        obj = _require_mapping(data, path)
        portfolio_id = _require_non_empty_str(obj, "portfolio_id", f"{path}.portfolio_id")
        as_of = _require_utc_timestamp(obj, "as_of", f"{path}.as_of")
        nav_usd = _require_number(obj, "nav_usd", f"{path}.nav_usd", gt=0)
        cash_usd = _require_number(obj, "cash_usd", f"{path}.cash_usd", ge=0)
        var_pct = _require_number(
            obj, "current_estimated_var_95_pct", f"{path}.current_estimated_var_95_pct", ge=0, le=100.0
        )
        raw_holdings = obj.get("holdings")
        if not isinstance(raw_holdings, Sequence) or isinstance(raw_holdings, (str, bytes)):
            raise SchemaValidationError(
                f"Field '{path}.holdings' must be a list",
                field_errors=[{"field": f"{path}.holdings", "error": "must be a list"}],
            )
        holdings = tuple(
            PortfolioHolding.model_validate(item, f"{path}.holdings[{idx}]")
            for idx, item in enumerate(raw_holdings)
        )
        return cls(
            portfolio_id=portfolio_id,
            as_of=as_of,
            nav_usd=nav_usd,
            cash_usd=cash_usd,
            current_estimated_var_95_pct=var_pct,
            holdings=holdings,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "as_of": self.as_of,
            "nav_usd": self.nav_usd,
            "cash_usd": self.cash_usd,
            "current_estimated_var_95_pct": self.current_estimated_var_95_pct,
            "holdings": [h.model_dump() for h in self.holdings],
        }


@dataclass(frozen=True)
class RiskPolicy:
    schema_version: str
    policy_id: str
    max_single_position_weight_pct: float
    max_sector_weight_pct: float
    max_gross_exposure_pct: float
    min_cash_reserve_pct: float
    max_estimated_var_95_pct: float
    max_adv_participation_pct: float
    min_verified_citation_ratio: float
    max_fabricated_citations: int
    restricted_tickers: Tuple[str, ...]
    allow_live_execution: bool = False

    @classmethod
    def model_validate(cls, data: Any, path: str = "risk_policy") -> "RiskPolicy":
        obj = _require_mapping(data, path)
        schema_version = _require_non_empty_str(obj, "schema_version", f"{path}.schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise UnsupportedInputError(
                f"Unsupported risk_policy schema_version '{schema_version}' (expected '{SUPPORTED_SCHEMA_VERSION}')",
                details={"field": f"{path}.schema_version", "schema_version": schema_version},
            )
        policy_id = _require_non_empty_str(obj, "policy_id", f"{path}.policy_id")
        max_pos = _require_number(obj, "max_single_position_weight_pct", f"{path}.max_single_position_weight_pct", gt=0, le=100.0)
        max_sec = _require_number(obj, "max_sector_weight_pct", f"{path}.max_sector_weight_pct", gt=0, le=100.0)
        max_gross = _require_number(obj, "max_gross_exposure_pct", f"{path}.max_gross_exposure_pct", gt=0, le=300.0)
        min_cash = _require_number(obj, "min_cash_reserve_pct", f"{path}.min_cash_reserve_pct", ge=0, le=100.0)
        max_var = _require_number(obj, "max_estimated_var_95_pct", f"{path}.max_estimated_var_95_pct", gt=0, le=100.0)
        max_adv = _require_number(obj, "max_adv_participation_pct", f"{path}.max_adv_participation_pct", gt=0, le=100.0)
        min_cit = _require_number(obj, "min_verified_citation_ratio", f"{path}.min_verified_citation_ratio", ge=0.0, le=1.0)
        max_fab = _require_number(obj, "max_fabricated_citations", f"{path}.max_fabricated_citations", ge=0, as_int=True)
        raw_restricted = obj.get("restricted_tickers", [])
        if not isinstance(raw_restricted, Sequence) or isinstance(raw_restricted, (str, bytes)):
            raise SchemaValidationError(
                f"Field '{path}.restricted_tickers' must be a list of ticker strings",
                field_errors=[{"field": f"{path}.restricted_tickers", "error": "must be list"}],
            )
        restricted = tuple(str(t).strip().upper() for t in raw_restricted if str(t).strip())
        allow_live = _require_bool(obj, "allow_live_execution", f"{path}.allow_live_execution", default=False)
        if allow_live:
            raise NoExecutionCapabilityError(
                "Risk policy cannot enable allow_live_execution=true; live execution is strictly prohibited.",
                details={"field": f"{path}.allow_live_execution"},
            )
        return cls(
            schema_version=schema_version,
            policy_id=policy_id,
            max_single_position_weight_pct=max_pos,
            max_sector_weight_pct=max_sec,
            max_gross_exposure_pct=max_gross,
            min_cash_reserve_pct=min_cash,
            max_estimated_var_95_pct=max_var,
            max_adv_participation_pct=max_adv,
            min_verified_citation_ratio=min_cit,
            max_fabricated_citations=max_fab,
            restricted_tickers=restricted,
            allow_live_execution=False,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "max_single_position_weight_pct": self.max_single_position_weight_pct,
            "max_sector_weight_pct": self.max_sector_weight_pct,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "min_cash_reserve_pct": self.min_cash_reserve_pct,
            "max_estimated_var_95_pct": self.max_estimated_var_95_pct,
            "max_adv_participation_pct": self.max_adv_participation_pct,
            "min_verified_citation_ratio": self.min_verified_citation_ratio,
            "max_fabricated_citations": self.max_fabricated_citations,
            "restricted_tickers": list(self.restricted_tickers),
            "allow_live_execution": self.allow_live_execution,
        }


@dataclass(frozen=True)
class CommitteeProposal:
    schema_version: str
    proposal_id: str
    created_at: str
    as_of: str
    execution_mode: str
    candidate_position: CandidatePosition
    portfolio_state: PortfolioState
    risk_policy: RiskPolicy
    research_briefs: Tuple[ResearchBrief, ...]

    def evidence_index(self) -> Dict[str, EvidenceSnippet]:
        index: Dict[str, EvidenceSnippet] = {}
        for brief in self.research_briefs:
            for snippet in brief.snippets:
                index[snippet.evidence_id] = snippet
        return index

    @classmethod
    def model_validate(cls, data: Any, path: str = "proposal") -> "CommitteeProposal":
        obj = _require_mapping(data, path)
        schema_version = _require_non_empty_str(obj, "schema_version", f"{path}.schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise UnsupportedInputError(
                f"Unsupported proposal schema_version '{schema_version}' (expected '{SUPPORTED_SCHEMA_VERSION}')",
                details={"field": f"{path}.schema_version", "schema_version": schema_version},
            )
        proposal_id = _require_non_empty_str(obj, "proposal_id", f"{path}.proposal_id")
        created_at = _require_utc_timestamp(obj, "created_at", f"{path}.created_at")
        as_of = _require_utc_timestamp(obj, "as_of", f"{path}.as_of")
        execution_mode = _require_non_empty_str(obj, "execution_mode", f"{path}.execution_mode").upper()
        if execution_mode != "PAPER":
            raise NoExecutionCapabilityError(
                f"Execution mode '{execution_mode}' is forbidden. Only 'PAPER' proposals are permitted.",
                details={"field": f"{path}.execution_mode", "execution_mode": execution_mode},
            )
        candidate_position = CandidatePosition.model_validate(
            obj.get("candidate_position"), f"{path}.candidate_position"
        )
        portfolio_state = PortfolioState.model_validate(
            obj.get("portfolio_state"), f"{path}.portfolio_state"
        )
        risk_policy = RiskPolicy.model_validate(obj.get("risk_policy"), f"{path}.risk_policy")
        raw_briefs = obj.get("research_briefs")
        if not isinstance(raw_briefs, Sequence) or isinstance(raw_briefs, (str, bytes)) or len(raw_briefs) == 0:
            raise SchemaValidationError(
                f"Field '{path}.research_briefs' must be a non-empty list",
                field_errors=[{"field": f"{path}.research_briefs", "error": "must be non-empty list"}],
            )
        briefs = tuple(
            ResearchBrief.model_validate(item, f"{path}.research_briefs[{idx}]")
            for idx, item in enumerate(raw_briefs)
        )
        seen_evidence_ids = set()
        for brief in briefs:
            for snip in brief.snippets:
                if snip.evidence_id in seen_evidence_ids:
                    raise SchemaValidationError(
                        f"Duplicate evidence_id '{snip.evidence_id}' in research_briefs",
                        field_errors=[{"field": f"{path}.research_briefs", "error": f"duplicate evidence_id {snip.evidence_id}"}],
                    )
                seen_evidence_ids.add(snip.evidence_id)
        return cls(
            schema_version=schema_version,
            proposal_id=proposal_id,
            created_at=created_at,
            as_of=as_of,
            execution_mode=execution_mode,
            candidate_position=candidate_position,
            portfolio_state=portfolio_state,
            risk_policy=risk_policy,
            research_briefs=briefs,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "created_at": self.created_at,
            "as_of": self.as_of,
            "execution_mode": self.execution_mode,
            "candidate_position": self.candidate_position.model_dump(),
            "portfolio_state": self.portfolio_state.model_dump(),
            "risk_policy": self.risk_policy.model_dump(),
            "research_briefs": [b.model_dump() for b in self.research_briefs],
        }


@dataclass(frozen=True)
class AgentBudget:
    max_tool_calls: int
    max_tokens: int
    max_latency_ms: int
    max_cost_usd: float

    @classmethod
    def model_validate(cls, data: Any, path: str = "agent_budget") -> "AgentBudget":
        obj = _require_mapping(data, path)
        return cls(
            max_tool_calls=_require_number(obj, "max_tool_calls", f"{path}.max_tool_calls", gt=0, as_int=True),
            max_tokens=_require_number(obj, "max_tokens", f"{path}.max_tokens", gt=0, as_int=True),
            max_latency_ms=_require_number(obj, "max_latency_ms", f"{path}.max_latency_ms", gt=0, as_int=True),
            max_cost_usd=_require_number(obj, "max_cost_usd", f"{path}.max_cost_usd", gt=0),
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "max_latency_ms": self.max_latency_ms,
            "max_cost_usd": self.max_cost_usd,
        }


@dataclass(frozen=True)
class CommitteeConfig:
    schema_version: str
    config_id: str
    seed: int
    adapter_mode: str
    allow_live_execution: bool
    strict_citation_mode: bool
    require_human_approval: bool
    agent_budgets: Dict[str, AgentBudget]

    @classmethod
    def model_validate(cls, data: Any, path: str = "committee_config") -> "CommitteeConfig":
        obj = _require_mapping(data, path)
        schema_version = _require_non_empty_str(obj, "schema_version", f"{path}.schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise UnsupportedInputError(
                f"Unsupported config schema_version '{schema_version}'",
                details={"field": f"{path}.schema_version"},
            )
        config_id = _require_non_empty_str(obj, "config_id", f"{path}.config_id")
        seed = _require_number(obj, "seed", f"{path}.seed", ge=0, as_int=True)
        adapter_mode = _require_non_empty_str(obj, "adapter_mode", f"{path}.adapter_mode")
        if adapter_mode not in {"deterministic_mock", "custom_adapter"}:
            raise UnsupportedInputError(
                f"Unsupported adapter_mode '{adapter_mode}'. Live external LLM calls are disabled by default.",
                details={"field": f"{path}.adapter_mode", "adapter_mode": adapter_mode},
            )
        allow_live = _require_bool(obj, "allow_live_execution", f"{path}.allow_live_execution", default=False)
        if allow_live:
            raise NoExecutionCapabilityError(
                "CommitteeConfig cannot set allow_live_execution=true; no execution capability exists.",
                details={"field": f"{path}.allow_live_execution"},
            )
        strict_citation = _require_bool(obj, "strict_citation_mode", f"{path}.strict_citation_mode", default=True)
        require_human = _require_bool(obj, "require_human_approval", f"{path}.require_human_approval", default=True)
        if not require_human:
            raise SchemaValidationError(
                "CommitteeConfig must enforce require_human_approval=true",
                field_errors=[{"field": f"{path}.require_human_approval", "error": "human approval is mandatory"}],
            )
        raw_budgets = _require_mapping(obj.get("agent_budgets"), f"{path}.agent_budgets")
        budgets: Dict[str, AgentBudget] = {}
        for role in sorted(ALLOWED_AGENT_ROLES):
            if role not in raw_budgets:
                raise SchemaValidationError(
                    f"Missing budget for required agent role '{role}'",
                    field_errors=[{"field": f"{path}.agent_budgets.{role}", "error": "missing role budget"}],
                )
            budgets[role] = AgentBudget.model_validate(raw_budgets[role], f"{path}.agent_budgets.{role}")
        return cls(
            schema_version=schema_version,
            config_id=config_id,
            seed=seed,
            adapter_mode=adapter_mode,
            allow_live_execution=False,
            strict_citation_mode=strict_citation,
            require_human_approval=require_human,
            agent_budgets=budgets,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config_id": self.config_id,
            "seed": self.seed,
            "adapter_mode": self.adapter_mode,
            "allow_live_execution": self.allow_live_execution,
            "strict_citation_mode": self.strict_citation_mode,
            "require_human_approval": self.require_human_approval,
            "agent_budgets": {role: b.model_dump() for role, b in sorted(self.agent_budgets.items())},
        }


@dataclass(frozen=True)
class Claim:
    """Atomic analytical claim.

    Invariant: every claim must either cite >= 1 evidence_id OR be explicitly marked
    `is_uncertain=True` with a non-empty `uncertainty_reason`.
    """

    claim_id: str
    author_role: str
    statement: str
    evidence_ids: Tuple[str, ...]
    is_uncertain: bool = False
    uncertainty_reason: Optional[str] = None
    citation_status: str = "VERIFIED"
    fabricated_evidence_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim_id.strip():
            raise SchemaValidationError("claim_id must be non-empty")
        if self.author_role not in ALLOWED_AGENT_ROLES:
            raise SchemaValidationError(f"Invalid author_role: {self.author_role}")
        if not self.statement.strip():
            raise SchemaValidationError("Claim statement must be non-empty")
        if self.citation_status not in ALLOWED_CITATION_STATUSES:
            raise SchemaValidationError(f"Invalid citation_status: {self.citation_status}")
        if not self.evidence_ids and not self.is_uncertain:
            raise SchemaValidationError(
                f"Claim '{self.claim_id}' has no evidence_ids and is not marked uncertain",
                field_errors=[{"field": "claim", "error": "all claims must be cited or marked uncertain"}],
            )
        if self.is_uncertain and (not self.uncertainty_reason or not self.uncertainty_reason.strip()):
            raise SchemaValidationError(
                f"Uncertain claim '{self.claim_id}' requires non-empty uncertainty_reason",
                field_errors=[{"field": "uncertainty_reason", "error": "required when is_uncertain=True"}],
            )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "author_role": self.author_role,
            "statement": self.statement,
            "evidence_ids": list(self.evidence_ids),
            "is_uncertain": self.is_uncertain,
            "uncertainty_reason": self.uncertainty_reason,
            "citation_status": self.citation_status,
            "fabricated_evidence_ids": list(self.fabricated_evidence_ids),
        }


@dataclass(frozen=True)
class ThesisRecord:
    proposal_id: str
    ticker: str
    stance: str
    conviction_score: float
    summary: str
    claims: Tuple[Claim, ...]
    injection_flags: Tuple[str, ...] = ()

    def model_dump(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "ticker": self.ticker,
            "stance": self.stance,
            "conviction_score": self.conviction_score,
            "summary": self.summary,
            "claims": [c.model_dump() for c in self.claims],
            "injection_flags": list(self.injection_flags),
        }


@dataclass(frozen=True)
class ChallengeRecord:
    proposal_id: str
    ticker: str
    dissent_level: str
    dissent_score: float
    challenged_claim_ids: Tuple[str, ...]
    summary: str
    claims: Tuple[Claim, ...]
    injection_flags: Tuple[str, ...] = ()

    def model_dump(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "ticker": self.ticker,
            "dissent_level": self.dissent_level,
            "dissent_score": self.dissent_score,
            "challenged_claim_ids": list(self.challenged_claim_ids),
            "summary": self.summary,
            "claims": [c.model_dump() for c in self.claims],
            "injection_flags": list(self.injection_flags),
        }


@dataclass(frozen=True)
class PortfolioReviewRecord:
    proposal_id: str
    ticker: str
    sizing_recommendation: str
    pro_forma_metrics: Dict[str, float]
    summary: str
    claims: Tuple[Claim, ...]

    def model_dump(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "ticker": self.ticker,
            "sizing_recommendation": self.sizing_recommendation,
            "pro_forma_metrics": dict(self.pro_forma_metrics),
            "summary": self.summary,
            "claims": [c.model_dump() for c in self.claims],
        }


@dataclass(frozen=True)
class RiskCheckResult:
    rule_id: str
    passed: bool
    observed_value: Any
    limit_value: Any
    unit: str
    message: str

    def model_dump(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "observed_value": self.observed_value,
            "limit_value": self.limit_value,
            "unit": self.unit,
            "message": self.message,
        }


@dataclass(frozen=True)
class RiskVerdictRecord:
    proposal_id: str
    policy_id: str
    verdict: str
    non_overridable: bool
    checks: Tuple[RiskCheckResult, ...]
    violated_rules: Tuple[str, ...]
    metrics: Dict[str, float]
    rationale: str

    def __post_init__(self) -> None:
        if self.verdict not in ALLOWED_VERDICTS:
            raise SchemaValidationError(f"Invalid risk verdict: {self.verdict}")
        if self.verdict == "VETO" and not self.non_overridable:
            raise SchemaValidationError("VETO verdicts must be marked non_overridable=True")

    def model_dump(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "policy_id": self.policy_id,
            "verdict": self.verdict,
            "non_overridable": self.non_overridable,
            "checks": [c.model_dump() for c in self.checks],
            "violated_rules": list(self.violated_rules),
            "metrics": dict(self.metrics),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class HumanApprovalRecord:
    approval_id: str
    proposal_id: str
    proposal_hash: str
    reviewer_id: str
    decision: str
    rationale: str
    approved_at: str

    @classmethod
    def model_validate(cls, data: Any, path: str = "human_approval") -> "HumanApprovalRecord":
        obj = _require_mapping(data, path)
        approval_id = _require_non_empty_str(obj, "approval_id", f"{path}.approval_id")
        proposal_id = _require_non_empty_str(obj, "proposal_id", f"{path}.proposal_id")
        proposal_hash = _require_non_empty_str(obj, "proposal_hash", f"{path}.proposal_hash")
        reviewer_id = _require_non_empty_str(obj, "reviewer_id", f"{path}.reviewer_id")
        decision = _require_non_empty_str(obj, "decision", f"{path}.decision").upper()
        if decision not in ALLOWED_HUMAN_DECISIONS:
            raise SchemaValidationError(
                f"Field '{path}.decision' must be one of {sorted(ALLOWED_HUMAN_DECISIONS)}",
                field_errors=[{"field": f"{path}.decision", "error": f"invalid decision: {decision}"}],
            )
        rationale = _require_non_empty_str(obj, "rationale", f"{path}.rationale")
        approved_at = _require_utc_timestamp(obj, "approved_at", f"{path}.approved_at")
        return cls(
            approval_id=approval_id,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            reviewer_id=reviewer_id,
            decision=decision,
            rationale=rationale,
            approved_at=approved_at,
        )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "reviewer_id": self.reviewer_id,
            "decision": self.decision,
            "rationale": self.rationale,
            "approved_at": self.approved_at,
        }


@dataclass(frozen=True)
class ToolCallTrace:
    role: str
    tool_name: str
    arguments: Dict[str, Any]
    status: str
    latency_ms: int
    tokens_used: int
    cost_usd: float

    def model_dump(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "status": self.status,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class AgentExecutionTrace:
    role: str
    allowed_tools: Tuple[str, ...]
    budget: AgentBudget
    tool_calls_used: int
    tokens_used: int
    latency_ms: int
    cost_usd: float
    tool_calls: Tuple[ToolCallTrace, ...]
    injection_attempts_flagged: Tuple[str, ...]

    def model_dump(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "allowed_tools": list(self.allowed_tools),
            "budget": self.budget.model_dump(),
            "tool_calls_used": self.tool_calls_used,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "cost_usd": round(self.cost_usd, 6),
            "tool_calls": [t.model_dump() for t in self.tool_calls],
            "injection_attempts_flagged": list(self.injection_attempts_flagged),
        }


@dataclass(frozen=True)
class DecisionRecord:
    schema_version: str
    decision_id: str
    proposal_id: str
    proposal_hash: str
    config_id: str
    config_hash: str
    seed: int
    status: str
    execution_capability: str
    thesis: ThesisRecord
    challenge: ChallengeRecord
    portfolio_review: PortfolioReviewRecord
    risk_verdict: RiskVerdictRecord
    human_approval: Optional[HumanApprovalRecord] = None
    notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in ALLOWED_DECISION_STATUSES:
            raise SchemaValidationError(f"Invalid decision status: {self.status}")
        if self.execution_capability != EXECUTION_CAPABILITY_NONE:
            raise NoExecutionCapabilityError(
                f"DecisionRecord execution_capability must always be '{EXECUTION_CAPABILITY_NONE}'"
            )

    def model_dump(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "config_id": self.config_id,
            "config_hash": self.config_hash,
            "seed": self.seed,
            "status": self.status,
            "execution_capability": self.execution_capability,
            "thesis": self.thesis.model_dump(),
            "challenge": self.challenge.model_dump(),
            "portfolio_review": self.portfolio_review.model_dump(),
            "risk_verdict": self.risk_verdict.model_dump(),
            "human_approval": self.human_approval.model_dump() if self.human_approval else None,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DeliberationReplayTrace:
    schema_version: str
    decision_id: str
    proposal_id: str
    proposal_hash: str
    config_hash: str
    seed: int
    created_at: str
    decision: DecisionRecord
    agent_traces: Tuple[AgentExecutionTrace, ...]
    total_tool_calls: int
    total_tokens: int
    total_latency_ms: int
    total_cost_usd: float
    runtime_metadata: Dict[str, Any]

    def model_dump(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "config_hash": self.config_hash,
            "seed": self.seed,
            "created_at": self.created_at,
            "decision": self.decision.model_dump(),
            "agent_traces": [t.model_dump() for t in self.agent_traces],
            "total_tool_calls": self.total_tool_calls,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "runtime_metadata": dict(self.runtime_metadata),
        }


@dataclass(frozen=True)
class EvaluationMetrics:
    decision_id: str
    proposal_id: str
    dissent_present: bool
    dissent_score: float
    total_claims: int
    verified_cited_claims: int
    uncertain_claims: int
    unsupported_claims: int
    fabricated_citations: int
    all_claims_cited_or_uncertain: bool
    prompt_injection_attempts_detected: int
    total_tool_calls: int
    total_tokens: int
    total_latency_ms: int
    total_cost_usd: float
    budget_utilization_pct: Dict[str, float]
    verdict: str
    status: str

    def model_dump(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "dissent_present": self.dissent_present,
            "dissent_score": round(self.dissent_score, 4),
            "total_claims": self.total_claims,
            "verified_cited_claims": self.verified_cited_claims,
            "uncertain_claims": self.uncertain_claims,
            "unsupported_claims": self.unsupported_claims,
            "fabricated_citations": self.fabricated_citations,
            "all_claims_cited_or_uncertain": self.all_claims_cited_or_uncertain,
            "prompt_injection_attempts_detected": self.prompt_injection_attempts_detected,
            "total_tool_calls": self.total_tool_calls,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "budget_utilization_pct": dict(self.budget_utilization_pct),
            "verdict": self.verdict,
            "status": self.status,
        }
