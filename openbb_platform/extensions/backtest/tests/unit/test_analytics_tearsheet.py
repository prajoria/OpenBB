"""Unit tests for ``analytics/tearsheet.py`` (component 07, §2).

Covers :func:`compute_benchmark_stats` (alpha/beta/information-ratio vs a
benchmark) and :func:`build_tearsheet` (structured :class:`TearSheet` with rolling
Sharpe, worst-first drawdown periods, monthly-return buckets and embedded
:class:`PerformanceMetrics`).

pyfolio-reloaded cannot be installed in this environment (it pins ``pandas<3.0``),
so the **in-house pandas path is canonical** and is what these unit tests exercise;
the pyfolio-present parity path lives in
``tests/integration/test_analytics_tearsheet_integration.py`` (importorskip, skipped
here). Heavy deps stay lazy: importing the module never imports pyfolio.

See ``docs/designs/backtest-design/07-analytics.md`` §2.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

_BACKTEST_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


# ---- helpers -------------------------------------------------------------


def _returns_from_equity(levels: list[float]) -> pd.Series:
    """Normalized return series implied by an explicit equity path (first 0)."""
    idx = pd.date_range("2021-01-04", periods=len(levels), freq="D", tz="UTC")
    arr = np.asarray(levels, dtype=float)
    rets = np.zeros_like(arr)
    rets[1:] = arr[1:] / arr[:-1] - 1.0
    return pd.Series(rets, index=idx, name="returns")


def _year_returns(seed: int = 5, periods: int = 400) -> pd.Series:
    """A ~1.5y business-day normalized return series with a mild up-drift."""
    idx = pd.date_range("2021-01-04", periods=periods, freq="B", tz="UTC")
    rng = np.random.default_rng(seed)
    vals = rng.normal(0.0006, 0.011, periods)
    vals[0] = 0.0
    return pd.Series(vals, index=idx, name="returns")


def _force_fallback(monkeypatch) -> None:
    """Force :func:`build_tearsheet` onto the in-house (no-pyfolio) path."""
    import openbb_backtest.analytics.tearsheet as t

    monkeypatch.setattr(t, "_pyfolio", lambda: None)


# ---- build_tearsheet (fallback path) -------------------------------------


def test_build_tearsheet_is_populated(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet
    from openbb_backtest.models import PerformanceMetrics, TearSheet

    _force_fallback(monkeypatch)
    returns = _year_returns()
    ts = build_tearsheet(returns, benchmark=None, trades=[], sessions_per_year=252)

    assert isinstance(ts, TearSheet)
    assert isinstance(ts.metrics, PerformanceMetrics)
    assert len(ts.rolling_sharpe) > 0
    assert all(np.isfinite(x) for x in ts.rolling_sharpe)
    assert len(ts.monthly_returns) > 0
    assert ts.html_path is None  # export is C07.5, not here
    assert ts.benchmark_relative is None  # no benchmark given


def test_build_tearsheet_embeds_compute_metrics(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    _force_fallback(monkeypatch)
    returns = _year_returns()
    ts = build_tearsheet(returns, None, [], sessions_per_year=252)
    expected = compute_metrics(returns, None, [], sessions_per_year=252)
    assert ts.metrics == expected


def test_drawdown_periods_are_worst_first(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    _force_fallback(monkeypatch)
    # Two drawdowns: -10% (110->99) then a deeper -25% (120->90), both recover.
    returns = _returns_from_equity([100, 110, 99, 105, 120, 90, 130])
    ts = build_tearsheet(returns, None, [], sessions_per_year=252)

    assert len(ts.drawdown_periods) >= 2
    depths = [d.depth for d in ts.drawdown_periods]
    # Worst (most negative) first.
    assert depths == sorted(depths)
    # Deepest is the 120->90 = -25% episode; shallower is the 110->99 = -10% one.
    assert ts.drawdown_periods[0].depth == pytest.approx(90 / 120 - 1, abs=1e-9)
    assert ts.drawdown_periods[1].depth == pytest.approx(99 / 110 - 1, abs=1e-9)
    for d in ts.drawdown_periods:
        assert d.length >= 1
        assert d.start <= d.valley <= d.end


def test_monthly_returns_compound_within_month(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    _force_fallback(monkeypatch)
    returns = _year_returns()
    ts = build_tearsheet(returns, None, [], sessions_per_year=252)

    # Each bucket is the compounded monthly total return.
    expected = (1.0 + returns).resample("ME").prod() - 1.0
    got = {(m.year, m.month): m.ret for m in ts.monthly_returns}
    assert len(got) == len(expected)
    for stamp, val in expected.items():
        assert got[(stamp.year, stamp.month)] == pytest.approx(float(val), abs=1e-12)


def test_rolling_sharpe_respects_window(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    _force_fallback(monkeypatch)
    returns = _year_returns(periods=120)
    window = 21
    ts = build_tearsheet(
        returns, None, [], sessions_per_year=252, rolling_window=window
    )
    # A rolling window of W over N points yields N-W+1 non-NaN values.
    assert len(ts.rolling_sharpe) == len(returns) - window + 1


# ---- benchmark-relative --------------------------------------------------


def test_benchmark_relative_present_when_benchmark_given(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet
    from openbb_backtest.models import BenchmarkStats

    _force_fallback(monkeypatch)
    returns = _year_returns(seed=1)
    bench = _year_returns(seed=2)
    ts = build_tearsheet(returns, bench, [], sessions_per_year=252)
    assert isinstance(ts.benchmark_relative, BenchmarkStats)
    assert np.isfinite(ts.benchmark_relative.information_ratio)


def test_information_ratio_positive_when_beating_benchmark(monkeypatch):
    from openbb_backtest.analytics.tearsheet import compute_benchmark_stats

    _force_fallback(monkeypatch)
    bench = _year_returns(seed=9)
    # Strategy beats the benchmark by a noisy ~+6bps/session => positive, finite IR
    # (noise gives non-zero tracking error so the ratio is well-defined).
    rng = np.random.default_rng(11)
    active = rng.normal(0.0006, 0.0008, len(bench))
    returns = bench + active
    returns.name = "returns"
    stats = compute_benchmark_stats(returns, bench, sessions_per_year=252)
    assert stats.information_ratio > 0
    assert np.isfinite(stats.information_ratio)
    assert np.isfinite(stats.alpha)
    assert np.isfinite(stats.beta)


def test_information_ratio_negative_when_lagging_benchmark(monkeypatch):
    from openbb_backtest.analytics.tearsheet import compute_benchmark_stats

    _force_fallback(monkeypatch)
    bench = _year_returns(seed=9)
    rng = np.random.default_rng(12)
    active = rng.normal(-0.0006, 0.0008, len(bench))  # noisy underperformance
    returns = bench + active
    returns.name = "returns"
    stats = compute_benchmark_stats(returns, bench, sessions_per_year=252)
    assert stats.information_ratio < 0
    assert np.isfinite(stats.information_ratio)


def test_compute_benchmark_stats_self_is_unit_beta_zero_alpha_ir(monkeypatch):
    from openbb_backtest.analytics.tearsheet import compute_benchmark_stats

    _force_fallback(monkeypatch)
    returns = _year_returns(seed=4)
    stats = compute_benchmark_stats(returns, returns.copy(), sessions_per_year=252)
    assert stats.beta == pytest.approx(1.0, abs=1e-9)
    assert stats.alpha == pytest.approx(0.0, abs=1e-9)
    # Zero active return => zero tracking error => IR defined as 0.0.
    assert stats.information_ratio == pytest.approx(0.0, abs=1e-12)


# ---- privacy gate --------------------------------------------------------


def test_build_tearsheet_rejects_non_normalized_returns(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    _force_fallback(monkeypatch)
    dollars = pd.Series(
        [100000.0, 101000.0, 99990.0],
        index=pd.date_range("2021-01-04", periods=3, freq="D", tz="UTC"),
    )
    with pytest.raises(ValueError):
        build_tearsheet(dollars, None, [], sessions_per_year=252)


def test_build_tearsheet_rejects_decimal_returns(monkeypatch):
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    _force_fallback(monkeypatch)
    decimals = pd.Series([Decimal("0.01"), Decimal("-0.02")])
    with pytest.raises((TypeError, ValueError)):
        build_tearsheet(decimals, None, [], sessions_per_year=252)


# ---- lazy-import guard ---------------------------------------------------


def test_tearsheet_imports_and_runs_with_heavy_deps_absent():
    """build_tearsheet must run with pyfolio/quantstats/ffn/numba forced absent."""
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_BACKTEST_ROOT!r})
        for m in ("pyfolio", "quantstats", "ffn", "numba"):
            sys.modules[m] = None
        import numpy as np, pandas as pd
        from openbb_backtest.analytics.tearsheet import build_tearsheet
        idx = pd.date_range("2021-01-04", periods=80, freq="B", tz="UTC")
        rng = np.random.default_rng(0)
        r = pd.Series(rng.normal(0.0005, 0.01, 80), index=idx, name="returns")
        r.iloc[0] = 0.0
        ts = build_tearsheet(r, None, [], 252, rolling_window=20)
        assert ts.benchmark_relative is None
        assert len(ts.rolling_sharpe) > 0
        print("OK", len(ts.monthly_returns))
        """
    )
    # Fixed self-authored script via the current interpreter — the S603 precondition.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK ")
