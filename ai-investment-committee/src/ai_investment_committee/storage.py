"""SQLite persistence layer for deliberations, replay traces, and hash-bound human approvals."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .errors import DuplicateApprovalError
from .models import (
    AgentBudget,
    AgentExecutionTrace,
    ChallengeRecord,
    Claim,
    DecisionRecord,
    DeliberationReplayTrace,
    HumanApprovalRecord,
    PortfolioReviewRecord,
    RiskCheckResult,
    RiskVerdictRecord,
    ThesisRecord,
    ToolCallTrace,
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deliberations (
    decision_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    config_id TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    seed INTEGER NOT NULL,
    status TEXT NOT NULL,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL,
    total_tool_calls INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    total_latency_ms INTEGER NOT NULL,
    total_cost_usd REAL NOT NULL,
    proposal_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    trace_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_approvals (
    approval_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    proposal_id TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    FOREIGN KEY(decision_id) REFERENCES deliberations(decision_id)
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    eval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    FOREIGN KEY(decision_id) REFERENCES deliberations(decision_id)
);
"""


def _deserialize_claim(raw: Dict[str, Any]) -> Claim:
    return Claim(
        claim_id=raw["claim_id"],
        author_role=raw["author_role"],
        statement=raw["statement"],
        evidence_ids=tuple(raw["evidence_ids"]),
        is_uncertain=bool(raw["is_uncertain"]),
        uncertainty_reason=raw.get("uncertainty_reason"),
        citation_status=raw["citation_status"],
        fabricated_evidence_ids=tuple(raw.get("fabricated_evidence_ids", [])),
    )


def deserialize_trace(raw: Dict[str, Any]) -> DeliberationReplayTrace:
    dec = raw["decision"]
    thesis_raw = dec["thesis"]
    thesis = ThesisRecord(
        proposal_id=thesis_raw["proposal_id"],
        ticker=thesis_raw["ticker"],
        stance=thesis_raw["stance"],
        conviction_score=float(thesis_raw["conviction_score"]),
        summary=thesis_raw["summary"],
        claims=tuple(_deserialize_claim(c) for c in thesis_raw["claims"]),
        injection_flags=tuple(thesis_raw.get("injection_flags", [])),
    )
    chal_raw = dec["challenge"]
    challenge = ChallengeRecord(
        proposal_id=chal_raw["proposal_id"],
        ticker=chal_raw["ticker"],
        dissent_level=chal_raw["dissent_level"],
        dissent_score=float(chal_raw["dissent_score"]),
        challenged_claim_ids=tuple(chal_raw["challenged_claim_ids"]),
        summary=chal_raw["summary"],
        claims=tuple(_deserialize_claim(c) for c in chal_raw["claims"]),
        injection_flags=tuple(chal_raw.get("injection_flags", [])),
    )
    pf_raw = dec["portfolio_review"]
    portfolio_review = PortfolioReviewRecord(
        proposal_id=pf_raw["proposal_id"],
        ticker=pf_raw["ticker"],
        sizing_recommendation=pf_raw["sizing_recommendation"],
        pro_forma_metrics={k: float(v) for k, v in pf_raw["pro_forma_metrics"].items()},
        summary=pf_raw["summary"],
        claims=tuple(_deserialize_claim(c) for c in pf_raw["claims"]),
    )
    rv_raw = dec["risk_verdict"]
    risk_verdict = RiskVerdictRecord(
        proposal_id=rv_raw["proposal_id"],
        policy_id=rv_raw["policy_id"],
        verdict=rv_raw["verdict"],
        non_overridable=bool(rv_raw["non_overridable"]),
        checks=tuple(
            RiskCheckResult(
                rule_id=ch["rule_id"],
                passed=bool(ch["passed"]),
                observed_value=ch["observed_value"],
                limit_value=ch["limit_value"],
                unit=ch["unit"],
                message=ch["message"],
            )
            for ch in rv_raw["checks"]
        ),
        violated_rules=tuple(rv_raw["violated_rules"]),
        metrics={k: float(v) for k, v in rv_raw["metrics"].items()},
        rationale=rv_raw["rationale"],
    )
    ha_raw = dec.get("human_approval")
    human_approval = HumanApprovalRecord.model_validate(ha_raw) if ha_raw else None
    decision = DecisionRecord(
        schema_version=dec["schema_version"],
        decision_id=dec["decision_id"],
        proposal_id=dec["proposal_id"],
        proposal_hash=dec["proposal_hash"],
        config_id=dec["config_id"],
        config_hash=dec["config_hash"],
        seed=int(dec["seed"]),
        status=dec["status"],
        execution_capability=dec["execution_capability"],
        thesis=thesis,
        challenge=challenge,
        portfolio_review=portfolio_review,
        risk_verdict=risk_verdict,
        human_approval=human_approval,
        notes=tuple(dec.get("notes", [])),
    )
    agent_traces = tuple(
        AgentExecutionTrace(
            role=t["role"],
            allowed_tools=tuple(t["allowed_tools"]),
            budget=AgentBudget.model_validate(t["budget"]),
            tool_calls_used=int(t["tool_calls_used"]),
            tokens_used=int(t["tokens_used"]),
            latency_ms=int(t["latency_ms"]),
            cost_usd=float(t["cost_usd"]),
            tool_calls=tuple(
                ToolCallTrace(
                    role=tc["role"],
                    tool_name=tc["tool_name"],
                    arguments=dict(tc["arguments"]),
                    status=tc["status"],
                    latency_ms=int(tc["latency_ms"]),
                    tokens_used=int(tc["tokens_used"]),
                    cost_usd=float(tc["cost_usd"]),
                )
                for tc in t["tool_calls"]
            ),
            injection_attempts_flagged=tuple(t.get("injection_attempts_flagged", [])),
        )
        for t in raw["agent_traces"]
    )
    return DeliberationReplayTrace(
        schema_version=raw["schema_version"],
        decision_id=raw["decision_id"],
        proposal_id=raw["proposal_id"],
        proposal_hash=raw["proposal_hash"],
        config_hash=raw["config_hash"],
        seed=int(raw["seed"]),
        created_at=raw["created_at"],
        decision=decision,
        agent_traces=agent_traces,
        total_tool_calls=int(raw["total_tool_calls"]),
        total_tokens=int(raw["total_tokens"]),
        total_latency_ms=int(raw["total_latency_ms"]),
        total_cost_usd=float(raw["total_cost_usd"]),
        runtime_metadata=dict(raw.get("runtime_metadata", {})),
    )


