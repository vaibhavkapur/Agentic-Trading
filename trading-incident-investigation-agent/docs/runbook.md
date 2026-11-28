# Operator & Developer Runbook

## 1. Environment Setup

Requires Python 3.11+ and Pydantic v2 (`pyproject.toml`).

```bash
cd trading-incident-investigation-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If running in an offline environment where an existing Python 3.12 virtualenv already provides `pydantic` and `pytest`, run with `PYTHONPATH=src`:

```bash
PYTHONPATH=src pytest -v
```

## 2. Demo Walkthrough

### A. Read-Only Investigation (Default Safe Mode)

```bash
PYTHONPATH=src python3 -m trading_incident_agent.cli demo \
  --fixture data/fixtures/inc_ref_001_gateway_pool.json \
  --config config/default.json
```

Expected behavior:
- Prints a cited Markdown root-cause report (`Verdict: DETERMINED`, `gateway_connection_pool_exhaustion`).
- Does **not** execute any remediation (`read_only_enforced=True`, `operational_changes_applied=0`).
- Prints the SHA-256 `plan_digest` required for explicit operator approval.

### B. Explicitly Approved Simulated Remediation & Recovery Verification

```bash
PYTHONPATH=src python3 -m trading_incident_agent.cli demo \
  --fixture data/fixtures/inc_ref_001_gateway_pool.json \
  --config config/default.json \
  --approve-demo
```

Expected behavior:
- Constructs an `OperatorApproval` bound to the proposal's `plan_digest` with role `oncall_sre`.
- Executes the bounded simulated remediation (`drain_and_recycle_gateway_pool`) in memory with seed `42`.
- Prints a `RemediationReceipt` with `status: EXECUTED_RECOVERED` and before/after health-check metrics.

### C. Reproducible Evaluation & Report Generation

```bash
PYTHONPATH=src python3 scripts/run_evaluation.py
```

Writes versioned raw JSON/Markdown reports and `reports/evaluation_summary.json`.

## 3. Validation Commands

```bash
# Run full unit, integration, security, and boundary test suite
PYTHONPATH=src pytest -v

# Run CLI oracle evaluation directly
PYTHONPATH=src python3 -m trading_incident_agent.cli evaluate \
  --fixtures-dir data/fixtures \
  --config config/default.json
```

## 4. Diagnostics & Recovery Procedures

Every `IncidentReport` includes `diagnostics_counters` and `diagnostic_log` (step-by-step trace) plus `runtime_metadata` (`input_digest`, `config_digest`, `seed`).

| Failure Mode / Error Code | Diagnostic Signal | Recovery Steps |
|---|---|---|
| `CONFIGURATION_ERROR` | Missing or malformed config JSON | Verify `--config` path and validate against `config/default.json` schema. |
| `UNSUPPORTED_SCHEMA_ERROR` | Non-`1.0.0` `schema_version` or `environment="production"` | Convert input to schema `1.0.0` and ensure only synthetic/paper/sim telemetry is supplied. |
| `INPUT_VALIDATION_ERROR` | Naive timestamps, negative durations, empty telemetry | Add explicit UTC offsets (`Z`), fix invalid values, and rerun. |
| `BUDGET_EXCEEDED_ERROR` | `max_steps` / `max_tool_calls` / `max_llm_calls` exceeded | Inspect `config/default.json` budgets; reduce input size or raise budget intentionally. |
| `APPROVAL_REQUIRED_ERROR` / `APPROVAL_MISMATCH_ERROR` | Missing, expired, unauthorized-role, or tampered approval | Re-issue a fresh `OperatorApproval` from an authorized role matching the exact `plan_digest`. |
| `AMBIGUOUS_ROOT_CAUSE_ERROR` | Competing hypotheses within `ambiguity_margin` | Execute `discriminating_checks` listed in the report; only set `acknowledge_ambiguity=True` after operator disambiguation. |
| `EXECUTED_RECOVERY_FAILED` | Post-remediation health checks stayed above threshold | Follow `rollback_recommended=True` in `RemediationReceipt` and inspect simulated metrics. |

## 5. Limitations & Out-of-Scope Boundaries

- **Offline simulation only:** No live broker, OMS, FIX engine, Kubernetes cluster, or production telemetry store is connected.
- **No automatic operational changes:** Read-only analysis is enforced structurally by `IncidentReport`.
- **Regex-based sanitization defense-in-depth:** Pattern matching catches known secret and prompt-injection signatures; privilege isolation guarantees injected text still cannot alter deterministic verdicts or execute actions even if a novel phrasing bypasses regex detection.
