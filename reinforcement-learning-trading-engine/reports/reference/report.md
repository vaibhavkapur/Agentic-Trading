# Synthetic allocation policy report

5 expanding folds, each with 40 held-out daily returns. Each policy started every window in cash with USD 10,000.

Mean net return and worst peak-to-trough drawdown are per test window. Intervals resample whole test folds with replacement. Excess return is paired by fold against buy-and-hold. Few folds and serial dependence limit precision.

| Scenario | Policy | Mean return (95% interval) | Excess vs hold (95% interval) | Worst drawdown |
|---|---|---:|---:|---:|
| base | q_learning | -1.43% (-3.71%, 0.78%) | 2.38% (-5.15%, 9.91%) | 6.02% |
| base | cash | 0.00% (0.00%, 0.00%) | 3.81% (-5.08%, 12.70%) | 0.00% |
| base | buy_hold | -3.81% (-12.70%, 5.08%) | 0.00% (0.00%, 0.00%) | 17.83% |
| base | random | -3.02% (-7.45%, 1.17%) | 0.79% (-4.07%, 5.48%) | 10.94% |
| double_cost | q_learning | -2.06% (-4.56%, 0.21%) | 1.82% (-5.65%, 9.29%) | 6.94% |
| double_cost | cash | 0.00% (0.00%, 0.00%) | 3.87% (-5.01%, 12.76%) | 0.00% |
| double_cost | buy_hold | -3.87% (-12.76%, 5.01%) | 0.00% (0.00%, 0.00%) | 17.83% |
| double_cost | random | -4.34% (-8.78%, -0.19%) | -0.47% (-5.44%, 4.27%) | 12.18% |
| selloff_thin_auction | q_learning | -2.19% (-3.73%, -0.66%) | 12.51% (4.61%, 20.51%) | 4.78% |
| selloff_thin_auction | cash | 0.00% (0.00%, 0.00%) | 14.71% (6.83%, 22.58%) | 0.00% |
| selloff_thin_auction | buy_hold | -14.71% (-22.58%, -6.83%) | 0.00% (0.00%, 0.00%) | 26.91% |
| selloff_thin_auction | random | -8.68% (-12.86%, -4.50%) | 6.03% (2.12%, 9.93%) | 16.17% |

The final export is the last fold’s validation-selected policy. All candidate scores, including losing runs, are in `runs.jsonl`. The fixture and stress paths are synthetic. Results describe these simulations only.
