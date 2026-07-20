"""Unit tests for shared cost-basis + P&L math (#548)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from openbb_portfolio_intel.paper import (
    CostBasisError,
    FillEvent,
    Lot,
    apply_fill,
    mark_to_market,
    unrealized_pnl,
)

D = Decimal
FLAT = Lot(symbol="AAPL", qty=D("0"), avg_cost=D("0"), realized_pnl=D("0"))


# ---------------------------------------------------------------------------
# Opening from flat
# ---------------------------------------------------------------------------


def test_open_long_sets_avg_cost_to_price() -> None:
    fill = FillEvent(symbol="AAPL", qty=D("10"), price=D("100"))
    new_lot, realized = apply_fill(FLAT, fill)
    assert new_lot.qty == D("10")
    assert new_lot.avg_cost == D("100")
    assert new_lot.realized_pnl == D("0")
    assert realized == D("0")


def test_open_long_folds_commission_into_avg_cost() -> None:
    """Commission on a buy increases effective cost basis per share."""
    fill = FillEvent(symbol="AAPL", qty=D("10"), price=D("100"), commission=D("5"))
    new_lot, _ = apply_fill(FLAT, fill)
    # (100 * 10 + 5) / 10 = 100.5
    assert new_lot.avg_cost == D("100.5")


def test_open_short_folds_commission_into_avg_proceeds() -> None:
    fill = FillEvent(symbol="AAPL", qty=D("-10"), price=D("100"), commission=D("5"))
    new_lot, _ = apply_fill(FLAT, fill)
    assert new_lot.qty == D("-10")
    # (100 * 10 - 5) / 10 = 99.5 (proceeds per share reduced by commission)
    assert new_lot.avg_cost == D("99.5")


# ---------------------------------------------------------------------------
# Same-side add — weighted average
# ---------------------------------------------------------------------------


def test_add_to_long_uses_weighted_average() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("10"), price=D("120"))
    new_lot, realized = apply_fill(lot, fill)
    assert new_lot.qty == D("20")
    # (10 * 100 + 10 * 120) / 20 = 110
    assert new_lot.avg_cost == D("110")
    assert realized == D("0")


def test_add_to_short_uses_weighted_average_of_proceeds() -> None:
    lot = Lot(symbol="AAPL", qty=D("-10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-10"), price=D("90"))
    new_lot, realized = apply_fill(lot, fill)
    assert new_lot.qty == D("-20")
    assert new_lot.avg_cost == D("95")
    assert realized == D("0")


# ---------------------------------------------------------------------------
# Full close
# ---------------------------------------------------------------------------


def test_full_close_long_realizes_pnl_and_flattens() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-10"), price=D("120"))
    new_lot, realized = apply_fill(lot, fill)
    # (120 - 100) * 10 = 200
    assert realized == D("200")
    assert new_lot.qty == D("0")
    assert new_lot.avg_cost == D("0")
    assert new_lot.realized_pnl == D("200")


def test_full_close_short_realizes_pnl_and_flattens() -> None:
    lot = Lot(symbol="AAPL", qty=D("-10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("10"), price=D("80"))
    new_lot, realized = apply_fill(lot, fill)
    # short: (avg_cost - price) * qty_closed = (100 - 80) * 10 = 200
    assert realized == D("200")
    assert new_lot.qty == D("0")


def test_full_close_at_a_loss_realizes_negative_pnl() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-10"), price=D("80"))
    _, realized = apply_fill(lot, fill)
    assert realized == D("-200")


def test_close_commission_reduces_realized_pnl() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-10"), price=D("120"), commission=D("5"))
    _, realized = apply_fill(lot, fill)
    # (120 - 100) * 10 - 5 = 195
    assert realized == D("195")


# ---------------------------------------------------------------------------
# Partial close
# ---------------------------------------------------------------------------


def test_partial_close_long_preserves_avg_cost() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-4"), price=D("120"))
    new_lot, realized = apply_fill(lot, fill)
    assert new_lot.qty == D("6")
    assert new_lot.avg_cost == D("100")  # unchanged
    assert realized == D("80")  # (120-100) * 4
    assert new_lot.realized_pnl == D("80")


# ---------------------------------------------------------------------------
# Flipping (long → short or short → long in one fill)
# ---------------------------------------------------------------------------


def test_flip_long_to_short_realizes_full_close_and_opens_short() -> None:
    """Long 10 @ 100, then sell 15 @ 120 → flat +5 short @ 120.

    Realized P&L on the closing 10 shares: (120-100) * 10 = 200.
    The remaining 5 opens a short at 120.
    """
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-15"), price=D("120"))
    new_lot, realized = apply_fill(lot, fill)
    assert realized == D("200")
    assert new_lot.qty == D("-5")  # short 5
    assert new_lot.avg_cost == D("120")  # short proceeds per share
    assert new_lot.realized_pnl == D("200")


def test_flip_short_to_long_symmetric() -> None:
    lot = Lot(symbol="AAPL", qty=D("-10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("15"), price=D("80"))
    new_lot, realized = apply_fill(lot, fill)
    # short close: (100-80) * 10 = 200
    assert realized == D("200")
    assert new_lot.qty == D("5")  # long 5
    assert new_lot.avg_cost == D("80")


def test_flip_prorates_commission_between_close_and_open() -> None:
    """A flip fill's commission splits between the closing and opening portions."""
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    fill = FillEvent(symbol="AAPL", qty=D("-15"), price=D("120"), commission=D("15"))
    new_lot, realized = apply_fill(lot, fill)
    # close fraction: 10/15 → commission_close = 10; commission_open = 5
    # realized: (120-100)*10 - 10 = 190
    assert realized == D("190")
    # opening 5-share short at 120 with 5 commission: avg = (120*5 - 5) / 5 = 119
    assert new_lot.qty == D("-5")
    assert new_lot.avg_cost == D("119")


