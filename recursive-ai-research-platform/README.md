# Recursive AI Research Platform (RARP)

An auditable, bounded recursive AI research loop that proposes hypotheses, executes deterministic causal experiments, critiques results with cryptographically evidence-linked claims, remembers failed hypotheses, protects blinded holdout splits, and requires independent human review before paper-sandbox-only promotion.

> **Governance Notice:** This is a local reproducible prototype. Order execution is **disabled by default**, automatic or direct live deployment is **explicitly prohibited**, unrestricted generated code is **explicitly banned**, and simulated metrics on synthetic fixtures never imply live performance or alpha.

## Getting started

Run these commands from `recursive-ai-research-platform/` with Python 3.9 or later. The core demo uses the standard library. Optional FastAPI, PostgreSQL, and S3 dependencies are listed in [pyproject.toml](pyproject.toml).

```bash
bash scripts/setup.sh
bash scripts/validate.sh
bash scripts/demo.sh
bash scripts/reproduce.sh
```

To launch the local Review Console on `http://127.0.0.1:8080` after running the demo:

```bash
PYTHONPATH=src python3 -m rarp serve-console --state-dir reports/demo_state --port 8080
```

## How it works

| Deliverable | Module(s) | Key Guarantees |
|---|---|---|
| Hypothesis & Experiment DSL | `src/rarp/domain/dsl.py` | Declarative typed specs, versioned strategy catalog & parameter bounds, explicit ban on arbitrary generated code, mandatory causal lag `>= 1`, canonical semantic fingerprints. |
| Research DAG & Budget Scheduler | `src/rarp/scheduler/` | Cycle-checked typed Research DAG, hard-enforced iteration/experiment/USD-cost/compute/token ceilings, stop conditions, idempotent workers with crash-checkpoint retry & replay deduplication, TS-14 clean-room adapter boundary. |
| Immutable Run Registry & Research Memory | `src/rarp/registry/` | Append-only SQLite (with `BEFORE UPDATE`/`BEFORE DELETE` immutability triggers), JSONL audit log, cryptographic hash-chain, content-addressed object store, exact & near-duplicate novelty checks, negative-result indexing, PSR/DSR/Bonferroni trial accounting. |
| Evidence-Linked Critic & Refiner | `src/rarp/critic/` | Every numerical claim binds to `(run_id, metric_name, artifact_sha256, value)` verified against the immutable registry; hallucinated or tampered metrics are detected, audited, and quarantined; bounded iterative refiner consumes critic findings and negative memory. |
| Human Review, Signing & Paper-Only Gate | `src/rarp/governance/` | HMAC-SHA256 signed research bundles (key from env/caller, never hardcoded), strict separation of duties (`reviewer_id != proposer_id`, no automated self-review), `PAPER_SANDBOX` target only (`order_execution_enabled=false`, `LIVE` rejected), WSGI + optional FastAPI review console. |

## Project layout

```text
recursive-ai-research-platform/
  plan.md
  README.md
  pyproject.toml
  config/            # Versioned strategy catalog, cost scenarios, loop config (no secrets)
  data/fixtures/     # Deterministic synthetic fixture CSV + SHA-256 manifest
  docs/              # Architecture, API/schemas, assumptions/limitations, runbook, ADRs
  src/rarp/          # Domain contracts, data/holdout guard, scheduler, registry, critic, governance
  tests/             # unit/, integration/, and all 6 required failure-path scenarios/
  scripts/           # setup.sh, validate.sh, demo.sh, reproduce.sh, export_scenario_evidence.py
  reports/           # Demo report, reproducibility report, scenario evidence, test report, acceptance evidence
```

## Documentation

- [Architecture](docs/architecture.md)
- [API & Schema Reference](docs/api_and_schemas.md)
- [Assumptions, Limitations, Security & IP Review](docs/assumptions_and_limitations.md)
- [Operator Runbook](docs/runbook.md)
- ADRs:
  - [ADR 0001 — TS-14 Audit & Foundation Contracts](docs/adr/0001-ts14-audit-and-foundation.md)
  - [ADR 0002 — Evidence-Linked Critic, Novelty & Budgets](docs/adr/0002-critic-novelty-and-budget.md)
  - [ADR 0003 — Research Memory, Trial Accounting & Blinded Holdout](docs/adr/0003-memory-trial-accounting-and-holdout.md)
  - [ADR 0004 — Signed Artifacts, Review Console & Paper-Only Gate](docs/adr/0004-signed-artifacts-console-and-paper-gate.md)
