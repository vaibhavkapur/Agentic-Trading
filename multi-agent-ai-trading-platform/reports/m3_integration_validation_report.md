# Milestone M3 Report — Integration & Validation

## Scope Delivered
- Implemented `IndependentRiskService` (`src/trading_platform/agents/risk_agent.py`) executing deterministic symbol allowlist, quote freshness (`<= 60s`), price collar (`<= 250 bps`), order notional, % NAV, cash buffer / sell inventory, position concentration, and gross exposure checks at **both** `PRE_APPROVAL` and `PRE_DISPATCH`.
- Implemented `PolicyEngine` (`src/trading_platform/policy/engine.py`) and `ExactActionApprovalService` (`src/trading_platform/policy/approvals.py`) enforcing `DISABLED` default execution mode, `LIVE_TRADING_FORBIDDEN`, RBAC/maker-checker approvals, SHA-256 exact parameter binding, TTL expiration, and single-use consumption ([ADR-002](../docs/adr/ADR-002-deterministic-policy-and-exact-action-approvals.md)).
- Implemented `IdempotentOMS` (`src/trading_platform/execution/oms.py`) and `SimulatedPaperBroker` (`src/trading_platform/execution/broker.py`) with `idempotency_key` deduplication, `PRE_DISPATCH` risk re-check, broker timeout reconciliation, and `broker_fill_id` fill deduplication ([ADR-003](../docs/adr/ADR-003-idempotent-oms-and-pre-dispatch-risk.md)).
- Delivered FastAPI REST API (`src/trading_platform/api/app.py`), zero-CDN Operator Console (`src/trading_platform/web/index.html`), and `matp` CLI (`src/trading_platform/cli.py`).

## Verification Evidence
- Integration tests: `tests/integration/test_orchestrator_and_oms_flow.py`, `tests/integration/test_fastapi_console_and_api.py`, `tests/integration/test_persistence_and_restart.py` (4 passed).
- Unit tests: `tests/unit/test_policy_and_approvals.py` (3 passed), `tests/unit/test_risk_and_audit_chain.py` (3 passed).
- Paper demo evidence: [evidence/demo_evidence.json](evidence/demo_evidence.json) (`PASSED`, `broker_order_count=1`, `risk_stages_executed=["PRE_APPROVAL", "PRE_DISPATCH"]`, `audit_chain_valid=true`).
