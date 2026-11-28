"""Evidence-grounded question answering with strict abstention guarantees.

Questions are answered ONLY when backed by verified claims from fresh,
non-quarantined transcript segments. Unanswerable questions, stale sources,
contradictory guidance, and injection-only references result in explicit abstention.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from .contracts import (
    AbstentionReason,
    AgentConfig,
    CanonicalUnit,
    ClaimType,
    ExtractedClaim,
    GuidanceComparison,
    QuestionAnswer,
    QuestionRequest,
    UncertaintyLevel,
    normalize_fiscal_period,
)
from .extraction import METRIC_ALIASES, _PERIOD_SEARCH_PATTERNS, _QUARTER_WORD_MAP
from .ingestion import SourceFreshness
from .security import SanitizedSegment

_GUIDANCE_Q_RE = re.compile(
    r"\b(?:guidance|outlook|expect|forecast|project|target|raised|lowered|reaffirmed|change|compare)\b",
    re.IGNORECASE,
)
_CONTRADICTION_Q_RE = re.compile(
    r"\b(?:contradict\w*|conflict\w*|discrepanc\w*|inconsisten\w*|disagree\w*)\b",
    re.IGNORECASE,
)


def _infer_metric_from_question(question: QuestionRequest) -> Optional[str]:
    if question.metric_hint:
        return question.metric_hint.lower()
    lower = question.question.lower()
    for canonical, aliases in METRIC_ALIASES:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", lower):
                return canonical
    return None


def _infer_period_from_question(question: QuestionRequest) -> Optional[str]:
    if question.fiscal_period_hint:
        return question.fiscal_period_hint
    for pattern, kind in _PERIOD_SEARCH_PATTERNS:
        m = pattern.search(question.question)
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
    return None


def _quarantined_mentions_topic(
    sanitized_segments: Sequence[SanitizedSegment],
    metric: Optional[str],
    question_text: str,
) -> bool:
    keywords: List[str] = []
    if metric:
        for canonical, aliases in METRIC_ALIASES:
            if canonical == metric:
                keywords.extend(aliases)
                break
        keywords.append(metric.replace("_", " "))
    else:
        for token in re.findall(r"[a-zA-Z]{4,}", question_text.lower()):
            if token not in {"what", "when", "does", "were", "company", "guidance", "management", "reported"}:
                keywords.append(token)

    for san in sanitized_segments:
        for snippet in san.quarantined_text_snippets:
            low = snippet.lower()
            if any(k in low for k in keywords):
                return True
    return False


def _format_value(low: float, high: float, unit: CanonicalUnit) -> str:
    if unit == CanonicalUnit.USD_MILLIONS:
        if abs(low - high) < 1e-6:
            return f"${low:,.2f}M"
        return f"${low:,.2f}M to ${high:,.2f}M"
    if unit == CanonicalUnit.USD_PER_SHARE:
        if abs(low - high) < 1e-6:
            return f"${low:.2f}/share"
        return f"${low:.2f} to ${high:.2f}/share"
    if unit == CanonicalUnit.PERCENT:
        if abs(low - high) < 1e-6:
            return f"{low:.2f}%"
        return f"{low:.2f}% to {high:.2f}%"
    if unit == CanonicalUnit.BPS:
        if abs(low - high) < 1e-6:
            return f"{low:.1f} bps"
        return f"{low:.1f} to {high:.1f} bps"
    if abs(low - high) < 1e-6:
        return f"{low:g} {unit.value}"
    return f"{low:g} to {high:g} {unit.value}"


def answer_questions(
    questions: Sequence[QuestionRequest],
    claims: Sequence[ExtractedClaim],
    comparisons: Sequence[GuidanceComparison],
    sanitized_segments: Sequence[SanitizedSegment],
    freshness: SourceFreshness,
    config: AgentConfig,
) -> Tuple[QuestionAnswer, ...]:
    """Answer each question with verified evidence or abstain explicitly."""
    answers: List[QuestionAnswer] = []

    for q in questions:
        # Policy gate 1: stale source abstention
        if freshness.is_stale and config.stale_policy == "abstain":
            answers.append(
                QuestionAnswer(
                    question_id=q.question_id,
                    question=q.question,
                    answered=False,
                    abstained=True,
                    abstention_reason=AbstentionReason.STALE_SOURCE,
                    answer_text=None,
                    supporting_claim_ids=(),
                    evidence_spans=(),
                    confidence=0.0,
                )
            )
            continue

        metric = _infer_metric_from_question(q)
        period = _infer_period_from_question(q)
        asks_guidance = bool(_GUIDANCE_Q_RE.search(q.question))
        asks_contradiction = bool(_CONTRADICTION_Q_RE.search(q.question))

        # Policy gate 2: metric must be identifiable and present in verified claims
        if metric is None:
            reason = (
                AbstentionReason.PROMPT_INJECTION_QUARANTINED
                if _quarantined_mentions_topic(sanitized_segments, None, q.question)
                else AbstentionReason.NO_SUPPORTING_EVIDENCE
            )
            answers.append(
                QuestionAnswer(
                    question_id=q.question_id,
                    question=q.question,
                    answered=False,
                    abstained=True,
                    abstention_reason=reason,
                    answer_text=None,
                    supporting_claim_ids=(),
                    evidence_spans=(),
                    confidence=0.0,
                )
            )
            continue

        matching = [c for c in claims if c.metric_name == metric]
        if period is not None:
            matching = [c for c in matching if c.fiscal_period == period]
        if asks_guidance:
            guidance_only = [c for c in matching if c.claim_type == ClaimType.FORWARD_GUIDANCE]
            if guidance_only:
                matching = guidance_only

        if not matching:
            reason = (
                AbstentionReason.PROMPT_INJECTION_QUARANTINED
                if _quarantined_mentions_topic(sanitized_segments, metric, q.question)
                else AbstentionReason.NO_SUPPORTING_EVIDENCE
            )
            answers.append(
                QuestionAnswer(
                    question_id=q.question_id,
                    question=q.question,
                    answered=False,
                    abstained=True,
                    abstention_reason=reason,
                    answer_text=None,
                    supporting_claim_ids=(),
                    evidence_spans=(),
                    confidence=0.0,
                )
            )
            continue

        # Check matching guidance comparison for contradictions
        matching_comps = [
            comp
            for comp in comparisons
            if comp.metric_name == metric and (period is None or comp.fiscal_period == period)
        ]
        contradictory_comps = [comp for comp in matching_comps if comp.contradiction_detected]

        if contradictory_comps and not asks_contradiction:
            comp = contradictory_comps[0]
            answers.append(
                QuestionAnswer(
                    question_id=q.question_id,
                    question=q.question,
                    answered=False,
                    abstained=True,
                    abstention_reason=AbstentionReason.AMBIGUOUS_OR_CONTRADICTORY,
                    answer_text=None,
                    supporting_claim_ids=comp.contradicting_claim_ids,
                    evidence_spans=comp.evidence_spans,
                    confidence=0.0,
                )
            )
            continue

        if contradictory_comps and asks_contradiction:
            comp = contradictory_comps[0]
            parts = [
                f"{c.evidence.speaker} ({c.evidence.section.value}) stated "
                f"{_format_value(c.normalized_low, c.normalized_high, c.normalized_unit)}"
                for c in matching
                if c.claim_id in comp.contradicting_claim_ids
            ]
            answers.append(
                QuestionAnswer(
                    question_id=q.question_id,
                    question=q.question,
                    answered=True,
                    abstained=False,
                    abstention_reason=None,
                    answer_text=(
                        f"Contradictory {metric} guidance detected for {comp.fiscal_period}: "
                        + "; ".join(parts)
                        + "."
                    ),
                    supporting_claim_ids=comp.contradicting_claim_ids,
                    evidence_spans=comp.evidence_spans,
                    confidence=0.9,
                )
            )
            continue

        # Build verified grounded answer
        chosen = matching
        if asks_guidance and matching_comps:
            comp = matching_comps[0]
            val_str = _format_value(comp.current_low, comp.current_high, comp.normalized_unit)
            if comp.prior_midpoint is not None and comp.delta_midpoint is not None:
                prior_str = _format_value(
                    comp.prior_low if comp.prior_low is not None else comp.prior_midpoint,
                    comp.prior_high if comp.prior_high is not None else comp.prior_midpoint,
                    comp.normalized_unit,
                )
                ans_text = (
                    f"{comp.fiscal_period} {metric} guidance is {val_str} "
                    f"({comp.direction.value} vs prior guidance of {prior_str}; "
                    f"midpoint delta {comp.delta_midpoint:+.4g})."
                )
            else:
                ans_text = (
                    f"{comp.fiscal_period} {metric} guidance is {val_str} "
                    f"({comp.direction.value}; no prior guidance baseline)."
                )
            c_ids = comp.supporting_claim_ids
            spans = comp.evidence_spans
        else:
            primary = chosen[0]
            val_str = _format_value(
                primary.normalized_low, primary.normalized_high, primary.normalized_unit
            )
            basis_tag = (
                f" ({primary.accounting_basis.value})"
                if primary.accounting_basis.value != "UNSPECIFIED"
                else ""
            )
            ans_text = (
                f"{primary.fiscal_period} {metric}{basis_tag} "
                f"({primary.claim_type.value}) is {val_str}, cited by "
                f"{primary.evidence.speaker} ({primary.evidence.segment_id})."
            )
            c_ids = (primary.claim_id,)
            spans = (primary.evidence,)

        max_unc = UncertaintyLevel.LOW
        for c in chosen:
            if c.claim_id in c_ids:
                if c.uncertainty_level == UncertaintyLevel.HIGH:
                    max_unc = UncertaintyLevel.HIGH
                elif c.uncertainty_level == UncertaintyLevel.MEDIUM and max_unc == UncertaintyLevel.LOW:
                    max_unc = UncertaintyLevel.MEDIUM

        conf = 1.0 if max_unc == UncertaintyLevel.LOW else (0.8 if max_unc == UncertaintyLevel.MEDIUM else 0.65)
        answers.append(
            QuestionAnswer(
                question_id=q.question_id,
                question=q.question,
                answered=True,
                abstained=False,
                abstention_reason=None,
                answer_text=ans_text,
                supporting_claim_ids=c_ids,
                evidence_spans=spans,
                confidence=conf,
            )
        )

    return tuple(answers)
