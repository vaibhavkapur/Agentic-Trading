# Acceptance Evidence — Financial Agent Evaluation Framework

**Recorded:** `2026-11-28`  
**Environment:** CPython `3.12.15`, macOS (`arm64`), `pydantic==2.14.4`, `pytest==8.4.2`  
**Data Provenance:** 100% synthetic offline fixtures (fictional issuers `ACME`, `ORBN`, `VLTQ`, synthetic macro series); zero live capital, zero customer records, zero credentials, zero proprietary employer/SAAT artifacts.

> **Distinction of Evidence:** All figures below are **actual observed measurements** from running the offline test suite and synthetic fixture benchmarks on this machine. Simulated token costs and mock tool latencies are **synthetic model-config estimates**, not live LLM API billing measurements.

## 1. Project-Specific Acceptance Criteria Mapping

| # | Acceptance Criterion | Status | Verified Evidence & Artifact |
|---|---|---|---|
| 1 | Publish task-level scores, failure types and confidence intervals | **PASS** | Machine-readable JSON & Markdown reports in [reports/baseline/eval-fin_gold_dev-mock_deterministic_v1-6c3a8c9ad1f2.report.md](baseline/eval-fin_gold_dev-mock_deterministic_v1-6c3a8c9ad1f2.report.md) and 5-seed stochastic run [reports/runs/eval-fin_gold_dev-mock_stochastic_v1-2fbe67029321.report.md](runs/eval-fin_gold_dev-mock_stochastic_v1-2fbe67029321.report.md) (`pass_rate = 75.00%`, 95% Wilson CI `[59.81%, 85.81%]`, `mean_score = 0.9269`, 95% t-interval `[0.8841, 0.9696]`, failures: `WRONG_ARITHMETIC=6`, `UNSUPPORTED_CLAIM=5`). |
| 2 | All fixtures reproducible | **PASS** | `test_repeat_runs_for_stochastic_variance_and_reproducible_cis` confirms identical `report_id`, pass rate, mean score, and failure counts across repeated seeded runs; `fin-eval replay` and `scripts/run_demo.py` confirm `replay_verified: true` against `*.replay.json`. |
| 3 | No fabricated tool execution | **PASS** | `MockToolRuntime` signs HMAC-SHA256 `ToolExecutionReceipt`s for every call. `test_fabricated_tool_execution_detected_via_receipt_verification` verifies missing receipts, forged signatures, and tampered outputs fail with `FABRICATED_TOOL_EXECUTION` (`receipt_verified=False`, `overall_score=0.0`). All benchmark runs achieved `receipt_verification_rate = 100.0%`. |
| 4 | All required test scenarios pass (or unavailable dependencies marked not run) | **PASS** | `PYTHONPATH=src .venv/bin/pytest -v`: **22 passed, 0 failed in 0.09s**. Live external LLM HTTP provider transport is **explicitly marked NOT RUN / out of scope** (disabled by default via `external_network_allowed=false` and verified by `test_optional_llm_provider_disabled_by_default`). |
| 5 | README documents setup, demo, validation, assumptions, and limitations | **PASS** | [README.md](../README.md) documents quickstart, CLI/demo commands, validation, dependency licenses, fixture provenance, observed vs. synthetic metrics, and explicit limitations. |
| 6 | No real transactions, customer data, credentials or proprietary artifacts | **PASS** | Enforced structurally via `live_execution_enabled: Literal[False] = False` (`test_live_execution_enabled_is_strictly_rejected`), policy-blocked mutating/PII tools (`execute_live_order`, `wire_transfer`, `export_customer_records`, `modify_production_db`), and synthetic fixture store (`mock_store_v1.json`). |

## 2. Test and Validation Matrix Results

