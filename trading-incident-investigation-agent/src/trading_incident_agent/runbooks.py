"""Deterministic runbook retrieval over normalized incident timeline signals."""

from __future__ import annotations

from trading_incident_agent.models import (
    EventSource,
    IncidentBundle,
    IncidentTimeline,
    RetrievedRunbook,
)


def retrieve_runbooks(
    bundle: IncidentBundle,
    timeline: IncidentTimeline,
    *,
    max_results: int = 5,
) -> list[RetrievedRunbook]:
    """Match and rank candidate runbooks deterministically against anomalous timeline signals."""
    anomalous_events = [ev for ev in timeline.events if ev.is_anomalous]
    if not anomalous_events or not bundle.runbooks:
        return []

    anomalous_services = {ev.service.lower() for ev in anomalous_events}
    alert_rules = {
        str(ev.attributes.get("rule_id", "")).upper()
        for ev in anomalous_events
        if ev.source_type == EventSource.ALERT and ev.attributes.get("rule_id")
    }
    reject_codes = {
        str(ev.attributes.get("reject_code", "")).upper()
        for ev in anomalous_events
        if ev.source_type == EventSource.OMS_EVENT and ev.attributes.get("reject_code")
    }

    # Combine sanitized summaries and operations from anomalous events for symptom matching.
    corpus_chunks: list[str] = []
    for ev in anomalous_events:
        corpus_chunks.append(ev.summary.lower())
        op = ev.attributes.get("operation")
        if isinstance(op, str):
            corpus_chunks.append(op.lower())
    corpus_text = "\n".join(corpus_chunks)

    ranked: list[RetrievedRunbook] = []
    for rb in bundle.runbooks:
        score = 0.0
        matched_signals: list[str] = []

        # 1. Exact alert rule match
        rb_rules = {r.upper() for r in rb.alert_rules}
        rule_hits = sorted(alert_rules & rb_rules)
        if rule_hits:
            score += 0.35
            for r in rule_hits:
                matched_signals.append(f"alert_rule:{r}")

        # 2. Exact OMS reject code match
        rb_rejects = {c.upper() for c in rb.reject_codes}
        reject_hits = sorted(reject_codes & rb_rejects)
        if reject_hits:
            score += 0.35
            for c in reject_hits:
                matched_signals.append(f"reject_code:{c}")

        # 3. Service match
        if rb.service.lower() in anomalous_services:
            score += 0.15
            matched_signals.append(f"service:{rb.service}")

        # 4. Symptom keyword / phrase match
        symptom_hits = [s for s in rb.symptoms if s.lower() in corpus_text]
        if symptom_hits:
            symptom_ratio = len(symptom_hits) / max(1, len(rb.symptoms))
            score += round(0.15 + 0.15 * symptom_ratio, 4)
            for s in symptom_hits:
                matched_signals.append(f"symptom:{s}")

        final_score = round(min(1.0, score), 4)
        if final_score > 0.0:
            ranked.append(
                RetrievedRunbook(
                    runbook_id=rb.runbook_id,
                    title=rb.title,
                    failure_mode=rb.failure_mode,
                    service=rb.service,
                    relevance_score=final_score,
                    matched_signals=matched_signals,
                    recommended_actions=list(rb.recommended_actions),
                )
            )

    ranked.sort(key=lambda item: (-item.relevance_score, item.runbook_id))
    return ranked[:max_results]
