"""Unit tests for the EntryExitRule level + sizing kernel (issue #76, PRD §13, §20 Q6).

Fully offline and deterministic: every assertion pins an exact ``Decimal`` derived
by hand in the plan's "worked golden" table, so any drift in the level math, the
long/short sign convention, the risk-per-share definition, or the risk-based floor
sizing is caught. No network, no API key, no router. The Q6 sizing inputs are
abstract notional (account_size: Decimal + risk_per_trade: float) -- no personal
dollar amounts. Decimal discipline is asserted explicitly (isinstance checks), and
floats (atr / multipliers) are converted via Decimal(str(...)) inside the kernel.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from openbb_techtrade.engine.rules import (
    apply_rule,
    position_size,
    stop_price,
    target_price,
)
from openbb_techtrade.models import EntryExitRule, MoverSignal

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90
_RULE = EntryExitRule()  # atr_stop_mult=2.0, target_r_multiple=2.0, max_holding_bars=20
_ACCOUNT = Decimal("100000")
_RISK = 0.01


def _signal(direction: str) -> MoverSignal:
    """Build a minimal MoverSignal carrying just the direction the kernel reads."""
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


def test_stop_price_long_is_below_entry():
    """Assert a long stop sits atr_stop_mult*ATR below entry (121.40 - 3.80 = 117.60)."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    assert stop == Decimal("117.60")
    assert isinstance(stop, Decimal)


def test_stop_price_short_is_above_entry():
    """Assert a short stop sits atr_stop_mult*ATR above entry (121.40 + 3.80 = 125.20)."""
    stop = stop_price(_ENTRY, _ATR, "short", _RULE)
    assert stop == Decimal("125.20")
    assert isinstance(stop, Decimal)


def test_risk_per_share_equals_atr_stop_mult_times_atr():
    """Assert |entry - stop| == atr_stop_mult * ATR for both directions (= 3.80)."""
    long_stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    short_stop = stop_price(_ENTRY, _ATR, "short", _RULE)
    expected = Decimal(str(_RULE.atr_stop_mult)) * Decimal(str(_ATR))  # Decimal("3.80")
    assert abs(_ENTRY - long_stop) == expected
    assert abs(_ENTRY - short_stop) == expected
    assert expected == Decimal("3.80")


def test_stop_price_flat_raises():
    """Assert a flat direction has no stop and raises ValueError (no position to protect)."""
    with pytest.raises(ValueError):
        stop_price(_ENTRY, _ATR, "flat", _RULE)


def test_target_price_long_is_above_entry():
    """Assert a long target is entry + R*risk (121.40 + 2*3.80 = 129.00)."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    target = target_price(_ENTRY, stop, "long", _RULE)
    assert target == Decimal("129.00")
    assert isinstance(target, Decimal)


def test_target_price_short_is_below_entry():
    """Assert a short target is entry - R*risk (121.40 - 2*3.80 = 113.80)."""
    stop = stop_price(_ENTRY, _ATR, "short", _RULE)
    target = target_price(_ENTRY, stop, "short", _RULE)
    assert target == Decimal("113.80")
    assert isinstance(target, Decimal)


def test_target_price_flat_raises():
    """Assert a flat direction has no target and raises ValueError."""
    stop = Decimal("117.60")
    with pytest.raises(ValueError):
        target_price(_ENTRY, stop, "flat", _RULE)


def test_target_honors_custom_r_multiple():
    """Assert a 3R rule widens the long target to entry + 3*3.80 = 132.80."""
    rule = EntryExitRule(target_r_multiple=3.0)
    stop = stop_price(_ENTRY, _ATR, "long", rule)
    target = target_price(_ENTRY, stop, "long", rule)
    assert target == Decimal("132.80")


def test_position_size_floors_risk_budget_over_risk_per_share():
    """Assert qty = floor((100000*0.01) / 3.80) = floor(263.157...) = 263, as a Decimal."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)  # 117.60 -> risk_per_share 3.80
    qty = position_size(_ENTRY, stop, account_size=_ACCOUNT, risk_per_trade=_RISK)
    assert qty == Decimal("263")
    assert isinstance(qty, Decimal)


