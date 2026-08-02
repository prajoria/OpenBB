"""MySqlPortfolioStore unit tests (#1744).

Uses a **SQLite-backed fake connection pool** to exercise every
:class:`MySqlPortfolioStore` method without a live MySQL. Rationale:

- The store's SQL is trivially portable (INSERT IGNORE has a SQLite
  equivalent via INSERT OR IGNORE; we translate at test-fixture level).
- We're testing PROTOCOL contract compliance, not MySQL SQL semantics
  — a live-MySQL test is separately marked ``@pytest.mark.integration``.

R7.11 twin notes on load-bearing tests.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from portfolio_snapshot_importer.mysql_store import (
    _PI_POSITION_DDL,
    _PI_SNAPSHOT_DDL,
    MySqlPortfolioStore,
)


class _SqliteConn:
    """Wrapper that makes sqlite3.Connection quack like mysql.connector."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self, dictionary: bool = False) -> Any:  # noqa: ARG002
        cur = self._conn.cursor()
        # rewrite MySQL %s placeholders to sqlite ?
        return _CursorShim(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        # Pool caller closes the wrapper; leave the real conn open.
        pass


class _CursorShim:
    """Cursor wrapper: rewrites %s -> ? and MySQL DDL to SQLite DDL."""

    _DDL_MAP: dict[str, str] = {
        _PI_SNAPSHOT_DDL: (
            "CREATE TABLE IF NOT EXISTS pi_snapshot ("
            " snapshot_id TEXT PRIMARY KEY,"
            " snapshot_date TEXT NOT NULL,"
            " user_id TEXT NOT NULL,"
            " source_filename TEXT NOT NULL,"
            " source_sha256 TEXT NOT NULL,"
            " imported_at TEXT NOT NULL DEFAULT (datetime('now')),"
            " row_count_raw INTEGER NOT NULL,"
            " row_count_kept INTEGER NOT NULL,"
            " row_count_skipped INTEGER NOT NULL,"
            " schema_version INTEGER NOT NULL,"
            " UNIQUE (source_sha256, user_id)"
            ")"
        ),
        _PI_POSITION_DDL: (
            "CREATE TABLE IF NOT EXISTS pi_position ("
            " position_id INTEGER PRIMARY KEY,"
            " snapshot_id TEXT NOT NULL,"
            " snapshot_date TEXT NOT NULL,"
            " user_id TEXT NOT NULL,"
            " account_number TEXT NOT NULL,"
            " account_name TEXT,"
            " basket_name TEXT,"
            " symbol TEXT NOT NULL,"
            " description TEXT,"
            " type TEXT,"
            " quantity REAL,"
            " last_price REAL,"
            " last_price_change REAL,"
            " current_value REAL,"
            " today_gain_loss_dollar REAL,"
            " today_gain_loss_percent REAL,"
            " total_gain_loss_dollar REAL,"
            " total_gain_loss_percent REAL,"
            " percent_of_account REAL,"
            " cost_basis_total REAL,"
            " average_cost_basis REAL,"
            " raw_row_number INTEGER NOT NULL,"
            " FOREIGN KEY (snapshot_id) REFERENCES pi_snapshot(snapshot_id)"
            ")"
        ),
    }

    def __init__(self, real: sqlite3.Cursor) -> None:
        self._real = real

    @staticmethod
    def _rewrite(sql: str) -> str:
        # Translate MySQL-only fragments to SQLite.
        translated = sql.replace("%s", "?").replace("INSERT IGNORE", "INSERT OR IGNORE")
        return _CursorShim._DDL_MAP.get(sql, translated)

    def execute(self, sql: str, params: tuple | None = None) -> Any:
        return self._real.execute(self._rewrite(sql), params or ())

    def executemany(self, sql: str, seq: list[tuple]) -> Any:
        return self._real.executemany(self._rewrite(sql), seq)

    def fetchone(self) -> Any:
        return self._real.fetchone()

    def fetchall(self) -> Any:
        return self._real.fetchall()

    def close(self) -> None:
        self._real.close()


class _FakePool:
    """Fake connection pool backed by a single in-memory SQLite DB."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def get_connection(self) -> _SqliteConn:
        return _SqliteConn(self._conn)


@pytest.fixture()
def fake_pool(tmp_path: Path) -> _FakePool:
    """Fresh in-file SQLite so foreign-key + persistence semantics apply."""
    return _FakePool(tmp_path / "pi_test.db")


@pytest.fixture()
def store(fake_pool: _FakePool) -> MySqlPortfolioStore:
    return MySqlPortfolioStore(connection_pool=fake_pool)


def _snap_meta(snapshot_id: str, sha: str, user: str = "u1") -> dict:
    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": "2026-08-01",
        "user_id": user,
        "source_filename": f"{snapshot_id}.csv",
        "source_sha256": sha,
        "row_count_raw": 10,
        "row_count_kept": 8,
        "row_count_skipped": 2,
    }


def _position_row(snapshot_id: str, symbol: str, i: int = 0) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": "2026-08-01",
        "user_id": "u1",
        "account_number": "****1234",
        "account_name": "Individual",
        "basket_name": None,
        "symbol": symbol,
        "description": f"{symbol} Inc.",
        "type": "STOCK",
        "quantity": 10.0,
        "last_price": 100.0,
        "last_price_change": 1.0,
        "current_value": 1000.0,
        "today_gain_loss_dollar": 10.0,
        "today_gain_loss_percent": 0.01,
        "total_gain_loss_dollar": 100.0,
        "total_gain_loss_percent": 0.1,
        "percent_of_account": 0.5,
        "cost_basis_total": 900.0,
        "average_cost_basis": 90.0,
        "raw_row_number": i,
    }


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_ensure_schema_creates_both_tables(store: MySqlPortfolioStore) -> None:
    """Schema bootstrap runs at construction — tables must exist afterwards."""
    with store._acquire() as conn:  # noqa: SLF001
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('pi_snapshot','pi_position')"
        )
        names = {row[0] for row in cur.fetchall()}
    assert names == {"pi_snapshot", "pi_position"}


def test_snapshot_exists_none_before_insert(store: MySqlPortfolioStore) -> None:
    assert store.snapshot_exists("nope", "u1") is None


def test_insert_snapshot_then_exists_finds_it(store: MySqlPortfolioStore) -> None:
    store.insert_snapshot(_snap_meta("snap-a", "abc123"))
    assert store.snapshot_exists("abc123", "u1") == "snap-a"


def test_insert_snapshot_is_idempotent_via_insert_ignore(
    store: MySqlPortfolioStore,
) -> None:
    """R7.11 twin: replace INSERT IGNORE with plain INSERT -> this test raises."""
    store.insert_snapshot(_snap_meta("snap-a", "abc123"))
    # Second call with same (sha, user) should NOT raise.
    store.insert_snapshot(_snap_meta("snap-b", "abc123"))
    # Original snap-a wins because INSERT IGNORE.
    assert store.snapshot_exists("abc123", "u1") == "snap-a"


def test_insert_positions_returns_row_count(store: MySqlPortfolioStore) -> None:
    store.insert_snapshot(_snap_meta("snap-a", "abc123"))
    rows = [_position_row("snap-a", s, i) for i, s in enumerate(["A", "B", "C"])]
    assert store.insert_positions(rows) == 3


def test_positions_for_returns_inserted_rows(store: MySqlPortfolioStore) -> None:
    store.insert_snapshot(_snap_meta("snap-a", "abc123"))
    store.insert_positions([_position_row("snap-a", "AAPL", 0)])
    rows = store.positions_for("snap-a")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


def test_positions_for_orders_by_account_then_symbol(
    store: MySqlPortfolioStore,
) -> None:
    store.insert_snapshot(_snap_meta("snap-a", "abc123"))
    a = _position_row("snap-a", "MSFT", 0)
    b = _position_row("snap-a", "AAPL", 1)
    store.insert_positions([a, b])
    rows = store.positions_for("snap-a")
    assert [r["symbol"] for r in rows] == ["AAPL", "MSFT"]


def test_list_snapshots_newest_first(store: MySqlPortfolioStore) -> None:
    store.insert_snapshot(
        {**_snap_meta("old", "sha-old"), "snapshot_date": "2026-01-01"}
    )
    store.insert_snapshot(
        {**_snap_meta("new", "sha-new"), "snapshot_date": "2026-06-01"}
    )
    rows = store.list_snapshots(user_id="u1")
    assert [r["snapshot_id"] for r in rows] == ["new", "old"]


def test_list_snapshots_filters_by_user(store: MySqlPortfolioStore) -> None:
    store.insert_snapshot(_snap_meta("a", "sha-a", user="u1"))
    store.insert_snapshot(_snap_meta("b", "sha-b", user="u2"))
    rows = store.list_snapshots(user_id="u2")
    assert len(rows) == 1
    assert rows[0]["snapshot_id"] == "b"


def test_latest_snapshot_returns_newest(store: MySqlPortfolioStore) -> None:
    store.insert_snapshot(
        {**_snap_meta("old", "sha-old"), "snapshot_date": "2026-01-01"}
    )
    store.insert_snapshot(
        {**_snap_meta("new", "sha-new"), "snapshot_date": "2026-06-01"}
    )
    row = store.latest_snapshot("u1")
    assert row is not None
    assert row["snapshot_id"] == "new"


def test_latest_snapshot_returns_none_for_unknown_user(
    store: MySqlPortfolioStore,
) -> None:
    assert store.latest_snapshot("nope") is None


def test_transaction_rolls_back_on_exception(store: MySqlPortfolioStore) -> None:
    """R7.11 twin: swap ``raise`` for ``pass`` in transaction() -> row leaks."""
    try:
        with store.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pi_snapshot(snapshot_id, snapshot_date, user_id, "
                "source_filename, source_sha256, row_count_raw, row_count_kept, "
                "row_count_skipped, schema_version) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("boom", "2026-01-01", "u1", "f", "sha", 0, 0, 0, 1),
            )
            cur.close()
            raise RuntimeError("intentional")
    except RuntimeError:
        pass
    assert store.snapshot_exists("sha", "u1") is None


def test_insert_positions_with_empty_list_returns_zero(
    store: MySqlPortfolioStore,
) -> None:
    """R7.11 twin: remove the `if not payload: return 0` -> executemany([]) may raise."""
    assert store.insert_positions([]) == 0


def test_fk_ordering_enforced_positions_require_snapshot_first(
    store: MySqlPortfolioStore,
) -> None:
    """Positions inserted without a matching snapshot MUST fail — FK enforcement."""
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_positions([_position_row("no-such-snap", "AAPL", 0)])
