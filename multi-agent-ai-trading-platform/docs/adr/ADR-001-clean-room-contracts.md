# ADR-001: Clean-Room Typed Domain Contracts

- **Status:** Accepted
- **Date:** 2026-11-27

## Context
`plan.md` Section 2 lists three external personal prototype repositories (`01-agentic-trading-platform`, `15-agentic-trading-guardrails`, `14-ai-quant-research-agent`) and directs that if repository access, licensing, or SAAT background-IP ownership is unresolved, the team must implement against clean, documented contracts instead of copying unverified code.

## Decision
Implement all domain contracts (`src/trading_platform/domain/contracts.py`), versioned configuration (`config.py`), tool boundaries (`tools/gateway.py`), and adapter interfaces (`agents/`, `execution/broker.py`) clean-room using Pydantic v2 (`extra="forbid"`), `Decimal` monetary precision, explicit `USD` units, and timezone-aware UTC timestamps.

## Consequences
- Zero ambiguous IP or third-party licensing provenance.
- Future integration with SAAT's existing OMS, pre-trade risk engine, or approved LLM/LangGraph research agents only requires implementing the documented adapter protocols (`ResearchAgentAdapter`, `PaperBroker`, `StateRepository`).
