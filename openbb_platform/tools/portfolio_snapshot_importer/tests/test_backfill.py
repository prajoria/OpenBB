"""Backfill CLI + module tests (#1744).

Populates a temp SQLite with real snapshot data, runs
``backfill_sqlite_to_mysql`` against a fake MySQL pool, asserts row
counts propagate correctly. Also smokes the ``backfill-to-mysql`` CLI
subcommand end-to-end via ``argparse``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from portfolio_snapshot_importer import SqlitePortfolioStore
from portfolio_snapshot_importer.backfill import backfill_sqlite_to_mysql
from portfolio_snapshot_importer.cli import build_parser, main
from portfolio_snapshot_importer.mysql_store import MySqlPortfolioStore

from .test_mysql_store import _FakePool, _position_row, _snap_meta


def _seed_sqlite(path: Path) -> None:
    """Populate a temp SQLite with 3 snapshots + a few positions each."""
    store = SqlitePortfolioStore(path)
    try:
        for i, sha in enumerate(["sha-a", "sha-b", "sha-c"]):
            snap_id = f"snap-{sha}"
            store.insert_snapshot(_snap_meta(snap_id, sha, user="u1"))
            positions = [
                _position_row(snap_id, s, j)
                for j, s in enumerate(["AAPL", "MSFT", "NVDA"])
            ]
            store.insert_positions(positions)
    finally:
        store.close()


def test_backfill_copies_all_snapshots_and_positions(tmp_path: Path) -> None:
    """R7.11 twin: swap ``insert_snapshot(meta)`` for ``pass`` -> counts stay zero."""
    src = tmp_path / "src.db"
    _seed_sqlite(src)
    dst_store = MySqlPortfolioStore(connection_pool=_FakePool(tmp_path / "dst.db"))

    result = backfill_sqlite_to_mysql(source_sqlite=src, mysql_store=dst_store)

    assert result["snapshots"] == 3
    assert result["positions"] == 9  # 3 snapshots × 3 positions
    assert result["skipped_existing"] == 0
    # Verify persistence.
    assert len(dst_store.list_snapshots(user_id="u1")) == 3
    for sha in ("sha-a", "sha-b", "sha-c"):
        assert dst_store.snapshot_exists(sha, "u1") is not None


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _seed_sqlite(src)
    dst_store = MySqlPortfolioStore(connection_pool=_FakePool(tmp_path / "dst.db"))

    result = backfill_sqlite_to_mysql(
        source_sqlite=src, dry_run=True, mysql_store=dst_store
    )

    assert result["snapshots"] == 3
    assert result["positions"] == 9
    # But nothing landed.
    assert dst_store.list_snapshots(user_id="u1") == []


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    """Second run skips existing snapshots — INSERT IGNORE + snapshot_exists probe."""
    src = tmp_path / "src.db"
    _seed_sqlite(src)
    dst_store = MySqlPortfolioStore(connection_pool=_FakePool(tmp_path / "dst.db"))

    first = backfill_sqlite_to_mysql(source_sqlite=src, mysql_store=dst_store)
    second = backfill_sqlite_to_mysql(source_sqlite=src, mysql_store=dst_store)

    assert first["snapshots"] == 3
    assert second["snapshots"] == 0  # nothing new
    assert second["skipped_existing"] == 3


def test_backfill_filters_by_user_id(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    store = SqlitePortfolioStore(src)
    try:
        store.insert_snapshot(_snap_meta("a", "sha-a", user="alice"))
        store.insert_snapshot(_snap_meta("b", "sha-b", user="bob"))
    finally:
        store.close()

    dst_store = MySqlPortfolioStore(connection_pool=_FakePool(tmp_path / "dst.db"))
    result = backfill_sqlite_to_mysql(
        source_sqlite=src, user_id="alice", mysql_store=dst_store
    )
    assert result["snapshots"] == 1
    assert dst_store.snapshot_exists("sha-a", "alice") is not None
    assert dst_store.snapshot_exists("sha-b", "bob") is None


def test_backfill_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        backfill_sqlite_to_mysql(source_sqlite=tmp_path / "nope.db")


def test_backfill_cli_dry_run_smoke(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI wiring smoke — dry-run mode doesn't require a MySQL adapter."""
    src = tmp_path / "src.db"
    _seed_sqlite(src)

    rc = main(
        [
            "backfill-to-mysql",
            "--from",
            str(src),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "snapshots=3" in out
    assert "positions=9" in out
    assert "dry-run" in out.lower()


def test_parser_accepts_both_from_and_source_alias() -> None:
    """``--from`` and ``--source`` map to the same dest so old scripts don't break."""
    p = build_parser()
    ns_a = p.parse_args(["backfill-to-mysql", "--from", "/tmp/x"])
    ns_b = p.parse_args(["backfill-to-mysql", "--source", "/tmp/x"])
    assert ns_a.source == ns_b.source == "/tmp/x"
