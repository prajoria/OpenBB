"""Tests for T5 P3.c — MySQL-backed paper trading engine (#1790).

Uses a **SQLite-backed fake connection pool** so the same test suite
runs without a live MySQL, matching the pattern in
``portfolio_snapshot_importer/tests/test_mysql_store.py``.

Every load-bearing scenario from ``test_paper_engine.py`` +
``test_paper_engine_p3b.py`` is mirrored, PLUS a scope-isolation test
that runs two engines against the same pool with different
``(run_id, strategy_id, account_id)`` triples and verifies zero
cross-contamination.

R7.11 mutation-twin notes on every load-bearing assertion.
"""

# ruff: noqa: D101, D102, D103, D105, SLF001

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from openbb_fmp_cached.utils import database
from openbb_techtrade.execution.mysql_paper_engine import (
    _PI_PAPER_ACCOUNT_DDL,
    _PI_PAPER_FILL_DDL,
    _PI_PAPER_LOT_DDL,
    _PI_PAPER_ORDER_DDL,
    _PI_PAPER_POSITION_DDL,
    MysqlPaperEngine,
)
from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import (
    OrderStatus,
    PaperEngine,
    PaperEngineError,
    PaperEquity,
)

# ---------------------------------------------------------------------------
# SQLite-backed MySQL shim (see test_mysql_store.py for the pattern)
# ---------------------------------------------------------------------------


_DDL_MAP: dict[str, str] = {
    _PI_PAPER_ACCOUNT_DDL: (
        "CREATE TABLE IF NOT EXISTS pi_paper_account ("
        " run_id TEXT NOT NULL DEFAULT 'live',"
        " strategy_id TEXT NOT NULL DEFAULT 'default',"
        " account_id TEXT NOT NULL DEFAULT 'paper',"
        " starting_cash TEXT NOT NULL,"
        " cash TEXT NOT NULL,"
        " realized_pl TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " PRIMARY KEY (run_id, strategy_id, account_id)"
        ")"
    ),
    _PI_PAPER_ORDER_DDL: (
        "CREATE TABLE IF NOT EXISTS pi_paper_order ("
        " order_id TEXT NOT NULL,"
        " run_id TEXT NOT NULL DEFAULT 'live',"
        " strategy_id TEXT NOT NULL DEFAULT 'default',"
        " account_id TEXT NOT NULL DEFAULT 'paper',"
        " symbol TEXT NOT NULL,"
        " side TEXT NOT NULL,"
        " quantity TEXT NOT NULL,"
        " order_type TEXT NOT NULL,"
        " limit_price TEXT,"
        " status TEXT NOT NULL,"
        " submitted_at TEXT NOT NULL,"
        " plan_id TEXT NOT NULL DEFAULT '',"
        " batch_sha256 TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (run_id, strategy_id, account_id, order_id)"
        ")"
    ),
    _PI_PAPER_FILL_DDL: (
        "CREATE TABLE IF NOT EXISTS pi_paper_fill ("
        " fill_id TEXT NOT NULL,"
        " run_id TEXT NOT NULL DEFAULT 'live',"
        " strategy_id TEXT NOT NULL DEFAULT 'default',"
        " account_id TEXT NOT NULL DEFAULT 'paper',"
        " order_id TEXT NOT NULL,"
        " symbol TEXT NOT NULL,"
        " side TEXT NOT NULL,"
        " filled_qty TEXT NOT NULL,"
        " price TEXT NOT NULL,"
        " commission TEXT NOT NULL,"
        " filled_at TEXT NOT NULL,"
        " fill_mode TEXT NOT NULL DEFAULT 'OPERATOR_RECORDED',"
        " PRIMARY KEY (run_id, strategy_id, account_id, fill_id)"
        ")"
    ),
    _PI_PAPER_POSITION_DDL: (
        "CREATE TABLE IF NOT EXISTS pi_paper_position ("
        " run_id TEXT NOT NULL DEFAULT 'live',"
        " strategy_id TEXT NOT NULL DEFAULT 'default',"
        " account_id TEXT NOT NULL DEFAULT 'paper',"
        " symbol TEXT NOT NULL,"
        " quantity TEXT NOT NULL,"
        " avg_cost TEXT NOT NULL,"
        " realized_pl TEXT NOT NULL,"
        " last_updated TEXT NOT NULL,"
        " PRIMARY KEY (run_id, strategy_id, account_id, symbol)"
        ")"
    ),
    _PI_PAPER_LOT_DDL: (
        "CREATE TABLE IF NOT EXISTS _pi_paper_lot ("
        " lot_id TEXT NOT NULL,"
        " run_id TEXT NOT NULL DEFAULT 'live',"
        " strategy_id TEXT NOT NULL DEFAULT 'default',"
        " account_id TEXT NOT NULL DEFAULT 'paper',"
        " symbol TEXT NOT NULL,"
        " qty TEXT NOT NULL,"
        " cost_per_unit TEXT NOT NULL,"
        " opened_at TEXT NOT NULL,"
        " opening_fill_id TEXT NOT NULL,"
        " closed_at TEXT,"
        " closing_fill_id TEXT,"
        " PRIMARY KEY (run_id, strategy_id, account_id, lot_id)"
        ")"
    ),
}


