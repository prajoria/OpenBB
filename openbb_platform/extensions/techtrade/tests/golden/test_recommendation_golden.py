"""Golden-fixture lock for the #80 Recommendation builder (PRD §14.2, design §5.2).

Because the builder's ``reasoning`` / ``top_factors`` / ``caveats`` are **deterministic
strings**, this suite locks them byte-stable against a committed JSON fixture via the
:func:`~openbb_techtrade.testing.assert_matches_golden` harness. The fixture covers all
three Q-D branches:

* ``recommendation_buy_filled`` -- a clean BUY (high conviction, every family present,
  a divergence-style caveat included so trigger-firing is exercised).
* ``recommendation_sell_short_filled`` -- a mirror SELL_SHORT (sign-folded levels
  sentence, "above entry" wording).
* ``recommendation_hold_flat`` -- a HOLD/FLAT (zero-distance, NO levels sentence,
  ``"None."`` caveat).

Regenerate intentionally with ``TECHTRADE_REGEN_GOLDEN=1`` after a *reviewed* change to
the template grammar (§4.1), the top-factors rank (§4.2), or the caveats precedence
(§4.3) -- never blindly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_techtrade.engine.execution import build_recommendation
from openbb_techtrade.models import (
    EntryExitRule,
    Fill,
    IndicatorVote,
    MoverSignal,
    Order,
    Recommendation,
    TradePlan,
)
from openbb_techtrade.testing import assert_matches_golden

FIXTURES = Path(__file__).parent / "fixtures"

# Worked-golden constants (carried from #76 / #77 test conventions).
_AS_OF = date(2024, 1, 12)
_FILL_TS = datetime(2024, 1, 16, 14, 30, tzinfo=timezone.utc)
_ENTRY = Decimal("121.40")
_STOP_LONG = Decimal("117.60")
_TARGET_LONG = Decimal("129.00")
_STOP_SHORT = Decimal("125.20")
_TARGET_SHORT = Decimal("113.80")
_QTY = Decimal("263")
_ATR = 1.90


def _votes_long_with_split() -> list[IndicatorVote]:
    """A long-side vote set that fires the 'trend votes split' caveat (Q-C trigger #4).

    Trend has one positive (macd_hist+) and one negative (ema_cross-) vote, so the family
    is split and the caveat fires. Net score remains long-dominant via the other families.
    """
    return [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=-1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.8, weight=0.25),
        IndicatorVote(family="momentum", name="stoch", vote=1.0, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=1.0, weight=0.15),
        IndicatorVote(family="volume", name="cmf", vote=1.0, weight=0.15),
    ]


def _votes_short_clean() -> list[IndicatorVote]:
    """A short-side vote set (sign-flipped, no triggers other than possibly borderline)."""
    return [
        IndicatorVote(family="trend", name="macd_hist", vote=-1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=-1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=-0.8, weight=0.25),
        IndicatorVote(family="momentum", name="stoch", vote=-1.0, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=-0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=-1.0, weight=0.15),
        IndicatorVote(family="volume", name="cmf", vote=-1.0, weight=0.15),
    ]


def _orders(direction: str, stop: Decimal, target: Decimal) -> list[Order]:
    """Synthesize the #77 canonical order legs for a non-flat plan."""
    entry_side, exit_side = (
        ("buy", "sell") if direction == "long" else ("sell_short", "buy_to_cover")
    )
    return [
        Order(symbol="GLD", side=entry_side, quantity=_QTY, order_type="market", tif="day", intent="entry"),
        Order(symbol="GLD", side=exit_side, quantity=_QTY, order_type="stop", stop_price=stop, tif="gtc", intent="exit_stop"),
        Order(symbol="GLD", side=exit_side, quantity=_QTY, order_type="limit", limit_price=target, tif="gtc", intent="exit_target"),
        Order(symbol="GLD", side=exit_side, quantity=_QTY, order_type="market", tif="gtc", intent="exit_time"),
        Order(symbol="GLD", side=exit_side, quantity=_QTY, order_type="market", tif="gtc", intent="exit_signal"),
    ]


def _placeholder_rec(direction: str, entry: Decimal, stop: Decimal, target: Decimal, score: float) -> Recommendation:
    """A minimal placeholder Recommendation -- the inline #77 build the #80 builder overwrites."""
    action = {"long": "BUY", "short": "SELL_SHORT", "flat": "HOLD/FLAT"}[direction]
    conviction = "High" if abs(score) >= 0.7 else "Medium" if abs(score) >= 0.4 else "Low"
    if direction == "flat":
        return Recommendation(
            symbol="GLD", segment="Materials", as_of=_AS_OF,
            action=action, conviction=conviction, score=score,
            entry_price=entry, stop_price=entry, target_price=entry,
            stop_distance_pct=0.0, target_distance_pct=0.0, risk_reward=0.0, atr=_ATR,
            position_size=Decimal(0), risk_per_share=Decimal(0),
            risk_pct_of_notional=0.0, time_stop_bars=None,
            reasoning="placeholder", caveats="",
        )
    return Recommendation(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        action=action, conviction=conviction, score=score,
        entry_price=entry, stop_price=stop, target_price=target,
        stop_distance_pct=0.0, target_distance_pct=0.0, risk_reward=0.0, atr=_ATR,
        position_size=_QTY, risk_per_share=abs(entry - stop),
        risk_pct_of_notional=0.0, time_stop_bars=20,
        reasoning="placeholder", caveats="",
    )


def _buy_filled_plan() -> TradePlan:
    """A clean BUY with the realized entry == planned entry and a 'trend split' caveat."""
    votes = _votes_long_with_split()
    sig = MoverSignal(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        score=0.72, direction="long", votes=votes, rank_in_segment=1,
    )
    fill = Fill(
        order_ref="GLD:entry", timestamp=_FILL_TS, symbol="GLD", side="buy",
        quantity=_QTY, price=_ENTRY, commission=Decimal("0"), slippage=Decimal("0.05"),
    )
    return TradePlan(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        signal=sig, rule=EntryExitRule(), position_size=_QTY,
        orders=_orders("long", _STOP_LONG, _TARGET_LONG),
        simulated_fills=[fill],
        recommendation=_placeholder_rec("long", _ENTRY, _STOP_LONG, _TARGET_LONG, 0.72),
    )


def _sell_short_filled_plan() -> TradePlan:
    """A SELL_SHORT (sign-folded levels sentence + 'above entry' wording)."""
    votes = _votes_short_clean()
    sig = MoverSignal(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        score=-0.78, direction="short", votes=votes, rank_in_segment=1,
    )
    fill = Fill(
        order_ref="GLD:entry", timestamp=_FILL_TS, symbol="GLD", side="sell_short",
        quantity=_QTY, price=_ENTRY, commission=Decimal("0"), slippage=Decimal("0.05"),
    )
    return TradePlan(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        signal=sig, rule=EntryExitRule(), position_size=_QTY,
        orders=_orders("short", _STOP_SHORT, _TARGET_SHORT),
        simulated_fills=[fill],
        recommendation=_placeholder_rec("short", _ENTRY, _STOP_SHORT, _TARGET_SHORT, -0.78),
    )


def _hold_flat_plan() -> TradePlan:
    """A HOLD/FLAT with no votes -- zero-distance, no levels sentence, 'None.' caveats."""
    sig = MoverSignal(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        score=0.05, direction="flat", votes=[], rank_in_segment=1,
    )
    return TradePlan(
        symbol="GLD", segment="Materials", as_of=_AS_OF,
        signal=sig, rule=EntryExitRule(), position_size=Decimal(0),
        orders=[], simulated_fills=[],
        recommendation=_placeholder_rec("flat", _ENTRY, _ENTRY, _ENTRY, 0.05),
    )


@pytest.mark.golden
def test_recommendation_buy_filled_golden():
    """Lock the clean-BUY narrative (top_factors + reasoning + caveats) byte-stable."""
    rec = build_recommendation(_buy_filled_plan())
    assert_matches_golden("recommendation_buy_filled", rec, fixture_dir=FIXTURES)


@pytest.mark.golden
def test_recommendation_sell_short_filled_golden():
    """Lock the SELL_SHORT narrative -- sign-folded levels sentence."""
    rec = build_recommendation(_sell_short_filled_plan())
    assert_matches_golden("recommendation_sell_short_filled", rec, fixture_dir=FIXTURES)


@pytest.mark.golden
def test_recommendation_hold_flat_golden():
    """Lock the HOLD/FLAT narrative -- no levels sentence, 'None.' caveats."""
    rec = build_recommendation(_hold_flat_plan())
    assert_matches_golden("recommendation_hold_flat", rec, fixture_dir=FIXTURES)
