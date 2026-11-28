# Acceptance Evidence Report — Macro Intelligence Agent

**Generated from measured local runs on:** Python `3.9.6` (`stdlib` core)  
**Config SHA-256:** `8dbee4d83ad246666380ef53b9faf2b2d2c1b6d8ecdfb82588dcc000735fbc97` (`config/default_config.json`, `seed=42`, `numeric_tolerance=0.0001`)  
**Data Origin:** Synthetic curated fixtures (`data/fixtures/*.json`) — explicitly distinguished from live market/wire feeds.

## 1. Acceptance Criteria Mapping

| # | Acceptance Criterion (`plan.md` §5) | Status | Measured Evidence | Raw Artifact / Test |
|---|---|---|---|---|
| 1 | No future release visible at historical cutoff | **PASS** | `embargo_leakage_count = 0` across all 5 gold-set cases; T1 gates out 3 future/embargoed releases (`US_CPI_2025_03:v2_revised`, `FOMC_STMT_2025_05`, `US_CPI_2025_05_EMBARGOED`); T2 gates out 1 embargoed release (`US_CPI_2025_05_EMBARGOED`); direct lookup raises `EmbargoViolationError`. | `reports/evaluation_results.json`, `reports/baseline_reference_t1.json`, `tests/test_domain_and_embargo.py` |
| 2 | All figures traceable | **PASS** | `citation_traceability_rate = 1.0` (`100%`), `verification_passed = true` on every run; every figure, surprise, revision endpoint, policy cue, and conflict maps to an exact `[char_start:char_end]` slice and SHA-256 hash of its archived release; tampered quote test raises `CitationVerificationError`. | `reports/evaluation_results.json`, `reports/demo_brief_t2.json`, `tests/test_domain_and_embargo.py` |
| 3 | Report exact-match and abstention metrics | **PASS** | Gold set (`5/5` cases): Figure exact-match `1.0` (`8/8`), Surprise exact-match `1.0` (`7/7`), Revision exact-match `1.0` (`2/2`), Abstention Precision `1.0`, Recall `1.0`, F1 `1.0` (`tp=3, fp=0, fn=0`), False fabrications `0`. | `reports/evaluation_results.json`, `scripts/run_acceptance.py` |
| 4 | All required test scenarios pass in supported environment | **PASS** | `15/15` automated tests pass (`0` failures, `0` errors, `0` skipped) covering embargoed release, revised data, unit mismatch, conflicting reports, untrusted source instructions, reproducibility/SQLite replay, and operational error handling; `bash scripts/ci_check.sh` exits `0`. | `tests/test_*.py`, `scripts/ci_check.sh` |
| 5 | README documents setup, demo, validation, assumptions, limitations, and synthetic vs target distinction | **PASS** | `README.md`, `docs/architecture.md`, `docs/contracts.md`, `docs/integration.md`, `docs/runbook.md`, and `docs/adr/0001-deterministic-core-and-publication-gates.md` completed and cross-linked. | `README.md`, `docs/` |
| 6 | No real transactions, customer data, credentials, or employer/SAAT artifacts | **PASS** | Clean-room original code; synthetic fixtures only; `allow_live_network=true` explicitly blocked by `ConfigurationError`. | `src/`, `data/fixtures/`, `docs/integration.md` |

## 2. Test & Validation Matrix Coverage (`plan.md` §4)

| Test Area | Required Scenario | Test Evidence | Outcome |
|---|---|---|---|
| Domain correctness | Embargoed release and revised data | `test_embargoed_release_invisible_and_checked_access_blocked`, `test_revised_data_and_fomc_policy_match_oracle_t2` (compared against hand-calculated `reference_expected_oracle.json` within `0.0001` tolerance) | **PASS** |
| Integration & resilience | Unit mismatch and conflicting reports | `test_integration_unit_mismatch_and_conflicting_reports_fixture`, `test_unit_conversion_rules`, `test_agreeing_multi_source_reports_reconcile_without_conflict` (`reports/integration_edge_cases.json`) | **PASS** |
| Boundary & failure behavior | Untrusted source instructions | `test_untrusted_source_instructions_quarantined`, `test_untrusted_source_instructions_reject_mode_raises`, `test_metric_claiming_quarantined_span_rejected_by_grounding` (`reports/security_boundary_output.json`) | **PASS** |
| Reproducibility | Same versioned inputs/config and fixed seed | `test_reproducibility_and_sqlite_replay_across_restart` + CLI `replay` subcommand | **PASS** |
| Operational review | Missing config, unsupported inputs, budget exhaustion, restart/rerun | `test_schema_rejects_naive_timestamps_and_invalid_inputs`, `test_operational_error_handling_config_and_budget`, `test_cli_brief_evaluate_replay_and_error_exit` | **PASS** |

## 3. Gold-Set Case Breakdown (Observed on Synthetic Fixtures)

| Case ID | Run ID | Brief ID | Figures | Surprises | Revisions | Abstentions (Actual / Expected) | Embargo Leaks | Security Findings | Passed |
|---|---|---|---|---|---|---|---|---|---|
| `GOLD_01_INITIAL_CPI_AND_EMBARGO` | `run_3daac58bda853930` | `brf_bb38d8d0431866ad` | 2/2 | 2/2 | 0/0 | 0 / 0 | 0 | 0 | Yes |
| `GOLD_02_REVISED_CPI_AND_FOMC_POLICY` | `run_65450206e371e4c4` | `brf_8437bd62dbb64285` | 3/3 | 3/3 | 2/2 | 0 / 0 | 0 | 0 | Yes |
| `GOLD_03_PRE_RELEASE_ZERO_VISIBILITY` | `run_d489a7a3591904de` | `brf_cf1dc53c0102d863` | 0/0 | 0/0 | 0/0 | 1 / 1 | 0 | 0 | Yes |
| `GOLD_04_UNIT_MISMATCH_AND_CONFLICT_ABSTENTION` | `run_a4a9b1d64fcead74` | `brf_ba7f7646437091e3` | 2/2 | 1/1 | 0/0 | 2 / 2 | 0 | 0 | Yes |
| `GOLD_05_UNTRUSTED_SOURCE_INSTRUCTION_RESILIENCE` | `run_c188e065d89d907c` | `brf_b04f02c135dd0b04` | 1/1 | 1/1 | 0/0 | 0 / 0 | 0 | 1 | Yes |

## 4. Explicitly Untested / Out-of-Scope Capabilities

The following capabilities were **NOT RUN** in this offline research prototype and remain explicitly out of scope:

- **Live external LLM API providers** (e.g., hosted OpenAI/Gemini/Anthropic endpoints): disabled by configuration (`allow_live_network=false`); only `deterministic_mock` and `none` adapters were executed.
- **Optional third-party tooling in this local environment:** `pydantic`, `pytest`, `ruff`, and `mypy` were not installed in the offline Python 3.9.6 environment; core runtime and tests ran via Python stdlib (`dataclasses`, `sqlite3`, `unittest`).
- **Live macroeconomic wire/calendar feeds and production order execution:** excluded by project scope; requires separate vendor licensing, security, operational, legal, and risk reviews before any production use.
