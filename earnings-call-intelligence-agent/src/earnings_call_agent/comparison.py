"""Pure domain comparison of current vs prior guidance and contradiction detection."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from .contracts import (
    AccountingBasis,
    CanonicalUnit,
    ClaimType,
    ExtractedClaim,
    GuidanceComparison,
    GuidanceDirection,
    PriorGuidanceRecord,
    UncertaintyLevel,
    stable_id,
)


def _claims_contradict(
    claims: Sequence[ExtractedClaim],
    tolerance_pct: float,
) -> bool:
    """Return True if two or more guidance claims in the same group materially conflict."""
    if len(claims) < 2:
        return False
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a, b = claims[i], claims[j]
            # Disjoint numeric ranges are always contradictory
            if a.normalized_high < b.normalized_low or b.normalized_high < a.normalized_low:
                return True
            denom = max(abs(a.normalized_point), abs(b.normalized_point), 1e-9)
            rel_diff_pct = (abs(a.normalized_point - b.normalized_point) / denom) * 100.0
            if rel_diff_pct > tolerance_pct:
                return True
    return False


def _match_prior_guidance(
    metric_name: str,
    fiscal_period: str,
    accounting_basis: AccountingBasis,
    normalized_unit: CanonicalUnit,
    prior_records: Sequence[PriorGuidanceRecord],
) -> Tuple[Optional[PriorGuidanceRecord], List[str]]:
    """Find matching prior guidance record and return any compatibility flags."""
    flags: List[str] = []

    # 1. Exact match on metric, period, accounting basis, and unit
    for rec in prior_records:
        if (
            rec.metric_name == metric_name
            and rec.fiscal_period == fiscal_period
            and rec.accounting_basis == accounting_basis
            and rec.normalized_unit == normalized_unit
        ):
            return rec, flags

    # 2. Match if either side left accounting basis UNSPECIFIED (flag explicitly)
    for rec in prior_records:
        if (
            rec.metric_name == metric_name
            and rec.fiscal_period == fiscal_period
            and rec.normalized_unit == normalized_unit
            and (
                rec.accounting_basis == AccountingBasis.UNSPECIFIED
                or accounting_basis == AccountingBasis.UNSPECIFIED
            )
        ):
            flags.append("ACCOUNTING_BASIS_ASSUMED_MATCH")
            return rec, flags

    # 3. Check if metric+period exists in prior guidance with a different unit
    for rec in prior_records:
        if rec.metric_name == metric_name and rec.fiscal_period == fiscal_period:
            if rec.normalized_unit != normalized_unit:
                flags.append("PRIOR_UNIT_MISMATCH")
                return None, flags

    return None, flags


def compare_guidance(
    claims: Sequence[ExtractedClaim],
    prior_guidance: Sequence[PriorGuidanceRecord],
    contradiction_tolerance_pct: float = 0.5,
    reaffirm_tolerance_pct: float = 0.5,
    is_stale_source: bool = False,
) -> Tuple[GuidanceComparison, ...]:
    """Compare extracted forward guidance against prior guidance and flag uncertainty."""
    guidance_claims = [c for c in claims if c.claim_type == ClaimType.FORWARD_GUIDANCE]
    grouped: Dict[
        Tuple[str, str, AccountingBasis, CanonicalUnit], List[ExtractedClaim]
    ] = defaultdict(list)

    for claim in guidance_claims:
        key = (
            claim.metric_name,
            claim.fiscal_period,
            claim.accounting_basis,
            claim.normalized_unit,
        )
        grouped[key].append(claim)

    comparisons: List[GuidanceComparison] = []

    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[1], k[2].value, k[3].value)):
        metric_name, fiscal_period, basis, norm_unit = key
        group_claims = grouped[key]
        flags: List[str] = []

        if is_stale_source:
            flags.append("STALE_SOURCE")

        # Uncertainty cues from claims
        levels = {c.uncertainty_level for c in group_claims}
        if UncertaintyLevel.HIGH in levels:
            flags.append("HIGH_UNCERTAINTY_LANGUAGE")
        elif UncertaintyLevel.MEDIUM in levels:
            flags.append("MEDIUM_UNCERTAINTY_LANGUAGE")
        if any(c.is_approximate for c in group_claims):
            flags.append("APPROXIMATE_VALUE")

        contradiction = _claims_contradict(group_claims, contradiction_tolerance_pct)
        contradicting_ids: Tuple[str, ...] = ()
        if contradiction:
            contradicting_ids = tuple(c.claim_id for c in group_claims)
            flags.append("INTRA_CALL_CONTRADICTION")
            speakers = {c.evidence.speaker for c in group_claims}
            if len(speakers) > 1:
                flags.append("SPEAKER_DISAGREEMENT")
            sections = {c.evidence.section for c in group_claims}
            if len(sections) > 1:
                flags.append("PREPARED_VS_QA_DIVERGENCE")

        # Current bounds envelope
        curr_low = min(c.normalized_low for c in group_claims)
        curr_high = max(c.normalized_high for c in group_claims)
        curr_mid = round((curr_low + curr_high) / 2.0, 6)

        prior_rec, match_flags = _match_prior_guidance(
            metric_name, fiscal_period, basis, norm_unit, prior_guidance
        )
        flags.extend(match_flags)

        prior_low: Optional[float] = None
        prior_high: Optional[float] = None
        prior_mid: Optional[float] = None
        delta_mid: Optional[float] = None
        delta_pct: Optional[float] = None
        prior_id: Optional[str] = None

        if prior_rec is not None:
            prior_id = prior_rec.guidance_id
            prior_low = prior_rec.normalized_low
            prior_high = prior_rec.normalized_high
            prior_mid = prior_rec.normalized_midpoint
            delta_mid = round(curr_mid - prior_mid, 6)
            if abs(prior_mid) > 1e-9:
                delta_pct = round((delta_mid / abs(prior_mid)) * 100.0, 4)
        else:
            if "PRIOR_UNIT_MISMATCH" not in flags:
                flags.append("NO_PRIOR_GUIDANCE_BASELINE")

        if contradiction:
            direction = GuidanceDirection.CONTRADICTORY
        elif prior_rec is None:
            direction = GuidanceDirection.INTRODUCED
        else:
            assert prior_low is not None and prior_high is not None and prior_mid is not None
            assert delta_mid is not None
            rel_shift = abs(delta_pct) if delta_pct is not None else abs(delta_mid)
            if rel_shift > reaffirm_tolerance_pct:
                direction = (
                    GuidanceDirection.RAISED if delta_mid > 0 else GuidanceDirection.LOWERED
                )
            else:
                prior_width = prior_high - prior_low
                curr_width = curr_high - curr_low
                if curr_width < prior_width - 1e-6:
                    direction = GuidanceDirection.NARROWED
                elif curr_width > prior_width + 1e-6:
                    direction = GuidanceDirection.WIDENED
                else:
                    direction = GuidanceDirection.REAFFIRMED

        supporting_ids = tuple(c.claim_id for c in group_claims)
        evidence_spans = tuple(c.evidence for c in group_claims)
        comp_id = stable_id(
            "cmp",
            [metric_name, fiscal_period, basis.value, norm_unit.value, list(supporting_ids)],
        )

        comparisons.append(
            GuidanceComparison(
                comparison_id=comp_id,
                metric_name=metric_name,
                fiscal_period=fiscal_period,
                accounting_basis=basis,
                normalized_unit=norm_unit,
                prior_low=prior_low,
                prior_high=prior_high,
                prior_midpoint=prior_mid,
                current_low=curr_low,
                current_high=curr_high,
                current_midpoint=curr_mid,
                delta_midpoint=delta_mid,
                delta_pct=delta_pct,
                direction=direction,
                uncertainty_flags=tuple(sorted(set(flags))),
                contradiction_detected=contradiction,
                contradicting_claim_ids=contradicting_ids,
                supporting_claim_ids=supporting_ids,
                prior_guidance_id=prior_id,
                evidence_spans=evidence_spans,
            )
        )

    return tuple(comparisons)
