"""Append-only immutable run registry (SQLite + JSONL audit log + content-addressed object store)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from rarp.domain.dsl import ExperimentSpec
from rarp.domain.errors import PolicyViolationError
from rarp.domain.types import RunStatus, canonical_json, sha256_bytes, sha256_json, utc_now_iso


class ObjectStore(Protocol):
    """Abstract object storage interface (local FS default; S3/GCS compatible seam)."""

    def put_json(self, relative_key: str, payload: Dict[str, Any]) -> Tuple[str, str]:
        ...

    def get_json(self, uri: str) -> Dict[str, Any]:
        ...


class LocalObjectStore:
    """Content-addressed local filesystem object store."""

    def __init__(self, root_dir: Path) -> None:
        self._root = root_dir
        self._root.mkdir(parents=True, exist_ok=True)

    def put_json(self, relative_key: str, payload: Dict[str, Any]) -> Tuple[str, str]:
        raw_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        digest = sha256_bytes(raw_bytes)
        safe_key = relative_key.lstrip("/")
        target = self._root / safe_key
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing_hash = sha256_bytes(target.read_bytes())
            if existing_hash != digest:
                # Never overwrite an existing artifact with different bytes; suffix by digest.
                target = target.with_name(f"{target.stem}_{digest[:10]}{target.suffix}")
        target.write_bytes(raw_bytes)
        return str(target.resolve()), digest

    def get_json(self, uri: str) -> Dict[str, Any]:
        path = Path(uri)
        return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    experiment_id: str
    hypothesis_id: str
    hypothesis_fingerprint: str
    idempotency_key: str
    data_manifest_id: str
    data_manifest_sha256: str
    split_sha256: str
    config_sha256: str
    seed: int
    status: str
    attempts: int
    started_at_utc: str
    completed_at_utc: str
    metrics: Dict[str, float]
    artifact_uri: str
    artifact_sha256: str
    error_code: Optional[str]
    error_message: Optional[str]
    experiment_spec: Dict[str, Any]
    prev_record_sha256: str
    record_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RunRegistry:
    """Immutable run registry backed by SQLite (with immutability triggers) and JSONL audit log."""

    def __init__(self, state_dir: Path, object_store: Optional[ObjectStore] = None) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "registry.db"
        self.audit_log_path = self.state_dir / "audit_log.jsonl"
        self.object_store: ObjectStore = object_store or LocalObjectStore(self.state_dir / "objects")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE NOT NULL,
                    experiment_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    hypothesis_fingerprint TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    data_manifest_id TEXT NOT NULL,
                    data_manifest_sha256 TEXT NOT NULL,
                    split_sha256 TEXT NOT NULL,
                    config_sha256 TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    artifact_uri TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    experiment_spec_json TEXT NOT NULL,
                    prev_record_sha256 TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS prevent_runs_update
                BEFORE UPDATE ON runs
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_RUN_RECORD');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_runs_delete
                BEFORE DELETE ON runs
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_RUN_RECORD');
                END;

                CREATE TABLE IF NOT EXISTS critic_reports (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT UNIQUE NOT NULL,
                    run_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    verified INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    report_sha256 TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS prevent_critic_update
                BEFORE UPDATE ON critic_reports
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_CRITIC_REPORT');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_critic_delete
                BEFORE DELETE ON critic_reports
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_CRITIC_REPORT');
                END;

                CREATE TABLE IF NOT EXISTS review_decisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT UNIQUE NOT NULL,
                    run_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    proposer_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    target_environment TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    decision_sha256 TEXT NOT NULL,
                    decided_at_utc TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS prevent_review_update
                BEFORE UPDATE ON review_decisions
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_REVIEW_DECISION');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_review_delete
                BEFORE DELETE ON review_decisions
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_REVIEW_DECISION');
                END;

                CREATE TABLE IF NOT EXISTS audit_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS prevent_audit_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_AUDIT_EVENT');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'IMMUTABLE_AUDIT_EVENT');
                END;
                """
            )

    def put_artifact(self, relative_key: str, payload: Dict[str, Any]) -> Tuple[str, str]:
        return self.object_store.put_json(relative_key, payload)

    def record_audit_event(self, event_type: str, actor_id: str, details: Dict[str, Any]) -> None:
        ts = utc_now_iso()
        details_json = canonical_json(details)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_events (timestamp_utc, event_type, actor_id, details_json) VALUES (?, ?, ?, ?)",
                (ts, event_type, actor_id, details_json),
            )
        line = canonical_json(
            {
                "timestamp_utc": ts,
                "event_type": event_type,
                "actor_id": actor_id,
                "details": details,
            }
        )
        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _last_run_hash(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT record_sha256 FROM runs ORDER BY seq DESC LIMIT 1").fetchone()
        return row["record_sha256"] if row is not None else "GENESIS"

    def record_run(
        self,
        spec: ExperimentSpec,
        status: RunStatus,
        metrics: Dict[str, float],
        artifact_uri: str,
        artifact_sha256: str,
        split_sha256: str,
        attempts: int,
        started_at_utc: str,
        completed_at_utc: str,
        error_code: Optional[str],
        error_message: Optional[str],
    ) -> RunRecord:
        idem_key = spec.idempotency_key()
        config_hash = spec.config_sha256()
        hyp_fp = spec.hypothesis.semantic_fingerprint()
        spec_dict = spec.to_dict()

        with self._connect() as conn:
            prev_hash = self._last_run_hash(conn)
            next_seq_row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS nxt FROM runs").fetchone()
            next_seq = int(next_seq_row["nxt"])
            run_id = f"run_{next_seq:04d}_{idem_key[:10]}"

            body = {
                "run_id": run_id,
                "experiment_id": spec.experiment_id,
                "hypothesis_id": spec.hypothesis.hypothesis_id,
                "hypothesis_fingerprint": hyp_fp,
                "idempotency_key": idem_key,
                "data_manifest_id": spec.data_manifest_id,
                "data_manifest_sha256": spec.data_manifest_sha256,
                "split_sha256": split_sha256,
                "config_sha256": config_hash,
                "seed": spec.seed,
                "status": status.value,
                "attempts": attempts,
                "started_at_utc": started_at_utc,
                "completed_at_utc": completed_at_utc,
                "metrics": dict(sorted(metrics.items())),
                "artifact_uri": artifact_uri,
                "artifact_sha256": artifact_sha256,
                "error_code": error_code,
                "error_message": error_message,
                "prev_record_sha256": prev_hash,
            }
            rec_hash = sha256_json(body)

            try:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, experiment_id, hypothesis_id, hypothesis_fingerprint,
                        idempotency_key, data_manifest_id, data_manifest_sha256, split_sha256,
                        config_sha256, seed, status, attempts, started_at_utc, completed_at_utc,
                        metrics_json, artifact_uri, artifact_sha256, error_code, error_message,
                        experiment_spec_json, prev_record_sha256, record_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        spec.experiment_id,
                        spec.hypothesis.hypothesis_id,
                        hyp_fp,
                        idem_key,
                        spec.data_manifest_id,
                        spec.data_manifest_sha256,
                        split_sha256,
                        config_hash,
                        spec.seed,
                        status.value,
                        attempts,
                        started_at_utc,
                        completed_at_utc,
                        canonical_json(dict(sorted(metrics.items()))),
                        artifact_uri,
                        artifact_sha256,
                        error_code,
                        error_message,
                        canonical_json(spec_dict),
                        prev_hash,
                        rec_hash,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PolicyViolationError(f"Cannot overwrite immutable run record {run_id}: {exc}") from exc

        self.record_audit_event(
            event_type="RUN_RECORDED",
            actor_id="run_registry",
            details={
                "run_id": run_id,
                "hypothesis_id": spec.hypothesis.hypothesis_id,
                "status": status.value,
                "data_manifest_id": spec.data_manifest_id,
                "record_sha256": rec_hash,
            },
        )

        return RunRecord(
            run_id=run_id,
            experiment_id=spec.experiment_id,
            hypothesis_id=spec.hypothesis.hypothesis_id,
            hypothesis_fingerprint=hyp_fp,
            idempotency_key=idem_key,
            data_manifest_id=spec.data_manifest_id,
            data_manifest_sha256=spec.data_manifest_sha256,
            split_sha256=split_sha256,
            config_sha256=config_hash,
            seed=spec.seed,
            status=status.value,
            attempts=attempts,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            metrics=dict(sorted(metrics.items())),
            artifact_uri=artifact_uri,
            artifact_sha256=artifact_sha256,
            error_code=error_code,
            error_message=error_message,
            experiment_spec=spec_dict,
            prev_record_sha256=prev_hash,
            record_sha256=rec_hash,
        )

    def _row_to_run(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            experiment_id=row["experiment_id"],
            hypothesis_id=row["hypothesis_id"],
            hypothesis_fingerprint=row["hypothesis_fingerprint"],
            idempotency_key=row["idempotency_key"],
            data_manifest_id=row["data_manifest_id"],
            data_manifest_sha256=row["data_manifest_sha256"],
            split_sha256=row["split_sha256"],
            config_sha256=row["config_sha256"],
            seed=int(row["seed"]),
            status=row["status"],
            attempts=int(row["attempts"]),
            started_at_utc=row["started_at_utc"],
            completed_at_utc=row["completed_at_utc"],
            metrics=json.loads(row["metrics_json"]),
            artifact_uri=row["artifact_uri"],
            artifact_sha256=row["artifact_sha256"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            experiment_spec=json.loads(row["experiment_spec_json"]),
            prev_record_sha256=row["prev_record_sha256"],
            record_sha256=row["record_sha256"],
        )

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row is not None else None

    def find_succeeded_by_idempotency_key(self, idempotency_key: str) -> Optional[RunRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE idempotency_key = ? AND status = ? ORDER BY seq ASC LIMIT 1",
                (idempotency_key, RunStatus.SUCCEEDED.value),
            ).fetchone()
        return self._row_to_run(row) if row is not None else None

    def list_runs(self, status: Optional[str] = None) -> List[RunRecord]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM runs WHERE status = ? ORDER BY seq ASC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM runs ORDER BY seq ASC").fetchall()
        return [self._row_to_run(r) for r in rows]

    def store_critic_report(self, report_dict: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO critic_reports (
                    report_id, run_id, hypothesis_id, verdict, verified,
                    report_json, report_sha256, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_dict["report_id"],
                    report_dict["run_id"],
                    report_dict["hypothesis_id"],
                    report_dict["verdict"],
                    1 if report_dict["verified"] else 0,
                    canonical_json(report_dict),
                    report_dict["report_sha256"],
                    report_dict["created_at_utc"],
                ),
            )
        self.record_audit_event(
            event_type="CRITIC_REPORT_STORED",
            actor_id="run_registry",
            details={
                "report_id": report_dict["report_id"],
                "run_id": report_dict["run_id"],
                "verdict": report_dict["verdict"],
                "verified": report_dict["verified"],
            },
        )

    def get_critic_report_for_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM critic_reports WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return json.loads(row["report_json"]) if row is not None else None

    def list_critic_reports(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT report_json FROM critic_reports ORDER BY seq ASC").fetchall()
        return [json.loads(r["report_json"]) for r in rows]

    def store_review_decision(self, decision_dict: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_decisions (
                    decision_id, run_id, hypothesis_id, proposer_id, reviewer_id,
                    decision, target_environment, decision_json, decision_sha256, decided_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_dict["decision_id"],
                    decision_dict["run_id"],
                    decision_dict["hypothesis_id"],
                    decision_dict["proposer_id"],
                    decision_dict["reviewer_id"],
                    decision_dict["decision"],
                    decision_dict["target_environment"],
                    canonical_json(decision_dict),
                    decision_dict["decision_sha256"],
                    decision_dict["decided_at_utc"],
                ),
            )
        self.record_audit_event(
            event_type="REVIEW_DECISION_RECORDED",
            actor_id=decision_dict["reviewer_id"],
            details={
                "decision_id": decision_dict["decision_id"],
                "run_id": decision_dict["run_id"],
                "decision": decision_dict["decision"],
                "target_environment": decision_dict["target_environment"],
            },
        )

    def list_review_decisions(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT decision_json FROM review_decisions WHERE run_id = ? ORDER BY seq ASC",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT decision_json FROM review_decisions ORDER BY seq ASC").fetchall()
        return [json.loads(r["decision_json"]) for r in rows]

    def list_audit_events(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM audit_events ORDER BY seq ASC").fetchall()
        return [
            {
                "seq": int(r["seq"]),
                "timestamp_utc": r["timestamp_utc"],
                "event_type": r["event_type"],
                "actor_id": r["actor_id"],
                "details": json.loads(r["details_json"]),
            }
            for r in rows
        ]

    def verify_hash_chain(self) -> bool:
        """Verify cryptographic hash chain across every immutable run record."""
        runs = self.list_runs()
        expected_prev = "GENESIS"
        for r in runs:
            if r.prev_record_sha256 != expected_prev:
                return False
            body = {
                "run_id": r.run_id,
                "experiment_id": r.experiment_id,
                "hypothesis_id": r.hypothesis_id,
                "hypothesis_fingerprint": r.hypothesis_fingerprint,
                "idempotency_key": r.idempotency_key,
                "data_manifest_id": r.data_manifest_id,
                "data_manifest_sha256": r.data_manifest_sha256,
                "split_sha256": r.split_sha256,
                "config_sha256": r.config_sha256,
                "seed": r.seed,
                "status": r.status,
                "attempts": r.attempts,
                "started_at_utc": r.started_at_utc,
                "completed_at_utc": r.completed_at_utc,
                "metrics": dict(sorted(r.metrics.items())),
                "artifact_uri": r.artifact_uri,
                "artifact_sha256": r.artifact_sha256,
                "error_code": r.error_code,
                "error_message": r.error_message,
                "prev_record_sha256": r.prev_record_sha256,
            }
            if sha256_json(body) != r.record_sha256:
                return False
            expected_prev = r.record_sha256
        return True
