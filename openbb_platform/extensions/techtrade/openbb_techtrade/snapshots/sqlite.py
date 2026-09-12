"""Compatibility facade from the legacy scan API to the canonical EOD store."""

from __future__ import annotations

import os
from pathlib import Path

from openbb_techtrade import config
from openbb_techtrade.snapshot.datasets import validate_techtrade_snapshot
from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    SnapshotStatus,
    SqliteSnapshotStore,
    canonical_key,
    snapshot_input_hash,
)
from openbb_techtrade.snapshots.models import DEFAULT_SCAN_KIND, ScanSnapshot

SCAN_DB_ENV = "OPENBB_TECHTRADE_SCAN_DB"
_DATASET_PREFIX = "techtrade.scan"


def default_scan_db_path() -> Path:
    """Return the compatibility path, defaulting to the canonical snapshot DB."""
    override = os.environ.get(SCAN_DB_ENV)
    return Path(override).expanduser() if override else config.snapshot_db_path()


def _dataset(kind: str) -> str:
    normalized = canonical_key(kind).replace(" ", "-")
    return (
        _DATASET_PREFIX
        if normalized == canonical_key(DEFAULT_SCAN_KIND).replace(" ", "-")
        else f"{_DATASET_PREFIX}.{normalized}"
    )


def _entity_key(segment: str) -> str:
    if not segment.strip():
        raise ValueError("segment must not be blank")
    return canonical_key(f"segment={segment}")


def _payload(snapshot: ScanSnapshot) -> dict:
    return {
        "rows": snapshot.rows,
        "segment": snapshot.segment,
        "as_of_session": snapshot.as_of_session.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": [],
        "excluded_symbols": [],
        "survivorship": "not-applicable",
        "legacy": {
            "snapshot_id": snapshot.snapshot_id,
            "kind": snapshot.kind,
            "computed_at": snapshot.computed_at.isoformat(),
            "preset": snapshot.preset,
            "params": snapshot.params,
        },
    }


def _to_snapshot(row: SnapshotRow) -> ScanSnapshot:
    legacy = row.payload.get("legacy", {})
    return ScanSnapshot(
        snapshot_id=str(legacy.get("snapshot_id") or row.job_run_id),
        kind=str(legacy.get("kind") or DEFAULT_SCAN_KIND),
        segment=str(row.payload.get("segment") or row.entity_key.split("=", 1)[-1]),
        as_of_session=row.as_of_session,
        computed_at=legacy.get("computed_at") or row.created_at,
        preset=legacy.get("preset"),
        params=legacy.get("params") or {},
        rows=row.payload.get("rows") or [],
    )


