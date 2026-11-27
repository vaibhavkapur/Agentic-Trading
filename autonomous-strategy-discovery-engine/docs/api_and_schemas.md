# API, Contracts, and Schema Reference

## Domain Contracts (`src/asde/types.py`)

- `MarketBar`: `{symbol, event_time_utc, available_time_utc, open, high, low, close, volume, currency}` (all timestamps ISO-8601 UTC with `Z`; `available_time_utc >= event_time_utc`; strictly positive OHLC).
- `DatasetManifest`: `{dataset_id, schema_version, source_type, entitlement, license_note, currency, frequency, symbols, start_time_utc, end_time_utc, row_count, data_file, data_sha256, seed}`.
- `TrialRecord`: `{trial_id, run_id, strategy_id, family, is_baseline, phase, status, seed, parameters, dataset_fingerprint, split_manifest_hash, cost_scenario, cost_scenario_hash, created_at_utc, metrics, fold_metrics, rejection_reasons, error}`.
- `EvaluationMetrics`: Includes `total_return`, `cagr`, `annualized_volatility`, `sharpe_ratio`, `sortino_ratio`, `max_drawdown`, `calmar_ratio`, `annualized_turnover`, `total_cost_drag`, `gross_total_return`, `gross_sharpe_ratio`, `win_rate`, `profit_factor`, `num_bars`, `sharpe_se`, `sharpe_ci_low`, `sharpe_ci_high`, `cagr_ci_low`, `cagr_ci_high`, `skewness`, `kurtosis`.

## Strategy DSL Schema (`src/asde/dsl/schema.py`)

- Allowed families in `config/strategy_catalog.json` (`dsl_version: "1.0.0"`):
  - `trend_ma_crossover` (`fast_window < slow_window`, volatility-targeted, rebalance band)
  - `mean_reversion_zscore` (`exit_z < entry_z`, rolling z-score state machine)
  - `volatility_breakout` (`exit_window < breakout_window`, Donchian channel breakout)
  - `dual_momentum` (cross-sectional + absolute momentum, long-only)
- Allowed baselines (evaluated on identical data and costs):
  - `baseline_buy_and_hold`
  - `baseline_cash`
  - `baseline_risk_parity_equal_weight`

## Adapter Protocols

- `BacktesterAdapter` (`src/asde/evaluation/backtester.py`): `run_slice(dataset, signals, cost_scenario, start_idx, end_idx, ...) -> BacktestResult`
- `OptimizerAdapter` (`src/asde/search/optimizer.py`): `tune_candidate(run_id, base_spec, dataset, holdout_guard, cost_scenario, max_inner_trials, seed) -> TuningOutcome`
- `TrialStore` (`src/asde/reporting/trial_store.py`): `record_trial`, `record_many`, `list_trials`, `accounting_summary`

## Structured Errors (`src/asde/errors.py`)

| Error Class | Code | Trigger |
|---|---|---|
| `DslValidationError` | `DSL_VALIDATION_ERROR` | Unknown family, out-of-bounds parameter, constraint violation, version mismatch |
| `UnconstrainedCodeError` | `UNCONSTRAINED_CODE_FORBIDDEN` | Non-null `raw_code` or forbidden parameter keys (`code`, `python`, `eval`, `exec`, etc.) |
| `LookAheadError` | `LOOK_AHEAD_VIOLATION` | `signal_lag_bars < 1`, negative lag override, future `available_time_utc`, or look-ahead shift |
| `HoldoutLeakageError` | `HOLDOUT_LEAKAGE_VIOLATION` | Pre-lock read of `test` split or inner fold extending past `train_end` |
| `ManifestIntegrityError` | `MANIFEST_INTEGRITY_ERROR` | SHA-256 mismatch on dataset CSV, split manifest, or exported package |
| `GovernanceViolationError` | `GOVERNANCE_VIOLATION` | Execution enabled, live target requested, self-review, or incomplete checklist |

## CLI Reference (`src/asde/cli.py`)

```bash
PYTHONPATH=src python3 -m asde.cli discover --config config/default_discovery.json --out reports/demo_run
PYTHONPATH=src python3 -m asde.cli verify-package --package reports/demo_run/packages/<strategy_id>
PYTHONPATH=src python3 -m asde.cli review --package reports/demo_run/packages/<strategy_id> \
  --reviewer <reviewer_id> --decision APPROVE_PAPER_ONLY --rationale "<rationale>"
```
