"""Unit tests for the signals orchestrator + confluence presets (issue #75, PRD §12.3, §9.2).

Fully offline and deterministic: hand-built ``IndicatorPanel`` literals are served
through an injected ``panel_fetcher`` so the whole movers->panels->confluence->rank
chain runs with no network, no API key, and no pandas-ta call. The bullish
``_gold_panel`` is the same literal #74 locks (score 0.8832 under ``trend_follow``);
the other panels exercise the flat and short branches and the signed-score ranking.

Covers the three Q4 presets (``trend_follow`` = the locked base, ``mean_revert``
and ``breakout`` tilts), the ``resolve_preset`` merge-override + validation (Q-D),
signed-score-descending ranking into a contiguous ``rank_in_segment``, the
preset-distinct score behaviour, and the per-vote weight-tilt attribution. It also
pins the carried-over #74 short-side volume inversion at the command layer.
"""

from __future__ import annotations

from datetime import date

import pytest
from openbb_techtrade.engine.confluence import DEFAULT_WEIGHTS, ConfluenceWeights
from openbb_techtrade.engine.signals import build_signals
from openbb_techtrade.models import IndicatorPanel, MoverSignal
from openbb_techtrade.strategies.presets import PRESETS, resolve_preset

_AS_OF = date(2024, 1, 12)


def _gold_panel(symbol: str = "GOLD") -> IndicatorPanel:
    """Build the bullish reference panel (#74's golden literal; trend_follow score 0.8832)."""
    return IndicatorPanel(
        symbol=symbol,
        as_of=_AS_OF,
        trend={"macd_hist": 0.85, "adx": 28.0, "ema_fast": 121.5, "ema_slow": 117.0, "ema_cross": 4.5},
        momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
        volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
        volume={"obv_slope": 12.0, "cmf": 0.18},
        candles={"cdl_engulfing": 1},
    )


def _flat_panel(symbol: str = "FLAT") -> IndicatorPanel:
    """Build a weak / mixed panel that resolves below the entry threshold (direction flat)."""
    return IndicatorPanel(
        symbol=symbol,
        as_of=_AS_OF,
        trend={"macd_hist": 0.10, "adx": 10.0, "ema_cross": -0.2},
        momentum={"rsi": 50.0, "stoch_k": 50.0, "stoch_d": 50.0},
        volatility={"bb_pctb": 0.50},
        volume={"obv_slope": 0.0, "cmf": 0.0},
    )


def _short_panel(symbol: str = "SHORT", *, volume: dict | None = None) -> IndicatorPanel:
    """Build a bearish panel (negative score, direction short); optional volume family."""
    return IndicatorPanel(
        symbol=symbol,
        as_of=_AS_OF,
        trend={"macd_hist": -0.85, "adx": 28.0, "ema_cross": -4.5},
        momentum={"rsi": 36.0, "stoch_k": 72.0, "stoch_d": 80.0},
        volume=volume or {},
    )


def _fetcher_for(*panels: IndicatorPanel):
    """Return an offline ``panel_fetcher`` that serves the given panels by symbol."""
    by_symbol = {p.symbol: p for p in panels}

    def _fetch(symbol: str, *, as_of: date) -> IndicatorPanel:
        return by_symbol[symbol]

    return _fetch


# --------------------------------------------------------------------------- presets


def test_presets_are_the_three_named_profiles():
    """Assert exactly the three named presets exist and trend_follow is the locked base."""
    assert set(PRESETS) == {"trend_follow", "mean_revert", "breakout"}
    assert PRESETS["trend_follow"] == DEFAULT_WEIGHTS  # L5: default preset IS the Q4 base
    assert all(isinstance(w, ConfluenceWeights) for w in PRESETS.values())


def test_every_preset_additive_trio_sums_to_85_and_volume_is_fixed():
    """Assert all presets preserve the 0.85 additive ceiling and pin volume at 0.15 (Q-B note 1)."""
    for name, w in PRESETS.items():
        assert w.trend + w.momentum + w.volatility == pytest.approx(0.85), name
        assert w.volume == pytest.approx(0.15), name  # volume amplitude is engine-fixed


