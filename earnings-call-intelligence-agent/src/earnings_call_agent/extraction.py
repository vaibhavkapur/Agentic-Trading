"""Pure domain extraction of financial metrics and forward guidance with exact evidence spans.

This module performs no I/O. Every extracted claim carries a verbatim EvidenceSpan
verified against the original TranscriptSegment text and normalized to canonical units
and fiscal periods.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from .contracts import (
    AccountingBasis,
    CanonicalUnit,
    ClaimType,
    ExtractedClaim,
    SpeakerRole,
    UncertaintyLevel,
    build_verified_evidence,
    normalize_fiscal_period,
    normalize_unit_and_value,
    stable_id,
)
from .security import SanitizedSegment, split_sentence_spans

# Roles allowed to make official company claims (analyst questions & operator intros excluded)
_EXECUTIVE_ROLES = frozenset(
    {
        SpeakerRole.CEO,
        SpeakerRole.CFO,
        SpeakerRole.COO,
        SpeakerRole.IR,
        SpeakerRole.EXECUTIVE,
    }
)

# Ordered longest-alias-first to prevent partial matches (e.g., "gross margin" before "margin")
METRIC_ALIASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("operating_margin", ("operating margin", "ebit margin", "operating income margin")),
    ("gross_margin", ("gross margin", "gross profit margin")),
    ("free_cash_flow", ("free cash flow", "fcf")),
    ("operating_income", ("operating income", "ebit")),
    ("net_income", ("net income", "net earnings")),
    ("ebitda", ("adjusted ebitda", "ebitda")),
    ("arr", ("annual recurring revenue", "arr")),
    ("capex", ("capital expenditures", "capital expenditure", "capex")),
    ("eps", ("diluted earnings per share", "earnings per share", "diluted eps", "eps")),
    ("revenue", ("total revenue", "net revenue", "top-line revenue", "revenues", "revenue", "net sales")),
)

_METRIC_DEFAULT_UNITS: Dict[str, CanonicalUnit] = {
    "revenue": CanonicalUnit.USD_MILLIONS,
    "operating_income": CanonicalUnit.USD_MILLIONS,
    "net_income": CanonicalUnit.USD_MILLIONS,
    "free_cash_flow": CanonicalUnit.USD_MILLIONS,
    "ebitda": CanonicalUnit.USD_MILLIONS,
    "arr": CanonicalUnit.USD_MILLIONS,
    "capex": CanonicalUnit.USD_MILLIONS,
    "eps": CanonicalUnit.USD_PER_SHARE,
    "gross_margin": CanonicalUnit.PERCENT,
    "operating_margin": CanonicalUnit.PERCENT,
}

_GUIDANCE_CUES_RE = re.compile(
    r"\b(?:expect|expects|expecting|expected|guide|guiding|guidance|outlook|project|"
    r"projecting|projected|forecast|forecasting|target|targeting|anticipate|anticipating|"
    r"reaffirm|reaffirming|reaffirmed|raise|raising|raised|lower|lowering|lowered|"
    r"revise|revising|revised|narrow|narrowing|narrowed|now\s+see|see\s+(?:full|q[1-4]|fy|cy)|"
    r"will\s+be|should\s+be|trending\s+toward|estimate|estimating)\b",
    re.IGNORECASE,
)

_REPORTED_CUES_RE = re.compile(
    r"\b(?:reported|came\s+in\s+at|reached|delivered|generated|achieved|posted|totaled|"
    r"finished\s+at|ended\s+at|stood\s+at|was|were)\b",
    re.IGNORECASE,
)

_CLAUSE_SPLIT_RE = re.compile(
    r"(?:;\s+|,\s+(?:and\s+|while\s+|whereas\s+|with\s+)(?=(?:for\s+|in\s+|we\s+|our\s+|full|q[1-4]|fy|cy|non-gaap|gaap|gross|operating|revenue|diluted|eps|free|adjusted))|"
    r"\s+and\s+(?=(?:for\s+(?:q[1-4]|fy|cy|full)|we\s+(?:expect|guide|project|reaffirm|raise|lower|see|anticipate)|our\s+(?:q[1-4]|fy|cy|full))))",
    re.IGNORECASE,
)

_APPROX_RE = re.compile(r"\b(?:approximately|roughly|around|about|nearly)\b|~", re.IGNORECASE)

_STRONG_UNCERTAINTY_WORDS = frozenset(
    {
        "uncertain",
        "uncertainty",
        "subject to",
        "depending on",
        "volatile",
        "volatility",
        "headwinds",
        "visibility",
        "tentative",
        "preliminary",
        "cautious",
    }
)

_QUARTER_WORD_MAP = {
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
}

_PERIOD_SEARCH_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bQ([1-4])[\s_-]*(?:FY)?(20\d{2})\b", re.IGNORECASE), "Q_NUM"),
    (re.compile(r"\b([1-4])Q[\s_-]*(?:FY)?(\d{2})\b", re.IGNORECASE), "Q_SHORT"),
    (
        re.compile(
            r"\b(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:fiscal\s+|FY)?(20\d{2})\b",
            re.IGNORECASE,
        ),
        "Q_WORD",
    ),
    (re.compile(r"\b(?:full[- ]year\s+)?(?:fiscal\s+(?:year\s+)?)?FY[\s_-]*(20\d{2})\b", re.IGNORECASE), "FY_NUM"),
    (re.compile(r"\b(?:full[- ]year\s+)?fiscal\s+(?:year\s+)?(20\d{2})\b", re.IGNORECASE), "FY_NUM"),
    (re.compile(r"\bfull[- ]year\s+(20\d{2})\b", re.IGNORECASE), "FY_NUM"),
    (re.compile(r"\bFY[\s_-]*(\d{2})\b", re.IGNORECASE), "FY_SHORT"),
    (re.compile(r"\b(?:calendar\s+year\s+|CY[\s_-]*)(20\d{2})\b", re.IGNORECASE), "CY_NUM"),
    (re.compile(r"\bH([12])[\s_-]*(?:FY)?(20\d{2})\b", re.IGNORECASE), "H_NUM"),
)

# Numeric extraction patterns (checked in priority order inside a local window after metric)
_NUM = r"(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)"
_SCALE_WORD = r"(billion|billions|bn|b|million|millions|mm|m|thousand|thousands|k)"
_PER_SHARE = r"(?:per\s+(?:diluted\s+)?share)"

_DOLLAR_RANGE_RE = re.compile(
    rf"(?:between\s+)?\$\s*{_NUM}\s*(?:{_SCALE_WORD}\s*)?(?:to|-|–|and)\s*\$?\s*{_NUM}\s*(?:{_SCALE_WORD}\b)?(?:\s*{_PER_SHARE})?",
    re.IGNORECASE,
)
_DOLLAR_POINT_RE = re.compile(
    rf"\$\s*{_NUM}\s*(?:{_SCALE_WORD}\b)?(?:\s*{_PER_SHARE})?",
    re.IGNORECASE,
)
_PERCENT_RANGE_RE = re.compile(
    rf"(?:between\s+)?{_NUM}\s*(?:%|percent|pct)?\s*(?:to|-|–|and)\s*{_NUM}\s*(%|(?:percent|pct)\b)",
    re.IGNORECASE,
)
_PERCENT_POINT_RE = re.compile(
    rf"{_NUM}\s*(%|(?:percent|pct)\b)(?!\s*(?:yoy|year[- ]over[- ]year|qoq|sequentially))",
    re.IGNORECASE,
)
_BPS_RANGE_RE = re.compile(
    rf"(?:between\s+)?{_NUM}\s*(?:bps|basis\s+points?)?\s*(?:to|-|–|and)\s*{_NUM}\s*(bps|basis\s+points?)\b",
    re.IGNORECASE,
)
_BPS_POINT_RE = re.compile(
    rf"{_NUM}\s*(bps|basis\s+points?)\b",
    re.IGNORECASE,
)


def _to_float(num_str: str) -> float:
    return float(num_str.replace(",", ""))


def _next_quarter(period: str) -> str:
    m = re.match(r"^Q([1-4])_FY(20\d{2})$", period)
    if not m:
        return period
    q = int(m.group(1))
    yr = int(m.group(2))
    if q == 4:
        return f"Q1_FY{yr + 1}"
    return f"Q{q + 1}_FY{yr}"


def _next_full_year(period: str) -> str:
    m = re.match(r"^Q([1-4])_FY(20\d{2})$", period)
    if m:
        q = int(m.group(1))
        yr = int(m.group(2))
        return f"FY{yr + 1}" if q == 4 else f"FY{yr}"
    m2 = re.match(r"^FY(20\d{2})$", period)
    if m2:
        return f"FY{int(m2.group(1)) + 1}"
    return period


def _detect_fiscal_period(
    clause_text: str,
    sentence_text: str,
    default_period: str,
    claim_type: ClaimType,
) -> str:
    for text in (clause_text, sentence_text):
        for pattern, kind in _PERIOD_SEARCH_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            if kind == "Q_NUM":
                return normalize_fiscal_period(f"Q{m.group(1)}_FY{m.group(2)}")
            if kind == "Q_SHORT":
                return normalize_fiscal_period(f"Q{m.group(1)}_FY20{m.group(2)}")
            if kind == "Q_WORD":
                qnum = _QUARTER_WORD_MAP[m.group(1).lower()]
                return normalize_fiscal_period(f"Q{qnum}_FY{m.group(2)}")
            if kind == "FY_NUM":
                return normalize_fiscal_period(f"FY{m.group(1)}")
            if kind == "FY_SHORT":
                return normalize_fiscal_period(f"FY20{m.group(1)}")
            if kind == "CY_NUM":
                return normalize_fiscal_period(f"CY{m.group(1)}")
            if kind == "H_NUM":
                return normalize_fiscal_period(f"H{m.group(1)}_FY{m.group(2)}")

    lower = clause_text.lower()
    if claim_type == ClaimType.FORWARD_GUIDANCE:
        if "next quarter" in lower:
            return _next_quarter(default_period)
        if "full year" in lower or "full-year" in lower:
            return _next_full_year(default_period)
    return default_period


def _detect_accounting_basis(window_text: str, clause_text: str) -> AccountingBasis:
    for text in (window_text, clause_text):
        lower = text.lower()
        if re.search(r"\bnon[- ]gaap\b", lower) or re.search(r"\badjusted\b", lower):
            return AccountingBasis.NON_GAAP
        if re.search(r"(?<!non-)(?<!non )\bgaap\b", lower):
            return AccountingBasis.GAAP
    return AccountingBasis.UNSPECIFIED


def _detect_claim_type(clause_text: str, sentence_text: str) -> ClaimType:
    if _GUIDANCE_CUES_RE.search(clause_text):
        return ClaimType.FORWARD_GUIDANCE
    if _REPORTED_CUES_RE.search(clause_text):
        return ClaimType.REPORTED_METRIC
    if _GUIDANCE_CUES_RE.search(sentence_text):
        return ClaimType.FORWARD_GUIDANCE
    return ClaimType.REPORTED_METRIC


def _detect_uncertainty(
    clause_text: str,
    hedges: Sequence[str],
) -> Tuple[bool, UncertaintyLevel, Tuple[str, ...]]:
    lower = clause_text.lower()
    found: List[str] = []
    for h in hedges:
        if re.search(rf"\b{re.escape(h)}\b", lower):
            found.append(h)
    is_approx = bool(_APPROX_RE.search(clause_text))
    strong_hits = [h for h in found if h in _STRONG_UNCERTAINTY_WORDS]
    if len(strong_hits) >= 1 or len(found) >= 2:
        level = UncertaintyLevel.HIGH
    elif len(found) == 1 or is_approx:
        level = UncertaintyLevel.MEDIUM
    else:
        level = UncertaintyLevel.LOW
    return is_approx, level, tuple(sorted(set(found)))


def _split_clauses_with_offsets(
    text: str, sent_start: int, sent_end: int
) -> List[Tuple[int, int]]:
    sentence = text[sent_start:sent_end]
    spans: List[Tuple[int, int]] = []
    cur = 0
    for m in _CLAUSE_SPLIT_RE.finditer(sentence):
        end = m.start()
        if end > cur:
            spans.append((sent_start + cur, sent_start + end))
        cur = m.end()
    if cur < len(sentence):
        spans.append((sent_start + cur, sent_end))
    return spans


def _strip_span(text: str, start: int, end: int) -> Tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _parse_value_for_metric(
    metric_name: str,
    after_metric_text: str,
) -> Optional[Tuple[str, str, CanonicalUnit, float, float, bool]]:
    """Extract the first metric-compatible numeric value/range after a metric mention.

    Returns (raw_value_text, raw_unit, normalized_unit, norm_low, norm_high, is_range).
    """
    expected_unit = _METRIC_DEFAULT_UNITS.get(metric_name)

    # Margin metrics: expect PERCENT or BPS
    if expected_unit == CanonicalUnit.PERCENT:
        m = _PERCENT_RANGE_RE.search(after_metric_text)
        if m and m.start() <= 60:
            low = _to_float(m.group(1))
            high = _to_float(m.group(2))
            if low <= high:
                u, nl = normalize_unit_and_value("percent", low)
                _, nh = normalize_unit_and_value("percent", high)
                return m.group(0).strip(), "%", u, nl, nh, True
        m = _PERCENT_POINT_RE.search(after_metric_text)
        if m and m.start() <= 60:
            val = _to_float(m.group(1))
            u, nv = normalize_unit_and_value("percent", val)
            return m.group(0).strip(), "%", u, nv, nv, False
        m = _BPS_RANGE_RE.search(after_metric_text)
        if m and m.start() <= 60:
            low = _to_float(m.group(1))
            high = _to_float(m.group(2))
            if low <= high:
                u, nl = normalize_unit_and_value("bps", low)
                _, nh = normalize_unit_and_value("bps", high)
                return m.group(0).strip(), "bps", u, nl, nh, True
        m = _BPS_POINT_RE.search(after_metric_text)
        if m and m.start() <= 60:
            val = _to_float(m.group(1))
            u, nv = normalize_unit_and_value("bps", val)
            return m.group(0).strip(), "bps", u, nv, nv, False
        return None

    # EPS: expect USD_PER_SHARE
    if expected_unit == CanonicalUnit.USD_PER_SHARE:
        m = _DOLLAR_RANGE_RE.search(after_metric_text)
        if m and m.start() <= 60 and not m.group(2) and not m.group(4):
            low = _to_float(m.group(1))
            high = _to_float(m.group(3))
            if low <= high:
                u, nl = normalize_unit_and_value("usd_per_share", low)
                _, nh = normalize_unit_and_value("usd_per_share", high)
                return m.group(0).strip(), "usd_per_share", u, nl, nh, True
        m = _DOLLAR_POINT_RE.search(after_metric_text)
        if m and m.start() <= 60 and not m.group(2):
            val = _to_float(m.group(1))
            u, nv = normalize_unit_and_value("usd_per_share", val)
            return m.group(0).strip(), "usd_per_share", u, nv, nv, False
        return None

    # Monetary metrics (USD_MILLIONS): expect dollar amounts with scale word (billion/million/thousand)
    m = _DOLLAR_RANGE_RE.search(after_metric_text)
    if m and m.start() <= 65:
        scale_high = m.group(4)
        scale_low = m.group(2) or scale_high
        if scale_low and scale_high:
            low = _to_float(m.group(1))
            high = _to_float(m.group(3))
            u_low, nl = normalize_unit_and_value(scale_low, low)
            u_high, nh = normalize_unit_and_value(scale_high, high)
            if u_low == u_high and nl <= nh:
                raw_u = scale_low if scale_low.lower() == scale_high.lower() else f"{scale_low}/{scale_high}"
                return m.group(0).strip(), raw_u, u_low, nl, nh, True

    m = _DOLLAR_POINT_RE.search(after_metric_text)
    if m and m.start() <= 65 and m.group(2):
        val = _to_float(m.group(1))
        scale = m.group(2)
        u, nv = normalize_unit_and_value(scale, val)
        return m.group(0).strip(), scale, u, nv, nv, False

    return None


def _find_metric_mentions(clause_text: str) -> List[Tuple[int, int, str]]:
    """Locate non-overlapping canonical metric mentions in clause_text."""
    matches: List[Tuple[int, int, str]] = []
    lower = clause_text.lower()
    occupied: List[Tuple[int, int]] = []

    for canonical_name, aliases in METRIC_ALIASES:
        for alias in aliases:
            pattern = re.compile(rf"\b{re.escape(alias)}\b")
            for m in pattern.finditer(lower):
                s, e = m.start(), m.end()
                if any(not (e <= os or s >= oe) for os, oe in occupied):
                    continue
                occupied.append((s, e))
                matches.append((s, e, canonical_name))

    matches.sort(key=lambda item: item[0])
    return matches


def extract_claims_from_segments(
    sanitized_segments: Sequence[SanitizedSegment],
    default_fiscal_period: str,
    published_at: datetime,
    uncertainty_hedges: Sequence[str],
) -> Tuple[ExtractedClaim, ...]:
    """Deterministically extract verified financial claims from sanitized segments."""
    claims: List[ExtractedClaim] = []
    seen_claim_ids = set()

    for san_seg in sanitized_segments:
        segment = san_seg.segment
        if segment.speaker_role not in _EXECUTIVE_ROLES:
            continue
        if san_seg.fully_quarantined:
            continue

        san_text = san_seg.sanitized_text
        sentence_spans = split_sentence_spans(san_text)
        for sent_start, sent_end in sentence_spans:
            sentence_raw = san_text[sent_start:sent_end]
            if not sentence_raw.strip():
                continue
            # Ignore pure questions
            if sentence_raw.strip().endswith("?"):
                continue

            clause_spans = _split_clauses_with_offsets(san_text, sent_start, sent_end)
            for c_start, c_end in clause_spans:
                c_start, c_end = _strip_span(san_text, c_start, c_end)
                if c_end <= c_start:
                    continue
                clause_text = san_text[c_start:c_end]
                metric_mentions = _find_metric_mentions(clause_text)
                if not metric_mentions:
                    continue

                claim_type = _detect_claim_type(clause_text, sentence_raw)
                fiscal_period = _detect_fiscal_period(
                    clause_text, sentence_raw, default_fiscal_period, claim_type
                )
                is_approx, unc_level, unc_cues = _detect_uncertainty(
                    clause_text, uncertainty_hedges
                )

                for idx, (m_start, m_end, metric_name) in enumerate(metric_mentions):
                    next_m_start = (
                        metric_mentions[idx + 1][0]
                        if idx + 1 < len(metric_mentions)
                        else len(clause_text)
                    )
                    after_text = clause_text[m_end:next_m_start]
                    parsed = _parse_value_for_metric(metric_name, after_text)
                    if parsed is None:
                        continue
                    (
                        raw_value_text,
                        raw_unit,
                        norm_unit,
                        norm_low,
                        norm_high,
                        is_range,
                    ) = parsed

                    # Local accounting basis window around the metric mention
                    win_start = max(0, m_start - 25)
                    win_end = min(len(clause_text), m_end + 40)
                    basis = _detect_accounting_basis(
                        clause_text[win_start:win_end], clause_text
                    )

                    # Verify evidence span verbatim against the ORIGINAL segment.text
                    evidence = build_verified_evidence(
                        segment=segment,
                        char_start=c_start,
                        char_end=c_end,
                        source_published_at=published_at,
                        expected_quote=clause_text,
                    )

                    norm_point = round((norm_low + norm_high) / 2.0, 6)
                    cid = stable_id(
                        "clm",
                        [
                            segment.segment_id,
                            c_start,
                            c_end,
                            metric_name,
                            fiscal_period,
                            basis.value,
                            norm_unit.value,
                            norm_low,
                            norm_high,
                        ],
                    )
                    if cid in seen_claim_ids:
                        continue
                    seen_claim_ids.add(cid)

                    claims.append(
                        ExtractedClaim(
                            claim_id=cid,
                            claim_type=claim_type,
                            metric_name=metric_name,
                            fiscal_period=fiscal_period,
                            accounting_basis=basis,
                            raw_value_text=raw_value_text,
                            raw_unit=raw_unit,
                            normalized_unit=norm_unit,
                            normalized_low=norm_low,
                            normalized_high=norm_high,
                            normalized_point=norm_point,
                            is_range=is_range,
                            is_approximate=is_approx,
                            uncertainty_level=unc_level,
                            uncertainty_cues=unc_cues,
                            evidence=evidence,
                            extraction_method="deterministic_rules",
                        )
                    )

    return tuple(claims)