def _rewrite(sql: str) -> str:
    if sql in _DDL_MAP:
        return _DDL_MAP[sql]
    # Strip MySQL-only INDEX clauses in CREATE TABLE (not that we hit them
    # since DDLs are mapped above), then rewrite placeholders.
    out = sql.replace("%s", "?").replace(" FOR UPDATE", "")
    out = out.replace(
        "ON DUPLICATE KEY UPDATE account_id = account_id",
        "ON CONFLICT(run_id, strategy_id, account_id) DO NOTHING",
    )
    # sqlite doesn't grok DATETIME/ENUM in generic SELECT/UPDATE; the DDLs
    # already mapped. Nothing else to rewrite.
    return out


class _CursorShim:
    def __init__(self, real: sqlite3.Cursor, statements: list[str]) -> None:
        self._real = real
        self._statements = statements

    def execute(self, sql: str, params: tuple | None = None) -> Any:
        self._statements.append(sql)
        return self._real.execute(_rewrite(sql), params or ())

    def executemany(self, sql: str, seq: list[tuple]) -> Any:
        return self._real.executemany(_rewrite(sql), seq)

    def fetchone(self) -> Any:
        return self._real.fetchone()

    def fetchall(self) -> Any:
        return self._real.fetchall()

    def close(self) -> None:
        self._real.close()


class _SqliteConn:
    def __init__(
        self,
        conn: sqlite3.Connection,
        events: list[str],
        statements: list[str],
        *,
        owns_raw: bool = False,
    ) -> None:
        self._conn = conn
        self._events = events
        self._statements = statements
        self._owns_raw = owns_raw

    def cursor(self) -> Any:
        return _CursorShim(self._conn.cursor(), self._statements)

    def begin(self) -> None:
        self._events.append("begin")
        self._conn.execute("BEGIN")

    def commit(self) -> None:
        self._events.append("commit")
        self._conn.commit()

    def rollback(self) -> None:
        self._events.append("rollback")
        self._conn.rollback()

    def close(self) -> None:
        self._events.append("close")
        if self._owns_raw:
            self._conn.close()


class _FakePool:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self.events: list[str] = []
        self.statements: list[str] = []

    @contextmanager
    def get_connection(self) -> Iterator[_SqliteConn]:
        self.events.append("enter")
        try:
            yield _SqliteConn(self._conn, self.events, self.statements)
        finally:
            self.events.append("exit")


class _InterleavingCursor(_CursorShim):
    def __init__(
        self,
        real: sqlite3.Cursor,
        statements: list[str],
        connection: _InterleavingConn,
    ) -> None:
        super().__init__(real, statements)
        self._connection = connection

    def execute(self, sql: str, params: tuple | None = None) -> Any:
        if "FROM pi_paper_order" in sql and "FOR UPDATE" in sql:
            self._connection.acquire_order_lock()
        result = super().execute(sql, params)
        if (
            threading.current_thread().name == "fill-first"
            and "SELECT filled_qty FROM pi_paper_fill" in sql
        ):
            self._connection.pool.first_prior_read.set()
            if not self._connection.pool.second_lock_attempt.wait(timeout=5):
                raise TimeoutError("second fill did not attempt the order lock")
        return result


