"""Canonical typed data contracts, validation rules, and error hierarchy.

All inputs, intermediate domain artifacts, and final outputs pass through strict
validation defined here so downstream stages never silently accept malformed data.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

INPUT_SCHEMA_VERSION = "1.0.0"
OUTPUT_SCHEMA_VERSION = "1.0.0"
CONFIG_SCHEMA_VERSION = "1.0.0"

SUPPORTED_INPUT_SCHEMAS = frozenset({INPUT_SCHEMA_VERSION})
SUPPORTED_CONFIG_SCHEMAS = frozenset({CONFIG_SCHEMA_VERSION})


class EarningsCallAgentError(Exception):
    """Base error with machine-readable code and structured details."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: Dict[str, Any] = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class SchemaValidationError(EarningsCallAgentError):
    """Raised when an input document or record violates the canonical schema."""


class ConfigurationError(EarningsCallAgentError):
    """Raised when configuration is missing, malformed, or violates safety policy."""


class BudgetExceededError(EarningsCallAgentError):
    """Raised when execution exceeds a fixed deterministic resource budget."""


class UnsupportedInputError(EarningsCallAgentError):
    """Raised when an input uses an unsupported currency, language, unit, or schema."""


class EvidenceVerificationError(EarningsCallAgentError):
    """Raised when an evidence span fails verbatim span verification."""


class SpeakerRole(str, Enum):
    CEO = "CEO"
    CFO = "CFO"
    COO = "COO"
    IR = "IR"
    EXECUTIVE = "EXECUTIVE"
    ANALYST = "ANALYST"
    OPERATOR = "OPERATOR"
    UNKNOWN = "UNKNOWN"


class TranscriptSection(str, Enum):
    PREPARED_REMARKS = "PREPARED_REMARKS"
    QA = "QA"
    OPERATOR_INTRO = "OPERATOR_INTRO"
    UNKNOWN = "UNKNOWN"


class CanonicalUnit(str, Enum):
    USD_MILLIONS = "USD_MILLIONS"
    USD_PER_SHARE = "USD_PER_SHARE"
    PERCENT = "PERCENT"
    BPS = "BPS"
    COUNT = "COUNT"
    RATIO = "RATIO"


class AccountingBasis(str, Enum):
    GAAP = "GAAP"
    NON_GAAP = "NON_GAAP"
    UNSPECIFIED = "UNSPECIFIED"


class ClaimType(str, Enum):
    REPORTED_METRIC = "REPORTED_METRIC"
    FORWARD_GUIDANCE = "FORWARD_GUIDANCE"


class GuidanceDirection(str, Enum):
    RAISED = "RAISED"
    LOWERED = "LOWERED"
    REAFFIRMED = "REAFFIRMED"
    NARROWED = "NARROWED"
    WIDENED = "WIDENED"
    INTRODUCED = "INTRODUCED"
    CONTRADICTORY = "CONTRADICTORY"
    UNAVAILABLE = "UNAVAILABLE"


class UncertaintyLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AbstentionReason(str, Enum):
    NO_SUPPORTING_EVIDENCE = "NO_SUPPORTING_EVIDENCE"
    STALE_SOURCE = "STALE_SOURCE"
    PROMPT_INJECTION_QUARANTINED = "PROMPT_INJECTION_QUARANTINED"
    AMBIGUOUS_OR_CONTRADICTORY = "AMBIGUOUS_OR_CONTRADICTORY"
    UNSUPPORTED_METRIC_OR_PERIOD = "UNSUPPORTED_METRIC_OR_PERIOD"


class InjectionSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def canonical_json(obj: Any) -> str:
    """Serialize data deterministically for hashing and reproducible outputs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_id(prefix: str, parts: Sequence[Any], length: int = 12) -> str:
    """Create a deterministic identifier from stable domain fields."""
    payload = canonical_json(list(parts)).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:length]
    return f"{prefix}_{digest}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_utc_timestamp(value: Any, field_name: str) -> datetime:
    """Parse an ISO-8601 timestamp with explicit timezone and normalize to UTC."""
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(
            "INVALID_TIMESTAMP",
            f"Field '{field_name}' must be a non-empty ISO-8601 timestamp string.",
            {"field": field_name, "value": value},
        )
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SchemaValidationError(
            "INVALID_TIMESTAMP",
            f"Field '{field_name}' is not a valid ISO-8601 timestamp: {value!r}",
            {"field": field_name, "value": value},
        ) from exc
    if dt.tzinfo is None:
        raise SchemaValidationError(
            "NAIVE_TIMESTAMP",
            f"Field '{field_name}' must include an explicit UTC or timezone offset.",
            {"field": field_name, "value": value},
        )
    return dt.astimezone(timezone.utc)


def format_utc_timestamp(dt: datetime) -> str:
    """Format a timezone-aware datetime as canonical ISO-8601 UTC with Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_FISCAL_PERIOD_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    # Q1 FY2026, Q1 2026, Q1_2026, 1Q26, first quarter 2026
    (re.compile(r"^(?:Q([1-4]))[\s_-]*(?:FY)?(20\d{2})$", re.IGNORECASE), "Q_FULL"),
    (re.compile(r"^([1-4])Q[\s_-]*(?:FY)?(\d{2})$", re.IGNORECASE), "Q_SHORT"),
    (re.compile(r"^FY[\s_-]*(20\d{2})$", re.IGNORECASE), "FY_FULL"),
    (re.compile(r"^FY[\s_-]*(\d{2})$", re.IGNORECASE), "FY_SHORT"),
    (re.compile(r"^CY[\s_-]*(20\d{2})$", re.IGNORECASE), "CY_FULL"),
    (re.compile(r"^H([12])[\s_-]*(?:FY)?(20\d{2})$", re.IGNORECASE), "H_FULL"),
)


