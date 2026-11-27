"""Durable SQLite state store with PostgreSQL-compatible schema and hash-chained audit log."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from trading_platform.domain.contracts import (
    AccountSnapshot,
    ApprovalRequest,
    AuditEntry,
    ConflictRecord,
    DomainEvent,
    EvidenceItem,
    FillRecord,
    OrderRecord,
    PortfolioProposal,
    PositionSnapshot,
    ResearchReport,
    RiskAssessment,
    RunRecord,
    ToolCallRecord,
)
from trading_platform.domain.types import (
    ApprovalStatus,
    ExecutionMode,
    canonical_hash,
    canonical_json,
    utc_now,
)

GENESIS_HASH = "0" * 64

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS platform_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT,
    kind TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    tainted_injection_detected INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    timestamp_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stance TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    exact_action_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    assessment_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    exact_action_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    client_order_id TEXT NOT NULL UNIQUE,
    approval_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    broker_fill_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    run_id TEXT,
    timestamp_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp_utc TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    run_id TEXT,
    entity_type TEXT,
    entity_id TEXT,
    evidence_ids_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
"""


class StateRepository:
    """Thread-safe durable SQLite repository for shared multi-agent state and provenance."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- Platform runtime state (execution_mode, kill_switch, account state) ---

    def get_state_value(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM platform_state WHERE key = ?",
                (key,),
            ).fetchone()
            return json.loads(row["value_json"]) if row else None

    def set_state_value(self, key: str, value: Any) -> None:
        with self._lock:
            now = utc_now().isoformat().replace("+00:00", "Z")
            self._conn.execute(
                """
                INSERT INTO platform_state(key, value_json, updated_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (key, canonical_json(value), now),
            )
            self._conn.commit()

    def get_execution_mode(self, default: ExecutionMode = ExecutionMode.DISABLED) -> ExecutionMode:
        val = self.get_state_value("execution_mode")
        return ExecutionMode(val) if val else default

    def set_execution_mode(self, mode: ExecutionMode) -> None:
        self.set_state_value("execution_mode", mode.value)

    def get_kill_switch(self) -> bool:
        val = self.get_state_value("kill_switch")
        return bool(val) if val is not None else False

    def set_kill_switch(self, active: bool) -> None:
        self.set_state_value("kill_switch", bool(active))

    def save_account_snapshot(self, snapshot: AccountSnapshot) -> None:
        self.set_state_value("account_snapshot", json.loads(snapshot.model_dump_json()))

    def load_account_snapshot(self) -> AccountSnapshot | None:
        val = self.get_state_value("account_snapshot")
        if val is None:
            return None
        return AccountSnapshot.model_validate(val)

    def apply_fill_to_account(self, fill: FillRecord) -> AccountSnapshot:
        """Atomically update persisted paper account cash & positions for a deduplicated fill."""
        with self._lock:
            account = self.load_account_snapshot()
            if account is None:
                raise RuntimeError("Account snapshot must be initialized before applying fills")
            positions = dict(account.positions)
            existing = positions.get(fill.symbol)
            notional = (fill.price * Decimal(fill.quantity)).quantize(Decimal("0.01"))
            if fill.side.value == "BUY":
                new_cash = (account.cash_usd - notional).quantize(Decimal("0.01"))
                if new_cash < Decimal("0"):
                    new_cash = Decimal("0.00")
                if existing is None or existing.quantity == 0:
                    positions[fill.symbol] = PositionSnapshot(
                        symbol=fill.symbol,
                        quantity=fill.quantity,
                        avg_cost_usd=fill.price,
                    )
                else:
                    total_qty = existing.quantity + fill.quantity
                    total_cost = existing.avg_cost_usd * Decimal(existing.quantity) + notional
                    avg_cost = (total_cost / Decimal(total_qty)).quantize(Decimal("0.0001"))
                    positions[fill.symbol] = PositionSnapshot(
                        symbol=fill.symbol,
                        quantity=total_qty,
                        avg_cost_usd=avg_cost,
                    )
            else:
                new_cash = (account.cash_usd + notional).quantize(Decimal("0.01"))
                if existing is not None:
                    rem_qty = max(0, existing.quantity - fill.quantity)
                    if rem_qty == 0:
                        positions.pop(fill.symbol, None)
                    else:
                        positions[fill.symbol] = PositionSnapshot(
                            symbol=fill.symbol,
                            quantity=rem_qty,
                            avg_cost_usd=existing.avg_cost_usd,
                        )
            updated = AccountSnapshot(
                account_id=account.account_id,
                cash_usd=new_cash,
                positions=positions,
                as_of_utc=fill.executed_at_utc,
            )
            self.save_account_snapshot(updated)
            return updated

    # --- Runs ---

    def save_run(self, run: RunRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runs(run_id, symbol, status, policy_version, started_at_utc, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json
                """,
                (
                    run.run_id,
                    run.symbol,
                    run.status.value,
                    run.policy_version,
                    run.started_at_utc.isoformat().replace("+00:00", "Z"),
                    run.model_dump_json(),
                ),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return RunRecord.model_validate_json(row["payload_json"]) if row else None

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM runs ORDER BY started_at_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [RunRecord.model_validate_json(r["payload_json"]) for r in rows]

    # --- Evidence ---

    def save_evidence(self, item: EvidenceItem) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO evidence_items(
                    evidence_id, run_id, symbol, kind, content_hash,
                    tainted_injection_detected, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.evidence_id,
                    item.run_id,
                    item.symbol,
                    item.kind,
                    item.content_hash,
                    1 if item.tainted_injection_detected else 0,
                    item.model_dump_json(),
                ),
            )
            self._conn.commit()

    def list_evidence_for_run(self, run_id: str) -> list[EvidenceItem]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM evidence_items WHERE run_id = ? ORDER BY rowid ASC",
                (run_id,),
            ).fetchall()
            return [EvidenceItem.model_validate_json(r["payload_json"]) for r in rows]

    # --- Tool calls ---

    def save_tool_call(self, record: ToolCallRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO tool_calls(
                    call_id, run_id, agent_id, tool_name, allowed, timestamp_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.call_id,
                    record.run_id,
                    record.agent_id,
                    record.tool_name,
                    1 if record.allowed else 0,
                    record.timestamp_utc.isoformat().replace("+00:00", "Z"),
                    record.model_dump_json(),
                ),
            )
            self._conn.commit()

    def list_tool_calls_for_run(self, run_id: str) -> list[ToolCallRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM tool_calls WHERE run_id = ? ORDER BY rowid ASC",
                (run_id,),
            ).fetchall()
            return [ToolCallRecord.model_validate_json(r["payload_json"]) for r in rows]

    # --- Research reports & Conflicts ---

    def save_research_report(self, report: ResearchReport) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO research_reports(
                    report_id, run_id, agent_id, symbol, stance, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.run_id,
                    report.agent_id,
                    report.symbol,
                    report.stance.value,
                    report.model_dump_json(),
                ),
            )
            self._conn.commit()

    def list_research_reports_for_run(self, run_id: str) -> list[ResearchReport]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM research_reports WHERE run_id = ? ORDER BY rowid ASC",
                (run_id,),
            ).fetchall()
            return [ResearchReport.model_validate_json(r["payload_json"]) for r in rows]

    def save_conflict(self, conflict: ConflictRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO conflicts(conflict_id, run_id, symbol, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conflict.conflict_id,
                    conflict.run_id,
                    conflict.symbol,
                    conflict.model_dump_json(),
                ),
            )
            self._conn.commit()

    def list_conflicts_for_run(self, run_id: str) -> list[ConflictRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM conflicts WHERE run_id = ? ORDER BY rowid ASC",
                (run_id,),
            ).fetchall()
            return [ConflictRecord.model_validate_json(r["payload_json"]) for r in rows]

    # --- Proposals ---

    def save_proposal(self, proposal: PortfolioProposal) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO proposals(
                    proposal_id, run_id, symbol, policy_version, exact_action_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    proposal.run_id,
                    proposal.order_intent.symbol,
                    proposal.policy_version,
                    proposal.exact_action_hash(),
                    proposal.model_dump_json(),
                ),
            )
            self._conn.commit()

    def get_proposal(self, proposal_id: str) -> PortfolioProposal | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            return PortfolioProposal.model_validate_json(row["payload_json"]) if row else None

    def list_proposals(self, limit: int = 50) -> list[PortfolioProposal]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM proposals ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [PortfolioProposal.model_validate_json(r["payload_json"]) for r in rows]

    # --- Risk assessments ---

    def save_risk_assessment(self, assessment: RiskAssessment) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO risk_assessments(
                    assessment_id, run_id, proposal_id, stage, status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    assessment.run_id,
                    assessment.proposal_id,
                    assessment.stage,
                    assessment.status.value,
                    assessment.model_dump_json(),
                ),
            )
            self._conn.commit()

    def get_risk_assessment(self, assessment_id: str) -> RiskAssessment | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM risk_assessments WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
            return RiskAssessment.model_validate_json(row["payload_json"]) if row else None

    def list_risk_assessments_for_proposal(self, proposal_id: str) -> list[RiskAssessment]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM risk_assessments WHERE proposal_id = ? ORDER BY rowid ASC",
                (proposal_id,),
            ).fetchall()
            return [RiskAssessment.model_validate_json(r["payload_json"]) for r in rows]

    # --- Approvals ---

    def save_approval(self, approval: ApprovalRequest) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, run_id, proposal_id, exact_action_hash,
                    status, expires_at_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json
                """,
                (
                    approval.approval_id,
                    approval.run_id,
                    approval.proposal_id,
                    approval.exact_action_hash,
                    approval.status.value,
                    approval.expires_at_utc.isoformat().replace("+00:00", "Z"),
                    approval.model_dump_json(),
                ),
            )
            self._conn.commit()

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return ApprovalRequest.model_validate_json(row["payload_json"]) if row else None

    def list_approvals(self, status: ApprovalStatus | None = None) -> list[ApprovalRequest]:
        with self._lock:
            if status is not None:
                rows = self._conn.execute(
                    "SELECT payload_json FROM approvals WHERE status = ? ORDER BY rowid DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT payload_json FROM approvals ORDER BY rowid DESC"
                ).fetchall()
            return [ApprovalRequest.model_validate_json(r["payload_json"]) for r in rows]

    # --- Orders & Fills (Idempotent) ---

    def save_order(self, order: OrderRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO orders(
                    order_id, idempotency_key, client_order_id, approval_id, status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json
                """,
                (
                    order.order_id,
                    order.idempotency_key,
                    order.client_order_id,
                    order.approval_id,
                    order.status.value,
                    order.model_dump_json(),
                ),
            )
            self._conn.commit()

    def get_order(self, order_id: str) -> OrderRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return OrderRecord.model_validate_json(row["payload_json"]) if row else None

    def get_order_by_idempotency_key(self, idempotency_key: str) -> OrderRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM orders WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return OrderRecord.model_validate_json(row["payload_json"]) if row else None

    def get_order_by_client_order_id(self, client_order_id: str) -> OrderRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            return OrderRecord.model_validate_json(row["payload_json"]) if row else None

    def list_orders(self, limit: int = 100) -> list[OrderRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM orders ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [OrderRecord.model_validate_json(r["payload_json"]) for r in rows]

    def save_fill_if_new(self, fill: FillRecord) -> bool:
        """Insert a fill idempotently by unique broker_fill_id. Returns True if newly inserted."""
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO fills(fill_id, broker_fill_id, order_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (fill.fill_id, fill.broker_fill_id, fill.order_id, fill.model_dump_json()),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def list_fills_for_order(self, order_id: str) -> list[FillRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM fills WHERE order_id = ? ORDER BY rowid ASC",
                (order_id,),
            ).fetchall()
            return [FillRecord.model_validate_json(r["payload_json"]) for r in rows]

    def list_fills(self, limit: int = 200) -> list[FillRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM fills ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [FillRecord.model_validate_json(r["payload_json"]) for r in rows]

    # --- Domain Events ---

    def save_event(self, event: DomainEvent) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO domain_events(
                    event_id, event_type, run_id, timestamp_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.run_id,
                    event.timestamp_utc.isoformat().replace("+00:00", "Z"),
                    event.model_dump_json(),
                ),
            )
            self._conn.commit()

    def list_events(self, limit: int = 100) -> list[DomainEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM domain_events ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [DomainEvent.model_validate_json(r["payload_json"]) for r in rows]

    # --- Append-Only Hash-Chained Audit Log ---

    def append_audit(
        self,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        outcome: str,
        policy_version: str,
        run_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        evidence_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        timestamp_utc: datetime | None = None,
    ) -> AuditEntry:
        with self._lock:
            row = self._conn.execute(
                "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = row["entry_hash"] if row else GENESIS_HASH
            next_seq = (row["seq"] + 1) if row else 1
            event_id = f"AUD-{uuid4().hex[:12].upper()}"
            ts = timestamp_utc or utc_now()
            ts_str = ts.isoformat().replace("+00:00", "Z")
            ev_ids = sorted(set(evidence_ids or []))
            body = payload or {}
            hash_material = {
                "seq": next_seq,
                "event_id": event_id,
                "timestamp_utc": ts_str,
                "actor_id": actor_id,
                "actor_role": actor_role,
                "action": action,
                "outcome": outcome,
                "policy_version": policy_version,
                "run_id": run_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "evidence_ids": ev_ids,
                "payload": body,
                "prev_hash": prev_hash,
            }
            entry_hash = canonical_hash(hash_material)
            self._conn.execute(
                """
                INSERT INTO audit_log(
                    seq, event_id, timestamp_utc, actor_id, actor_role, action, outcome,
                    policy_version, run_id, entity_type, entity_id, evidence_ids_json,
                    payload_json, prev_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_seq,
                    event_id,
                    ts_str,
                    actor_id,
                    actor_role,
                    action,
                    outcome,
                    policy_version,
                    run_id,
                    entity_type,
                    entity_id,
                    canonical_json(ev_ids),
                    canonical_json(body),
                    prev_hash,
                    entry_hash,
                ),
            )
            self._conn.commit()
            return AuditEntry(
                seq=next_seq,
                event_id=event_id,
                timestamp_utc=ts,
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                outcome=outcome,
                policy_version=policy_version,
                run_id=run_id,
                entity_type=entity_type,
                entity_id=entity_id,
                evidence_ids=ev_ids,
                payload=body,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )

    def list_audit_entries(self, limit: int = 200) -> list[AuditEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_log ORDER BY seq ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_audit(r) for r in rows]

    def verify_audit_chain(self) -> tuple[bool, int, str | None]:
        """Recompute SHA-256 chain from genesis. Returns (valid, count, failure_reason)."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()
            expected_prev = GENESIS_HASH
            for idx, row in enumerate(rows, start=1):
                if row["seq"] != idx:
                    return False, len(rows), f"Sequence gap at seq={row['seq']} expected={idx}"
                if row["prev_hash"] != expected_prev:
                    return False, len(rows), f"Broken prev_hash at seq={row['seq']}"
                hash_material = {
                    "seq": row["seq"],
                    "event_id": row["event_id"],
                    "timestamp_utc": row["timestamp_utc"],
                    "actor_id": row["actor_id"],
                    "actor_role": row["actor_role"],
                    "action": row["action"],
                    "outcome": row["outcome"],
                    "policy_version": row["policy_version"],
                    "run_id": row["run_id"],
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "evidence_ids": json.loads(row["evidence_ids_json"]),
                    "payload": json.loads(row["payload_json"]),
                    "prev_hash": row["prev_hash"],
                }
                recomputed = canonical_hash(hash_material)
                if recomputed != row["entry_hash"]:
                    return False, len(rows), f"Hash mismatch at seq={row['seq']}"
                expected_prev = row["entry_hash"]
            return True, len(rows), None

    def _row_to_audit(self, row: sqlite3.Row) -> AuditEntry:
        return AuditEntry(
            seq=row["seq"],
            event_id=row["event_id"],
            timestamp_utc=datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")),
            actor_id=row["actor_id"],
            actor_role=row["actor_role"],
            action=row["action"],
            outcome=row["outcome"],
            policy_version=row["policy_version"],
            run_id=row["run_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            evidence_ids=json.loads(row["evidence_ids_json"]),
            payload=json.loads(row["payload_json"]),
            prev_hash=row["prev_hash"],
            entry_hash=row["entry_hash"],
        )