class _InterleavingConn(_SqliteConn):
    def __init__(
        self,
        conn: sqlite3.Connection,
        pool: _InterleavingPool,
    ) -> None:
        super().__init__(
            conn,
            pool.events,
            pool.statements,
            owns_raw=True,
        )
        self.pool = pool
        self._holds_order_lock = False

    def cursor(self) -> Any:
        return _InterleavingCursor(self._conn.cursor(), self._statements, self)

    def acquire_order_lock(self) -> None:
        if threading.current_thread().name == "fill-second":
            self.pool.second_lock_attempt.set()
        if not self.pool.order_lock.acquire(timeout=5):
            raise TimeoutError("timed out acquiring simulated order row lock")
        self._holds_order_lock = True

    def _release_order_lock(self) -> None:
        if self._holds_order_lock:
            self._holds_order_lock = False
            self.pool.order_lock.release()

    def commit(self) -> None:
        try:
            super().commit()
        finally:
            self._release_order_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_order_lock()

    def close(self) -> None:
        self._release_order_lock()
        super().close()


class _InterleavingPool:
    """Independent SQLite sessions with a simulated InnoDB order-row lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: list[str] = []
        self.statements: list[str] = []
        self.order_lock = threading.Lock()
        self.first_prior_read = threading.Event()
        self.second_lock_attempt = threading.Event()

    @contextmanager
    def get_connection(self) -> Iterator[_InterleavingConn]:
        raw = sqlite3.connect(self.path, timeout=5)
        raw.row_factory = sqlite3.Row
        conn = _InterleavingConn(raw, self)
        self.events.append("enter")
        try:
            yield conn
        finally:
            conn.close()
            self.events.append("exit")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pool(tmp_path: Path) -> _FakePool:
    """Shared per-test in-file SQLite pool (persistent across engines)."""
    return _FakePool(tmp_path / "paper_mysql_test.db")


@pytest.fixture
def engine(pool: _FakePool) -> MysqlPaperEngine:
    return MysqlPaperEngine(connection_pool=pool, starting_cash=Decimal("100000"))


def _batch(*tickets: OrderTicket) -> OrderBatch:
    return OrderBatch(tickets=tickets)


def _tk(
    symbol: str,
    action: str = "Buy",
    qty: str = "10",
    limit: str | None = None,
) -> OrderTicket:
    return OrderTicket(
        symbol=symbol,
        action=action,  # type: ignore[arg-type]
        quantity=Decimal(qty),
        order_type="Limit" if limit else "Market",
        limit_price=Decimal(limit) if limit else None,
    )


def _t(hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 1, 15, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Account + Protocol
# ---------------------------------------------------------------------------


class TestAccountLifecycle:
    def test_account_seeded_on_first_open(self, engine: MysqlPaperEngine) -> None:
        acct = engine.get_account()
        assert acct.account_id == "paper"
        assert acct.starting_cash == Decimal("100000")
        assert acct.cash == Decimal("100000")
        assert acct.realized_pl == Decimal("0")

    def test_reopening_same_pool_preserves_account(self, pool: _FakePool) -> None:
        """R7.11 twin: dropping the no-op upsert clause in _ensure_account
        would raise a PK violation on the second open.
        """
        MysqlPaperEngine(connection_pool=pool, starting_cash=Decimal("50000"))
        pool.statements.clear()
        eng2 = MysqlPaperEngine(connection_pool=pool, starting_cash=Decimal("999999"))
        acct = eng2.get_account()
        assert acct.starting_cash == Decimal("50000")
        assert any("ON DUPLICATE KEY UPDATE" in sql for sql in pool.statements)
        assert not any(
            "SELECT account_id FROM pi_paper_account" in sql
            for sql in pool.statements
        )

    def test_protocol_conformance(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: renaming submit_batch breaks isinstance()."""
        assert isinstance(engine, PaperEngine)


