"""Pure domain logic for vintage revision comparison, conflict detection, and surprises."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from .config import AgentConfig
from .errors import UnitMismatchError
from .models import (
    AbstentionRecord,
    ConflictRecord,
    ConsensusEstimate,
    ExtractedFigure,
    MacroRelease,
    RevisionDiff,
    SurpriseCalculation,
    convert_unit,
    stable_id,
)


@dataclass(frozen=True)
class ReconciliationOutcome:
    """Deterministic result of reconciling vintages, conflicts, revisions, and surprises."""

    latest_figures: Tuple[ExtractedFigure, ...]
    revisions: Tuple[RevisionDiff, ...]
    surprises: Tuple[SurpriseCalculation, ...]
    conflicts: Tuple[ConflictRecord, ...]
    abstentions: Tuple[AbstentionRecord, ...]


def _values_conflict(a: Decimal, b: Decimal, tolerance_ratio: Decimal) -> bool:
    diff = abs(a - b)
    scale = max(abs(a), abs(b), Decimal("1"))
    return diff > (scale * tolerance_ratio)


def _direction(delta: Decimal, tolerance: Decimal, pos: str, neg: str, zero: str) -> str:
    if abs(delta) <= tolerance:
        return zero
    return pos if delta > Decimal("0") else neg


def reconcile_figures_and_surprises(
    releases: Sequence[MacroRelease],
    extracted_figures: Sequence[ExtractedFigure],
    consensus_estimates: Sequence[ConsensusEstimate],
    config: AgentConfig,
) -> ReconciliationOutcome:
    """Reconcile multi-source figures, compute vintage revisions, and evaluate surprises.

    Rules:
    1. Figures for the same `(series_id, reference_period)` from the same `release_id`
       with ascending `vintage_sequence` represent official revisions -> compute `RevisionDiff`.
    2. Figures for the same `(series_id, reference_period)` from DIFFERENT `release_id`s
       (or competing sources) are cross-checked for agreement:
       - If units are incompatible -> record `ConflictRecord(unit_mismatch)` + abstain.
       - If values diverge beyond `conflict_tolerance_ratio` -> record
         `ConflictRecord(conflicting_reports)` + abstain (never guess or average).
    3. For each clean latest figure, look up the latest pre-release consensus benchmark
       for `(series_id, reference_period)` (where `consensus.published_at <= release.available_at`
       or fallback to latest available consensus as of cutoff):
       - If units match or are explicitly convertible -> compute `SurpriseCalculation`.
       - If units are incompatible -> record `ConflictRecord(unit_mismatch)` + abstain.
       - If no consensus is available -> abstain on surprise (never fabricate consensus).
    """
    release_lookup: Dict[Tuple[str, str], MacroRelease] = {
        (r.release_id, r.vintage_id): r for r in releases
    }

    grouped: Dict[Tuple[str, str], List[ExtractedFigure]] = {}
    for fig in extracted_figures:
        grouped.setdefault((fig.series_id, fig.reference_period), []).append(fig)

    consensus_by_key: Dict[Tuple[str, str], List[ConsensusEstimate]] = {}
    for est in consensus_estimates:
        consensus_by_key.setdefault((est.series_id, est.reference_period), []).append(est)
    for key in consensus_by_key:
        consensus_by_key[key].sort(key=lambda c: (c.published_at, c.consensus_id))

    latest_figures: List[ExtractedFigure] = []
    revisions: List[RevisionDiff] = []
    surprises: List[SurpriseCalculation] = []
    conflicts: List[ConflictRecord] = []
    abstentions: List[AbstentionRecord] = []

    for series_id, ref_period in sorted(grouped.keys()):
        figs = grouped[(series_id, ref_period)]

        # Partition by release_id so distinct vintages of the same release form a revision chain,
        # while distinct release_ids for the exact same (series_id, reference_period) are compared for conflict.
        by_release_id: Dict[str, List[ExtractedFigure]] = {}
        for f in figs:
            by_release_id.setdefault(f.release_id, []).append(f)

        latest_per_release: List[ExtractedFigure] = []
        chain_unit_conflict = False

        for rel_id in sorted(by_release_id.keys()):
            chain = by_release_id[rel_id]
            chain.sort(
                key=lambda f: (
                    release_lookup[(f.release_id, f.vintage_id)].vintage_sequence,
                    release_lookup[(f.release_id, f.vintage_id)].available_at,
                    f.vintage_id,
                )
            )
            # Compute consecutive vintage diffs within this release_id
            for prior, current in zip(chain[:-1], chain[1:]):
                try:
                    prior_converted = convert_unit(
                        prior.value,
                        prior.unit,
                        current.unit,
                        allow_conversion=config.enable_unit_auto_conversion,
                    )
                except UnitMismatchError:
                    chain_unit_conflict = True
                    cid = stable_id(
                        "cnf",
                        {
                            "type": "unit_mismatch",
                            "series_id": series_id,
                            "reference_period": ref_period,
                            "prior": prior.figure_id,
                            "current": current.figure_id,
                        },
                    )
                    conflicts.append(
                        ConflictRecord(
                            conflict_id=cid,
                            conflict_type="unit_mismatch",
                            series_id=series_id,
                            reference_period=ref_period,
                            description=(
                                f"Cannot compare vintage {prior.vintage_id} ({prior.unit.value}) "
                                f"with vintage {current.vintage_id} ({current.unit.value})"
                            ),
                            involved_release_ids=(
                                f"{prior.release_id}:{prior.vintage_id}",
                                f"{current.release_id}:{current.vintage_id}",
                            ),
                            involved_values=(
                                f"{format(prior.value, 'f')} {prior.unit.value}",
                                f"{format(current.value, 'f')} {current.unit.value}",
                            ),
                            citations=(prior.citation, current.citation),
                        )
                    )
                    abstentions.append(
                        AbstentionRecord(
                            abstention_id=stable_id(
                                "abs", {"scope": f"revision:{series_id}:{ref_period}", "cid": cid}
                            ),
                            scope=f"revision:{series_id}:{ref_period}",
                            reason_code="UNIT_MISMATCH",
                            explanation=(
                                f"Abstained from revision diff for {series_id} ({ref_period}) "
                                f"due to incompatible units: {prior.unit.value} vs {current.unit.value}."
                            ),
                            related_conflict_id=cid,
                        )
                    )
                    continue

                delta = current.value - prior_converted
                direction = _direction(
                    delta,
                    config.numeric_tolerance,
                    "upward_revision",
                    "downward_revision",
                    "unchanged",
                )
                revisions.append(
                    RevisionDiff(
                        revision_id=stable_id(
                            "rev",
                            {
                                "series_id": series_id,
                                "reference_period": ref_period,
                                "prior_vintage_id": prior.vintage_id,
                                "current_vintage_id": current.vintage_id,
                                "delta": format(delta, "f"),
                            },
                        ),
                        series_id=series_id,
                        reference_period=ref_period,
                        prior_vintage_id=prior.vintage_id,
                        current_vintage_id=current.vintage_id,
                        prior_value=prior_converted,
                        current_value=current.value,
                        delta=delta,
                        unit=current.unit,
                        direction=direction,
                        prior_citation=prior.citation,
                        current_citation=current.citation,
                    )
                )
            latest_per_release.append(chain[-1])

        if chain_unit_conflict:
            continue

        # Cross-source conflict check when multiple independent releases report the same series & period
        if len(latest_per_release) > 1:
            anchor = latest_per_release[0]
            has_conflict = False
            conflict_kind = "conflicting_reports"
            for other in latest_per_release[1:]:
                try:
                    other_val = convert_unit(
                        other.value,
                        other.unit,
                        anchor.unit,
                        allow_conversion=config.enable_unit_auto_conversion,
                    )
                except UnitMismatchError:
                    has_conflict = True
                    conflict_kind = "unit_mismatch"
                    break
                if _values_conflict(anchor.value, other_val, config.conflict_tolerance_ratio):
                    has_conflict = True
                    conflict_kind = "conflicting_reports"
                    break

            if has_conflict:
                involved_rels = tuple(f"{f.release_id}:{f.vintage_id}" for f in latest_per_release)
                involved_vals = tuple(
                    f"{format(f.value, 'f')} {f.unit.value} ({f.source_id})"
                    for f in latest_per_release
                )
                involved_cits = tuple(f.citation for f in latest_per_release)
                cid = stable_id(
                    "cnf",
                    {
                        "type": conflict_kind,
                        "series_id": series_id,
                        "reference_period": ref_period,
                        "releases": list(involved_rels),
                    },
                )
                conflicts.append(
                    ConflictRecord(
                        conflict_id=cid,
                        conflict_type=conflict_kind,
                        series_id=series_id,
                        reference_period=ref_period,
                        description=(
                            f"Competing reports disagree for {series_id} ({ref_period}): "
                            + "; ".join(involved_vals)
                        ),
                        involved_release_ids=involved_rels,
                        involved_values=involved_vals,
                        citations=involved_cits,
                    )
                )
                if config.brief_policy.abstain_on_unresolved_conflict:
                    abstentions.append(
                        AbstentionRecord(
                            abstention_id=stable_id(
                                "abs", {"scope": f"metric:{series_id}:{ref_period}", "cid": cid}
                            ),
                            scope=f"metric:{series_id}:{ref_period}",
                            reason_code=conflict_kind.upper(),
                            explanation=(
                                f"Abstained from selecting a canonical value or surprise for "
                                f"{series_id} ({ref_period}) due to unresolved {conflict_kind}."
                            ),
                            related_conflict_id=cid,
                        )
                    )
                continue

        # All sources agree (or single release chain): choose most recent available release
        latest_per_release.sort(
            key=lambda f: (
                release_lookup[(f.release_id, f.vintage_id)].available_at,
                f.release_id,
                f.vintage_id,
            )
        )
        canonical = latest_per_release[-1]
        latest_figures.append(canonical)

        # Evaluate surprise against pre-release consensus
        candidates = consensus_by_key.get((series_id, ref_period), [])
        canonical_release = release_lookup[(canonical.release_id, canonical.vintage_id)]
        pre_release_consensus = [
            c for c in candidates if c.published_at <= canonical_release.available_at
        ]
        chosen_consensus: Optional[ConsensusEstimate] = (
            pre_release_consensus[-1] if pre_release_consensus else None
        )

        if chosen_consensus is None:
            if config.brief_policy.abstain_on_missing_consensus_for_surprise:
                abstentions.append(
                    AbstentionRecord(
                        abstention_id=stable_id(
                            "abs",
                            {
                                "scope": f"surprise:{series_id}:{ref_period}",
                                "reason": "MISSING_CONSENSUS",
                            },
                        ),
                        scope=f"surprise:{series_id}:{ref_period}",
                        reason_code="MISSING_CONSENSUS",
                        explanation=(
                            f"No pre-release consensus benchmark archived for {series_id} "
                            f"({ref_period}); abstained rather than fabricating consensus."
                        ),
                    )
                )
            continue

        try:
            converted_from = (
                chosen_consensus.unit if chosen_consensus.unit != canonical.unit else None
            )
            consensus_in_actual_unit = convert_unit(
                chosen_consensus.expected_value,
                chosen_consensus.unit,
                canonical.unit,
                allow_conversion=config.enable_unit_auto_conversion,
            )
        except UnitMismatchError:
            cid = stable_id(
                "cnf",
                {
                    "type": "unit_mismatch",
                    "series_id": series_id,
                    "reference_period": ref_period,
                    "actual_unit": canonical.unit.value,
                    "consensus_unit": chosen_consensus.unit.value,
                    "consensus_id": chosen_consensus.consensus_id,
                },
            )
            conflicts.append(
                ConflictRecord(
                    conflict_id=cid,
                    conflict_type="unit_mismatch",
                    series_id=series_id,
                    reference_period=ref_period,
                    description=(
                        f"Unit mismatch between actual {series_id} ({canonical.unit.value}) "
                        f"and consensus {chosen_consensus.consensus_id} ({chosen_consensus.unit.value})"
                    ),
                    involved_release_ids=(
                        f"{canonical.release_id}:{canonical.vintage_id}",
                        chosen_consensus.consensus_id,
                    ),
                    involved_values=(
                        f"{format(canonical.value, 'f')} {canonical.unit.value}",
                        f"{format(chosen_consensus.expected_value, 'f')} {chosen_consensus.unit.value}",
                    ),
                    citations=(canonical.citation,),
                )
            )
            if config.brief_policy.abstain_on_unit_mismatch:
                abstentions.append(
                    AbstentionRecord(
                        abstention_id=stable_id(
                            "abs", {"scope": f"surprise:{series_id}:{ref_period}", "cid": cid}
                        ),
                        scope=f"surprise:{series_id}:{ref_period}",
                        reason_code="UNIT_MISMATCH",
                        explanation=(
                            f"Abstained from surprise calculation for {series_id} ({ref_period}) "
                            f"because actual unit '{canonical.unit.value}' is incompatible with "
                            f"consensus unit '{chosen_consensus.unit.value}'."
                        ),
                        related_conflict_id=cid,
                    )
                )
            continue

        surprise_val = canonical.value - consensus_in_actual_unit
        direction = _direction(
            surprise_val,
            config.numeric_tolerance,
            "above_consensus",
            "below_consensus",
            "in_line",
        )
        surprises.append(
            SurpriseCalculation(
                surprise_id=stable_id(
                    "srp",
                    {
                        "series_id": series_id,
                        "reference_period": ref_period,
                        "actual_figure_id": canonical.figure_id,
                        "consensus_id": chosen_consensus.consensus_id,
                    },
                ),
                series_id=series_id,
                reference_period=ref_period,
                actual_value=canonical.value,
                consensus_value=consensus_in_actual_unit,
                surprise_value=surprise_val,
                unit=canonical.unit,
                direction=direction,
                actual_figure_id=canonical.figure_id,
                consensus_id=chosen_consensus.consensus_id,
                converted_from_unit=converted_from,
                citation=canonical.citation,
            )
        )

    return ReconciliationOutcome(
        latest_figures=tuple(latest_figures),
        revisions=tuple(revisions),
        surprises=tuple(surprises),
        conflicts=tuple(conflicts),
        abstentions=tuple(abstentions),
    )
