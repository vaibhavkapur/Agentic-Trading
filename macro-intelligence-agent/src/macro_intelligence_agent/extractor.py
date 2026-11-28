"""Deterministic extraction of macroeconomic figures and central bank policy language with citations.

Pure domain module (no I/O, no network, no nondeterministic state).
"""

from __future__ import annotations

from decimal import Decimal
import re
from typing import List, Optional, Tuple

from .errors import CitationVerificationError
from .models import (
    Citation,
    DocumentType,
    ExtractedFigure,
    MacroRelease,
    PolicyLanguageSignal,
    PolicyStance,
    Unit,
    parse_decimal,
    stable_id,
)

# Fallback deterministic text extraction patterns for raw-text-only releases.
_TEXT_METRIC_PATTERNS: Tuple[Tuple[str, Unit, re.Pattern[str]], ...] = (
    (
        "US_CPI_HEADLINE",
        Unit.PERCENT_YOY,
        re.compile(
            r"(?:US\s+)?Headline\s+CPI[^.\n]{0,40}?([-+]?\d+(?:\.\d+)?)%\s*YoY",
            re.IGNORECASE,
        ),
    ),
    (
        "US_CPI_CORE",
        Unit.PERCENT_YOY,
        re.compile(
            r"(?:US\s+)?Core\s+CPI[^.\n]{0,50}?([-+]?\d+(?:\.\d+)?)%\s*YoY",
            re.IGNORECASE,
        ),
    ),
    (
        "US_NFP",
        Unit.THOUSANDS,
        re.compile(
            r"(?:US\s+)?Nonfarm\s+Payrolls[^.\n]{0,40}?([-+]?\d+(?:\.\d+)?)\s*(?:thousand|k)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "FED_FUNDS_TARGET_UPPER",
        Unit.PERCENT_RATE,
        re.compile(
            r"federal\s+funds\s+rate[^.\n]{0,40}?(\d+(?:\.\d+)?)%",
            re.IGNORECASE,
        ),
    ),
)

# Deterministic central bank policy language lexicon (phrase, stance, topic).
_POLICY_LEXICON: Tuple[Tuple[re.Pattern[str], PolicyStance, str], ...] = (
    (
        re.compile(r"inflation\s+remains\s+(?:somewhat\s+)?elevated", re.IGNORECASE),
        PolicyStance.HAWKISH,
        "inflation_persistence",
    ),
    (
        re.compile(
            r"prepared\s+to\s+maintain\s+the\s+target\s+range|higher\s+for\s+longer|additional\s+policy\s+firming",
            re.IGNORECASE,
        ),
        PolicyStance.HAWKISH,
        "rate_path",
    ),
    (
        re.compile(
            r"carefully\s+assess\s+incoming\s+data|data[- ]dependent|meeting[- ]by[- ]meeting",
            re.IGNORECASE,
        ),
        PolicyStance.DATA_DEPENDENT,
        "reaction_function",
    ),
    (
        re.compile(
            r"disinflation\s+is\s+well\s+on\s+track|appropriate\s+to\s+dial\s+back\s+policy\s+restraint|downside\s+risks\s+to\s+employment",
            re.IGNORECASE,
        ),
        PolicyStance.DOVISH,
        "easing_bias",
    ),
    (
        re.compile(
            r"risks\s+to\s+achieving\s+its\s+employment\s+and\s+inflation\s+goals\s+are\s+roughly\s+in\s+balance",
            re.IGNORECASE,
        ),
        PolicyStance.NEUTRAL,
        "balance_of_risks",
    ),
)


def _locate_verified_span(
    sanitized_text: str,
    raw_text: str,
    quote: Optional[str],
    value: Decimal,
) -> Tuple[int, int, str]:
    """Find an exact span in sanitized_text that matches raw_text verbatim."""
    if quote:
        idx = sanitized_text.find(quote)
        if idx == -1:
            raise CitationVerificationError(
                f"Reported metric quote could not be grounded in sanitized source text: '{quote}'",
                details={"quote": quote},
            )
        end = idx + len(quote)
        # Ensure quote matches untouched raw_text at the exact same offsets
        if raw_text[idx:end] != quote:
            raise CitationVerificationError(
                "Citation offset integrity failed between sanitized_text and raw_text",
                details={"char_start": idx, "char_end": end},
            )
        return idx, end, quote

    # No explicit quote supplied: locate numeric token in sanitized text and expand to sentence/clause
    val_str = format(value, "f")
    candidates = [val_str]
    normalized = format(value.normalize(), "f")
    if normalized != val_str:
        candidates.append(normalized)
    for token in candidates:
        idx = sanitized_text.find(token)
        if idx != -1:
            start = max(0, sanitized_text.rfind(".", 0, idx) + 1)
            next_dot = sanitized_text.find(".", idx + len(token))
            end = len(sanitized_text) if next_dot == -1 else next_dot + 1
            snippet = sanitized_text[start:end].strip()
            exact_start = sanitized_text.find(snippet, start, end)
            exact_end = exact_start + len(snippet)
            if exact_start != -1 and raw_text[exact_start:exact_end] == snippet:
                return exact_start, exact_end, snippet

    raise CitationVerificationError(
        f"Reported numeric value '{val_str}' could not be located in sanitized source text",
        details={"value": val_str},
    )


def extract_figures_from_release(
    release: MacroRelease,
    sanitized_text: str,
) -> Tuple[ExtractedFigure, ...]:
    """Extract verified figures with character-span citations from a release."""
    extracted: List[ExtractedFigure] = []

    if release.reported_metrics:
        for obs in release.reported_metrics:
            char_start, char_end, verified_quote = _locate_verified_span(
                sanitized_text=sanitized_text,
                raw_text=release.raw_text,
                quote=obs.quote,
                value=obs.value,
            )
            citation = Citation.build(
                release_id=release.release_id,
                vintage_id=release.vintage_id,
                source_id=release.source_id,
                published_at=release.published_at,
                char_start=char_start,
                char_end=char_end,
                quote=verified_quote,
                document_sha256=release.document_sha256,
            )
            fig_id = stable_id(
                "fig",
                {
                    "release_id": release.release_id,
                    "vintage_id": release.vintage_id,
                    "series_id": obs.series_id,
                    "reference_period": obs.reference_period,
                    "value": format(obs.value, "f"),
                    "unit": obs.unit.value,
                    "citation_id": citation.citation_id,
                },
            )
            extracted.append(
                ExtractedFigure(
                    figure_id=fig_id,
                    series_id=obs.series_id,
                    reference_period=obs.reference_period,
                    value=obs.value,
                    unit=obs.unit,
                    release_id=release.release_id,
                    vintage_id=release.vintage_id,
                    source_id=release.source_id,
                    published_at=release.published_at,
                    citation=citation,
                    extraction_method="grounded_structured_metric",
                )
            )
        return tuple(extracted)

    # Fallback: deterministic regex extraction directly from sanitized_text
    for series_id, unit, pattern in _TEXT_METRIC_PATTERNS:
        for match in pattern.finditer(sanitized_text):
            val = parse_decimal(match.group(1), series_id)
            char_start, char_end = match.start(), match.end()
            quote = release.raw_text[char_start:char_end]
            citation = Citation.build(
                release_id=release.release_id,
                vintage_id=release.vintage_id,
                source_id=release.source_id,
                published_at=release.published_at,
                char_start=char_start,
                char_end=char_end,
                quote=quote,
                document_sha256=release.document_sha256,
            )
            fig_id = stable_id(
                "fig",
                {
                    "release_id": release.release_id,
                    "vintage_id": release.vintage_id,
                    "series_id": series_id,
                    "reference_period": release.reference_period,
                    "value": format(val, "f"),
                    "unit": unit.value,
                    "citation_id": citation.citation_id,
                },
            )
            extracted.append(
                ExtractedFigure(
                    figure_id=fig_id,
                    series_id=series_id,
                    reference_period=release.reference_period,
                    value=val,
                    unit=unit,
                    release_id=release.release_id,
                    vintage_id=release.vintage_id,
                    source_id=release.source_id,
                    published_at=release.published_at,
                    citation=citation,
                    extraction_method="deterministic_text_regex",
                )
            )
    return tuple(extracted)


def extract_policy_language(
    release: MacroRelease,
    sanitized_text: str,
) -> Tuple[PolicyLanguageSignal, ...]:
    """Extract policy-stance language cues with verifiable citations from central bank documents."""
    if release.document_type not in (
        DocumentType.CENTRAL_BANK_STATEMENT,
        DocumentType.CENTRAL_BANK_MINUTES,
    ):
        return ()

    signals: List[PolicyLanguageSignal] = []
    for pattern, stance, topic in _POLICY_LEXICON:
        for match in pattern.finditer(sanitized_text):
            char_start, char_end = match.start(), match.end()
            quote = release.raw_text[char_start:char_end]
            citation = Citation.build(
                release_id=release.release_id,
                vintage_id=release.vintage_id,
                source_id=release.source_id,
                published_at=release.published_at,
                char_start=char_start,
                char_end=char_end,
                quote=quote,
                document_sha256=release.document_sha256,
            )
            sig_id = stable_id(
                "pol",
                {
                    "release_id": release.release_id,
                    "vintage_id": release.vintage_id,
                    "stance": stance.value,
                    "topic": topic,
                    "citation_id": citation.citation_id,
                },
            )
            signals.append(
                PolicyLanguageSignal(
                    signal_id=sig_id,
                    stance=stance,
                    matched_phrase=quote,
                    topic=topic,
                    release_id=release.release_id,
                    vintage_id=release.vintage_id,
                    citation=citation,
                )
            )
    signals.sort(key=lambda s: (s.citation.char_start, s.signal_id))
    return tuple(signals)
