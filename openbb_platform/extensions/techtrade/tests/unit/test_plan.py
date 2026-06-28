"""Unit tests for the #77 plan orchestrator + orders materializer (PRD §9.2, contract §3).

Fully offline and deterministic. ``build_plans`` is the pure core behind ``obb.techtrade.plan``:
it runs the #75 signal chain (here injected) per the requested universe, sources each symbol's
``(entry, atr)`` through a second injectable ``level_fetcher`` seam, and assembles one #77
``TradePlan`` skeleton per signal via :func:`build_trade_plan` (so the #76 sizing, the order
mapping, and the inline ``Recommendation`` all flow through). ``materialize_orders`` is the pure
helper the ``orders`` command delegates to -- it re-validates a possibly-deserialized plan (dict
or model) and returns its ``orders`` (idempotent round-trip). Both seams are faked here so the
whole chain runs with no network, no API key, and no pandas-ta call; every price/quantity is
pinned to the #76 "worked golden" (entry 121.40, ATR 1.90, account 100000, risk 0.01 -> stop
117.60, target 129.00, qty 263), so any drift in the per-symbol fan-out, the ranking pass-through,
the risk->sizing flow, the as_of look-ahead discipline, or the orders round-trip is caught.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.plan import build_plans, materialize_orders
from openbb_techtrade.models import MoverSignal, Order, Recommendation, TradePlan
from openbb_techtrade.testing import to_jsonable

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90
_QTY = Decimal("263")  # floor(100000*0.01 / 3.80)
_CANONICAL = ["entry", "exit_stop", "exit_target", "exit_time", "exit_signal"]


def _signal(symbol: str, direction: str) -> MoverSignal:
    """Build a minimal ranked MoverSignal carrying just the fields the plan chain reads."""
    score = {"long": 0.72, "short": -0.72, "flat": 0.05}[direction]
    return MoverSignal(
        symbol=symbol,
        segment="Information Technology",
        as_of=_AS_OF,
        score=score,
        direction=direction,
        votes=[],
        rank_in_segment=1,
    )


def _signal_fetcher(*signals: MoverSignal):
    """Return an offline ``signal_fetcher`` that ignores the universe and serves fixed signals."""

    def _fetch(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        return list(signals)

    return _fetch


def _level_fetcher(entry: Decimal = _ENTRY, atr: float = _ATR):
    """Return an offline ``level_fetcher`` seam yielding a fixed ``(entry, atr)`` per symbol."""

    def _fetch(symbol: str, *, as_of: date):
        return entry, atr

    return _fetch


def _long_plan() -> TradePlan:
    plans = build_plans(
        symbols=["AAA"],
        preset="trend_follow",
        risk=0.01,
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long")),
        level_fetcher=_level_fetcher(),
    )
    return plans[0]


def test_build_plans_returns_one_plan_per_signal():
    """Assert build_plans assembles exactly one TradePlan per ranked signal."""
    plans = build_plans(
        symbols=["AAA", "CCC"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long"), _signal("CCC", "short")),
        level_fetcher=_level_fetcher(),
    )
    assert len(plans) == 2
    assert all(isinstance(p, TradePlan) for p in plans)
    assert [p.symbol for p in plans] == ["AAA", "CCC"]


def test_build_plans_preserves_signal_ranking_order():
    """Assert plans are emitted in the signal_fetcher's (ranked) order, unre-sorted."""
    signals = (_signal("AAA", "long"), _signal("BBB", "flat"), _signal("CCC", "short"))
    plans = build_plans(
        symbols=["CCC", "BBB", "AAA"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(*signals),
        level_fetcher=_level_fetcher(),
    )
    assert [p.symbol for p in plans] == ["AAA", "BBB", "CCC"]


def test_build_plans_segment_fan_out_one_plan_per_symbol():
    """Assert segment mode fans out to one TradePlan per resolved symbol (Q-E)."""
    signals = (_signal("AAA", "long"), _signal("BBB", "short"), _signal("CCC", "long"))
    plans = build_plans(
        segment="Information Technology",
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(*signals),
        level_fetcher=_level_fetcher(),
    )
    assert len(plans) == 3
    assert all(p.segment == "Information Technology" for p in plans)


def test_build_plans_single_symbol_is_length_one_list():
    """Assert a single-symbol request still returns a length-1 list (list-always, Q-E)."""
    plans = build_plans(
        symbols=["AAA"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long")),
        level_fetcher=_level_fetcher(),
    )
    assert isinstance(plans, list)
    assert len(plans) == 1


def test_build_plans_empty_universe_yields_empty_plans():
    """Assert an empty signal set produces an empty plan list (no holes, no error)."""
    plans = build_plans(
        symbols=["AAA"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(),
        level_fetcher=_level_fetcher(),
    )
    assert plans == []


def test_build_plans_long_plan_assembles_full_skeleton():
    """Assert a long plan wires signal/rule/size/orders + an inline recommendation (§3)."""
    plan = _long_plan()
    assert plan.symbol == "AAA"
    assert plan.segment == "Information Technology"
    assert plan.as_of == _AS_OF
    assert plan.signal.direction == "long"
    assert plan.position_size == _QTY
    assert [o.intent for o in plan.orders] == _CANONICAL
    assert all(isinstance(o, Order) for o in plan.orders)
    assert plan.simulated_fills == []
    assert plan.validation is None
    assert isinstance(plan.recommendation, Recommendation)
    assert plan.recommendation.action == "BUY"


def test_build_plans_flat_plan_is_zero_size_no_orders():
    """Assert a flat signal yields a HOLD/FLAT plan with no orders and zero size."""
    plans = build_plans(
        symbols=["FLT"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("FLT", "flat")),
        level_fetcher=_level_fetcher(),
    )
    plan = plans[0]
    assert plan.orders == []
    assert plan.position_size == Decimal(0)
    assert plan.recommendation.action == "HOLD/FLAT"


def test_build_plans_risk_flows_through_to_position_size():
    """Assert halving ``risk`` halves the sizing budget -> qty 131 (floor(500/3.80)) (Q-D)."""
    plans = build_plans(
        symbols=["AAA"],
        risk=0.005,
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long")),
        level_fetcher=_level_fetcher(),
    )
    assert plans[0].position_size == Decimal("131")


def test_build_plans_default_risk_reproduces_golden_size():
    """Assert the default risk (0.01) + normalized notional reproduces the #76 golden qty 263."""
    assert _long_plan().position_size == _QTY


def test_build_plans_passes_signal_as_of_to_level_fetcher():
    """Assert the level_fetcher is queried at the signal's own (snapped) as_of (look-ahead-free)."""
    captured: dict[str, date] = {}

    def _capturing(symbol: str, *, as_of: date):
        captured[symbol] = as_of
        return _ENTRY, _ATR

    build_plans(
        symbols=["AAA"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long")),
        level_fetcher=_capturing,
    )
    assert captured == {"AAA": _AS_OF}


def test_build_plans_every_order_carries_plan_symbol():
    """Assert every emitted leg echoes its plan's symbol."""
    plan = _long_plan()
    assert all(o.symbol == "AAA" for o in plan.orders)


def test_build_plans_round_trips_through_jsonable():
    """Assert assembled plans are JSON-serializable via to_jsonable (Decimal/date coerced)."""
    plan = _long_plan()
    json.dumps(to_jsonable(plan))  # must not raise
    assert TradePlan.model_validate(plan.model_dump()).model_dump() == plan.model_dump()


def test_build_plans_is_deterministic():
    """Assert two identical builds produce equal plan snapshots (pure, no hidden state)."""
    a = build_plans(
        symbols=["AAA", "CCC"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long"), _signal("CCC", "short")),
        level_fetcher=_level_fetcher(),
    )
    b = build_plans(
        symbols=["AAA", "CCC"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("AAA", "long"), _signal("CCC", "short")),
        level_fetcher=_level_fetcher(),
    )
    assert [p.model_dump() for p in a] == [p.model_dump() for p in b]


def test_materialize_orders_returns_plan_orders():
    """Assert materialize_orders returns the plan's existing order list unchanged."""
    plan = _long_plan()
    assert materialize_orders(plan) == plan.orders


def test_materialize_orders_round_trips_through_dict():
    """Assert materialize_orders re-validates a reloaded dict and returns equal orders (idempotent)."""
    plan = _long_plan()
    reloaded = plan.model_dump()
    materialized = materialize_orders(reloaded)
    assert [o.model_dump() for o in materialized] == [o.model_dump() for o in plan.orders]
    assert all(isinstance(o, Order) for o in materialized)


def test_materialize_orders_flat_plan_is_empty():
    """Assert materializing a flat plan's orders yields an empty list."""
    plans = build_plans(
        symbols=["FLT"],
        as_of=_AS_OF,
        signal_fetcher=_signal_fetcher(_signal("FLT", "flat")),
        level_fetcher=_level_fetcher(),
    )
    assert materialize_orders(plans[0]) == []
