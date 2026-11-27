# Research Leaderboard — Run `run_927735496198`

> **Governance Notice:** Simulated walk-forward results do NOT imply live trading performance. Order execution is disabled; independent review is mandatory before paper/sandbox promotion.

## Provenance & Trial Accounting

| Field | Value |
|---|---|
| Dataset Fingerprint | `95d1d5dd098eb177...` |
| Split Manifest Hash | `def5ca74c8c8e7b2...` |
| Cost Scenario | `base_institutional` (`feae3ae34a56...`) |
| Total Trials Accounted (incl. inner & failures) | 93 |
| Candidate Trials / Baseline Trials | 90 / 3 |
| Passed / Rejected / Failed Trials | 68 / 25 / 0 |
| Holdout Reads During Selection | 0 (Blocked: 0) |

## Baselines (Identical Data & Costs)

| Baseline | Sharpe (95% CI) | CAGR | Max DD | Ann. Turnover | Cost Drag |
|---|---:|---:|---:|---:|---:|
| `baseline_buy_and_hold` | 0.250 [-1.43, 1.50] | 4.00% | 15.07% | 4.16x | 0.53% |
| `baseline_cash` | 0.000 [0.00, 0.00] | 2.02% | 0.00% | 0.00x | 0.00% |
| `baseline_risk_parity_equal_weight` | 0.698 [-1.17, 2.26] | 8.46% | 10.67% | 6.46x | 0.81% |

## Candidate Strategies (All Evaluated Candidates Including Rejected)

