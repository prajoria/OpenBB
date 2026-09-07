"""Contract tests for the append-only scan snapshot store (issue #1934).

Fully offline. Exercises the ``ScanSnapshotStore`` contract through the SQLite
implementation: round trips, latest-by-``(kind, segment)``, list/filter, retention,
and the last-good guarantee (a failed later write never clobbers the previous
committed snapshot).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
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
    old = _snapshot(computed_at=datetime(2024, 1, 12, 8, 0, tzinfo=UTC), rows=_rows("OLD"))
    new = _snapshot(computed_at=datetime(2024, 1, 12, 9, 0, tzinfo=UTC), rows=_rows("NEW"))
    store.write_snapshot(old)
    store.write_snapshot(new)

    latest = store.read_latest(kind="daily_scan", segment="Energy")
    assert latest is not None
    assert [r["symbol"] for r in latest.rows] == ["NEW"]


def test_read_latest_is_scoped_by_kind_and_segment(store):
    """Latest reads never cross kind or segment boundaries."""
    store.write_snapshot(_snapshot(segment="Energy", rows=_rows("ENE")))
    store.write_snapshot(_snapshot(segment="Financials", rows=_rows("FIN")))
    store.write_snapshot(_snapshot(kind="other_scan", segment="Energy", rows=_rows("OTH")))

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
            _snapshot(segment="Energy", computed_at=base + timedelta(minutes=i), rows=_rows(f"E{i}"))
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
            _snapshot(segment="Energy", computed_at=base + timedelta(minutes=i), rows=_rows(f"E{i}"))
        )
    for i in range(4):
        store.write_snapshot(
            _snapshot(segment="Financials", computed_at=base + timedelta(minutes=i), rows=_rows(f"F{i}"))
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


def test_last_good_survives_a_failed_later_write(store):
    """A failed later write leaves the previous committed snapshot intact (last-good)."""
    good = _snapshot(computed_at=datetime(2024, 1, 12, 8, 0, tzinfo=UTC), rows=_rows("GOOD"))
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
