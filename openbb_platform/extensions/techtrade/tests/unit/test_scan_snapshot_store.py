"""Contract tests for the append-only scan snapshot store (issue #1934).

Fully offline. Exercises the ``ScanSnapshotStore`` contract through the SQLite
implementation: round trips, latest-by-``(kind, segment)``, list/filter, retention,
and the last-good guarantee (a failed later write never clobbers the previous
committed snapshot).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from openbb_techtrade.snapshot.store import SqliteSnapshotStore
from openbb_techtrade.snapshots import (
    ScanSnapshot,
    SqliteScanSnapshotStore,
    default_scan_db_path,
)
from openbb_techtrade.snapshots.sqlite import SCAN_DB_ENV

UTC = timezone.utc
_SESSION = date(2024, 1, 12)


@pytest.fixture()
def store(tmp_path):
    """Return a fresh SQLite snapshot store on a temp database."""
    db = tmp_path / "scan.db"
    snapshot_store = SqliteScanSnapshotStore(db)
    try:
        yield snapshot_store
    finally:
        snapshot_store.close()


def _rows(*symbols: str) -> list[dict]:
    """Build simple widget-ready rows for the given symbols."""
    return [
        {"symbol": s, "segment": "Energy", "score": 0.9, "action": "BUY"}
        for s in symbols
    ]


def _snapshot(
    *,
    segment: str = "Energy",
    kind: str = "daily_scan",
    computed_at: datetime | None = None,
    rows: list[dict] | None = None,
) -> ScanSnapshot:
    """Build a ScanSnapshot with sensible defaults."""
    return ScanSnapshot(
        kind=kind,
        segment=segment,
        as_of_session=_SESSION,
        computed_at=computed_at or datetime(2024, 1, 12, 8, 30, tzinfo=UTC),
        preset="trend_follow",
        params={"top_n": 3},
        rows=_rows("AAA", "BBB") if rows is None else rows,
    )


def test_write_and_read_by_id_round_trips(store):
    """A written snapshot reads back byte-for-byte by id."""
    snap = _snapshot()
    store.write_snapshot(snap)

    loaded = store.read_by_id(snap.snapshot_id)
    assert loaded is not None
    assert loaded.snapshot_id == snap.snapshot_id
    assert loaded.kind == "daily_scan"
    assert loaded.segment == "Energy"
    assert loaded.as_of_session == _SESSION
    assert loaded.computed_at == snap.computed_at
    assert loaded.preset == "trend_follow"
    assert loaded.params == {"top_n": 3}
    assert loaded.rows == _rows("AAA", "BBB")
    assert loaded.row_count == 2


def test_read_by_id_missing_returns_none(store):
    """Reading an unknown id yields None (not an error)."""
    assert store.read_by_id("does-not-exist") is None


def test_read_latest_missing_returns_none(store):
    """Reading latest for an unseen segment yields None."""
    assert store.read_latest(kind="daily_scan", segment="Energy") is None


def test_read_latest_returns_newest_per_segment(store):
    """read_latest returns the most recently computed snapshot for the segment."""
    old = _snapshot(
        computed_at=datetime(2024, 1, 12, 8, 0, tzinfo=UTC), rows=_rows("OLD")
    )
    new = _snapshot(
        computed_at=datetime(2024, 1, 12, 9, 0, tzinfo=UTC), rows=_rows("NEW")
    )
    store.write_snapshot(old)
    store.write_snapshot(new)

    latest = store.read_latest(kind="daily_scan", segment="Energy")
    assert latest is not None
    assert [r["symbol"] for r in latest.rows] == ["NEW"]


def test_out_of_order_write_does_not_move_legacy_live_backward(store):
    """A late import with older computed metadata cannot replace latest."""
    newer = _snapshot(
        computed_at=datetime(2024, 1, 12, 9, 0, tzinfo=UTC),
        rows=_rows("NEW"),
    )
    older = _snapshot(
        computed_at=datetime(2024, 1, 12, 8, 0, tzinfo=UTC),
        rows=_rows("OLD"),
    )
    store.write_snapshot(newer)
    store.write_snapshot(older)

    latest = store.read_latest(kind="daily_scan", segment="Energy")

    assert latest.snapshot_id == newer.snapshot_id


def test_older_session_with_later_compute_time_is_archived(store):
    """Session ordering wins over a later migration timestamp."""
    newer = _snapshot(
        computed_at=datetime(2024, 1, 12, 9, 0, tzinfo=UTC),
        rows=_rows("NEW"),
    )
    older = _snapshot(
        computed_at=datetime(2024, 1, 13, 9, 0, tzinfo=UTC),
        rows=_rows("OLD"),
    ).model_copy(update={"as_of_session": date(2024, 1, 11)})
    store.write_snapshot(newer)
    store.write_snapshot(older)

    assert (
        store.read_latest(kind="daily_scan", segment="Energy").snapshot_id
        == newer.snapshot_id
    )
    assert {snapshot.snapshot_id for snapshot in store.list_snapshots()} == {
        newer.snapshot_id,
        older.snapshot_id,
    }


def test_read_latest_is_scoped_by_kind_and_segment(store):
    """Latest reads never cross kind or segment boundaries."""
    store.write_snapshot(_snapshot(segment="Energy", rows=_rows("ENE")))
    store.write_snapshot(_snapshot(segment="Financials", rows=_rows("FIN")))
    store.write_snapshot(
        _snapshot(kind="other_scan", segment="Energy", rows=_rows("OTH"))
    )

    energy = store.read_latest(kind="daily_scan", segment="Energy")
    fin = store.read_latest(kind="daily_scan", segment="Financials")
    assert [r["symbol"] for r in energy.rows] == ["ENE"]
    assert [r["symbol"] for r in fin.rows] == ["FIN"]


def test_empty_but_fresh_snapshot_round_trips(store):
    """An empty snapshot is a real, fresh record (distinct from 'never scanned')."""
    empty = _snapshot(rows=[])
    store.write_snapshot(empty)

    latest = store.read_latest(kind="daily_scan", segment="Energy")
    assert latest is not None
    assert latest.rows == []
    assert latest.row_count == 0
    assert latest.is_empty


def test_list_snapshots_newest_first_and_filters(store):
    """list_snapshots returns newest-first and honors kind/segment/limit filters."""
    base = datetime(2024, 1, 12, 8, 0, tzinfo=UTC)
    for i in range(3):
        store.write_snapshot(
            _snapshot(
                segment="Energy",
                computed_at=base + timedelta(minutes=i),
                rows=_rows(f"E{i}"),
            )
        )
    store.write_snapshot(_snapshot(segment="Financials", rows=_rows("FIN")))

    energy = store.list_snapshots(kind="daily_scan", segment="Energy")
    assert [s.rows[0]["symbol"] for s in energy] == ["E2", "E1", "E0"]

    capped = store.list_snapshots(kind="daily_scan", segment="Energy", limit=1)
    assert len(capped) == 1 and capped[0].rows[0]["symbol"] == "E2"

    everything = store.list_snapshots()
    assert len(everything) == 4


def test_prune_keeps_newest_per_kind_and_segment(store):
    """Pruning retains only the newest ``keep`` per (kind, segment) and reports deletes."""
    base = datetime(2024, 1, 12, 8, 0, tzinfo=UTC)
    for i in range(5):
        store.write_snapshot(
            _snapshot(
                segment="Energy",
                computed_at=base + timedelta(minutes=i),
                rows=_rows(f"E{i}"),
            )
        )
    for i in range(4):
        store.write_snapshot(
            _snapshot(
                segment="Financials",
                computed_at=base + timedelta(minutes=i),
                rows=_rows(f"F{i}"),
            )
        )

    deleted = store.prune_snapshots(keep=2)
    # 5 -> 2 (3 deleted) for Energy, 4 -> 2 (2 deleted) for Financials.
    assert deleted == 5

    energy = store.list_snapshots(kind="daily_scan", segment="Energy")
    fin = store.list_snapshots(kind="daily_scan", segment="Financials")
    assert [s.rows[0]["symbol"] for s in energy] == ["E4", "E3"]
    assert [s.rows[0]["symbol"] for s in fin] == ["F3", "F2"]


def test_prune_noop_when_within_retention(store):
    """Pruning below the retention count deletes nothing."""
    store.write_snapshot(_snapshot(rows=_rows("A")))
    assert store.prune_snapshots(keep=10) == 0
    assert len(store.list_snapshots()) == 1


def test_prune_rejects_zero_retention(store):
    """The facade cannot promise deletion of its authoritative LIVE row."""
    with pytest.raises(ValueError, match="at least 1"):
        store.prune_snapshots(keep=0)


def test_last_good_survives_a_failed_later_write(store):
    """A failed later write leaves the previous committed snapshot intact (last-good)."""
    good = _snapshot(
        computed_at=datetime(2024, 1, 12, 8, 0, tzinfo=UTC), rows=_rows("GOOD")
    )
    store.write_snapshot(good)

    # Simulate a later run that raises mid-write: reuse the same primary key so the
    # INSERT fails inside its transaction and rolls back without touching the good row.
    duplicate = ScanSnapshot(
        snapshot_id=good.snapshot_id,
        kind="daily_scan",
        segment="Energy",
        as_of_session=_SESSION,
        computed_at=datetime(2024, 1, 12, 9, 0, tzinfo=UTC),
        rows=_rows("SHOULD_NOT_PERSIST"),
    )
    with pytest.raises(Exception):
        store.write_snapshot(duplicate)

    latest = store.read_latest(kind="daily_scan", segment="Energy")
    assert latest is not None
    assert [r["symbol"] for r in latest.rows] == ["GOOD"]
    assert len(store.list_snapshots()) == 1


def test_snapshots_persist_across_reopen(tmp_path):
    """Snapshots survive closing and reopening the database."""
    db = tmp_path / "scan.db"
    first = SqliteScanSnapshotStore(db)
    snap = _snapshot(rows=_rows("PERSIST"))
    first.write_snapshot(snap)
    first.close()

    second = SqliteScanSnapshotStore(db)
    try:
        latest = second.read_latest(kind="daily_scan", segment="Energy")
        assert latest is not None
        assert [r["symbol"] for r in latest.rows] == ["PERSIST"]
    finally:
        second.close()


def test_default_scan_db_path_honors_env_override(monkeypatch, tmp_path):
    """The default path respects the OPENBB_TECHTRADE_SCAN_DB override."""
    target = tmp_path / "custom" / "scan.db"
    monkeypatch.setenv(SCAN_DB_ENV, str(target))
    assert default_scan_db_path() == target


def test_computed_at_must_be_timezone_aware():
    """A naive computed_at is rejected at model construction."""
    with pytest.raises(Exception):
        ScanSnapshot(
            segment="Energy",
            as_of_session=_SESSION,
            computed_at=datetime(2024, 1, 12, 8, 30),  # naive
        )


def test_legacy_facade_uses_only_canonical_snapshot_tables(tmp_path):
    """The compatibility API must not recreate its retired table."""
    db = tmp_path / "canonical.db"
    store = SqliteScanSnapshotStore(db)
    store.write_snapshot(_snapshot())
    store.close()

    with sqlite3.connect(db) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert "pi_eod_snapshot" in tables
    assert "pi_eod_live_pointer" in tables
    assert "scan_snapshot" not in tables


def test_snapshot_id_is_globally_unique_across_segments(store):
    """One legacy snapshot ID must resolve to exactly one segment."""
    first = _snapshot(segment="Energy")
    store.write_snapshot(first)

    duplicate = _snapshot(segment="Financials").model_copy(
        update={"snapshot_id": first.snapshot_id}
    )

    with pytest.raises(ValueError, match="snapshot_id already exists"):
        store.write_snapshot(duplicate)


def test_batch_snapshot_ids_round_trip_uniquely(store):
    """Atomic batch IDs resolve to their exact persisted segment."""
    persisted = store.write_snapshots(
        [_snapshot(segment="Energy"), _snapshot(segment="Financials")]
    )

    assert len({snapshot.snapshot_id for snapshot in persisted}) == 2
    assert {
        store.read_by_id(snapshot.snapshot_id).segment for snapshot in persisted
    } == {"Energy", "Financials"}


def test_rejected_staging_row_is_not_listed(store):
    """A failed validation candidate must stay invisible to legacy readers."""
    good = _snapshot(rows=[{"symbol": f"S{i}", "close": i + 1.0} for i in range(10)])
    store.write_snapshot(good)
    rejected = _snapshot(
        computed_at=good.computed_at + timedelta(minutes=1),
        rows=[{"symbol": "BAD", "close": None}],
    )

    with pytest.raises(ValueError, match="validation failed"):
        store.write_snapshot(rejected)

    listed = store.list_snapshots(kind="daily_scan", segment="Energy")
    assert [snapshot.snapshot_id for snapshot in listed] == [good.snapshot_id]
    assert store.read_by_id(rejected.snapshot_id) is None


def test_list_snapshots_is_not_silently_capped_at_fifty(store):
    """Compatibility history must include every retained canonical row."""
    base = datetime(2024, 1, 12, 8, 0, tzinfo=UTC)
    for index in range(55):
        store.write_snapshot(
            _snapshot(
                computed_at=base + timedelta(seconds=index),
                rows=_rows(f"S{index}"),
            )
        )

    assert len(store.list_snapshots(kind="daily_scan", segment="Energy")) == 55


def test_busy_timeout_constructor_argument_remains_compatible(tmp_path):
    """The retired store's public constructor still accepts its timeout."""
    store = SqliteScanSnapshotStore(
        tmp_path / "busy.db",
        busy_timeout_ms=1234,
    )
    try:
        assert store._store._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
    finally:
        store.close()


