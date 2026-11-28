# AI Strategy Code Generation Sandbox

> **Scope:** Independently developed educational/research prototype for evaluating AI-generated trading strategy code in isolated, resource-bounded offline paper experiments. No live capital, real customer records, market feeds, or broker credentials are used or supported.

## Overview

This project implements a defense-in-depth evaluation sandbox for LLM- or human-authored trading strategy proposals:

- **Typed data contracts & restricted strategy API** (`on_bar(ctx)` with read-only causal `StrategyContext`, `OrderIntent`, `StrategySpec`, `DatasetManifest`, `ExperimentBudget`, and `StrategyProposal`).
- **Multi-layer isolated execution** (dataset untrusted-text screening, static AST allowlist & budget gate, clean-environment isolated Python subprocess with `RLIMIT_CPU`/`RLIMIT_NOFILE`/`RLIMIT_CORE` + Linux `RLIMIT_AS`, PEP 578 `sys.addaudithook`, `tracemalloc` memory cap, wall-clock process-group kill switch, and bounded stdout).
- **Automated research-integrity verification** covering **future-data leakage** (future-shock perturbation + prefix-truncation invariance), **determinism** (seeded repeat runs), **double-entry paper accounting** (`|equity - (initial_cash + realized_pnl + unrealized_pnl - commission)| <= 1e-6`), and **hand-calculated reference oracle comparison**.
- **Auditability & human-review promotion gate**: Every trial is persisted with SHA-256 artifact hashes (`code_sha256`, `dataset_sha256`, `input_bundle_sha256`, `output_sha256`), replay verification, and strict governance blocking promotion without both a passing hash-verified trial and a matching human `APPROVE` review.

## Quickstart

### 1. Setup

```bash
cd ai-strategy-code-generation-sandbox
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
```

### 2. Run the test suite

```bash
PYTHONPATH=src .venv/bin/pytest -v
```

### 3. Run the reproducible demo & benchmarks

```bash
PYTHONPATH=src .venv/bin/python scripts/run_demo_and_benchmarks.py
```

### Example observed output (synthetic offline fixtures)

```text
=== AI Strategy Code Generation Sandbox — Demo Summary ===
Reference trial ID : trial-5a25ccc8126d-6b893d53
Reference status   : PASSED
Final equity       : $101,137.0006 (expected $101,137.0006, identity_err=0.00e+00)
Replay match       : True
Governance gate    : unreviewed_blocked=True, promoted=True
Benchmark (5 runs) : median full eval=189.63 ms, median single sandbox exec=30.59 ms
Docker available   : False
```

> **Note:** Observed figures above are measured on deterministic synthetic fixtures (`data/fixtures/reference_dataset.json`, 10 bars, `SYNTH_A`), not live market backtests or performance targets.

## Repository layout

```text
ai-strategy-code-generation-sandbox/
├── plan.md                                # Original implementation specification
├── pyproject.toml                         # Package metadata and pytest config
├── requirements.lock.txt                  # Pinned Python 3.12 dependency versions
├── Dockerfile & docker-compose.yml        # Optional rootless container profile
├── config/default_sandbox_config.json     # Default policy, budgets, tolerances
├── data/fixtures/                         # Deterministic valid, invalid, oracle & adversarial fixtures
├── src/strategy_sandbox/                  # Core library, worker, paper engine, verifiers, registry, CLI
├── tests/                                 # 30 automated unit, security, leakage, governance & CLI tests
├── scripts/run_demo_and_benchmarks.py     # Reproducible demo & raw report generator
├── docs/                                  # Architecture, ADR-0001, contracts, integration, runbook
└── reports/                               # Acceptance evidence & machine-readable JSON outputs
```

## Documentation & acceptance evidence

- **Acceptance Report:** [reports/acceptance.md](reports/acceptance.md) (maps every criterion to test cases and raw JSON artifacts [reports/demo_results.json](reports/demo_results.json) and [reports/benchmark_results.json](reports/benchmark_results.json))
- **Architecture & Threat Model:** [docs/architecture.md](docs/architecture.md) and [docs/adr/0001-sandbox-architecture.md](docs/adr/0001-sandbox-architecture.md)
- **Data Contracts & Restricted Strategy API:** [docs/contracts.md](docs/contracts.md)
- **Integration Boundaries:** [docs/integration.md](docs/integration.md)
- **Operator / Developer Runbook:** [docs/runbook.md](docs/runbook.md)

## Dependencies, licenses, and fixture provenance

- **Runtime dependencies:** Python 3.12 stdlib (PSF License), `pydantic==2.14.4` (MIT), `pydantic-core==2.50.5` (MIT), `annotated-types==0.8.0` (MIT), `typing-extensions==4.16.0` (PSF), `typing-inspection==0.4.5` (MIT).
- **Dev/test dependencies:** `pytest==8.4.2` (MIT), `pluggy==1.7.0` (MIT), `iniconfig==2.3.1` (MIT), `packaging==26.4` (Apache-2.0 / BSD-2-Clause), `pygments==2.21.0` (BSD-2-Clause).
- **Fixture provenance:** All files under `data/fixtures/` are original synthetic fixtures created specifically for deterministic oracle verification and security/boundary regression testing. No confidential, proprietary, customer, or employer/SAAT data is included.

## Known limitations & assumptions

1. **Isolation boundary:** Python subprocess isolation, PEP 578 audit hooks, and containers alone are **not** a perfect security boundary against hostile untrusted code. Production execution of untrusted third-party code requires hardware-virtualized microVMs (e.g., Firecracker/gVisor) plus independent security, operational, legal, and risk review.
2. **Untested host capabilities:** Rootless Docker container execution (`Dockerfile` / `docker-compose.yml`) was **not run** in the verification environment because Docker is not installed (`docker_available: false`); Linux `RLIMIT_AS` is skipped on macOS ARM64 (covered by `tracemalloc` locally and by Linux CI).
3. **Paper execution model:** Market orders fill deterministically at current bar close adjusted by fixed `slippage_bps` and `commission_bps`; limit/stop books, partial liquidity fills, corporate actions, and live broker connectivity are out of scope.
