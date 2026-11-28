"""Transcript ingestion, metadata normalization, freshness checks, and quarantine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .contracts import (
    AgentConfig,
    PromptInjectionEvent,
    SchemaValidationError,
    TranscriptInput,
    canonical_json,
    format_utc_timestamp,
    parse_utc_timestamp,
    sha256_text,
)
from .security import SanitizedSegment, scan_and_quarantine


@dataclass(frozen=True)
class SourceFreshness:
    is_stale: bool
    age_days: float
    max_age_days: int
    as_of_timestamp: datetime
    published_at: datetime
    filing_timestamp: datetime
    filing_lag_hours: float
    stale_reason: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_stale": self.is_stale,
            "age_days": self.age_days,
            "max_age_days": self.max_age_days,
            "as_of_timestamp": format_utc_timestamp(self.as_of_timestamp),
            "published_at": format_utc_timestamp(self.published_at),
            "filing_timestamp": format_utc_timestamp(self.filing_timestamp),
            "filing_lag_hours": self.filing_lag_hours,
            "stale_reason": self.stale_reason,
        }


@dataclass(frozen=True)
class IngestedTranscript:
    transcript: TranscriptInput
    input_digest: str
    freshness: SourceFreshness
    sanitized_segments: Tuple[SanitizedSegment, ...]
    injection_events: Tuple[PromptInjectionEvent, ...]


def evaluate_source_freshness(
    transcript: TranscriptInput,
    config: AgentConfig,
    as_of_timestamp: Optional[str] = None,
) -> SourceFreshness:
    """Evaluate publication age and filing alignment deterministically."""
    if as_of_timestamp is not None:
        as_of_dt = parse_utc_timestamp(as_of_timestamp, "as_of_timestamp")
    else:
        as_of_dt = transcript.published_at

    age_seconds = (as_of_dt - transcript.published_at).total_seconds()
    age_days = round(age_seconds / 86400.0, 4)
    filing_lag_hours = round(
        (transcript.published_at - transcript.filing_timestamp).total_seconds() / 3600.0, 4
    )

    is_stale = age_days > float(config.max_source_age_days)
    stale_reason: Optional[str] = None
    if is_stale:
        stale_reason = (
            f"Transcript published {age_days:.2f} days before as_of_timestamp "
            f"(max_source_age_days={config.max_source_age_days})."
        )
    elif age_days < 0:
        stale_reason = (
            f"Transcript published_at ({format_utc_timestamp(transcript.published_at)}) "
            f"is after as_of_timestamp ({format_utc_timestamp(as_of_dt)})."
        )

    return SourceFreshness(
        is_stale=is_stale,
        age_days=age_days,
        max_age_days=config.max_source_age_days,
        as_of_timestamp=as_of_dt,
        published_at=transcript.published_at,
        filing_timestamp=transcript.filing_timestamp,
        filing_lag_hours=filing_lag_hours,
        stale_reason=stale_reason,
    )


def ingest_transcript(
    raw_data: Dict[str, Any],
    config: AgentConfig,
    as_of_timestamp: Optional[str] = None,
) -> IngestedTranscript:
    """Validate transcript input, compute digest, check freshness, and quarantine injections."""
    transcript = TranscriptInput.from_dict(
        raw_data,
        supported_currencies=config.supported_currencies,
        supported_languages=config.supported_languages,
        max_segments=config.max_segments,
    )
    input_digest = sha256_text(canonical_json(transcript.to_dict()))
    freshness = evaluate_source_freshness(transcript, config, as_of_timestamp=as_of_timestamp)
    sanitized_segments, injection_events = scan_and_quarantine(transcript.segments)
    return IngestedTranscript(
        transcript=transcript,
        input_digest=input_digest,
        freshness=freshness,
        sanitized_segments=sanitized_segments,
        injection_events=injection_events,
    )


def load_transcript_file(path: str) -> Dict[str, Any]:
    """Load a JSON transcript payload from disk with structured validation errors."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise SchemaValidationError(
            "MISSING_INPUT_FILE",
            f"Transcript file not found: {path}",
            {"path": path},
        ) from exc
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(
            "MALFORMED_INPUT_JSON",
            f"Transcript file is not valid JSON: {path} ({exc})",
            {"path": path},
        ) from exc
    if not isinstance(data, dict):
        raise SchemaValidationError(
            "INVALID_ROOT",
            f"Transcript file '{path}' must contain a JSON object at root.",
            {"path": path},
        )
    return data
