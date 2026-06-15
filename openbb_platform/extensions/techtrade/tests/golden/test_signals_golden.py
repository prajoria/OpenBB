"""Golden-score regression lock for the signals orchestrator + presets (#75, #71 harness, PRD §12.3).

Exercises the **full** signals chain end-to-end -- preset resolution -> universe ->
panels -> #74 confluence -> signed-score ranking -- yet stays **offline + deterministic**
by injecting a ``panel_fetcher`` seam over hand-built fixture panels at a fixed ``as_of``.
Each of the three presets locks its full ranked ``list[MoverSignal]`` (score + direction +
every IndicatorVote, including the preset-tilted weights) against a committed golden JSON
within DEFAULT_TOL.

Like #74's golden (which locks ``build_signal`` directly), the lock runs through the pure
``engine.signals.build_signals`` core -- the deterministic seam the offline fetcher plugs
into -- rather than the live router command (whose locked 4-arg signature takes no fetcher
per the pipeline contract). A separate assertion confirms the thin ``signals_router.signals``
command forwards to this same core. Carries the ``golden`` marker. Regenerate intentionally
after a *reviewed* change with ``TECHTRADE_REGEN_GOLDEN=1`` -- never blindly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openbb_techtrade.engine.signals import build_signals
from openbb_techtrade.models import IndicatorPanel, MoverSignal
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)
_SEGMENT = "Information Technology"

#: A small, distinct universe: a strong-long, a flat, and a short panel, so the
#: golden locks the cross-symbol signed-score ranking as well as the per-symbol scores.
_PANELS: dict[str, IndicatorPanel] = {
    "AAA": IndicatorPanel(
        symbol="AAA",
        as_of=_AS_OF,
        trend={"macd_hist": 0.85, "adx": 28.0, "ema_fast": 121.5, "ema_slow": 117.0, "ema_cross": 4.5},
        momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
        volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
        volume={"obv_slope": 12.0, "cmf": 0.18},
        candles={"cdl_engulfing": 1},
    ),
    "BBB": IndicatorPanel(
        symbol="BBB",
        as_of=_AS_OF,
        trend={"macd_hist": 0.10, "adx": 10.0, "ema_cross": -0.2},
        momentum={"rsi": 50.0, "stoch_k": 50.0, "stoch_d": 50.0},
        volatility={"bb_pctb": 0.50},
        volume={"obv_slope": 0.0, "cmf": 0.0},
    ),
    "CCC": IndicatorPanel(
        symbol="CCC",
        as_of=_AS_OF,
        trend={"macd_hist": -0.85, "adx": 28.0, "ema_cross": -4.5},
        momentum={"rsi": 36.0, "stoch_k": 72.0, "stoch_d": 80.0},
        volatility={"bb_pctb": 0.10},
        volume={"obv_slope": -8.0, "cmf": -0.2},
    ),
}
_SYMBOLS = ["CCC", "BBB", "AAA"]  # deliberately unranked so the lock proves the sort


def _fake_fetcher(symbol: str, *, as_of: date) -> IndicatorPanel:
    """Serve a hand-built fixture panel by symbol (offline determinism seam)."""
    return _PANELS[symbol]


def _run(preset: str) -> list[MoverSignal]:
    """Run the full signals chain offline for one preset and return its ranked signals."""
    return build_signals(
        symbols=_SYMBOLS,
        segment=_SEGMENT,
        preset=preset,
        as_of=_AS_OF,
        panel_fetcher=_fake_fetcher,
    )


@pytest.mark.parametrize("preset", ["trend_follow", "mean_revert", "breakout"])
def test_signals_chain_matches_golden(preset: str):
    """Assert each preset's full ranked signal list matches its committed golden fixture."""
    assert_matches_golden(f"signals_{preset}", _run(preset), fixture_dir=_FIXTURE_DIR)


def test_signals_results_are_mover_signals():
    """Assert the chain yields MoverSignals (the OBBject[list[MoverSignal]] payload, L2)."""
    assert all(isinstance(s, MoverSignal) for s in _run("trend_follow"))


def test_presets_produce_distinct_golden_scores():
    """Assert the three presets give pairwise-distinct scores for the shared top symbol."""
    top_scores = {preset: _run(preset)[0].score for preset in ("trend_follow", "mean_revert", "breakout")}
    assert len({round(s, 6) for s in top_scores.values()}) == 3


def test_signals_chain_is_deterministic():
    """Assert two runs of the same preset produce an identical signal snapshot."""
    assert [s.model_dump() for s in _run("breakout")] == [s.model_dump() for s in _run("breakout")]


def test_router_command_forwards_to_core(monkeypatch):
    """Assert the thin router command wraps the same core build_signals output in an OBBject."""
    import openbb_techtrade.engine.signals as signals_engine
    from openbb_core.app.model.obbject import OBBject
    from openbb_techtrade.engine.signals_router import signals

    expected = _run("mean_revert")
    captured: dict = {}

    def _fake_build_signals(symbols=None, segment=None, **kwargs):
        captured["symbols"] = symbols
        captured["segment"] = segment
        captured["preset"] = kwargs.get("preset")
        captured["as_of"] = kwargs.get("as_of")
        return expected

    # The command lazily imports build_signals from engine.signals inside its body,
    # so patch the source module (mirrors screener_router's in-body import style).
    monkeypatch.setattr(signals_engine, "build_signals", _fake_build_signals)
    result = signals(segment=_SEGMENT, symbols=_SYMBOLS, preset="mean_revert", as_of=_AS_OF.isoformat())
    assert isinstance(result, OBBject)
    assert result.results is expected
    assert captured == {"symbols": _SYMBOLS, "segment": _SEGMENT, "preset": "mean_revert", "as_of": _AS_OF.isoformat()}
