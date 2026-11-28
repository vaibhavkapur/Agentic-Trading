"""Pydantic v2 data contracts for inputs, internal evidence records, and outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_SCHEMA_VERSION = "1.0.0"


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include an explicit timezone offset or 'Z' (UTC)")
    return dt.astimezone(timezone.utc)


class EventSource(str, Enum):
    OTEL_SPAN = "otel_span"
    LOG = "log"
    OMS_EVENT = "oms_event"
    ALERT = "alert"


class Severity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class SpanStatus(str, Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class OmsEventType(str, Enum):
    ORDER_NEW = "ORDER_NEW"
    ORDER_ACK = "ORDER_ACK"
    ORDER_REJECT = "ORDER_REJECT"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    ORDER_CANCEL_REQUEST = "ORDER_CANCEL_REQUEST"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_FILL = "ORDER_FILL"
    THROTTLE_TRIGGERED = "THROTTLE_TRIGGERED"
    CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER_TRIPPED"
    RISK_CHECK_FAILED = "RISK_CHECK_FAILED"


class VerdictStatus(str, Enum):
    DETERMINED = "DETERMINED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RemediationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DENIED = "DENIED"
    EXECUTED_RECOVERED = "EXECUTED_RECOVERED"
    EXECUTED_RECOVERY_FAILED = "EXECUTED_RECOVERY_FAILED"


class ActionRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    FORBIDDEN = "FORBIDDEN"


class OtelSpan(BaseModel):
    """OpenTelemetry-style distributed trace span fixture."""

    model_config = ConfigDict(extra="forbid")

    span_id: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    parent_span_id: Optional[str] = None
    service: str = Field(..., min_length=1)
    operation: str = Field(..., min_length=1)
    start_time_utc: datetime
    duration_ms: float = Field(..., ge=0.0)
    status: SpanStatus = SpanStatus.OK
    status_message: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("start_time_utc")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class LogEntry(BaseModel):
    """Structured service log entry (treated as untrusted data)."""

    model_config = ConfigDict(extra="forbid")

    log_id: str = Field(..., min_length=1)
    timestamp_utc: datetime
    service: str = Field(..., min_length=1)
    severity: Severity
    message: str = Field(..., min_length=1)
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    order_id: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp_utc")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class OmsEvent(BaseModel):
    """Order Management System lifecycle or risk/throttle event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    timestamp_utc: datetime
    service: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    venue: str = Field(..., min_length=1)
    event_type: OmsEventType
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    notional_usd: Optional[float] = Field(default=None, ge=0.0)
    reject_code: Optional[str] = None
    trace_id: Optional[str] = None
    message: str = Field(..., min_length=1)

    @field_validator("timestamp_utc")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class AlertEvent(BaseModel):
    """Monitoring alert emitted by metrics/SLO rules."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str = Field(..., min_length=1)
    timestamp_utc: datetime
    rule_id: str = Field(..., min_length=1)
    service: str = Field(..., min_length=1)
    severity: Severity
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None
    unit: Optional[str] = None
    trace_id: Optional[str] = None
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("timestamp_utc")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class Runbook(BaseModel):
    """Operator runbook describing symptoms, diagnostics, and allowlisted simulated remediations."""

    model_config = ConfigDict(extra="forbid")

    runbook_id: str = Field(..., min_length=1)
    version: str = Field(default="1.0.0", min_length=1)
    title: str = Field(..., min_length=1)
    service: str = Field(..., min_length=1)
    failure_mode: str = Field(..., min_length=1)
    symptoms: list[str] = Field(default_factory=list)
    alert_rules: list[str] = Field(default_factory=list)
    reject_codes: list[str] = Field(default_factory=list)
    diagnostic_checks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    expected_recovery_signals: list[str] = Field(default_factory=list)
    notes: str = ""


class IncidentBundle(BaseModel):
    """Canonical versioned input package representing a single simulated trading incident."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SUPPORTED_SCHEMA_VERSION)
    incident_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    environment: Literal["synthetic", "paper", "sim"] = "synthetic"
    reported_at_utc: datetime
    traces: list[OtelSpan] = Field(default_factory=list)
    logs: list[LogEntry] = Field(default_factory=list)
    oms_events: list[OmsEvent] = Field(default_factory=list)
    alerts: list[AlertEvent] = Field(default_factory=list)
    runbooks: list[Runbook] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reported_at_utc")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @model_validator(mode="after")
    def _validate_non_empty_telemetry(self) -> "IncidentBundle":
        if not (self.traces or self.logs or self.oms_events or self.alerts):
            raise ValueError("IncidentBundle must include at least one telemetry event")
        return self


