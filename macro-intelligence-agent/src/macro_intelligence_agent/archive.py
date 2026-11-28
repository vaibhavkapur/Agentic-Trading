"""SQLite-backed vintage archive with strict publication-gate enforcement and replay storage."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from .errors import EmbargoViolationError, SchemaValidationError
from .models import (
    AgentRunResult,
    ConsensusEstimate,
    DocumentType,
    MacroRelease,
    MetricObservation,
    format_utc_timestamp,
    parse_utc_timestamp,
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS releases (
    release_id TEXT NOT NULL,
    vintage_id TEXT NOT NULL,
    vintage_sequence INTEGER NOT NULL,
    series_group TEXT NOT NULL,
    reference_period TEXT NOT NULL,
    document_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    embargo_until TEXT,
    available_at TEXT NOT NULL,
    ingested_at TEXT,
    raw_text TEXT NOT NULL,
    document_sha256 TEXT NOT NULL,
    reported_metrics_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (release_id, vintage_id)
);

CREATE INDEX IF NOT EXISTS idx_releases_gate
    ON releases (series_group, available_at, release_id, vintage_sequence);

CREATE TABLE IF NOT EXISTS consensus_estimates (
    consensus_id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL,
    reference_period TEXT NOT NULL,
    expected_value TEXT NOT NULL,
    unit TEXT NOT NULL,
    published_at TEXT NOT NULL,
    source_id TEXT NOT NULL,
    contributor_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_consensus_gate
    ON consensus_estimates (series_id, reference_period, published_at);

CREATE TABLE IF NOT EXISTS run_replay_log (
    run_id TEXT PRIMARY KEY,
    as_of_utc TEXT NOT NULL,
    series_group TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


class ReleaseArchive:
    """Publication-gated SQLite store for macro releases, vintages, consensus, and run replays.

    Core invariant:
        No query parameterized by `as_of_utc` can ever return a release or consensus
        record whose effective availability timestamp (`available_at = max(published_at,
        embargo_until)`) is strictly greater than `as_of_utc`.
    """

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ReleaseArchive":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def add_release(self, release: MacroRelease) -> None:
        """Archive a validated release vintage (idempotent upsert by release_id + vintage_id)."""
        if not isinstance(release, MacroRelease):
            raise SchemaValidationError("add_release requires a MacroRelease instance")
        self._conn.execute(
            """
            INSERT OR REPLACE INTO releases (
                release_id, vintage_id, vintage_sequence, series_group, reference_period,
                document_type, source_id, source_name, title,
                published_at, embargo_until, available_at, ingested_at,
                raw_text, document_sha256, reported_metrics_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                release.release_id,
                release.vintage_id,
                release.vintage_sequence,
                release.series_group,
                release.reference_period,
                release.document_type.value,
                release.source_id,
                release.source_name,
                release.title,
                format_utc_timestamp(release.published_at),
                (
                    format_utc_timestamp(release.embargo_until)
                    if release.embargo_until is not None
                    else None
                ),
                format_utc_timestamp(release.available_at),
                (
                    format_utc_timestamp(release.ingested_at)
                    if release.ingested_at is not None
                    else None
                ),
                release.raw_text,
                release.document_sha256,
                json.dumps([m.to_dict() for m in release.reported_metrics], sort_keys=True),
                json.dumps(release.metadata, sort_keys=True),
            ),
        )
        self._conn.commit()

    def add_consensus(self, estimate: ConsensusEstimate) -> None:
        """Archive a validated pre-release consensus benchmark."""
        if not isinstance(estimate, ConsensusEstimate):
            raise SchemaValidationError("add_consensus requires a ConsensusEstimate instance")
        self._conn.execute(
            """
            INSERT OR REPLACE INTO consensus_estimates (
                consensus_id, series_id, reference_period, expected_value,
                unit, published_at, source_id, contributor_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                estimate.consensus_id,
                estimate.series_id,
                estimate.reference_period,
                format(estimate.expected_value, "f"),
                estimate.unit.value,
                format_utc_timestamp(estimate.published_at),
                estimate.source_id,
                estimate.contributor_count,
            ),
        )
        self._conn.commit()

    def load_fixture_dict(self, payload: Dict[str, Any]) -> Tuple[int, int]:
        """Load releases and consensus records from a fixture dictionary."""
        if not isinstance(payload, dict):
            raise SchemaValidationError("Fixture payload must be a JSON object")
        releases_raw = payload.get("releases", [])
        consensus_raw = payload.get("consensus_estimates", [])
        if not isinstance(releases_raw, list) or not isinstance(consensus_raw, list):
            raise SchemaValidationError(
                "Fixture 'releases' and 'consensus_estimates' must be lists"
            )
        for item in releases_raw:
            self.add_release(MacroRelease.from_dict(item))
        for item in consensus_raw:
            self.add_consensus(ConsensusEstimate.from_dict(item))
        return len(releases_raw), len(consensus_raw)

    def load_fixture_file(self, path: Union[str, Path]) -> Tuple[int, int]:
        fixture_path = Path(path)
        if not fixture_path.exists():
            raise SchemaValidationError(
                f"Fixture file does not exist: {fixture_path}",
                details={"path": str(fixture_path)},
            )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        return self.load_fixture_dict(data)

    def _row_to_release(self, row: sqlite3.Row) -> MacroRelease:
        metrics = tuple(
            MetricObservation.from_dict(m) for m in json.loads(row["reported_metrics_json"])
        )
        return MacroRelease(
            release_id=row["release_id"],
            vintage_id=row["vintage_id"],
            vintage_sequence=int(row["vintage_sequence"]),
            series_group=row["series_group"],
            reference_period=row["reference_period"],
            document_type=DocumentType.parse(row["document_type"]),
            source_id=row["source_id"],
            source_name=row["source_name"],
            title=row["title"],
            published_at=parse_utc_timestamp(row["published_at"], "published_at"),
            embargo_until=(
                parse_utc_timestamp(row["embargo_until"], "embargo_until")
                if row["embargo_until"] is not None
                else None
            ),
            ingested_at=(
                parse_utc_timestamp(row["ingested_at"], "ingested_at")
                if row["ingested_at"] is not None
                else None
            ),
            raw_text=row["raw_text"],
            reported_metrics=metrics,
            metadata=json.loads(row["metadata_json"]),
        )

    def query_releases_as_of(
        self,
        as_of_utc: Union[datetime, str],
        *,
        series_group: Optional[str] = None,
    ) -> List[MacroRelease]:
        """Return all release vintages strictly available on or before `as_of_utc`."""
        cutoff = parse_utc_timestamp(as_of_utc, "as_of_utc")
        cutoff_iso = format_utc_timestamp(cutoff)
        if series_group is not None:
            rows = self._conn.execute(
                """
                SELECT * FROM releases
                WHERE series_group = ? AND available_at <= ?
                ORDER BY available_at ASC, release_id ASC, vintage_sequence ASC
                """,
                (series_group, cutoff_iso),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM releases
                WHERE available_at <= ?
                ORDER BY available_at ASC, release_id ASC, vintage_sequence ASC
                """,
                (cutoff_iso,),
            ).fetchall()
        results = [self._row_to_release(r) for r in rows]
        # Defense-in-depth in-memory publication gate check (never trust SQLite string sort alone)
        gated = [r for r in results if r.available_at <= cutoff]
        return gated

    def count_gated_out_releases(
        self,
        as_of_utc: Union[datetime, str],
        *,
        series_group: Optional[str] = None,
    ) -> int:
        """Count archived releases hidden by the publication/embargo gate (metadata count only)."""
        cutoff = parse_utc_timestamp(as_of_utc, "as_of_utc")
        if series_group is not None:
            rows = self._conn.execute(
                "SELECT available_at FROM releases WHERE series_group = ?",
                (series_group,),
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT available_at FROM releases").fetchall()
        return sum(
            1
            for r in rows
            if parse_utc_timestamp(r["available_at"], "available_at") > cutoff
        )

    def get_release_checked(
        self,
        release_id: str,
        vintage_id: str,
        as_of_utc: Union[datetime, str],
    ) -> MacroRelease:
        """Fetch a specific release vintage or raise EmbargoViolationError if gated."""
        cutoff = parse_utc_timestamp(as_of_utc, "as_of_utc")
        row = self._conn.execute(
            "SELECT * FROM releases WHERE release_id = ? AND vintage_id = ?",
            (release_id, vintage_id),
        ).fetchone()
        if row is None:
            raise SchemaValidationError(
                f"Release vintage not found: ({release_id}, {vintage_id})",
                details={"release_id": release_id, "vintage_id": vintage_id},
            )
        release = self._row_to_release(row)
        if release.available_at > cutoff:
            raise EmbargoViolationError(
                f"Release ({release_id}, {vintage_id}) is embargoed/unpublished at cutoff {format_utc_timestamp(cutoff)}",
                details={
                    "release_id": release_id,
                    "vintage_id": vintage_id,
                    "available_at": format_utc_timestamp(release.available_at),
                    "as_of_utc": format_utc_timestamp(cutoff),
                },
            )
        return release

    def query_consensus_as_of(
        self,
        as_of_utc: Union[datetime, str],
        *,
        series_id: Optional[str] = None,
        reference_period: Optional[str] = None,
    ) -> List[ConsensusEstimate]:
        """Return consensus benchmarks published on or before `as_of_utc`."""
        cutoff = parse_utc_timestamp(as_of_utc, "as_of_utc")
        clauses: List[str] = []
        params: List[Any] = []
        if series_id is not None:
            clauses.append("series_id = ?")
            params.append(series_id)
        if reference_period is not None:
            clauses.append("reference_period = ?")
            params.append(reference_period)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM consensus_estimates {where} ORDER BY published_at ASC, consensus_id ASC",
            params,
        ).fetchall()
        estimates: List[ConsensusEstimate] = []
        for row in rows:
            est = ConsensusEstimate.from_dict(
                {
                    "consensus_id": row["consensus_id"],
                    "series_id": row["series_id"],
                    "reference_period": row["reference_period"],
                    "expected_value": row["expected_value"],
                    "unit": row["unit"],
                    "published_at": row["published_at"],
                    "source_id": row["source_id"],
                    "contributor_count": row["contributor_count"],
                }
            )
            if est.published_at <= cutoff:
                estimates.append(est)
        return estimates

    def save_run_result(self, result: AgentRunResult) -> None:
        """Persist a completed run for deterministic replay and audit comparison."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO run_replay_log (
                run_id, as_of_utc, series_group, config_sha256, input_sha256, result_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                result.metadata.run_id,
                format_utc_timestamp(result.metadata.as_of_utc),
                result.brief.series_group,
                result.metadata.config_sha256,
                result.metadata.input_sha256,
                json.dumps(result.to_dict(), sort_keys=True),
            ),
        )
        self._conn.commit()

    def load_run_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT result_json FROM run_replay_log WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["result_json"])

    def list_runs(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT run_id, as_of_utc, series_group, config_sha256, input_sha256
            FROM run_replay_log
            ORDER BY as_of_utc ASC, run_id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]
