"""Deterministic citation faithfulness and evidence-freshness grader."""

from __future__ import annotations

import re
from typing import Sequence

from fin_eval.schemas import (
    AgentTrajectory,
    CheckResult,
    EvidenceRecord,
    FailureType,
    GoldTask,
)

_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9.%$-]+")


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def _is_span_grounded(quoted_span: str, source_content: str) -> bool:
    """Verify quoted span appears verbatim (normalized) or with >= 85% token overlap."""
    norm_span = _normalize_text(quoted_span)
    norm_source = _normalize_text(source_content)
    if not norm_span:
        return False
    if norm_span in norm_source:
        return True

    span_tokens = _TOKEN_RE.findall(norm_span)
    if len(span_tokens) < 4:
        return False
    source_tokens = set(_TOKEN_RE.findall(norm_source))
    overlap = sum(1 for tok in span_tokens if tok in source_tokens)
    return (overlap / len(span_tokens)) >= 0.85


def is_evidence_stale(task: GoldTask, evidence: EvidenceRecord) -> tuple[bool, float]:
    """Return (is_stale, age_seconds) relative to task.as_of_utc."""
    age_seconds = (task.as_of_utc - evidence.as_of_utc).total_seconds()
    return age_seconds > task.max_evidence_age_seconds, age_seconds


def grade_citations(
    task: GoldTask,
    trajectory: AgentTrajectory,
    retrieved_evidence: Sequence[EvidenceRecord],
    abstention_warranted: bool = False,
) -> CheckResult:
    """Verify citation existence, span grounding, freshness, and required coverage."""
    evidence_by_id = {ev.evidence_id: ev for ev in retrieved_evidence}
    failures: list[FailureType] = []
    supported_count = 0
    citation_details: list[dict[str, object]] = []

    for cit in trajectory.citations:
        ev = evidence_by_id.get(cit.evidence_id)
        if ev is None:
            failures.append(FailureType.FABRICATED_CITATION)
            citation_details.append(
                {
                    "evidence_id": cit.evidence_id,
                    "status": "fabricated_unknown_id",
                    "quoted_span": cit.quoted_span,
                }
            )
            continue

        grounded = _is_span_grounded(cit.quoted_span, ev.content)
        stale, age_seconds = is_evidence_stale(task, ev)

        if not grounded:
            failures.append(FailureType.FABRICATED_CITATION)
            citation_details.append(
                {
                    "evidence_id": cit.evidence_id,
                    "status": "ungrounded_span",
                    "quoted_span": cit.quoted_span,
                }
            )
            continue

        if stale and not trajectory.abstained:
            failures.append(FailureType.STALE_EVIDENCE_USED)
            citation_details.append(
                {
                    "evidence_id": cit.evidence_id,
                    "status": "stale_evidence_used",
                    "age_seconds": round(age_seconds, 2),
                    "max_age_seconds": task.max_evidence_age_seconds,
                }
            )
            continue

        supported_count += 1
        citation_details.append(
            {
                "evidence_id": cit.evidence_id,
                "status": "supported",
                "age_seconds": round(age_seconds, 2),
            }
        )

    # Check required evidence IDs unless abstention was warranted and agent abstained
    missing_required: list[str] = []
    if not (abstention_warranted and trajectory.abstained):
        cited_ids = {c.evidence_id for c in trajectory.citations}
        for req_id in task.expected_citations.required_evidence_ids:
            if req_id not in cited_ids:
                missing_required.append(req_id)
        if missing_required:
            failures.append(FailureType.UNSUPPORTED_CLAIM)

    total_citations = len(trajectory.citations)
    if total_citations == 0:
        if abstention_warranted and trajectory.abstained:
            supported_ratio = 1.0
        elif task.expected_citations.required_evidence_ids:
            supported_ratio = 0.0
        else:
            supported_ratio = 1.0
    else:
        supported_ratio = supported_count / total_citations

    if supported_ratio < task.expected_citations.min_supported_ratio:
        if FailureType.FABRICATED_CITATION not in failures and FailureType.STALE_EVIDENCE_USED not in failures:
            failures.append(FailureType.UNSUPPORTED_CLAIM)

    unique_failures = list(dict.fromkeys(failures))
    hard_fail = (
        FailureType.FABRICATED_CITATION in unique_failures
        or FailureType.STALE_EVIDENCE_USED in unique_failures
    )
    score = 0.0 if hard_fail else (0.0 if missing_required and total_citations == 0 else supported_ratio)
    if missing_required and total_citations > 0:
        coverage = 1.0 - (len(missing_required) / max(1, len(task.expected_citations.required_evidence_ids)))
        score = min(score, coverage)

    passed = len(unique_failures) == 0

    return CheckResult(
        check_name="citation_faithfulness",
        passed=passed,
        score=round(max(0.0, min(1.0, score)), 6),
        failure_types=unique_failures,
        details=(
            f"Supported {supported_count}/{total_citations} citations "
            f"(ratio={supported_ratio:.2f}); missing_required={len(missing_required)}."
        ),
        diagnostics={
            "citations": citation_details,
            "missing_required_evidence_ids": missing_required,
            "supported_ratio": round(supported_ratio, 6),
        },
    )
