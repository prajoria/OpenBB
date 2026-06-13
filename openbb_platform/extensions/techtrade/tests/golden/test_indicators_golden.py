"""Golden-value regression lock for the IndicatorPanel builder (#72, #71 harness).

Builds the panel over a fixed seeded synthetic OHLCV frame (last bar forced to a
doji so the candles family is non-empty) and locks the full panel against a
committed golden JSON within DEFAULT_TOL. Carries the ``golden`` marker. Regenerate
intentionally after a *reviewed* change with TECHTRADE_REGEN_GOLDEN=1 -- never blindly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)


def _rows(n: int = 220) -> list[dict]:
    """Build the fixed seeded OHLCV rows, last bar forced to a doji."""
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


def _snapshot():
    """Return the panel model_dump for the fixed synthetic frame."""
    return build_indicator_panel("SYNTH", _AS_OF, _rows()).model_dump()


def test_indicator_panel_matches_golden():
    """Lock the synthetic panel against the committed golden fixture."""
    assert_matches_golden("indicator_panel_synthetic", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_indicator_panel_is_deterministic():
    """Assert two snapshots over identical input are equal."""
    assert _snapshot() == _snapshot()
