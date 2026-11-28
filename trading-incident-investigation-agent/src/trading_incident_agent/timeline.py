"""Deterministic normalization of heterogeneous telemetry into a correlated incident timeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from trading_incident_agent.models import (
    EventSource,
    IncidentBundle,
    IncidentTimeline,
    OmsEventType,
    SanitizationFinding,
    Severity,
    SpanStatus,
    TimelineEvent,
    TraceGap,
)
from trading_incident_agent.security import sanitize_attributes, sanitize_text

EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)

SOURCE_PRIORITY: dict[EventSource, int] = {
    EventSource.OTEL_SPAN: 0,
    EventSource.OMS_EVENT: 1,
    EventSource.LOG: 2,
    EventSource.ALERT: 3,
}

ANOMALOUS_OMS_TYPES: set[OmsEventType] = {
    OmsEventType.ORDER_REJECT,
    OmsEventType.ORDER_TIMEOUT,
    OmsEventType.THROTTLE_TRIGGERED,
    OmsEventType.CIRCUIT_BREAKER_TRIPPED,
    OmsEventType.RISK_CHECK_FAILED,
}

ANOMALOUS_SEVERITIES: set[Severity] = {
    Severity.WARNING,
    Severity.ERROR,
    Severity.CRITICAL,
}


def to_timestamp_ns(dt: datetime) -> int:
    """Convert an aware UTC datetime into exact integer nanoseconds since Unix epoch."""
    delta = dt.astimezone(timezone.utc) - EPOCH_UTC
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _detect_trace_gaps(bundle: IncidentBundle) -> list[TraceGap]:
    """Detect missing parent spans and child-before-parent clock skew in OpenTelemetry traces."""
    span_by_id = {s.span_id: s for s in bundle.traces}
    gaps: list[TraceGap] = []

    for span in sorted(bundle.traces, key=lambda s: (to_timestamp_ns(s.start_time_utc), s.span_id)):
        if span.parent_span_id is None:
            continue
        parent = span_by_id.get(span.parent_span_id)
        if parent is None:
            gaps.append(
                TraceGap(
                    trace_id=span.trace_id,
                    child_span_id=span.span_id,
                    missing_parent_span_id=span.parent_span_id,
                    child_service=span.service,
                    gap_type="missing_parent_span",
                    description=(
                        f"Span '{span.span_id}' ({span.service}.{span.operation}) references "
                        f"missing parent_span_id '{span.parent_span_id}' in trace '{span.trace_id}'."
                    ),
                )
            )
        elif to_timestamp_ns(span.start_time_utc) < to_timestamp_ns(parent.start_time_utc):
            gaps.append(
                TraceGap(
                    trace_id=span.trace_id,
                    child_span_id=span.span_id,
                    missing_parent_span_id=span.parent_span_id,
                    child_service=span.service,
                    gap_type="clock_skew",
                    description=(
                        f"Child span '{span.span_id}' starts before parent '{parent.span_id}' "
                        f"in trace '{span.trace_id}' (clock skew detected)."
                    ),
                )
            )
    return gaps


def _correlation_group(trace_id: str | None, order_id: str | None, service: str) -> str:
    if trace_id:
        return f"trace:{trace_id}"
    if order_id:
        return f"order:{order_id}"
    return f"service:{service}"


def build_incident_timeline(
    bundle: IncidentBundle,
) -> tuple[IncidentTimeline, list[SanitizationFinding]]:
    """Normalize traces, logs, OMS events, and alerts into a sorted, sanitized timeline."""
    finding_counter = [0]
    all_findings: list[SanitizationFinding] = []
    raw_events: list[TimelineEvent] = []

    # 1. OpenTelemetry spans
    for span in bundle.traces:
        msg_raw = (
            f"{span.operation} [{span.status.value}] ({span.duration_ms:.1f}ms)"
            + (f": {span.status_message}" if span.status_message else "")
        )
        summary, f_msg, inj_msg, red_msg = sanitize_text(
            msg_raw,
            source_type=EventSource.OTEL_SPAN,
            source_id=span.span_id,
            finding_counter=finding_counter,
        )
        clean_attrs, f_attr, inj_attr, red_attr = sanitize_attributes(
            span.attributes,
            source_type=EventSource.OTEL_SPAN,
            source_id=span.span_id,
            finding_counter=finding_counter,
        )
        all_findings.extend(f_msg)
        all_findings.extend(f_attr)
        order_id = clean_attrs.get("order.id") or clean_attrs.get("order_id")
        is_anomalous = span.status == SpanStatus.ERROR or span.duration_ms >= 500.0
        severity = Severity.ERROR if span.status == SpanStatus.ERROR else (
            Severity.WARNING if span.duration_ms >= 500.0 else Severity.INFO
        )
        attrs = {
            **clean_attrs,
            "operation": span.operation,
            "duration_ms": span.duration_ms,
            "span_status": span.status.value,
        }
        raw_events.append(
            TimelineEvent(
                evidence_id="PENDING",
                timestamp_utc=span.start_time_utc,
                timestamp_ns=to_timestamp_ns(span.start_time_utc),
                source_type=EventSource.OTEL_SPAN,
                source_id=span.span_id,
                service=span.service,
                severity=severity,
                summary=summary,
                trace_id=span.trace_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                order_id=str(order_id) if order_id is not None else None,
                correlation_group=_correlation_group(
                    span.trace_id, str(order_id) if order_id is not None else None, span.service
                ),
                is_anomalous=is_anomalous,
                injection_detected=inj_msg or inj_attr,
                redacted=red_msg or red_attr,
                attributes=attrs,
            )
        )

    # 2. Structured logs
    for log in bundle.logs:
        summary, f_msg, inj_msg, red_msg = sanitize_text(
            log.message,
            source_type=EventSource.LOG,
            source_id=log.log_id,
            finding_counter=finding_counter,
        )
        clean_attrs, f_attr, inj_attr, red_attr = sanitize_attributes(
            log.attributes,
            source_type=EventSource.LOG,
            source_id=log.log_id,
            finding_counter=finding_counter,
        )
        all_findings.extend(f_msg)
        all_findings.extend(f_attr)
        raw_events.append(
            TimelineEvent(
                evidence_id="PENDING",
                timestamp_utc=log.timestamp_utc,
                timestamp_ns=to_timestamp_ns(log.timestamp_utc),
                source_type=EventSource.LOG,
                source_id=log.log_id,
                service=log.service,
                severity=log.severity,
                summary=summary,
                trace_id=log.trace_id,
                span_id=log.span_id,
                parent_span_id=None,
                order_id=log.order_id,
                correlation_group=_correlation_group(log.trace_id, log.order_id, log.service),
                is_anomalous=log.severity in ANOMALOUS_SEVERITIES,
                injection_detected=inj_msg or inj_attr,
                redacted=red_msg or red_attr,
                attributes=clean_attrs,
            )
        )

    # 3. OMS events
    for oms in bundle.oms_events:
        oms_text = f"{oms.event_type.value} ({oms.symbol}@{oms.venue}): {oms.message}"
        if oms.reject_code:
            oms_text += f" [reject_code={oms.reject_code}]"
        summary, f_msg, inj_msg, red_msg = sanitize_text(
            oms_text,
            source_type=EventSource.OMS_EVENT,
            source_id=oms.event_id,
            finding_counter=finding_counter,
        )
        all_findings.extend(f_msg)
        is_anomalous = oms.event_type in ANOMALOUS_OMS_TYPES or oms.reject_code is not None
        severity = Severity.ERROR if is_anomalous else Severity.INFO
        raw_events.append(
            TimelineEvent(
                evidence_id="PENDING",
                timestamp_utc=oms.timestamp_utc,
                timestamp_ns=to_timestamp_ns(oms.timestamp_utc),
                source_type=EventSource.OMS_EVENT,
                source_id=oms.event_id,
                service=oms.service,
                severity=severity,
                summary=summary,
                trace_id=oms.trace_id,
                span_id=None,
                parent_span_id=None,
                order_id=oms.order_id,
                correlation_group=_correlation_group(oms.trace_id, oms.order_id, oms.service),
                is_anomalous=is_anomalous,
                injection_detected=inj_msg,
                redacted=red_msg,
                attributes={
                    "event_type": oms.event_type.value,
                    "symbol": oms.symbol,
                    "venue": oms.venue,
                    "reject_code": oms.reject_code,
                    "latency_ms": oms.latency_ms,
                    "notional_usd": oms.notional_usd,
                },
            )
        )

    # 4. Alerts
    for alert in bundle.alerts:
        alert_text = f"[{alert.rule_id}] {alert.title}: {alert.description}"
        if alert.metric_name is not None and alert.metric_value is not None:
            unit_suffix = f" {alert.unit}" if alert.unit else ""
            alert_text += f" ({alert.metric_name}={alert.metric_value}{unit_suffix})"
        summary, f_msg, inj_msg, red_msg = sanitize_text(
            alert_text,
            source_type=EventSource.ALERT,
            source_id=alert.alert_id,
            finding_counter=finding_counter,
        )
        all_findings.extend(f_msg)
        raw_events.append(
            TimelineEvent(
                evidence_id="PENDING",
                timestamp_utc=alert.timestamp_utc,
                timestamp_ns=to_timestamp_ns(alert.timestamp_utc),
                source_type=EventSource.ALERT,
                source_id=alert.alert_id,
                service=alert.service,
                severity=alert.severity,
                summary=summary,
                trace_id=alert.trace_id,
                span_id=None,
                parent_span_id=None,
                order_id=None,
                correlation_group=_correlation_group(alert.trace_id, None, alert.service),
                is_anomalous=alert.severity in ANOMALOUS_SEVERITIES,
                injection_detected=inj_msg,
                redacted=red_msg,
                attributes={
                    "rule_id": alert.rule_id,
                    "metric_name": alert.metric_name,
                    "metric_value": alert.metric_value,
                    "threshold_value": alert.threshold_value,
                    "unit": alert.unit,
                    "labels": alert.labels,
                },
            )
        )

    # Deterministic UTC chronological sorting with stable tie-breaking
    raw_events.sort(
        key=lambda ev: (ev.timestamp_ns, SOURCE_PRIORITY[ev.source_type], ev.source_id)
    )

    events: list[TimelineEvent] = []
    groups: dict[str, list[str]] = defaultdict(list)
    for idx, ev in enumerate(raw_events, start=1):
        ev_id = f"EV-{idx:04d}-{ev.source_id}"
        final_ev = ev.model_copy(update={"evidence_id": ev_id})
        events.append(final_ev)
        groups[final_ev.correlation_group].append(ev_id)

    trace_gaps = _detect_trace_gaps(bundle)
    start_ts = events[0].timestamp_utc
    end_ts = events[-1].timestamp_utc
    duration_ms = round((events[-1].timestamp_ns - events[0].timestamp_ns) / 1_000_000.0, 3)

    timeline = IncidentTimeline(
        incident_id=bundle.incident_id,
        event_count=len(events),
        anomalous_event_count=sum(1 for e in events if e.is_anomalous),
        start_time_utc=start_ts,
        end_time_utc=end_ts,
        duration_ms=duration_ms,
        events=events,
        trace_gaps=trace_gaps,
        correlation_groups=dict(sorted(groups.items())),
    )
    return timeline, all_findings
