"""Typed data contracts, units, UTC timestamp validation, and deterministic hashing.

Every domain input and output crosses strict validation boundaries here.
Core runtime uses Python stdlib dataclasses + Decimal for offline determinism;
optional Pydantic v2 schema mirrors are available via `pydantic_adapter.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from .errors import SchemaValidationError, UnitMismatchError, UnsupportedInputError

SCHEMA_VERSION = "1.0.0"


class Unit(str, Enum):
    """Canonical measurement units with explicit periodicity semantics."""

    PERCENT_YOY = "percent_yoy"
    PERCENT_MOM = "percent_mom"
    PERCENT_QOQ_SAAR = "percent_qoq_saar"
    PERCENT_RATE = "percent_rate"
    BPS = "bps"
    THOUSANDS = "thousands"
    MILLIONS = "millions"
    INDEX_POINTS = "index_points"

    @classmethod
    def parse(cls, raw: Any) -> "Unit":
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str):
            raise UnsupportedInputError(
                f"Unit must be a string, got {type(raw).__name__}",
                details={"raw_unit": repr(raw)},
            )
        normalized = raw.strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {
            "%_yoy": cls.PERCENT_YOY,
            "pct_yoy": cls.PERCENT_YOY,
            "yoy_pct": cls.PERCENT_YOY,
            "percent_yoy": cls.PERCENT_YOY,
            "%_mom": cls.PERCENT_MOM,
            "pct_mom": cls.PERCENT_MOM,
            "mom_pct": cls.PERCENT_MOM,
            "percent_mom": cls.PERCENT_MOM,
            "%_qoq_saar": cls.PERCENT_QOQ_SAAR,
            "pct_qoq_saar": cls.PERCENT_QOQ_SAAR,
            "percent_qoq_saar": cls.PERCENT_QOQ_SAAR,
            "%": cls.PERCENT_RATE,
            "pct": cls.PERCENT_RATE,
            "percent": cls.PERCENT_RATE,
            "percent_rate": cls.PERCENT_RATE,
            "bps": cls.BPS,
            "basis_points": cls.BPS,
            "k": cls.THOUSANDS,
            "thousands": cls.THOUSANDS,
            "m": cls.MILLIONS,
            "millions": cls.MILLIONS,
            "index": cls.INDEX_POINTS,
            "index_points": cls.INDEX_POINTS,
        }
        if normalized in aliases:
            return aliases[normalized]
        raise UnsupportedInputError(
            f"Unsupported unit: '{raw}'",
            details={"raw_unit": raw, "supported_units": [u.value for u in cls]},
        )


# Explicit lossless conversion factors between compatible units only.
# Notice that YoY vs MoM vs QoQ SAAR are intentionally NOT convertible.
_UNIT_CONVERSION_FACTORS: Dict[Tuple[Unit, Unit], Decimal] = {
    (Unit.PERCENT_RATE, Unit.BPS): Decimal("100"),
    (Unit.BPS, Unit.PERCENT_RATE): Decimal("0.01"),
    (Unit.MILLIONS, Unit.THOUSANDS): Decimal("1000"),
    (Unit.THOUSANDS, Unit.MILLIONS): Decimal("0.001"),
}


def convert_unit(
    value: Decimal,
    from_unit: Unit,
    to_unit: Unit,
    *,
    allow_conversion: bool = True,
) -> Decimal:
    """Convert between explicitly compatible units or raise UnitMismatchError."""
    if from_unit == to_unit:
        return value
    if not allow_conversion:
        raise UnitMismatchError(
            f"Unit mismatch ({from_unit.value} vs {to_unit.value}) with auto-conversion disabled",
            details={"from_unit": from_unit.value, "to_unit": to_unit.value},
        )
    factor = _UNIT_CONVERSION_FACTORS.get((from_unit, to_unit))
    if factor is None:
        raise UnitMismatchError(
            f"Incompatible units cannot be converted: {from_unit.value} -> {to_unit.value}",
            details={"from_unit": from_unit.value, "to_unit": to_unit.value},
        )
    return value * factor


class DocumentType(str, Enum):
    ECONOMIC_RELEASE = "economic_release"
    CENTRAL_BANK_STATEMENT = "central_bank_statement"
    CENTRAL_BANK_MINUTES = "central_bank_minutes"
    CONSENSUS_SURVEY = "consensus_survey"
    PRESS_REPORT = "press_report"

    @classmethod
    def parse(cls, raw: Any) -> "DocumentType":
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str):
            raise UnsupportedInputError(
                f"DocumentType must be a string, got {type(raw).__name__}",
                details={"raw_document_type": repr(raw)},
            )
        try:
            return cls(raw.strip().lower())
        except ValueError as exc:
            raise UnsupportedInputError(
                f"Unsupported document_type: '{raw}'",
                details={
                    "raw_document_type": raw,
                    "supported_document_types": [d.value for d in cls],
                },
            ) from exc


class PolicyStance(str, Enum):
    HAWKISH = "hawkish"
    DOVISH = "dovish"
    NEUTRAL = "neutral"
    DATA_DEPENDENT = "data_dependent"


def parse_utc_timestamp(value: Any, field_name: str) -> datetime:
    """Parse an ISO-8601 timestamp and require explicit timezone information."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise SchemaValidationError(
                f"Field '{field_name}' cannot be empty",
                details={"field": field_name},
            )
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise SchemaValidationError(
                f"Field '{field_name}' is not a valid ISO-8601 timestamp: '{value}'",
                details={"field": field_name, "value": value},
            ) from exc
    else:
        raise SchemaValidationError(
            f"Field '{field_name}' must be an ISO-8601 string or datetime",
            details={"field": field_name, "type": type(value).__name__},
        )

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SchemaValidationError(
            f"Field '{field_name}' must include an explicit timezone offset (UTC recommended); naive timestamps are rejected",
            details={"field": field_name, "value": str(value)},
        )
    return dt.astimezone(timezone.utc)


