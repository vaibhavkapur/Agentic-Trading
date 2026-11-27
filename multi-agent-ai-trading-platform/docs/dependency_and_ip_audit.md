# Dependency, Provenance & IP Audit

## 1. Linked External Repository Inventory (Section 2 of `plan.md`)

`plan.md` references three personal prototype repositories as potential foundations:
- `Trading-Software/projects/01-agentic-trading-platform`
- `Trading-Software/projects/15-agentic-trading-guardrails`
- `Trading-Software/projects/14-ai-quant-research-agent`

**Audit finding:** In this offline local environment, remote GitHub access, pinned commit verification, license confirmation, and SAAT background-IP assignment terms for those personal repositories are **unresolved**. In strict compliance with `plan.md` Section 2 (*"If access or licensing is unresolved, implement against clean, documented contracts instead"*), this repository implements **clean-room, documented domain contracts** with zero copied third-party or personal prototype code. See [ADR-001](adr/ADR-001-clean-room-contracts.md).

## 2. Third-Party Runtime & Dev Dependencies

Pinned in [uv.lock](../uv.lock) and declared in [pyproject.toml](../pyproject.toml):

| Package | Role | License (Standard Upstream) |
|---|---|---|
| `fastapi` | REST API & OpenAPI framework | MIT |
| `pydantic` | Typed schema & invariant validation | MIT |
| `uvicorn` | ASGI server for local Operator Console | BSD-3-Clause |
| `httpx` (dev) | FastAPI `TestClient` transport | BSD-3-Clause |
| `pytest` (dev) | Automated unit, integration & scenario tests | MIT |
| `ruff` (dev) | Static linting & import hygiene | MIT |

No external LLM API keys, cloud SDKs, or proprietary market data feeds are required to run setup, tests, demos, or failure drills.

## 3. Data Provenance & Entitlements

All fixtures are recorded in [config/fixtures_manifest.json](../config/fixtures_manifest.json). Every input file under `data/fixtures/` is **100% synthetic** (`internal-synthetic-unrestricted`) with explicit UTC timestamps and `USD` currency. No real market quotes, copyrighted filings, or customer PII are stored in the repository.

## 4. Security & Deployment Approval Gate

- **Secrets management:** Zero credentials or tokens exist in `config/` or source files.
- **Execution safety:** `execution_mode` defaults to `DISABLED`; `allow_live_trading` is hard-rejected by `PolicyConfig` and `PolicyEngine`.
- **Promotion requirement:** Moving beyond this local paper prototype requires explicit legal/regulatory, broker, security, risk, and SAAT IP ownership sign-off.
