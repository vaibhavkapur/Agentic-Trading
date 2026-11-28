# Financial Agent Evaluation Framework

An offline, deterministic evaluation framework for measuring **numeric correctness**, **citation faithfulness**, **tool execution integrity**, **abstention judgment**, and **adversarial resilience** across financial agent tasks.

> **Scope Notice:** Independently developed educational/research prototype executing exclusively on offline synthetic fixtures and mock tools. Live capital, real customer records, and production credentials are strictly excluded.

## Key Capabilities

- **Typed Data Contracts (Pydantic v2):** Strict schemas (`extra="forbid"`) for versioned gold tasks, unit-aware numeric expectations, UTC-enforced timestamps, evidence records (`is_untrusted_text=True`), tool contracts, and reports — see [docs/contracts.md](docs/contracts.md).
- **Zero-I/O Deterministic Graders:**
  - **Numeric Grader:** Cross-unit conversion (`USD` / `USD_MILLIONS` / `USD_BILLIONS`, `RATIO` / `PERCENT` / `BPS`), unit-mismatch detection, and absolute/relative tolerance checks.
  - **Tool & Receipt Integrity Grader:** Every real mock-tool call produces an HMAC-SHA256 `ToolExecutionReceipt`, preventing fabricated tool execution and catching blocked unsafe tool requests (`execute_live_order`, `wire_transfer`, `export_customer_records`, `modify_production_db`).
  - **Citation & Freshness Grader:** Verifies evidence ID existence, span grounding, required coverage, and evidence age against `max_evidence_age_seconds`.
  - **Abstention & Injection Safety Grader:** Enforces warranted abstention on unsafe requests, unavailable tools, or stale evidence, and catches prompt-injection compromises.
- **Human Rubric & LLM-Judge Guardrail:** 5-dimension anchored rubric with inter-rater Cohen's kappa (`docs/human_rubric.md`) and a hard policy prohibiting advisory LLM-as-judge scores from overriding deterministic hard fails.
- **Failure Injection Middleware:** Deterministic/seeded injection of `tool_unavailable`, `tool_timeout`, `tool_malformed_response`, `rate_limit`, `stale_evidence`, and `prompt_injection`.
- **Versioned Reports, Confidence Intervals & Replay:** Generates JSON + Markdown reports with 95% Wilson pass-rate CIs, 95% t-interval score CIs, failure-type breakdowns, cost/latency estimates, structured JSONL event logs, baseline regression diffs, and offline replay bundles (`*.replay.json`).

## Project Layout

```text
financial-agent-evaluation-framework/
├── config/                     # Versioned model configs and failure injection profiles
├── data/fixtures/              # Synthetic dev, held-out, oracle, and invalid fixtures
├── docs/                       # Architecture, contracts, integration, runbook, rubric, ADR-0001
├── reports/
│   ├── acceptance.md           # Acceptance criteria mapped to measured evidence
│   ├── baseline/               # Reference baseline JSON, MD, replay bundle, JSONL logs
│   └── runs/                   # Resilience, stochastic 5x, and held-out benchmark outputs
├── scripts/run_demo.py         # Reproducible end-to-end demo & benchmark script
├── src/fin_eval/               # Core library, graders, mock runtime, injection, runner, CLI
├── tests/                      # Unit, integration, boundary, reproducibility & operational tests
├── pyproject.toml              # Package metadata and pytest configuration
└── requirements-lock.txt       # Pinned dependencies with documented licenses
```

## Quickstart & Setup

Requires Python `>=3.10` (verified on Python `3.12.15`).

```bash
cd financial-agent-evaluation-framework
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
```

## Validation & Demo Commands

```bash
# 1. Validate canonical fixtures and configs
PYTHONPATH=src .venv/bin/python -m fin_eval validate \
  --dataset data/fixtures/gold_tasks_dev_v1.json \
  --fixtures data/fixtures/mock_store_v1.json \
  --config config/model_deterministic.json \
  --faults config/faults_resilience.json

# 2. Run the full automated test suite (22 tests)
PYTHONPATH=src .venv/bin/pytest -v

# 3. Run the reproducible end-to-end demo (baseline, resilience, 5x stochastic, held-out, replay)
PYTHONPATH=src .venv/bin/python scripts/run_demo.py
```