class BudgetConfig(BaseModel):
    """Deterministic resource and call limits enforced per investigation."""

    model_config = ConfigDict(extra="forbid")

    max_tool_calls: int = Field(default=25, ge=1, le=500)
    max_steps: int = Field(default=15, ge=1, le=200)
    max_llm_calls: int = Field(default=1, ge=0, le=10)
    max_prompt_chars: int = Field(default=8000, ge=256, le=100000)


class AgentConfig(BaseModel):
    """Versioned runtime configuration for TradingIncidentAgent."""

    model_config = ConfigDict(extra="forbid")

    config_version: str = Field(default="1.0.0")
    seed: int = Field(default=42, ge=0)
    read_only_default: Literal[True] = True
    ambiguity_margin: float = Field(default=0.12, ge=0.0, le=0.5)
    min_root_cause_confidence: float = Field(default=0.45, ge=0.0, le=1.0)
    missing_span_confidence_penalty: float = Field(default=0.12, ge=0.0, le=0.5)
    single_modality_confidence_cap: float = Field(default=0.52, ge=0.1, le=1.0)
    log_only_weight_multiplier: float = Field(default=0.35, ge=0.05, le=1.0)
    max_retrieved_runbooks: int = Field(default=5, ge=1, le=20)
    max_hypotheses: int = Field(default=5, ge=1, le=20)
    allowed_approver_roles: list[str] = Field(
        default_factory=lambda: ["oncall_sre", "trading_ops_lead", "incident_commander"]
    )
    approval_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    advisor_mode: Literal["offline_template", "custom_callback"] = "offline_template"


class SanitizationFinding(BaseModel):
    """Security record emitted when prompt injection or secret patterns are detected."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    source_type: EventSource
    source_id: str
    category: Literal["prompt_injection", "secret_redaction"]
    pattern_name: str
    matched_excerpt_redacted: str
    action_taken: str


class TimelineEvent(BaseModel):
    """Normalized, sanitized, UTC-ordered telemetry event."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    timestamp_utc: datetime
    timestamp_ns: int
    source_type: EventSource
    source_id: str
    service: str
    severity: Severity
    summary: str
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    order_id: Optional[str] = None
    correlation_group: str
    is_anomalous: bool = False
    injection_detected: bool = False
    redacted: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceGap(BaseModel):
    """Detected structural anomaly in distributed OpenTelemetry span graphs."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    child_span_id: str
    missing_parent_span_id: Optional[str] = None
    child_service: str
    gap_type: Literal["missing_parent_span", "clock_skew"]
    description: str


class IncidentTimeline(BaseModel):
    """Normalized incident timeline with trace-gap diagnostics and correlation clusters."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    event_count: int
    anomalous_event_count: int
    start_time_utc: datetime
    end_time_utc: datetime
    duration_ms: float
    events: list[TimelineEvent]
    trace_gaps: list[TraceGap] = Field(default_factory=list)
    correlation_groups: dict[str, list[str]] = Field(default_factory=dict)


