"""Unit tests for SimpleFillModel — Broker Protocol adapter (#892).

Covers Market-order semantics + Protocol conformance. Limit/Stop/TIF
work is out of scope for this issue; see #563 (Fills v0) and #544
(Fills v1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest
from openbb_backtest.interfaces import Broker
from openbb_backtest.models import Bar, CommissionModel, SlippageModel
from openbb_portfolio_intel.execution import SimpleFillModel


@pytest.fixture
def bar() -> Bar:
    """Return a deterministic bar for tests that reference a single symbol."""
    return Bar(
        symbol="MSFT",
        timestamp=datetime(2026, 7, 19, 14, 30, tzinfo=timezone.utc),
        open=Decimal("412.30"),
        high=Decimal("415.00"),
        low=Decimal("410.00"),
        close=Decimal("413.50"),
        volume=Decimal("1000000"),
    )


@pytest.fixture
def zero_slip_broker() -> SimpleFillModel:
    """Broker with zero commission, zero slippage — for testing pure fill logic."""
    return SimpleFillModel(
        commission=CommissionModel(kind="flat", value=Decimal("0")),
        slippage=SlippageModel(kind="fixed_bps", value=Decimal("0")),
    )


def test_implements_broker_protocol() -> None:
    """SimpleFillModel must satisfy the runtime_checkable Broker Protocol."""
    b = SimpleFillModel()
    assert isinstance(b, Broker), (
        "SimpleFillModel must implement openbb_backtest.interfaces.Broker "
        "for the swappable-adapter design (#498 A' resolution)."
    )


def test_market_buy_produces_trade_at_bar_open(
    zero_slip_broker: SimpleFillModel, bar: Bar
) -> None:
    """A positive-qty market order fills at bar.open (zero slippage config)."""
    orders = pd.DataFrame({"quantity": [10]}, index=["MSFT"])
    trades = zero_slip_broker.fill(orders, bar)
    assert len(trades) == 1
    t = trades[0]
    assert t.symbol == "MSFT"
    assert t.side == "buy"
    assert t.quantity == Decimal("10")
    assert t.price == Decimal("412.30")  # bar.open, no slippage
    assert t.commission == Decimal("0")
    assert t.slippage == Decimal("0")


def test_market_sell_produces_trade(
    zero_slip_broker: SimpleFillModel, bar: Bar
) -> None:
    """A negative-qty market order fills as a sell with quantity=|qty|."""
    orders = pd.DataFrame({"quantity": [-5]}, index=["MSFT"])
    trades = zero_slip_broker.fill(orders, bar)
    assert len(trades) == 1
    assert trades[0].side == "sell"
    assert trades[0].quantity == Decimal("5")


def test_zero_quantity_produces_no_trade(
    zero_slip_broker: SimpleFillModel, bar: Bar
) -> None:
    """quantity=0 is a no-op — no Trade emitted."""
    orders = pd.DataFrame({"quantity": [0]}, index=["MSFT"])
    trades = zero_slip_broker.fill(orders, bar)
    assert trades == []


def test_order_for_different_symbol_is_skipped(
    zero_slip_broker: SimpleFillModel, bar: Bar
) -> None:
    """Orders whose symbol != bar.symbol are silently skipped (matches RealisticBroker)."""
    orders = pd.DataFrame(
        {"quantity": [10, 5]},
        index=["MSFT", "AAPL"],
    )
    trades = zero_slip_broker.fill(orders, bar)
    # Only MSFT fills; AAPL is skipped because bar.symbol=='MSFT'.
    assert len(trades) == 1
    assert trades[0].symbol == "MSFT"


def test_non_market_order_raises_not_implemented(
    zero_slip_broker: SimpleFillModel, bar: Bar
) -> None:
    """Limit / Stop / etc. must raise NotImplementedError with pointer to follow-ups."""
    orders = pd.DataFrame(
        {"quantity": [10], "order_type": ["limit"]},
        index=["MSFT"],
    )
    with pytest.raises(NotImplementedError, match=r"limit.*#563"):
        zero_slip_broker.fill(orders, bar)


def test_commission_delegates_to_configured_model(bar: Bar) -> None:
    """commission() returns whatever the injected CommissionModel says."""
    broker = SimpleFillModel(
        commission=CommissionModel(kind="flat", value=Decimal("1.50")),
        slippage=SlippageModel(kind="fixed_bps", value=Decimal("0")),
    )
    # 100 shares at $50 with flat $1.50 commission → $1.50 total.
    assert broker.commission(Decimal("100"), Decimal("50")) == Decimal("1.50")


def test_slippage_is_adverse_for_buy_and_sell(bar: Bar) -> None:
    """Slippage returns signed: positive worsens buys, negative worsens sells."""
    # 10 bps of $100 = $0.10 per share, adverse.
    broker = SimpleFillModel(
        commission=CommissionModel(kind="flat", value=Decimal("0")),
        slippage=SlippageModel(kind="fixed_bps", value=Decimal("10")),
    )
    buy_slip = broker.slippage(Decimal("10"), Decimal("100"), bar)  # positive
    sell_slip = broker.slippage(Decimal("-10"), Decimal("100"), bar)  # negative
    assert (
        buy_slip > 0
    ), f"buy slippage must be positive (adverse to buyer); got {buy_slip}"
    assert (
        sell_slip < 0
    ), f"sell slippage must be negative (adverse to seller); got {sell_slip}"
    assert abs(buy_slip) == abs(
        sell_slip
    ), "magnitude should be identical, sign flipped"


def test_market_buy_with_slippage_fills_above_open(bar: Bar) -> None:
    """End-to-end: slippage flows into Trade.price."""
    broker = SimpleFillModel(
        commission=CommissionModel(kind="flat", value=Decimal("0")),
        slippage=SlippageModel(kind="fixed_bps", value=Decimal("10")),  # 10 bps
    )
    orders = pd.DataFrame({"quantity": [10]}, index=["MSFT"])
    trades = broker.fill(orders, bar)
    assert len(trades) == 1
    # bar.open = 412.30, slippage = 412.30 * 10/10000 = 0.4123, buy fills above.
    assert trades[0].price > bar.open
    # Confirm the exact amount
    expected_slip = bar.open * Decimal("10") / Decimal("10000")
    assert trades[0].price == bar.open + expected_slip
