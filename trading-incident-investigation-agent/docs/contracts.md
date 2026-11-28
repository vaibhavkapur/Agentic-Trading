# Data Contracts — Trading Incident Investigation Agent

All inputs and outputs are strictly typed with **Pydantic v2** (`ConfigDict(extra="forbid")`) in [models.py](../src/trading_incident_agent/models.py).

## 1. Versioning, Units, and Timestamp Semantics

- **Schema Version:** `1.0.0` (`SUPPORTED_SCHEMA_VERSION`). Any other value raises `UnsupportedSchemaError` (`UNSUPPORTED_SCHEMA_ERROR`).
- **Environment Guard:** Only `"synthetic"`, `"paper"`, or `"sim"` are accepted. `"production"` or `"live"` raise `UnsupportedSchemaError`.
- **Timestamps:** All timestamps (`start_time_utc`, `timestamp_utc`, `reported_at_utc`, `approved_at_utc`, `expires_at_utc`) **must** be timezone-aware ISO-8601 strings (e.g., `2026-04-15T14:30:01.030Z`). Naive timestamps without offsets raise `InputValidationError`. Internally, all timestamps are normalized to UTC and converted to exact integer epoch nanoseconds (`timestamp_ns`) for deterministic ordering.
- **Tie-Breaking Rule:** Events with identical `timestamp_ns` are deterministically ordered by `(timestamp_ns, source_priority, source_id)` where `otel_span=0`, `oms_event=1`, `log=2`, `alert=3`.
- **Units:**
  - `duration_ms`, `latency_ms`: non-negative milliseconds (`float >= 0.0`).
  - `notional_usd`: non-negative US dollars (`float >= 0.0`).
  - `confidence`, `relevance_score`: dimensionless probability-like score in `[0.0, 1.0]`.
  - Alert metrics carry an explicit `unit` field (e.g., `"percent"`, `"ms"`, `"messages"`, `"count"`).

## 2. Canonical Identifiers

| Identifier | Format / Semantics |
|---|---|
| `incident_id` | Stable incident key (e.g., `INC-REF-001`) |
| `trace_id`, `span_id`, `parent_span_id` | Distributed OpenTelemetry correlation identifiers |
| `order_id` | Simulated OMS order key (e.g., `ORD-SIM-9001`) |
| `evidence_id` | Deterministic post-sort ID `EV-0001-<source_id>` |
| `runbook_id` | Versioned operator runbook identifier (e.g., `RB-FIX-POOL-001`) |
| `hypothesis_id` | Deterministic hypothesis key `HYP-01-<failure_mode>` |
| `remediation_id` | Deterministic proposal key `REM-<incident_id>-01` |
| `plan_digest` | SHA-256 hex digest binding approval to exact incident, action, target, and parameters |
| `report_id` | Stable content-derived ID `RPT-<incident_id>-<sha256(input_digest, config_digest)[:12]>` |

## 3. Input Contracts (`IncidentBundle`)

An `IncidentBundle` must contain at least one telemetry record across:

- **`traces: list[OtelSpan]`**: `span_id`, `trace_id`, `parent_span_id`, `service`, `operation`, `start_time_utc`, `duration_ms >= 0`, `status` (`UNSET|OK|ERROR`), `status_message`, `attributes`.
- **`logs: list[LogEntry]`**: `log_id`, `timestamp_utc`, `service`, `severity` (`DEBUG|INFO|WARNING|ERROR|CRITICAL`), `message`, optional `trace_id`, `span_id`, `order_id`, `attributes`.
- **`oms_events: list[OmsEvent]`**: `event_id`, `timestamp_utc`, `service`, `order_id`, `symbol`, `venue`, `event_type` (`ORDER_NEW`, `ORDER_ACK`, `ORDER_REJECT`, `ORDER_TIMEOUT`, `THROTTLE_TRIGGERED`, `CIRCUIT_BREAKER_TRIPPED`, `RISK_CHECK_FAILED`, etc.), optional `latency_ms`, `notional_usd`, `reject_code`, `trace_id`, `message`.
- **`alerts: list[AlertEvent]`**: `alert_id`, `timestamp_utc`, `rule_id`, `service`, `severity`, `title`, `description`, optional `metric_name`, `metric_value`, `threshold_value`, `unit`, `trace_id`, `labels`.
- **`runbooks: list[Runbook]`**: `runbook_id`, `version`, `title`, `service`, `failure_mode`, `symptoms`, `alert_rules`, `reject_codes`, `diagnostic_checks`, `recommended_actions`, `expected_recovery_signals`, `notes`.

