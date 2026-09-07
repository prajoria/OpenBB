"""SQLite-backed append-only scan snapshot store (issue #1934).

Single-host and durable, following the same WAL + foreign-keys + busy-timeout +
short-transaction discipline as the core ``SqliteJobStore``. Snapshots are only ever
inserted -- never updated -- so a reader always sees the last committed
``(kind, segment)`` snapshot even while a later run is mid-flight or has failed.

The default database lives next to the jobs database at
``~/.openbb_platform/techtrade_scan.db`` and is overridable with the
``OPENBB_TECHTRADE_SCAN_DB`` environment variable so tests and operators can point
it elsewhere without code changes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openbb_techtrade.snapshots.models import ScanSnapshot
from openbb_techtrade.snapshots.store import DEFAULT_RETENTION

UTC = timezone.utc
DEFAULT_BUSY_TIMEOUT_MS = 5_000

#: Environment variable overriding the snapshot database location.
SCAN_DB_ENV = "OPENBB_TECHTRADE_SCAN_DB"


def default_scan_db_path() -> Path:
    """Return the configured (or default) snapshot database path."""
    override = os.environ.get(SCAN_DB_ENV)
    if override:
        return Path(override).expanduser()

    return Path.home() / ".openbb_platform" / "techtrade_scan.db"


def _serialize_json(value: Any) -> str:
    """Serialize a JSON payload in canonical form."""
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _ensure_utc(value: datetime) -> datetime:
    """Normalize an aware datetime to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("computed_at must be timezone-aware")

    return value.astimezone(UTC)


class SqliteScanSnapshotStore:
    """Single-host SQLite persistence for append-only scan snapshots."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        """Open (creating parents as needed) the snapshot database."""
        self._path = Path(path) if path is not None else default_scan_db_path()
        self._busy_timeout_ms = busy_timeout_ms
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self._path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._apply_pragmas()
        self.initialize()

    @property
    def path(self) -> Path:
        """Return the backing database path."""
        return self._path

    def initialize(self) -> None:
        """Create the append-only snapshot schema if it does not exist."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scan_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                segment TEXT NOT NULL,
                as_of_session TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                preset TEXT,
                params_json TEXT NOT NULL DEFAULT '{}',
                rows_json TEXT NOT NULL DEFAULT '[]',
                row_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_scan_snapshot_latest
                ON scan_snapshot (kind, segment, computed_at);
            """
        )

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()

    def write_snapshot(self, snapshot: ScanSnapshot) -> ScanSnapshot:
        """Append one immutable snapshot in a single transaction."""
        computed_at = _ensure_utc(snapshot.computed_at)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO scan_snapshot (
                    snapshot_id, kind, segment, as_of_session, computed_at,
                    preset, params_json, rows_json, row_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.kind,
                    snapshot.segment,
                    snapshot.as_of_session.isoformat(),
                    computed_at.isoformat(),
                    snapshot.preset,
                    _serialize_json(snapshot.params),
                    _serialize_json(snapshot.rows),
                    snapshot.row_count,
                ),
            )

        return snapshot

    def read_latest(self, *, kind: str, segment: str) -> ScanSnapshot | None:
        """Return the newest snapshot for a ``(kind, segment)`` pair."""
        row = self._connection.execute(
            """
            SELECT * FROM scan_snapshot
            WHERE kind = ? AND segment = ?
            ORDER BY computed_at DESC, rowid DESC
            LIMIT 1
            """,
            (kind, segment),
        ).fetchone()

        return None if row is None else self._row_to_snapshot(row)

    def read_by_id(self, snapshot_id: str) -> ScanSnapshot | None:
        """Return a snapshot by identifier or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM scan_snapshot WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()

        return None if row is None else self._row_to_snapshot(row)

    def list_snapshots(
        self,
        *,
        kind: str | None = None,
        segment: str | None = None,
        limit: int | None = None,
    ) -> list[ScanSnapshot]:
        """Return snapshots newest-first, optionally filtered by kind/segment."""
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if segment is not None:
            clauses.append("segment = ?")
            params.append(segment)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        rows = self._connection.execute(
            f"""
            SELECT * FROM scan_snapshot
            {where}
            ORDER BY computed_at DESC, rowid DESC
            {limit_sql}
            """,  # noqa: S608 - {where}/{limit_sql} are built from static literals only; all values are parameterized
            tuple(params),
        ).fetchall()

        return [self._row_to_snapshot(row) for row in rows]

    def prune_snapshots(self, *, keep: int = DEFAULT_RETENTION) -> int:
        """Delete all but the newest ``keep`` snapshots per ``(kind, segment)``."""
        if keep < 0:
            raise ValueError("keep must be non-negative")

        with self._transaction() as connection:
            cursor = connection.execute(
                """
                DELETE FROM scan_snapshot
                WHERE rowid IN (
                    SELECT rowid FROM (
                        SELECT rowid,
                               ROW_NUMBER() OVER (
                                   PARTITION BY kind, segment
                                   ORDER BY computed_at DESC, rowid DESC
                               ) AS rn
                        FROM scan_snapshot
                    )
                    WHERE rn > ?
                )
                """,
                (keep,),
            )
            return cursor.rowcount

    def _row_to_snapshot(self, row: sqlite3.Row) -> ScanSnapshot:
        """Hydrate a snapshot from a SQLite row."""
        return ScanSnapshot(
            snapshot_id=row["snapshot_id"],
            kind=row["kind"],
            segment=row["segment"],
            as_of_session=date.fromisoformat(row["as_of_session"]),
            computed_at=datetime.fromisoformat(row["computed_at"]),
            preset=row["preset"],
            params=json.loads(row["params_json"]),
            rows=json.loads(row["rows_json"]),
        )

    def _apply_pragmas(self) -> None:
        """Configure SQLite for durable multi-process access."""
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        self._connection.execute("PRAGMA synchronous = NORMAL")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a short explicit immediate transaction."""
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")
