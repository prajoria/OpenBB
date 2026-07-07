"""Unit tests for the weighted-confluence vote engine (issue #74, PRD §12, §20 Q4).

Fully offline and deterministic: hand-built ``IndicatorPanel`` literals drive every
voter so the closed-form vote math (PRD §12.1) is pinned exactly, with no network,
no API key, and no pandas-ta call. The bullish ``_gold_panel`` is the same literal
the golden fixture locks; ``_flat_panel`` exercises the damped / neutral branches.
Covers the Q4 weights, ADX gating, RSI 70/30 saturation, the stoch K/D cross, the
regime-aware Bollinger %B vote, ATR never voting, and the volume confirmation
multiplier (which is NOT an additive family).
"""

from __future__ import annotations

from datetime import date

import pytest
from openbb_techtrade.engine.confluence import (
    DEFAULT_WEIGHTS,
    ConfluenceWeights,
    build_signal,
    composite_score,
    conviction_for,
    direction_for,
    momentum_votes,
    trend_votes,
    volatility_votes,
    volume_confirmation,
)
from openbb_techtrade.models import IndicatorPanel, IndicatorVote, MoverSignal

_AS_OF = date(2024, 1, 12)


def _gold_panel() -> IndicatorPanel:
    """Build the bullish reference panel (every family fires); golden-locked literal."""
    return IndicatorPanel(
        symbol="GOLD",
        as_of=_AS_OF,
        trend={
            "macd_hist": 0.85,
            "adx": 28.0,
            "ema_fast": 121.5,
            "ema_slow": 117.0,
            "ema_cross": 4.5,
        },
        momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
        volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
        volume={"obv_slope": 12.0, "cmf": 0.18},
        candles={"cdl_engulfing": 1},
    )


def _flat_panel() -> IndicatorPanel:
    """Build a weak / mixed panel: damped MACD (ADX<gate), neutral RSI, mid-band %B."""
    return IndicatorPanel(
        symbol="FLAT",
        as_of=_AS_OF,
        trend={
            "macd_hist": 0.10,
            "adx": 10.0,
            "ema_fast": 99.9,
            "ema_slow": 100.1,
            "ema_cross": -0.2,
        },
        momentum={"rsi": 50.0, "stoch_k": 50.0, "stoch_d": 50.0},
        volatility={"bb_pctb": 0.50, "atr": 1.0, "kc_upper": 102.0, "kc_lower": 98.0},
        volume={"obv_slope": 0.0, "cmf": 0.0},
        candles={},
    )


def test_default_weights_match_q4():
    """Assert the frozen Q4 weights: trend .40 / momentum .25 / volatility .20 / volume .15."""
    assert (DEFAULT_WEIGHTS.trend, DEFAULT_WEIGHTS.momentum) == (0.40, 0.25)
    assert (DEFAULT_WEIGHTS.volatility, DEFAULT_WEIGHTS.volume) == (0.20, 0.15)
    assert isinstance(ConfluenceWeights(), ConfluenceWeights)


def test_trend_votes_macd_full_strength_when_adx_strong():
    """Assert MACD votes its sign at full strength when ADX exceeds the gate, plus the EMA cross."""
    votes = trend_votes(_gold_panel())
    by_name = {v.name: v for v in votes}
    assert by_name["macd_hist"].vote == pytest.approx(1.0)  # sign(+0.85) * gate(1.0)
    assert by_name["ema_cross"].vote == pytest.approx(1.0)  # golden cross
    assert all(v.family == "trend" and v.weight == pytest.approx(0.40) for v in votes)
    assert all(isinstance(v, IndicatorVote) for v in votes)


def test_trend_macd_damped_when_adx_weak():
    """Assert a weak ADX damps the MACD vote by adx/adx_gate (here 10/20 = 0.5)."""
    macd = {v.name: v for v in trend_votes(_flat_panel())}["macd_hist"]
    assert macd.vote == pytest.approx(0.5)  # sign(+0.10) * clip(10/20, 0, 1)


