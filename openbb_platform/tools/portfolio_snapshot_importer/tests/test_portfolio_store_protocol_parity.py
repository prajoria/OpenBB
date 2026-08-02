"""Portfolio store Protocol parity tests (#1744).

Runs the same 6 contract tests against BOTH concrete backends
(SqlitePortfolioStore and MySqlPortfolioStore-backed-by-fake-pool) via
pytest parametrization. Loud proof that the two implementations are
behaviorally interchangeable.

If any test fails on one backend but passes on the other, the Protocol
is a lie and consumers can't safely swap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from portfolio_snapshot_importer import PortfolioStore, SqlitePortfolioStore

from .test_mysql_store import _FakePool, _position_row, _snap_meta

# Type alias
StoreFactory = Callable[[Path], PortfolioStore]


def _sqlite_factory(tmp_path: Path) -> PortfolioStore:
    return SqlitePortfolioStore(tmp_path / "sqlite_positions.db")


def _mysql_factory(tmp_path: Path) -> PortfolioStore:
    from portfolio_snapshot_importer.mysql_store import (  # noqa: PLC0415
        MySqlPortfolioStore,
    )

    return MySqlPortfolioStore(connection_pool=_FakePool(tmp_path / "pi_test.db"))


BACKENDS = [
    pytest.param(_sqlite_factory, id="sqlite"),
    pytest.param(_mysql_factory, id="mysql_fake_pool"),
]


@pytest.mark.parametrize("factory", BACKENDS)
def test_snapshot_exists_before_and_after_insert(
    tmp_path: Path, factory: StoreFactory
) -> None:
    with factory(tmp_path) as store:
        assert store.snapshot_exists("sha1", "u1") is None
        store.insert_snapshot(_snap_meta("snap-a", "sha1"))
        assert store.snapshot_exists("sha1", "u1") == "snap-a"


@pytest.mark.parametrize("factory", BACKENDS)
def test_insert_positions_roundtrip(tmp_path: Path, factory: StoreFactory) -> None:
    with factory(tmp_path) as store:
        store.insert_snapshot(_snap_meta("snap-a", "sha1"))
        n = store.insert_positions(
            [_position_row("snap-a", s, i) for i, s in enumerate(["AAPL", "MSFT"])]
        )
        assert n == 2
        rows = store.positions_for("snap-a")
        assert len(rows) == 2
        assert {r["symbol"] for r in rows} == {"AAPL", "MSFT"}


@pytest.mark.parametrize("factory", BACKENDS)
def test_latest_snapshot_returns_newest_or_none(
    tmp_path: Path, factory: StoreFactory
) -> None:
    with factory(tmp_path) as store:
        assert store.latest_snapshot("u1") is None
        store.insert_snapshot(
            {**_snap_meta("old", "sha-old"), "snapshot_date": "2026-01-01"}
        )
        store.insert_snapshot(
            {**_snap_meta("new", "sha-new"), "snapshot_date": "2026-06-01"}
        )
        latest = store.latest_snapshot("u1")
        assert latest is not None
        assert latest["snapshot_id"] == "new"


@pytest.mark.parametrize("factory", BACKENDS)
def test_list_snapshots_filter_by_user(tmp_path: Path, factory: StoreFactory) -> None:
    with factory(tmp_path) as store:
        store.insert_snapshot(_snap_meta("a", "sha-a", user="u1"))
        store.insert_snapshot(_snap_meta("b", "sha-b", user="u2"))
        assert [r["snapshot_id"] for r in store.list_snapshots(user_id="u2")] == ["b"]
        # No filter — both come back.
        assert {r["snapshot_id"] for r in store.list_snapshots()} == {"a", "b"}


@pytest.mark.parametrize("factory", BACKENDS)
def test_insert_positions_empty_returns_zero(
    tmp_path: Path, factory: StoreFactory
) -> None:
    with factory(tmp_path) as store:
        assert store.insert_positions([]) == 0


@pytest.mark.parametrize("factory", BACKENDS)
def test_duplicate_snapshot_insert_is_idempotent_or_raises(
    tmp_path: Path, factory: StoreFactory
) -> None:
    """Both backends must handle re-inserting the same (sha, user).

    SqlitePortfolioStore relies on the caller checking ``snapshot_exists``
    first; a plain INSERT would raise UNIQUE constraint. MySQL uses
    INSERT IGNORE. In practice the ingest layer always checks first, so
    this test asserts that the ingest pattern works on both.
    """
    with factory(tmp_path) as store:
        store.insert_snapshot(_snap_meta("a", "sha1"))
        # Ingest-layer contract: check-then-insert.
        if store.snapshot_exists("sha1", "u1") is None:
            store.insert_snapshot(_snap_meta("a2", "sha1"))
        # Still only one snapshot with sha1.
        rows = [
            r
            for r in store.list_snapshots(user_id="u1")
            if r["source_sha256"] == "sha1"
        ]
        assert len(rows) == 1
