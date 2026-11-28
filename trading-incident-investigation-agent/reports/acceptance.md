# Acceptance & Validation Report — Trading Incident Investigation Agent

> **Evidence Note:** All measurements below are **actual observed results on synthetic offline fixtures** (`data/fixtures/`), not production telemetry or live trading measurements. Live LLM API calls, production OTel collectors, and live OMS integrations are explicitly outside scope and marked **Not Run (Out of Scope)**.

## 1. Execution Environment & Configuration

| Field | Measured Value |
|---|---|
| Package Version | `0.1.0` |
| Schema Version | `1.0.0` |
| Python Version | `3.12.15` |
| Platform | `macOS-26.5.1-arm64-arm-64bit` |
| Pydantic / Pytest | `pydantic 2.14.4` / `pytest 8.4.2` |
| Config File | `config/default.json` (SHA-256 `a176d0b1040065a5...`) |
| Fixed Seed | `42` |
| Default Advisor Mode | `offline_template` |

## 2. Test & Validation Matrix Mapping

| Test Area | Required Scenario | Automated Test / Evidence | Measured Result | Status |
|---|---|---|---|---|
| **Domain correctness** | Missing spans and misleading logs (`INC-MS-002`) | `tests/test_domain_hypotheses.py::test_missing_spans_and_misleading_logs_scenario`, `reports/inc_ms_002_report.json` | Root cause `oms_rate_limit_throttle` (`conf=0.7783`), `2` missing parent spans flagged, archival market-data red-herring logs rejected (`conf < 0.30` with counterevidence), timeline ordering `1.0`, evidence precision `1.0` | **PASS** |
| **Integration and resilience** | Prompt injection in logs (`INC-PI-003`) | `tests/test_security_and_integration.py::test_prompt_injection_and_secret_redaction_in_logs`, `reports/inc_pi_003_report.json` | `3/3` prompt-injection payloads quarantined, `2/2` synthetic secrets redacted, verdict unaffected (`fix_session_sequence_gap`, `conf=0.8539`), `0` auto-executed actions, sanitized prompt verified via callback advisor | **PASS** |
| **Boundary and failure behavior** | Ambiguous root cause (`INC-AMB-004`) | `tests/test_remediation_and_boundaries.py::test_ambiguous_root_cause_surfaces_uncertainty_and_gates_remediation`, `reports/inc_amb_004_report.json` | Verdict `AMBIGUOUS` (`primary_root_cause=null`), both competing causes (`internal_oms_gc_pause`, `exchange_venue_throttling`, `conf=0.5377`) surfaced with counterevidence; remediation blocked until `acknowledge_ambiguity=True` | **PASS** |
| **Boundary and failure behavior** | Unauthorized action | `tests/test_remediation_and_boundaries.py::test_unauthorized_actions_are_blocked_without_state_mutation` | Missing approval (`ApprovalRequiredError`), unauthorized role, tampered `plan_digest`, expired approval (`ApprovalMismatchError`), and forbidden action `disable_risk_limits` (`ForbiddenActionError`) all blocked with `0` state mutations | **PASS** |
| **Reproducibility** | Same versioned inputs/config and fixed seed | `tests/test_security_and_integration.py::test_deterministic_replay_produces_identical_outputs`, `reports/evaluation_summary.json` | Byte-identical `IncidentReport` JSON and identical `report_id` across repeated runs on all 4 scenarios (`reproducible_replay=true`) | **PASS** |
| **Operational review** | Missing config, unsupported inputs, CLI exit codes | `tests/test_contracts_and_timeline.py`, `tests/test_remediation_and_boundaries.py::test_operational_diagnostics_missing_config_and_cli_flows` | Missing/malformed config -> `ConfigurationError`; schema `9.9.9` & `environment="production"` -> `UnsupportedSchemaError` (CLI exit `2`); naive timestamp & negative duration -> `InputValidationError` | **PASS** |

## 3. Project-Specific Acceptance Criteria

