"""Pure domain hypothesis generation, corroboration testing, counterevidence, and ambiguity detection."""

from __future__ import annotations

import math
from typing import Optional

from trading_incident_agent.models import (
    AgentConfig,
    EventSource,
    EvidenceCitation,
    HypothesisEvaluation,
    IncidentBundle,
    IncidentTimeline,
    RetrievedRunbook,
    Runbook,
    TimelineEvent,
    VerdictStatus,
)

MODALITY_BASE_WEIGHTS: dict[EventSource, float] = {
    EventSource.ALERT: 0.32,
    EventSource.OMS_EVENT: 0.30,
    EventSource.OTEL_SPAN: 0.26,
    EventSource.LOG: 0.18,
}

ARCHIVAL_RED_HERRING_TOKENS = (
    "archival",
    "replay_only",
    "unaffected",
    "ignored on live",
    "background snapshot",
)


def _matches_runbook(ev: TimelineEvent, rb: Runbook) -> tuple[bool, str]:
    """Check if an anomalous timeline event provides direct evidence for a runbook hypothesis."""
    text = ev.summary.lower()
    rb_service = rb.service.lower()
    rb_rules = {r.upper() for r in rb.alert_rules}
    rb_rejects = {c.upper() for c in rb.reject_codes}

    if ev.source_type == EventSource.ALERT:
        rule_id = str(ev.attributes.get("rule_id", "")).upper()
        if rule_id in rb_rules:
            return True, f"Alert rule '{rule_id}' directly maps to {rb.runbook_id}"
        if ev.service.lower() == rb_service and any(s.lower() in text for s in rb.symptoms):
            return True, f"Alert on '{ev.service}' matches runbook symptom"
        return False, ""

    if ev.source_type == EventSource.OMS_EVENT:
        reject_code = str(ev.attributes.get("reject_code") or "").upper()
        if reject_code and reject_code in rb_rejects:
            return True, f"OMS reject_code '{reject_code}' directly matches {rb.runbook_id}"
        if ev.service.lower() == rb_service and any(s.lower() in text for s in rb.symptoms):
            return True, f"Anomalous OMS event on '{ev.service}' matches symptom"
        return False, ""

    if ev.source_type == EventSource.OTEL_SPAN:
        op = str(ev.attributes.get("operation", "")).lower()
        symptom_hit = next((s for s in rb.symptoms if s.lower() in text or s.lower() in op), None)
        if ev.service.lower() == rb_service and (symptom_hit or ev.is_anomalous):
            reason = (
                f"Error span on '{ev.service}' matches symptom '{symptom_hit}'"
                if symptom_hit
                else f"Error span directly on hypothesized service '{ev.service}'"
            )
            return True, reason
        # Upstream error span explicitly citing a symptom / reject code of this failure mode
        if symptom_hit and (
            any(c.lower() in text for c in rb.reject_codes)
            or rb_service in text
            or "oms" in text
            and "oms" in rb_service
        ):
            return True, f"Upstream error span on '{ev.service}' reports '{symptom_hit}'"
        return False, ""

    if ev.source_type == EventSource.LOG:
        symptom_hit = next((s for s in rb.symptoms if s.lower() in text), None)
        if ev.service.lower() == rb_service and symptom_hit:
            return True, f"Log entry on '{ev.service}' mentions symptom '{symptom_hit}'"
        return False, ""

    return False, ""


def _is_archival_or_unaffected_log(ev: TimelineEvent) -> bool:
    if ev.source_type != EventSource.LOG:
        return False
    combined = ev.summary.lower() + " " + " ".join(str(v).lower() for v in ev.attributes.values())
    return any(tok in combined for tok in ARCHIVAL_RED_HERRING_TOKENS)


