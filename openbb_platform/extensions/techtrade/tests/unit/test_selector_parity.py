"""Parity oracle: pandas-ta-classic vs OpenBB-technical for the shared set (#73, PRD §8).

Runs ONLY where openbb_technical is installed (CI); importorskip skips it cleanly
on a checkout without the technical extension. For each indicator the selector
sources from `technical`, the classic value must agree within tolerance -- proving
"the same" indicator never diverges between sources.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")
pytest.importorskip("openbb_technical")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.engine.indicators_technical import technical_panel

_AS_OF = date(2024, 1, 12)
_TOL = 1e-6


def _rows(n: int = 220) -> list[dict]:
    """Build a deterministic synthetic OHLCV frame."""
    rng = np.random.default_rng(20240112)
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


@pytest.mark.parametrize("family", ["trend", "momentum", "volatility"])
def test_classic_technical_parity(family):
    """Assert classic and technical agree within tolerance for shared-set keys.

    Also assert the technical leg populates the *same* keys as classic for the
    family -- otherwise a silently-omitted technical key (a prefix mismatch that
    drops the column) would pass vacuously by shrinking the compared intersection.
    """
    classic = getattr(build_indicator_panel("X", _AS_OF, _rows()), family)
    tech = getattr(technical_panel("X", _AS_OF, _rows()), family)
    assert set(tech) == set(classic), (
        f"{family}: technical keys {sorted(tech)} != classic keys {sorted(classic)}"
    )
    for key in classic:
        assert abs(classic[key] - tech[key]) <= _TOL, f"{family}.{key} diverged"
