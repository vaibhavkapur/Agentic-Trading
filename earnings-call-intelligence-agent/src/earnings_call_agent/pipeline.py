"""End-to-end deterministic analysis pipeline with structured logging and replay support."""

from __future__ import annotations

import platform
import sys
from typing import Any, Dict, List, Optional, Tuple

from .adapters import LLMExtractorProtocol, run_budgeted_llm_extraction
from .comparison import compare_guidance
from .contracts import (
    OUTPUT_SCHEMA_VERSION,
    AgentConfig,
    AnalysisReport,
    DiagnosticCounters,
    ExtractedClaim,
    canonical_json,
    format_utc_timestamp,
    sha256_text,
    stable_id,
)
from .extraction import extract_claims_from_segments
from .ingestion import ingest_transcript
from .qa import answer_questions

PACKAGE_VERSION = "0.1.0"


def _verify_claim_evidence_integrity(
    claims: Tuple[ExtractedClaim, ...],
    segment_map: Dict[str, str],
) -> Tuple[Tuple[ExtractedClaim, ...], int]:
    """Final deterministic gate confirming every numerical claim has verbatim evidence."""
    verified: List[ExtractedClaim] = []
    rejected = 0
    for c in claims:
        ev = c.evidence
        seg_text = segment_map.get(ev.segment_id)
        if (
            seg_text is None
            or not ev.verified
            or ev.char_start < 0
            or ev.char_end > len(seg_text)
            or seg_text[ev.char_start : ev.char_end] != ev.exact_quote
        ):
            rejected += 1
            continue
        verified.append(c)
    return tuple(verified), rejected