def _evaluate_single_hypothesis(
    idx: int,
    rb: Runbook,
    timeline: IncidentTimeline,
    config: AgentConfig,
    earliest_anomalous_ns: int,
) -> HypothesisEvaluation:
    supporting: list[EvidenceCitation] = []
    counterevidence: list[EvidenceCitation] = []
    uncertainty_factors: list[str] = []

    for ev in timeline.events:
        if ev.is_anomalous:
            matched, rationale = _matches_runbook(ev, rb)
            if matched:
                weight = MODALITY_BASE_WEIGHTS[ev.source_type]
                if ev.source_type == EventSource.OTEL_SPAN and ev.service.lower() != rb.service.lower():
                    # Upstream propagating span carries slightly lower weight than direct service span.
                    weight = round(weight * 0.75, 4)

                # Down-weight archival / secondary-only logs and mark as misleading counterevidence.
                if _is_archival_or_unaffected_log(ev):
                    counterevidence.append(
                        EvidenceCitation(
                            evidence_id=ev.evidence_id,
                            source_type=ev.source_type,
                            source_id=ev.source_id,
                            timestamp_utc=ev.timestamp_utc,
                            service=ev.service,
                            summary=ev.summary,
                            weight=0.14,
                            rationale=(
                                "Log indicates archival/secondary channel or unaffected primary feed; "
                                "treated as potential red herring."
                            ),
                        )
                    )
                    weight = round(weight * 0.35, 4)

                supporting.append(
                    EvidenceCitation(
                        evidence_id=ev.evidence_id,
                        source_type=ev.source_type,
                        source_id=ev.source_id,
                        timestamp_utc=ev.timestamp_utc,
                        service=ev.service,
                        summary=ev.summary,
                        weight=weight,
                        rationale=rationale,
                    )
                )
        else:
            # Healthy non-anomalous span on the hypothesized service is concrete counterevidence.
            if ev.source_type == EventSource.OTEL_SPAN and ev.service.lower() == rb.service.lower():
                counterevidence.append(
                    EvidenceCitation(
                        evidence_id=ev.evidence_id,
                        source_type=ev.source_type,
                        source_id=ev.source_id,
                        timestamp_utc=ev.timestamp_utc,
                        service=ev.service,
                        summary=ev.summary,
                        weight=0.22,
                        rationale=(
                            f"Healthy OK span observed on hypothesized service '{rb.service}' "
                            "during incident window."
                        ),
                    )
                )

    modalities = sorted({c.source_type.value for c in supporting})
    raw_support = round(sum(c.weight for c in supporting), 4)
    counter_penalty = round(sum(c.weight for c in counterevidence), 4)

    # Check temporal mismatch: if earliest supporting evidence is > 2s after incident onset
    # and lacks any trace/order correlation, record uncertainty and counterevidence penalty.
    if supporting:
        supporting_ev_map = {e.evidence_id: e for e in timeline.events}
        earliest_support_ns = min(
            supporting_ev_map[c.evidence_id].timestamp_ns for c in supporting
        )
        has_correlation = any(
            supporting_ev_map[c.evidence_id].trace_id is not None
            or supporting_ev_map[c.evidence_id].order_id is not None
            for c in supporting
        )
        onset_lag_ms = (earliest_support_ns - earliest_anomalous_ns) / 1_000_000.0
        if onset_lag_ms > 2000.0 and not has_correlation:
            uncertainty_factors.append(
                f"Earliest supporting evidence lags incident onset by {onset_lag_ms:.0f}ms "
                "with no trace_id or order_id correlation."
            )
            counter_penalty = round(counter_penalty + 0.15, 4)

    # Penalize uncorroborated log-only hypotheses so misleading logs cannot hijack root cause.
    if modalities == [EventSource.LOG.value]:
        effective_support = raw_support * config.log_only_weight_multiplier
        uncertainty_factors.append(
            "Supported by log entries only (no corroborating OpenTelemetry spans, OMS events, or alerts)."
        )
    else:
        effective_support = raw_support

    # Reward independent multi-modality corroboration.
    modality_bonus = 0.06 * max(0, len(modalities) - 1)

    # Penalize confidence when distributed trace gaps reduce causal visibility.
    gap_penalty = 0.0
    if timeline.trace_gaps:
        gap_penalty = config.missing_span_confidence_penalty
        uncertainty_factors.append(
            f"{len(timeline.trace_gaps)} distributed trace gap(s) detected; "
            "intermediate span visibility is incomplete."
        )

    if counterevidence:
        uncertainty_factors.append(
            f"{len(counterevidence)} counterevidence record(s) conflict with or weaken this hypothesis."
        )

    if not supporting:
        confidence = 0.0
        raw_score = 0.0
    else:
        saturated = (1.0 - math.exp(-1.15 * effective_support)) * 0.82
        raw_score = round(saturated + modality_bonus - counter_penalty - gap_penalty, 4)
        confidence = raw_score
        if modalities == [EventSource.LOG.value]:
            confidence = min(confidence, 0.30)
        elif len(modalities) == 1:
            confidence = min(confidence, config.single_modality_confidence_cap)
            uncertainty_factors.append(
                f"Single-modality support ({modalities[0]} only); confidence capped at "
                f"{config.single_modality_confidence_cap:.2f}."
            )
        confidence = round(max(0.0, min(0.96, confidence)), 4)

    return HypothesisEvaluation(
        hypothesis_id=f"HYP-{idx:02d}-{rb.failure_mode}",
        title=rb.title,
        failure_mode=rb.failure_mode,
        service=rb.service,
        runbook_id=rb.runbook_id,
        confidence=confidence,
        raw_score=raw_score,
        supporting_evidence=supporting,
        counterevidence=counterevidence,
        modalities_supporting=modalities,
        uncertainty_factors=uncertainty_factors,
        discriminating_checks=list(rb.diagnostic_checks),
    )


