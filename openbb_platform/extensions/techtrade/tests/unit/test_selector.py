"""Unit tests for the reuse-first indicator source selector (issue #73, PRD §8).

Offline + deterministic. Locks: one source per indicator (no duplication), the
auto/classic/technical routing, ValueError on a bad source, and that the bulk
multi-symbol path returns the same panels as per-symbol build_panel.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.selector import (
    INDICATOR_SOURCE,
    build_panel,
    build_panels_bulk,
)
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)


def _rows(n: int = 220, seed: int = 20240112) -> list[dict]:
    """Build deterministic OHLCV rows for a given seed."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    return [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(n)
    ]


def test_source_map_has_no_duplicate_assignment():
    """Assert each indicator key maps to exactly one source string."""
    assert set(INDICATOR_SOURCE.values()) <= {"technical", "classic"}
    assert "obv_slope" in INDICATOR_SOURCE and INDICATOR_SOURCE["obv_slope"] == "classic"


def test_build_panel_auto_returns_panel():
    """Assert auto source yields a populated panel."""
    panel = build_panel("TEST", _AS_OF, _rows(), source="auto")
    assert isinstance(panel, IndicatorPanel)
    assert panel.trend and panel.momentum and panel.volatility and panel.volume


def test_build_panel_classic_matches_72():
    """Assert source='classic' equals the #72 builder exactly."""
    from openbb_techtrade.engine.indicators import build_indicator_panel
    a = build_panel("TEST", _AS_OF, _rows(), source="classic").model_dump()
    b = build_indicator_panel("TEST", _AS_OF, _rows()).model_dump()
    assert a == b


def test_unknown_source_raises():
    """Assert an unknown source string raises ValueError."""
    with pytest.raises(ValueError):
        build_panel("TEST", _AS_OF, _rows(), source="bogus")


def test_bulk_matches_per_symbol():
    """Assert the bulk path equals per-symbol build_panel for each symbol."""
    frames = {"AAA": _rows(seed=1), "BBB": _rows(seed=2)}
    bulk = build_panels_bulk(frames, _AS_OF, source="classic")
    assert set(bulk) == {"AAA", "BBB"}
    for sym, rows in frames.items():
        assert bulk[sym].model_dump() == build_panel(sym, _AS_OF, rows, source="classic").model_dump()
