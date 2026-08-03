"""Tests for T5 P3.b — unrealized P&L (#1766)."""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import (
    PaperEngineError,
    PaperEquity,
    SqlitePaperEngine,
)


@pytest.fixture
def engine(tmp_path: Path) -> SqlitePaperEngine:
    """Engine with $100k, one MSFT long (10 @ 400) and one AAPL long (20 @ 180)."""
    eng = SqlitePaperEngine(tmp_path / "paper.db", starting_cash=Decimal("100000"))
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


# ---------------------------------------------------------------------------
# get_positions_with_unrealized happy path
# ---------------------------------------------------------------------------


class TestUnrealizedHappyPath:
    def test_long_position_unrealized_pl_correct(
        self, engine: SqlitePaperEngine
    ) -> None:
        """MSFT: 10 shares @ 400 basis, mark 420 → unrealized = 10 * 20 = 200.

        R7.11 twin: if the formula reversed the operands (`avg_cost -
        mark_price`), the sign would flip. Verified — a positive delta
        with correct formula is +200; with reversed, -200.
        """
        marked = engine.get_positions_with_unrealized(
            {"MSFT": Decimal("420"), "AAPL": Decimal("180")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["MSFT"].unrealized_pl == Decimal("200")

    def test_flat_position_unrealized_pl_zero(self, engine: SqlitePaperEngine) -> None:
        """When mark == avg_cost, unrealized_pl == 0 (not None)."""
        marked = engine.get_positions_with_unrealized(
            {"MSFT": Decimal("400"), "AAPL": Decimal("180")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["MSFT"].unrealized_pl == Decimal("0")

    def test_underwater_position_unrealized_negative(
        self, engine: SqlitePaperEngine
    ) -> None:
        """AAPL: 20 shares @ 180, mark 175 → unrealized = 20 * -5 = -100."""
        marked = engine.get_positions_with_unrealized(
            {"MSFT": Decimal("400"), "AAPL": Decimal("175")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["AAPL"].unrealized_pl == Decimal("-100")

    def test_mark_value_equals_qty_times_mark(self, engine: SqlitePaperEngine) -> None:
        marked = engine.get_positions_with_unrealized(
            {"MSFT": Decimal("420"), "AAPL": Decimal("175")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["MSFT"].mark_value == Decimal("4200")
        assert by_sym["AAPL"].mark_value == Decimal("3500")

    def test_unrealized_pct_uses_avg_cost_as_denominator(
        self, engine: SqlitePaperEngine
    ) -> None:
        """MSFT +5% mark → pct == 5.

        R7.11 twin: dividing by mark_price instead of avg_cost gives
        ~4.76%. Verified — formula that divides by avg_cost yields
        exactly 5, mark-based yields 5/1.05 ≈ 4.762.
        """
        marked = engine.get_positions_with_unrealized(
            {"MSFT": Decimal("420"), "AAPL": Decimal("180")}
        )
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["MSFT"].unrealized_pl_pct == Decimal("5")


# ---------------------------------------------------------------------------
# Missing marks: loud-empty (None), not silent-zero
# ---------------------------------------------------------------------------


class TestMissingMarksLoudEmpty:
    def test_missing_symbol_gets_none_unrealized(
        self, engine: SqlitePaperEngine
    ) -> None:
        """R7.11 twin: reporting 0 instead of None hides that we held
        AAPL but the price feed didn't cover it. Verified — a caller
        checking `unrealized_pl == 0` would be misled to think AAPL is
        marked-to-market when it's not.
        """
        marked = engine.get_positions_with_unrealized({"MSFT": Decimal("420")})
        by_sym = {m.symbol: m for m in marked}
        assert by_sym["AAPL"].mark_price is None
        assert by_sym["AAPL"].mark_value is None
        assert by_sym["AAPL"].unrealized_pl is None
        assert by_sym["AAPL"].unrealized_pl_pct is None

    def test_all_marks_missing_returns_all_none(
        self, engine: SqlitePaperEngine
    ) -> None:
        marked = engine.get_positions_with_unrealized({})
        assert all(m.mark_price is None for m in marked)
        assert all(m.unrealized_pl is None for m in marked)


# ---------------------------------------------------------------------------
# Zero / negative mark raises loudly
# ---------------------------------------------------------------------------


class TestZeroOrNegativeMarkRaises:
    def test_zero_mark_raises(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: without the ``mark <= 0`` guard the caller would
        get unrealized_pl == qty × -avg_cost, silently reporting a
        catastrophic loss when the real problem is a broken feed.
        """
        with pytest.raises(PaperEngineError, match="non-positive"):
            engine.get_positions_with_unrealized(
                {"MSFT": Decimal("0"), "AAPL": Decimal("180")}
            )

    def test_negative_mark_raises(self, engine: SqlitePaperEngine) -> None:
        with pytest.raises(PaperEngineError, match="non-positive"):
            engine.get_positions_with_unrealized(
                {"MSFT": Decimal("-10"), "AAPL": Decimal("180")}
            )


# ---------------------------------------------------------------------------
# Short position sign
# ---------------------------------------------------------------------------


class TestShortPositionSign:
    def test_short_profits_when_mark_drops(self, tmp_path: Path) -> None:
        """Short 10 shares at basis 400 (position quantity = -10).
        Mark drops to 380 → unrealized = -10 * (380 - 400) = -10 * -20 = +200.

        We can't easily open a real short via record_fill in P3.a
        (that would raise `exceeds long position`). We simulate a short
        by manipulating the position table directly for this unit
        test — the sign math is what we're validating.

        R7.11 twin: if the formula used ``abs(quantity)`` we'd
        incorrectly get -200 for the short's profit.
        """
        eng = SqlitePaperEngine(tmp_path / "paper.db", starting_cash=Decimal("100000"))
        # Manually write a short position for test purposes.
        eng._conn.execute(  # noqa: SLF001
            "INSERT INTO pi_paper_position "
            "(account_id, symbol, quantity, avg_cost, realized_pl, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("paper", "MSFT", "-10", "400", "0", "2026-01-01T00:00:00+00:00"),
        )

        marked = eng.get_positions_with_unrealized({"MSFT": Decimal("380")})
        [m] = marked
        assert m.quantity == Decimal("-10")
        assert m.unrealized_pl == Decimal("200")  # short profited
        eng.close()


# ---------------------------------------------------------------------------
# get_account_equity
# ---------------------------------------------------------------------------


class TestGetAccountEquity:
    def test_equity_equals_cash_plus_marked_value(
        self, engine: SqlitePaperEngine
    ) -> None:
        """MSFT 10 @ 400 (marked 420) + AAPL 20 @ 180 (marked 180).

        Cash after fills = 100000 - 4000 - 3600 = 92400.
        Marked value = 10*420 + 20*180 = 4200 + 3600 = 7800.
        Equity = 92400 + 7800 = 100200.

        R7.11 twin: using avg_cost instead of mark gives 100000 (flat)
        instead of 100200 (up 200 unrealized).
        """
        eq = engine.get_account_equity({"MSFT": Decimal("420"), "AAPL": Decimal("180")})
        assert isinstance(eq, PaperEquity)
        assert eq.cash == Decimal("92400")
        assert eq.marked_value == Decimal("7800")
        assert eq.equity == Decimal("100200")
        assert eq.unrealized_pl == Decimal("200")
        assert eq.symbols_missing_marks == ()

    def test_missing_mark_surfaces_symbol(self, engine: SqlitePaperEngine) -> None:
        """R7.11 twin: silently excluding the symbol from
        symbols_missing_marks hides the "we can't mark this" signal.
        Caller should see AAPL in the list.
        """
        eq = engine.get_account_equity({"MSFT": Decimal("420")})
        assert "AAPL" in eq.symbols_missing_marks
        # AAPL contributes 0 to marked_value (excluded)
        assert eq.marked_value == Decimal("4200")  # only MSFT
        assert eq.equity == Decimal("96600")  # 92400 + 4200

    def test_zero_mark_still_raises_at_equity_level(
        self, engine: SqlitePaperEngine
    ) -> None:
        """Bad marks propagate — no silent "well, the OTHER positions
        are fine" fallback.
        """
        with pytest.raises(PaperEngineError, match="non-positive"):
            engine.get_account_equity({"MSFT": Decimal("0")})