def test_preset_tilts_match_q4_table():
    """Assert the locked per-preset weight tilts."""
    assert (PRESETS["mean_revert"].trend, PRESETS["mean_revert"].momentum) == (0.20, 0.40)
    assert PRESETS["mean_revert"].volatility == pytest.approx(0.25)
    assert (PRESETS["breakout"].trend, PRESETS["breakout"].momentum) == (0.25, 0.15)
    assert PRESETS["breakout"].volatility == pytest.approx(0.45)


def test_resolve_preset_by_name_returns_the_base_when_no_override():
    """Assert a bare preset lookup returns the registry weights unchanged."""
    assert resolve_preset("mean_revert") == PRESETS["mean_revert"]
    assert resolve_preset() == PRESETS["trend_follow"]  # default arg


def test_resolve_preset_unknown_name_raises_listing_valid():
    """Assert an unknown preset name raises ValueError listing the valid keys."""
    with pytest.raises(ValueError, match="bogus"):
        resolve_preset("bogus")


def test_resolve_preset_merges_partial_override():
    """Assert a partial {family: weight} override merges over the preset (unset families kept)."""
    merged = resolve_preset("trend_follow", {"trend": 0.50, "volatility": 0.10})
    assert (merged.trend, merged.momentum, merged.volatility) == (0.50, 0.25, 0.10)
    assert merged.volume == pytest.approx(0.15)  # untouched


def test_resolve_preset_override_unknown_family_raises():
    """Assert an unknown override key raises ValueError."""
    with pytest.raises(ValueError, match="momentumm"):
        resolve_preset("trend_follow", {"momentumm": 0.3})


def test_resolve_preset_override_must_preserve_additive_sum():
    """Assert a merged additive trio that breaks the 0.85 sum raises (Q-D: require exact sum)."""
    with pytest.raises(ValueError, match="0.85"):
        resolve_preset("trend_follow", {"trend": 0.50})  # 0.50+0.25+0.20 = 0.95


def test_resolve_preset_override_rejects_negative_and_out_of_range_volume():
    """Assert additive weights must be >= 0 and volume must stay within [0, 1]."""
    with pytest.raises(ValueError):
        resolve_preset("trend_follow", {"trend": -0.10, "volatility": 0.30})
    with pytest.raises(ValueError):
        resolve_preset("trend_follow", {"volume": 1.5})


# --------------------------------------------------------------------------- build_signals


def test_build_signals_requires_symbols_or_segment():
    """Assert build_signals with neither a symbol set nor a segment raises ValueError."""
    with pytest.raises(ValueError, match="symbols or segment"):
        build_signals(as_of=_AS_OF, panel_fetcher=_fetcher_for(_gold_panel()))


def test_build_signals_returns_mover_signals_with_full_attribution():
    """Assert build_signals returns MoverSignals carrying score, direction, and votes."""
    fetcher = _fetcher_for(_gold_panel())
    signals = build_signals(symbols=["GOLD"], segment="Information Technology", as_of=_AS_OF, panel_fetcher=fetcher)
    assert len(signals) == 1
    sig = signals[0]
    assert isinstance(sig, MoverSignal)
    assert sig.symbol == "GOLD"
    assert sig.segment == "Information Technology"
    assert sig.as_of == _AS_OF
    assert sig.score == pytest.approx(0.8832)
    assert sig.direction == "long"
    assert {v.family for v in sig.votes} == {"trend", "momentum", "volatility", "volume"}


def test_build_signals_ranks_signed_score_descending_contiguous():
    """Assert signals rank by signed score desc into a contiguous 1..N (most-long first)."""
    fetcher = _fetcher_for(_gold_panel("AAA"), _flat_panel("BBB"), _short_panel("CCC"))
    signals = build_signals(symbols=["CCC", "BBB", "AAA"], segment="Tech", as_of=_AS_OF, panel_fetcher=fetcher)
    assert [s.symbol for s in signals] == ["AAA", "BBB", "CCC"]  # 0.8832 > -0.10 > -0.60
    assert [s.rank_in_segment for s in signals] == [1, 2, 3]
    assert [s.direction for s in signals] == ["long", "flat", "short"]


