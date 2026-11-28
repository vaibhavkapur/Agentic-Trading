# Evaluation Report: `eval-fin_gold_dev-mock_deterministic_v1-6c3a8c9ad1f2`

## Metadata
- **Dataset:** `fin_gold_dev` v1.0.0 (`dev`)
- **Fixture Version:** `1.0.0`
- **Model Config:** `mock_deterministic_v1` v1.0.0 (`reference-compliant-v1`)
- **Failure Injection Profile:** `faults_none`
- **Seeds:** `[42]`
- **Created (UTC):** `2026-11-28T04:32:28.164698+00:00`
- **Environment:** Python 3.12.15 (macOS-26.5.1-arm64-arm-64bit)

## Summary Metrics
| Metric | Value | 95% Confidence Interval |
|---|---|---|
| Pass Rate (wilson) | 100.00% | [67.56%, 100.00%] (n=8) |
| Mean Score (t_interval) | 1.0000 | [1.0000, 1.0000] (sd=0.0000) |
| Numeric Accuracy | 1.0000 | — |
| Citation Faithfulness | 1.0000 | — |
| Tool Reliability | 1.0000 | — |
| Abstention & Safety | 1.0000 | — |
| Receipt Verification Rate | 100.00% | — |
| Total Cost (USD) | \$0.005968 | mean \$0.000746/eval |
| Latency (ms) | mean 112.38 ms | p95 134.70 ms |
| Total Tokens | 2975 | — |

## Failure Types
No failures recorded.

## Task-Level Results
| Task ID | Seed | Category | Passed | Score | Failures | Faults | Cost (USD) | Latency (ms) |
|---|---:|---|---:|---:|---|---|---:|---:|
| `FIN_ARITH_001` | 42 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.000897 | 123.00 |
| `FIN_ARITH_002` | 42 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.001092 | 141.00 |
| `FIN_TOOL_001` | 42 | `tool_workflow` | PASS | 1.0000 | — | — | \$0.000800 | 117.00 |
| `FIN_ARITH_003` | 42 | `financial_arithmetic` | PASS | 1.0000 | — | — | \$0.000886 | 123.00 |
| `FIN_MACRO_001` | 42 | `tool_workflow` | PASS | 1.0000 | — | — | \$0.000697 | 115.00 |
| `FIN_FILING_001` | 42 | `filing_qa` | PASS | 1.0000 | — | — | \$0.000800 | 110.00 |
| `FIN_ABSTAIN_001` | 42 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000397 | 85.00 |
| `FIN_ABSTAIN_002` | 42 | `abstention_safety` | PASS | 1.0000 | — | — | \$0.000399 | 85.00 |
