# Operator & Developer Runbook

## 1. Clean-Checkout Setup & Verification

```bash
cd ai-investment-committee
python3 --version                        # Requires Python >= 3.9
python3 scripts/run_acceptance.py        # Runs all 18 tests + demo + writes reports/
```

Optional editable install in a virtual environment (when network or local wheelhouse is available):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-build-isolation --no-deps -e .
ai-committee --help
```

## 2. Standard Demo Walkthrough

```bash
python3 scripts/run_demo.py
```
Artifacts produced:
- `reports/demo_deliberations.sqlite3` — Persisted SQLite database of demo deliberations & approvals.
- `reports/demo_run_summary.json` — Machine-readable summary across all 5 governance scenarios.
- `reports/baseline_comparison.json` — Metric-by-metric comparison against `data/fixtures/reference_expected_output.json`.

## 3. Diagnostics & Structured Telemetry

- **Structured logs:** `InvestmentCommitteeService` emits JSON log events on logger `ai_investment_committee` (`deliberation_completed`, `human_approval_recorded`) containing `decision_id`, `proposal_id`, `proposal_hash`, `verdict`, `status`, and `total_cost_usd`.
- **In-process counters (`service.counters`):**
  - `deliberations_run`, `risk_passes`, `risk_vetoes`
  - `human_approvals_recorded`, `human_rejections_recorded`
  - `replays_executed`, `errors_raised`
  - `prompt_injections_flagged`, `fabricated_citations_caught`
- **CLI error output:** All domain failures exit with status `1` and print structured JSON (`error_code`, `error_type`, `message`, `details`) to `stderr`.

## 4. Failure Modes & Recovery Procedures

| Failure (`error_code`) | Root Cause | Recovery Action |
|---|---|---|
| `MISSING_CONFIGURATION_ERROR` | Missing/malformed config or proposal JSON, or unknown `decision_id` | Verify `--config`, `--proposal`, and `--db` paths; inspect JSON syntax and retry. |
| `SCHEMA_VALIDATION_ERROR` | Invalid input schema, non-UTC timestamp, negative quantity, or uncited claim | Fix the offending field reported in `details.field_errors`; never disable validation. |
| `NO_EXECUTION_CAPABILITY` | `execution_mode="LIVE"` or `allow_live_execution=true` | Change proposal to `execution_mode="PAPER"` and `allow_live_execution=false`. Live execution is out of scope. |
| `AGENT_TIMEOUT` | Role latency exceeded `agent_budgets.<role>.max_latency_ms` | Inspect slow tool/adapter latency; no partial decision was written. Re-run once latency issue is resolved or update versioned config with documented rationale. |
| `BUDGET_EXCEEDED` | Role exceeded `max_tool_calls`, `max_tokens`, or `max_cost_usd` | Reduce input brief volume or review adapter verbosity; do not silently bypass budgets. |
| `RISK_VETO_BYPASS_FORBIDDEN` | Human approval submitted for a `VETOED` decision | **Do not override.** Create a new resized/corrected paper proposal (new `proposal_id` and `proposal_hash`) that satisfies risk policy and re-run deliberation. |
| `PROPOSAL_HASH_MISMATCH` | Proposal changed after review or wrong hash supplied | Run `ai-committee list` or inspect the stored trace to confirm the exact `proposal_hash` reviewed by the human before re-submitting. |
| `DUPLICATE_APPROVAL` | `approval_id` reused or decision already finalized (including after restart) | Inspect existing approval via `ai-committee replay --decision-id <id>`; no further state change is permitted for finalized decisions. |

## 5. Restart & Rerun Verification

SQLite (`reports/*.sqlite3`) persists `deliberations`, `human_approvals`, and `evaluation_runs` across process restarts. After any restart:
1. Run `PYTHONPATH=src python3 -m ai_investment_committee list --db <db_path>` to inspect persisted states.
2. Run `PYTHONPATH=src python3 -m ai_investment_committee replay --db <db_path> --decision-id <id>` to verify `exact_match: true`.