def test_position_size_is_sign_free_for_short():
    """Assert sizing is identical for a short (same risk budget, same per-share risk)."""
    short_stop = stop_price(_ENTRY, _ATR, "short", _RULE)  # 125.20 -> risk_per_share 3.80
    qty = position_size(_ENTRY, short_stop, account_size=_ACCOUNT, risk_per_trade=_RISK)
    assert qty == Decimal("263")


def test_position_size_zero_risk_per_share_raises():
    """Assert a zero stop distance (entry == stop) raises ValueError, not ZeroDivisionError."""
    with pytest.raises(ValueError):
        position_size(_ENTRY, _ENTRY, account_size=_ACCOUNT, risk_per_trade=_RISK)


def test_position_size_smaller_risk_per_trade_shrinks_qty():
    """Assert halving risk_per_trade to 0.005 halves the budget -> floor(500/3.80) = 131."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    qty = position_size(_ENTRY, stop, account_size=_ACCOUNT, risk_per_trade=0.005)
    assert qty == Decimal("131")  # floor(500.00 / 3.80) = floor(131.578...)


def test_position_size_tiny_atr_floors_large_qty():
    """Assert a very small ATR yields a large but exactly floored share count."""
    rule = EntryExitRule()
    stop = stop_price(_ENTRY, 0.05, "long", rule)  # dist = 2.0*0.05 = 0.10 -> rps 0.10
    qty = position_size(_ENTRY, stop, account_size=_ACCOUNT, risk_per_trade=_RISK)
    # risk_budget 1000.00 / 0.10 = 10000 exactly -> Decimal("10000")
    assert qty == Decimal("10000")


def test_apply_rule_long_returns_full_level_and_size_dict():
    """Assert apply_rule reproduces the worked-golden long dict exactly (all Decimal)."""
    result = apply_rule(_signal("long"), entry=_ENTRY, atr=_ATR)
    assert result == {
        "entry": Decimal("121.40"),
        "stop": Decimal("117.60"),
        "target": Decimal("129.00"),
        "qty": Decimal("263"),
        "risk_per_share": Decimal("3.80"),
    }
    assert set(result) == {"entry", "stop", "target", "qty", "risk_per_share"}
    for key in ("entry", "stop", "target", "qty", "risk_per_share"):
        assert isinstance(result[key], Decimal)


def test_apply_rule_short_mirrors_levels():
    """Assert a short plan mirrors stop above / target below entry with identical sizing."""
    result = apply_rule(_signal("short"), entry=_ENTRY, atr=_ATR)
    assert result["stop"] == Decimal("125.20")
    assert result["target"] == Decimal("113.80")
    assert result["risk_per_share"] == Decimal("3.80")
    assert result["qty"] == Decimal("263")


def test_apply_rule_flat_returns_zero_size_no_levels():
    """Assert a flat signal yields entry only, None stop/target, and zero size / zero risk."""
    result = apply_rule(_signal("flat"), entry=_ENTRY, atr=_ATR)
    assert result == {
        "entry": Decimal("121.40"),
        "stop": None,
        "target": None,
        "qty": Decimal(0),
        "risk_per_share": Decimal(0),
    }
    assert isinstance(result["qty"], Decimal)


def test_apply_rule_honors_account_and_risk_overrides():
    """Assert overriding account_size / risk_per_trade re-sizes deterministically."""
    result = apply_rule(
        _signal("long"), entry=_ENTRY, atr=_ATR,
        account_size=Decimal("50000"), risk_per_trade=0.02,
    )
    # risk_budget = 50000 * 0.02 = 1000.00 -> same qty 263 as the golden
    assert result["qty"] == Decimal("263")
    assert result["stop"] == Decimal("117.60")  # levels unchanged by sizing inputs


def test_apply_rule_is_deterministic():
    """Assert two identical calls return equal dicts (pure, no hidden state)."""
    a = apply_rule(_signal("long"), entry=_ENTRY, atr=_ATR)
    b = apply_rule(_signal("long"), entry=_ENTRY, atr=_ATR)
    assert a == b


def test_apply_rule_zero_atr_raises_via_sizing_guard():
    """Assert a non-flat signal with a zero ATR (stop == entry) raises through the size guard."""
    with pytest.raises(ValueError):
        apply_rule(_signal("long"), entry=_ENTRY, atr=0.0)