| Strategy | Family | Status | Sharpe (95% CI) | DSR Prob | BH q-val | CAGR | Max DD | Turnover | Pos Folds | Rejection Reasons |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `trend_ma_crossover_8dbb34db6310` | `trend_ma_crossover` | **ELIGIBLE_FOR_REVIEW** | 2.110 [0.48, 3.93] | 0.621 | 0.130 | 12.06% | 5.35% | 8.53x | 75% | none |
| `volatility_breakout_aba639901fb6` | `volatility_breakout` | **ELIGIBLE_FOR_REVIEW** | 1.960 [0.57, 3.41] | 0.545 | 0.130 | 14.21% | 4.35% | 16.72x | 100% | none |
| `volatility_breakout_69f186cf5e35` | `volatility_breakout` | **REJECTED** | 1.995 [0.36, 3.53] | 0.562 | 0.130 | 19.04% | 6.95% | 28.92x | 75% | excessive_turnover:28.92>18.00 |
| `trend_ma_crossover_85c80517b452` | `trend_ma_crossover` | **REJECTED** | 1.503 [-0.08, 3.46] | 0.311 | 0.509 | 9.03% | 4.47% | 9.56x | 50% | failed_deflated_sharpe:0.311<0.50 |
| `volatility_breakout_588a8ef68df7` | `volatility_breakout` | **REJECTED** | 1.436 [0.03, 2.56] | 0.279 | 0.509 | 11.52% | 3.74% | 21.61x | 100% | excessive_turnover:21.61>18.00, failed_deflated_sharpe:0.279<0.50 |
| `trend_ma_crossover_2509f2d09e3e` | `trend_ma_crossover` | **REJECTED** | 1.295 [-0.55, 3.43] | 0.222 | 0.656 | 11.04% | 5.79% | 10.53x | 50% | failed_deflated_sharpe:0.222<0.50 |
| `dual_momentum_93c8c3891bf3` | `dual_momentum` | **REJECTED** | 0.972 [-0.98, 2.74] | 0.116 | 1.000 | 13.62% | 12.15% | 8.65x | 50% | failed_deflated_sharpe:0.116<0.50 |
| `dual_momentum_5e711a24e9bc` | `dual_momentum` | **REJECTED** | 0.947 [-1.02, 3.01] | 0.111 | 1.000 | 9.93% | 8.22% | 5.03x | 75% | failed_deflated_sharpe:0.111<0.50 |
| `dual_momentum_9b9ba7eba604` | `dual_momentum` | **REJECTED** | 0.454 [-1.28, 2.05] | 0.030 | 1.000 | 6.70% | 13.91% | 16.56x | 75% | failed_deflated_sharpe:0.030<0.50 |
| `trend_ma_crossover_32a3dae933c0` | `trend_ma_crossover` | **REJECTED** | 0.420 [-1.41, 2.04] | 0.027 | 1.000 | 5.43% | 9.30% | 9.52x | 75% | failed_deflated_sharpe:0.027<0.50 |
| `dual_momentum_fd2c50b66454` | `dual_momentum` | **REJECTED** | 0.123 [-1.31, 1.68] | 0.010 | 1.000 | 2.72% | 9.30% | 12.99x | 50% | failed_deflated_sharpe:0.010<0.50 |
| `dual_momentum_cc5c063c39bf` | `dual_momentum` | **REJECTED** | -0.061 [-2.05, 1.76] | 0.005 | 1.000 | 0.60% | 19.47% | 7.58x | 50% | non_positive_net_sharpe:-0.061, fails_stressed_2x_cost_sensitivity, failed_deflated_sharpe:0.005<0.50 |
| `trend_ma_crossover_bdf98757bdcb` | `trend_ma_crossover` | **REJECTED** | -0.153 [-2.23, 1.69] | 0.004 | 1.000 | 0.62% | 10.32% | 17.65x | 50% | non_positive_net_sharpe:-0.153, fails_stressed_2x_cost_sensitivity, failed_deflated_sharpe:0.004<0.50 |
| `mean_reversion_zscore_2ffaed50b1bc` | `mean_reversion_zscore` | **REJECTED** | -1.481 [-3.55, 0.35] | 0.000 | 1.000 | -2.66% | 6.51% | 5.15x | 25% | non_positive_net_sharpe:-1.481, fails_stressed_2x_cost_sensitivity, low_fold_consistency:0.25<0.50, failed_deflated_sharpe:0.000<0.50 |
| `mean_reversion_zscore_337dd23d9f11` | `mean_reversion_zscore` | **REJECTED** | -1.928 [-3.53, -0.31] | 0.000 | 1.000 | -6.91% | 12.51% | 15.76x | 0% | non_positive_net_sharpe:-1.928, fails_stressed_2x_cost_sensitivity, low_fold_consistency:0.00<0.50, failed_deflated_sharpe:0.000<0.50 |
| `mean_reversion_zscore_a2f9e02f7971` | `mean_reversion_zscore` | **REJECTED** | -2.037 [-3.71, -0.23] | 0.000 | 1.000 | -8.12% | 15.95% | 7.29x | 25% | non_positive_net_sharpe:-2.037, fails_stressed_2x_cost_sensitivity, low_fold_consistency:0.25<0.50, failed_deflated_sharpe:0.000<0.50 |
| `mean_reversion_zscore_4618c999efe4` | `mean_reversion_zscore` | **REJECTED** | -2.882 [-4.68, -1.22] | 0.000 | 1.000 | -8.94% | 16.12% | 15.80x | 0% | non_positive_net_sharpe:-2.882, fails_stressed_2x_cost_sensitivity, low_fold_consistency:0.00<0.50, failed_deflated_sharpe:0.000<0.50 |
| `mean_reversion_zscore_a79f028f3f50` | `mean_reversion_zscore` | **REJECTED** | -3.147 [-4.53, -1.71] | 0.000 | 1.000 | -6.95% | 12.25% | 12.91x | 0% | non_positive_net_sharpe:-3.147, fails_stressed_2x_cost_sensitivity, low_fold_consistency:0.00<0.50, failed_deflated_sharpe:0.000<0.50 |

## Failed / Invalid Candidates

_No failed/errored outer candidates in this run (all inner/outer failures remain tracked in trial ledger)._
