"""Unit tests for the #77 order generator + TradePlan assembler (PRD §13, contract §3).

Fully offline and deterministic. ``generate_orders`` is a pure mapper: it takes the
already-sized #76 levels (entry / stop / target / qty) and a signal and emits the
canonical broker-style ``Order`` list -- an entry leg first, then the contingent
``exit_stop`` / ``exit_target`` / ``exit_time`` / ``exit_signal`` legs, each tagged with
its intent and the direction-correct side. ``build_trade_plan`` then orchestrates the #76
sizing, the order mapping, and a self-contained inline ``Recommendation`` into the
``TradePlan`` skeleton (contract §3 #77: ``recommendation`` stays required, built inline;
#80 later refactors it to delegate). Every price / quantity is pinned to an exact
``Decimal`` derived from the #76 "worked golden" (entry 121.40, ATR 1.90, account 100000,
risk 0.01 -> stop 117.60, target 129.00, qty 263), so any drift in the side convention,
the per-intent order_type/price/tif map, the canonical ordering, the conditional-exit
gating, or the Decimal discipline is caught.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from openbb_techtrade.engine.orders import build_trade_plan, generate_orders
from openbb_techtrade.models import EntryExitRule, MoverSignal, Order, Recommendation, TradePlan
from openbb_techtrade.testing import to_jsonable

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90
_RULE = EntryExitRule()  # max_holding_bars=20, exit_on_opposite=True -> all four exits
_ACCOUNT = Decimal("100000")
_RISK = 0.01

# #76 worked golden levels (long): stop 121.40 - 2.0*1.90 = 117.60; target 121.40 + 2.0*3.80 = 129.00.
_STOP_LONG = Decimal("117.60")
_TARGET_LONG = Decimal("129.00")
_STOP_SHORT = Decimal("125.20")
_TARGET_SHORT = Decimal("113.80")
_QTY = Decimal("263")  # floor(100000*0.01 / 3.80)

_CANONICAL = ["entry", "exit_stop", "exit_target", "exit_time", "exit_signal"]


def _signal(direction: str) -> MoverSignal:
    """Build a minimal MoverSignal carrying just the direction + score the kernel reads."""
    score = {"long": 0.72, "short": -0.72, "flat": 0.05}[direction]
    return MoverSignal(
        symbol="TEST",
        segment="Information Technology",
        as_of=_AS_OF,
        score=score,
        direction=direction,
        votes=[],
        rank_in_segment=1,
    )


def _orders_long() -> list[Order]:
    return generate_orders(
        _signal("long"), entry=_ENTRY, stop=_STOP_LONG, target=_TARGET_LONG, qty=_QTY, rule=_RULE
    )


def _by_intent(orders: list[Order]) -> dict[str, Order]:
    return {o.intent: o for o in orders}


def test_long_emits_canonical_intent_sequence():
    """Assert a long plan emits all five legs in canonical entry-first enum order."""
    assert [o.intent for o in _orders_long()] == _CANONICAL


def test_short_emits_canonical_intent_sequence():
    """Assert a short plan emits the same canonical intent sequence."""
    orders = generate_orders(
        _signal("short"), entry=_ENTRY, stop=_STOP_SHORT, target=_TARGET_SHORT, qty=_QTY, rule=_RULE
    )
    assert [o.intent for o in orders] == _CANONICAL


def test_entry_is_market_with_no_prices_day_tif():
    """Assert the entry leg defaults to a market order with no price and day tif (L4)."""
    entry = _by_intent(_orders_long())["entry"]
    assert entry.order_type == "market"
    assert entry.limit_price is None
    assert entry.stop_price is None
    assert entry.tif == "day"


def test_exit_stop_is_stop_order_carrying_stop_price():
    """Assert exit_stop is a gtc stop order whose stop_price is the #76 stop level."""
    stop = _by_intent(_orders_long())["exit_stop"]
    assert stop.order_type == "stop"
    assert stop.stop_price == _STOP_LONG
    assert stop.limit_price is None
    assert stop.tif == "gtc"
    assert isinstance(stop.stop_price, Decimal)


def test_exit_target_is_limit_order_carrying_limit_price():
    """Assert exit_target is a gtc limit order whose limit_price is the #76 target level."""
    target = _by_intent(_orders_long())["exit_target"]
    assert target.order_type == "limit"
    assert target.limit_price == _TARGET_LONG
    assert target.stop_price is None
    assert target.tif == "gtc"
    assert isinstance(target.limit_price, Decimal)


def test_exit_time_and_signal_are_market_none_gtc():
    """Assert the event-driven exits are market rows with no prices (triggers live on the rule)."""
    by_intent = _by_intent(_orders_long())
    for intent in ("exit_time", "exit_signal"):
        order = by_intent[intent]
        assert order.order_type == "market"
        assert order.limit_price is None
        assert order.stop_price is None
        assert order.tif == "gtc"


def test_long_side_mapping():
    """Assert a long plan buys to enter and sells to exit every leg (Q-B)."""
    orders = _orders_long()
    assert orders[0].side == "buy"
    assert all(o.side == "sell" for o in orders[1:])


def test_short_side_mapping():
    """Assert a short plan sells short to enter and buys to cover every exit (Q-B)."""
    orders = generate_orders(
        _signal("short"), entry=_ENTRY, stop=_STOP_SHORT, target=_TARGET_SHORT, qty=_QTY, rule=_RULE
    )
    assert orders[0].side == "sell_short"
    assert all(o.side == "buy_to_cover" for o in orders[1:])


