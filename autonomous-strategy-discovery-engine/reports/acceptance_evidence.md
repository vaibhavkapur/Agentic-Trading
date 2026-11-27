# Acceptance & Milestone Verification Evidence

**Run ID:** `run_927735496198`  
**Report Fingerprint (SHA-256):** `d867ed600d96e54561ce12eeec3da42731c55d377acc083fce38f075d515a315`  
**Dataset Fingerprint (SHA-256):** `95d1d5dd098eb177...` (`synthetic_equities_daily_v1`, 1,800 bars x 4 symbols)  
**Split Manifest Hash (SHA-256):** `def5ca74c8c8e7b2...`  
**Environment:** Python 3.9.6 (zero external mandatory runtime dependencies)

## 1. Automated Test Suite Summary

- **Command:** `bash scripts/validate.sh`
- **Result:** `21 / 21` tests passed (`OK`), including:
  - Unit tests (`tests/unit/`): DSL/catalog validation, unconstrained-code ban, chronological embargoed splits, manifest tamper detection, HoldoutGuard, cost monotonicity, metrics uncertainty, PSR/DSR/Bonferroni/Holm/BH-FDR, package tamper detection, and ReviewGate governance enforcement.
  - Integration tests (`tests/integration/`): End-to-end discovery pipeline, SQLite/JSONL failure & trial accounting, CLI `discover`, `verify-package`, and `review`.
  - Required Scenario tests (`tests/scenarios/test_required_scenarios.py`): All 6 required scenarios verified and persisted in `reports/scenario_evidence.json` (`all_passed: true`).

## 2. Required Verification Scenarios (Section 5)

| Scenario | Verified Outcome | Evidence File |
|---|---|---|
| Look-ahead injection | Compiler shift injection and future `available_time_utc` injection both rejected with `LOOK_AHEAD_VIOLATION`; clean signal compiles. | `reports/scenario_evidence.json` |
| Same seed rerun | Identical `run_id`, `report_fingerprint`, `leaderboard.json`, `trials.jsonl`, and `split_manifest.json` verified via `diff -u` in `scripts/reproduce.sh`. | `reports/scenario_evidence.json` |
| Holdout leakage | Pre-lock `test` slice read blocked with `HOLDOUT_LEAKAGE_VIOLATION` (`blocked_attempts: 1`, `holdout_reads_during_selection: 0`); tampered manifest rejected with `MANIFEST_INTEGRITY_ERROR`. | `reports/scenario_evidence.json` |
| Multiple-testing inflation | 40 pure-noise trials yielded naive best Sharpe `1.380` (PSR `0.864`), deflated by DSR to `0.135` (`expected_max_null_sharpe: 2.765`, BH q-value `0.971`, `0` FDR survivors). | `reports/scenario_evidence.json` |
| Excessive turnover | High-churn candidate (`48.92x` > `10.0x` cap) rejected with `excessive_turnover` reason while retained in leaderboard and trial ledger; net return degraded vs gross. | `reports/scenario_evidence.json` |
| Cost sensitivity | Identical cost hashes applied to candidate and buy-and-hold baseline across `zero_cost_reference`, `base_institutional`, `stressed_2x`, `severe_3x`; monotonic cost drag increase and net return degradation confirmed. | `reports/scenario_evidence.json` |

## 3. Acceptance Criteria Checklist (Section 6)

| Criterion | Status | Evidence |
|---|---|---|
| Every trial is accounted for including failures | Verified | `reports/demo_run/trial_ledger.sqlite`, `reports/demo_run/trials.jsonl` (93 trials recorded), `test_end_to_end_pipeline_accounts_for_all_trials_including_failures` |
| Test split is untouched during candidate selection | Verified | `HoldoutGuard` audit (`holdout_reads_during_selection: 0`), `test_holdout_guard_blocks_pre_lock_and_allows_post_lock`, Scenario 3 |
| Baselines and candidates use identical costs and data | Verified | Identical `dataset_fingerprint` and `cost_scenario_hash` asserted across all baselines and candidates in `test_pipeline_and_cli.py` and `reports/demo_report.json` |
| Report includes uncertainty, turnover and drawdown | Verified | `reports/demo_leaderboard.md` & `reports/demo_report.json` (95% bootstrap Sharpe & CAGR CIs, Sharpe SE, DSR, BH q-val, annualized turnover, max drawdown) |
| Export contains exact configuration and dataset fingerprints | Verified | `reports/demo_run/packages/*/package_manifest.json` verified via `asde.cli verify-package` (`verified: true`) |
| Clean checkout runs setup, tests and demo with permitted fixtures | Verified | `scripts/setup.sh`, `scripts/validate.sh`, `scripts/demo.sh`, `scripts/reproduce.sh` all exit 0 with Python 3.9+ stdlib |
| Architecture, dependency assumptions, known limitations and runbook committed | Verified | `docs/architecture.md`, `docs/api_and_schemas.md`, `docs/assumptions_and_limitations.md`, `docs/runbook.md`, `docs/adr/0001..0003` |
| Relevant CI checks pass and raw evaluation or test evidence retained | Verified | `reports/scenario_evidence.json`, `reports/demo_report.json`, `reports/demo_leaderboard.md`, `reports/demo_run/health_metrics.json` |
| Security, data licensing, IP and deployment approval requirements reviewed | Verified | Documented in `docs/assumptions_and_limitations.md` and `docs/adr/0001-foundation-contracts.md`; enforced by `ReviewGate` (`order_execution_enabled: false`, `live_execution_permitted: false`) |