class DeliberationStore:
    """SQLite-backed storage for committee deliberations, approvals, and replay."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    def save_deliberation(
        self,
        *,
        trace: DeliberationReplayTrace,
        proposal_dict: Dict[str, Any],
        config_dict: Dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO deliberations (
                    decision_id, proposal_id, proposal_hash, config_id, config_hash,
                    seed, status, verdict, created_at, total_tool_calls, total_tokens,
                    total_latency_ms, total_cost_usd, proposal_json, config_json, trace_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.decision_id,
                    trace.proposal_id,
                    trace.proposal_hash,
                    trace.decision.config_id,
                    trace.config_hash,
                    trace.seed,
                    trace.decision.status,
                    trace.decision.risk_verdict.verdict,
                    trace.created_at,
                    trace.total_tool_calls,
                    trace.total_tokens,
                    trace.total_latency_ms,
                    trace.total_cost_usd,
                    json.dumps(proposal_dict, sort_keys=True),
                    json.dumps(config_dict, sort_keys=True),
                    json.dumps(trace.model_dump(), sort_keys=True),
                ),
            )

    def get_deliberation(
        self, decision_id: str
    ) -> Optional[Tuple[DeliberationReplayTrace, Dict[str, Any], Dict[str, Any]]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT proposal_json, config_json, trace_json FROM deliberations WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        return (
            deserialize_trace(json.loads(row["trace_json"])),
            json.loads(row["proposal_json"]),
            json.loads(row["config_json"]),
        )

    def list_deliberations(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT decision_id, proposal_id, proposal_hash, status, verdict,
                       created_at, total_tool_calls, total_tokens, total_cost_usd
                FROM deliberations
                ORDER BY created_at ASC, decision_id ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def seen_approval_ids(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT approval_id FROM human_approvals").fetchall()
        return [str(r["approval_id"]) for r in rows]

    def record_human_approval(
        self,
        *,
        updated_trace: DeliberationReplayTrace,
        approval: HumanApprovalRecord,
    ) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO human_approvals (
                        approval_id, decision_id, proposal_id, proposal_hash,
                        reviewer_id, decision, rationale, approved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval.approval_id,
                        updated_trace.decision_id,
                        approval.proposal_id,
                        approval.proposal_hash,
                        approval.reviewer_id,
                        approval.decision,
                        approval.rationale,
                        approval.approved_at,
                    ),
                )
                conn.execute(
                    """
                    UPDATE deliberations
                    SET status = ?, trace_json = ?
                    WHERE decision_id = ?
                    """,
                    (
                        updated_trace.decision.status,
                        json.dumps(updated_trace.model_dump(), sort_keys=True),
                        updated_trace.decision_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateApprovalError(
                f"Database constraint rejected duplicate approval '{approval.approval_id}' for decision '{updated_trace.decision_id}'.",
                details={"approval_id": approval.approval_id, "decision_id": updated_trace.decision_id},
            ) from exc

    def save_evaluation(self, *, decision_id: str, evaluated_at: str, metrics: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_runs (decision_id, evaluated_at, metrics_json)
                VALUES (?, ?, ?)
                """,
                (decision_id, evaluated_at, json.dumps(metrics, sort_keys=True)),
            )