def normalize_fiscal_period(raw_period: str) -> str:
    """Normalize a fiscal period string to canonical form (e.g., Q4_FY2025, FY2026, CY2026)."""
    if not isinstance(raw_period, str) or not raw_period.strip():
        raise SchemaValidationError(
            "INVALID_FISCAL_PERIOD",
            "Fiscal period must be a non-empty string.",
            {"value": raw_period},
        )
    cleaned = raw_period.strip().replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    for pattern, kind in _FISCAL_PERIOD_PATTERNS:
        m = pattern.match(cleaned)
        if not m:
            continue
        if kind == "Q_FULL":
            return f"Q{m.group(1)}_FY{m.group(2)}"
        if kind == "Q_SHORT":
            return f"Q{m.group(1)}_FY20{m.group(2)}"
        if kind == "FY_FULL":
            return f"FY{m.group(1)}"
        if kind == "FY_SHORT":
            return f"FY20{m.group(1)}"
        if kind == "CY_FULL":
            return f"CY{m.group(1)}"
        if kind == "H_FULL":
            return f"H{m.group(1)}_FY{m.group(2)}"
    raise UnsupportedInputError(
        "UNSUPPORTED_FISCAL_PERIOD",
        f"Unsupported fiscal period format: {raw_period!r}",
        {"value": raw_period},
    )


_UNIT_SCALE_MAP: Dict[str, Tuple[CanonicalUnit, float]] = {
    "usd_billions": (CanonicalUnit.USD_MILLIONS, 1000.0),
    "billion": (CanonicalUnit.USD_MILLIONS, 1000.0),
    "billions": (CanonicalUnit.USD_MILLIONS, 1000.0),
    "b": (CanonicalUnit.USD_MILLIONS, 1000.0),
    "bn": (CanonicalUnit.USD_MILLIONS, 1000.0),
    "usd_millions": (CanonicalUnit.USD_MILLIONS, 1.0),
    "million": (CanonicalUnit.USD_MILLIONS, 1.0),
    "millions": (CanonicalUnit.USD_MILLIONS, 1.0),
    "m": (CanonicalUnit.USD_MILLIONS, 1.0),
    "mm": (CanonicalUnit.USD_MILLIONS, 1.0),
    "usd_thousands": (CanonicalUnit.USD_MILLIONS, 0.001),
    "thousand": (CanonicalUnit.USD_MILLIONS, 0.001),
    "thousands": (CanonicalUnit.USD_MILLIONS, 0.001),
    "k": (CanonicalUnit.USD_MILLIONS, 0.001),
    "usd": (CanonicalUnit.USD_MILLIONS, 1e-6),
    "usd_per_share": (CanonicalUnit.USD_PER_SHARE, 1.0),
    "per_share": (CanonicalUnit.USD_PER_SHARE, 1.0),
    "eps": (CanonicalUnit.USD_PER_SHARE, 1.0),
    "percent": (CanonicalUnit.PERCENT, 1.0),
    "percentage": (CanonicalUnit.PERCENT, 1.0),
    "%": (CanonicalUnit.PERCENT, 1.0),
    "pct": (CanonicalUnit.PERCENT, 1.0),
    "bps": (CanonicalUnit.BPS, 1.0),
    "basis_points": (CanonicalUnit.BPS, 1.0),
    "basis points": (CanonicalUnit.BPS, 1.0),
    "count": (CanonicalUnit.COUNT, 1.0),
    "customers": (CanonicalUnit.COUNT, 1.0),
    "ratio": (CanonicalUnit.RATIO, 1.0),
    "x": (CanonicalUnit.RATIO, 1.0),
}