class RetrievedRunbook(BaseModel):
    """Ranked runbook match produced by deterministic retrieval."""

    model_config = ConfigDict(extra="forbid")

    runbook_id: str
    title: str
    failure_mode: str
    service: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    matched_signals: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class EvidenceCitation(BaseModel):
    """Traceable reference to a normalized timeline event used in hypothesis scoring."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: EventSource
    source_id: str
    timestamp_utc: datetime
    service: str
    summary: str
    weight: float
    rationale: str


class HypothesisEvaluation(BaseModel):
    """Evaluated root-cause hypothesis with supporting evidence, counterevidence, and confidence."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    title: str
    failure_mode: str
    service: str
    runbook_id: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    raw_score: float
    supporting_evidence: list[EvidenceCitation] = Field(default_factory=list)
    counterevidence: list[EvidenceCitation] = Field(default_factory=list)
    modalities_supporting: list[str] = Field(default_factory=list)
    uncertainty_factors: list[str] = Field(default_factory=list)
    discriminating_checks: list[str] = Field(default_factory=list)


class RemediationProposal(BaseModel):
    """Proposed simulated remediation bound by a deterministic SHA-256 plan digest."""

    model_config = ConfigDict(extra="forbid")

    remediation_id: str
    incident_id: str
    action_id: str
    target_service: str
    risk_level: ActionRiskLevel
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    expected_recovery_checks: list[str] = Field(default_factory=list)
    requires_explicit_approval: Literal[True] = True
    auto_executed: Literal[False] = False
    plan_digest: str
    blocked_reason: Optional[str] = None


class OperatorApproval(BaseModel):
    """Explicit operator approval required before any simulated remediation runs."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(..., min_length=1)
    incident_id: str = Field(..., min_length=1)
    remediation_id: str = Field(..., min_length=1)
    plan_digest: str = Field(..., min_length=16)
    approver_id: str = Field(..., min_length=1)
    approver_role: str = Field(..., min_length=1)
    approved_at_utc: datetime
    expires_at_utc: datetime
    rationale: str = Field(..., min_length=5)
    acknowledge_ambiguity: bool = False

    @field_validator("approved_at_utc", "expires_at_utc")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class HealthCheckResult(BaseModel):
    """Single simulated post-remediation health verification check."""

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    before_value: float
    after_value: float
    threshold: float
    unit: str
    passed: bool


class RecoveryVerification(BaseModel):
    """Deterministic post-remediation recovery verification summary."""

    model_config = ConfigDict(extra="forbid")

    verified: bool
    seed: int
    checks: list[HealthCheckResult]
    summary: str
    rollback_recommended: bool


class RemediationReceipt(BaseModel):
    """Auditable record of a simulated remediation attempt (executed or denied)."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str
    incident_id: str
    remediation_id: str
    action_id: str
    status: RemediationStatus
    approval_id: Optional[str] = None
    approver_id: Optional[str] = None
    executed_in_simulation: bool
    state_mutated: bool
    denial_reason: Optional[str] = None
    verification: Optional[RecoveryVerification] = None
    executed_at_utc: datetime


class DiagnosticLogEntry(BaseModel):
    """Structured execution trace record for observability and replay debugging."""

    model_config = ConfigDict(extra="forbid")

    step: int
    component: str
    event: str
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeMetadata(BaseModel):
    """Reproducibility metadata captured alongside every incident report."""

    model_config = ConfigDict(extra="forbid")

    package_version: str
    schema_version: str
    python_version: str
    platform: str
    config_digest: str
    input_digest: str
    seed: int
    advisor_mode: str


class IncidentReport(BaseModel):
    """Canonical cited root-cause report produced by read-only investigation."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    schema_version: str
    incident_id: str
    incident_title: str
    verdict_status: VerdictStatus
    primary_root_cause: Optional[HypothesisEvaluation] = None
    hypotheses: list[HypothesisEvaluation] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertainty_notes: list[str] = Field(default_factory=list)
    timeline: IncidentTimeline
    retrieved_runbooks: list[RetrievedRunbook] = Field(default_factory=list)
    proposed_remediations: list[RemediationProposal] = Field(default_factory=list)
    security_findings: list[SanitizationFinding] = Field(default_factory=list)
    narrative_summary: str
    read_only_enforced: Literal[True] = True
    operational_changes_applied: Literal[0] = 0
    diagnostics_counters: dict[str, int] = Field(default_factory=dict)
    diagnostic_log: list[DiagnosticLogEntry] = Field(default_factory=list)
    runtime_metadata: RuntimeMetadata
