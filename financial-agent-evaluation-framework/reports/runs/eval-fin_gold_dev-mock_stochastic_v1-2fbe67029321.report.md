# Evaluation Report: `eval-fin_gold_dev-mock_stochastic_v1-2fbe67029321`

## Metadata
- **Dataset:** `fin_gold_dev` v1.0.0 (`dev`)
- **Fixture Version:** `1.0.0`
- **Model Config:** `mock_stochastic_v1` v1.0.0 (`stochastic-sim-v1`)
- **Failure Injection Profile:** `faults_none`
- **Seeds:** `[100, 101, 102, 103, 104]`
- **Created (UTC):** `2026-11-28T04:32:28.173013+00:00`
- **Environment:** Python 3.12.15 (macOS-26.5.1-arm64-arm-64bit)

## Summary Metrics
| Metric | Value | 95% Confidence Interval |
|---|---|---|
| Pass Rate (wilson) | 75.00% | [59.81%, 85.81%] (n=40) |
| Mean Score (t_interval) | 0.9269 | [0.8841, 0.9696] (sd=0.1379) |
| Numeric Accuracy | 0.8500 | — |
| Citation Faithfulness | 0.8875 | — |
| Tool Reliability | 1.0000 | — |
| Abstention & Safety | 1.0000 | — |
| Receipt Verification Rate | 100.00% | — |
| Total Cost (USD) | \$0.042347 | mean \$0.001059/eval |
| Latency (ms) | mean 125.66 ms | p95 163.40 ms |
| Total Tokens | 15904 | — |

## Failure Types
| Failure Type | Count |
|---|---|
| `UNSUPPORTED_CLAIM` | 5 |
| `WRONG_ARITHMETIC` | 6 |

## Baseline Comparison
- **Baseline Report:** `eval-fin_gold_dev-mock_deterministic_v1-6c3a8c9ad1f2`
- **Pass Rate Delta:** `-0.2500`
- **Mean Score Delta:** `-0.0731`
- **Within Tolerance (0.250):** `True`
- **Notes:** Within baseline tolerance.

## Task-Level Results
| Task ID | Seed | Category | Passed | Score | Failures | Faults | Cost (USD) | Latency (ms) |
|---|---:|---|---:|---:|---|---|---:|---:|
| `FIN_ARITH_001` | 100 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001233 | 151.00 |
| `FIN_ARITH_002` | 100 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001419 | 148.27 |
| `FIN_TOOL_001` | 100 | `tool_workflow` | PASS | 1.0000 | — | — | \$0.001140 | 139.50 |
| `FIN_ARITH_003` | 100 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001168 | 115.22 |
| `FIN_MACRO_001` | 100 | `tool_workflow` | FAIL | 0.7000 | WRONG_ARITHMETIC | — | \$0.000949 | 127.32 |
| `FIN_FILING_001` | 100 | `filing_qa` | PASS | 1.0000 | — | — | \$0.001107 | 150.14 |
| `FIN_ABSTAIN_001` | 100 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000625 | 83.51 |
| `FIN_ABSTAIN_002` | 100 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000691 | 93.88 |
| `FIN_ARITH_001` | 101 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001251 | 163.35 |
| `FIN_ARITH_002` | 101 | `financial_arithmetic` | FAIL | 0.7500 | UNSUPPORTED_CLAIM | — | \$0.001437 | 131.41 |
| `FIN_TOOL_001` | 101 | `tool_workflow` | FAIL | 0.8750 | UNSUPPORTED_CLAIM | — | \$0.001113 | 141.58 |
| `FIN_ARITH_003` | 101 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001147 | 132.94 |
| `FIN_MACRO_001` | 101 | `tool_workflow` | PASS | 1.0000 | — | — | \$0.001056 | 101.54 |
| `FIN_FILING_001` | 101 | `filing_qa` | PASS | 1.0000 | — | — | \$0.001158 | 154.04 |
| `FIN_ABSTAIN_001` | 101 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000688 | 92.27 |
| `FIN_ABSTAIN_002` | 101 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000727 | 84.38 |
| `FIN_ARITH_001` | 102 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001157 | 164.73 |
| `FIN_ARITH_002` | 102 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001395 | 145.88 |
| `FIN_TOOL_001` | 102 | `tool_workflow` | FAIL | 0.7000 | WRONG_ARITHMETIC | — | \$0.001107 | 146.53 |
| `FIN_ARITH_003` | 102 | `financial_arithmetic` | FAIL | 0.7500 | UNSUPPORTED_CLAIM | — | \$0.001162 | 161.53 |
| `FIN_MACRO_001` | 102 | `tool_workflow` | FAIL | 0.7500 | UNSUPPORTED_CLAIM | — | \$0.001081 | 131.07 |
| `FIN_FILING_001` | 102 | `filing_qa` | PASS | 1.0000 | — | — | \$0.001146 | 113.09 |
| `FIN_ABSTAIN_001` | 102 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000706 | 72.67 |
| `FIN_ABSTAIN_002` | 102 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000715 | 89.93 |
| `FIN_ARITH_001` | 103 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001277 | 147.86 |
| `FIN_ARITH_002` | 103 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001440 | 164.40 |
| `FIN_TOOL_001` | 103 | `tool_workflow` | FAIL | 0.7000 | WRONG_ARITHMETIC | — | \$0.001152 | 145.70 |
| `FIN_ARITH_003` | 103 | `financial_arithmetic` | FAIL | 0.7000 | WRONG_ARITHMETIC | — | \$0.001132 | 110.92 |
| `FIN_MACRO_001` | 103 | `tool_workflow` | FAIL | 0.7000 | WRONG_ARITHMETIC | — | \$0.001063 | 112.20 |
| `FIN_FILING_001` | 103 | `filing_qa` | PASS | 1.0000 | — | — | \$0.001155 | 97.60 |
| `FIN_ABSTAIN_001` | 103 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000611 | 84.83 |
| `FIN_ABSTAIN_002` | 103 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000727 | 126.52 |
| `FIN_ARITH_001` | 104 | `financial_arithmetic` | FAIL | 0.4500 | WRONG_ARITHMETIC, UNSUPPORTED_CLAIM | — | \$0.001215 | 138.43 |
| `FIN_ARITH_002` | 104 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001359 | 145.93 |
| `FIN_TOOL_001` | 104 | `tool_workflow` | PASS | 1.0000 | — | — | \$0.001158 | 158.53 |
| `FIN_ARITH_003` | 104 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001192 | 153.86 |
| `FIN_MACRO_001` | 104 | `tool_workflow` | PASS | 1.0000 | — | — | \$0.001056 | 102.62 |
| `FIN_FILING_001` | 104 | `filing_qa` | PASS | 1.0000 | — | — | \$0.001095 | 132.17 |
| `FIN_ABSTAIN_001` | 104 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000706 | 83.90 |
| `FIN_ABSTAIN_002` | 104 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000629 | 85.01 |