def normalize_unit_and_value(raw_unit: str, value: float) -> Tuple[CanonicalUnit, float]:
    """Normalize a raw unit string and numeric value into canonical units."""
    if not isinstance(raw_unit, str) or not raw_unit.strip():
        raise SchemaValidationError(
            "INVALID_UNIT",
            "Unit must be a non-empty string.",
            {"raw_unit": raw_unit},
        )
    key = raw_unit.strip().lower().replace("-", "_")
    if key not in _UNIT_SCALE_MAP:
        raise UnsupportedInputError(
            "UNSUPPORTED_UNIT",
            f"Unsupported unit: {raw_unit!r}",
            {"raw_unit": raw_unit, "supported_units": sorted(_UNIT_SCALE_MAP.keys())},
        )
    canonical_unit, factor = _UNIT_SCALE_MAP[key]
    return canonical_unit, round(float(value) * factor, 6)


def _require_non_empty_str(data: Dict[str, Any], key: str, context: str) -> str:
    val = data.get(key)
    if not isinstance(val, str) or not val.strip():
        raise SchemaValidationError(
            "MISSING_OR_INVALID_FIELD",
            f"{context}: field '{key}' must be a non-empty string.",
            {"context": context, "field": key, "value": val},
        )
    return val.strip()


def _parse_enum(enum_cls: Any, value: Any, field_name: str, default: Optional[Any] = None) -> Any:
    if value is None and default is not None:
        return default
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return enum_cls(normalized)
        except ValueError:
            pass
    raise SchemaValidationError(
        "INVALID_ENUM",
        f"Field '{field_name}' has invalid value {value!r}; expected one of {[e.value for e in enum_cls]}.",
        {"field": field_name, "value": value},
    )


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    speaker: str
    speaker_role: SpeakerRole
    section: TranscriptSection
    text: str
    start_offset_sec: float
    end_offset_sec: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any], index: int = 0) -> "TranscriptSegment":
        if not isinstance(data, dict):
            raise SchemaValidationError(
                "INVALID_SEGMENT",
                f"Segment at index {index} must be a JSON object.",
                {"index": index},
            )
        seg_id = _require_non_empty_str(data, "segment_id", f"segment[{index}]")
        speaker = _require_non_empty_str(data, "speaker", f"segment[{seg_id}]")
        role = _parse_enum(SpeakerRole, data.get("speaker_role", "UNKNOWN"), "speaker_role")
        section = _parse_enum(
            TranscriptSection, data.get("section", "UNKNOWN"), "section"
        )
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SchemaValidationError(
                "EMPTY_SEGMENT_TEXT",
                f"Segment '{seg_id}' text must be a non-empty string.",
                {"segment_id": seg_id},
            )
        start = data.get("start_offset_sec", 0.0)
        end = data.get("end_offset_sec", start)
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise SchemaValidationError(
                "INVALID_SEGMENT_TIMING",
                f"Segment '{seg_id}' timing offsets must be numeric.",
                {"segment_id": seg_id, "start_offset_sec": start, "end_offset_sec": end},
            )
        if start < 0 or end < start:
            raise SchemaValidationError(
                "INVALID_SEGMENT_TIMING",
                f"Segment '{seg_id}' has invalid timing range [{start}, {end}].",
                {"segment_id": seg_id, "start_offset_sec": start, "end_offset_sec": end},
            )
        return cls(
            segment_id=seg_id,
            speaker=speaker,
            speaker_role=role,
            section=section,
            text=text,
            start_offset_sec=float(start),
            end_offset_sec=float(end),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "speaker": self.speaker,
            "speaker_role": self.speaker_role.value,
            "section": self.section.value,
            "text": self.text,
            "start_offset_sec": self.start_offset_sec,
            "end_offset_sec": self.end_offset_sec,
        }


