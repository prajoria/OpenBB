"""Unit tests for paper ledger + replay (#545)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from openbb_portfolio_intel.paper import (
    InMemoryLedgerStore,
    LedgerEntry,
    LedgerEntryType,
    LedgerError,
    Lot,
    deposit_entry,
    dividend_entry,
    fee_entry,
    replay,
    split_entry,
    trade_entry,
    withdraw_entry,
)

D = Decimal
NOW = datetime(2026, 7, 20, 9, 30, 0)


def _t(seconds: int = 0) -> datetime:
    return NOW + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Constructor helpers (correct amount folding, sign conventions)
# ---------------------------------------------------------------------------


def test_trade_entry_computes_amount_from_qty_price_commission() -> None:
    e = trade_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        quantity=D("10"),
        price=D("100"),
        commission=D("1"),
    )
    # BUY 10 @ 100 with $1 commission: amount = -(10*100 + 1) = -1001
    assert e.amount == D("-1001")
    assert e.entry_type is LedgerEntryType.TRADE
    assert e.symbol == "AAPL"


def test_trade_entry_for_sell_produces_positive_amount() -> None:
    e = trade_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        quantity=D("-10"),  # sell
        price=D("100"),
        commission=D("1"),
    )
    # SELL: amount = -(-10*100 + 1) = 1000 - 1 = 999
    assert e.amount == D("999")


def test_deposit_entry_positive_amount() -> None:
    e = deposit_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        amount=D("5000"),
    )
    assert e.amount == D("5000")
    assert e.entry_type is LedgerEntryType.DEPOSIT


def test_withdraw_entry_stored_as_negative() -> None:
    e = withdraw_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        amount=D("1000"),
    )
    assert e.amount == D("-1000")


def test_withdraw_rejects_non_positive_input() -> None:
    with pytest.raises(LedgerError, match="positive"):
        withdraw_entry(
            account_id="acc",
            user_id="daisy",
            sequence=1,
            occurred_at=NOW,
            amount=D("0"),
        )


def test_dividend_entry_positive_amount_required_at_replay() -> None:
    """dividend_entry helper doesn't check sign; replay does."""
    e = LedgerEntry(
        entry_id="ent",
        account_id="acc",
        user_id="daisy",
        entry_type=LedgerEntryType.DIVIDEND,
        sequence=1,
        occurred_at=NOW,
        amount=D("-1"),  # bad
    )
    with pytest.raises(LedgerError, match="dividend"):
        replay([e], starting_cash=D("100"))


def test_split_entry_ratio_stored_in_quantity() -> None:
    e = split_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        ratio=D("2"),
    )
    assert e.quantity == D("2")
    assert e.amount == D("0")


def test_fee_entry_stored_as_negative() -> None:
    e = fee_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        amount=D("5"),
    )
    assert e.amount == D("-5")


# ---------------------------------------------------------------------------
# InMemoryLedgerStore
# ---------------------------------------------------------------------------


def test_store_append_and_list() -> None:
    store = InMemoryLedgerStore()
    e = deposit_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        amount=D("1000"),
    )
    store.append(e)
    assert store.list_for_account("acc", user_id="daisy") == [e]


def test_store_append_is_idempotent_on_entry_id() -> None:
    """Duplicate entry_id — second append is a no-op. Enables safe retry."""
    store = InMemoryLedgerStore()
    e = deposit_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        amount=D("1000"),
        entry_id="e-1",
    )
    store.append(e)
    store.append(e)
    assert len(store.list_for_account("acc", user_id="daisy")) == 1


def test_store_isolates_foreign_users() -> None:
    """user_id scoping — mallory can't see daisy's entries."""
    store = InMemoryLedgerStore()
    daisy_e = deposit_entry(
        account_id="acc-1",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        amount=D("1000"),
    )
    store.append(daisy_e)
    # Same account_id, foreign user
    mallory_view = store.list_for_account("acc-1", user_id="mallory")
    assert mallory_view == []


def test_store_returns_entries_sorted_by_occurred_at_and_sequence() -> None:
    store = InMemoryLedgerStore()
    # Insert out of order
    for offset, seq in [(20, 3), (10, 2), (0, 1), (10, 1)]:  # note: 10s @ seq 2 vs 1
        store.append(
            deposit_entry(
                account_id="acc",
                user_id="daisy",
                sequence=seq,
                occurred_at=_t(offset),
                amount=D("1"),
            )
        )
    entries = store.list_for_account("acc", user_id="daisy")
    order = [(e.occurred_at, e.sequence) for e in entries]
    assert order == sorted(order)


# ---------------------------------------------------------------------------
# replay — cash-only paths
# ---------------------------------------------------------------------------


