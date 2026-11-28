# Acceptance & Validation Evidence Report

**Project:** `earnings-call-intelligence-agent`  
**Package Version:** `0.1.0`  
**Config Digest:** `e135797a6fcbb584d081df61c936ad8d4f4517b95baa73aae8715056f965926c`  
**Verified Environment:** Python `3.9.6` on `macOS-26.5.1-arm64-arm-64bit`  
**Data Provenance:** 100% synthetic educational fixtures (`data/fixtures/`); **measured results below reflect synthetic gold fixtures, not live market or production transcripts.**

---

## 1. Project-Specific Acceptance Criteria (`plan.md` Section 5)

| # | Acceptance Criterion | Status | Measured Evidence & Artifact Link |
|---|---|---|---|
| 1 | Every numerical claim has evidence and normalized units | **PASS** | `20 / 20` extracted claims (`citation_validity_rate = 1.0000`) verified verbatim against `segment.text[char_start:char_end]` and normalized to `CanonicalUnit` (`USD_MILLIONS`, `USD_PER_SHARE`, `PERCENT`, `BPS`). Verified in [`eval_results.json`](eval_results.json) and `tests/test_extraction_and_domain.py`. |
| 2 | Report extraction F1 and citation validity | **PASS** | Measured on synthetic gold suite (`earnings_call_gold_eval_v1`, 4 cases, 20 gold claims): **Precision = `1.0000`**, **Recall = `1.0000`**, **F1 = `1.0000`** (target `>= 0.85`), **Citation Validity = `1.0000`** (`20/20`, target `1.00`). Raw results in [`eval_results.json`](eval_results.json). |
| 3 | Abstain without support | **PASS** | **`1.0000` QA & abstention accuracy (`9/9` questions)** across answerable questions, unanswerable questions (`NO_SUPPORTING_EVIDENCE`), stale sources (`STALE_SOURCE`), contradictory guidance (`AMBIGUOUS_OR_CONTRADICTORY`), and injection-only queries (`PROMPT_INJECTION_QUARANTINED`). Verified in [`eval_results.json`](eval_results.json) and `tests/test_evaluation_and_boundaries.py`. |
| 4 | All required test scenarios pass in the supported environment, or unavailable dependencies marked not run | **PASS** | All `13/13` automated tests in `tests/` pass (`0.024s`) via `bash scripts/run_ci.sh`. Optional live third-party LLM API calls and optional vector search are explicitly marked **Not Run (offline prototype)** in Section 3 below. |
| 5 | README documents setup, demo, validation, assumptions, and known limitations; measured results distinguish synthetic fixtures from estimates/targets | **PASS** | Documented in [`README.md`](../README.md) and [`docs/runbook.md`](../docs/runbook.md). |
| 6 | No real transactions, customer data, credentials, or proprietary employer/SAAT artifacts | **PASS** | `allow_trade_actions` is enforced `false` by `AgentConfig` (`test_config_safety_policy_invariants`); `trade_action_permitted: false` across all reports and adapters; all fixtures are synthetic fictional companies (`data/fixtures/README.md`). |

---

## 2. Test & Validation Matrix Mapping (`plan.md` Section 4)

| Test Area | Required Scenario | Test / Benchmark Evidence | Observed Result |
|---|---|---|---|
| **Domain correctness** | Contradictory guidance, units and fiscal periods | `tests/test_extraction_and_domain.py::test_contradictory_guidance_mixed_units_and_fiscal_periods`, `gold_02_contradictory_boreal` | **PASS** — CEO `$2.10B–$2.20B` vs CFO `$1,950M–$2,020M` normalized to `USD_MILLIONS`, flagged `CONTRADICTORY` (`INTRA_CALL_CONTRADICTION`, `SPEAKER_DISAGREEMENT`, `PREPARED_VS_QA_DIVERGENCE`); GAAP (`NARROWED`) separated from non-GAAP (`REAFFIRMED`); `CY2026` (`PERCENT`) distinct from `Q1_FY2026` (`BPS`). |
| **Integration and resilience** | Prompt injection inside transcript | `tests/test_guidance_and_security.py::test_prompt_injection_quarantined_and_legitimate_claims_preserved`, [`integration_prompt_injection.json`](integration_prompt_injection.json) | **PASS** — `8` injection pattern events detected and quarantined across `seg_m01` and `seg_m02`; `$9.90B` and `$999M` fake values blocked (`0` leaked claims); `4` legitimate claims preserved with verbatim source offsets; injection-targeted questions abstained with `PROMPT_INJECTION_QUARANTINED`. |
| **Boundary and failure behavior** | Unanswerable questions and stale source | `tests/test_evaluation_and_boundaries.py::test_stale_source_and_unanswerable_boundary`, `gold_04_stale_northstar` | **PASS** — 654.62-day-old transcript flagged `is_stale=true` with `STALE_SOURCE` warning and abstention; fresh unanswerable M&A and customer churn questions abstain with `NO_SUPPORTING_EVIDENCE`. |
| **Reproducibility** | Same versioned inputs/configuration and fixed seed | `tests/test_guidance_and_security.py::test_deterministic_replay_and_structured_logs`, [`demo_output.json`](demo_output.json) | **PASS** — Deterministic `run_id = run_665c5464612b`, replay logical digest `540dc913daea5330af29bb5b0ee8d5a2caf1deb3adf4e9449652a50a36016464` matched (`reproducible_match: true`). |
| **Operational review** | Missing configuration, unsupported inputs, restart/rerun | `tests/test_contracts_and_ingestion.py`, `tests/test_evaluation_and_boundaries.py::test_cli_operational_checks_and_no_silent_failure` | **PASS** — Missing config exits with code `1` and structured JSON `MISSING_CONFIG_FILE` on stderr; 6 invalid/unsupported inputs raise explicit error codes; CLI replay exits `0` on verified digest match. |

---

## 3. Explicitly Untested / Out-of-Scope Capabilities

| Capability | Status | Reason |
|---|---|---|
| Live external LLM API provider (OpenAI / Gemini / Anthropic) | **Not Run** | Offline research prototype without production API keys; hybrid integration and verification/budget gates are tested deterministically via `MockLLMExtractor` in `tests/test_guidance_and_security.py`. |
| Optional vector search backend | **Not Run** | Not required for single-call segmented transcript verification; optional extension point left decoupled from deterministic core. |
| Real public SEC/earnings transcripts & multi-currency/non-English calls | **Not Run / Out of Scope (v1.0.0)** | Current validation uses synthetic English/USD fixtures only; unsupported currencies/languages fail explicitly with `UNSUPPORTED_CURRENCY` / `UNSUPPORTED_LANGUAGE`. |
| Live trading / order routing | **Permanently Disabled** | Explicitly out of scope; `allow_trade_actions=true` raises `ConfigurationError("POLICY_VIOLATION")`. |

---

## 4. Raw Machine-Readable Artifacts in `reports/`

- [`baseline_reference.json`](baseline_reference.json) — Reference baseline `AnalysisReport` for `reference_valid.json` (`run_665c5464612b`).
- [`integration_prompt_injection.json`](integration_prompt_injection.json) — Integration scenario report for `prompt_injection.json` (`run_e1bf17489423`).
- [`demo_output.json`](demo_output.json) — Consolidated demo + replay digest verification + research-note envelope.
- [`eval_results.json`](eval_results.json) — Gold fixture benchmark metrics, per-case scores, target checks, and runtime metadata.