def test_trend_macd_full_strength_when_adx_absent():
    """Assert an absent ADX leaves MACD un-damped (gate=1.0), not silenced."""
    no_adx = IndicatorPanel(symbol="N", as_of=_AS_OF, trend={"macd_hist": 0.5})
    macd = {v.name: v for v in trend_votes(no_adx)}["macd_hist"]
    assert macd.vote == pytest.approx(1.0)  # sign(+0.5) * gate(1.0, adx None)


def test_momentum_rsi_scales_and_stoch_cross_confirms():
    """Assert RSI scales toward +1 by 70 and the stoch K/D cross votes its sign."""
    by_name = {v.name: v for v in momentum_votes(_gold_panel())}
    assert by_name["rsi"].vote == pytest.approx(0.6)  # (64-55)/15
    assert by_name["stoch"].vote == pytest.approx(1.0)  # sign(80-72)
    assert all(v.weight == pytest.approx(0.25) for v in momentum_votes(_gold_panel()))


def test_momentum_rsi_saturates_at_70_30():
    """Assert RSI magnitude saturates at +1 by 70 and -1 by 30, and is neutral in [45,55]."""
    hot = IndicatorPanel(symbol="H", as_of=_AS_OF, momentum={"rsi": 82.0})
    cold = IndicatorPanel(symbol="C", as_of=_AS_OF, momentum={"rsi": 18.0})
    mid = IndicatorPanel(symbol="M", as_of=_AS_OF, momentum={"rsi": 50.0})
    assert {v.name: v.vote for v in momentum_votes(hot)}["rsi"] == pytest.approx(1.0)
    assert {v.name: v.vote for v in momentum_votes(cold)}["rsi"] == pytest.approx(-1.0)
    assert {v.name: v.vote for v in momentum_votes(mid)}["rsi"] == pytest.approx(0.0)


def test_volatility_bbpctb_regime_aware_and_atr_silent():
    """Assert %B votes continuation in a trend regime, flips in a range regime, and ATR never votes."""
    trend_vote = {v.name: v for v in volatility_votes(_gold_panel(), regime="trend")}
    range_vote = {v.name: v for v in volatility_votes(_gold_panel(), regime="range")}
    assert trend_vote["bb_pctb"].vote == pytest.approx(0.84)  # 2*(0.92-0.5)
    assert range_vote["bb_pctb"].vote == pytest.approx(-0.84)  # mean-revert flip
    assert "atr" not in trend_vote  # ATR sets stops (§13), never votes
    assert all(
        v.family == "volatility" and v.weight == pytest.approx(0.20)
        for v in trend_vote.values()
    )


def test_volume_confirmation_amplifies_and_damps():
    """Assert volume confirmation is 1 + 0.15*v: 1.15 when OBV/CMF agree, 1.0 when neutral."""
    assert volume_confirmation(_gold_panel()) == pytest.approx(1.15)  # v = +1
    assert volume_confirmation(_flat_panel()) == pytest.approx(1.0)  # v = 0
    bearish = IndicatorPanel(
        symbol="B", as_of=_AS_OF, volume={"obv_slope": -5.0, "cmf": -0.2}
    )
    assert volume_confirmation(bearish) == pytest.approx(0.85)  # v = -1


def test_voters_omit_missing_keys():
    """Assert voters degrade gracefully: absent panel keys simply drop their vote, no raise."""
    empty = IndicatorPanel(symbol="E", as_of=_AS_OF)
    assert trend_votes(empty) == []
    assert momentum_votes(empty) == []
    assert volatility_votes(empty) == []
    assert volume_confirmation(empty) == pytest.approx(1.0)


def test_composite_score_reproduces_golden_value():
    """Assert the hand-derived composite score (0.8832) is reproduced exactly."""
    score, votes = composite_score(_gold_panel())
    assert score == pytest.approx(0.8832)
    assert len(votes) == 7  # 2 trend + 2 momentum + 1 volatility + 2 volume


def test_votes_fully_reconcile_the_score():
    """Assert the returned votes reconstruct the score (sum / weights reconcile, §12.2)."""
    score, votes = composite_score(_gold_panel())

    def _mean_family(family: str) -> float:
        vals = [v.vote for v in votes if v.family == family]
        return sum(vals) / len(vals) if vals else 0.0

    w = {v.family: v.weight for v in votes}  # one weight per family
    raw = (
        w["trend"] * _mean_family("trend")
        + w["momentum"] * _mean_family("momentum")
        + w["volatility"] * _mean_family("volatility")
    )
    vc = 1.0 + w["volume"] * _mean_family("volume")
    rebuilt = max(-1.0, min(1.0, raw * vc))
    assert rebuilt == pytest.approx(score)


