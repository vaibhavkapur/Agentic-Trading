# Acceptance Evidence Report — AI Investment Committee

- **Environment Observed:** Python `3.9.6` on `macOS-26.5.1-arm64-arm-64bit`, SQLite `3.51.0`
- **Configuration:** `config/committee_default.json` (`config_id: committee-default-v1`, `seed: 42`, `adapter_mode: deterministic_mock`, `allow_live_execution: false`)
- **Raw Machine-Readable Artifacts:**
  - [`reports/test_results.json`](test_results.json)
  - [`reports/baseline_comparison.json`](baseline_comparison.json)
  - [`reports/demo_run_summary.json`](demo_run_summary.json)

> **Observation vs. Synthetic Distinction:** All test pass counts, execution timings (`41.27 ms`), hash values, and baseline diffs (`0.0`) are **actual observed measurements** from running the code locally. All underlying financial portfolios, tickers, research briefs, and mock LLM token/cost numbers are **synthetic fixtures** designed to exercise governance invariants.

## 1. Project-Specific Acceptance Criteria (`plan.md` Section 5)

| Acceptance Criterion | Status | Evidence |
|---|---|---|
| No veto bypass or execution capability | **PASS (Observed)** | `test_role_tool_isolation_and_no_execution_capability`, `test_all_invalid_input_fixture_cases_raise_expected_errors`, `test_prompt_injection_quarantined_and_risk_veto_enforced`; demo confirms `execution_capability: NONE_PAPER_ONLY` and `veto_bypass_blocked: true` (`RISK_VETO_BYPASS_FORBIDDEN`). |
| All claims cited or marked uncertain | **PASS (Observed)** | `Claim.__post_init__` rejects uncited non-uncertain claims (`test_claim_without_citation_or_uncertainty_flag_rejected`); `audit_claims` catches fabricated citations (`test_fabricated_evidence_detected_marked_uncertain_and_vetoed`); all 4 demo deliberation scenarios report `all_claims_cited_or_uncertain: true` and `unsupported_claims: 0`. |
| Replay trace captures decision and budget | **PASS (Observed)** | `test_sqlite_replay_captures_decision_and_budget`, `test_cli_end_to_end_run_approve_replay_evaluate_and_duplicate_error`; `reports/demo_run_summary.json` records `replay_exact_match: true`, `total_tool_calls: 13`, `total_tokens: 2020`, `total_latency_ms: 379`, `total_cost_usd: 0.0201`. |
| All required test scenarios pass (or unavailable dependencies marked not run) | **PASS (Observed)** | `18 / 18` tests pass (`reports/test_results.json`: `failures: 0`, `errors: 0`, `skipped: 0`). Untested optional capabilities are listed explicitly in Section 3 below. |
| README documents setup, demo, validation, assumptions, and limitations | **PASS (Verified)** | See [`README.md`](../README.md) and [`docs/runbook.md`](../docs/runbook.md). |
| No real transactions, customer data, credentials, or employer/SAAT artifacts | **PASS (Verified)** | Pure synthetic tickers/briefs, zero external network calls, zero secrets, zero brokerage integrations. |

## 2. Test & Validation Matrix Coverage (`plan.md` Section 4)

| Test Area | Required Scenario | Automated Test / Artifact Evidence | Result |
|---|---|---|---|
| Domain correctness | Agent disagreement and fabricated evidence | `tests/test_domain_agents_and_evidence.py` (`test_agent_disagreement_records_high_dissent`, `test_fabricated_evidence_detected_marked_uncertain_and_vetoed`, `test_reference_proposal_matches_independent_oracle`) + `reports/baseline_comparison.json` (`12/12` metrics within tolerance, `0.0` diff) | **PASS** |
| Integration & resilience | Prompt injection and risk veto attempt | `tests/test_integration_security_and_veto.py` (`test_prompt_injection_quarantined_and_risk_veto_enforced`, `test_human_approval_bound_to_canonical_proposal_hash`) + `reports/demo_run_summary.json` (`7` injection directives quarantined, `6` risk rules vetoed, bypass blocked) | **PASS** |
| Boundary & failure behavior | Timeout and duplicate approval | `tests/test_boundary_failures_and_ops.py` (`test_agent_timeout_fails_explicitly_with_diagnostics`, `test_duplicate_approval_rejected_same_id_and_second_id_after_restart`) + `tests/test_contracts_and_fixtures.py` (`test_boundary_exact_policy_limits_pass`) | **PASS** |
| Reproducibility | Same versioned inputs/configuration and fixed seed | `tests/test_replay_and_reproducibility.py` (`test_same_inputs_config_and_seed_produce_matching_logical_outputs`, `test_sqlite_replay_captures_decision_and_budget`) | **PASS** |
| Operational review | Missing config, unsupported inputs, restart/rerun | `tests/test_boundary_failures_and_ops.py` (`test_missing_or_corrupt_configuration_raises_explicit_error`, `test_unsupported_adapter_mode_and_schema_version_rejected`, restart check) + `docs/runbook.md` | **PASS** |

## 3. Explicitly Untested / Out-of-Scope Capabilities

- **Live LLM provider adapters (OpenAI/Anthropic/Gemini API calls):** **NOT RUN** — intentionally excluded in offline prototype mode (`adapter_mode: deterministic_mock`); only the `LLMAdapter` protocol interface and deterministic/fault-injection mock adapters were executed.
- **Optional `pydantic`, `pytest`, `ruff`, `mypy` extras:** **NOT RUN** in this offline environment (no third-party wheels installed; tests executed via Python `3.9.6` stdlib `unittest` and structured to be `pytest`-compatible in CI).
- **Live order execution / brokerage routing / real market data:** **PERMANENTLY OUT OF SCOPE** and structurally blocked (`NoExecutionCapabilityError`).
