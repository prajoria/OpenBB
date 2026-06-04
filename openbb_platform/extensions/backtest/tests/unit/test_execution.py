"""Unit tests for execution realism (component 06)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
from openbb_backtest.engine.execution import (
    Commission,
    Constraints,
    FillModel,
    RealisticBroker,
    ShortModel,
    Slippage,
)
from openbb_backtest.models import Bar, CommissionModel, SlippageModel


def _bar(symbol: str = "AAPL", volume: str = "1000000", spread_bps: float = 10.0) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2020, 6, 1, tzinfo=timezone.utc),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal(volume),
        spread_bps=spread_bps,
    )


# ---- Commission ----------------------------------------------------------


def test_commission_per_share():
    c = Commission.of(CommissionModel(kind="per_share", value=Decimal("0.01")))
    assert c.cost(Decimal("100"), Decimal("50")) == Decimal("1.00")


def test_commission_flat():
    c = Commission.of(CommissionModel(kind="flat", value=Decimal("1")))
    assert c.cost(Decimal("100"), Decimal("50")) == Decimal("1")


def test_commission_percent():
    c = Commission.of(CommissionModel(kind="percent", value=Decimal("0.001")))
    assert c.cost(Decimal("10"), Decimal("100")) == Decimal("1.000")


def test_commission_min_per_trade_floor():
    c = Commission.of(
        CommissionModel(kind="per_share", value=Decimal("0.01"), min_per_trade=Decimal("1"))
    )
    assert c.cost(Decimal("10"), Decimal("50")) == Decimal("1")


def test_commission_is_sign_independent():
    c = Commission.of(CommissionModel(kind="per_share", value=Decimal("0.01")))
    assert c.cost(Decimal("-100"), Decimal("50")) == c.cost(Decimal("100"), Decimal("50"))


# ---- Slippage ------------------------------------------------------------


def test_slippage_buy_is_positive_sell_is_negative():
    s = Slippage.of(SlippageModel(kind="fixed_bps", value=Decimal("10")))
    bar = _bar()
    buy = s.cost(Decimal("100"), Decimal("100"), bar)
    sell = s.cost(Decimal("-100"), Decimal("100"), bar)
    assert buy > 0
    assert sell < 0
    assert buy == -sell


def test_slippage_fixed_bps_magnitude():
    s = Slippage.of(SlippageModel(kind="fixed_bps", value=Decimal("10")))
    # 10 bps of 100 = 0.10
    assert s.cost(Decimal("100"), Decimal("100"), _bar()) == Decimal("0.10")


def test_slippage_volume_share_zero_volume():
    s = Slippage.of(SlippageModel(kind="volume_share", value=Decimal("0.1")))
    assert s.cost(Decimal("100"), Decimal("100"), _bar(volume="0")) == Decimal("0")


def test_slippage_zero_qty():
    s = Slippage.of(SlippageModel(kind="fixed_bps", value=Decimal("10")))
    assert s.cost(Decimal("0"), Decimal("100"), _bar()) == Decimal("0")


# ---- FillModel -----------------------------------------------------------


def test_fill_reference_next_bar_open():
    assert FillModel(kind="next_bar_open").reference_price(_bar()) == Decimal("100")


def test_fill_reference_vwap():
    # (high + low + 2*close) / 4 = (102 + 99 + 202) / 4 = 100.75
    assert FillModel(kind="vwap").reference_price(_bar()) == Decimal("100.75")


def test_limit_marketable_buy_and_sell():
    fm = FillModel(kind="limit")
    bar = _bar()  # low=99 high=102
    assert fm.limit_marketable(Decimal("10"), Decimal("99.5"), bar) is True
    assert fm.limit_marketable(Decimal("10"), Decimal("98"), bar) is False
    assert fm.limit_marketable(Decimal("-10"), Decimal("101"), bar) is True
    assert fm.limit_marketable(Decimal("-10"), Decimal("103"), bar) is False


# ---- ShortModel ----------------------------------------------------------


def test_short_borrow_cost():
    sm = ShortModel(borrow_fee_bps_annual=Decimal("252"))
    # 252 bps annual on 10000 over 1 of 252 days => 10000 * 0.0252 / 252 = 1.0
    assert sm.borrow_cost(Decimal("10000"), days=1) == Decimal("1.0000")


def test_short_hard_to_borrow_blocks():
    sm = ShortModel(hard_to_borrow={"GME"})
    assert sm.can_short("AAPL") is True
    assert sm.can_short("GME") is False


# ---- Constraints ---------------------------------------------------------


def test_constraints_restricted_symbol():
    cons = Constraints(restricted={"AAPL"})
    assert cons.reject_reason("AAPL", Decimal("10")) == "restricted"
    assert cons.reject_reason("MSFT", Decimal("10")) is None


# ---- RealisticBroker -----------------------------------------------------


def test_broker_satisfies_buy_fill():
    broker = RealisticBroker(
        CommissionModel(kind="per_share", value=Decimal("0.01")),
        SlippageModel(kind="fixed_bps", value=Decimal("10")),
    )
    orders = pd.DataFrame({"quantity": [Decimal("100")]}, index=["AAPL"])
    trades = broker.fill(orders, _bar())
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "buy"
    assert t.price == Decimal("100.10")  # open + 10bps slippage
    assert t.commission == Decimal("1.00")


def test_broker_sell_fills_lower():
    broker = RealisticBroker(
        CommissionModel(),
        SlippageModel(kind="fixed_bps", value=Decimal("10")),
    )
    orders = pd.DataFrame({"quantity": [Decimal("-100")]}, index=["AAPL"])
    trades = broker.fill(orders, _bar())
    assert trades[0].side == "sell"
    assert trades[0].price == Decimal("99.90")


def test_broker_rejects_restricted():
    broker = RealisticBroker(
        CommissionModel(),
        SlippageModel(),
        constraints=Constraints(restricted={"AAPL"}),
    )
    orders = pd.DataFrame({"quantity": [Decimal("100")]}, index=["AAPL"])
    trades = broker.fill(orders, _bar())
    assert trades == []
    assert broker.rejected_orders == 1


def test_broker_ignores_zero_qty():
    broker = RealisticBroker(CommissionModel(), SlippageModel())
    orders = pd.DataFrame({"quantity": [Decimal("0")]}, index=["AAPL"])
    assert broker.fill(orders, _bar()) == []