| Test Area | Required Scenario | Test Case(s) | Observed Result |
|---|---|---|---|
| **Domain correctness** | Wrong arithmetic, fabricated citation, unsafe tool request | `test_reference_compliant_agent_passes_hand_calculated_oracle`, `test_numeric_unit_conversion_and_mismatch`, `test_wrong_arithmetic_detected_deterministically`, `test_fabricated_citation_unknown_id_and_ungrounded_span`, `test_unsafe_tool_request_blocked_and_zero_scored`, `test_fabricated_tool_execution_detected_via_receipt_verification`, `test_human_rubric_agreement_and_llm_judge_cannot_override_hard_fail` | **7/7 PASSED** |
| **Integration and resilience** | Unavailable tool, stale evidence, prompt injection | `test_resilience_suite_unavailable_tool_stale_evidence_and_prompt_injection`, `test_stale_evidence_reckless_agent_is_caught`, `test_prompt_injection_compromised_agent_is_caught`, `test_tool_timeout_and_budget_enforcement` | **4/4 PASSED** |
| **Boundary and failure behavior** | Repeat runs for stochastic variance, exact tolerance boundaries | `test_numeric_exact_tolerance_boundaries_and_non_finite`, `test_repeat_runs_for_stochastic_variance_and_reproducible_cis` | **2/2 PASSED** |
| **Reproducibility** | Same versioned inputs/config and fixed seed, replay, baseline diff | `test_repeat_runs_for_stochastic_variance_and_reproducible_cis`, `test_baseline_comparison_detects_regression`, `scripts/run_demo.py` (`replay_verified=true`) | **PASSED (100% match)** |
| **Operational review** | Missing config, invalid fixtures, held-out leakage, CLI exit codes | `test_canonical_fixtures_and_configs_validate_cleanly`, `test_invalid_fixtures_fail_with_contract_validation_error`, `test_live_execution_enabled_is_strictly_rejected`, `test_held_out_dataset_leakage_guard`, `test_missing_and_corrupt_configuration_errors`, `test_optional_llm_provider_disabled_by_default`, `test_cli_validate_run_replay_compare_and_error_handling` | **7/7 PASSED** |

## 3. Observed Benchmark Summary (Synthetic Fixtures)

| Run | Report ID | Split | Evals | Pass Rate (95% CI) | Mean Score (95% CI) | Receipt Verified | Synthetic Cost (USD) | Mean / P95 Latency (ms) | Faults Injected |
|---|---|---|---:|---|---|---:|---:|---:|---:|
| Deterministic Baseline | `eval-fin_gold_dev-mock_deterministic_v1-6c3a8c9ad1f2` | `dev` | 8 | `100.00%` `[67.56%, 100.00%]` | `1.0000` `[1.0000, 1.0000]` | `100.00%` | `\$0.005968` | `112.38` / `141.00` | 0 |
| Resilience Failure Injection | `eval-fin_gold_dev-mock_deterministic_v1-41e274963cb4` | `dev` | 8 | `100.00%` `[67.56%, 100.00%]` | `1.0000` `[1.0000, 1.0000]` | `100.00%` | `\$0.005753` | `115.00` / `141.00` | 7 |
| Stochastic 5-Seed Benchmark | `eval-fin_gold_dev-mock_stochastic_v1-2fbe67029321` | `dev` | 40 | `75.00%` `[59.81%, 85.81%]` | `0.9269` `[0.8841, 0.9696]` | `100.00%` | `\$0.042347` | `124.46` / `163.40` | 0 |
| Held-Out Final Check | `eval-fin_gold_held_out-mock_deterministic_v1-2f419b7d864f` | `held_out` | 3 | `100.00%` `[43.85%, 100.00%]` | `1.0000` `[1.0000, 1.0000]` | `100.00%` | `\$0.002229` | `110.67` / `123.00` | 0 |

## 4. Explicitly Untested / Out-of-Scope Capabilities

- **Live External LLM API Transport:** Intentionally disabled (`external_network_allowed=false`) in the offline sandbox; `OptionalLLMProviderAdapter` verifies the opt-in and env-var boundary only.
- **Live Brokerage / Market Data Feeds & Production Credentials:** Excluded by design (`live_execution_enabled: Literal[False] = False`).
- **Live Multi-Human Calibration Study:** Human rubric schema, normalization, inter-rater Cohen's kappa, and deterministic hard-fail guardrail are unit-tested on synthetic scorecards; live analyst annotation batches were not run.