## Example Observed Output (`scripts/run_demo.py`)

Measured on CPython `3.12.15` using offline synthetic fixtures (`gold_tasks_dev_v1.json`, `gold_tasks_held_out_v1.json`, `mock_store_v1.json`):

```json
{
  "baseline": {
    "report_id": "eval-fin_gold_dev-mock_deterministic_v1-6c3a8c9ad1f2",
    "pass_rate": 1.0,
    "mean_score": 1.0,
    "receipt_verification_rate": 1.0,
    "total_cost_usd": 0.005968,
    "mean_latency_ms": 112.375
  },
  "resilience_injected": {
    "report_id": "eval-fin_gold_dev-mock_deterministic_v1-41e274963cb4",
    "pass_rate": 1.0,
    "mean_score": 1.0,
    "faults_injected": 7,
    "baseline_within_tolerance": true
  },
  "stochastic_5x": {
    "report_id": "eval-fin_gold_dev-mock_stochastic_v1-2fbe67029321",
    "pass_rate_ci": {
      "mean": 0.75,
      "lower": 0.59806,
      "upper": 0.858129,
      "confidence_level": 0.95,
      "method": "wilson",
      "n_samples": 40,
      "std_dev": 0.433013
    },
    "mean_score_ci": {
      "mean": 0.926875,
      "lower": 0.884137,
      "upper": 0.969613,
      "confidence_level": 0.95,
      "method": "t_interval",
      "n_samples": 40,
      "std_dev": 0.137909
    },
    "failure_type_counts": {
      "UNSUPPORTED_CLAIM": 5,
      "WRONG_ARITHMETIC": 6
    },
    "total_cost_usd": 0.042347,
    "p95_latency_ms": 163.399975
  },
  "held_out": {
    "report_id": "eval-fin_gold_held_out-mock_deterministic_v1-2f419b7d864f",
    "pass_rate": 1.0,
    "mean_score": 1.0
  },
  "replay_verified": true
}
```

> **Measured vs. Synthetic Note:** Pass rates, scores, failure counts, confidence intervals, and replay determinism are **actual measured outputs** of the evaluator. Token counts, USD costs, and mock tool latencies are **synthetic estimates** driven by `config/model_*.json` rather than live LLM provider billing.

## Documentation & Acceptance Evidence

- **Acceptance Evidence Matrix:** [reports/acceptance.md](reports/acceptance.md)
- **Architecture & Diagrams:** [docs/architecture.md](docs/architecture.md)
- **Data Contracts:** [docs/contracts.md](docs/contracts.md)
- **Integration Guide:** [docs/integration.md](docs/integration.md)
- **Operator Runbook:** [docs/runbook.md](docs/runbook.md)
- **Human Rubric:** [docs/human_rubric.md](docs/human_rubric.md)
- **ADR 0001:** [docs/adr/0001-deterministic-evaluation-architecture.md](docs/adr/0001-deterministic-evaluation-architecture.md)
- **Original Plan:** [plan.md](plan.md)

## Assumptions, Limitations & Provenance

- **Fixture Provenance:** All issuer data (`ACME`, `ORBN`, `VLTQ`), quotes, filings, and macro releases are original synthetic educational fixtures authored for this repository.
- **Dependency Licenses (`requirements-lock.txt`):** `pydantic`, `pydantic-core`, `annotated-types`, `typing-inspection`, `pytest`, `iniconfig`, `pluggy` (MIT); `typing-extensions` (PSF-2.0); `packaging` (Apache-2.0 OR BSD-2-Clause); `pygments` (BSD-2-Clause).
- **Known Limitations:**
  - External LLM API transport (`OptionalLLMProviderAdapter`) is intentionally disabled by default (`external_network_allowed=false`) and not benchmarked against live cloud models.
  - Agents must emit structured `NumericClaim` and `CitationClaim` records via `FinancialAgentAdapter` rather than unstructured prose alone.
  - Not approved for production trading, live order routing, or processing regulated customer data without independent security, legal, and risk review.
