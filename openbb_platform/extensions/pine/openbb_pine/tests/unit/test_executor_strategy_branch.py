"""run_compiled() strategy branch — bd-liz.

When a compiled strategy runs, the OBBject result carries:
  - result.extra['stats'] — dict-form of pynecore StrategyStatistics
  - result.extra['equity_curve'] — list of {bar_index, equity, drawdown}

For indicator scripts, neither key is present. For library scripts,
compile_pine raises PineUnsupportedFeatureError PF011 (M3-deferred).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from openbb_pine.errors import PineUnsupportedFeatureError
from openbb_pine.runtime.executor_shell import run_compiled
from pyne_compiler.compiler import compile_pine


def _byo_bars(n: int = 60) -> pd.DataFrame:
    """Synthetic BYO OHLCV DataFrame."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz=timezone.utc, name="date")
    close = 100.0 + np.cumsum(np.random.default_rng(42).normal(0, 1, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=idx,
    )


def test_strategy_result_carries_stats_dict():
    src = '//@version=6\nstrategy("MyStrat")\nplot(close)\n'
    compiled = compile_pine(src, use_cache=False)
    assert compiled.script_type == "strategy"
    bars = _byo_bars()
    result = run_compiled(compiled, provider_or_data=bars, symbol="X", interval="1d")
    assert "stats" in result.extra
    stats = result.extra["stats"]
    assert isinstance(stats, dict)
    for key in ("net_profit", "gross_profit", "closed_trades"):
        assert key in stats, f"missing {key!r} in stats keys: {sorted(stats.keys())}"


def test_strategy_result_carries_equity_curve():
    src = '//@version=6\nstrategy("s")\nplot(close)\n'
    compiled = compile_pine(src, use_cache=False)
    bars = _byo_bars()
    result = run_compiled(compiled, provider_or_data=bars, symbol="X", interval="1d")
    curve = result.extra.get("equity_curve")
    assert curve is not None
    assert isinstance(curve, list)
    assert len(curve) == len(bars)
    assert set(curve[0].keys()) >= {"bar_index", "equity", "drawdown"}


def test_indicator_result_omits_stats_and_equity():
    src = '//@version=6\nindicator("i")\nplot(close)\n'
    compiled = compile_pine(src, use_cache=False)
    assert compiled.script_type == "indicator"
    bars = _byo_bars()
    result = run_compiled(compiled, provider_or_data=bars, symbol="X", interval="1d")
    assert "stats" not in result.extra
    assert "equity_curve" not in result.extra


def test_library_raises_pf011():
    src = '//@version=6\nlibrary("L")\n'
    with pytest.raises(PineUnsupportedFeatureError) as exc:
        compile_pine(src, use_cache=False)
    assert "PF011" in str(exc.value)
