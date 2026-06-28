"""Structured tear sheet + benchmark-relative stats (component 07, §2).

:func:`build_tearsheet` turns a normalized return series (plus an optional
benchmark and the executed trades) into a structured
:class:`~openbb_backtest.models.TearSheet`: the embedded
:class:`~openbb_backtest.models.PerformanceMetrics` (from
:func:`~openbb_backtest.analytics.metrics.compute_metrics`), a rolling-Sharpe
series, worst-first drawdown periods, per-month return buckets, and — when a
benchmark is supplied — :class:`~openbb_backtest.models.BenchmarkStats`
(alpha/beta/information-ratio) via :func:`compute_benchmark_stats`.

Dependency policy (see memory ``backtest-impl-env-constraints``):

- **pyfolio-reloaded** pins ``pandas<3.0`` and is *not* installable in this fork's
  environment, so the **in-house pandas implementation is canonical** and is what
  the unit suite exercises. pyfolio is *lazy-imported* via
  :func:`~openbb_backtest.analytics._common.optional_import`; when present it is
  used as the drawdown-table source and validated by an importorskip integration
  test, otherwise the in-house path runs.
- **Privacy:** the input returns pass through
  :func:`~openbb_backtest.analytics._common.assert_normalized` first, and every
  field on the emitted :class:`TearSheet` is a normalized float — never a dollar
  amount, account number, or lot detail (fork privacy rule).

See ``docs/designs/backtest-design/07-analytics.md`` §2.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from openbb_backtest.analytics._common import assert_normalized, optional_import
from openbb_backtest.analytics.metrics import compute_metrics
from openbb_backtest.models import (
    BenchmarkStats,
    DrawdownPeriod,
    MonthlyReturn,
    TearSheet,
)

if TYPE_CHECKING:
    from openbb_backtest.models import Trade

#: Default rolling-Sharpe lookback (sessions). One trading month ≈ 21 sessions.
_DEFAULT_ROLLING_WINDOW = 21


def _pyfolio() -> ModuleType | None:
    """Return the ``pyfolio`` module, or ``None`` when it is not installed.

    Lazy + swallowing so the tear sheet degrades to the in-house pandas path
    rather than failing when the optional dependency is absent. Patched in unit
    tests to force the in-house path deterministically.
    """
    try:
        return optional_import("pyfolio")
    except ImportError:
        return None


def build_tearsheet(
    returns: pd.Series,
    benchmark: pd.Series | None,
    trades: list[Trade],
    sessions_per_year: int,
    *,
    rolling_window: int = _DEFAULT_ROLLING_WINDOW,
) -> TearSheet:
    """Build a structured :class:`TearSheet` from returns, benchmark and trades.

    Parameters
    ----------
    returns
        Normalized per-session float returns (validated by the privacy gate).
    benchmark
        Optional benchmark return series; drives ``benchmark_relative`` and the
        metrics' beta/alpha. ``None`` leaves ``benchmark_relative`` ``None``.
    trades
        Executed trades, forwarded to :func:`compute_metrics` for
        win-rate/profit-factor/turnover.
    sessions_per_year
        Trading sessions per year (config calendar); drives all annualization.
    rolling_window
        Lookback (sessions) for the rolling-Sharpe series.
    """
    assert_normalized(returns)
    metrics = compute_metrics(returns, benchmark, trades, sessions_per_year)

    rolling_sharpe = _rolling_sharpe(returns, rolling_window, sessions_per_year)
    drawdown_periods = _drawdown_periods(returns)
    monthly_returns = _monthly_returns(returns)

    benchmark_relative: BenchmarkStats | None = None
    if benchmark is not None:
        benchmark_relative = compute_benchmark_stats(
            returns, benchmark, sessions_per_year
        )

    return TearSheet(
        metrics=metrics,
        rolling_sharpe=rolling_sharpe,
        drawdown_periods=drawdown_periods,
        monthly_returns=monthly_returns,
        html_path=None,  # artifact export is component 07.5
        benchmark_relative=benchmark_relative,
    )


def compute_benchmark_stats(
    returns: pd.Series, benchmark: pd.Series, sessions_per_year: int
) -> BenchmarkStats:
    """Benchmark-relative ``alpha`` / ``beta`` / ``information_ratio``.

    ``beta`` is ``cov(r, b)/var(b)`` (ddof=1) and ``alpha`` is the geometrically
    annualized intercept ``(1 + mean(r - beta*b))**spy - 1`` — matching the
    metrics layer (and empyrical) so the tear sheet and ``PerformanceMetrics``
    agree. ``information_ratio`` is the annualized active return over tracking
    error: ``mean(active)/std(active, ddof=1) * sqrt(spy)``; with zero tracking
    error (identical series) it is defined as ``0.0``.
    """
    r, b = _aligned(returns, benchmark)
    rv = r.to_numpy(dtype=float)
    bv = b.to_numpy(dtype=float)
    spy = float(sessions_per_year)

    if rv.size < 2:
        return BenchmarkStats(alpha=0.0, beta=0.0, information_ratio=0.0)

    cov = np.cov(rv, bv, ddof=1)
    var_b = float(cov[1, 1])
    beta = float(cov[0, 1] / var_b) if var_b != 0.0 else 0.0
    alpha_daily = float(np.mean(rv - beta * bv))
    alpha = float((1.0 + alpha_daily) ** spy - 1.0)

    active = rv - bv
    te = float(active.std(ddof=1)) if active.size > 1 else 0.0
    info_ratio = float(active.mean() / te * np.sqrt(spy)) if te > 0 else 0.0

    return BenchmarkStats(
        alpha=_finite(alpha),
        beta=_finite(beta),
        information_ratio=_finite(info_ratio),
    )


# --- rolling Sharpe -------------------------------------------------------


def _rolling_sharpe(returns: pd.Series, window: int, sessions_per_year: int) -> list[float]:
    """Annualized rolling Sharpe over ``window`` sessions (non-NaN values only).

    Uses sample std (ddof=1) to match pandas' rolling default; the resulting
    series has ``len(returns) - window + 1`` finite points.
    """
    spy = float(sessions_per_year)
    roll = returns.rolling(window)
    mean = roll.mean()
    std = roll.std(ddof=1)
    sharpe = (mean / std) * np.sqrt(spy)
    sharpe = sharpe.replace([np.inf, -np.inf], np.nan).dropna()
    return [float(x) for x in sharpe.to_numpy()]


# --- drawdown periods -----------------------------------------------------


def _drawdown_periods(returns: pd.Series) -> list[DrawdownPeriod]:
    """Worst-first peak→valley→recovery drawdown episodes from a return series.

    Builds a normalized equity curve, then segments it into episodes that begin
    when equity first dips below a running peak and end when that peak is
    regained (the final, unrecovered episode ends at the last session). ``depth``
    is the trough's fractional drop from the peak (negative).
    """
    if returns.shape[0] == 0:
        return []
    idx = returns.index
    equity = (1.0 + returns).cumprod().to_numpy(dtype=float)

    episodes: list[DrawdownPeriod] = []
    peak = equity[0]
    peak_i = 0
    valley = equity[0]
    valley_i = 0
    in_dd = False

    for i in range(1, equity.shape[0]):
        value = equity[i]
        if value >= peak:
            if in_dd:  # recovered: close the episode at this session
                episodes.append(_episode(idx, peak, peak_i, valley_i, valley, i))
                in_dd = False
            peak = value
            peak_i = i
            valley = value
            valley_i = i
        elif not in_dd:
            in_dd = True
            valley = value
            valley_i = i
        elif value < valley:
            valley = value
            valley_i = i

    if in_dd:  # unrecovered tail drawdown ends at the last session
        episodes.append(
            _episode(idx, peak, peak_i, valley_i, valley, equity.shape[0] - 1)
        )

    episodes.sort(key=lambda d: d.depth)  # most-negative (worst) first
    return episodes


def _episode(idx, peak_val, peak_i, valley_i, valley_val, end_i) -> DrawdownPeriod:
    """Construct one :class:`DrawdownPeriod` from peak / valley / end indices."""
    depth = float(valley_val / peak_val - 1.0)
    return DrawdownPeriod(
        start=pd.Timestamp(idx[peak_i]).date(),
        valley=pd.Timestamp(idx[valley_i]).date(),
        end=pd.Timestamp(idx[end_i]).date(),
        depth=depth,
        length=int(end_i - peak_i),
    )


# --- monthly returns ------------------------------------------------------


def _monthly_returns(returns: pd.Series) -> list[MonthlyReturn]:
    """Per-calendar-month compounded total returns (the returns heatmap)."""
    if returns.shape[0] == 0:
        return []
    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    out: list[MonthlyReturn] = []
    for stamp, val in monthly.items():
        ts = pd.Timestamp(stamp)
        out.append(MonthlyReturn(year=int(ts.year), month=int(ts.month), ret=float(val)))
    return out


# --- helpers --------------------------------------------------------------


def _aligned(returns: pd.Series, benchmark: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Inner-join ``returns`` and ``benchmark`` on their shared index."""
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    return joined.iloc[:, 0], joined.iloc[:, 1]


def _finite(value: float) -> float:
    """Map non-finite (nan/inf) results to ``0.0`` for clean float fields."""
    out = float(value)
    return out if np.isfinite(out) else 0.0
