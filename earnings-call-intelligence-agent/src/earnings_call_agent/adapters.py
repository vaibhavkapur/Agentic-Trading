"""Adapter boundaries for optional LLM extractors and sibling Trading-Agentic consumers.

All external/model proposals pass through deterministic budget enforcement and
verbatim span verification before entering the domain state. No adapter is allowed
to trigger live orders or external side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from .contracts import (
    AccountingBasis,
    AnalysisReport,
    BudgetExceededError,
    ClaimType,
    EvidenceVerificationError,
    ExtractedClaim,
    UncertaintyLevel,
    build_verified_evidence,
    normalize_fiscal_period,
    normalize_unit_and_value,
    stable_id,
)
from .security import SanitizedSegment


@dataclass(frozen=True)
class ProposedClaim:
    """Untrusted claim proposal returned by an optional LLM provider."""

    segment_id: str
    char_start: int
    char_end: int
    quoted_text: str
    claim_type: str
    metric_name: str
    fiscal_period: str
    accounting_basis: str
    raw_value_text: str
    raw_unit: str
    value_low: float
    value_high: float
    is_approximate: bool = False
    uncertainty_cues: Tuple[str, ...] = ()
    tokens_used: int = 100


class LLMExtractorProtocol(Protocol):
    """Typed boundary for optional LLM-backed extraction providers."""

    def propose_claims(
        self,
        sanitized_segment: SanitizedSegment,
        default_fiscal_period: str,
        seed: int,
    ) -> Sequence[ProposedClaim]:
        ...


class MockLLMExtractor:
    """Deterministic offline mock provider for testing hybrid mode and verification gates."""

    def __init__(
        self,
        canned_proposals: Optional[Dict[str, Sequence[ProposedClaim]]] = None,
        tokens_per_call: int = 150,
    ) -> None:
        self._proposals = canned_proposals or {}
        self._tokens_per_call = tokens_per_call

    def propose_claims(
        self,
        sanitized_segment: SanitizedSegment,
        default_fiscal_period: str,
        seed: int,
    ) -> Sequence[ProposedClaim]:
        del default_fiscal_period, seed
        items = self._proposals.get(sanitized_segment.segment.segment_id, ())
        return tuple(
            ProposedClaim(
                segment_id=p.segment_id,
                char_start=p.char_start,
                char_end=p.char_end,
                quoted_text=p.quoted_text,
                claim_type=p.claim_type,
                metric_name=p.metric_name,
                fiscal_period=p.fiscal_period,
                accounting_basis=p.accounting_basis,
                raw_value_text=p.raw_value_text,
                raw_unit=p.raw_unit,
                value_low=p.value_low,
                value_high=p.value_high,
                is_approximate=p.is_approximate,
                uncertainty_cues=p.uncertainty_cues,
                tokens_used=p.tokens_used or self._tokens_per_call,
            )
            for p in items
        )


@dataclass
class BudgetedVerificationResult:
    verified_claims: Tuple[ExtractedClaim, ...]
    rejected_count: int
    calls_used: int
    tokens_used: int


def run_budgeted_llm_extraction(
    provider: LLMExtractorProtocol,
    sanitized_segments: Sequence[SanitizedSegment],
    default_fiscal_period: str,
    published_at: datetime,
    max_calls: int,
    max_tokens: int,
    seed: int,
) -> BudgetedVerificationResult:
    """Invoke an optional LLM provider under fixed budgets and verify every span verbatim."""
    verified: List[ExtractedClaim] = []
    rejected = 0
    calls_used = 0
    tokens_used = 0

    for san_seg in sanitized_segments:
        if san_seg.fully_quarantined:
            continue
        if calls_used >= max_calls:
            raise BudgetExceededError(
                "LLM_CALL_BUDGET_EXCEEDED",
                f"Exceeded max_llm_calls budget ({max_calls}).",
                {"calls_used": calls_used, "max_llm_calls": max_calls},
            )
        calls_used += 1
        proposals = provider.propose_claims(san_seg, default_fiscal_period, seed)
        for p in proposals:
            tokens_used += max(0, int(p.tokens_used))
            if tokens_used > max_tokens:
                raise BudgetExceededError(
                    "LLM_TOKEN_BUDGET_EXCEEDED",
                    f"Exceeded max_llm_tokens budget ({max_tokens}).",
                    {"tokens_used": tokens_used, "max_llm_tokens": max_tokens},
                )
            # Reject proposals falling inside quarantined ranges
            in_quarantine = any(
                not (p.char_end <= qs or p.char_start >= qe)
                for qs, qe in san_seg.quarantined_spans
            )
            if in_quarantine or p.segment_id != san_seg.segment.segment_id:
                rejected += 1
                continue
            try:
                evidence = build_verified_evidence(
                    segment=san_seg.segment,
                    char_start=p.char_start,
                    char_end=p.char_end,
                    source_published_at=published_at,
                    expected_quote=p.quoted_text,
                )
                norm_unit, norm_low = normalize_unit_and_value(p.raw_unit, p.value_low)
                _, norm_high = normalize_unit_and_value(p.raw_unit, p.value_high)
                if norm_low > norm_high:
                    rejected += 1
                    continue
                period = normalize_fiscal_period(p.fiscal_period)
                ctype = ClaimType(p.claim_type)
                basis = AccountingBasis(p.accounting_basis)
            except (EvidenceVerificationError, ValueError, Exception):
                rejected += 1
                continue

            norm_point = round((norm_low + norm_high) / 2.0, 6)
            cid = stable_id(
                "clm",
                [
                    san_seg.segment.segment_id,
                    p.char_start,
                    p.char_end,
                    p.metric_name.lower(),
                    period,
                    basis.value,
                    norm_unit.value,
                    norm_low,
                    norm_high,
                ],
            )
            unc_level = (
                UncertaintyLevel.HIGH
                if len(p.uncertainty_cues) >= 2
                else (
                    UncertaintyLevel.MEDIUM
                    if p.is_approximate or len(p.uncertainty_cues) == 1
                    else UncertaintyLevel.LOW
                )
            )
            verified.append(
                ExtractedClaim(
                    claim_id=cid,
                    claim_type=ctype,
                    metric_name=p.metric_name.lower(),
                    fiscal_period=period,
                    accounting_basis=basis,
                    raw_value_text=p.raw_value_text,
                    raw_unit=p.raw_unit,
                    normalized_unit=norm_unit,
                    normalized_low=norm_low,
                    normalized_high=norm_high,
                    normalized_point=norm_point,
                    is_range=abs(norm_high - norm_low) > 1e-9,
                    is_approximate=p.is_approximate,
                    uncertainty_level=unc_level,
                    uncertainty_cues=tuple(sorted(set(p.uncertainty_cues))),
                    evidence=evidence,
                    extraction_method="llm_adapter_verified",
                )
            )

    return BudgetedVerificationResult(
        verified_claims=tuple(verified),
        rejected_count=rejected,
        calls_used=calls_used,
        tokens_used=tokens_used,
    )


def export_research_note_envelope(report: AnalysisReport) -> Dict[str, Any]:
    """Export an independent research-note payload for sibling Trading-Agentic modules.

    Strictly read-only research artifact; trade_action_permitted is hardcoded to False.
    """
    return {
        "envelope_version": "1.0.0",
        "source_agent": "earnings-call-intelligence-agent",
        "execution_mode": "research_only_no_orders",
        "trade_action_permitted": False,
        "run_id": report.run_id,
        "ticker": report.ticker,
        "company_name": report.company_name,
        "fiscal_period": report.fiscal_period,
        "as_of_timestamp": report.as_of_timestamp,
        "is_stale_source": report.source_freshness["is_stale"],
        "prompt_injection_detected": len(report.prompt_injection_events) > 0,
        "guidance_summary": [
            {
                "comparison_id": g.comparison_id,
                "metric_name": g.metric_name,
                "fiscal_period": g.fiscal_period,
                "direction": g.direction.value,
                "normalized_unit": g.normalized_unit.value,
                "current_midpoint": g.current_midpoint,
                "delta_midpoint": g.delta_midpoint,
                "contradiction_detected": g.contradiction_detected,
                "uncertainty_flags": list(g.uncertainty_flags),
                "evidence_count": len(g.evidence_spans),
            }
            for g in report.guidance_comparisons
        ],
        "verified_claim_count": report.diagnostics.claims_verified,
        "abstained_question_count": report.diagnostics.questions_abstained,
    }