def test_build_signals_tie_break_is_symbol_ascending():
    """Assert equal-score signals tie-break on symbol ascending (deterministic rank)."""
    fetcher = _fetcher_for(_gold_panel("ZZZ"), _gold_panel("AAA"))
    signals = build_signals(symbols=["ZZZ", "AAA"], segment="Tech", as_of=_AS_OF, panel_fetcher=fetcher)
    assert [s.symbol for s in signals] == ["AAA", "ZZZ"]
    assert [s.rank_in_segment for s in signals] == [1, 2]


def test_build_signals_symbols_mode_default_segment_label():
    """Assert symbols-mode without a segment labels the signals 'custom'."""
    signals = build_signals(symbols=["GOLD"], as_of=_AS_OF, panel_fetcher=_fetcher_for(_gold_panel()))
    assert signals[0].segment == "custom"


def test_presets_produce_distinct_scores_on_the_same_panel():
    """Assert the three presets yield pairwise-distinct scores for the same symbol (acceptance)."""
    fetcher = _fetcher_for(_gold_panel())
    scores = {
        preset: build_signals(symbols=["GOLD"], as_of=_AS_OF, preset=preset, panel_fetcher=fetcher)[0].score
        for preset in ("trend_follow", "mean_revert", "breakout")
    }
    assert scores["trend_follow"] == pytest.approx(0.8832)
    assert scores["mean_revert"] == pytest.approx(0.8395)
    assert scores["breakout"] == pytest.approx(0.8602)
    assert len(set(round(s, 6) for s in scores.values())) == 3  # pairwise distinct


def test_preset_weight_tilt_is_visible_in_vote_attribution():
    """Assert the resolved preset weights are stamped onto the votes (tilt is auditable, §4)."""
    fetcher = _fetcher_for(_gold_panel())
    sig = build_signals(symbols=["GOLD"], as_of=_AS_OF, preset="mean_revert", panel_fetcher=fetcher)[0]
    weight_by_family = {v.family: v.weight for v in sig.votes}
    assert weight_by_family["trend"] == pytest.approx(0.20)
    assert weight_by_family["momentum"] == pytest.approx(0.40)
    assert weight_by_family["volatility"] == pytest.approx(0.25)
    assert weight_by_family["volume"] == pytest.approx(0.15)  # engine-fixed amplitude


def test_custom_weights_override_changes_score_and_weights():
    """Assert a custom weights override flows through to both the score and the vote weights."""
    fetcher = _fetcher_for(_gold_panel())
    base = build_signals(symbols=["GOLD"], as_of=_AS_OF, panel_fetcher=fetcher)[0]
    tilted = build_signals(
        symbols=["GOLD"], as_of=_AS_OF, weights={"trend": 0.50, "volatility": 0.10}, panel_fetcher=fetcher
    )[0]
    assert tilted.score != pytest.approx(base.score)
    # raw = 0.50*1.0 + 0.25*0.8 + 0.10*0.84 = 0.784; score = 0.784 * 1.15
    assert tilted.score == pytest.approx(0.784 * 1.15)
    assert all(v.weight == pytest.approx(0.50) for v in tilted.votes if v.family == "trend")


def test_build_signals_deterministic_across_calls():
    """Assert two identical builds produce identical signal snapshots (no RNG / clock)."""
    fetcher = _fetcher_for(_gold_panel("AAA"), _short_panel("CCC"))
    first = build_signals(symbols=["AAA", "CCC"], as_of=_AS_OF, panel_fetcher=fetcher)
    second = build_signals(symbols=["AAA", "CCC"], as_of=_AS_OF, panel_fetcher=fetcher)
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_known_short_side_volume_inversion_at_command_layer():
    """Pin the carried #74 limitation: bearish volume DAMPS a short instead of confirming it.

    volume_confirmation has no sign(raw) term, so a bearish (negative) volume family
    on a short (raw<0) shrinks |score| rather than growing it. Documented here at the
    ranking layer; the direction-aware engine fix is deferred to separate scope.
    """
    fetcher = _fetcher_for(
        _short_panel("SN"),
        _short_panel("SV", volume={"obv_slope": -5.0, "cmf": -0.2}),
    )
    signals = build_signals(symbols=["SN", "SV"], as_of=_AS_OF, panel_fetcher=fetcher)
    by_symbol = {s.symbol: s for s in signals}
    # Bearish volume on a short reduces conviction (vc=0.85): |score| shrinks, not grows.
    assert abs(by_symbol["SV"].score) < abs(by_symbol["SN"].score)