def test_replay_deposit_increases_cash() -> None:
    e = deposit_entry(
        account_id="acc", user_id="daisy", sequence=1, occurred_at=NOW, amount=D("500")
    )
    state = replay([e], starting_cash=D("100"))
    assert state.cash == D("600")
    assert state.positions == {}
    assert state.entries_replayed == 1


def test_replay_withdraw_decreases_cash() -> None:
    e = withdraw_entry(
        account_id="acc", user_id="daisy", sequence=1, occurred_at=NOW, amount=D("30")
    )
    state = replay([e], starting_cash=D("100"))
    assert state.cash == D("70")


def test_replay_dividend_increases_cash() -> None:
    e = dividend_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        amount=D("42"),
    )
    state = replay([e], starting_cash=D("0"))
    assert state.cash == D("42")


def test_replay_fee_decreases_cash() -> None:
    e = fee_entry(
        account_id="acc", user_id="daisy", sequence=1, occurred_at=NOW, amount=D("5")
    )
    state = replay([e], starting_cash=D("100"))
    assert state.cash == D("95")


# ---------------------------------------------------------------------------
# replay — trade path (composes #548 apply_fill)
# ---------------------------------------------------------------------------


def test_replay_single_buy_creates_position_and_debits_cash() -> None:
    e = trade_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        quantity=D("10"),
        price=D("100"),
    )
    state = replay([e], starting_cash=D("2000"))
    assert state.cash == D("1000")  # 2000 - 1000
    assert "AAPL" in state.positions
    lot = state.positions["AAPL"]
    assert lot.qty == D("10")
    assert lot.avg_cost == D("100")


def test_replay_buy_then_sell_closes_position_and_returns_cash() -> None:
    entries = [
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=1,
            occurred_at=_t(0),
            symbol="AAPL",
            quantity=D("10"),
            price=D("100"),
        ),
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=2,
            occurred_at=_t(60),
            symbol="AAPL",
            quantity=D("-10"),
            price=D("110"),
        ),
    ]
    state = replay(entries, starting_cash=D("5000"))
    # After buy: 5000 - 1000 = 4000. After sell: 4000 + 1100 = 5100.
    assert state.cash == D("5100")
    # Flat position dropped from positions dict
    assert "AAPL" not in state.positions


def test_replay_rejects_zero_qty_trade() -> None:
    e = LedgerEntry(
        entry_id="e",
        account_id="acc",
        user_id="daisy",
        entry_type=LedgerEntryType.TRADE,
        sequence=1,
        occurred_at=NOW,
        amount=D("0"),
        symbol="AAPL",
        quantity=D("0"),
        price=D("100"),
    )
    with pytest.raises(LedgerError, match=r"zero quantity"):
        replay([e], starting_cash=D("100"))


# ---------------------------------------------------------------------------
# replay — splits
# ---------------------------------------------------------------------------


def test_replay_forward_split_doubles_qty_halves_avg_cost() -> None:
    entries = [
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=1,
            occurred_at=_t(0),
            symbol="AAPL",
            quantity=D("10"),
            price=D("200"),
        ),
        split_entry(
            account_id="acc",
            user_id="daisy",
            sequence=2,
            occurred_at=_t(60),
            symbol="AAPL",
            ratio=D("2"),
        ),
    ]
    state = replay(entries, starting_cash=D("5000"))
    lot = state.positions["AAPL"]
    assert lot.qty == D("20")
    assert lot.avg_cost == D("100")


def test_replay_reverse_split_halves_qty_doubles_avg_cost() -> None:
    entries = [
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=1,
            occurred_at=_t(0),
            symbol="AAPL",
            quantity=D("10"),
            price=D("100"),
        ),
        split_entry(
            account_id="acc",
            user_id="daisy",
            sequence=2,
            occurred_at=_t(60),
            symbol="AAPL",
            ratio=D("0.5"),
        ),
    ]
    state = replay(entries, starting_cash=D("2000"))
    lot = state.positions["AAPL"]
    assert lot.qty == D("5")
    assert lot.avg_cost == D("200")


def test_replay_split_on_missing_symbol_is_noop() -> None:
    """Corporate action after position closed — no-op, not raise."""
    e = split_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        ratio=D("2"),
    )
    state = replay([e], starting_cash=D("100"))
    assert state.cash == D("100")
    assert state.positions == {}


def test_replay_split_rejects_zero_ratio() -> None:
    e = split_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=NOW,
        symbol="AAPL",
        ratio=D("0"),
    )
    with pytest.raises(LedgerError, match=r"non-positive ratio"):
        replay([e], starting_cash=D("100"))


# ---------------------------------------------------------------------------
# replay — determinism + PRD §16.7 contract
# ---------------------------------------------------------------------------