@dataclass(frozen=True)
class PriorGuidanceRecord:
    guidance_id: str
    metric_name: str
    fiscal_period: str
    accounting_basis: AccountingBasis
    raw_unit: str
    normalized_unit: CanonicalUnit
    normalized_low: float
    normalized_high: float
    normalized_midpoint: float
    source_ref: str
    published_at: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any], index: int = 0) -> "PriorGuidanceRecord":
        if not isinstance(data, dict):
            raise SchemaValidationError(
                "INVALID_PRIOR_GUIDANCE",
                f"prior_guidance[{index}] must be a JSON object.",
                {"index": index},
            )
        gid = _require_non_empty_str(data, "guidance_id", f"prior_guidance[{index}]")
        metric = _require_non_empty_str(data, "metric_name", f"prior_guidance[{gid}]").lower()
        period = normalize_fiscal_period(
            _require_non_empty_str(data, "fiscal_period", f"prior_guidance[{gid}]")
        )
        basis = _parse_enum(
            AccountingBasis,
            data.get("accounting_basis", "UNSPECIFIED"),
            "accounting_basis",
        )
        raw_unit = _require_non_empty_str(data, "unit", f"prior_guidance[{gid}]")
        point = data.get("point_value")
        low = data.get("value_low")
        high = data.get("value_high")
        if point is not None:
            if not isinstance(point, (int, float)):
                raise SchemaValidationError(
                    "INVALID_NUMERIC_VALUE",
                    f"prior_guidance[{gid}].point_value must be numeric.",
                    {"guidance_id": gid},
                )
            low = float(point) if low is None else float(low)
            high = float(point) if high is None else float(high)
        if low is None or high is None:
            raise SchemaValidationError(
                "MISSING_GUIDANCE_VALUE",
                f"prior_guidance[{gid}] requires point_value or both value_low and value_high.",
                {"guidance_id": gid},
            )
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            raise SchemaValidationError(
                "INVALID_NUMERIC_VALUE",
                f"prior_guidance[{gid}] bounds must be numeric.",
                {"guidance_id": gid},
            )
        if float(low) > float(high):
            raise SchemaValidationError(
                "REVERSED_RANGE",
                f"prior_guidance[{gid}] has value_low ({low}) > value_high ({high}).",
                {"guidance_id": gid, "value_low": low, "value_high": high},
            )
        norm_unit, norm_low = normalize_unit_and_value(raw_unit, float(low))
        _, norm_high = normalize_unit_and_value(raw_unit, float(high))
        midpoint = round((norm_low + norm_high) / 2.0, 6)
        source_ref = _require_non_empty_str(data, "source_ref", f"prior_guidance[{gid}]")
        published_at = parse_utc_timestamp(data.get("published_at"), f"prior_guidance[{gid}].published_at")
        return cls(
            guidance_id=gid,
            metric_name=metric,
            fiscal_period=period,
            accounting_basis=basis,
            raw_unit=raw_unit,
            normalized_unit=norm_unit,
            normalized_low=norm_low,
            normalized_high=norm_high,
            normalized_midpoint=midpoint,
            source_ref=source_ref,
            published_at=published_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guidance_id": self.guidance_id,
            "metric_name": self.metric_name,
            "fiscal_period": self.fiscal_period,
            "accounting_basis": self.accounting_basis.value,
            "raw_unit": self.raw_unit,
            "normalized_unit": self.normalized_unit.value,
            "normalized_low": self.normalized_low,
            "normalized_high": self.normalized_high,
            "normalized_midpoint": self.normalized_midpoint,
            "source_ref": self.source_ref,
            "published_at": format_utc_timestamp(self.published_at),
        }


@dataclass(frozen=True)
class QuestionRequest:
    question_id: str
    question: str
    metric_hint: Optional[str] = None
    fiscal_period_hint: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], index: int = 0) -> "QuestionRequest":
        if not isinstance(data, dict):
            raise SchemaValidationError(
                "INVALID_QUESTION",
                f"questions[{index}] must be a JSON object.",
                {"index": index},
            )
        qid = _require_non_empty_str(data, "question_id", f"questions[{index}]")
        qtext = _require_non_empty_str(data, "question", f"questions[{qid}]")
        metric_hint = data.get("metric_hint")
        if metric_hint is not None:
            if not isinstance(metric_hint, str) or not metric_hint.strip():
                raise SchemaValidationError(
                    "INVALID_METRIC_HINT",
                    f"questions[{qid}].metric_hint must be a non-empty string if provided.",
                    {"question_id": qid},
                )
            metric_hint = metric_hint.strip().lower()
        period_hint = data.get("fiscal_period_hint")
        if period_hint is not None:
            period_hint = normalize_fiscal_period(period_hint)
        return cls(
            question_id=qid,
            question=qtext,
            metric_hint=metric_hint,
            fiscal_period_hint=period_hint,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "metric_hint": self.metric_hint,
            "fiscal_period_hint": self.fiscal_period_hint,
        }


