# Operator & Developer Runbook

## 1. Environment Setup (Clean Checkout)

```bash
cd financial-agent-evaluation-framework
python3 -m venv .venv          # or: python3 -m uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
```

## 2. Standard Validation Commands

### Validate Canonical Fixtures & Configs
```bash
PYTHONPATH=src .venv/bin/python -m fin_eval validate \
  --dataset data/fixtures/gold_tasks_dev_v1.json \
  --fixtures data/fixtures/mock_store_v1.json \
  --config config/model_deterministic.json \
  --faults config/faults_resilience.json
```

### Run Full Automated Test Suite
```bash
PYTHONPATH=src .venv/bin/pytest -v
```

Run individual test categories by pytest marker:
```bash
PYTHONPATH=src .venv/bin/pytest -m unit
PYTHONPATH=src .venv/bin/pytest -m integration
PYTHONPATH=src .venv/bin/pytest -m boundary
PYTHONPATH=src .venv/bin/pytest -m reproducibility
PYTHONPATH=src .venv/bin/pytest -m operational
```

## 3. End-to-End Demo & Benchmarking

Run the complete reproducible benchmark suite (baseline, failure injection, 5-seed stochastic variance, held-out verification, and replay check):
```bash
PYTHONPATH=src .venv/bin/python scripts/run_demo.py
```

Or invoke individual CLI evaluation runs:
```bash
# Deterministic baseline
PYTHONPATH=src .venv/bin/python -m fin_eval run \
  --dataset data/fixtures/gold_tasks_dev_v1.json \
  --fixtures data/fixtures/mock_store_v1.json \
  --config config/model_deterministic.json \
  --faults config/faults_none.json \
  --out-dir reports/baseline

# 5-seed stochastic repeat run compared to baseline
PYTHONPATH=src .venv/bin/python -m fin_eval run \
  --dataset data/fixtures/gold_tasks_dev_v1.json \
  --fixtures data/fixtures/mock_store_v1.json \
  --config config/model_stochastic.json \
  --repeats 5 \
  --out-dir reports/runs

# Final held-out verification (requires explicit opt-in flag)
PYTHONPATH=src .venv/bin/python -m fin_eval run \
  --dataset data/fixtures/gold_tasks_held_out_v1.json \
  --fixtures data/fixtures/mock_store_v1.json \
  --config config/model_deterministic.json \
  --include-held-out \
  --out-dir reports/runs
```

## 4. Deterministic Replay and Baseline Comparison

```bash
# Re-grade a saved trajectory bundle without re-running agents or tools
PYTHONPATH=src .venv/bin/python -m fin_eval replay \
  --bundle reports/baseline/<report_id>.replay.json \
  --expected-report reports/baseline/<report_id>.report.json

# Compare two saved reports within tolerance
PYTHONPATH=src .venv/bin/python -m fin_eval compare \
  --current reports/runs/<current_report_id>.report.json \
  --baseline reports/baseline/<baseline_report_id>.report.json \
  --tolerance 0.02
```

## 5. Diagnostics & Error Recovery

| Error / Exit Code | Root Cause | Recovery Action |
|---|---|---|
| `ConfigurationError` (exit 1) | Missing or syntactically invalid JSON config/fixture file | Verify file path and JSON syntax with `fin-eval validate` |
| `ContractValidationError` (exit 1) | Schema violation (naive timestamp, unknown field, overlapping allowed/forbidden tools, `live_execution_enabled=true`) | Inspect stderr field path; fix fixture against `docs/contracts.md` |
| `HeldOutLeakageError` (exit 1) | Attempted to run a `held_out` split without `--include-held-out` | Use `gold_tasks_dev_v1.json` during development; pass `--include-held-out` only for final evaluation |
| `UnsupportedOperationError` (exit 1) | External LLM provider requested while `external_network_allowed=false` or API key unset | Keep offline mock providers for standard runs, or configure custom adapter per `docs/integration.md` |
| Exit code `2` on `replay` or `compare` | Replay ID diverged from expected report, or regression exceeded tolerance | Inspect `*.events.jsonl` and `*.report.md` task-level failure types (`WRONG_ARITHMETIC`, `FABRICATED_CITATION`, etc.) |