def test_replay_is_deterministic() -> None:
    entries = [
        deposit_entry(
            account_id="acc",
            user_id="daisy",
            sequence=1,
            occurred_at=_t(0),
            amount=D("1000"),
        ),
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=2,
            occurred_at=_t(60),
            symbol="AAPL",
            quantity=D("5"),
            price=D("100"),
        ),
        dividend_entry(
            account_id="acc",
            user_id="daisy",
            sequence=3,
            occurred_at=_t(120),
            symbol="AAPL",
            amount=D("10"),
        ),
    ]
    s1 = replay(entries, starting_cash=D("500"))
    s2 = replay(entries, starting_cash=D("500"))
    assert s1 == s2


def test_replay_full_journey_matches_hand_computed_state() -> None:
    """PRD §16.7: replay(ledger) == live_state.

    Model a small trading day and verify final cash + position match
    a hand-computed reference.
    """
    entries = [
        # Start: $10,000 deposit
        deposit_entry(
            account_id="acc",
            user_id="daisy",
            sequence=1,
            occurred_at=_t(0),
            amount=D("10000"),
        ),
        # Buy 20 AAPL @ 150 with $2 commission → cash -= 3002
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=2,
            occurred_at=_t(60),
            symbol="AAPL",
            quantity=D("20"),
            price=D("150"),
            commission=D("2"),
        ),
        # Dividend: $30 → cash += 30
        dividend_entry(
            account_id="acc",
            user_id="daisy",
            sequence=3,
            occurred_at=_t(120),
            symbol="AAPL",
            amount=D("30"),
        ),
        # 2:1 split → 40 shares @ avg 76.01
        split_entry(
            account_id="acc",
            user_id="daisy",
            sequence=4,
            occurred_at=_t(180),
            symbol="AAPL",
            ratio=D("2"),
        ),
        # Fee $5 → cash -= 5
        fee_entry(
            account_id="acc",
            user_id="daisy",
            sequence=5,
            occurred_at=_t(240),
            amount=D("5"),
        ),
        # Sell 10 shares @ 80 (post-split) → cash += 800
        trade_entry(
            account_id="acc",
            user_id="daisy",
            sequence=6,
            occurred_at=_t(300),
            symbol="AAPL",
            quantity=D("-10"),
            price=D("80"),
        ),
    ]
    state = replay(entries, starting_cash=D("0"))
    # Cash: 0 + 10000 - 3002 + 30 + 0 - 5 + 800 = 7823
    assert state.cash == D("7823")
    # Position: 20 * 2 - 10 = 30 shares @ (150*20 + 2)/20 / 2 = 75.05
    lot = state.positions["AAPL"]
    assert lot.qty == D("30")
    assert lot.avg_cost == D("75.05")


# ---------------------------------------------------------------------------
# R7.11 — replay determinism proves the contract
# ---------------------------------------------------------------------------


def test_r711_reordering_entries_changes_state() -> None:
    """Order matters: weighted-avg cost basis changes with fill order.

    Buy 10@100, buy 10@200, sell 10@150 in correct order:
      avg after both buys = 150; sell at 150 → 0 realized P&L
    Reversed (sell first at 150 = short; buy 10@100 = cover, then buy 10@200):
      first sell opens short at 150; cover at 100 → +500 realized;
      remaining buy opens fresh long at 200. Different final state.
    """
    buy1 = trade_entry(
        account_id="acc",
        user_id="daisy",
        sequence=1,
        occurred_at=_t(0),
        symbol="AAPL",
        quantity=D("10"),
        price=D("100"),
    )
    buy2 = trade_entry(
        account_id="acc",
        user_id="daisy",
        sequence=2,
        occurred_at=_t(60),
        symbol="AAPL",
        quantity=D("10"),
        price=D("200"),
    )
    sell = trade_entry(
        account_id="acc",
        user_id="daisy",
        sequence=3,
        occurred_at=_t(120),
        symbol="AAPL",
        quantity=D("-10"),
        price=D("150"),
    )
    correct = replay([buy1, buy2, sell], starting_cash=D("10000"))
    reversed_ = replay([sell, buy1, buy2], starting_cash=D("10000"))
    # Cash is identical either way (sum of amounts) but position avg_cost differs.
    correct_lot = correct.positions["AAPL"]
    reversed_lot = reversed_.positions["AAPL"]
    # Correct: weighted-avg (10*100 + 10*200)/20 = 150; sell 10 @ 150 → 10 left @ 150
    assert correct_lot.qty == D("10")
    assert correct_lot.avg_cost == D("150")
    # Reversed: sell 10@150 (short), buy 10@100 (cover, realizes +500),
    # buy 10@200 (fresh long @ 200)
    assert reversed_lot.qty == D("10")
    assert reversed_lot.avg_cost == D("200")
    assert correct_lot.avg_cost != reversed_lot.avg_cost