@dataclass(frozen=True)
class TranscriptInput:
    schema_version: str
    transcript_id: str
    ticker: str
    company_name: str
    fiscal_period: str
    call_timestamp: datetime
    published_at: datetime
    filing_timestamp: datetime
    currency: str
    language: str
    source_name: str
    source_license: str
    segments: Tuple[TranscriptSegment, ...]
    prior_guidance: Tuple[PriorGuidanceRecord, ...] = field(default_factory=tuple)
    questions: Tuple[QuestionRequest, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        supported_currencies: Sequence[str] = ("USD",),
        supported_languages: Sequence[str] = ("en",),
        max_segments: int = 500,
    ) -> "TranscriptInput":
        if not isinstance(data, dict):
            raise SchemaValidationError(
                "INVALID_ROOT",
                "Transcript input must be a JSON object.",
            )
        schema_version = _require_non_empty_str(data, "schema_version", "root")
        if schema_version not in SUPPORTED_INPUT_SCHEMAS:
            raise UnsupportedInputError(
                "UNSUPPORTED_SCHEMA_VERSION",
                f"Unsupported input schema_version {schema_version!r}; supported: {sorted(SUPPORTED_INPUT_SCHEMAS)}.",
                {"schema_version": schema_version},
            )
        transcript_id = _require_non_empty_str(data, "transcript_id", "root")
        ticker = _require_non_empty_str(data, "ticker", "root").upper()
        company_name = _require_non_empty_str(data, "company_name", "root")
        fiscal_period = normalize_fiscal_period(_require_non_empty_str(data, "fiscal_period", "root"))
        call_ts = parse_utc_timestamp(data.get("call_timestamp"), "call_timestamp")
        pub_ts = parse_utc_timestamp(data.get("published_at"), "published_at")
        filing_ts = parse_utc_timestamp(data.get("filing_timestamp"), "filing_timestamp")
        if pub_ts < call_ts:
            raise SchemaValidationError(
                "INCONSISTENT_TIMESTAMPS",
                "published_at cannot precede call_timestamp.",
                {
                    "call_timestamp": format_utc_timestamp(call_ts),
                    "published_at": format_utc_timestamp(pub_ts),
                },
            )
        currency = _require_non_empty_str(data, "currency", "root").upper()
        if currency not in {c.upper() for c in supported_currencies}:
            raise UnsupportedInputError(
                "UNSUPPORTED_CURRENCY",
                f"Currency {currency!r} is not supported; supported: {list(supported_currencies)}.",
                {"currency": currency},
            )
        language = _require_non_empty_str(data, "language", "root").lower()
        if language not in {lang.lower() for lang in supported_languages}:
            raise UnsupportedInputError(
                "UNSUPPORTED_LANGUAGE",
                f"Language {language!r} is not supported; supported: {list(supported_languages)}.",
                {"language": language},
            )
        source_name = _require_non_empty_str(data, "source_name", "root")
        source_license = _require_non_empty_str(data, "source_license", "root")

        raw_segments = data.get("segments")
        if not isinstance(raw_segments, list) or len(raw_segments) == 0:
            raise SchemaValidationError(
                "EMPTY_SEGMENTS",
                "Transcript must contain at least one segment.",
            )
        if len(raw_segments) > max_segments:
            raise BudgetExceededError(
                "SEGMENT_BUDGET_EXCEEDED",
                f"Segment count {len(raw_segments)} exceeds configured max_segments ({max_segments}).",
                {"segment_count": len(raw_segments), "max_segments": max_segments},
            )
        segments: List[TranscriptSegment] = []
        seen_ids = set()
        for idx, seg_raw in enumerate(raw_segments):
            seg = TranscriptSegment.from_dict(seg_raw, idx)
            if seg.segment_id in seen_ids:
                raise SchemaValidationError(
                    "DUPLICATE_SEGMENT_ID",
                    f"Duplicate segment_id '{seg.segment_id}'.",
                    {"segment_id": seg.segment_id},
                )
            seen_ids.add(seg.segment_id)
            segments.append(seg)

        raw_prior = data.get("prior_guidance", [])
        if not isinstance(raw_prior, list):
            raise SchemaValidationError(
                "INVALID_PRIOR_GUIDANCE",
                "prior_guidance must be a list.",
            )
        prior_guidance = tuple(
            PriorGuidanceRecord.from_dict(item, idx) for idx, item in enumerate(raw_prior)
        )

        raw_questions = data.get("questions", [])
        if not isinstance(raw_questions, list):
            raise SchemaValidationError(
                "INVALID_QUESTIONS",
                "questions must be a list.",
            )
        questions = tuple(
            QuestionRequest.from_dict(item, idx) for idx, item in enumerate(raw_questions)
        )

        return cls(
            schema_version=schema_version,
            transcript_id=transcript_id,
            ticker=ticker,
            company_name=company_name,
            fiscal_period=fiscal_period,
            call_timestamp=call_ts,
            published_at=pub_ts,
            filing_timestamp=filing_ts,
            currency=currency,
            language=language,
            source_name=source_name,
            source_license=source_license,
            segments=tuple(segments),
            prior_guidance=prior_guidance,
            questions=questions,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transcript_id": self.transcript_id,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "fiscal_period": self.fiscal_period,
            "call_timestamp": format_utc_timestamp(self.call_timestamp),
            "published_at": format_utc_timestamp(self.published_at),
            "filing_timestamp": format_utc_timestamp(self.filing_timestamp),
            "currency": self.currency,
            "language": self.language,
            "source_name": self.source_name,
            "source_license": self.source_license,
            "segments": [s.to_dict() for s in self.segments],
            "prior_guidance": [g.to_dict() for g in self.prior_guidance],
            "questions": [q.to_dict() for q in self.questions],
        }


