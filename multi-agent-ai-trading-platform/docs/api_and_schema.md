# API, CLI, Event Bus & Schema Documentation

## 1. FastAPI REST Endpoints

Base URL when launched locally via `.venv/bin/matp serve`: `http://127.0.0.1:8080`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Zero-CDN Operator Console SPA (`src/trading_platform/web/index.html`). |
| `GET` | `/api/health` | Service health, active `policy_version`, `execution_mode`, `kill_switch_active`, and audit chain validity. |
| `GET` | `/api/metrics` | Operational counts (runs, pending/approved/consumed approvals, orders, fills, audit entries). |
| `GET` | `/api/account` | Current paper account cash (`USD`) and positions snapshot. |
| `GET` | `/api/quotes` | Current synthetic market quotes with UTC timestamps. |
| `POST` | `/api/controls/execution-mode` | Authorized operator switch between `DISABLED` and `PAPER` (`LIVE` always returns HTTP `403 LIVE_TRADING_FORBIDDEN`). |
| `POST` | `/api/controls/kill-switch` | Authorized operator emergency kill switch (`active: true/false`). |
| `POST` | `/api/runs` | Trigger bounded multi-agent research -> portfolio -> risk -> policy cycle for a symbol. |
| `GET` | `/api/runs` | List recent orchestration runs. |
| `GET` | `/api/runs/{run_id}/provenance` | Full provenance graph: run, evidence items, tool calls, research reports, conflicts, proposal, risk assessments, approval, order, and fills. |
| `GET` | `/api/approvals` | List approval requests (optional `?status=PENDING|APPROVED|REJECTED|EXPIRED|CONSUMED`). |
| `POST` | `/api/approvals/{approval_id}/decide` | Operator exact-action approval/rejection requiring `actor_id`, `expected_action_hash`, and `reason`. |
| `POST` | `/api/oms/dispatch` | Idempotent paper order dispatch requiring `approval_id` and `idempotency_key`; repeats pre-dispatch risk checks. |
| `GET` | `/api/oms/orders` | List OMS order records. |
| `GET` | `/api/oms/fills` | List deduplicated fill records. |
| `GET` | `/api/audit` | List append-only hash-chained audit entries. |
| `GET` | `/api/audit/verify` | Recompute and verify SHA-256 hash chain from genesis. |

## 2. Structured Error Format

All domain violations (`PlatformError`) serialize deterministically:

```json
{
  "error_code": "APPROVAL_ALREADY_CONSUMED",
  "message": "Approval 'APR-...' was already consumed by order 'ORD-...'. Replay blocked.",
  "details": {"approval_id": "APR-...", "consumed_by_order_id": "ORD-..."}
}
```

## 3. CLI (`matp`)

```bash
.venv/bin/matp --db data/platform.sqlite3 status
.venv/bin/matp --db data/platform.sqlite3 run-cycle --symbol AAPL
.venv/bin/matp --db data/platform.sqlite3 set-mode --mode PAPER --actor ops_approver_1
.venv/bin/matp --db data/platform.sqlite3 approve --approval-id APR-... --actor ops_approver_1 --hash <64-hex>
.venv/bin/matp --db data/platform.sqlite3 dispatch --approval-id APR-... --idempotency-key IDEMP-001
.venv/bin/matp --db data/platform.sqlite3 verify-audit
.venv/bin/matp serve --host 127.0.0.1 --port 8080
```

## 4. Typed Event Bus Events

Published via `EventBus` and persisted in `domain_events`:
- `orchestrator.run_started`, `orchestrator.conflict_detected`, `orchestrator.run_completed`
- `tool.invoked`, `tool.denied`, `security.prompt_injection_detected`
- `approval.requested`, `approval.decided`
- `risk.pre_dispatch_rejected`
- `oms.order_dispatched`, `oms.order_timeout`, `oms.fill_applied`, `oms.duplicate_fill_ignored`
- `controls.execution_mode_changed`, `controls.kill_switch_changed`

## 5. Relational Schema

PostgreSQL-compatible DDL is committed at [docs/schema.sql](schema.sql) covering 13 tables (`platform_state`, `runs`, `evidence_items`, `tool_calls`, `research_reports`, `conflicts`, `proposals`, `risk_assessments`, `approvals`, `orders`, `fills`, `domain_events`, `audit_log`) with uniqueness constraints on `orders.idempotency_key`, `orders.client_order_id`, and `fills.broker_fill_id`. Local execution uses SQLite via `StateRepository` with identical logical tables.
