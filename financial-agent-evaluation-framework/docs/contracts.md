# Data Contracts — Financial Agent Evaluation Framework

**Contract Schema Version:** `1.0.0`  
**Implementation:** [schemas.py](../src/fin_eval/schemas.py)

All input and output models inherit from `StrictModel` (`extra="forbid"`, `validate_assignment=True`) so unknown fields or silent coercions fail fast with `ContractValidationError`.

## 1. Units, Timestamps, and Identifiers

### Numeric Units (`NumericUnit`)
| Dimension | Allowed Units | Canonical Conversion |
|---|---|---|
| Currency (USD) | `USD`, `USD_THOUSANDS`, `USD_MILLIONS`, `USD_BILLIONS` | `1 USD_BILLIONS = 1e3 USD_MILLIONS = 1e6 USD_THOUSANDS = 1e9 USD` |
| Rates & Ratios | `RATIO`, `PERCENT`, `BPS` | `1.0 RATIO = 100.0 PERCENT = 10000.0 BPS` |
| Discrete | `SHARES`, `COUNT`, `DAYS` | Exact unit match required |

Cross-dimension comparisons (e.g., claiming `USD_MILLIONS` when `PERCENT` is expected) emit `FailureType.UNIT_MISMATCH`.

### Timestamp Semantics (`UtcDateTime`)
- All timestamps (`as_of_utc`, `published_at_utc`, `executed_at_utc`, `created_at_utc`, `reviewed_at_utc`) **must be timezone-aware ISO-8601 strings** (e.g., `2026-02-16T12:00:00Z`).
- Naive timestamps (e.g., `2026-02-16T12:00:00`) are rejected at validation time with `ValueError`.
- Staleness is computed deterministically as `(task.as_of_utc - evidence.as_of_utc).total_seconds() > task.max_evidence_age_seconds`.

### Identifiers
| Identifier | Pattern / Format | Purpose |
|---|---|---|
| `task_id` | `^[A-Z0-9_-]{3,64}$` | Unique task key within a dataset |
| `evidence_id` | `^EVD-[A-Z0-9_-]{3,64}$` | Immutable evidence record key |
| `config_id` | `^[a-z0-9_-]{3,64}$` | Model/agent runtime config identifier |
| `fault_id` | `^[A-Z0-9_-]{3,64}$` | Failure injection rule identifier |
| `report_id` | `eval-{dataset_id}-{config_id}-{sha256[:12]}` | Deterministic logical report identifier |

## 2. Input Contracts

1. **`GoldTaskDataset` (`data/fixtures/gold_tasks_*_v1.json`)**
   - Required fields: `schema_version`, `dataset_id`, `dataset_version`, `split` (`dev` | `held_out`), `tasks` (non-empty list of `GoldTask`).
   - Invariants: Unique `task_id`s; every task's `split` matches dataset `split`; `allowed_tools` and `forbidden_tools` must be disjoint; `min_calls <= max_calls`.
2. **`MockFixtureStore` (`data/fixtures/mock_store_v1.json`)**
   - Required fields: `schema_version`, `fixture_version`, `provenance`, `evidence_records`, `filing_metrics`, `market_quotes`, `macro_indicators`.
   - Every `EvidenceRecord` enforces `is_untrusted_text: Literal[True] = True`.
3. **`ModelConfig` (`config/model_*.json`)**
   - Enforces `live_execution_enabled: Literal[False] = False`, positive `budget_usd`, `max_tool_calls`, and `max_latency_ms`.
   - `external_network_allowed` defaults to `false`.
4. **`FailureInjectionProfile` (`config/faults_*.json`)**
   - List of `FaultRule`s targeting `tool_unavailable`, `tool_timeout`, `tool_malformed_response`, `stale_evidence`, `prompt_injection`, or `rate_limit`.

## 3. Output Contracts

1. **`TaskEvaluationResult`**
   - Contains `task_id`, `task_version`, `split`, `category`, `run_id`, `seed`, `overall_score` (`[0.0, 1.0]`), `passed`, per-grader `check_results`, `failure_types`, `receipt_verified`, `cost_usd`, `latency_ms`, `token_usage`, `faults_triggered`, and `human_rubric_template_id`.
2. **`EvaluationReport`**
   - Contains `report_id`, `schema_version`, `framework_version`, `created_at_utc`, dataset/fixture/config versions, `seeds`, `runtime_environment`, `model_config_snapshot`, `summary` (`MetricSummary` with 95% Wilson pass-rate CI and 95% t-interval score CI, cost, latency, failure-type counts), `task_results`, `diagnostic_counters`, and optional `baseline_comparison`.
3. **`ReplayBundle`**
   - Persists exact tasks, trajectories, retrieved evidence, signed receipts, signing key, and injected faults so `fin-eval replay` can re-grade any run deterministically offline.

## 4. Validation Errors and Fixture Coverage

| Fixture Type | Path | Expected Behavior |
|---|---|---|
| Valid Dev Dataset | `data/fixtures/gold_tasks_dev_v1.json` | Passes validation (8 tasks, `dev` split) |
| Valid Held-Out Dataset | `data/fixtures/gold_tasks_held_out_v1.json` | Blocked by `HeldOutLeakageError` unless `--include-held-out` is passed |
| Reference Oracle | `data/fixtures/reference_oracle_v1.json` | Hand-calculated `312.5 / 1250.0 * 100 = 25.0%` verified by unit test |
| Invalid (Naive Timestamp) | `data/fixtures/invalid/naive_timestamp_dataset.json` | Raises `ContractValidationError` (`timezone-aware`) |
| Invalid (Tool Overlap) | `data/fixtures/invalid/overlapping_tools_dataset.json` | Raises `ContractValidationError` (`allowed and forbidden`) |
| Boundary Tolerances | `tests/test_boundary_reproducibility_ops.py` | Exact boundary `25.025` passes; `25.026` and `NaN` fail |