@dataclass(frozen=True)
class EvidenceSpan:
    segment_id: str
    speaker: str
    speaker_role: SpeakerRole
    section: TranscriptSection
    char_start: int
    char_end: int
    exact_quote: str
    timestamp_sec: float
    source_published_at: str
    verified: bool
    quote_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "speaker": self.speaker,
            "speaker_role": self.speaker_role.value,
            "section": self.section.value,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "exact_quote": self.exact_quote,
            "timestamp_sec": self.timestamp_sec,
            "source_published_at": self.source_published_at,
            "verified": self.verified,
            "quote_sha256": self.quote_sha256,
        }


def build_verified_evidence(
    segment: TranscriptSegment,
    char_start: int,
    char_end: int,
    source_published_at: datetime,
    expected_quote: Optional[str] = None,
) -> EvidenceSpan:
    """Create an EvidenceSpan and enforce strict verbatim substring invariants."""
    if char_start < 0 or char_end <= char_start or char_end > len(segment.text):
        raise EvidenceVerificationError(
            "SPAN_OUT_OF_BOUNDS",
            f"Evidence span [{char_start}, {char_end}) out of bounds for segment '{segment.segment_id}' (len={len(segment.text)}).",
            {"segment_id": segment.segment_id, "char_start": char_start, "char_end": char_end},
        )
    actual_quote = segment.text[char_start:char_end]
    if expected_quote is not None and actual_quote != expected_quote:
        raise EvidenceVerificationError(
            "QUOTE_MISMATCH",
            f"Expected quote does not match segment '{segment.segment_id}' slice [{char_start}, {char_end}).",
            {"segment_id": segment.segment_id, "expected": expected_quote, "actual": actual_quote},
        )
    return EvidenceSpan(
        segment_id=segment.segment_id,
        speaker=segment.speaker,
        speaker_role=segment.speaker_role,
        section=segment.section,
        char_start=char_start,
        char_end=char_end,
        exact_quote=actual_quote,
        timestamp_sec=segment.start_offset_sec,
        source_published_at=format_utc_timestamp(source_published_at),
        verified=True,
        quote_sha256=sha256_text(actual_quote),
    )


@dataclass(frozen=True)
class ExtractedClaim:
    claim_id: str
    claim_type: ClaimType
    metric_name: str
    fiscal_period: str
    accounting_basis: AccountingBasis
    raw_value_text: str
    raw_unit: str
    normalized_unit: CanonicalUnit
    normalized_low: float
    normalized_high: float
    normalized_point: float
    is_range: bool
    is_approximate: bool
    uncertainty_level: UncertaintyLevel
    uncertainty_cues: Tuple[str, ...]
    evidence: EvidenceSpan
    extraction_method: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_type": self.claim_type.value,
            "metric_name": self.metric_name,
            "fiscal_period": self.fiscal_period,
            "accounting_basis": self.accounting_basis.value,
            "raw_value_text": self.raw_value_text,
            "raw_unit": self.raw_unit,
            "normalized_unit": self.normalized_unit.value,
            "normalized_low": self.normalized_low,
            "normalized_high": self.normalized_high,
            "normalized_point": self.normalized_point,
            "is_range": self.is_range,
            "is_approximate": self.is_approximate,
            "uncertainty_level": self.uncertainty_level.value,
            "uncertainty_cues": list(self.uncertainty_cues),
            "evidence": self.evidence.to_dict(),
            "extraction_method": self.extraction_method,
        }


@dataclass(frozen=True)
class GuidanceComparison:
    comparison_id: str
    metric_name: str
    fiscal_period: str
    accounting_basis: AccountingBasis
    normalized_unit: CanonicalUnit
    prior_low: Optional[float]
    prior_high: Optional[float]
    prior_midpoint: Optional[float]
    current_low: float
    current_high: float
    current_midpoint: float
    delta_midpoint: Optional[float]
    delta_pct: Optional[float]
    direction: GuidanceDirection
    uncertainty_flags: Tuple[str, ...]
    contradiction_detected: bool
    contradicting_claim_ids: Tuple[str, ...]
    supporting_claim_ids: Tuple[str, ...]
    prior_guidance_id: Optional[str]
    evidence_spans: Tuple[EvidenceSpan, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "metric_name": self.metric_name,
            "fiscal_period": self.fiscal_period,
            "accounting_basis": self.accounting_basis.value,
            "normalized_unit": self.normalized_unit.value,
            "prior_low": self.prior_low,
            "prior_high": self.prior_high,
            "prior_midpoint": self.prior_midpoint,
            "current_low": self.current_low,
            "current_high": self.current_high,
            "current_midpoint": self.current_midpoint,
            "delta_midpoint": self.delta_midpoint,
            "delta_pct": self.delta_pct,
            "direction": self.direction.value,
            "uncertainty_flags": list(self.uncertainty_flags),
            "contradiction_detected": self.contradiction_detected,
            "contradicting_claim_ids": list(self.contradicting_claim_ids),
            "supporting_claim_ids": list(self.supporting_claim_ids),
            "prior_guidance_id": self.prior_guidance_id,
            "evidence_spans": [e.to_dict() for e in self.evidence_spans],
        }


