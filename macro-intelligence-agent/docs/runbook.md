# Operator & Developer Runbook — Macro Intelligence Agent

## 1. Environment Setup

**Supported environment:** Python 3.9+ (verified on Python 3.9.6, macOS/Linux; zero external runtime packages required).

```bash
cd macro-intelligence-agent
python3 --version
```

Optional editable install (if installing into a virtualenv):

```bash
pip install -e .
```

All commands below also work directly from a clean checkout using `PYTHONPATH=src` without `pip install`.

## 2. Demo Walkthrough

Run the reproducible end-to-end demo across all core scenarios (initial T1 release with embargoed future data hidden, post-revision T2 + FOMC policy cues, unit mismatch + conflicting reports, and prompt-injection quarantine):

```bash
python3 scripts/run_demo.py
```

Generated versioned outputs:
- `reports/baseline_reference_t1.json` — Pre-revision T1 cutoff (`2025-04-10T13:00:00Z`)
- `reports/demo_brief_t2.json` — Post-revision T2 + FOMC cutoff (`2025-05-13T13:00:00Z`)
- `reports/integration_edge_cases.json` — Unit mismatch (`MoM` vs `YoY`), `bps -> %` conversion, and conflicting NFP wire reports
- `reports/security_boundary_output.json` — Untrusted source instruction quarantine & audit log

### Running Ad-Hoc CLI Queries & Replay

```bash
# Generate a brief and persist run metadata to a local SQLite archive
PYTHONPATH=src python3 -m macro_intelligence_agent brief \
  --fixture data/fixtures/reference_cpi_release.json \
  --series-group US_INFLATION_POLICY \
  --as-of 2025-05-13T13:00:00Z \
  --config config/default_config.json \
  --db /tmp/macro_demo.sqlite3 \
  --output /tmp/brief_t2.json

# Replay the persisted run_id and verify exact logical match
RUN_ID=$(python3 -c 'import json; print(json.load(open("/tmp/brief_t2.json"))["metadata"]["run_id"])')
PYTHONPATH=src python3 -m macro_intelligence_agent replay \
  --db /tmp/macro_demo.sqlite3 \
  --run-id "$RUN_ID" \
  --config config/default_config.json
```

## 3. Validation & CI Checks

Run the full CI check locally:

```bash
bash scripts/ci_check.sh
```

This runs:
1. All 15 automated tests (`python3 -m unittest discover -s tests -p "test_*.py" -v`).
2. `scripts/run_demo.py` (including in-process replay verification).
3. `scripts/run_acceptance.py` (gold-set benchmark writing `reports/evaluation_results.json`).
4. CLI smoke check (`python3 -m macro_intelligence_agent evaluate ...`).

## 4. Diagnostics & Telemetry

Every `AgentRunResult` includes `diagnostics.counters` and ordered `diagnostics.events`:
- `releases_visible` vs `releases_gated_out`: confirms publication gate filtering.
- `security_findings`: non-zero indicates quarantined prompt-injection spans (`untrusted_source_instructions_detected` warning event).
- `conflicts_detected` and `abstentions_recorded`: indicates unresolved source conflicts, incompatible unit comparisons, or missing consensus.
- `verification_passed`: must be `1` (boolean `true` on `brief.verification_passed`).

## 5. Failure Modes & Recovery

| Symptom / Error Code | Cause | Recovery Action |
|---|---|---|
| `CONFIGURATION_ERROR` | Missing config file, invalid JSON, `allow_live_network=true`, or disabled citation/hypothesis policy | Verify `--config` path against `config/default_config.json`; restore required safety flags |
| `SCHEMA_VALIDATION_ERROR` | Naive timestamp (missing `Z` / offset), invalid decimal (`NaN`), or missing field | Normalize timestamps to UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`) and re-ingest fixture |
| `UNSUPPORTED_INPUT` | Unknown unit string or `document_type` | Map input to canonical units/types listed in `docs/contracts.md` |
| `EMBARGO_VIOLATION` | Caller explicitly requested a release/vintage before its `available_at` gate | Advance `as_of_utc` past `available_at` or remove direct lookup |
| `UNTRUSTED_SOURCE_INSTRUCTION` | Prompt injection detected with `strict_untrusted_instruction_mode="reject"` | Inspect `details.findings`, quarantine upstream source, or switch mode to `"quarantine"` if benign surrounding figures should still be extracted |
| `CITATION_VERIFICATION_FAILED` | Reported metric quote/value absent from non-quarantined text or tampered citation | Inspect upstream fixture alignment between `reported_metrics` and `raw_text` |
| `BUDGET_EXCEEDED` | Summarizer exceeded `model_adapter.max_calls_per_run` | Increase `max_calls_per_run` or set `model_adapter.provider="none"` |
| Replay mismatch (`exit code 3`) | SQLite archive modified or different config/seed used during replay | Confirm `config_sha256` and archived releases match original run metadata |
