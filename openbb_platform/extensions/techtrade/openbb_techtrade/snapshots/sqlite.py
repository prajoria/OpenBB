"""Compatibility facade from the legacy scan API to the canonical EOD store."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from openbb_techtrade import config
from openbb_techtrade.engine.universe import GICS_SECTOR_ETFS
from openbb_techtrade.snapshot.datasets import validate_techtrade_snapshot
from openbb_techtrade.snapshot.job import SnapshotJobState
from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SqliteSnapshotStore,
    _row_from_mapping,
    canonical_key,
    get_default_snapshot_store,
    snapshot_input_hash,
)
from openbb_techtrade.snapshots.models import DEFAULT_SCAN_KIND, ScanSnapshot

SCAN_DB_ENV = "OPENBB_TECHTRADE_SCAN_DB"
_DATASET_PREFIX = "techtrade.scan"


def default_scan_db_path() -> Path:
    """Return the compatibility path, defaulting to the canonical snapshot DB."""
    override = os.environ.get(SCAN_DB_ENV)
    return Path(override).expanduser() if override else config.snapshot_db_path()


def legacy_scan_db_path() -> Path:
    """Return the retired standalone scan-store path."""
    return Path.home() / ".openbb_platform" / "techtrade_scan.db"


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
    digest = sha256(f"{row.dataset}\x1f{row.entity_key}".encode()).hexdigest()[:16]
    return ScanSnapshot(
        snapshot_id=str(legacy.get("snapshot_id") or f"{row.job_run_id}~{digest}"),
        kind=str(legacy.get("kind") or DEFAULT_SCAN_KIND),
        segment=str(row.payload.get("segment") or row.entity_key.split("=", 1)[-1]),
        as_of_session=row.as_of_session,
        computed_at=legacy.get("computed_at") or row.created_at,
        preset=legacy.get("preset", row.payload.get("preset")),
        params=legacy.get("params") or row.payload.get("params") or {},
        rows=row.payload.get("rows") or [],
    )


class SqliteScanSnapshotStore:
    """Legacy API backed exclusively by :class:`SqliteSnapshotStore` tables."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        legacy_override = os.environ.get(SCAN_DB_ENV)
        sqlite_path = path if path is not None else legacy_override
        self._store: Any = (
            SqliteSnapshotStore(sqlite_path)
            if sqlite_path is not None
            else get_default_snapshot_store()
        )
        if isinstance(self._store, SqliteSnapshotStore):
            self._store._conn.execute(  # pylint: disable=protected-access
                f"PRAGMA busy_timeout = {int(busy_timeout_ms)}"
            )
        if path is None and legacy_override is None:
            self._migrate_legacy_history()

    @property
    def path(self) -> Path:
        """Return the canonical SQLite database path."""
        if not isinstance(self._store, SqliteSnapshotStore):
            raise RuntimeError("configured canonical backend is not SQLite")
        return self._store._db_path  # pylint: disable=protected-access

    def initialize(self) -> None:
        """Retain the old no-op hook; construction initializes the schema."""

    def _migrate_legacy_history(self) -> None:
        source = legacy_scan_db_path()
        if not source.is_file() or (
            isinstance(self._store, SqliteSnapshotStore)
            and source.resolve()
            == self._store._db_path  # pylint: disable=protected-access
        ):
            return
        with sqlite3.connect(
            f"file:{source.as_posix()}?mode=ro", uri=True
        ) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='scan_snapshot'"
            ).fetchone()
            if exists is None:
                return
            rows = connection.execute(
                "SELECT snapshot_id, kind, segment, as_of_session, computed_at, "
                "preset, params_json, rows_json FROM scan_snapshot "
                "ORDER BY computed_at"
            ).fetchall()
        for row in rows:
            if self._store.get_job(str(row[0])) is not None:
                continue
            self.write_snapshot(
                ScanSnapshot(
                    snapshot_id=str(row[0]),
                    kind=str(row[1]),
                    segment=str(row[2]),
                    as_of_session=date.fromisoformat(str(row[3])),
                    computed_at=datetime.fromisoformat(str(row[4])),
                    preset=row[5],
                    params=json.loads(row[6]),
                    rows=json.loads(row[7]),
                )
            )

    def close(self) -> None:
        """Close the canonical store connection."""
        self._store.close()

    def write_snapshot(self, snapshot: ScanSnapshot) -> ScanSnapshot:
        """Validate and promote one legacy DTO through the canonical lifecycle."""
        dataset = _dataset(snapshot.kind)
        entity_key = _entity_key(snapshot.segment)
        payload = _payload(snapshot)
        if self._store.get_job(snapshot.snapshot_id) is not None:
            raise ValueError("snapshot_id already exists")
        self._store.start_job(dataset, snapshot.snapshot_id)
        try:
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
            self._store.publish_job(
                snapshot.snapshot_id,
                [
                    (
                        dataset,
                        entity_key,
                        snapshot.as_of_session,
                        snapshot.snapshot_id,
                    )
                ],
            )
            if (
                previous is not None
                and snapshot.computed_at < _to_snapshot(previous).computed_at
                and not self._store.rollback(
                    dataset,
                    entity_key,
                    previous.as_of_session,
                    previous.job_run_id,
                )
            ):
                raise RuntimeError("failed to preserve newer LIVE snapshot")
        except BaseException:
            job = self._store.get_job(snapshot.snapshot_id)
            if job is not None and job.state is SnapshotJobState.RUNNING:
                self._store.record_job_errors(
                    snapshot.snapshot_id,
                    {entity_key: "validation_failed"},
                )
                self._store.finish_job(
                    snapshot.snapshot_id,
                    SnapshotJobState.FAILED,
                    n_ok=0,
                    n_failed=1,
                    error="validation_failed",
                )
            raise
        return snapshot

    def read_latest(self, *, kind: str, segment: str) -> ScanSnapshot | None:
        """Return the generic LIVE row translated to the legacy DTO."""
        row = self._store.get_live(_dataset(kind), _entity_key(segment))
        return None if row is None else _to_snapshot(row)

    def read_by_id(self, snapshot_id: str) -> ScanSnapshot | None:
        """Return one historical legacy DTO by its snapshot identifier."""
        job_run_id = snapshot_id
        job = self._store.get_job(job_run_id)
        if job is None and "~" in snapshot_id:
            job_run_id = snapshot_id.rsplit("~", 1)[0]
            job = self._store.get_job(job_run_id)
        if job is None:
            return None
        visible = [
            row
            for row in self._store.rows_for_job(job_run_id)
            if row.dataset.startswith(_DATASET_PREFIX)
            and row.state is not SnapshotState.STAGING
        ]
        matching = [
            row for row in visible if _to_snapshot(row).snapshot_id == snapshot_id
        ]
        if not matching:
            return None
        if len(matching) != 1:
            raise ValueError("snapshot_id is ambiguous")
        return _to_snapshot(matching[0])

    def _history_rows(self, kind: str | None, segment: str | None) -> list[SnapshotRow]:
        if not isinstance(self._store, SqliteSnapshotStore):
            datasets = (
                [_dataset(kind)]
                if kind is not None
                else self._store.list_datasets(prefix=_DATASET_PREFIX)
            )
            segments = [segment] if segment is not None else list(GICS_SECTOR_ETFS)
            return [
                row
                for dataset in datasets
                for candidate in segments
                for row in self._store.list_history(
                    dataset,
                    _entity_key(candidate),
                    limit=2_147_483_647,
                )
                if row.state is not SnapshotState.STAGING
            ]
        select = (
            "SELECT dataset, entity_key, as_of_session, created_at, job_run_id, "
            "status, state, validated, validation_reason, payload_json, "
            "input_hash, row_count, engine_version, payload_schema_version "
            "FROM pi_eod_snapshot WHERE state != ?"
        )
        connection = self._store._conn  # pylint: disable=protected-access
        if kind is not None and segment is not None:
            records = connection.execute(
                select + " AND dataset = ? AND entity_key = ?",
                (
                    SnapshotState.STAGING.value,
                    _dataset(kind),
                    _entity_key(segment),
                ),
            ).fetchall()
        elif kind is not None:
            records = connection.execute(
                select + " AND dataset = ?",
                (SnapshotState.STAGING.value, _dataset(kind)),
            ).fetchall()
        elif segment is not None:
            records = connection.execute(
                select + " AND dataset LIKE ? AND entity_key = ?",
                (
                    SnapshotState.STAGING.value,
                    f"{_DATASET_PREFIX}%",
                    _entity_key(segment),
                ),
            ).fetchall()
        else:
            records = connection.execute(
                select + " AND dataset LIKE ?",
                (SnapshotState.STAGING.value, f"{_DATASET_PREFIX}%"),
            ).fetchall()
        return [_row_from_mapping(record) for record in records]

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
        rows = self._history_rows(kind, segment)
        snapshots = sorted(
            (_to_snapshot(row) for row in rows),
            key=lambda snapshot: snapshot.computed_at,
            reverse=True,
        )
        return snapshots if limit is None else snapshots[:limit]

    def prune_snapshots(self, *, keep: int = 10) -> int:
        """Keep the newest legacy-compatible rows per dataset and segment."""
        if keep < 1:
            raise ValueError("keep must be at least 1")
        history_by_scope: dict[tuple[str, str], list[SnapshotRow]] = {}
        for row in self._history_rows(None, None):
            history_by_scope.setdefault((row.dataset, row.entity_key), []).append(row)
        removable = [
            (
                row.dataset,
                row.entity_key,
                row.as_of_session,
                row.job_run_id,
            )
            for history in history_by_scope.values()
            for row in sorted(
                history,
                key=lambda item: _to_snapshot(item).computed_at,
                reverse=True,
            )[keep:]
            if row.state is not SnapshotState.LIVE
        ]
        return self._store.delete_history(removable)


__all__ = [
    "SCAN_DB_ENV",
    "SqliteScanSnapshotStore",
    "default_scan_db_path",
    "legacy_scan_db_path",
]