@dataclass(frozen=True)
class PromptInjectionEvent:
    event_id: str
    segment_id: str
    pattern_name: str
    severity: InjectionSeverity
    char_start: int
    char_end: int
    matched_snippet: str
    action_taken: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "segment_id": self.segment_id,
            "pattern_name": self.pattern_name,
            "severity": self.severity.value,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "matched_snippet": self.matched_snippet,
            "action_taken": self.action_taken,
        }


@dataclass(frozen=True)
class QuestionAnswer:
    question_id: str
    question: str
    answered: bool
    abstained: bool
    abstention_reason: Optional[AbstentionReason]
    answer_text: Optional[str]
    supporting_claim_ids: Tuple[str, ...]
    evidence_spans: Tuple[EvidenceSpan, ...]
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "answered": self.answered,
            "abstained": self.abstained,
            "abstention_reason": self.abstention_reason.value if self.abstention_reason else None,
            "answer_text": self.answer_text,
            "supporting_claim_ids": list(self.supporting_claim_ids),
            "evidence_spans": [e.to_dict() for e in self.evidence_spans],
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class AgentConfig:
    schema_version: str
    config_version: str
    seed: int
    extraction_mode: str
    max_source_age_days: int
    stale_policy: str
    max_segments: int
    max_llm_calls: int
    max_llm_tokens: int
    require_verified_evidence: bool
    allow_trade_actions: bool
    supported_currencies: Tuple[str, ...]
    supported_languages: Tuple[str, ...]
    contradiction_tolerance_pct: float
    reaffirm_tolerance_pct: float
    uncertainty_hedges: Tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        if not isinstance(data, dict):
            raise ConfigurationError("INVALID_CONFIG", "Configuration must be a JSON object.")
        schema_version = data.get("schema_version")
        if schema_version not in SUPPORTED_CONFIG_SCHEMAS:
            raise ConfigurationError(
                "UNSUPPORTED_CONFIG_SCHEMA",
                f"Unsupported config schema_version {schema_version!r}.",
                {"schema_version": schema_version},
            )
        allow_trade = data.get("allow_trade_actions", False)
        if allow_trade is not False:
            raise ConfigurationError(
                "POLICY_VIOLATION",
                "allow_trade_actions must be false; automated trade execution is strictly out of scope.",
                {"allow_trade_actions": allow_trade},
            )
        extraction_mode = data.get("extraction_mode", "deterministic")
        if extraction_mode not in {"deterministic", "hybrid"}:
            raise ConfigurationError(
                "INVALID_EXTRACTION_MODE",
                f"Invalid extraction_mode {extraction_mode!r}; expected 'deterministic' or 'hybrid'.",
            )
        stale_policy = data.get("stale_policy", "abstain")
        if stale_policy not in {"abstain", "flag_only"}:
            raise ConfigurationError(
                "INVALID_STALE_POLICY",
                f"Invalid stale_policy {stale_policy!r}; expected 'abstain' or 'flag_only'.",
            )
        max_age = data.get("max_source_age_days", 90)
        if not isinstance(max_age, int) or max_age <= 0:
            raise ConfigurationError("INVALID_MAX_AGE", "max_source_age_days must be a positive integer.")
        max_segments = data.get("max_segments", 500)
        if not isinstance(max_segments, int) or max_segments <= 0:
            raise ConfigurationError("INVALID_MAX_SEGMENTS", "max_segments must be a positive integer.")
        max_llm_calls = data.get("max_llm_calls", 10)
        max_llm_tokens = data.get("max_llm_tokens", 8000)
        if not isinstance(max_llm_calls, int) or max_llm_calls < 0:
            raise ConfigurationError("INVALID_BUDGET", "max_llm_calls must be a non-negative integer.")
        if not isinstance(max_llm_tokens, int) or max_llm_tokens < 0:
            raise ConfigurationError("INVALID_BUDGET", "max_llm_tokens must be a non-negative integer.")
        seed = data.get("seed", 42)
        if not isinstance(seed, int):
            raise ConfigurationError("INVALID_SEED", "seed must be an integer.")
        require_verified = data.get("require_verified_evidence", True)
        if require_verified is not True:
            raise ConfigurationError(
                "POLICY_VIOLATION",
                "require_verified_evidence must be true to enforce evidence-backed claims.",
            )
        currencies = tuple(str(c).upper() for c in data.get("supported_currencies", ["USD"]))
        languages = tuple(str(l).lower() for l in data.get("supported_languages", ["en"]))
        hedges = tuple(str(h).lower() for h in data.get("uncertainty_hedges", []))
        return cls(
            schema_version=str(schema_version),
            config_version=str(data.get("config_version", "1.0.0")),
            seed=seed,
            extraction_mode=extraction_mode,
            max_source_age_days=max_age,
            stale_policy=stale_policy,
            max_segments=max_segments,
            max_llm_calls=max_llm_calls,
            max_llm_tokens=max_llm_tokens,
            require_verified_evidence=True,
            allow_trade_actions=False,
            supported_currencies=currencies,
            supported_languages=languages,
            contradiction_tolerance_pct=float(data.get("contradiction_tolerance_pct", 0.5)),
            reaffirm_tolerance_pct=float(data.get("reaffirm_tolerance_pct", 0.5)),
            uncertainty_hedges=hedges,
        )

    @classmethod
    def from_file(cls, path: str) -> "AgentConfig":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError as exc:
            raise ConfigurationError(
                "MISSING_CONFIG_FILE",
                f"Configuration file not found: {path}",
                {"path": path},
            ) from exc
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                "MALFORMED_CONFIG_JSON",
                f"Configuration file is not valid JSON: {path} ({exc})",
                {"path": path},
            ) from exc
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config_version": self.config_version,
            "seed": self.seed,
            "extraction_mode": self.extraction_mode,
            "max_source_age_days": self.max_source_age_days,
            "stale_policy": self.stale_policy,
            "max_segments": self.max_segments,
            "max_llm_calls": self.max_llm_calls,
            "max_llm_tokens": self.max_llm_tokens,
            "require_verified_evidence": self.require_verified_evidence,
            "allow_trade_actions": self.allow_trade_actions,
            "supported_currencies": list(self.supported_currencies),
            "supported_languages": list(self.supported_languages),
            "contradiction_tolerance_pct": self.contradiction_tolerance_pct,
            "reaffirm_tolerance_pct": self.reaffirm_tolerance_pct,
            "uncertainty_hedges": list(self.uncertainty_hedges),
        }

    def digest(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class DiagnosticCounters:
    segments_ingested: int
    segments_quarantined: int
    injection_events_count: int
    claims_extracted: int
    claims_verified: int
    claims_rejected_unverified: int
    guidance_comparisons_count: int
    contradictions_detected: int
    questions_answered: int
    questions_abstained: int
    llm_calls_used: int
    llm_tokens_used: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segments_ingested": self.segments_ingested,
            "segments_quarantined": self.segments_quarantined,
            "injection_events_count": self.injection_events_count,
            "claims_extracted": self.claims_extracted,
            "claims_verified": self.claims_verified,
            "claims_rejected_unverified": self.claims_rejected_unverified,
            "guidance_comparisons_count": self.guidance_comparisons_count,
            "contradictions_detected": self.contradictions_detected,
            "questions_answered": self.questions_answered,
            "questions_abstained": self.questions_abstained,
            "llm_calls_used": self.llm_calls_used,
            "llm_tokens_used": self.llm_tokens_used,
        }


