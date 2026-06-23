"""Golden-value regression lock for the bulk selector (issue #73, #71 harness).

Builds panels for a fixed two-symbol seeded batch via ``build_panels_bulk`` (classic
source, so the lock is hermetic and reproducible without the technical extension) and
locks the whole ``{symbol: panel}`` mapping against a committed golden JSON within
DEFAULT_TOL. Carries the ``golden`` marker. Regenerate intentionally after a
*reviewed* change with TECHTRADE_REGEN_GOLDEN=1 -- never blindly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.selector import build_panels_bulk
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
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


def _snapshot():
    """Return the bulk-panel mapping (model_dump per symbol) for the fixed batch."""
    frames = {"AAA": _rows(seed=1), "BBB": _rows(seed=2)}
    panels = build_panels_bulk(frames, _AS_OF, source="classic")
    return {symbol: panel.model_dump() for symbol, panel in panels.items()}


def test_selector_bulk_matches_golden():
    """Lock the two-symbol bulk panels against the committed golden fixture."""
    assert_matches_golden("selector_panel_synthetic", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_selector_bulk_is_deterministic():
    """Assert two bulk snapshots over identical input are equal."""
    assert _snapshot() == _snapshot()
