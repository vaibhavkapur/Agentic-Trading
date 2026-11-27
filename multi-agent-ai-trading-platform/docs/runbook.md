# Operations Runbook

Run the commands in this guide from `multi-agent-ai-trading-platform/`. See the [project README](../README.md) for prerequisites.

## 1. Startup & Health Verification

```bash
./scripts/setup.sh
./scripts/validate.sh
.venv/bin/matp serve --host 127.0.0.1 --port 8080
```

Verify health before any paper activity:
- `GET /api/health` must return `"status": "ok"`, `"audit_chain_valid": true`, and `"execution_mode": "DISABLED"`.
- Confirm `policy_version` matches the reviewed version in `config/platform_config.json` (`POL-MATP-2026.1`).

## 2. Standard Operator Workflow (Paper Mode)

1. **Enable Paper Execution:** Only an authorized operator (`ops_approver_1`, `ops_approver_2`, or `cio_reviewer`) may switch `execution_mode` from `DISABLED` to `PAPER` via `POST /api/controls/execution-mode` or the Operator Console.
2. **Run Multi-Agent Cycle:** Trigger `POST /api/runs` for an allowlisted symbol. The orchestrator collects read-only evidence, runs research & portfolio agents, checks for conflicts, executes `PRE_APPROVAL` independent risk checks, and creates a `PENDING` `ApprovalRequest`.
3. **Review Provenance & Approve Exact Action:** Inspect `/api/runs/{run_id}/provenance` (evidence hashes, injection warnings, risk checks, exact `OrderIntent`). Submit `POST /api/approvals/{approval_id}/decide` supplying the exact `exact_action_hash` before `expires_at_utc`.
4. **Idempotent Dispatch:** Submit `POST /api/oms/dispatch` with a stable `idempotency_key`. The OMS re-runs `PRE_DISPATCH` risk validation, consumes the single-use approval, dispatches to the paper broker, and applies deduplicated fills.

## 3. Incident Response Playbooks

| Incident / Failure Mode | Detection Signal | Safe Default Behavior | Operator Response |
|---|---|---|---|
| **Prompt injection in news** | `security.prompt_injection_detected` event; `tainted_injection_detected=true` on `EvidenceItem` | Tainted text quarantined & excluded from scoring; agents remain strictly read-only | Inspect quarantined evidence in provenance; disable untrusted feed source if recurring. |
| **Malicious tool arguments / privilege probe** | `tool.denied` event; `MALICIOUS_TOOL_ARGUMENTS` or `AGENT_EXECUTION_FORBIDDEN` | Tool call blocked before execution and logged in `tool_calls` & `audit_log` | Review `tool_calls` for run; halt suspicious agent adapter version. |
| **Approval replay or parameter tampering** | `APPROVAL_ALREADY_CONSUMED` or `APPROVAL_PARAMETER_MISMATCH` | Dispatch rejected; zero duplicate broker orders | Audit caller identity; verify `orders` table for original consumed order. |
| **Conflicting agent stances** | Run status `BLOCKED_CONFLICT`; `orchestrator.conflict_detected` | Proposal creation blocked under `BLOCK_AND_ESCALATE` policy | Review opposing `ResearchReport` theses & evidence; keep no-trade unless manually resolved. |
| **Stale market quote** | `STALE_MARKET_DATA` in `PRE_APPROVAL` or `PRE_DISPATCH` risk check | Proposal or dispatch blocked; order never sent to broker | Verify quote feed timestamps & clock sync; wait for fresh quotes before re-running. |
| **Broker timeout** | `oms.order_timeout`; order status `UNCERTAIN_TIMEOUT` | OMS refuses blind re-submission | Retry dispatch with the **exact same `idempotency_key`** (or call `reconcile_uncertain_order`) to query broker by `client_order_id`. |
| **Duplicate fill webhook** | `oms.duplicate_fill_ignored`; `OMS_DUPLICATE_FILL_IGNORED` in audit | Ignored idempotently by `broker_fill_id`; cash & positions unchanged | No corrective ledger action needed; confirm broker webhook retry health. |
| **Process crash / restart** | Process restart against persisted SQLite file | Persisted approvals, orders, idempotency keys, account state & audit chain reload intact | Call `GET /api/audit/verify` and `GET /api/oms/orders` to inspect any `UNCERTAIN_TIMEOUT` orders before resuming. |

## 4. Emergency Kill Switch

To halt all order dispatch immediately:
- Operator Console: click **Kill Switch ON**, or
- API: `POST /api/controls/kill-switch` with `{"active": true, "actor_id": "ops_approver_1", "reason": "..."}`.

While active, every OMS dispatch fails closed with `KILL_SWITCH_ACTIVE` (`409`), and audit logs record every blocked attempt.
