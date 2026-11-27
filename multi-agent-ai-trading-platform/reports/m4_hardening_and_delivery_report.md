# Milestone M4 Report — Hardening & Delivery

## Scope Delivered
- Verified all 7 failure scenarios mandated by `plan.md` Section 5 plus multi-leg partial fills and cold process restart recovery in both automated pytest scenarios (`tests/scenarios/test_failure_scenarios.py`) and standalone reproducible drill (`scripts/scenario_drill.py`).
- Delivered reproducible setup (`scripts/setup.sh`), one-command validation (`scripts/validate.sh`), end-to-end paper demo (`scripts/demo.py`), operator runbook ([docs/runbook.md](../docs/runbook.md)), explicit unsupported features list ([docs/unsupported_features.md](../docs/unsupported_features.md)), and pinned dependency lockfile ([uv.lock](../uv.lock)).

## Failure Scenario Drill Summary

| # | Scenario | Verified Outcome | Raw Evidence |
|---|---|---|---|
| 1 | Injected instructions in news | Quarantined by `PromptInjectionGuard` (6 rules matched), zero broker orders, agent stayed read-only | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 2 | Malicious tool arguments | Rejected with `MALICIOUS_TOOL_ARGUMENTS` and `AGENT_EXECUTION_FORBIDDEN`, logged to `tool_calls` & `audit_log` | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 3 | Approval replay & tampering | Parameter mutation blocked (`APPROVAL_PARAMETER_MISMATCH`); consumed replay blocked (`APPROVAL_ALREADY_CONSUMED`); 1 broker order total | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 4 | Conflicting agents | Bullish vs bearish desks detected; run status `BLOCKED_CONFLICT`; proposal blocked under `BLOCK_AND_ESCALATE` | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 5 | Stale quote | Blocked at `PRE_APPROVAL` (`BLOCKED_RISK`) and again at `PRE_DISPATCH` (`STALE_MARKET_DATA`) when quote aged after approval | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 6 | Broker timeout | Marked `UNCERTAIN_TIMEOUT`; retry with same `idempotency_key` reconciled broker fill without duplicate submission (`broker_submit_attempts=1`) | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 7 | Duplicate fill & partial fill | 50% fill -> duplicate leg 1 ignored (`duplicate_leg1_accepted=false`) -> leg 2 completed order (`FILLED`, 20/20) | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |
| 8 | Cold restart recovery | Persisted SQLite state reloaded pending approvals, filled orders, idempotency keys, cash/positions, and unbroken SHA-256 audit chain | [scenario_drill_evidence.json](evidence/scenario_drill_evidence.json) |

## Baseline Local Environment Measurements
- Environment: macOS arm64, Python 3.12.15, SQLite in-memory / local disk, synthetic fixtures (not representative of production network/PostgreSQL latency).
- Full pytest suite (25 tests): `0.19s` (`25 passed`).
- Paper trading demo (`scripts/demo.py`): `~2.7 ms`.
- 8-scenario failure & restart drill (`scripts/scenario_drill.py`): `~26 ms`.
