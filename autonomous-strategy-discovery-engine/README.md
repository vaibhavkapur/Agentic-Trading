# Autonomous Strategy Discovery Engine (ASDE)

Constrained systematic strategy discovery, nested parameter tuning, cost-aware walk-forward evaluation, multiple-testing reporting, and auditable strategy package export.

> **Governance Notice:** This is a local reproducible research prototype. Order execution is disabled by default, live strategy selection based on backtest returns is strictly prohibited, and simulated walk-forward metrics never imply live trading performance.

## Quickstart (Clean Checkout)

Requires Python 3.9+ (zero mandatory external dependencies for core execution).

```bash
cd autonomous-strategy-discovery-engine
bash scripts/setup.sh
bash scripts/validate.sh
bash scripts/demo.sh
bash scripts/reproduce.sh
```

## MVP Deliverables Implemented

| Component | Module(s) | Responsibility |
|---|---|---|
| Strategy DSL & Catalog | `src/asde/dsl/` | Declarative typed strategy specs, versioned allowed families & parameter bounds, explicit ban on unconstrained code generation, point-in-time signal compiler with strict lag (`>= 1`) and `available_time_utc` enforcement. |
| Fixtures & Immutable Splits | `src/asde/data/` | Deterministic synthetic multi-regime & pure-noise fixtures with SHA-256 manifests; immutable chronological `train / val / test` splits with embargo gaps, non-overlapping walk-forward & inner folds, and `HoldoutGuard`. |
| Cost-Aware Evaluator | `src/asde/evaluation/` | Explicit cost scenarios (commission, half-spread, slippage, impact, short borrow), reference bar-by-bar backtester (`BacktesterAdapter` contract), walk-forward robustness & cost sensitivity, and block-bootstrap uncertainty intervals. |
| Search, Tuning & Reporting | `src/asde/search/`, `src/asde/reporting/` | Seeded bounded candidate generator, nested inner-fold parameter tuner (`OptimizerAdapter` contract), append-only SQLite + JSONL trial ledger accounting for every trial (including failures), PSR/DSR/Bonferroni/Holm/BH-FDR multiple-testing adjustments, and research leaderboard. |
| Export & Independent Review | `src/asde/export/` | Self-contained strategy packages with exact config, catalog, dataset, split, and cost SHA-256 fingerprints; `ReviewGate` enforcing independent human review for `paper_sandbox` only while keeping live execution disabled. |

## Repository Structure

```text
autonomous-strategy-discovery-engine/
  plan.md
  README.md
  pyproject.toml
  config/            # Versioned settings, cost scenarios, strategy catalog (no secrets)
  data/fixtures/     # Synthetic fixtures + SHA-256 manifest + generator
  docs/              # Architecture, API/schemas, ADRs, assumptions/limitations, runbook
  src/asde/          # Core domain contracts, engine, adapters, and CLI
  tests/             # unit/, integration/, and all 6 required scenarios/
  scripts/           # setup.sh, demo.sh, reproduce.sh, validate.sh
  reports/           # Generated demo leaderboard, trial ledger, scenario & acceptance evidence
```

## Documentation

- [Architecture](docs/architecture.md)
- [API & Schema Reference](docs/api_and_schemas.md)
- [Assumptions, Limitations, Security & IP Review](docs/assumptions_and_limitations.md)
- [Operator Runbook](docs/runbook.md)
- [ADRs](docs/adr/0001-foundation-contracts.md)
