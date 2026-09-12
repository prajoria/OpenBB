"""Tests for T5 P3.a — paper trading engine.

Coverage:

- Account creation is idempotent (re-instantiating the engine opens the
  same account without duplicating).
- ``submit_batch`` inserts one PENDING order per ticket.
- ``record_fill`` transitions PENDING → PARTIAL → FILLED across multiple
  fill events; loud on unknown order, overfill, cancelled/rejected/
  already-filled state.
- Cash side effects: buy debits cash+commission, sell credits cash-
  commission; buy that would drive cash negative raises.
- FIFO realized-P&L: sell walks open lots in age order and computes
  ``qty * (fill_price - lot_cost)``; sell that exceeds long position
  raises (no accidental short).
- Materialized position: quantity, avg_cost (weighted average on adds,
  unchanged on partial closes), cumulative realized_pl, all round-trip
  through get_positions.
- Cancel: PENDING → CANCELLED. Idempotent. Not allowed on terminal
  states.
- Protocol conformance.

R7.11 mutation-twin notes on every load-bearing assertion.
"""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from openbb_techtrade.execution import paper_engine as paper_engine_module
from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import (
    OrderStatus,
    PaperEngine,
    PaperEngineError,
    SqlitePaperEngine,
    _identity_key,
    get_default_engine,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Per-test SQLite path."""
    return tmp_path / "paper.db"


@pytest.fixture
def engine(db_path: Path) -> SqlitePaperEngine:
    """Fresh SqlitePaperEngine seeded with $100k starting cash."""
    return SqlitePaperEngine(db_path, starting_cash=Decimal("100000"))


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
# Account creation + idempotency
# ---------------------------------------------------------------------------


class TestAccountLifecycle:
    def test_read_only_open_does_not_initialize_schema(self, db_path: Path) -> None:
        db_path.touch()
        eng = SqlitePaperEngine(db_path, initialize=False)
        eng.close()

        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name LIKE 'pi_paper_%'"
            ).fetchall()
        assert tables == []

    def test_account_seeded_on_first_open(self, engine: SqlitePaperEngine) -> None:
        acct = engine.get_account()
        assert acct.account_id == "paper"
        assert acct.starting_cash == Decimal("100000")
        assert acct.cash == Decimal("100000")
        assert acct.realized_pl == Decimal("0")

    def test_reopening_same_db_preserves_account(self, db_path: Path) -> None:
        """R7.11 twin: dropping the SELECT-before-INSERT guard in
        ``_ensure_account`` would cause a duplicate PK error, or worse,
        silently reset cash. Verified — this test crashes with
        IntegrityError if guard removed.
        """
        eng1 = SqlitePaperEngine(db_path, starting_cash=Decimal("50000"))
        eng1.close()
        # Second open with a DIFFERENT starting_cash — must be ignored
        # because the account already exists.
        eng2 = SqlitePaperEngine(db_path, starting_cash=Decimal("999999"))
        acct = eng2.get_account()
        assert acct.starting_cash == Decimal("50000")

    def test_protocol_conformance(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: renaming ``submit_batch`` breaks isinstance()."""
        assert isinstance(engine, PaperEngine)


# ---------------------------------------------------------------------------
# submit_batch
# ---------------------------------------------------------------------------


class TestSubmitBatch:
    def test_submission_reserves_sqlite_writer_before_idempotency_read(
        self, engine: SqlitePaperEngine
    ) -> None:
        statements: list[str] = []
        engine._conn.set_trace_callback(statements.append)  # noqa: SLF001

        engine.submit_batch(_batch(_tk("MSFT")), plan_id="serialized")

        assert "BEGIN IMMEDIATE" in statements

    def test_shared_engine_serializes_concurrent_transactions(
        self, engine: SqlitePaperEngine
    ) -> None:
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def submit(plan_id: str, symbol: str) -> None:
            barrier.wait(timeout=5)
            try:
                engine.submit_batch(_batch(_tk(symbol)), plan_id=plan_id)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        workers = [
            threading.Thread(target=submit, args=("plan-a", "MSFT")),
            threading.Thread(target=submit, args=("plan-b", "AAPL")),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        assert errors == []
        assert len(engine.get_orders()) == 2

    def test_shared_engine_blocks_reads_during_write_transaction(
        self, engine: SqlitePaperEngine
    ) -> None:
        writer_started = threading.Event()
        release_writer = threading.Event()
        reader_finished = threading.Event()

        def hold_write() -> None:
            with engine._tx():  # noqa: SLF001
                writer_started.set()
                release_writer.wait(timeout=5)

        writer = threading.Thread(target=hold_write)
        reader = threading.Thread(
            target=lambda: (engine.get_orders(), reader_finished.set())
        )
        writer.start()
        assert writer_started.wait(timeout=5)
        reader.start()
        assert not reader_finished.wait(timeout=0.1)
        release_writer.set()
        writer.join(timeout=5)
        reader.join(timeout=5)
        assert reader_finished.is_set()

    def test_order_identity_encoding_is_unambiguous(self) -> None:
        assert _identity_key("a:b", "c") != _identity_key("a", "b:c")

    def test_batch_creates_pending_orders(self, engine: SqlitePaperEngine) -> None:
        ids = engine.submit_batch(_batch(_tk("MSFT", qty="10"), _tk("AAPL", qty="20")))
        assert len(ids) == 2
        assert all(i.startswith("ord_") for i in ids)
        assert all(UUID(i.removeprefix("ord_")).version == 4 for i in ids)
        pending = engine.get_orders(status=OrderStatus.PENDING)
        assert {o.symbol for o in pending} == {"MSFT", "AAPL"}

    def test_same_batch_submission_is_idempotent(
        self, engine: SqlitePaperEngine
    ) -> None:
        batch = _batch(_tk("MSFT"), _tk("AAPL"))

        first = engine.submit_batch(batch, plan_id="plan-retry")
        second = engine.submit_batch(batch, plan_id="plan-retry")

        assert second == first
        assert len(engine.get_orders()) == 2

    def test_retry_accepts_legacy_random_order_ids(
        self,
        engine: SqlitePaperEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        batch = _batch(_tk("MSFT"), _tk("AAPL"))
        engine.submit_batch(batch, plan_id="legacy-plan")
        expected = [
            "ord_ffffffff-ffff-4fff-8fff-ffffffffffff",
            "ord_00000000-0000-4000-8000-000000000001",
        ]
        engine._conn.execute(  # noqa: SLF001
            "UPDATE pi_paper_order SET order_id = ? WHERE symbol = 'MSFT'",
            (expected[0],),
        )
        engine._conn.execute(  # noqa: SLF001
            "UPDATE pi_paper_order SET order_id = ? WHERE symbol = 'AAPL'",
            (expected[1],),
        )
        monkeypatch.setattr(
            paper_engine_module,
            "_new_order_id",
            lambda _identity: "ord_00000000-0000-4000-8000-000000000999",
        )

        assert engine.submit_batch(batch, plan_id="legacy-plan") == expected

    def test_legacy_duplicate_tickets_fail_closed(
        self,
        engine: SqlitePaperEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        batch = _batch(_tk("MSFT"), _tk("MSFT"))
        engine.submit_batch(batch, plan_id="legacy-duplicates")
        monkeypatch.setattr(
            paper_engine_module,
            "_new_order_id",
            lambda _identity: "ord_00000000-0000-4000-8000-000000000999",
        )

        with pytest.raises(PaperEngineError, match="identity set"):
            engine.submit_batch(batch, plan_id="legacy-duplicates")

    def test_batch_sha_stamped_on_orders(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: dropping batch_sha256 from the INSERT breaks the
        reconciliation-by-batch query that P5 will need.
        """
        batch = _batch(_tk("MSFT"))
        engine.submit_batch(batch)
        orders = engine.get_orders()
        assert orders[0].batch_sha256 == batch.sha256()

    def test_plan_id_stamped(self, engine: SqlitePaperEngine) -> None:
        engine.submit_batch(_batch(_tk("MSFT")), plan_id="plan-abc")
        orders = engine.get_orders()
        assert orders[0].plan_id == "plan-abc"

    def test_missing_tickets_attr_raises(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: without the duck-type guard, a bare list would
        silently pass and later blow up on .tickets access mid-tx.
        """

        class NotABatch:
            pass

        with pytest.raises(PaperEngineError, match=".tickets"):
            engine.submit_batch(NotABatch())


# ---------------------------------------------------------------------------
# record_fill happy path + status transitions
# ---------------------------------------------------------------------------


class TestRecordFillLifecycle:
    def test_full_fill_moves_pending_to_filled(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [order] = engine.get_orders()
        assert order.status == OrderStatus.FILLED

    def test_partial_fill_stays_partial(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: if the status transition used > instead of ==
        (new_total > ordered_qty → FILLED), a partial would be flagged
        FILLED prematurely. Verified.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("6"), at=_t())
        [order] = engine.get_orders()
        assert order.status == OrderStatus.PARTIAL

    def test_second_fill_completes_partial(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("6"), at=_t())
        engine.record_fill(
            oid, price=Decimal("401"), filled_qty=Decimal("4"), at=_t(13)
        )
        [order] = engine.get_orders()
        assert order.status == OrderStatus.FILLED
        fills = engine.get_fills()
        assert len(fills) == 2


# ---------------------------------------------------------------------------
# record_fill loud rejections
# ---------------------------------------------------------------------------


class TestRecordFillLoudRejects:
    def test_unknown_order_id_raises(self, engine: SqlitePaperEngine) -> None:
        with pytest.raises(PaperEngineError, match="unknown order_id"):
            engine.record_fill(
                "ord_nope", price=Decimal("100"), filled_qty=Decimal("1"), at=_t()
            )

    def test_overfill_raises(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: dropping the ordered_qty vs new_total check lets
        overfill through — a real Fidelity fill for more than ordered
        would corrupt cash and position math. Verified.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="overfill"):
            engine.record_fill(
                oid, price=Decimal("400"), filled_qty=Decimal("11"), at=_t()
            )

    def test_non_positive_price_raises(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="price"):
            engine.record_fill(
                oid, price=Decimal("0"), filled_qty=Decimal("10"), at=_t()
            )

    def test_negative_commission_raises(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        with pytest.raises(PaperEngineError, match="commission"):
            engine.record_fill(
                oid,
                price=Decimal("400"),
                filled_qty=Decimal("10"),
                at=_t(),
                commission=Decimal("-1"),
            )

    def test_fill_on_cancelled_raises(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.cancel_order(oid)
        with pytest.raises(PaperEngineError, match="CANCELLED"):
            engine.record_fill(
                oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t()
            )

    def test_fill_on_already_filled_raises(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: without the FILLED short-circuit, a duplicate
        fill event would decrement position twice and double the
        realized P&L. Verified.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        with pytest.raises(PaperEngineError, match="already FILLED"):
            engine.record_fill(
                oid, price=Decimal("400"), filled_qty=Decimal("1"), at=_t()
            )


# ---------------------------------------------------------------------------
# Cash side effects
# ---------------------------------------------------------------------------


class TestCashSideEffects:
    def test_buy_debits_cash(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        # 100000 - 4000 = 96000
        assert engine.get_account().cash == Decimal("96000")

    def test_buy_debits_commission_too(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: dropping ``+ fill.commission`` from cash_delta
        lets commission slip past unpaid. Verified.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            oid,
            price=Decimal("400"),
            filled_qty=Decimal("10"),
            at=_t(),
            commission=Decimal("5"),
        )
        assert engine.get_account().cash == Decimal("95995")

    def test_sell_credits_cash_minus_commission(
        self, engine: SqlitePaperEngine
    ) -> None:
        # Establish a long first: buy 10 @ 400.
        [buy_id] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            buy_id, price=Decimal("400"), filled_qty=Decimal("10"), at=_t()
        )
        # Now sell 5 @ 410 with $2 commission.
        [sell_id] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="5")))
        engine.record_fill(
            sell_id,
            price=Decimal("410"),
            filled_qty=Decimal("5"),
            at=_t(13),
            commission=Decimal("2"),
        )
        # Cash after buy: 96000. Sell adds 5*410 - 2 = 2048. Total 98048.
        assert engine.get_account().cash == Decimal("98048")

    def test_buy_exceeding_cash_raises(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: dropping the ``new_cash < 0`` guard silently lets
        the paper engine hold a negative cash balance — hides the
        real-world margin call that would have blown up manually.
        Verified.
        """
        # Try to buy 1000 shares @ 200 = 200_000 with only 100_000 cash.
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="1000")))
        with pytest.raises(PaperEngineError, match="cash negative"):
            engine.record_fill(
                oid, price=Decimal("200"), filled_qty=Decimal("1000"), at=_t()
            )


# ---------------------------------------------------------------------------
# FIFO realized P&L
# ---------------------------------------------------------------------------


class TestFIFORealizedPL:
    def test_sell_computes_realized_pl_from_fifo_lots(
        self, engine: SqlitePaperEngine
    ) -> None:
        """Buy 10 @ 400, then buy 10 @ 420, then sell 15 @ 430.

        FIFO: 10 * (430-400) + 5 * (430-420) = 300 + 50 = 350 realized.

        R7.11 twin: if the FIFO walker used LIFO order (newest lot first),
        we'd realize 10 * (430-420) + 5 * (430-400) = 100 + 150 = 250
        instead of 350. Verified — the 350 vs 250 gap uniquely identifies
        the ordering.
        """
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t(10)
        )
        [b2] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            b2, price=Decimal("420"), filled_qty=Decimal("10"), at=_t(11)
        )
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="15")))
        engine.record_fill(
            s1, price=Decimal("430"), filled_qty=Decimal("15"), at=_t(12)
        )

        # Account realized_pl reflects sum of both lots' realized.
        acct = engine.get_account()
        assert acct.realized_pl == Decimal("350")

    def test_sell_exceeding_long_position_raises(
        self, engine: SqlitePaperEngine
    ) -> None:
        """R7.11 twin: dropping the ``remaining > 0`` check silently
        creates a phantom short — the sell would appear to succeed but
        no lot would be closed. Verified.
        """
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="15")))
        with pytest.raises(PaperEngineError, match="exceeds long position"):
            engine.record_fill(
                s1, price=Decimal("410"), filled_qty=Decimal("15"), at=_t(13)
            )


# ---------------------------------------------------------------------------
# Materialized position math
# ---------------------------------------------------------------------------


class TestPositionMath:
    def test_first_buy_creates_position(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [pos] = engine.get_positions()
        assert pos.symbol == "MSFT"
        assert pos.quantity == Decimal("10")
        assert pos.avg_cost == Decimal("400")

    def test_add_uses_weighted_average_cost(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: dropping the weighted-average formula (simple
        replacement with new price) would give avg_cost=420 instead of
        the correct 410. Verified.
        """
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [b2] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(
            b2, price=Decimal("420"), filled_qty=Decimal("10"), at=_t(13)
        )
        [pos] = engine.get_positions()
        assert pos.quantity == Decimal("20")
        assert pos.avg_cost == Decimal("410")

    def test_full_close_flattens_position(self, engine: SqlitePaperEngine) -> None:
        [b1] = engine.submit_batch(_batch(_tk("MSFT", qty="10")))
        engine.record_fill(b1, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        [s1] = engine.submit_batch(_batch(_tk("MSFT", action="Sell", qty="10")))
        engine.record_fill(
            s1, price=Decimal("410"), filled_qty=Decimal("10"), at=_t(13)
        )
        # Position table has row with qty=0 → get_positions filters it out.
        positions = engine.get_positions()
        assert positions == []


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_pending_moves_to_cancelled(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.cancel_order(oid)
        [order] = engine.get_orders()
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_is_idempotent(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: without the ``if CANCELLED: return`` short-
        circuit, a second cancel would re-UPDATE the row (harmless) but
        wouldn't log — the idempotency contract is what callers depend
        on.
        """
        [oid] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.cancel_order(oid)
        engine.cancel_order(oid, reason="operator retry")  # no raise
        [order] = engine.get_orders()
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_filled_raises(self, engine: SqlitePaperEngine) -> None:
        [oid] = engine.submit_batch(_batch(_tk("MSFT")))
        engine.record_fill(oid, price=Decimal("400"), filled_qty=Decimal("10"), at=_t())
        with pytest.raises(PaperEngineError, match="cannot cancel"):
            engine.cancel_order(oid)


# ---------------------------------------------------------------------------
# get_default_engine factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_strict_mysql_mode_does_not_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openbb_techtrade.execution import mysql_paper_engine

        monkeypatch.setattr(paper_engine_module.config, "paper_engine", lambda: "mysql")
        monkeypatch.setattr(
            mysql_paper_engine,
            "MysqlPaperEngine",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mysql unavailable")),
        )

        with pytest.raises(RuntimeError, match="mysql unavailable"):
            get_default_engine(allow_fallback=False)

    def test_factory_uses_central_config(self, tmp_path, monkeypatch) -> None:
        target = tmp_path / "central-config.db"
        monkeypatch.setattr(
            paper_engine_module.config, "paper_engine", lambda: "sqlite"
        )
        monkeypatch.setattr(paper_engine_module.config, "paper_db_path", lambda: target)

        get_default_engine()

        assert target.exists()

    def test_explicit_path_precedes_central_config_path(
        self, tmp_path, monkeypatch
    ) -> None:
        target = tmp_path / "explicit.db"
        monkeypatch.setattr(
            paper_engine_module.config, "paper_engine", lambda: "sqlite"
        )
        monkeypatch.setattr(
            paper_engine_module.config,
            "paper_db_path",
            lambda: pytest.fail("config path must not be read"),
        )

        get_default_engine(db_path=target)

        assert target.exists()

    def test_env_var_selects_db_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target = tmp_path / "paper.db"
        monkeypatch.setenv("PI_PAPER_ENGINE", "sqlite")
        monkeypatch.setenv("PI_PAPER_DB", str(target))
        eng = get_default_engine()
        assert isinstance(eng, SqlitePaperEngine)
        assert target.exists()

    def test_arg_overrides_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PI_PAPER_ENGINE", "sqlite")
        monkeypatch.setenv("PI_PAPER_DB", "/nonexistent/should-not-be-used.db")
        arg_target = tmp_path / "arg.db"
        get_default_engine(db_path=arg_target)  # side effect: creates arg_target
        assert arg_target.exists()
        # The env-var-target must NOT be created.
        assert not Path("/nonexistent/should-not-be-used.db").exists()


# ---------------------------------------------------------------------------
# get_fills filtering
# ---------------------------------------------------------------------------


class TestGetFills:
    def test_since_filters_out_older(self, engine: SqlitePaperEngine) -> None:
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