def test_votes_reconcile_under_non_default_weights():
    """Assert the votes still reconstruct the score under custom weights (volume amplitude is fixed)."""
    weights = ConfluenceWeights(trend=0.5, momentum=0.3, volatility=0.1, volume=0.25)
    score, votes = composite_score(_gold_panel(), weights=weights)

    def _mean_family(family: str) -> float:
        vals = [v.vote for v in votes if v.family == family]
        return sum(vals) / len(vals) if vals else 0.0

    w = {v.family: v.weight for v in votes}
    # Volume votes carry the FIXED amplitude actually applied (0.15), not weights.volume (0.25),
    # so reconstructing vc from the stamped weight matches the real multiplier.
    assert w["volume"] == pytest.approx(0.15)
    raw = (
        w["trend"] * _mean_family("trend")
        + w["momentum"] * _mean_family("momentum")
        + w["volatility"] * _mean_family("volatility")
    )
    vc = 1.0 + w["volume"] * _mean_family("volume")
    assert max(-1.0, min(1.0, raw * vc)) == pytest.approx(score)


def test_volume_confirms_long_known_short_side_inversion():
    """Pin the current long-only volume semantics: bullish volume amplifies a long, but also a short.

    Documents the #74 limitation deferred to #75 (see task/bead): volume_confirmation has no
    sign(raw) term, so it confirms longs (raw>0) but is inverted for shorts (raw<0).
    """
    base_trend = {"macd_hist": 0.85, "adx": 28.0, "ema_cross": 4.5}
    base_mom = {"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0}
    bullish_vol = {"obv_slope": 12.0, "cmf": 0.18}
    long_with_vol = IndicatorPanel(
        symbol="L",
        as_of=_AS_OF,
        trend=base_trend,
        momentum=base_mom,
        volume=bullish_vol,
    )
    long_no_vol = IndicatorPanel(
        symbol="LN", as_of=_AS_OF, trend=base_trend, momentum=base_mom
    )
    # Bullish volume amplifies a long (vc=1.15): |score| grows.
    assert abs(composite_score(long_with_vol)[0]) > abs(composite_score(long_no_vol)[0])

    short_trend = {"macd_hist": -0.85, "adx": 28.0, "ema_cross": -4.5}
    short_mom = {"rsi": 36.0, "stoch_k": 72.0, "stoch_d": 80.0}
    short_with_vol = IndicatorPanel(
        symbol="S",
        as_of=_AS_OF,
        trend=short_trend,
        momentum=short_mom,
        volume=bullish_vol,
    )
    short_no_vol = IndicatorPanel(
        symbol="SN", as_of=_AS_OF, trend=short_trend, momentum=short_mom
    )
    # Same bullish volume on a SHORT also grows |score| (vc=1.15) -- the known inversion, not a confirm/damp.
    assert abs(composite_score(short_with_vol)[0]) > abs(
        composite_score(short_no_vol)[0]
    )


def test_score_ceiling_under_default_weights_is_below_one():
    """Assert an all-aligned panel tops out at 0.85*1.15 = 0.9775 under the Q4 weights (clip never fires)."""
    strong = IndicatorPanel(
        symbol="S",
        as_of=_AS_OF,
        trend={"macd_hist": 9.0, "adx": 60.0, "ema_cross": 5.0},
        momentum={"rsi": 95.0, "stoch_k": 99.0, "stoch_d": 10.0},
        volatility={"bb_pctb": 3.0},
        volume={"obv_slope": 9.0, "cmf": 0.9},
    )
    score, _ = composite_score(strong)
    assert score == pytest.approx(
        0.9775
    )  # raw 0.85 * vc 1.15; the 0.85 ceiling is intentional


def test_score_is_clipped_into_unit_interval():
    """Assert over-unity weights actually engage the [-1, +1] clip (not a vacuous bound)."""
    strong = IndicatorPanel(
        symbol="S",
        as_of=_AS_OF,
        trend={"macd_hist": 9.0, "adx": 60.0, "ema_cross": 5.0},
        momentum={"rsi": 95.0, "stoch_k": 99.0, "stoch_d": 10.0},
        volatility={"bb_pctb": 3.0},
        volume={"obv_slope": 9.0, "cmf": 0.9},
    )
    bearish = IndicatorPanel(
        symbol="X",
        as_of=_AS_OF,
        trend={"macd_hist": -9.0, "adx": 60.0, "ema_cross": -5.0},
        momentum={"rsi": 5.0, "stoch_k": 10.0, "stoch_d": 99.0},
        volatility={"bb_pctb": -3.0},
        volume={"obv_slope": -9.0, "cmf": -0.9},
    )
    # Additive families sum 1.2; raw=1.2 * vc=1.15 = 1.38 -> clamped exactly to the unit edge.
    over_unity = ConfluenceWeights(trend=0.5, momentum=0.4, volatility=0.3, volume=0.15)
    assert composite_score(strong, weights=over_unity)[0] == pytest.approx(1.0)
    assert composite_score(bearish, weights=over_unity)[0] == pytest.approx(-1.0)


def test_direction_buckets():
    """Assert direction bucketing at the default 0.4 entry threshold."""
    assert direction_for(0.55) == "long"
    assert direction_for(-0.55) == "short"
    assert direction_for(0.10) == "flat"
    assert direction_for(0.4) == "long"  # boundary is inclusive
    assert direction_for(0.30, entry_threshold=0.25) == "long"  # custom threshold


def test_conviction_buckets():
    """Assert |score| conviction bucketing: >=0.7 High, >=0.4 Medium, else Low (§14.2)."""
    assert conviction_for(0.80) == "High"
    assert conviction_for(-0.72) == "High"
    assert conviction_for(0.50) == "Medium"
    assert conviction_for(-0.41) == "Medium"
    assert conviction_for(0.20) == "Low"
    # Lower-inclusive edges exactly: 0.7 -> High, 0.4 -> Medium (guards a >/>= flip).
    assert conviction_for(0.70) == "High"
    assert conviction_for(0.40) == "Medium"


def test_build_signal_assembles_full_mover_signal():
    """Assert build_signal returns a MoverSignal carrying the score, direction, and full votes."""
    signal = build_signal(_gold_panel(), "Information Technology", rank_in_segment=1)
    assert isinstance(signal, MoverSignal)
    assert signal.symbol == "GOLD"
    assert signal.segment == "Information Technology"
    assert signal.as_of == _AS_OF
    assert signal.score == pytest.approx(0.8832)
    assert signal.direction == "long"
    assert signal.rank_in_segment == 1
    assert len(signal.votes) == 7
    assert {v.family for v in signal.votes} == {
        "trend",
        "momentum",
        "volatility",
        "volume",
    }


def test_build_signal_flat_when_score_below_threshold():
    """Assert a weak / mixed panel resolves to a flat, below-threshold signal."""
    signal = build_signal(_flat_panel(), "Financials")
    assert signal.direction == "flat"
    assert abs(signal.score) < 0.4
    assert conviction_for(signal.score) == "Low"


def test_consumes_real_indicator_panel_end_to_end():
    """Assert confluence consumes a #72-built panel (real keys) without raising."""
    pytest.importorskip("pandas_ta_classic")
    import numpy as np
    from openbb_techtrade.engine.indicators import build_indicator_panel

    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0.15, 1.0, 220))  # mild uptrend
    high = close + np.abs(rng.normal(0, 0.6, 220))
    low = close - np.abs(rng.normal(0, 0.6, 220))
    open_ = close + rng.normal(0, 0.4, 220)
    vol = rng.integers(1_000, 8_000, 220).astype(float)
    rows = [
        {
            "open": float(open_[i]),
            "high": float(high[i]),
            "low": float(low[i]),
            "close": float(close[i]),
            "volume": float(vol[i]),
        }
        for i in range(220)
    ]
    panel = build_indicator_panel("REAL", _AS_OF, rows)
    signal = build_signal(panel, "Information Technology", rank_in_segment=3)
    assert -1.0 <= signal.score <= 1.0
    assert signal.direction in {"long", "short", "flat"}
    assert signal.votes  # at least one indicator voted
