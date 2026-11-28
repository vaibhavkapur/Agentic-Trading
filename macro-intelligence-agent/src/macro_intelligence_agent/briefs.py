"""Scenario brief generation separating optional model adapters from deterministic policy.

Any narrative summary or hypothesis framing is strictly constrained by verified evidence
and checked afterward by `verification.verify_brief`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Protocol, Sequence, Tuple

from .config import AgentConfig
from .errors import BudgetExceededError
from .models import (
    AbstentionRecord,
    Citation,
    ConflictRecord,
    ExtractedFigure,
    PolicyLanguageSignal,
    PolicyStance,
    RevisionDiff,
    ScenarioBrief,
    ScenarioHypothesis,
    SurpriseCalculation,
    UntrustedInstructionFinding,
    format_utc_timestamp,
    stable_id,
)

LIMITATIONS_NOTICE = (
    "Research and educational prototype only. All macro interpretations are structured "
    "hypotheses grounded in archived synthetic/public releases as of the stated UTC cutoff, "
    "not predictions, market-impact forecasts, or trading recommendations."
)


class SummarizerAdapter(Protocol):
    """Typed boundary for optional LLM or deterministic mock narrative synthesis."""

    provider_name: str
    calls_used: int

    def synthesize_summary(
        self,
        *,
        series_group: str,
        as_of_utc: datetime,
        figures: Sequence[ExtractedFigure],
        surprises: Sequence[SurpriseCalculation],
        revisions: Sequence[RevisionDiff],
        policy_signals: Sequence[PolicyLanguageSignal],
        conflicts: Sequence[ConflictRecord],
        abstentions: Sequence[AbstentionRecord],
        security_findings: Sequence[UntrustedInstructionFinding],
    ) -> str:
        ...


class DeterministicMockSummarizer:
    """Offline, zero-network, fixed-budget summarizer for reproducible briefs."""

    def __init__(self, *, max_calls: int, max_output_tokens: int, seed: int) -> None:
        self.provider_name = "deterministic_mock"
        self._max_calls = max_calls
        self._max_output_tokens = max_output_tokens
        self._seed = seed
        self.calls_used = 0

    def synthesize_summary(
        self,
        *,
        series_group: str,
        as_of_utc: datetime,
        figures: Sequence[ExtractedFigure],
        surprises: Sequence[SurpriseCalculation],
        revisions: Sequence[RevisionDiff],
        policy_signals: Sequence[PolicyLanguageSignal],
        conflicts: Sequence[ConflictRecord],
        abstentions: Sequence[AbstentionRecord],
        security_findings: Sequence[UntrustedInstructionFinding],
    ) -> str:
        if self.calls_used + 1 > self._max_calls:
            raise BudgetExceededError(
                f"Model adapter call budget exceeded ({self.calls_used + 1} > {self._max_calls})",
                details={"calls_used": self.calls_used, "max_calls": self._max_calls},
            )
        self.calls_used += 1

        parts: List[str] = [
            f"As of {format_utc_timestamp(as_of_utc)} for {series_group}:"
        ]
        if not figures and abstentions:
            parts.append(
                f"No published figures available within cutoff; recorded {len(abstentions)} abstention(s)."
            )
        else:
            if figures:
                fig_str = ", ".join(
                    f"{f.series_id} ({f.reference_period})={format(f.value, 'f')} {f.unit.value} [{f.citation.citation_id}]"
                    for f in figures
                )
                parts.append(f"Verified latest figures: {fig_str}.")
            if surprises:
                srp_str = ", ".join(
                    f"{s.series_id} {s.direction} ({format(s.surprise_value, '+f')} {s.unit.value} vs consensus {format(s.consensus_value, 'f')})"
                    for s in surprises
                )
                parts.append(f"Consensus comparison: {srp_str}.")
            if revisions:
                rev_str = ", ".join(
                    f"{r.series_id} ({r.reference_period}) {r.direction} from {format(r.prior_value, 'f')} to {format(r.current_value, 'f')} ({format(r.delta, '+f')} {r.unit.value})"
                    for r in revisions
                )
                parts.append(f"Vintage revisions: {rev_str}.")
            if policy_signals:
                stances = sorted({p.stance.value for p in policy_signals})
                parts.append(
                    f"Central bank communication cues ({len(policy_signals)} cited): {', '.join(stances)}."
                )
            if conflicts:
                parts.append(
                    f"Detected {len(conflicts)} conflict/unit-mismatch issue(s); abstained on affected metrics."
                )
            if security_findings:
                parts.append(
                    f"Security guardrail quarantined {len(security_findings)} untrusted source instruction(s)."
                )

        summary = " ".join(parts)
        # Approximate token budget guard (1 token ~ 4 chars conservatively)
        max_chars = self._max_output_tokens * 4
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3].rstrip() + "..."
        return summary


def _build_deterministic_hypotheses(
    *,
    surprises: Sequence[SurpriseCalculation],
    revisions: Sequence[RevisionDiff],
    policy_signals: Sequence[PolicyLanguageSignal],
    conflicts: Sequence[ConflictRecord],
) -> Tuple[ScenarioHypothesis, ...]:
    """Generate deterministic hypothesis-framed scenarios grounded strictly in cited evidence."""
    hypotheses: List[ScenarioHypothesis] = []

    upward_surprises = [s for s in surprises if s.direction == "above_consensus"]
    hawkish_cues = [p for p in policy_signals if p.stance == PolicyStance.HAWKISH]
    dovish_cues = [p for p in policy_signals if p.stance == PolicyStance.DOVISH]
    data_dep_cues = [p for p in policy_signals if p.stance == PolicyStance.DATA_DEPENDENT]
    upward_revs = [r for r in revisions if r.direction == "upward_revision"]
    downward_revs = [r for r in revisions if r.direction == "downward_revision"]

    if upward_surprises or upward_revs or hawkish_cues:
        cits = sorted(
            {
                *(s.citation.citation_id for s in upward_surprises if s.citation),
                *(r.current_citation.citation_id for r in upward_revs),
                *(p.citation.citation_id for p in hawkish_cues),
            }
        )
        hypotheses.append(
            ScenarioHypothesis(
                hypothesis_id=stable_id("hyp", {"label": "persistence_hypothesis", "cits": cits}),
                label="Policy Restraint Persistence Hypothesis",
                condition=(
                    "If upside macro surprises, upward benchmark revisions, or elevated-inflation "
                    "policy language persist across upcoming vintages."
                ),
                interpretation=(
                    "Hypothesis: policymakers may emphasize maintaining restrictive settings longer "
                    "before adjusting rates; this reflects cited release language rather than a forecast."
                ),
                confidence_note="Qualitative hypothesis conditional on cited vintages; no market-impact estimate is made.",
                supporting_citation_ids=tuple(cits),
            )
        )

    if downward_revs or dovish_cues or data_dep_cues:
        cits = sorted(
            {
                *(r.current_citation.citation_id for r in downward_revs),
                *(p.citation.citation_id for p in dovish_cues),
                *(p.citation.citation_id for p in data_dep_cues),
            }
        )
        hypotheses.append(
            ScenarioHypothesis(
                hypothesis_id=stable_id("hyp", {"label": "disinflation_optionality", "cits": cits}),
                label="Data-Dependent Normalization Hypothesis",
                condition=(
                    "If downward core revisions or disinflation/data-dependent communication cues "
                    "are reinforced by subsequent official releases."
                ),
                interpretation=(
                    "Hypothesis: communication framing preserves optionality to calibrate policy "
                    "meeting-by-meeting as incoming vintages clarify underlying momentum."
                ),
                confidence_note="Qualitative hypothesis conditional on cited vintages; no market-impact estimate is made.",
                supporting_citation_ids=tuple(cits),
            )
        )

    if conflicts:
        cits = sorted({c.citation_id for cnf in conflicts for c in cnf.citations})
        hypotheses.append(
            ScenarioHypothesis(
                hypothesis_id=stable_id("hyp", {"label": "data_reconciliation_pending", "cits": cits}),
                label="Pending Data Reconciliation Hypothesis",
                condition=(
                    "While competing reports or incompatible units remain unresolved for one or more series."
                ),
                interpretation=(
                    "Hypothesis: macro interpretation for disputed series should remain suspended "
                    "(abstained) until an official statistical release reconciles units and figures."
                ),
                confidence_note="Explicit abstention guardrail active.",
                supporting_citation_ids=tuple(cits),
            )
        )

    return tuple(hypotheses)


def build_scenario_brief(
    *,
    as_of_utc: datetime,
    series_group: str,
    figures: Sequence[ExtractedFigure],
    surprises: Sequence[SurpriseCalculation],
    revisions: Sequence[RevisionDiff],
    policy_signals: Sequence[PolicyLanguageSignal],
    conflicts: Sequence[ConflictRecord],
    abstentions: Sequence[AbstentionRecord],
    security_findings: Sequence[UntrustedInstructionFinding],
    config: AgentConfig,
    summarizer: SummarizerAdapter,
) -> ScenarioBrief:
    """Assemble a citation-indexed ScenarioBrief."""
    citations_index: Dict[str, Citation] = {}
    for fig in figures:
        citations_index[fig.citation.citation_id] = fig.citation
    for srp in surprises:
        if srp.citation is not None:
            citations_index[srp.citation.citation_id] = srp.citation
    for rev in revisions:
        citations_index[rev.prior_citation.citation_id] = rev.prior_citation
        citations_index[rev.current_citation.citation_id] = rev.current_citation
    for sig in policy_signals:
        citations_index[sig.citation.citation_id] = sig.citation
    for cnf in conflicts:
        for cit in cnf.citations:
            citations_index[cit.citation_id] = cit

    scenarios = _build_deterministic_hypotheses(
        surprises=surprises,
        revisions=revisions,
        policy_signals=policy_signals,
        conflicts=conflicts,
    )

    if config.model_adapter.provider == "none":
        executive_summary = (
            f"Deterministic structured brief for {series_group} as of {format_utc_timestamp(as_of_utc)} "
            f"({len(figures)} figure(s), {len(surprises)} surprise(s), {len(revisions)} revision(s), "
            f"{len(abstentions)} abstention(s))."
        )
    else:
        executive_summary = summarizer.synthesize_summary(
            series_group=series_group,
            as_of_utc=as_of_utc,
            figures=figures,
            surprises=surprises,
            revisions=revisions,
            policy_signals=policy_signals,
            conflicts=conflicts,
            abstentions=abstentions,
            security_findings=security_findings,
        )

    brief_id = stable_id(
        "brf",
        {
            "as_of_utc": format_utc_timestamp(as_of_utc),
            "series_group": series_group,
            "figure_ids": [f.figure_id for f in figures],
            "surprise_ids": [s.surprise_id for s in surprises],
            "revision_ids": [r.revision_id for r in revisions],
            "abstention_ids": [a.abstention_id for a in abstentions],
            "security_ids": [s.finding_id for s in security_findings],
        },
    )

    return ScenarioBrief(
        brief_id=brief_id,
        as_of_utc=as_of_utc,
        series_group=series_group,
        executive_summary=executive_summary,
        figures=tuple(figures),
        surprises=tuple(surprises),
        revisions=tuple(revisions),
        policy_signals=tuple(policy_signals),
        conflicts=tuple(conflicts),
        abstentions=tuple(abstentions),
        security_findings=tuple(security_findings),
        scenarios=scenarios,
        citations_index=citations_index,
        verification_passed=False,
        limitations_notice=LIMITATIONS_NOTICE,
    )