class SqliteScanSnapshotStore:
    """Legacy API backed exclusively by :class:`SqliteSnapshotStore` tables."""

    def __init__(self, path: Path | str | None = None, **kwargs) -> None:
        self._store = SqliteSnapshotStore(path or default_scan_db_path(), **kwargs)

    @property
    def path(self) -> Path:
        """Return the canonical SQLite database path."""
        return self._store._db_path  # pylint: disable=protected-access

    def initialize(self) -> None:
        """Retain the old no-op hook; construction initializes the schema."""

    def close(self) -> None:
        """Close the canonical store connection."""
        self._store.close()

    def write_snapshot(self, snapshot: ScanSnapshot) -> ScanSnapshot:
        """Validate and promote one legacy DTO through the canonical lifecycle."""
        dataset = _dataset(snapshot.kind)
        entity_key = _entity_key(snapshot.segment)
        payload = _payload(snapshot)
        self._store.stage(
            dataset,
            entity_key,
            snapshot.as_of_session,
            snapshot.snapshot_id,
            payload,
            status=SnapshotStatus.OK,
            input_hash=snapshot_input_hash(payload, "legacy-compat-1"),
            row_count=snapshot.row_count,
            engine_version="legacy-compat-1",
            payload_schema_version="1",
        )
        previous = self._store.get_live(dataset, entity_key)
        verdict = self._store.validate(
            dataset,
            entity_key,
            snapshot.as_of_session,
            snapshot.snapshot_id,
            lambda row: validate_techtrade_snapshot(row, previous),
        )
        if not verdict.ok:
            raise ValueError(f"snapshot validation failed: {verdict.reason}")
        if not self._store.promote(
            dataset, entity_key, snapshot.as_of_session, snapshot.snapshot_id
        ):
            raise ValueError("snapshot promotion refused")
        return snapshot

    def read_latest(self, *, kind: str, segment: str) -> ScanSnapshot | None:
        """Return the generic LIVE row translated to the legacy DTO."""
        row = self._store.get_live(_dataset(kind), _entity_key(segment))
        return None if row is None else _to_snapshot(row)

    def read_by_id(self, snapshot_id: str) -> ScanSnapshot | None:
        """Return one historical legacy DTO by its snapshot identifier."""
        record = self._store._conn.execute(  # pylint: disable=protected-access
            "SELECT dataset, entity_key FROM pi_eod_snapshot "
            "WHERE dataset LIKE ? AND job_run_id = ? LIMIT 1",
            (f"{_DATASET_PREFIX}%", snapshot_id),
        ).fetchone()
        if record is None:
            return None
        matching = [
            row
            for row in self._store.list_history(
                str(record["dataset"]), str(record["entity_key"]), limit=10_000
            )
            if row.job_run_id == snapshot_id
        ]
        return None if not matching else _to_snapshot(matching[0])

    def _scopes(self, kind: str | None, segment: str | None) -> list[tuple[str, str]]:
        connection = self._store._conn  # pylint: disable=protected-access
        if kind is not None and segment is not None:
            records = connection.execute(
                "SELECT DISTINCT dataset, entity_key FROM pi_eod_snapshot "
                "WHERE dataset = ? AND entity_key = ?",
                (_dataset(kind), _entity_key(segment)),
            ).fetchall()
        elif kind is not None:
            records = connection.execute(
                "SELECT DISTINCT dataset, entity_key FROM pi_eod_snapshot "
                "WHERE dataset = ?",
                (_dataset(kind),),
            ).fetchall()
        elif segment is not None:
            records = connection.execute(
                "SELECT DISTINCT dataset, entity_key FROM pi_eod_snapshot "
                "WHERE dataset LIKE ? AND entity_key = ?",
                (f"{_DATASET_PREFIX}%", _entity_key(segment)),
            ).fetchall()
        else:
            records = connection.execute(
                "SELECT DISTINCT dataset, entity_key FROM pi_eod_snapshot "
                "WHERE dataset LIKE ?",
                (f"{_DATASET_PREFIX}%",),
            ).fetchall()
        return [(str(row["dataset"]), str(row["entity_key"])) for row in records]

    def list_snapshots(
        self,
        *,
        kind: str | None = None,
        segment: str | None = None,
        limit: int | None = None,
    ) -> list[ScanSnapshot]:
        """List legacy DTOs newest-first with optional filters."""
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        rows = [
            row
            for dataset, entity_key in self._scopes(kind, segment)
            for row in self._store.list_history(dataset, entity_key)
        ]
        snapshots = sorted(
            (_to_snapshot(row) for row in rows),
            key=lambda snapshot: snapshot.computed_at,
            reverse=True,
        )
        return snapshots if limit is None else snapshots[:limit]

    def prune_snapshots(self, *, keep: int = 10) -> int:
        """Keep the newest legacy-compatible rows per dataset and segment."""
        if keep < 0:
            raise ValueError("keep must be non-negative")
        deleted = 0
        for dataset, entity_key in self._scopes(None, None):
            history = self._store.list_history(dataset, entity_key)
            removable = [
                row
                for row in sorted(
                    history,
                    key=lambda item: _to_snapshot(item).computed_at,
                    reverse=True,
                )[keep:]
                if row.state.value != "live"
            ]
            with self._store._tx(immediate=True):  # pylint: disable=protected-access
                for row in removable:
                    cursor = self._store._conn.execute(  # pylint: disable=protected-access
                        "DELETE FROM pi_eod_snapshot WHERE dataset = ? "
                        "AND entity_key = ? AND as_of_session = ? AND job_run_id = ?",
                        (
                            row.dataset,
                            row.entity_key,
                            row.as_of_session.isoformat(),
                            row.job_run_id,
                        ),
                    )
                    deleted += cursor.rowcount
        return deleted


__all__ = ["SCAN_DB_ENV", "SqliteScanSnapshotStore", "default_scan_db_path"]
