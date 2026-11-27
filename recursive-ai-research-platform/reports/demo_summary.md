# Recursive AI Research Platform — Demo Run Summary

- **Session ID:** `demo_session_v1`
- **Stop Reason:** `QUEUE_EXHAUSTED`
- **Data Manifest:** `manifest_synthetic_multi_regime_equities_v1_seed42` (`cd4dcf4bf007bf92...`)
- **Split Fingerprint:** `060ff2f0b54eec17...` (holdout blinded: `True`)
- **Registry Hash Chain Valid:** `True`
- **Best Run ID:** `run_0002_3d62823c2c`

## Budget Usage

- Iterations: `2 / 4`
- Experiments: `4 / 8`
- Cost (USD): `$0.3200 / $1.0000`

## Runs Recorded in Immutable Registry

| Run ID | Hypothesis | Status | Train Sharpe | Val Sharpe | Max DD | Trades | Critic Verdict |
|---|---|---|---:|---:|---:|---:|---|
| `run_0001_e064248ddf` | `hyp_0001_mom_base` | SUCCEEDED | -1.463 | 1.201 | 2.79% | 160 | `CANDIDATE_FOR_REVIEW` |
| `run_0002_3d62823c2c` | `hyp_0002_mr_base` | SUCCEEDED | 0.510 | 2.211 | 2.42% | 25 | `CANDIDATE_FOR_REVIEW` |
| `run_0003_1bcd61f6c6` | `hyp_0003_vol_breakout_base` | SUCCEEDED | 0.918 | -0.017 | 5.50% | 10 | `REFINE` |
| `run_0004_cd24448430` | `hyp_0004_gen1` | SUCCEEDED | -0.307 | -0.767 | 3.80% | 8 | `REFINE` |

## Governance & Paper-Only Promotion Gate

- Decision `rev_83d513c86b0c` by independent reviewer `reviewer_independent_lead`: `APPROVED_PAPER_ONLY` (target: `PAPER_SANDBOX`)
- Paper Sandbox Package `paperpkg_eb1e2f6e9f72` signed (`art_eb1e2f6e9f72`), `order_execution_enabled=False`, `live_deployment_prohibited=True`.

> **Disclaimer:** Simulated backtest metrics on synthetic fixtures never imply live trading performance.
