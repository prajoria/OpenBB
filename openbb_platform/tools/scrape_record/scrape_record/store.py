"""User-local SQLite store for scrape_record snapshot envelopes.

Rationale (see GH #1425): committing Yahoo-shaped provider JSON to a
public fork reads as redistribution of Yahoo Finance data. The correct
posture — matching `yfinance`'s documented "personal use only" model — is
for every operator to record + keep their **own** local copy, outside
the git tree.

The store is a single SQLite DB (default: ``~/.scrape_record/snapshots.db``)
holding one row per ``(name, symbol)``. Upserts are idempotent so
`scrape-record record` and `scrape-record migrate` can be re-run freely.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scrape_record.record import SnapshotEnvelope


_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    name              TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    captured_at       TEXT NOT NULL,
    source_url        TEXT,
    raw_json          TEXT NOT NULL,
    extracted_json    TEXT,
    extractor_version TEXT,
    imported_at       TEXT NOT NULL,
    PRIMARY KEY (name, symbol)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_name ON snapshot(name);
"""


class SnapshotStore:
    """SQLite-backed store for snapshot envelopes.

    Use as a context manager, or call ``close()`` explicitly. Safe to
    open concurrently across processes thanks to WAL journaling.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        # WAL journal + foreign keys (FK unused today but keep the door open
        # for future joins to a `recording` table without a schema-migration
        # gotcha).
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> SnapshotStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection (idempotent)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def upsert(self, envelope: SnapshotEnvelope) -> None:
        """Insert or replace a snapshot envelope keyed on (name, symbol)."""
        row = asdict(envelope)
        raw_json = json.dumps(row["raw"], default=str, sort_keys=False)
        extracted = row.get("extracted")
        extracted_json = (
            json.dumps(extracted, default=str, sort_keys=False)
            if extracted is not None
            else None
        )
        imported_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO snapshot(
                name, symbol, captured_at, source_url,
                raw_json, extracted_json, extractor_version, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name, symbol) DO UPDATE SET
                captured_at       = excluded.captured_at,
                source_url        = excluded.source_url,
                raw_json          = excluded.raw_json,
                extracted_json    = excluded.extracted_json,
                extractor_version = excluded.extractor_version,
                imported_at       = excluded.imported_at
            """,
            (
                row["name"],
                row["symbol"],
                row["captured_at"],
                row.get("source_url"),
                raw_json,
                extracted_json,
                row.get("extractor_version"),
                imported_at,
            ),
        )
        self._conn.commit()

    def get(self, name: str, symbol: str) -> SnapshotEnvelope | None:
        """Return the envelope for (name, symbol), or None if absent."""
        # Imported here to avoid a circular import at module load.
        # pylint: disable=import-outside-toplevel
        from scrape_record.record import SnapshotEnvelope

        cur = self._conn.execute(
            "SELECT name, symbol, captured_at, source_url, raw_json, "
            "extracted_json, extractor_version FROM snapshot "
            "WHERE name = ? AND symbol = ?",
            (name, symbol),
        )
        row = cur.fetchone()
        if row is None:
            return None
        raw = json.loads(row["raw_json"])
        extracted = (
            json.loads(row["extracted_json"])
            if row["extracted_json"] is not None
            else None
        )
        return SnapshotEnvelope(
            name=row["name"],
            symbol=row["symbol"],
            captured_at=row["captured_at"],
            source_url=row["source_url"],
            raw=raw,
            extracted=extracted,
            extractor_version=row["extractor_version"],
        )

    def list_all(self) -> list[dict[str, Any]]:
        """Return metadata rows (no ``raw``/``extracted``) for every snapshot."""
        cur = self._conn.execute(
            "SELECT name, symbol, captured_at, source_url, extractor_version, "
            "imported_at, length(raw_json) AS raw_bytes "
            "FROM snapshot ORDER BY name, symbol"
        )
        return [dict(r) for r in cur.fetchall()]

    def delete(self, name: str, symbol: str) -> int:
        """Delete one row. Returns the number of rows removed (0 or 1)."""
        cur = self._conn.execute(
            "DELETE FROM snapshot WHERE name = ? AND symbol = ?",
            (name, symbol),
        )
        self._conn.commit()
        return cur.rowcount

    def count(self) -> int:
        """Total number of rows (convenience for the CLI + tests)."""
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM snapshot")
        return int(cur.fetchone()["n"])
