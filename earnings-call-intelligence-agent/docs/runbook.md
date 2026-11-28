# Operator & Developer Runbook

## 1. Local Setup (Clean Checkout)

No third-party packages or API keys are required to run the core agent, tests, demo, or gold benchmark.

```bash
cd earnings-call-intelligence-agent
python3 --version   # Requires Python >= 3.9
```

(Optional) To install in editable mode into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-build-isolation -e .
```

## 2. Quick Demo Walkthrough

Run the reproducible end-to-end demo script:

```bash
python3 scripts/run_demo.py
```

This script:
1. Validates `config/default.json` and ingests `data/fixtures/reference_valid.json` (Acme Cloud Systems Q4 FY2025 synthetic call) at `as_of_timestamp=2026-02-15T12:00:00Z`.
2. Extracts 8 verbatim-verified financial claims, computes 4 guidance comparisons (`RAISED`, `INTRODUCED`, `REAFFIRMED` with `HIGH_UNCERTAINTY_LANGUAGE`, `LOWERED`), answers 2 supported questions, and abstains on 1 unanswerable churn question.
3. Replays the run and verifies the deterministic logical SHA-256 digest matches bit-for-bit.
4. Executes the `prompt_injection.json` integration scenario, quarantining 8 adversarial patterns without leaking fabricated claims.
5. Writes `reports/baseline_reference.json`, `reports/integration_prompt_injection.json`, and `reports/demo_output.json`.

## 3. CLI Usage

```bash
# Validate configuration
PYTHONPATH=src python3 -m earnings_call_agent validate-config --config config/default.json

# Analyze a single transcript
PYTHONPATH=src python3 -m earnings_call_agent analyze \
  --input data/fixtures/reference_valid.json \
  --as-of 2026-02-15T12:00:00Z

# Replay and verify deterministic logical digest
PYTHONPATH=src python3 -m earnings_call_agent replay \
  --input data/fixtures/reference_valid.json \
  --as-of 2026-02-15T12:00:00Z \
  --expected-digest 540dc913daea5330af29bb5b0ee8d5a2caf1deb3adf4e9449652a50a36016464

# Run gold benchmark evaluation
PYTHONPATH=src python3 -m earnings_call_agent evaluate \
  --suite data/fixtures/gold_eval_suite.json \
  --eval-config config/eval.json \
  --output reports/eval_results.json
```

## 4. Full Validation Suite

Run the single-command CI validation script (config check + unit/integration/boundary tests + demo replay + gold benchmark):

```bash
bash scripts/run_ci.sh
```

## 5. Diagnostics, Structured Logs & Replay

Every `AnalysisReport` contains:
- `diagnostics`: exact counters (`segments_ingested`, `segments_quarantined`, `injection_events_count`, `claims_extracted`, `claims_verified`, `claims_rejected_unverified`, `guidance_comparisons_count`, `contradictions_detected`, `questions_answered`, `questions_abstained`, `llm_calls_used`, `llm_tokens_used`).
- `structured_logs`: ordered stage records (`ingestion`, `security_scan`, `extraction_and_verification`, `guidance_comparison`, `question_answering`) keyed by `run_id`.
- `warnings`: human-readable alerts for `STALE_SOURCE`, `PROMPT_INJECTION_DETECTED`, `CONTRADICTORY_GUIDANCE`, or `TIMESTAMP_ANOMALY`.

## 6. Failure Modes & Recovery

| Symptom / Error Code | Cause | Recovery Action |
|---|---|---|
| `MISSING_CONFIG_FILE` (exit 1) | `--config` path missing | Pass valid path (e.g. `config/default.json`) and re-run `validate-config` |
| `POLICY_VIOLATION` (exit 1) | `allow_trade_actions=true` or `require_verified_evidence=false` | Restore safety defaults (`allow_trade_actions: false`, `require_verified_evidence: true`) |
| `NAIVE_TIMESTAMP` / `INCONSISTENT_TIMESTAMPS` | Input lacks timezone or `published_at < call_timestamp` | Fix source timestamps to explicit UTC ISO-8601 (`...Z`) |
| `UNSUPPORTED_CURRENCY` / `UNSUPPORTED_LANGUAGE` | Non-USD or non-English transcript | Outside v1.0.0 scope; do not bypass without extending unit conversion & tests |
| `SEGMENT_BUDGET_EXCEEDED` / `LLM_*_BUDGET_EXCEEDED` | Input exceeds configured ceiling | Chunk transcript or increase configured budget explicitly with review |
| Replay digest mismatch (exit 2) | Input, config, seed, `as_of_timestamp`, or code version changed | Compare `input_digest`, `config_digest`, and `runtime_metadata` between runs |

## 7. Known Limitations

- **Research prototype only:** Not certified for production trading, regulatory filings, or investment advice; automated trade execution is permanently disabled.
- **Deterministic English/USD scope:** Default rule extractor covers USD monetary amounts, per-share EPS, percentages, and basis points in English transcripts. Non-standard phrasing, tables outside transcript text, or multi-currency FX adjustments are not handled automatically.
- **Pattern-based prompt-injection defense:** Quarantine rules catch explicit instruction overrides, system tags, tool spoofing, exfiltration, and order directives; subtle semantic social-engineering attacks would require additional layered defenses if paired with a live LLM.
- **Untested optional capabilities:** Live external LLM API calls and optional vector search backends are not executed in offline CI and remain unbenchmarked here.
