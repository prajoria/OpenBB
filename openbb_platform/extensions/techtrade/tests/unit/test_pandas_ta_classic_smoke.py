"""Smoke test for the vendored pandas-ta-classic submodule (#67).

Confirms the commit-pinned, editable-installed first-party fork imports and that
its pandas ``.ta`` accessor produces both a classic indicator (RSI) and a
candlestick pattern on sample OHLCV. This guards the vendoring contract that the
indicator engine (#72) builds on; it does not test indicator math correctness.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pandas_ta_classic = pytest.importorskip("pandas_ta_classic")


def _sample_ohlcv(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = pd.Series(100.0 + np.cumsum(rng.standard_normal(n)), name="close")
    high = close + rng.random(n)
    low = close - rng.random(n)
    # Keep open within [low, high] so every bar is well-formed OHLC.
    open_ = low + (high - low) * rng.random(n)
    volume = pd.Series(rng.integers(1_000_000, 5_000_000, n).astype(float))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def test_import_succeeds():
    assert pandas_ta_classic is not None
    # The package exposes a Category map describing the indicator families.
    assert isinstance(pandas_ta_classic.Category, dict)
    assert pandas_ta_classic.Category  # non-empty


def test_rsi_indicator_returns_values():
    df = _sample_ohlcv()
    rsi = df.ta.rsi()
    assert isinstance(rsi, pd.Series)
    valid = rsi.dropna()
    assert not valid.empty
    # RSI is bounded in [0, 100].
    assert float(valid.min()) >= 0.0
    assert float(valid.max()) <= 100.0


def test_candlestick_pattern_returns_values():
    df = _sample_ohlcv()
    doji = df.ta.cdl_pattern(name="doji")
    assert isinstance(doji, pd.DataFrame)
    assert len(doji) == len(df)
    values = doji.to_numpy()
    # Pattern signals are one of {-100, 0, 100} (TA-Lib convention).
    allowed = {-100.0, 0.0, 100.0}
    observed = set(np.unique(values[~np.isnan(values)]).tolist())
    assert observed.issubset(allowed)
    # The detector must actually fire on this fixture, not return all zeros.
    assert np.count_nonzero(values) > 0