def test_prune_rolls_back_all_scopes_when_one_delete_fails(store):
    """Compatibility pruning is atomic across every legacy scope."""
    base = datetime(2024, 1, 12, 8, 0, tzinfo=UTC)
    for segment in ("Energy", "Financials"):
        for index in range(3):
            store.write_snapshot(
                _snapshot(
                    segment=segment,
                    computed_at=base + timedelta(seconds=index),
                    rows=_rows(f"{segment[0]}{index}"),
                )
            )
    store._store._conn.execute("""
        CREATE TRIGGER reject_financial_prune
        BEFORE DELETE ON pi_eod_snapshot
        WHEN OLD.entity_key = 'segment=financials'
        BEGIN
            SELECT RAISE(ABORT, 'reject prune');
        END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="reject prune"):
        store.prune_snapshots(keep=1)

    assert len(store.list_snapshots(kind="daily_scan", segment="Energy")) == 3
    assert len(store.list_snapshots(kind="daily_scan", segment="Financials")) == 3


def test_default_facade_uses_configured_canonical_backend(monkeypatch):
    """No explicit legacy path may create a second SQLite authority."""
    backend = object()
    monkeypatch.delenv(SCAN_DB_ENV, raising=False)
    monkeypatch.setattr(
        "openbb_techtrade.snapshots.sqlite.get_default_snapshot_store",
        lambda **_kwargs: backend,
    )

    store = SqliteScanSnapshotStore()

    assert store._store is backend


def test_default_facade_migrates_existing_legacy_sqlite_history(monkeypatch, tmp_path):
    """Upgrade keeps legacy rows reachable through the canonical backend."""
    legacy_db = tmp_path / "legacy.db"
    with sqlite3.connect(legacy_db) as connection:
        connection.executescript("""
            CREATE TABLE scan_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                segment TEXT NOT NULL,
                as_of_session TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                preset TEXT,
                params_json TEXT NOT NULL,
                rows_json TEXT NOT NULL,
                row_count INTEGER NOT NULL
            );
            INSERT INTO scan_snapshot VALUES (
                'legacy-id', 'daily_scan', 'Energy', '2024-01-12',
                '2024-01-12T22:00:00+00:00', 'trend_follow',
                '{\"top_n\":3}', '[{\"symbol\":\"XOM\"}]', 1
            );
            """)
    canonical = SqliteSnapshotStore(tmp_path / "canonical.db")
    monkeypatch.delenv(SCAN_DB_ENV, raising=False)
    monkeypatch.setattr(
        "openbb_techtrade.snapshots.sqlite.get_default_snapshot_store",
        lambda **_kwargs: canonical,
    )
    monkeypatch.setattr(
        "openbb_techtrade.snapshots.sqlite.legacy_scan_db_path",
        lambda: legacy_db,
    )

    facade = SqliteScanSnapshotStore()

    assert facade.read_by_id("legacy-id").rows == [{"symbol": "XOM"}]
    facade.close()


def test_canonical_multi_segment_job_round_trips_facade_ids(tmp_path):
    """Facade IDs remain unique when canonical rows share one job ID."""
    from openbb_techtrade.snapshot.registry import DEFAULT_DATASET_REGISTRY
    from openbb_techtrade.snapshot.store import SqliteSnapshotStore

    db = tmp_path / "canonical-multi.db"
    canonical = SqliteSnapshotStore(db)
    canonical.start_job("techtrade.scan", "shared-job")
    successes = []
    for segment in ("Energy", "Financials"):
        key = f"segment={segment}"
        payload = {
            "rows": [{"symbol": segment[0]}],
            "segment": segment,
            "as_of_session": _SESSION.isoformat(),
            "exchange_calendar": "XNYS",
            "preset": "breakout",
            "params": {"top_n": 5, "preset": "breakout"},
        }
        canonical.stage(
            "techtrade.scan",
            key,
            _SESSION,
            "shared-job",
            payload,
            row_count=1,
            engine_version="test",
            payload_schema_version="1",
        )
        definition = DEFAULT_DATASET_REGISTRY.require("techtrade.scan")
        assert canonical.validate(
            "techtrade.scan",
            key,
            _SESSION,
            "shared-job",
            lambda row: definition.validator(row, None),
        ).ok
        successes.append(("techtrade.scan", key, _SESSION, "shared-job"))
    canonical.publish_job("shared-job", successes)
    canonical.close()

    facade = SqliteScanSnapshotStore(db)
    try:
        energy = facade.read_latest(kind="daily_scan", segment="Energy")
        financials = facade.read_latest(kind="daily_scan", segment="Financials")
        assert energy.snapshot_id != financials.snapshot_id
        assert energy.preset == "breakout"
        assert energy.params["top_n"] == 5
        assert facade.read_by_id(energy.snapshot_id).segment == "Energy"
        assert facade.read_by_id(financials.snapshot_id).segment == "Financials"
    finally:
        facade.close()
