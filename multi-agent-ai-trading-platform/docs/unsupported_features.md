# Unsupported Features & Explicit Non-Goals (MVP Scope)

Per `plan.md` Sections 1, 7, and 8, the following capabilities are **explicitly unsupported** in this MVP prototype:

1. **Live Real-Capital Trading:** Permanently blocked in `PolicyConfig` (`allow_live_trading=False`) and `PolicyEngine` (`LIVE_TRADING_FORBIDDEN`). No real broker credentials, FIX adapters, or live market routing exist.
2. **Agent-Controlled Policy or Risk Overrides:** Agents cannot modify risk thresholds, extend approval TTLs, approve their own proposals, or invoke execution tools (`AGENT_POLICY_OVERRIDE_FORBIDDEN`, `AGENT_EXECUTION_FORBIDDEN`).
3. **Autonomous Execution Without Human Approval:** `require_human_approval=True` is enforced across all order intents; there is no unattended auto-execution mode.
4. **Live LLM Provider Integration:** Agent adapters in this prototype are deterministic, reproducible adapters over typed schemas and read-only tools. Integrating an external LLM or LangGraph runtime behind `ResearchAgentAdapter` / `PortfolioAgentAdapter` requires separate model-governance approval and evaluation benchmarks.
5. **Short Selling, Margin Financing, Derivatives & Multi-Currency FX:** Paper account valuation and inventory checks assume long-only US equity/ETF spot positions denominated in `USD`.
6. **Distributed Multi-Node Deployment & PostgreSQL Runtime Driver:** While `docs/schema.sql` provides PostgreSQL-compatible DDL, the local prototype executes against single-node SQLite (`StateRepository`) and an in-process `EventBus`. Production deployment requires PostgreSQL, distributed locking, an external message broker, and mTLS service authentication.
7. **Regulatory Compliance / Production Readiness Claims:** Synthetic tests and failure drills verify control logic only and **never** imply live trading profitability, market-impact accuracy, or regulatory compliance.
