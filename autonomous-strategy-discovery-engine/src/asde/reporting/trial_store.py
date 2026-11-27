"""Append-only persistent trial ledger (SQLite + JSONL export) accounting for every trial."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional, Protocol

from asde.types import TrialRecord


class TrialStore(Protocol):
    """Contract for persisting every trial record (PostgreSQL adapter can implement this)."""

    def record_trial(self, trial: TrialRecord) -> None:
        ...

    def record_many(self, trials: List[TrialRecord]) -> None:
        ...

    def list_trials(self, *, run_id: Optional[str] = None, phase: Optional[str] = None) -> List[TrialRecord]:
        ...

    def accounting_summary(self, *, run_id: str) -> Dict[str, int]:
        ...


class SqliteTrialStore:
    """Zero-dependency SQLite trial store with JSONL audit export."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trials (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    trial_id TEXT UNIQUE NOT NULL,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    is_baseline INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    split_manifest_hash TEXT NOT NULL,
                    cost_scenario TEXT NOT NULL,
                    cost_scenario_hash TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def record_trial(self, trial: TrialRecord) -> None:
        self.record_many([trial])

    def record_many(self, trials: List[TrialRecord]) -> None:
        if not trials:
            return
        with self._connect() as conn:
            for t in trials:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trials (
                        trial_id, run_id, strategy_id, family, is_baseline, phase, status,
                        seed, dataset_fingerprint, split_manifest_hash, cost_scenario,
                        cost_scenario_hash, created_at_utc, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.trial_id,
                        t.run_id,
                        t.strategy_id,
                        t.family,
                        1 if t.is_baseline else 0,
                        t.phase,
                        t.status,
                        t.seed,
                        t.dataset_fingerprint,
                        t.split_manifest_hash,
                        t.cost_scenario,
                        t.cost_scenario_hash,
                        t.created_at_utc,
                        json.dumps(t.to_dict(), sort_keys=True),
                    ),
                )
            conn.commit()

    def list_trials(self, *, run_id: Optional[str] = None, phase: Optional[str] = None) -> List[TrialRecord]:
        query = "SELECT payload_json FROM trials"
        clauses: List[str] = []
        params: List[str] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if phase is not None:
            clauses.append("phase = ?")
            params.append(phase)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY seq ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [TrialRecord(**json.loads(r[0])) for r in rows]

    def accounting_summary(self, *, run_id: str) -> Dict[str, int]:
        trials = self.list_trials(run_id=run_id)
        summary = {
            "total_trials_recorded": len(trials),
            "candidate_trials_total": sum(1 for t in trials if not t.is_baseline),
            "baseline_trials_total": sum(1 for t in trials if t.is_baseline),
            "inner_tuning_trials": sum(1 for t in trials if t.phase == "inner_tuning"),
            "walk_forward_trials": sum(1 for t in trials if t.phase == "walk_forward_validation"),
            "holdout_trials": sum(1 for t in trials if t.phase == "holdout_test"),
            "passed_trials": sum(1 for t in trials if t.status == "PASSED"),
            "rejected_trials": sum(1 for t in trials if t.status == "REJECTED"),
            "failed_trials": sum(1 for t in trials if t.status == "FAILED"),
        }
        return summary

    def export_jsonl(self, out_path: Path, *, run_id: Optional[str] = None) -> int:
        trials = self.list_trials(run_id=run_id)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for t in trials:
                f.write(json.dumps(t.to_dict(), sort_keys=True) + "\n")
        return len(trials)
