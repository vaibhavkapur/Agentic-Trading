# Earnings Call Intelligence Agent

> **Scope & Safety Notice:** Research and educational prototype for offline deterministic execution only. No automated trade actions, live capital, customer records, or production credentials are used or supported.

Extracts verifiable financial metrics and forward guidance changes from segmented earnings-call transcripts with **exact character-level evidence spans**, **canonical unit & fiscal period normalization**, **intra-call contradiction detection**, **prompt-injection quarantine**, and **strict abstention without support**.

## Quickstart

Requires **Python >= 3.9** (zero required third-party runtime dependencies).

```bash
cd earnings-call-intelligence-agent

# 1. Run full validation suite (config check, 13 tests, demo + replay, gold benchmark)
bash scripts/run_ci.sh

# 2. Or run individual commands
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -v
python3 scripts/run_demo.py
python3 scripts/run_eval.py
```

## Example Output (Synthetic Reference Fixture)

Running `python3 scripts/run_demo.py` on `data/fixtures/reference_valid.json` (*Acme Cloud Systems Inc., Q4 FY2025*, synthetic fixture) produces deterministic run `run_665c5464612b` (replay-verified digest `540dc913daea5330af29bb5b0ee8d5a2caf1deb3adf4e9449652a50a36016464`):

```json
{
  "comparison_id": "cmp_b4fad6eb9a5e",
  "metric_name": "revenue",
  "fiscal_period": "FY2026",
  "direction": "RAISED",
  "normalized_unit": "USD_MILLIONS",
  "prior_midpoint": 1725.0,
  "current_midpoint": 1825.0,
  "delta_midpoint": 100.0,
  "contradiction_detected": false,
  "evidence_spans": [
    {
      "segment_id": "seg_002",
      "speaker": "Elena Vance",
      "char_start": 115,
      "char_end": 189,
      "exact_quote": "For full-year FY2026, we expect total revenue of $1.80 billion to $1.85 billion.",
      "verified": true
    }
  ]
}
```

Unanswerable questions (e.g., `"What was the customer churn rate in Q4 FY2025?"`) abstain explicitly with `abstained: true, abstention_reason: "NO_SUPPORTING_EVIDENCE"`.

## Measured Benchmark Results (Synthetic Gold Fixtures)

> **Important distinction:** Numbers below are **measured observations on our 4-case synthetic gold fixture suite** (`data/fixtures/gold_eval_suite.json`, 20 gold claims, 9 questions, 8 injected patterns). They are **not** guarantees of real-world production transcript accuracy. Engineering targets are defined separately in `config/eval.json`.

| Metric | Engineering Target (`config/eval.json`) | Measured on Synthetic Gold Suite (`reports/eval_results.json`) |
|---|---|---|
| Extraction Precision / Recall / F1 | F1 `>= 0.85` | Precision `1.0000` / Recall `1.0000` / **F1 `1.0000`** (`20 TP, 0 FP, 0 FN`) |
| Verbatim Citation Validity Rate | `1.00` | **`1.0000`** (`20 / 20` spans verified verbatim against source text) |
| Guidance Diff & Contradiction Accuracy | — | **`1.0000`** (`9 / 9` comparisons) |
| QA & Abstention Accuracy | `1.00` | **`1.0000`** (`9 / 9` questions) |
| Prompt-Injection Defense & Non-Leakage | `1.00` | **`1.0000`** (`8` patterns quarantined, `0` fake claims leaked) |

Full acceptance criterion mapping and raw artifacts:
- **[`reports/acceptance.md`](reports/acceptance.md)** — Acceptance criteria & test matrix evidence
- **[`reports/eval_results.json`](reports/eval_results.json)** — Machine-readable benchmark output & runtime metadata
- **[`reports/baseline_reference.json`](reports/baseline_reference.json)** — Reference fixture baseline report
- **[`reports/integration_prompt_injection.json`](reports/integration_prompt_injection.json)** — Prompt-injection integration report
- **[`reports/demo_output.json`](reports/demo_output.json)** — Demo summary & replay verification

## Repository Structure

```text
earnings-call-intelligence-agent/
├── plan.md                     # Original project implementation plan
├── pyproject.toml              # Build manifest & optional extras
├── requirements-lock.txt       # Pinned dependency & license manifest
├── config/
│   ├── default.json            # Versioned runtime & safety configuration
│   └── eval.json               # Gold evaluation tolerances & targets
├── src/earnings_call_agent/
│   ├── contracts.py            # Canonical schemas, unit/period normalization, errors
│   ├── security.py             # Prompt-injection detection & offset-preserving quarantine
│   ├── ingestion.py            # Validation, digests, freshness / staleness checks
│   ├── extraction.py           # Pure domain metric & guidance extractor
│   ├── comparison.py           # Current vs prior guidance diffing & contradiction engine
│   ├── qa.py                   # Evidence-grounded QA with strict abstention
│   ├── adapters.py             # Budgeted LLM verifier protocol, mock provider, research note export
│   ├── pipeline.py             # Orchestrator, verbatim gate, logs, replay verification
│   ├── evaluation.py           # Gold fixture F1, citation validity, and policy benchmark
│   └── cli.py                  # CLI (`analyze`, `replay`, `evaluate`, `validate-config`)
├── data/fixtures/              # 100% synthetic educational fixtures & expected oracle
├── tests/                      # Unit, domain, security, evaluation, and boundary tests
├── scripts/                    # `run_demo.py`, `run_eval.py`, `run_ci.sh`
├── docs/                       # `architecture.md`, `contracts.md`, `integration.md`, `runbook.md`, ADR-0001
└── reports/                    # `acceptance.md` and versioned JSON reports
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — Component diagram, trust boundaries, invariants, trade-offs
- [`docs/contracts.md`](docs/contracts.md) — Schemas, units, fiscal periods, timestamp semantics, error codes
- [`docs/integration.md`](docs/integration.md) — `Trading-Agentic` adapter boundaries & LLM protocol
- [`docs/runbook.md`](docs/runbook.md) — Setup, demo walkthrough, CLI, diagnostics, failure recovery
- [`docs/adr/0001-architecture-and-stack.md`](docs/adr/0001-architecture-and-stack.md) — Stack & security architecture rationale

## Assumptions, Limitations & Provenance

- **No trade actions:** `allow_trade_actions` is locked to `false`; any attempt to enable it fails configuration validation.
- **English / USD deterministic scope:** Default rule extraction supports English USD transcripts; non-USD currencies or non-English inputs fail explicitly rather than silently mis-scaling values.
- **Optional untested integrations:** Live external LLM API providers and optional vector search backends are not executed in offline CI (hybrid verification & budget enforcement are tested with `MockLLMExtractor`).
- **Clean-room synthetic fixtures & licenses:** All code is MIT-licensed original work; core runtime uses only Python stdlib (PSF-2.0); fixtures in `data/fixtures/` are 100% synthetic fictional companies with zero real customer data, live credentials, or proprietary/SAAT artifacts.