def test_flat_emits_no_orders():
    """Assert a flat signal produces an empty order list (no position to express)."""
    orders = generate_orders(
        _signal("flat"), entry=_ENTRY, stop=None, target=None, qty=Decimal(0), rule=_RULE
    )
    assert orders == []


def test_every_leg_quantity_equals_position_size():
    """Assert every emitted leg carries the full position size (exits close the position)."""
    orders = _orders_long()
    assert all(o.quantity == _QTY for o in orders)
    assert all(isinstance(o.quantity, Decimal) for o in orders)


def test_no_exit_time_when_max_holding_bars_none():
    """Assert disabling the time stop drops the exit_time leg (conditional emission, Q-C)."""
    rule = EntryExitRule(max_holding_bars=None)
    orders = generate_orders(
        _signal("long"), entry=_ENTRY, stop=_STOP_LONG, target=_TARGET_LONG, qty=_QTY, rule=rule
    )
    assert "exit_time" not in {o.intent for o in orders}
    assert [o.intent for o in orders] == ["entry", "exit_stop", "exit_target", "exit_signal"]


def test_no_exit_signal_when_exit_on_opposite_false():
    """Assert disabling opposite-cross exit drops the exit_signal leg (conditional emission, Q-C)."""
    rule = EntryExitRule(exit_on_opposite=False)
    orders = generate_orders(
        _signal("long"), entry=_ENTRY, stop=_STOP_LONG, target=_TARGET_LONG, qty=_QTY, rule=rule
    )
    assert "exit_signal" not in {o.intent for o in orders}
    assert [o.intent for o in orders] == ["entry", "exit_stop", "exit_target", "exit_time"]


def test_all_orders_carry_the_signal_symbol():
    """Assert every leg echoes the signal's symbol."""
    assert all(o.symbol == "TEST" for o in _orders_long())


def test_build_trade_plan_long_assembles_full_skeleton():
    """Assert build_trade_plan wires signal/rule/size/orders and an inline recommendation."""
    plan = build_trade_plan(
        _signal("long"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    )
    assert isinstance(plan, TradePlan)
    assert plan.symbol == "TEST"
    assert plan.segment == "Information Technology"
    assert plan.as_of == _AS_OF
    assert plan.signal.direction == "long"
    assert plan.rule == _RULE
    assert plan.position_size == _QTY
    assert [o.intent for o in plan.orders] == _CANONICAL
    assert plan.simulated_fills == []
    assert plan.validation is None
    assert isinstance(plan.recommendation, Recommendation)


def test_build_trade_plan_inline_recommendation_long_is_consistent():
    """Assert the inline recommendation reproduces the #76 levels + a 2R reward:risk for a long."""
    rec = build_trade_plan(
        _signal("long"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    ).recommendation
    assert rec.action == "BUY"
    assert rec.conviction == "High"  # |0.72| >= 0.7
    assert rec.entry_price == _ENTRY
    assert rec.stop_price == _STOP_LONG
    assert rec.target_price == _TARGET_LONG
    assert rec.position_size == _QTY
    assert rec.risk_per_share == Decimal("3.80")
    assert rec.atr == _ATR
    assert rec.time_stop_bars == 20
    assert rec.risk_reward == pytest.approx(2.0)
    assert rec.stop_distance_pct == pytest.approx(3.130148270181219)
    assert rec.target_distance_pct == pytest.approx(6.260296540362438)
    assert rec.risk_pct_of_notional == pytest.approx(0.9994)
    assert rec.top_factors == []
    assert rec.caveats == ""


def test_build_trade_plan_short_maps_action_and_levels():
    """Assert a short plan yields a SELL_SHORT recommendation mirroring the levels."""
    plan = build_trade_plan(
        _signal("short"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    )
    assert plan.recommendation.action == "SELL_SHORT"
    assert plan.recommendation.stop_price == _STOP_SHORT
    assert plan.recommendation.target_price == _TARGET_SHORT
    assert plan.orders[0].side == "sell_short"


def test_build_trade_plan_flat_is_zero_size_no_orders():
    """Assert a flat signal yields a HOLD/FLAT plan with no orders and zero size."""
    plan = build_trade_plan(
        _signal("flat"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    )
    assert plan.orders == []
    assert plan.position_size == Decimal(0)
    assert plan.recommendation.action == "HOLD/FLAT"
    assert plan.recommendation.position_size == Decimal(0)


def test_build_trade_plan_round_trips_through_jsonable():
    """Assert the assembled plan is JSON-serializable via to_jsonable (Decimal/date coerced)."""
    plan = build_trade_plan(
        _signal("long"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    )
    encoded = to_jsonable(plan)
    json.dumps(encoded)  # must not raise
    assert TradePlan.model_validate(plan.model_dump()).model_dump() == plan.model_dump()


def test_build_trade_plan_is_deterministic():
    """Assert two identical calls produce equal plan snapshots (pure, no hidden state)."""
    a = build_trade_plan(
        _signal("long"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    )
    b = build_trade_plan(
        _signal("long"), entry=_ENTRY, atr=_ATR, rule=_RULE,
        account_size=_ACCOUNT, risk_per_trade=_RISK,
    )
    assert a.model_dump() == b.model_dump()
