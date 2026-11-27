# Acceptance Evidence — Recursive AI Research Platform (MVP)

This document links every acceptance criterion in `plan.md` (§6) and every required failure-path scenario (§5) to committed code and retained verification evidence.

## Acceptance Criteria Checklist

| Criterion (`plan.md` §6) | Status | Verification Evidence |
|---|---|---|
| Every result resolves to a versioned run and data manifest. | Verified | `src/rarp/registry/store.py` (`RunRecord`), `reports/demo_report.json` (`data_manifest_id`, `data_manifest_sha256`, `record_sha256`, `registry_hash_chain_valid: true`), `tests/integration/test_end_to_end.py`. |
| A configured iteration/cost budget cannot be exceeded. | Verified | `src/rarp/scheduler/budget.py` (pre-dispatch atomic reservation), `tests/unit/test_dsl_and_dag.py`, `reports/scenario_evidence.json` (`budget_exhaustion.passed: true`). |
| Replaying the same deterministic run gives the same result within declared tolerance. | Verified | `reports/reproducibility_report.json` (`reproducible: true`, `max_abs_metric_diff: 0.0 <= 1e-12`), `scripts/reproduce.sh`. |
| Independent reviewer alone can approve promotion. | Verified | `src/rarp/governance/review.py` (`reviewer_id != proposer_id`, bans `auto_*`/`agent_*` & `LIVE` target), `tests/unit/test_registry_and_governance.py`, `tests/integration/test_end_to_end.py`. |
| A failed hypothesis remains discoverable. | Verified | `src/rarp/registry/memory.py` (`failed_hypotheses()`), `src/rarp/governance/console.py` (`/api/memory/hypotheses?failed_only=true`), `reports/scenario_evidence.json` (`future_data_mutation.discoverable_failed_count: 1`). |
| A clean checkout can run the documented setup, tests and demo with permitted fixtures. | Verified | `scripts/setup.sh`, `scripts/validate.sh`, `scripts/demo.sh`, `scripts/reproduce.sh` executed cleanly on Python 3.9.6 with zero external dependencies. |
| Architecture, dependency assumptions, known limitations and runbook are committed. | Verified | `docs/architecture.md`, `docs/api_and_schemas.md`, `docs/assumptions_and_limitations.md`, `docs/runbook.md`, `docs/adr/0001..0004`. |
| Relevant CI checks pass and raw evaluation or test evidence is retained. | Verified | `reports/test_report.txt` (13/13 tests OK), `reports/scenario_evidence.json` (6/6 scenarios passed), `reports/demo_report.json`, `reports/demo_summary.md`, `reports/reproducibility_report.json`. |
| Security, data licensing, IP and any deployment approval requirements are reviewed. | Documented & Gated | Synthetic-only fixtures with explicit `PERMITTED_INTERNAL_RESEARCH_SYNTHETIC` entitlement; zero secrets in code/config; TS-14 external code copying blocked (`TS14BacktesterAdapter`) until IP/licensing confirmation; `LIVE` execution hard-disabled (`docs/assumptions_and_limitations.md`). |

## Required Failure-Path Scenarios (`plan.md` §5)

All 6 scenarios are automated in `tests/scenarios/test_required_scenarios.py` with raw evidence retained in `reports/scenario_evidence.json`:

1. **Future-data mutation:** Manifest SHA-256 tamper & `available_time_utc > event_time_utc` both rejected with `LeakageError`; rejected run recorded in immutable registry and discoverable in negative memory.
2. **Repeated hypotheses:** Exact semantic fingerprint duplicate and near-duplicate both rejected with `DuplicateHypothesisError` before consuming budget.
3. **Budget exhaustion:** Hard USD cost ceiling stops dispatch at 2 experiments (`$0.20 <= $0.25`) raising `BudgetExhaustedError`.
4. **Worker crash and retry:** Mid-execution `WorkerCrashError` checkpointed on attempt 1, retried and succeeded on attempt 2, single finalized run recorded, idempotent replay deduplicated without double-charging budget.
5. **Hallucinated metric:** Fabricated Sharpe value, non-existent metric name, and forged artifact SHA-256 all rejected with `HallucinatedMetricError`, logged to audit log, and promotion blocked.
6. **Holdout access denial:** Missing token, proposer self-unlock, forged token, and reused single-use token all denied with `HoldoutAccessError`; independent reviewer single-use token granted once; all 5 events logged.