## 4. Output Contracts

### `IncidentReport` (Read-Only Investigation)
- `report_id`, `schema_version`, `incident_id`, `incident_title`
- `verdict_status`: `DETERMINED` | `AMBIGUOUS` | `INSUFFICIENT_EVIDENCE`
- `primary_root_cause`: `HypothesisEvaluation | null` (always `null` for `AMBIGUOUS` or `INSUFFICIENT_EVIDENCE`)
- `hypotheses`: ranked list of `HypothesisEvaluation` with `supporting_evidence`, `counterevidence`, `modalities_supporting`, `uncertainty_factors`, and `discriminating_checks`
- `timeline`: `IncidentTimeline` with UTC-ordered `events`, `trace_gaps`, and `correlation_groups`
- `proposed_remediations`: list of `RemediationProposal` (`requires_explicit_approval=True`, `auto_executed=False`, `plan_digest`)
- `security_findings`: list of `SanitizationFinding` (`prompt_injection` or `secret_redaction`)
- `read_only_enforced`: literal `True`; `operational_changes_applied`: literal `0`
- `diagnostics_counters`, `diagnostic_log`, and `runtime_metadata`

### `RemediationReceipt` (Approval-Gated Simulation)
- `receipt_id`, `incident_id`, `remediation_id`, `action_id`
- `status`: `EXECUTED_RECOVERED` | `EXECUTED_RECOVERY_FAILED` | `DENIED`
- `approval_id`, `approver_id`, `executed_in_simulation`, `state_mutated`, `denial_reason`
- `verification`: `RecoveryVerification` containing per-metric `before_value`, `after_value`, `threshold`, `unit`, `passed`, `seed`, and `rollback_recommended`.

## 5. Typed Validation & Policy Errors

| Exception Class | `error_code` | Trigger Condition |
|---|---|---|
| `ConfigurationError` | `CONFIGURATION_ERROR` | Missing, malformed, or schema-invalid config JSON |
| `InputValidationError` | `INPUT_VALIDATION_ERROR` | Malformed JSON, naive timestamp, negative duration, empty telemetry, extra fields |
| `UnsupportedSchemaError` | `UNSUPPORTED_SCHEMA_ERROR` | Unsupported `schema_version` or non-synthetic `environment` (`production`/`live`) |
| `BudgetExceededError` | `BUDGET_EXCEEDED_ERROR` | Exceeds `max_steps`, `max_tool_calls`, `max_llm_calls`, or `max_prompt_chars` |
| `ApprovalRequiredError` | `APPROVAL_REQUIRED_ERROR` | Simulated remediation invoked with `approval=None` |
| `ApprovalMismatchError` | `APPROVAL_MISMATCH_ERROR` | Unauthorized role, mismatched `plan_digest`/IDs, or expired approval |
| `ForbiddenActionError` | `FORBIDDEN_ACTION_ERROR` | Action in `FORBIDDEN_ACTIONS` or absent from `ALLOWLISTED_SIM_ACTIONS` |
| `AmbiguousRootCauseError` | `AMBIGUOUS_ROOT_CAUSE_ERROR` | Remediation invoked on `AMBIGUOUS` report without `acknowledge_ambiguity=True` |

## 6. Fixture Inventory (`data/fixtures/`)

- **Valid Reference:** `inc_ref_001_gateway_pool.json` + `reference_oracle.json`
- **Domain Edge Case:** `inc_missing_spans_002.json` (2 missing parent spans + archival market-data red-herring logs)
- **Security Integration:** `inc_prompt_injection_003.json` (3 prompt-injection payloads + 2 synthetic bearer/API-key secrets)
- **Boundary / Ambiguity:** `inc_ambiguous_004.json` (competing `internal_oms_gc_pause` vs `exchange_venue_throttling`)
- **Invalid Fixtures:** `invalid_schema_version.json` (`9.9.9`), `invalid_production_env.json` (`environment="production"`)