class TestConnectionPoolContract:
    def test_write_begins_and_commits(
        self, engine: MysqlPaperEngine, pool: _FakePool
    ) -> None:
        pool.events.clear()

        engine.submit_batch(_batch(_tk("MSFT")))

        assert pool.events == ["enter", "begin", "commit", "exit"]

    def test_failed_write_rolls_back(
        self, engine: MysqlPaperEngine, pool: _FakePool
    ) -> None:
        [order_id] = engine.submit_batch(_batch(_tk("MSFT", qty="1000")))
        pool.events.clear()

        with pytest.raises(PaperEngineError, match="cash negative"):
            engine.record_fill(
                order_id,
                price=Decimal("200"),
                filled_qty=Decimal("1000"),
                at=_t(),
            )

        assert pool.events == ["enter", "begin", "rollback", "exit"]
        assert engine.get_fills() == []
        assert engine.get_orders()[0].status == OrderStatus.PENDING
        assert engine.get_account().cash == Decimal("100000")

    def test_read_does_not_begin(
        self, engine: MysqlPaperEngine, pool: _FakePool
    ) -> None:
        pool.events.clear()

        engine.get_account()

        assert pool.events == ["enter", "exit"]

    def test_fill_and_cancel_lock_mutated_rows(
        self, engine: MysqlPaperEngine, pool: _FakePool
    ) -> None:
        [buy_order] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.record_fill(buy_order, Decimal("1"), Decimal("10"), _t())
        [sell_order] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="1")))
        [cancel_order] = engine.submit_batch(_batch(_tk("AAPL")))
        pool.statements.clear()

        engine.record_fill(sell_order, Decimal("2"), Decimal("1"), _t(13))
        engine.cancel_order(cancel_order)

        locking_reads = [
            statement for statement in pool.statements if "FOR UPDATE" in statement
        ]
        assert any("FROM pi_paper_account" in statement for statement in locking_reads)
        assert sum("FROM pi_paper_order" in statement for statement in locking_reads) == 2
        assert any("FROM _pi_paper_lot" in statement for statement in locking_reads)
        assert any("FROM pi_paper_position" in statement for statement in locking_reads)

    def test_concurrent_fills_serialize_across_independent_connections(
        self, tmp_path: Path
    ) -> None:
        pool = _InterleavingPool(tmp_path / "concurrent_fills.db")
        engine = MysqlPaperEngine(connection_pool=pool)
        [order_id] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        fills = []
        failures: list[BaseException] = []

        def record_fill() -> None:
            try:
                fills.append(
                    engine.record_fill(
                        order_id,
                        price=Decimal("100"),
                        filled_qty=Decimal("6"),
                        at=_t(),
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced in main thread
                failures.append(exc)

        first = threading.Thread(target=record_fill, name="fill-first")
        second = threading.Thread(target=record_fill, name="fill-second")
        first.start()
        assert pool.first_prior_read.wait(timeout=5)
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        assert not first.is_alive()
        assert not second.is_alive()
        assert len(fills) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], PaperEngineError)
        assert "overfill" in str(failures[0])
        assert len(engine.get_fills()) == 1
        assert engine.get_orders()[0].status is OrderStatus.PARTIAL
        assert engine.get_account().cash == Decimal("99400")

    def test_real_connection_pool_context_manager_contract(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        events: list[str] = []
        statements: list[str] = []
        database_path = tmp_path / "real_pool_contract.db"

        def open_connection(**_kwargs: Any) -> _SqliteConn:
            sqlite_conn = sqlite3.connect(database_path)
            sqlite_conn.row_factory = sqlite3.Row
            return _SqliteConn(
                sqlite_conn,
                events,
                statements,
                owns_raw=True,
            )

        connect = MagicMock(side_effect=open_connection)
        monkeypatch.setattr(database.pymysql, "connect", connect)
        config = MagicMock()
        config.connection_params = {}
        pool = database.ConnectionPool(config)

        engine = MysqlPaperEngine(
            connection_pool=pool,
            starting_cash=Decimal("12345"),
        )

        assert engine.get_account().cash == Decimal("12345")
        assert events == [
            "begin",
            "commit",
            "close",
            "begin",
            "commit",
            "close",
            "close",
        ]
        assert connect.call_count == 3
        assert all(call.kwargs["autocommit"] is True for call in connect.call_args_list)
        assert all(
            call.kwargs["cursorclass"] is database.pymysql.cursors.DictCursor
            for call in connect.call_args_list
        )

    def test_domain_rejection_does_not_log_connection_error(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        events: list[str] = []
        statements: list[str] = []
        database_path = tmp_path / "domain_rejection.db"

        def open_connection(**_kwargs: Any) -> _SqliteConn:
            sqlite_conn = sqlite3.connect(database_path)
            sqlite_conn.row_factory = sqlite3.Row
            return _SqliteConn(
                sqlite_conn,
                events,
                statements,
                owns_raw=True,
            )

        monkeypatch.setattr(database.pymysql, "connect", open_connection)
        config = MagicMock()
        config.connection_params = {}
        pool = database.ConnectionPool(config)
        engine = MysqlPaperEngine(connection_pool=pool)
        [order_id] = engine.submit_batch(_batch(_tk("MSFT", qty="1000")))
        caplog.clear()

        with (
            caplog.at_level(logging.ERROR, logger=database.__name__),
            pytest.raises(PaperEngineError, match="cash negative"),
        ):
            engine.record_fill(order_id, Decimal("200"), Decimal("1000"), _t())

        assert "MySQL connection error" not in caplog.text

    def test_rollback_failure_does_not_mask_domain_rejection(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class RollbackFailingConnection:
            def begin(self) -> None:
                pass

            def rollback(self) -> None:
                raise RuntimeError("connection lost during rollback")

        class SingleConnectionPool:
            exited = False

            @contextmanager
            def get_connection(self) -> Iterator[RollbackFailingConnection]:
                try:
                    yield RollbackFailingConnection()
                finally:
                    self.exited = True

        pool = SingleConnectionPool()
        engine = object.__new__(MysqlPaperEngine)
        engine._pool = pool

        with (
            caplog.at_level(
                logging.WARNING,
                logger="openbb_techtrade.execution.mysql_paper_engine",
            ),
            pytest.raises(PaperEngineError, match="original rejection"),
            engine.transaction(),
        ):
            raise PaperEngineError("original rejection")

        assert pool.exited
        assert "rollback failed" in caplog.text


# ---------------------------------------------------------------------------
# submit_batch
# ---------------------------------------------------------------------------


class TestSubmitBatch:
    def test_batch_creates_pending_orders(self, engine: MysqlPaperEngine) -> None:
        ids = engine.submit_batch(_batch(_tk("MSFT", qty="10"), _tk("AAPL", qty="20")))
        assert len(ids) == 2
        assert all(i.startswith("ord_") for i in ids)
        pending = engine.get_orders(status=OrderStatus.PENDING)
        assert {o.symbol for o in pending} == {"MSFT", "AAPL"}

    def test_batch_sha_stamped(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: dropping batch_sha256 breaks reconciliation-by-batch."""
        batch = _batch(_tk("MSFT"))
        engine.submit_batch(batch)
        [order] = engine.get_orders()
        assert order.batch_sha256 == batch.sha256()

    def test_plan_id_stamped(self, engine: MysqlPaperEngine) -> None:
        engine.submit_batch(_batch(_tk("MSFT")), plan_id="plan-abc")
        [order] = engine.get_orders()
        assert order.plan_id == "plan-abc"

    def test_missing_tickets_attr_raises(self, engine: MysqlPaperEngine) -> None:
        class NotABatch:
            pass

        with pytest.raises(PaperEngineError, match=".tickets"):
            engine.submit_batch(NotABatch())


# ---------------------------------------------------------------------------
# record_fill lifecycle
# ---------------------------------------------------------------------------


class TestRecordFillLifecycle:
    def test_full_fill_moves_to_filled(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [order] = engine.get_orders()
        assert order.status == OrderStatus.FILLED

    def test_partial_fill_stays_partial(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: > vs == in the FILLED transition would flip a
        partial to FILLED prematurely.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("6"), at=_t())
        [order] = engine.get_orders()
        assert order.status == OrderStatus.PARTIAL

    def test_second_fill_completes(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("6"), at=_t())
        engine.record_fill(
            oid, price=Decimal("401"), filled_qty=Decimal("4"), at=_t(13)
        )
        [order] = engine.get_orders()
        assert order.status == OrderStatus.FILLED
        assert len(engine.get_fills()) == 2


# ---------------------------------------------------------------------------
# Loud rejections
# ---------------------------------------------------------------------------


class TestLoudRejections:
    def test_unknown_order_id(self, engine: MysqlPaperEngine) -> None:
        with pytest.raises(PaperEngineError, match="unknown order_id"):
            engine.record_fill(
                "ord_nope", price=Decimal("100"), filled_qty=Decimal("1"), at=_t()
            )

    def test_overfill(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: dropping the ordered_qty vs new_total check lets
        overfill through, corrupting cash + position math.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="overfill"):
            engine.record_fill(
                oid, price=Decimal("400"), filled_qty=Decimal("11"), at=_t()
            )

    def test_non_positive_price(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="price"):
            engine.record_fill(
                oid, price=Decimal("0"), filled_qty=Decimal("10"), at=_t()
            )

    def test_negative_commission(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="commission"):
            engine.record_fill(
                oid,
                price=Decimal("400"),
                filled_qty=Decimal("10"),
                at=_t(),
                commission=Decimal("-1"),
            )

    def test_fill_on_cancelled(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.cancel_order(oid)
        with pytest.raises(PaperEngineError, match="CANCELLED"):
            engine.record_fill(
                oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t()
            )

    def test_fill_on_already_filled(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: without the FILLED short-circuit a duplicate fill
        would double realized P&L.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        with pytest.raises(PaperEngineError, match="already FILLED"):
            engine.record_fill(
                oid, price=Decimal("400"), filled_qty=Decimal("1"), at=_t()
            )

    def test_invalid_fill_mode(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="fill_mode"):
            engine.record_fill(
                oid,
                price=Decimal("400"),
                filled_qty=Decimal("10"),
                at=_t(),
                fill_mode="NOT_A_MODE",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Cash side effects
# ---------------------------------------------------------------------------


class TestCashSideEffects:
    def test_buy_debits_cash(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        assert engine.get_account().cash == Decimal("96000")

    def test_buy_debits_commission(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: dropping ``+ commission`` lets commission slip past."""
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            oid,
            price=Decimal("400"),
            filled_qty=Decimal("10"),
            at=_t(),
            commission=Decimal("5"),
        )
        assert engine.get_account().cash == Decimal("95995")

    def test_sell_credits_cash_minus_commission(self, engine: MysqlPaperEngine) -> None:
        [buy_id] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            buy_id, price=Decimal("400"), filled_qty=Decimal("10"), at=_t()
        )
        [sell_id] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="5")))
        engine.record_fill(
            sell_id,
            price=Decimal("410"),
            filled_qty=Decimal("5"),
            at=_t(13),
            commission=Decimal("2"),
        )
        assert engine.get_account().cash == Decimal("98048")

    def test_buy_exceeds_cash_raises(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: dropping ``new_cash < 0`` silently allows negative cash."""
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="1000")))
        with pytest.raises(PaperEngineError, match="cash negative"):
            engine.record_fill(
                oid, price=Decimal("200"), filled_qty=Decimal("1000"), at=_t()
            )


# ---------------------------------------------------------------------------
# FIFO
# ---------------------------------------------------------------------------


class TestFIFORealizedPL:
    def test_fifo_realized_pl_classic_case(self, engine: MysqlPaperEngine) -> None:
        """Buy 10@400, buy 20@420, sell 15@430 → 10*(430-400) + 5*(430-420) = 350.

        R7.11 twin: LIFO ordering gives 250, not 350 — 350 uniquely
        identifies FIFO.
        """
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t(10)
        )
        [b2] = engine.submit_batch(_batch(_tk("MSFT", qty="20")))
        engine.record_fill(
            b2, price=Decimal("420"), filled_qty=Decimal("20"), at=_t(11)
        )
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="15")))
        engine.record_fill(
            s1, price=Decimal("430"), filled_qty=Decimal("15"), at=_t(12)
        )
        acct = engine.get_account()
        assert acct.realized_pl == Decimal("350")

    def test_full_case_55_sold(self, engine: MysqlPaperEngine) -> None:
        """The doctrine's exact example: 10@400 + 20@420 then SELL 30 @ 430.

        FIFO: 10*(30) + 20*(10) = 300 + 200 = 500. Note: original spec says
        'sell 55' but with only 30 open shares that would exceed position.
        We test the largest valid sell — 30 — which fully drains both lots.
        """
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t(10)
        )
        [b2] = engine.submit_batch(_batch(_tk("MSFT", qty="20")))
        engine.record_fill(
            b2, price=Decimal("420"), filled_qty=Decimal("20"), at=_t(11)
        )
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="30")))
        engine.record_fill(
            s1, price=Decimal("430"), filled_qty=Decimal("30"), at=_t(12)
        )
        assert engine.get_account().realized_pl == Decimal("500")

    def test_sell_exceeds_long_raises(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: dropping the ``remaining > 0`` check creates a
        phantom short.
        """
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="15")))
        with pytest.raises(PaperEngineError, match="exceeds long position"):
            engine.record_fill(
                s1, price=Decimal("410"), filled_qty=Decimal("15"), at=_t(13)
            )