def evaluate_hypotheses(
    bundle: IncidentBundle,
    timeline: IncidentTimeline,
    retrieved_runbooks: list[RetrievedRunbook],
    config: AgentConfig,
) -> tuple[
    VerdictStatus,
    Optional[HypothesisEvaluation],
    list[HypothesisEvaluation],
    list[str],
]:
    """Generate and test candidate hypotheses deterministically and detect ambiguity."""
    runbook_by_id = {rb.runbook_id: rb for rb in bundle.runbooks}
    anomalous_events = [e for e in timeline.events if e.is_anomalous]
    earliest_anomalous_ns = (
        anomalous_events[0].timestamp_ns if anomalous_events else timeline.events[0].timestamp_ns
    )

    evaluations: list[HypothesisEvaluation] = []
    for idx, rrb in enumerate(retrieved_runbooks[: config.max_hypotheses], start=1):
        rb = runbook_by_id[rrb.runbook_id]
        evaluations.append(
            _evaluate_single_hypothesis(
                idx=idx,
                rb=rb,
                timeline=timeline,
                config=config,
                earliest_anomalous_ns=earliest_anomalous_ns,
            )
        )

    evaluations.sort(key=lambda h: (-h.confidence, -h.raw_score, h.hypothesis_id))

    uncertainty_notes: list[str] = []
    if timeline.trace_gaps:
        uncertainty_notes.append(
            f"Incomplete trace graph: {len(timeline.trace_gaps)} trace gap(s) detected "
            "(missing parent span or clock skew)."
        )

    if not evaluations or evaluations[0].confidence < config.min_root_cause_confidence:
        uncertainty_notes.append(
            "No candidate hypothesis reached the minimum confidence threshold "
            f"({config.min_root_cause_confidence:.2f})."
        )
        return VerdictStatus.INSUFFICIENT_EVIDENCE, None, evaluations, uncertainty_notes

    top = evaluations[0]
    if len(evaluations) >= 2:
        runner_up = evaluations[1]
        margin = round(top.confidence - runner_up.confidence, 4)
        if runner_up.confidence >= config.min_root_cause_confidence and margin <= config.ambiguity_margin:
            uncertainty_notes.append(
                f"Ambiguous root cause: '{top.failure_mode}' ({top.confidence:.2f}) and "
                f"'{runner_up.failure_mode}' ({runner_up.confidence:.2f}) are within "
                f"ambiguity margin {config.ambiguity_margin:.2f} (delta={margin:.4f})."
            )
            uncertainty_notes.append(
                "Run discriminating diagnostic checks before approving any targeted remediation."
            )
            return VerdictStatus.AMBIGUOUS, None, evaluations, uncertainty_notes

    if top.counterevidence:
        uncertainty_notes.append(
            f"Primary hypothesis '{top.failure_mode}' has {len(top.counterevidence)} counterevidence item(s); "
            "review counterevidence before approving remediation."
        )

    return VerdictStatus.DETERMINED, top, evaluations, uncertainty_notes
