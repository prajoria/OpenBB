"""Unit tests for the pandas-ta-classic IndicatorPanel adapter (issue #72, PRD §11).

Fully offline and deterministic: a fixed synthetic OHLCV frame (seeded numpy) is
fed straight into the pure ``build_indicator_panel`` -- no network, no API key. The
last bar is forced into a textbook doji so the candles family is non-empty. Covers
the five families populating, float typing, candle-sign normalisation, the
dict/attribute row readers, graceful degradation on too-few bars, and determinism.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import (
    DEFAULT_CONFIG,
    IndicatorConfig,
    build_indicator_panel,
    ohlcv_to_frame,
)
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)


def _synthetic_rows(n: int = 220) -> list[dict]:
    """Build deterministic OHLCV rows; force the last bar to a textbook doji."""
    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    rows = [
        {
            "open": float(open_[i]),
            "high": float(high[i]),
            "low": float(low[i]),
            "close": float(close[i]),
            "volume": float(vol[i]),
        }
        for i in range(n)
    ]
    mid = rows[-2]["close"]
    rows[-1] = {"open": mid, "high": mid + 2.0, "low": mid - 2.0, "close": mid, "volume": rows[-1]["volume"]}
    return rows


def test_panel_populates_all_five_families():
    """Assert every indicator family populates on a healthy frame."""
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    assert isinstance(panel, IndicatorPanel)
    assert panel.symbol == "TEST"
    assert panel.as_of == _AS_OF
    assert {"macd_hist", "adx", "ema_fast", "ema_slow", "ema_cross"} <= set(panel.trend)
    assert {"rsi", "stoch_k", "stoch_d"} <= set(panel.momentum)
    assert {"bb_pctb", "atr", "kc_upper", "kc_lower"} <= set(panel.volatility)
    assert {"obv_slope", "cmf"} <= set(panel.volume)
    assert panel.candles  # doji forced -> non-empty


def test_indicator_values_are_float():
    """Assert all numeric-family values are plain Python floats."""
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    for family in (panel.trend, panel.momentum, panel.volatility, panel.volume):
        for value in family.values():
            assert isinstance(value, float)


def test_ema_cross_is_fast_minus_slow():
    """Assert the ema_cross is exactly ema_fast minus ema_slow."""
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    assert panel.trend["ema_cross"] == pytest.approx(
        panel.trend["ema_fast"] - panel.trend["ema_slow"]
    )


def test_candle_signals_are_unit_ints():
    """Assert candle signals are non-zero unit ints (only fired patterns kept)."""
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    assert all(isinstance(v, int) and v in (-1, 0, 1) for v in panel.candles.values())
    assert all(v != 0 for v in panel.candles.values())  # only fired patterns kept


def test_accepts_attribute_rows():
    """Assert attribute-style OHLCV rows are accepted like dict rows."""
    rows = [SimpleNamespace(**r) for r in _synthetic_rows()]
    panel = build_indicator_panel("TEST", _AS_OF, rows)
    assert panel.trend and panel.momentum


def test_accepts_decimal_volume():
    """Assert Decimal volume is coerced to float without error."""
    rows = _synthetic_rows()
    for r in rows:
        r["volume"] = Decimal(str(int(r["volume"])))
    panel = build_indicator_panel("TEST", _AS_OF, rows)
    assert "obv_slope" in panel.volume


def test_too_few_bars_degrades_without_raising():
    """Assert too-few bars degrade gracefully, omitting long-period keys."""
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows(3))
    assert isinstance(panel, IndicatorPanel)
    # Long-period indicators cannot warm up; their keys are simply absent.
    assert "ema_slow" not in panel.trend


def test_empty_rows_raises_value_error():
    """Assert an empty OHLCV input raises ``ValueError``."""
    with pytest.raises(ValueError):
        build_indicator_panel("TEST", _AS_OF, [])


def test_panel_is_deterministic():
    """Assert two builds over identical input are byte-for-byte equal."""
    rows = _synthetic_rows()
    a = build_indicator_panel("TEST", _AS_OF, rows).model_dump()
    b = build_indicator_panel("TEST", _AS_OF, rows).model_dump()
    assert a == b


def test_ohlcv_to_frame_lowercases_and_orders():
    """Assert the frame has canonical lowercase columns in OHLCV order."""
    frame = ohlcv_to_frame(_synthetic_rows(5))
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 5


def test_default_config_matches_prd_periods():
    """Assert ``DEFAULT_CONFIG`` carries the PRD §11 default periods."""
    assert (DEFAULT_CONFIG.macd_fast, DEFAULT_CONFIG.macd_slow, DEFAULT_CONFIG.macd_signal) == (12, 26, 9)
    assert DEFAULT_CONFIG.ema_fast == 20 and DEFAULT_CONFIG.ema_slow == 50
    assert DEFAULT_CONFIG.rsi_length == 14 and DEFAULT_CONFIG.bb_length == 20
    assert isinstance(IndicatorConfig(), IndicatorConfig)


def test_build_panel_for_symbol_uses_injected_fetcher():
    """Assert the wrapper routes through an injected fetcher and snaps the session."""
    from openbb_techtrade.engine.indicators import build_panel_for_symbol

    rows = _synthetic_rows()
    captured = {}

    def fake_fetcher(symbol, as_of, **kwargs):
        captured["symbol"] = symbol
        return rows

    panel = build_panel_for_symbol("ABC", as_of="2024-01-13", ohlcv_fetcher=fake_fetcher)
    assert captured["symbol"] == "ABC"
    assert panel.symbol == "ABC"
    assert panel.as_of == date(2024, 1, 12)  # Saturday snapped back to Friday
    assert panel.trend and panel.momentum and panel.volatility and panel.volume