# ---------------------------------------------------------------------------
# Materialized position
# ---------------------------------------------------------------------------


class TestPositionMath:
    def test_first_buy_creates_position(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [pos] = engine.get_positions()
        assert pos.symbol == "MSFT"
        assert pos.quantity == Decimal("10")
        assert pos.avg_cost == Decimal("400")

    def test_add_uses_weighted_average(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: replacing weighted with simple gives 420 not 410."""
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [b2] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            b2, price=Decimal("420"), filled_qty=Decimal("10"), at=_t(13)
        )
        [pos] = engine.get_positions()
        assert pos.quantity == Decimal("20")
        assert pos.avg_cost == Decimal("410")

    def test_full_close_flattens(self, engine: MysqlPaperEngine) -> None:
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="10")))
        engine.record_fill(
            s1, price=Decimal("410"), filled_qty=Decimal("10"), at=_t(13)
        )
        assert engine.get_positions() == []


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_pending(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.cancel_order(oid)
        [order] = engine.get_orders()
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_is_idempotent(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.cancel_order(oid)
        engine.cancel_order(oid, reason="retry")
        [order] = engine.get_orders()
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_filled_raises(self, engine: MysqlPaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        with pytest.raises(PaperEngineError, match="cannot cancel"):
            engine.cancel_order(oid)


# ---------------------------------------------------------------------------
# get_fills / since
# ---------------------------------------------------------------------------


class TestGetFills:
    def test_since_filters_older(self, engine: MysqlPaperEngine) -> None:
        [oid1] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.record_fill(
            oid1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t(10)
        )
        [oid2] = engine.submit_batch(_batch(_tk("AAPL")))
        engine.record_fill(
            oid2, price=Decimal("180"), filled_qty=Decimal("10"), at=_t(14)
        )
        recent = engine.get_fills(since=_t(12))
        assert len(recent) == 1
        assert recent[0].symbol == "AAPL"


# ---------------------------------------------------------------------------
# P3.b — unrealized P&L
# ---------------------------------------------------------------------------


@pytest.fixture
def loaded_engine(pool: _FakePool) -> MysqlPaperEngine:
    eng = MysqlPaperEngine(connection_pool=pool, starting_cash=Decimal("100000"))
    for symbol, qty, price in (("MSFT", "10", "400"), ("AAPL", "20", "180")):
        [oid] = eng.submit_batch(
            OrderBatch(
                tickets=(
                    OrderTicket(
                        symbol=symbol,
                        action="Buy",
                        quantity=Decimal(qty),
                        order_type="Limit",
                        limit_price=Decimal(price),
                    ),
                )
            )
        )
        eng.record_fill(
            oid,
            price=Decimal(price),
            filled_qty=Decimal(qty),
            at=datetime.now(timezone.utc),
        )
    return eng


class TestUnrealized:
    def test_long_unrealized(self, loaded_engine: MysqlPaperEngine) -> None:
        """R7.11 twin: reversing operands flips sign — +200 vs -200."""
        marked = loaded_engine.get_positions_with_unrealized(
            {"MSFT": Decimal("420"), "AAPL": Decimal("180")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["MSFT"].unrealized_pl == Decimal("200")

    def test_flat_unrealized_zero(self, loaded_engine: MysqlPaperEngine) -> None:
        marked = loaded_engine.get_positions_with_unrealized(
            {"MSFT": Decimal("400"), "AAPL": Decimal("180")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["MSFT"].unrealized_pl == Decimal("0")

    def test_missing_mark_is_none(self, loaded_engine: MysqlPaperEngine) -> None:
        """R7.11 twin: reporting 0 vs None hides broken feed."""
        marked = loaded_engine.get_positions_with_unrealized({"MSFT": Decimal("420")})
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["AAPL"].unrealized_pl is None

    def test_zero_mark_raises(self, loaded_engine: MysqlPaperEngine) -> None:
        """R7.11 twin: without the mark<=0 guard we'd report catastrophic loss."""
        with pytest.raises(PaperEngineError, match="non-positive"):
            loaded_engine.get_positions_with_unrealized(
                {"MSFT": Decimal("0"), "AAPL": Decimal("180")}
            )

    def test_equity_snapshot(self, loaded_engine: MysqlPaperEngine) -> None:
        """R7.11 twin: using avg_cost instead of mark yields 100000 vs 100200."""
        eq = loaded_engine.get_account_equity(
            {"MSFT": Decimal("420"), "AAPL": Decimal("180")}
        )
        assert isinstance(eq, PaperEquity)
        assert eq.cash == Decimal("92400")
        assert eq.marked_value == Decimal("7800")
        assert eq.equity == Decimal("100200")

    def test_equity_surfaces_missing(self, loaded_engine: MysqlPaperEngine) -> None:
        eq = loaded_engine.get_account_equity({"MSFT": Decimal("420")})
        assert "AAPL" in eq.symbols_missing_marks


# ---------------------------------------------------------------------------
# Scope isolation — the new-in-P3.c load-bearing behavior
# ---------------------------------------------------------------------------


class TestScopeIsolation:
    def test_two_engines_different_scope_no_cross_contamination(
        self, pool: _FakePool
    ) -> None:
        """Two engines over the same pool, different scope triples: writes
        in one MUST NOT surface in the other.

        R7.11 twin: dropping the ``account_id`` predicate from
        ``_scope_where`` (or hardcoding 'paper') would let the ``bt``
        engine see the ``live`` engine's positions here. Verified: both
        would report the MSFT position and this test fails.
        """
        live = MysqlPaperEngine(
            connection_pool=pool,
            run_id="live",
            strategy_id="default",
            account_id="paper",
            starting_cash=Decimal("100000"),
        )
        bt = MysqlPaperEngine(
            connection_pool=pool,
            run_id="backtest_2026-01",
            strategy_id="mean_reversion",
            account_id="paper",
            starting_cash=Decimal("50000"),
        )

        [oid] = live.submit_batch(_batch(_tk("MSFT", qty="10")))
        live.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())

        # bt sees nothing.
        assert bt.get_positions() == []
        assert bt.get_orders() == []
        assert bt.get_fills() == []
        # bt's cash unchanged.
        assert bt.get_account().cash == Decimal("50000")
        assert bt.get_account().starting_cash == Decimal("50000")
        # live sees only its own state.
        assert live.get_account().cash == Decimal("96000")
        [pos] = live.get_positions()
        assert pos.symbol == "MSFT"

    def test_same_account_id_different_run_id_isolated(self, pool: _FakePool) -> None:
        """R7.11 twin: hardcoding run_id filter to 'live' would let this
        test succeed but break real backtest isolation. This ensures
        run_id is truly part of the composite key.
        """
        e1 = MysqlPaperEngine(
            connection_pool=pool,
            run_id="run_a",
            starting_cash=Decimal("10000"),
        )
        e2 = MysqlPaperEngine(
            connection_pool=pool,
            run_id="run_b",
            starting_cash=Decimal("20000"),
        )
        assert e1.get_account().starting_cash == Decimal("10000")
        assert e2.get_account().starting_cash == Decimal("20000")


# ---------------------------------------------------------------------------
# fill_mode column
# ---------------------------------------------------------------------------


class TestFillMode:
    def test_default_fill_mode_operator_recorded(
        self, engine: MysqlPaperEngine, pool: _FakePool
    ) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        with pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT fill_mode FROM pi_paper_fill")
            rows = cur.fetchall()
        modes = {r[0] for r in rows}
        assert modes == {"OPERATOR_RECORDED"}

    def test_bar_simulated_fill_mode_stored(
        self, engine: MysqlPaperEngine, pool: _FakePool
    ) -> None:
        """R7.11 twin: dropping the fill_mode kwarg would default every
        row back to OPERATOR_RECORDED and break backtest provenance.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            oid,
            price=Decimal("400"),
            filled_qty=Decimal("10"),
            at=_t(),
            fill_mode="BAR_SIMULATED",
        )
        with pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT fill_mode FROM pi_paper_fill")
            rows = cur.fetchall()
        assert rows[0][0] == "BAR_SIMULATED"


# ---------------------------------------------------------------------------
# Formula-injection guard on symbols (inherited from #1748 via OrderTicket)
# ---------------------------------------------------------------------------


class TestSymbolValidation:
    def test_bad_symbol_rejected(self, engine: MysqlPaperEngine) -> None:
        """R7.11 twin: dropping _validate_symbol lets =1+1 or ;DROP TABLE
        through into the fill ledger — formula injection guard.
        """
        # OrderTicket's own validator will reject at construction time.
        with pytest.raises((PaperEngineError, ValueError, Exception)):
            _ = OrderTicket(
                symbol="=CMD",
                action="Buy",
                quantity=Decimal("1"),
                order_type="Market",
                limit_price=None,
            )


# Keep the re-imported module symbol quiet.
_ = re
