# Operator Runbook — Recursive AI Research Platform

Run the commands in this guide from `recursive-ai-research-platform/`. See the [project README](../README.md) for prerequisites.

## Standard Operating Procedures

### 1. Clean Checkout Setup & Verification
```bash
bash scripts/setup.sh
bash scripts/validate.sh
bash scripts/demo.sh
bash scripts/reproduce.sh
```

### 2. Reviewing Candidates in the Review Console
```bash
PYTHONPATH=src python3 -m rarp serve-console --state-dir reports/demo_state --host 127.0.0.1 --port 8080
```
- Verify `/health` reports `"registry_hash_chain_valid": true` and `"execution_mode": "DISABLED"`.
- Inspect `GET /api/memory/hypotheses?failed_only=true` to review rejected/failed hypotheses and total trial count before approving any candidate.
- Submit human approval only for `PAPER_SANDBOX` via `POST /api/reviews/decide` using an independent `reviewer_id`.

## Health, Failure & Decision Metrics

Operators should monitor these recorded telemetry fields from `RunRegistry.list_audit_events()` and `/health`:
- `registry_hash_chain_valid`: must always be `true`.
- `BUDGET_EXHAUSTED` / `BudgetSnapshot`: verify `cost_usd_used <= max_cost_usd` and `iterations_used <= max_iterations`.
- `LEAKAGE_DETECTED`: count of point-in-time or manifest hash failures (expected 0 in clean pipelines; any non-zero event halts the affected dataset).
- `HALLUCINATED_METRIC_DETECTED`: count of rejected critic claims (any non-zero event quarantines the critic adapter).
- `WORKER_CRASH_CHECKPOINTED`: retry rate for worker execution.
- `HOLDOUT_ACCESS_DENIED`: unauthorized holdout access attempts.
- `PROMOTION_TARGET_BLOCKED` / `REVIEW_SEPARATION_OF_DUTIES_VIOLATION`: governance policy rejections.

## Incident Response & Safe Fallbacks

| Failure Mode | Detection | Immediate Operator Response | Safe Fallback |
|---|---|---|---|
| **Future-data mutation / Leakage** | `LEAKAGE_DETECTED` error & `REJECTED` run | Quarantine offending fixture/manifest; verify upstream ETL `available_time_utc` timestamps and SHA-256 manifest. | Revert to last verified immutable `DataManifest`. |
| **Hallucinated Critic Metric** | `HALLUCINATED_METRIC_DETECTED` audit event | Block promotion; inspect offending `CriticAdapter` output and disable external LLM adapter if active. | Switch `ResearchCritic` to `DeterministicCriticAdapter`. |
| **Worker Crash / Retries Exhausted** | `WORKER_CRASH_CHECKPOINTED` & `FAILED` run | Inspect worker logs; rerun with identical `ExperimentSpec` (idempotency key prevents duplicate runs or double billing). | Keep failed run in registry for audit; do not delete records. |
| **Budget Exhaustion** | `BUDGET_EXHAUSTED` / `STOP_PATIENCE_PLATEAU` | Review `BudgetSnapshot` and `ResearchMemory`; adjust `config/research_config.json` via versioned PR if additional search is justified. | Loop halts safely with zero overspend. |
| **Artifact Signature or Hash Chain Failure** | `ARTIFACT_SIGNATURE_INVALID` or `verify_hash_chain() == False` | Halt all promotions immediately; investigate potential file/DB tampering. | Re-run deterministic replay (`scripts/reproduce.sh`) into a clean state directory and compare hashes. |
| **Unauthorized Holdout or Live-Promotion Attempt** | `HOLDOUT_ACCESS_DENIED` or `PROMOTION_TARGET_BLOCKED` | Audit `actor_id` in `audit_log.jsonl`; verify role separation and access controls. | Execution remains `DISABLED`; holdout remains sealed. |
