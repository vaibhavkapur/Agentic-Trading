# API & Schema Reference

## Schema Version

All canonical domain objects declare `schema_version = "1.0.0"`, UTC ISO-8601 timestamps ending in `Z`, and explicit units (`USD`, `bps`, `bars`).

## Core Domain Contracts

### `HypothesisSpec`
- `hypothesis_id`: unique string identifier
- `title`, `rationale`: human-readable description (scanned against `disallowed_tokens`)
- `family`: allowlisted family from `config/strategy_catalog.json` (`momentum_crossover`, `mean_reversion_zscore`, `volatility_breakout`)
- `parameters`: typed, bounded dict strictly matching catalog schema; must include `signal_lag_bars >= 1`
- `universe`: non-empty list of symbol identifiers
- `proposer_id`: author/agent identity (enforced distinct from `reviewer_id` at promotion)
- `parent_hypothesis_id`, `generation`: lineage tracking
- `semantic_fingerprint()`: canonical SHA-256 over `(family, sorted normalized parameters, sorted universe)`

### `ExperimentSpec`
- `experiment_id`, `hypothesis`, `data_manifest_id`, `data_manifest_sha256`
- `split`: `SplitSpec(train_ratio, validation_ratio, holdout_ratio, embargo_bars >= 1)`
- `cost_model`: `CostModelSpec(scenario_name, currency="USD", commission_bps, half_spread_bps, slippage_bps, annual_borrow_bps)`
- `seed`, `initial_capital_usd`, `code_version`
- `idempotency_key()`: canonical SHA-256 over hypothesis fingerprint, manifest hash, split, cost model, seed, capital, and code version

### `DataManifest`
- `manifest_id`, `dataset_name`, `source_type`, `entitlement`, `license_notes`
- `symbols`, `row_count`, `start_event_time_utc`, `end_event_time_utc`, `content_sha256`, `created_at_utc`, `file_path`

### `CriticReport` & `MetricClaim`
- `MetricClaim(run_id, metric_name, claimed_value, artifact_sha256)` — every claim is independently verified against `RunRegistry` within `metric_tolerance` (`1e-9` default)
- `verdict`: `CANDIDATE_FOR_REVIEW` | `REFINE` | `REJECT`
- `trial_accounting`: `total_trials`, `succeeded_trials`, `failed_or_rejected_trials`, `probabilistic_sharpe_ratio`, `deflated_sharpe_ratio`, `bonferroni_p_value`

## Structured Error Codes

| Error Class | Code | Trigger |
|---|---|---|
| `RARPValidationError` | `VALIDATION_ERROR` | Invalid schema, bounds, relational constraint, or DAG cycle |
| `LeakageError` | `LEAKAGE_DETECTED` | `available_time_utc > event_time_utc`, non-monotonic bars, or manifest SHA-256 mismatch |
| `DuplicateHypothesisError` | `DUPLICATE_HYPOTHESIS` | Exact semantic fingerprint match or near-duplicate below threshold |
| `BudgetExhaustedError` | `BUDGET_EXHAUSTED` | Iteration, experiment, USD cost, compute, or LLM token limit reached |
| `WorkerCrashError` | `WORKER_CRASH` | Mid-execution worker crash (checkpointed and retried up to `max_retries`) |
| `HallucinatedMetricError` | `HALLUCINATED_METRIC` | Missing run, unknown metric, forged artifact hash, or numerical mismatch |
| `HoldoutAccessError` | `HOLDOUT_ACCESS_DENIED` | Holdout read without valid single-use independent reviewer token |
| `ReviewGateError` | `REVIEW_GATE_DENIED` | Missing verified critic, non-succeeded run, or proposer/agent self-approval |
| `ArtifactSignatureError` | `ARTIFACT_SIGNATURE_INVALID` | Payload SHA-256 or HMAC-SHA256 mismatch |
| `PolicyViolationError` | `POLICY_VIOLATION` | Unrestricted code tokens, `LIVE` promotion attempt, registry overwrite, or unvetted TS-14 external copy |

## Review Console HTTP Endpoints

Available via built-in WSGI server (`rarp serve-console`) and optional FastAPI adapter (`create_fastapi_app`):

| Method & Path | Description |
|---|---|
| `GET /` | HTML Review Console displaying runs, failed hypotheses, hash-chain status, and decisions |
| `GET /health` | Health status, hash-chain integrity, run count, and `execution_mode: "DISABLED"` |
| `GET /api/runs[?status=...]` | List immutable run records |
| `GET /api/runs/{run_id}` | Full run record, verified critic report, and review decisions |
| `GET /api/memory/hypotheses[?failed_only=true]` | Query all or negative/failed hypotheses |
| `GET /api/reports/{run_id}` | Evidence-linked critic report for a run |
| `GET /api/reviews` | Immutable log of human review decisions |
| `POST /api/reviews/decide` | Submit independent human review decision (`PAPER_SANDBOX` only) |