| Acceptance Criterion | Evidence & Measured Value | Status |
|---|---|---|
| **Report timeline ordering accuracy and evidence precision** | Across all 4 oracle scenarios in `reports/evaluation_summary.json`: `mean_timeline_exact_rank_accuracy = 1.0000`, `mean_timeline_pairwise_ordering_accuracy = 1.0000`, `mean_evidence_precision = 1.0000`, `mean_evidence_recall = 1.0000` (synthetic fixtures vs hand-calculated `reference_oracle.json`). | **PASS** |
| **No automatic operational changes** | Every investigation report enforces `read_only_enforced = true`, `operational_changes_applied = 0`, `auto_executed = false` on all proposals; `automatic_operational_changes = 0` in `reports/evaluation_summary.json`. | **PASS** |
| **All uncertainty clearly surfaced** | Trace gaps (`INC-MS-002`), counterevidence (`INC-MS-002`, `INC-AMB-004`), ambiguity margins (`INC-AMB-004`), prompt-injection warnings (`INC-PI-003`), and insufficient-evidence states are explicitly recorded in `uncertainty_notes` and `HypothesisEvaluation.uncertainty_factors`. | **PASS** |
| **All required test scenarios pass** | `pytest -v`: **16/16 passed in 0.05s**. `scripts/run_evaluation.py`: `all_scenarios_passed = true` (4/4 oracle scenarios). | **PASS** |
| **README documents setup, demo, validation, assumptions, and limitations** | Documented in `README.md` and `docs/runbook.md`, distinguishing synthetic fixture measurements from production scope. | **PASS** |
| **No real transactions, customer data, credentials, or proprietary artifacts** | Verified across all source, fixture, config, and report files; all identifiers (`SIMA`–`SIMD`, `SIMX`/`SIMY`, `ORD-SIM-*`, `sk-synth-FAKE...`) are synthetic. | **PASS** |

## 4. Per-Scenario Measured Summary (`reports/evaluation_summary.json`)

| Incident ID | Scenario | Verdict | Primary Failure Mode | Confidence (Tolerance) | Timeline Order (Exact / Pairwise) | Evidence (Prec / Rec) | Trace Gaps | Injections / Redactions | Raw Report |
|---|---|---|---|---|---|---|---|---|---|
| `INC-REF-001` | Reference baseline | `DETERMINED` | `gateway_connection_pool_exhaustion` | `0.8965` (`[0.70, 0.99]`) | `1.0 / 1.0` | `1.0 / 1.0` | `0` | `0 / 0` | `inc_ref_001_report.json` / `.md` |
| `INC-MS-002` | Missing spans & misleading logs | `DETERMINED` | `oms_rate_limit_throttle` | `0.7783` (`[0.50, 0.90]`) | `1.0 / 1.0` | `1.0 / 1.0` | `2` | `0 / 0` | `inc_ms_002_report.json` / `.md` |
| `INC-PI-003` | Prompt injection & secrets in logs | `DETERMINED` | `fix_session_sequence_gap` | `0.8539` (`[0.65, 0.99]`) | `1.0 / 1.0` | `1.0 / 1.0` | `0` | `3 / 2` | `inc_pi_003_report.json` / `.md` |
| `INC-AMB-004` | Ambiguous root cause | `AMBIGUOUS` | `null` (`internal_oms_gc_pause` vs `exchange_venue_throttling`) | `0.5377` (`[0.30, 0.75]`) | `1.0 / 1.0` | `1.0 / 1.0` | `0` | `0 / 0` | `inc_amb_004_report.json` / `.md` |

## 5. Approved Simulated Remediation Verification (`reports/remediation_demo_receipt.json`)

For `INC-REF-001`, after explicit `oncall_sre` approval bound to `plan_digest`, `SimulatedTradingEnvironment(seed=42)` executed `drain_and_recycle_gateway_pool` and verified all 3 simulated health checks (`status: EXECUTED_RECOVERED`, `rollback_recommended: false`):
- `gateway_pool_utilization_pct`: `100.0%` → `39.285%` (threshold `< 75.0%`) — **PASS**
- `p99_ack_latency_ms`: `2450.0 ms` → `46.313 ms` (threshold `< 150.0 ms`) — **PASS**
- `order_timeout_rate_pct`: `14.2%` → `0.198%` (threshold `< 0.5%`) — **PASS**

Failed-recovery detection (`EXECUTED_RECOVERY_FAILED`, `rollback_recommended: true`) is verified in `tests/test_remediation_and_boundaries.py::test_approved_simulated_remediation_verifies_recovery_and_detects_failed_recovery`.

## 6. Explicitly Untested / Out-of-Scope Capabilities

- **External / Hosted LLM Providers (Not Run):** The `CallbackNarrativeAdvisor` boundary and prompt budget enforcement are tested with a local mock callback; live networked LLM API calls are intentionally excluded from offline deterministic tests.
- **Live Telemetry Backends & Production Remediation (Out of Scope):** No live OpenTelemetry collectors, exchange FIX sessions, OMS instances, or production credentials are connected.
- **GitHub Actions Remote Execution (Not Run Locally):** `.github/workflows/ci.yml` is authored and mirrors the exact commands verified locally, but remote GitHub Actions runner execution was not triggered from this offline workspace.
