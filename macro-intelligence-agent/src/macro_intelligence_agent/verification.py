"""Deterministic citation, publication-gate, and hypothesis-framing verifier."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Dict, Sequence, Tuple

from .errors import CitationVerificationError
from .models import Citation, MacroRelease, ScenarioBrief

_FORBIDDEN_PREDICTION_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bexecute\s+(?:buy|sell)\b", re.IGNORECASE),
    re.compile(r"\bguaranteed\s+return\b", re.IGNORECASE),
    re.compile(r"\bplace\s+(?:live\s+)?order\b", re.IGNORECASE),
)


def _verify_single_citation(
    citation: Citation,
    releases_by_key: Dict[Tuple[str, str], MacroRelease],
    as_of_utc: datetime,
) -> None:
    key = (citation.release_id, citation.vintage_id)
    if key not in releases_by_key:
        raise CitationVerificationError(
            f"Citation {citation.citation_id} references unknown or gated release {key}",
            details={"citation_id": citation.citation_id, "release_key": key},
        )
    release = releases_by_key[key]
    if release.available_at > as_of_utc:
        raise CitationVerificationError(
            f"Citation {citation.citation_id} leaks embargoed/future release {key}",
            details={"citation_id": citation.citation_id, "release_key": key},
        )
    if citation.document_sha256 != release.document_sha256:
        raise CitationVerificationError(
            f"Citation {citation.citation_id} document hash mismatch",
            details={"citation_id": citation.citation_id},
        )
    actual_slice = release.raw_text[citation.char_start : citation.char_end]
    if actual_slice != citation.quote:
        raise CitationVerificationError(
            f"Citation {citation.citation_id} quote mismatch at [{citation.char_start}:{citation.char_end}]",
            details={
                "citation_id": citation.citation_id,
                "expected_quote": citation.quote,
                "actual_slice": actual_slice,
            },
        )


def verify_brief(
    brief: ScenarioBrief,
    visible_releases: Sequence[MacroRelease],
    as_of_utc: datetime,
) -> bool:
    """Deterministically verify all citations, publication gates, and hypothesis boundaries.

    Raises CitationVerificationError if any invariant is violated.
    """
    releases_by_key: Dict[Tuple[str, str], MacroRelease] = {
        (r.release_id, r.vintage_id): r for r in visible_releases
    }

    # 1. Verify every citation in citations_index against visible releases & cutoff
    for cid, citation in brief.citations_index.items():
        if cid != citation.citation_id:
            raise CitationVerificationError(
                f"Citation index key mismatch: {cid} != {citation.citation_id}"
            )
        _verify_single_citation(citation, releases_by_key, as_of_utc)

    # 2. Verify every figure, surprise, revision, policy signal, and conflict is traceable
    for fig in brief.figures:
        if fig.citation.citation_id not in brief.citations_index:
            raise CitationVerificationError(
                f"Figure {fig.figure_id} citation missing from citations_index"
            )
        _verify_single_citation(fig.citation, releases_by_key, as_of_utc)

    for srp in brief.surprises:
        if srp.citation is None or srp.citation.citation_id not in brief.citations_index:
            raise CitationVerificationError(
                f"Surprise {srp.surprise_id} lacks a verified citation"
            )
        _verify_single_citation(srp.citation, releases_by_key, as_of_utc)

    for rev in brief.revisions:
        for cit in (rev.prior_citation, rev.current_citation):
            if cit.citation_id not in brief.citations_index:
                raise CitationVerificationError(
                    f"Revision {rev.revision_id} citation {cit.citation_id} missing from index"
                )
            _verify_single_citation(cit, releases_by_key, as_of_utc)

    for sig in brief.policy_signals:
        if sig.citation.citation_id not in brief.citations_index:
            raise CitationVerificationError(
                f"Policy signal {sig.signal_id} citation missing from index"
            )
        _verify_single_citation(sig.citation, releases_by_key, as_of_utc)

    for cnf in brief.conflicts:
        for cit in cnf.citations:
            if cit.citation_id not in brief.citations_index:
                raise CitationVerificationError(
                    f"Conflict {cnf.conflict_id} citation missing from index"
                )
            _verify_single_citation(cit, releases_by_key, as_of_utc)

    # 3. Verify scenario hypotheses cite valid IDs and never contain live-trade / prediction commands
    for hyp in brief.scenarios:
        for cid in hyp.supporting_citation_ids:
            if cid not in brief.citations_index:
                raise CitationVerificationError(
                    f"ScenarioHypothesis {hyp.hypothesis_id} references unknown citation {cid}"
                )
        combined = f"{hyp.condition} {hyp.interpretation} {brief.executive_summary}"
        for pat in _FORBIDDEN_PREDICTION_PATTERNS:
            if pat.search(combined):
                raise CitationVerificationError(
                    f"Forbidden command or prediction phrase detected in brief output: {pat.pattern}"
                )

    return True