def format_utc_timestamp(dt: datetime) -> str:
    """Render a timezone-aware datetime in canonical UTC ISO-8601 Z format."""
    utc_dt = parse_utc_timestamp(dt, "timestamp")
    return utc_dt.isoformat().replace("+00:00", "Z")


def parse_decimal(value: Any, field_name: str) -> Decimal:
    """Parse exact Decimal values while rejecting NaN, Inf, and booleans."""
    if isinstance(value, bool):
        raise SchemaValidationError(
            f"Field '{field_name}' cannot be boolean",
            details={"field": field_name, "value": value},
        )
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, (int, float, str)):
        try:
            dec = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise SchemaValidationError(
                f"Field '{field_name}' is not a valid decimal number: '{value}'",
                details={"field": field_name, "value": value},
            ) from exc
    else:
        raise SchemaValidationError(
            f"Field '{field_name}' must be numeric or numeric string",
            details={"field": field_name, "type": type(value).__name__},
        )
    if not dec.is_finite():
        raise SchemaValidationError(
            f"Field '{field_name}' must be a finite number",
            details={"field": field_name, "value": str(value)},
        )
    return dec


def canonical_json(obj: Any) -> str:
    """Serialize objects canonically for stable content-addressed identifiers."""

    def _default(item: Any) -> Any:
        if isinstance(item, Decimal):
            return format(item.normalize(), "f")
        if isinstance(item, datetime):
            return format_utc_timestamp(item)
        if isinstance(item, Enum):
            return item.value
        if hasattr(item, "to_dict"):
            return item.to_dict()
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default)