def analyze_transcript(
    raw_data: Dict[str, Any],
    config: AgentConfig,
    as_of_timestamp: Optional[str] = None,
    llm_provider: Optional[LLMExtractorProtocol] = None,
) -> AnalysisReport:
    """Execute the full verifiable earnings-call intelligence pipeline."""
    logs: List[Dict[str, Any]] = []
    warnings: List[str] = []

    ingested = ingest_transcript(raw_data, config, as_of_timestamp=as_of_timestamp)
    transcript = ingested.transcript
    freshness = ingested.freshness
    as_of_str = format_utc_timestamp(freshness.as_of_timestamp)

    run_id = stable_id(
        "run",
        [ingested.input_digest, config.digest(), config.seed, as_of_str],
    )

    logs.append(
        {
            "stage": "ingestion",
            "run_id": run_id,
            "transcript_id": transcript.transcript_id,
            "segments_count": len(transcript.segments),
            "prior_guidance_count": len(transcript.prior_guidance),
            "is_stale": freshness.is_stale,
            "age_days": freshness.age_days,
        }
    )

    if freshness.is_stale and freshness.stale_reason:
        warnings.append(f"STALE_SOURCE: {freshness.stale_reason}")
    elif freshness.stale_reason:
        warnings.append(f"TIMESTAMP_ANOMALY: {freshness.stale_reason}")

    quarantined_segments = sum(1 for s in ingested.sanitized_segments if s.fully_quarantined)
    if ingested.injection_events:
        warnings.append(
            f"PROMPT_INJECTION_DETECTED: {len(ingested.injection_events)} suspicious pattern(s) quarantined."
        )
    logs.append(
        {
            "stage": "security_scan",
            "run_id": run_id,
            "injection_events_count": len(ingested.injection_events),
            "segments_quarantined": quarantined_segments,
        }
    )

    # Core deterministic extraction
    det_claims = extract_claims_from_segments(
        sanitized_segments=ingested.sanitized_segments,
        default_fiscal_period=transcript.fiscal_period,
        published_at=transcript.published_at,
        uncertainty_hedges=config.uncertainty_hedges,
    )

    llm_calls_used = 0
    llm_tokens_used = 0
    llm_rejected = 0
    combined_claims: List[ExtractedClaim] = list(det_claims)
    seen_ids = {c.claim_id for c in det_claims}

    if config.extraction_mode == "hybrid" and llm_provider is not None:
        llm_res = run_budgeted_llm_extraction(
            provider=llm_provider,
            sanitized_segments=ingested.sanitized_segments,
            default_fiscal_period=transcript.fiscal_period,
            published_at=transcript.published_at,
            max_calls=config.max_llm_calls,
            max_tokens=config.max_llm_tokens,
            seed=config.seed,
        )
        llm_calls_used = llm_res.calls_used
        llm_tokens_used = llm_res.tokens_used
        llm_rejected = llm_res.rejected_count
        for c in llm_res.verified_claims:
            if c.claim_id not in seen_ids:
                seen_ids.add(c.claim_id)
                combined_claims.append(c)

    segment_map = {s.segment_id: s.text for s in transcript.segments}
    verified_claims, gate_rejected = _verify_claim_evidence_integrity(
        tuple(combined_claims), segment_map
    )
    total_rejected = llm_rejected + gate_rejected

    logs.append(
        {
            "stage": "extraction_and_verification",
            "run_id": run_id,
            "claims_extracted": len(combined_claims) + llm_rejected,
            "claims_verified": len(verified_claims),
            "claims_rejected_unverified": total_rejected,
            "llm_calls_used": llm_calls_used,
            "llm_tokens_used": llm_tokens_used,
        }
    )

    comparisons = compare_guidance(
        claims=verified_claims,
        prior_guidance=transcript.prior_guidance,
        contradiction_tolerance_pct=config.contradiction_tolerance_pct,
        reaffirm_tolerance_pct=config.reaffirm_tolerance_pct,
        is_stale_source=freshness.is_stale,
    )
    contradictions_count = sum(1 for g in comparisons if g.contradiction_detected)
    if contradictions_count > 0:
        warnings.append(
            f"CONTRADICTORY_GUIDANCE: {contradictions_count} guidance group(s) contain conflicting values."
        )

    logs.append(
        {
            "stage": "guidance_comparison",
            "run_id": run_id,
            "guidance_comparisons_count": len(comparisons),
            "contradictions_detected": contradictions_count,
        }
    )

    answers = answer_questions(
        questions=transcript.questions,
        claims=verified_claims,
        comparisons=comparisons,
        sanitized_segments=ingested.sanitized_segments,
        freshness=freshness,
        config=config,
    )
    answered_count = sum(1 for a in answers if a.answered)
    abstained_count = sum(1 for a in answers if a.abstained)

    logs.append(
        {
            "stage": "question_answering",
            "run_id": run_id,
            "questions_answered": answered_count,
            "questions_abstained": abstained_count,
        }
    )

    diagnostics = DiagnosticCounters(
        segments_ingested=len(transcript.segments),
        segments_quarantined=quarantined_segments,
        injection_events_count=len(ingested.injection_events),
        claims_extracted=len(combined_claims) + llm_rejected,
        claims_verified=len(verified_claims),
        claims_rejected_unverified=total_rejected,
        guidance_comparisons_count=len(comparisons),
        contradictions_detected=contradictions_count,
        questions_answered=answered_count,
        questions_abstained=abstained_count,
        llm_calls_used=llm_calls_used,
        llm_tokens_used=llm_tokens_used,
    )

    runtime_metadata = {
        "package_version": PACKAGE_VERSION,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "extraction_mode": config.extraction_mode,
        "config_version": config.config_version,
        "seed": config.seed,
    }

    return AnalysisReport(
        schema_version=OUTPUT_SCHEMA_VERSION,
        run_id=run_id,
        input_digest=ingested.input_digest,
        config_digest=config.digest(),
        seed=config.seed,
        transcript_id=transcript.transcript_id,
        ticker=transcript.ticker,
        company_name=transcript.company_name,
        fiscal_period=transcript.fiscal_period,
        as_of_timestamp=as_of_str,
        source_freshness=freshness.to_dict(),
        trade_action_permitted=False,
        claims=verified_claims,
        guidance_comparisons=comparisons,
        question_answers=answers,
        prompt_injection_events=ingested.injection_events,
        warnings=tuple(warnings),
        diagnostics=diagnostics,
        runtime_metadata=runtime_metadata,
        structured_logs=tuple(logs),
    )


def report_logical_digest(report: AnalysisReport) -> str:
    """Hash logical report outputs (excluding volatile host/platform metadata) for replay checks."""
    payload = report.to_dict()
    payload.pop("runtime_metadata", None)
    return sha256_text(canonical_json(payload))


def replay_and_verify(
    raw_data: Dict[str, Any],
    config: AgentConfig,
    expected_digest: Optional[str] = None,
    as_of_timestamp: Optional[str] = None,
    llm_provider: Optional[LLMExtractorProtocol] = None,
) -> Dict[str, Any]:
    """Re-run analysis and confirm deterministic logical reproducibility."""
    report = analyze_transcript(
        raw_data=raw_data,
        config=config,
        as_of_timestamp=as_of_timestamp,
        llm_provider=llm_provider,
    )
    actual_digest = report_logical_digest(report)
    matched = True if expected_digest is None else (actual_digest == expected_digest)
    return {
        "run_id": report.run_id,
        "logical_digest": actual_digest,
        "expected_digest": expected_digest,
        "reproducible_match": matched,
        "report": report.to_dict(),
    }