@dataclass(frozen=True)
class AnalysisReport:
    schema_version: str
    run_id: str
    input_digest: str
    config_digest: str
    seed: int
    transcript_id: str
    ticker: str
    company_name: str
    fiscal_period: str
    as_of_timestamp: str
    source_freshness: Dict[str, Any]
    trade_action_permitted: bool
    claims: Tuple[ExtractedClaim, ...]
    guidance_comparisons: Tuple[GuidanceComparison, ...]
    question_answers: Tuple[QuestionAnswer, ...]
    prompt_injection_events: Tuple[PromptInjectionEvent, ...]
    warnings: Tuple[str, ...]
    diagnostics: DiagnosticCounters
    runtime_metadata: Dict[str, Any]
    structured_logs: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "input_digest": self.input_digest,
            "config_digest": self.config_digest,
            "seed": self.seed,
            "transcript_id": self.transcript_id,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "fiscal_period": self.fiscal_period,
            "as_of_timestamp": self.as_of_timestamp,
            "source_freshness": self.source_freshness,
            "trade_action_permitted": self.trade_action_permitted,
            "claims": [c.to_dict() for c in self.claims],
            "guidance_comparisons": [g.to_dict() for g in self.guidance_comparisons],
            "question_answers": [q.to_dict() for q in self.question_answers],
            "prompt_injection_events": [e.to_dict() for e in self.prompt_injection_events],
            "warnings": list(self.warnings),
            "diagnostics": self.diagnostics.to_dict(),
            "runtime_metadata": self.runtime_metadata,
            "structured_logs": list(self.structured_logs),
        }
