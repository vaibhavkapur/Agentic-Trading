# Multi-Agent AI Trading Platform

Research and portfolio agents propose paper trades. An independent risk service checks each proposal, the policy engine decides whether it can proceed, and a human approves the exact order before the order management system sends it to the paper broker.

> **Scope & Safety Notice**: Local reproducible prototype operating strictly on synthetic fixtures (`config/fixtures_manifest.json`). Order execution defaults to `DISABLED`; only `PAPER` mode may be explicitly enabled by an authorized operator. Live real-capital trading is permanently disabled in this prototype and is not implied by simulated test evidence.

## Getting started

Run these commands from `multi-agent-ai-trading-platform/`. The setup script uses `python3 -m uv` to create a Python 3.12 virtual environment.

```bash
# 1. Create Python 3.12 virtualenv and install package + dev tools
./scripts/setup.sh

# 2. Run full validation (ruff lint, 25 unit/integration/scenario tests, paper demo, 8-case failure drill)
./scripts/validate.sh

# 3. Launch FastAPI REST API + zero-CDN Operator Console (http://127.0.0.1:8080)
.venv/bin/matp serve
```

## How it works

| Component | Implementation |
|---|---|
| **Research, Portfolio & Risk Adapters** | Read-only `FundamentalResearchAgent` and `MomentumNewsResearchAgent` (`src/trading_platform/agents/research_agent.py`), read-only `PortfolioAgentAdapter` (`src/trading_platform/agents/portfolio_agent.py`), and independent deterministic `IndependentRiskService` (`src/trading_platform/agents/risk_agent.py`). |
| **Bounded Orchestrator & Tool Gateway** | `MultiAgentOrchestrator` (`src/trading_platform/orchestrator/engine.py`) and `BoundedToolGateway` (`src/trading_platform/tools/gateway.py`) enforce per-agent/per-run tool budgets, strict permission scopes, malicious argument filtering, prompt-injection quarantine (`PromptInjectionGuard`), and multi-agent conflict detection. |
| **Shared State & Decision Provenance** | Durable SQLite repository (`src/trading_platform/storage/repository.py`) mirroring PostgreSQL DDL (`docs/schema.sql`), typed `EventBus` (`src/trading_platform/storage/event_bus.py`), immutable SHA-256 content-hashed `EvidenceItem` records, and an append-only SHA-256 hash-chained `audit_log`. |
| **Deterministic Policy & Exact-Action Approvals** | `PolicyEngine` (`src/trading_platform/policy/engine.py`) acts as final authority and forbids agent overrides or live execution. `ExactActionApprovalService` (`src/trading_platform/policy/approvals.py`) binds approvals to a canonical SHA-256 `exact_action_hash`, enforces TTL expiration, RBAC/maker-checker separation, and single-use consumption against replay. |
| **Idempotent OMS, Paper Broker & Console** | `IdempotentOMS` (`src/trading_platform/execution/oms.py`) repeats independent risk checks at `PRE_DISPATCH`, deduplicates orders via `idempotency_key`, reconciles broker timeouts by `client_order_id`, and deduplicates fills by `broker_fill_id`. Exposed via FastAPI (`src/trading_platform/api/app.py`), zero-CDN Operator Console (`src/trading_platform/web/index.html`), and `matp` CLI (`src/trading_platform/cli.py`). |

## Project layout

```text
multi-agent-ai-trading-platform/
├── plan.md                        # Original implementation plan
├── README.md                      # Quickstart and overview
├── pyproject.toml                 # Package metadata, dependencies, ruff & pytest config
├── uv.lock                        # Reproducible dependency lockfile
├── config/                        # Versioned platform settings & fixture manifest (no secrets)
├── data/fixtures/                 # Synthetic market data, clean news, and adversarial fault fixtures
├── docs/                          # Architecture, API/schema, PostgreSQL DDL, IP audit, ADRs, runbook
├── src/trading_platform/          # Domain contracts, storage, tools, agents, policy, execution, API, UI, CLI
├── scripts/                       # setup.sh, validate.sh, demo.py, scenario_drill.py
├── tests/                         # unit/, integration/, scenarios/ (all 7 plan.md failure paths + restart)
└── reports/                       # M1–M4 milestone reports, acceptance checklist, and raw evidence/
```

## Documentation

- [Architecture & Trust Boundaries](docs/architecture.md)
- [API, CLI, Event Bus & PostgreSQL Schema](docs/api_and_schema.md) ([schema.sql](docs/schema.sql))
- [Dependency & IP Audit](docs/dependency_and_ip_audit.md)
- [Operator Runbook & Failure Response](docs/runbook.md)
- [Unsupported Features & Non-Goals](docs/unsupported_features.md)
- [ADRs](docs/adr/ADR-001-clean-room-contracts.md): [ADR-001](docs/adr/ADR-001-clean-room-contracts.md), [ADR-002](docs/adr/ADR-002-deterministic-policy-and-exact-action-approvals.md), [ADR-003](docs/adr/ADR-003-idempotent-oms-and-pre-dispatch-risk.md)
- [Milestone Reports](reports/m1_foundation_report.md): [M1](reports/m1_foundation_report.md), [M2](reports/m2_core_implementation_report.md), [M3](reports/m3_integration_validation_report.md), [M4](reports/m4_hardening_and_delivery_report.md)
- [Acceptance Checklist & Raw Evidence](reports/acceptance_checklist.md)
