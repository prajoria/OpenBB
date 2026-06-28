"""Unit tests for the OpenBB-technical IndicatorPanel adapter (issue #73, PRD §8/§11).

Fully offline. Because openbb_technical is not installed in this checkout, the
adapter must degrade to the #72 pandas-ta-classic builder and return an identical
panel -- these tests lock that graceful-fallback contract plus the availability
probe. A seeded synthetic frame (last bar a doji) drives the build.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.engine.indicators_technical import (
    _obb_technical_available,
    technical_panel,
)
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)


def _rows(n: int = 220) -> list[dict]:
    """Build deterministic OHLCV rows; force the last bar to a doji."""
    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    rows = [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(n)
    ]
    mid = rows[-2]["close"]
    rows[-1] = {"open": mid, "high": mid + 2.0, "low": mid - 2.0, "close": mid, "volume": rows[-1]["volume"]}
    return rows


def test_availability_probe_is_bool():
    """Assert the technical-availability probe returns a plain bool, never raises."""
    assert isinstance(_obb_technical_available(), bool)


def test_technical_panel_returns_panel():
    """Assert technical_panel builds a populated IndicatorPanel for the symbol."""
    panel = technical_panel("TEST", _AS_OF, _rows())
    assert isinstance(panel, IndicatorPanel)
    assert panel.symbol == "TEST"
    assert panel.trend and panel.momentum and panel.volatility and panel.volume


def test_falls_back_to_classic_when_technical_absent():
    """Assert that, with technical absent, the panel equals the #72 classic panel."""
    if _obb_technical_available():
        pytest.skip("openbb_technical present; fallback path not exercised here")
    expected = build_indicator_panel("TEST", _AS_OF, _rows())
    assert technical_panel("TEST", _AS_OF, _rows()).model_dump() == expected.model_dump()