def stable_id(prefix: str, payload: Any, length: int = 16) -> str:
    """Generate a deterministic SHA-256 based identifier."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:length]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(
            f"Field '{field_name}' must be a non-empty string",
            details={"field": field_name},
        )
    return value.strip()


@dataclass(frozen=True)
class Citation:
    """Verifiable byte/character-span citation into an archived release vintage."""

    citation_id: str
    release_id: str
    vintage_id: str
    source_id: str
    published_at: datetime
    char_start: int
    char_end: int
    quote: str
    document_sha256: str

    def __post_init__(self) -> None:
        _require_non_empty_str(self.citation_id, "citation_id")
        _require_non_empty_str(self.release_id, "release_id")
        _require_non_empty_str(self.vintage_id, "vintage_id")
        _require_non_empty_str(self.source_id, "source_id")
        parse_utc_timestamp(self.published_at, "published_at")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise SchemaValidationError(
                "Citation span must satisfy 0 <= char_start < char_end",
                details={"char_start": self.char_start, "char_end": self.char_end},
            )
        if not self.quote:
            raise SchemaValidationError("Citation quote cannot be empty")
        _require_non_empty_str(self.document_sha256, "document_sha256")

    @classmethod
    def build(
        cls,
        *,
        release_id: str,
        vintage_id: str,
        source_id: str,
        published_at: datetime,
        char_start: int,
        char_end: int,
        quote: str,
        document_sha256: str,
    ) -> "Citation":
        pub_utc = parse_utc_timestamp(published_at, "published_at")
        cid = stable_id(
            "cit",
            {
                "release_id": release_id,
                "vintage_id": vintage_id,
                "source_id": source_id,
                "char_start": char_start,
                "char_end": char_end,
                "quote_sha256": sha256_text(quote),
                "document_sha256": document_sha256,
            },
        )
        return cls(
            citation_id=cid,
            release_id=release_id,
            vintage_id=vintage_id,
            source_id=source_id,
            published_at=pub_utc,
            char_start=char_start,
            char_end=char_end,
            quote=quote,
            document_sha256=document_sha256,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "release_id": self.release_id,
            "vintage_id": self.vintage_id,
            "source_id": self.source_id,
            "published_at": format_utc_timestamp(self.published_at),
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.quote,
            "document_sha256": self.document_sha256,
        }


@dataclass(frozen=True)
class MetricObservation:
    """Structured metric claim attached to a release (verified against raw_text if quote given)."""

    series_id: str
    reference_period: str
    value: Decimal
    unit: Unit
    quote: Optional[str] = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.series_id, "series_id")
        _require_non_empty_str(self.reference_period, "reference_period")
        parse_decimal(self.value, "value")
        Unit.parse(self.unit)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricObservation":
        if not isinstance(data, dict):
            raise SchemaValidationError("MetricObservation must be an object")
        return cls(
            series_id=_require_non_empty_str(data.get("series_id"), "series_id"),
            reference_period=_require_non_empty_str(
                data.get("reference_period"), "reference_period"
            ),
            value=parse_decimal(data.get("value"), "value"),
            unit=Unit.parse(data.get("unit")),
            quote=data.get("quote"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "reference_period": self.reference_period,
            "value": format(self.value, "f"),
            "unit": self.unit.value,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class ConsensusEstimate:
    """Pre-release consensus benchmark with its own publication gate timestamp."""

    consensus_id: str
    series_id: str
    reference_period: str
    expected_value: Decimal
    unit: Unit
    published_at: datetime
    source_id: str
    contributor_count: Optional[int] = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.consensus_id, "consensus_id")
        _require_non_empty_str(self.series_id, "series_id")
        _require_non_empty_str(self.reference_period, "reference_period")
        parse_decimal(self.expected_value, "expected_value")
        Unit.parse(self.unit)
        parse_utc_timestamp(self.published_at, "published_at")
        _require_non_empty_str(self.source_id, "source_id")
        if self.contributor_count is not None and self.contributor_count < 1:
            raise SchemaValidationError(
                "contributor_count must be >= 1 when provided",
                details={"contributor_count": self.contributor_count},
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsensusEstimate":
        if not isinstance(data, dict):
            raise SchemaValidationError("ConsensusEstimate must be an object")
        return cls(
            consensus_id=_require_non_empty_str(data.get("consensus_id"), "consensus_id"),
            series_id=_require_non_empty_str(data.get("series_id"), "series_id"),
            reference_period=_require_non_empty_str(
                data.get("reference_period"), "reference_period"
            ),
            expected_value=parse_decimal(data.get("expected_value"), "expected_value"),
            unit=Unit.parse(data.get("unit")),
            published_at=parse_utc_timestamp(data.get("published_at"), "published_at"),
            source_id=_require_non_empty_str(data.get("source_id"), "source_id"),
            contributor_count=data.get("contributor_count"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consensus_id": self.consensus_id,
            "series_id": self.series_id,
            "reference_period": self.reference_period,
            "expected_value": format(self.expected_value, "f"),
            "unit": self.unit.value,
            "published_at": format_utc_timestamp(self.published_at),
            "source_id": self.source_id,
            "contributor_count": self.contributor_count,
        }


@dataclass(frozen=True)
class MacroRelease:
    """Canonical archived release or central bank communication vintage."""

    release_id: str
    vintage_id: str
    vintage_sequence: int
    series_group: str
    reference_period: str
    document_type: DocumentType
    source_id: str
    source_name: str
    title: str
    published_at: datetime
    raw_text: str
    embargo_until: Optional[datetime] = None
    ingested_at: Optional[datetime] = None
    reported_metrics: Tuple[MetricObservation, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.release_id, "release_id")
        _require_non_empty_str(self.vintage_id, "vintage_id")
        if not isinstance(self.vintage_sequence, int) or self.vintage_sequence < 1:
            raise SchemaValidationError(
                "vintage_sequence must be an integer >= 1",
                details={"vintage_sequence": self.vintage_sequence},
            )
        _require_non_empty_str(self.series_group, "series_group")
        _require_non_empty_str(self.reference_period, "reference_period")
        DocumentType.parse(self.document_type)
        _require_non_empty_str(self.source_id, "source_id")
        _require_non_empty_str(self.source_name, "source_name")
        _require_non_empty_str(self.title, "title")
        parse_utc_timestamp(self.published_at, "published_at")
        if not isinstance(self.raw_text, str) or not self.raw_text.strip():
            raise SchemaValidationError(
                "Field 'raw_text' must be a non-empty string",
                details={"field": "raw_text"},
            )
        if self.embargo_until is not None:
            parse_utc_timestamp(self.embargo_until, "embargo_until")
        if self.ingested_at is not None:
            parse_utc_timestamp(self.ingested_at, "ingested_at")

    @property
    def available_at(self) -> datetime:
        """Effective publication gate timestamp: max(published_at, embargo_until)."""
        pub = parse_utc_timestamp(self.published_at, "published_at")
        if self.embargo_until is None:
            return pub
        emb = parse_utc_timestamp(self.embargo_until, "embargo_until")
        return emb if emb > pub else pub

    @property
    def document_sha256(self) -> str:
        return sha256_text(self.raw_text)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MacroRelease":
        if not isinstance(data, dict):
            raise SchemaValidationError("MacroRelease must be an object")
        raw_metrics = data.get("reported_metrics", [])
        if not isinstance(raw_metrics, list):
            raise SchemaValidationError("reported_metrics must be a list")
        metrics = tuple(MetricObservation.from_dict(m) for m in raw_metrics)
        embargo = (
            parse_utc_timestamp(data["embargo_until"], "embargo_until")
            if data.get("embargo_until") is not None
            else None
        )
        ingested = (
            parse_utc_timestamp(data["ingested_at"], "ingested_at")
            if data.get("ingested_at") is not None
            else None
        )
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise SchemaValidationError("metadata must be a dict")
        return cls(
            release_id=_require_non_empty_str(data.get("release_id"), "release_id"),
            vintage_id=_require_non_empty_str(data.get("vintage_id"), "vintage_id"),
            vintage_sequence=int(data.get("vintage_sequence", 0)),
            series_group=_require_non_empty_str(data.get("series_group"), "series_group"),
            reference_period=_require_non_empty_str(
                data.get("reference_period"), "reference_period"
            ),
            document_type=DocumentType.parse(data.get("document_type")),
            source_id=_require_non_empty_str(data.get("source_id"), "source_id"),
            source_name=_require_non_empty_str(data.get("source_name"), "source_name"),
            title=_require_non_empty_str(data.get("title"), "title"),
            published_at=parse_utc_timestamp(data.get("published_at"), "published_at"),
            raw_text=str(data.get("raw_text", "")),
            embargo_until=embargo,
            ingested_at=ingested,
            reported_metrics=metrics,
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "release_id": self.release_id,
            "vintage_id": self.vintage_id,
            "vintage_sequence": self.vintage_sequence,
            "series_group": self.series_group,
            "reference_period": self.reference_period,
            "document_type": self.document_type.value,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "title": self.title,
            "published_at": format_utc_timestamp(self.published_at),
            "embargo_until": (
                format_utc_timestamp(self.embargo_until)
                if self.embargo_until is not None
                else None
            ),
            "available_at": format_utc_timestamp(self.available_at),
            "ingested_at": (
                format_utc_timestamp(self.ingested_at)
                if self.ingested_at is not None
                else None
            ),
            "raw_text": self.raw_text,
            "document_sha256": self.document_sha256,
            "reported_metrics": [m.to_dict() for m in self.reported_metrics],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ExtractedFigure:
    """A figure extracted from a release with mandatory verifiable citation."""

    figure_id: str
    series_id: str
    reference_period: str
    value: Decimal
    unit: Unit
    release_id: str
    vintage_id: str
    source_id: str
    published_at: datetime
    citation: Citation
    extraction_method: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "series_id": self.series_id,
            "reference_period": self.reference_period,
            "value": format(self.value, "f"),
            "unit": self.unit.value,
            "release_id": self.release_id,
            "vintage_id": self.vintage_id,
            "source_id": self.source_id,
            "published_at": format_utc_timestamp(self.published_at),
            "citation": self.citation.to_dict(),
            "extraction_method": self.extraction_method,
        }


@dataclass(frozen=True)
class SurpriseCalculation:
    """Actual vs pre-release consensus surprise with unit provenance."""

    surprise_id: str
    series_id: str
    reference_period: str
    actual_value: Decimal
    consensus_value: Decimal
    surprise_value: Decimal
    unit: Unit
    direction: str  # "above_consensus" | "below_consensus" | "in_line"
    actual_figure_id: str
    consensus_id: str
    converted_from_unit: Optional[Unit] = None
    citation: Optional[Citation] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surprise_id": self.surprise_id,
            "series_id": self.series_id,
            "reference_period": self.reference_period,
            "actual_value": format(self.actual_value, "f"),
            "consensus_value": format(self.consensus_value, "f"),
            "surprise_value": format(self.surprise_value, "f"),
            "unit": self.unit.value,
            "direction": self.direction,
            "actual_figure_id": self.actual_figure_id,
            "consensus_id": self.consensus_id,
            "converted_from_unit": (
                self.converted_from_unit.value if self.converted_from_unit else None
            ),
            "citation": self.citation.to_dict() if self.citation else None,
        }


@dataclass(frozen=True)
class PolicyLanguageSignal:
    """Extracted central bank policy communication cue with exact citation."""

    signal_id: str
    stance: PolicyStance
    matched_phrase: str
    topic: str
    release_id: str
    vintage_id: str
    citation: Citation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "stance": self.stance.value,
            "matched_phrase": self.matched_phrase,
            "topic": self.topic,
            "release_id": self.release_id,
            "vintage_id": self.vintage_id,
            "citation": self.citation.to_dict(),
        }


@dataclass(frozen=True)
class RevisionDiff:
    """Comparison between a prior vintage and a newer vintage for the same series & period."""

    revision_id: str
    series_id: str
    reference_period: str
    prior_vintage_id: str
    current_vintage_id: str
    prior_value: Decimal
    current_value: Decimal
    delta: Decimal
    unit: Unit
    direction: str  # "upward_revision" | "downward_revision" | "unchanged"
    prior_citation: Citation
    current_citation: Citation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "series_id": self.series_id,
            "reference_period": self.reference_period,
            "prior_vintage_id": self.prior_vintage_id,
            "current_vintage_id": self.current_vintage_id,
            "prior_value": format(self.prior_value, "f"),
            "current_value": format(self.current_value, "f"),
            "delta": format(self.delta, "f"),
            "unit": self.unit.value,
            "direction": self.direction,
            "prior_citation": self.prior_citation.to_dict(),
            "current_citation": self.current_citation.to_dict(),
        }


@dataclass(frozen=True)
class ConflictRecord:
    """Recorded discrepancy across reports or incompatible unit comparison."""

    conflict_id: str
    conflict_type: str  # "conflicting_reports" | "unit_mismatch"
    series_id: str
    reference_period: str
    description: str
    involved_release_ids: Tuple[str, ...]
    involved_values: Tuple[str, ...]
    citations: Tuple[Citation, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "conflict_type": self.conflict_type,
            "series_id": self.series_id,
            "reference_period": self.reference_period,
            "description": self.description,
            "involved_release_ids": list(self.involved_release_ids),
            "involved_values": list(self.involved_values),
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass(frozen=True)
class AbstentionRecord:
    """Explicit abstention when data is missing, conflicting, or unit-incompatible."""

    abstention_id: str
    scope: str  # e.g. "surprise:US_CPI_HEADLINE:2025-03" or "metric:US_NFP:2025-03"
    reason_code: str
    explanation: str
    related_conflict_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "abstention_id": self.abstention_id,
            "scope": self.scope,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "related_conflict_id": self.related_conflict_id,
        }


@dataclass(frozen=True)
class UntrustedInstructionFinding:
    """Detected prompt-injection or override directive in untrusted retrieved text."""

    finding_id: str
    release_id: str
    vintage_id: str
    rule_id: str
    matched_text: str
    char_start: int
    char_end: int
    action_taken: str  # "quarantined" | "rejected"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "release_id": self.release_id,
            "vintage_id": self.vintage_id,
            "rule_id": self.rule_id,
            "matched_text": self.matched_text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "action_taken": self.action_taken,
        }


@dataclass(frozen=True)
class ScenarioHypothesis:
    """Hypothesis-framed scenario statement (explicitly NOT a prediction or trade advice)."""

    hypothesis_id: str
    label: str
    condition: str
    interpretation: str
    confidence_note: str
    supporting_citation_ids: Tuple[str, ...]
    disclaimer: str = "Hypothesis only; not a forecast, market-impact estimate, or trade recommendation."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "label": self.label,
            "condition": self.condition,
            "interpretation": self.interpretation,
            "confidence_note": self.confidence_note,
            "supporting_citation_ids": list(self.supporting_citation_ids),
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True)
class ScenarioBrief:
    """Final verified macro intelligence brief."""

    brief_id: str
    as_of_utc: datetime
    series_group: str
    executive_summary: str
    figures: Tuple[ExtractedFigure, ...]
    surprises: Tuple[SurpriseCalculation, ...]
    revisions: Tuple[RevisionDiff, ...]
    policy_signals: Tuple[PolicyLanguageSignal, ...]
    conflicts: Tuple[ConflictRecord, ...]
    abstentions: Tuple[AbstentionRecord, ...]
    security_findings: Tuple[UntrustedInstructionFinding, ...]
    scenarios: Tuple[ScenarioHypothesis, ...]
    citations_index: Dict[str, Citation]
    verification_passed: bool
    limitations_notice: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brief_id": self.brief_id,
            "as_of_utc": format_utc_timestamp(self.as_of_utc),
            "series_group": self.series_group,
            "executive_summary": self.executive_summary,
            "figures": [f.to_dict() for f in self.figures],
            "surprises": [s.to_dict() for s in self.surprises],
            "revisions": [r.to_dict() for r in self.revisions],
            "policy_signals": [p.to_dict() for p in self.policy_signals],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "abstentions": [a.to_dict() for a in self.abstentions],
            "security_findings": [f.to_dict() for f in self.security_findings],
            "scenarios": [s.to_dict() for s in self.scenarios],
            "citations_index": {k: v.to_dict() for k, v in sorted(self.citations_index.items())},
            "verification_passed": self.verification_passed,
            "limitations_notice": self.limitations_notice,
        }


@dataclass(frozen=True)
class RunDiagnostics:
    """Structured diagnostic counters and event log for observability."""

    counters: Dict[str, int]
    events: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counters": dict(sorted(self.counters.items())),
            "events": list(self.events),
        }


@dataclass(frozen=True)
class RunMetadata:
    """Reproducibility and provenance metadata for a run."""

    run_id: str
    schema_version: str
    config_version: str
    config_sha256: str
    input_sha256: str
    seed: int
    as_of_utc: datetime
    python_version: str
    model_provider: str
    model_calls_used: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "config_version": self.config_version,
            "config_sha256": self.config_sha256,
            "input_sha256": self.input_sha256,
            "seed": self.seed,
            "as_of_utc": format_utc_timestamp(self.as_of_utc),
            "python_version": self.python_version,
            "model_provider": self.model_provider,
            "model_calls_used": self.model_calls_used,
        }


@dataclass(frozen=True)
class AgentRunResult:
    """Top-level versioned output envelope."""

    metadata: RunMetadata
    brief: ScenarioBrief
    diagnostics: RunDiagnostics

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "brief": self.brief.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
        }