# ---------------------------------------------------------------------------
# Re-opening after flat resets cost basis
# ---------------------------------------------------------------------------


def test_reopen_after_flat_resets_avg_cost() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    _, realized_close = apply_fill(lot, FillEvent("AAPL", D("-10"), D("120")))
    assert realized_close == D("200")
    flat = Lot(symbol="AAPL", qty=D("0"), avg_cost=D("0"), realized_pnl=D("200"))
    reopen, _ = apply_fill(flat, FillEvent("AAPL", D("5"), D("130")))
    assert reopen.avg_cost == D("130")  # fresh basis, not 100
    assert reopen.realized_pnl == D("200")  # prior P&L preserved


# ---------------------------------------------------------------------------
# unrealized_pnl / mark_to_market
# ---------------------------------------------------------------------------


def test_unrealized_pnl_long() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    assert unrealized_pnl(lot, D("110")) == D("100")


def test_unrealized_pnl_short() -> None:
    lot = Lot(symbol="AAPL", qty=D("-10"), avg_cost=D("100"), realized_pnl=D("0"))
    # short unrealized: (mark - avg_cost) * qty = (110 - 100) * -10 = -100
    assert unrealized_pnl(lot, D("110")) == D("-100")


def test_unrealized_pnl_flat_is_zero() -> None:
    assert unrealized_pnl(FLAT, D("100")) == D("0")


def test_mark_to_market_returns_pnl_and_market_value() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    up, mv = mark_to_market(lot, D("110"))
    assert up == D("100")
    assert mv == D("1100")


def test_mark_to_market_short_market_value_is_negative() -> None:
    lot = Lot(symbol="AAPL", qty=D("-10"), avg_cost=D("100"), realized_pnl=D("0"))
    _, mv = mark_to_market(lot, D("110"))
    assert mv == D("-1100")


def test_unrealized_pnl_rejects_nan_mark() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    with pytest.raises(CostBasisError, match=r"not finite"):
        unrealized_pnl(lot, D("NaN"))


def test_unrealized_pnl_rejects_negative_mark() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    with pytest.raises(CostBasisError, match=r">= 0"):
        unrealized_pnl(lot, D("-1"))


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_apply_fill_rejects_symbol_mismatch() -> None:
    lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    with pytest.raises(CostBasisError, match=r"does not match"):
        apply_fill(lot, FillEvent(symbol="MSFT", qty=D("1"), price=D("100")))


def test_apply_fill_rejects_zero_qty() -> None:
    with pytest.raises(CostBasisError, match=r"non-zero"):
        apply_fill(FLAT, FillEvent(symbol="AAPL", qty=D("0"), price=D("100")))


def test_apply_fill_rejects_nan_price() -> None:
    with pytest.raises(CostBasisError, match=r"finite"):
        apply_fill(FLAT, FillEvent(symbol="AAPL", qty=D("1"), price=D("NaN")))


def test_apply_fill_rejects_negative_price() -> None:
    with pytest.raises(CostBasisError, match=r">= 0"):
        apply_fill(FLAT, FillEvent(symbol="AAPL", qty=D("1"), price=D("-1")))


def test_apply_fill_rejects_negative_commission() -> None:
    with pytest.raises(CostBasisError, match=r"commission"):
        apply_fill(
            FLAT,
            FillEvent(symbol="AAPL", qty=D("1"), price=D("100"), commission=D("-1")),
        )


# ---------------------------------------------------------------------------
# R7.11 — reverse-verify weighted-average correctness
# ---------------------------------------------------------------------------


def test_r711_weighted_average_correct_under_two_adds() -> None:
    """Buy 10 @ $100, then 10 @ $200 → avg = $150 (not simple mean of $150).

    Simple mean would also be 150 here (coincidence — both quantities
    equal). Use unequal quantities to distinguish:
    Buy 3 @ $100 + 7 @ $200 → weighted-avg 170; simple mean would be 150.
    """
    lot, _ = apply_fill(FLAT, FillEvent("AAPL", D("3"), D("100")))
    assert lot.avg_cost == D("100")
    lot, _ = apply_fill(lot, FillEvent("AAPL", D("7"), D("200")))
    # (3*100 + 7*200) / 10 = 1700 / 10 = 170
    assert lot.avg_cost == D("170")
    # Simple mean would incorrectly report 150 — the R7.11 discrimination.


def test_r711_realized_pnl_uses_avg_cost_not_last_fill_price() -> None:
    """Realized P&L must use weighted-average cost, not the most recent fill price.

    Buy 5 @ 100, buy 5 @ 200 (avg 150). Sell 5 @ 180.
    Correct realized: (180 - 150) * 5 = 150.
    If someone incorrectly used the latest fill price (200):
      realized = (180 - 200) * 5 = -100.
    This test discriminates.
    """
    lot, _ = apply_fill(FLAT, FillEvent("AAPL", D("5"), D("100")))
    lot, _ = apply_fill(lot, FillEvent("AAPL", D("5"), D("200")))
    assert lot.avg_cost == D("150")
    lot, realized = apply_fill(lot, FillEvent("AAPL", D("-5"), D("180")))
    assert realized == D("150"), (
        "realized must use weighted-avg (150), not most-recent fill (200); "
        "if this fails, an implementation regression reverted the "
        "weighted-average correctness"
    )
