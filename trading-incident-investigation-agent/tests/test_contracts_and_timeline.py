"""M1 tests: data contracts, validation errors, timeline normalization, and reference oracle."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_incident_agent import (
    AgentConfig,
    InputValidationError,
    TradingIncidentAgent,
    UnsupportedSchemaError,
    VerdictStatus,
    load_incident_bundle,
    validate_incident_bundle,
)
from trading_incident_agent.evaluator import (
    compute_evidence_precision_recall,
    compute_timeline_ordering_accuracy,
)
from trading_incident_agent.models import IncidentBundle, OtelSpan, SpanStatus
from trading_incident_agent.timeline import build_incident_timeline


def test_reference_fixture_matches_hand_calculated_oracle(
    fixtures_dir: Path, agent: TradingIncidentAgent
) -> None:
    oracle = json.loads((fixtures_dir / "reference_oracle.json").read_text(encoding="utf-8"))
    ref_spec = oracle["scenarios"]["INC-REF-001"]
    bundle = load_incident_bundle(fixtures_dir / ref_spec["fixture_file"])

    report = agent.investigate(bundle)

    assert report.verdict_status == VerdictStatus.DETERMINED
    assert report.primary_root_cause is not None
    assert report.primary_root_cause.failure_mode == ref_spec["expected_failure_mode"]
    assert report.primary_root_cause.service == ref_spec["expected_service"]
    assert report.primary_root_cause.runbook_id == ref_spec["expected_runbook_id"]
    assert ref_spec["confidence_min"] <= report.confidence <= ref_spec["confidence_max"]
    assert report.read_only_enforced is True
    assert report.operational_changes_applied == 0

    actual_order = [ev.source_id for ev in report.timeline.events]
    order_metrics = compute_timeline_ordering_accuracy(
        actual_order, ref_spec["expected_timeline_source_order"]
    )
    assert order_metrics["exact_rank_accuracy"] == 1.0
    assert order_metrics["pairwise_ordering_accuracy"] == 1.0

    ev_metrics = compute_evidence_precision_recall(
        report, ref_spec["ground_truth_supporting_source_ids"]
    )
    assert ev_metrics["evidence_precision"] == 1.0
    assert ev_metrics["evidence_recall"] == 1.0


def test_unsupported_schema_version_raises_explicit_error(fixtures_dir: Path) -> None:
    with pytest.raises(UnsupportedSchemaError) as exc_info:
        load_incident_bundle(fixtures_dir / "invalid_schema_version.json")
    assert exc_info.value.error_code == "UNSUPPORTED_SCHEMA_ERROR"
    assert "9.9.9" in exc_info.value.message


def test_production_environment_is_rejected(fixtures_dir: Path) -> None:
    with pytest.raises(UnsupportedSchemaError) as exc_info:
        load_incident_bundle(fixtures_dir / "invalid_production_env.json")
    assert "production" in exc_info.value.message


def test_invalid_naive_timestamp_and_negative_duration_rejected() -> None:
    naive_payload = {
        "schema_version": "1.0.0",
        "incident_id": "INC-NAIVE",
        "title": "Naive timestamp test",
        "environment": "synthetic",
        "reported_at_utc": "2026-04-19T10:00:00",  # missing timezone
        "logs": [
            {
                "log_id": "lg-1",
                "timestamp_utc": "2026-04-19T09:59:00Z",
                "service": "oms-core",
                "severity": "ERROR",
                "message": "test",
            }
        ],
    }
    with pytest.raises(InputValidationError):
        validate_incident_bundle(naive_payload)

    neg_duration_payload = {
        "schema_version": "1.0.0",
        "incident_id": "INC-NEG",
        "title": "Negative duration test",
        "environment": "synthetic",
        "reported_at_utc": "2026-04-19T10:00:00Z",
        "traces": [
            {
                "span_id": "sp-1",
                "trace_id": "tr-1",
                "service": "oms-core",
                "operation": "RouteOrder",
                "start_time_utc": "2026-04-19T09:59:00Z",
                "duration_ms": -5.0,
                "status": "ERROR",
            }
        ],
    }
    with pytest.raises(InputValidationError):
        validate_incident_bundle(neg_duration_payload)


def test_empty_telemetry_bundle_rejected() -> None:
    with pytest.raises(InputValidationError):
        validate_incident_bundle(
            {
                "schema_version": "1.0.0",
                "incident_id": "INC-EMPTY",
                "title": "No telemetry",
                "environment": "synthetic",
                "reported_at_utc": "2026-04-19T10:00:00Z",
            }
        )


def test_timeline_detects_clock_skew_and_sorts_timezone_offsets() -> None:
    bundle = IncidentBundle(
        incident_id="INC-SKEW",
        title="Clock skew test",
        environment="synthetic",
        reported_at_utc=datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc),
        traces=[
            OtelSpan(
                span_id="sp-parent",
                trace_id="tr-skew",
                parent_span_id=None,
                service="order-router",
                operation="SubmitOrder",
                start_time_utc=datetime(2026, 4, 20, 10, 0, 5, tzinfo=timezone.utc),
                duration_ms=100.0,
                status=SpanStatus.ERROR,
            ),
            OtelSpan(
                span_id="sp-child",
                trace_id="tr-skew",
                parent_span_id="sp-parent",
                service="oms-core",
                operation="RouteOrder",
                start_time_utc=datetime(2026, 4, 20, 10, 0, 4, tzinfo=timezone.utc),
                duration_ms=50.0,
                status=SpanStatus.ERROR,
            ),
        ],
    )
    timeline, findings = build_incident_timeline(bundle)
    assert findings == []
    assert [e.source_id for e in timeline.events] == ["sp-child", "sp-parent"]
    assert len(timeline.trace_gaps) == 1
    assert timeline.trace_gaps[0].gap_type == "clock_skew"
    assert timeline.trace_gaps[0].child_span_id == "sp-child"
