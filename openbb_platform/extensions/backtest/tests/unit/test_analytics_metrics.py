"""Unit tests for ``analytics/metrics.py`` (component 07, §1).

Covers :func:`compute_metrics`, which turns a normalized return series (+ optional
benchmark + executed trades) into a :class:`PerformanceMetrics`. The contract:

- the return-based fields reproduce the vectorized engine's
  :func:`~openbb_backtest.engine.vectorized._metrics_from_returns` **oracle** to
  machine precision *when empyrical is absent* (the pure-Python fallback), so the
  analytics layer and the engine agree by construction;
- annualization uses the passed ``sessions_per_year`` (never a hardcoded 252);
- ``beta``/``alpha`` are ``None`` without a benchmark and finite when aligned;
- ``win_rate``/``profit_factor`` come from FIFO trade round-trip pairing with
  Decimal intermediates;
- ``turnover`` is an annualized estimate derived from trade notional;
- heavy deps are lazy: importing the module never imports empyrical.

The empyrical-*present* parity assertions live in
``tests/integration/test_analytics_metrics_integration.py`` (importorskip), so this
unit suite stays green with empyrical absent by exercising the fallback only.

See ``docs/designs/backtest-design/07-analytics.md`` §1.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

_BACKTEST_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_UTC = timezone.utc


# ---- fixtures / helpers --------------------------------------------------


def _returns(values: list[float]) -> pd.Series:
    """A normalized float return series over consecutive UTC sessions."""
    idx = pd.date_range("2021-01-04", periods=len(values), freq="D", tz="UTC")
    return pd.Series(np.asarray(values, dtype=float), index=idx, name="returns")


def _oracle(returns: pd.Series):
    """The vectorized engine's metrics for ``returns`` (the parity oracle)."""
    from openbb_backtest.engine.vectorized import (
        _metrics_from_returns,
        equity_curve_values,
    )

    port = returns.to_numpy(dtype=float)
    equity = equity_curve_values(1.0, port)
    return _metrics_from_returns(equity, port, np.zeros_like(port))


def _force_fallback(monkeypatch) -> None:
    """Make :func:`compute_metrics` take its pure-Python (no-empyrical) path."""
    import openbb_backtest.analytics.metrics as m

    monkeypatch.setattr(m, "_empyrical", lambda: None)


def _trade(ts_day: int, side: str, qty: str, price: str, commission: str = "0"):
    from openbb_backtest.models import Trade

    return Trade(
        timestamp=datetime(2021, 1, ts_day, tzinfo=_UTC),
        symbol="AAA",
        side=side,  # type: ignore[arg-type]
        quantity=Decimal(qty),
        price=Decimal(price),
        commission=Decimal(commission),
    )


# A deterministic, look-ahead-free return series (first session is 0.0, the
# engine convention) with both up and down sessions so every stat is exercised.
_R = [0.0, 0.012, -0.008, 0.021, -0.015, 0.006, 0.018, -0.004, 0.009, -0.011]


# ---- oracle parity (fallback path) ---------------------------------------


def test_compute_metrics_fallback_matches_oracle_to_machine_precision(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    returns = _returns(_R)
    got = compute_metrics(returns, benchmark=None, trades=[], sessions_per_year=252)
    want = _oracle(returns)

    for field in (
        "cagr",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "volatility",
        "var_95",
        "cvar_95",
    ):
        assert getattr(got, field) == pytest.approx(
            getattr(want, field), abs=1e-12
        ), field


def test_compute_metrics_returns_performance_metrics(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics
    from openbb_backtest.models import PerformanceMetrics

    _force_fallback(monkeypatch)
    out = compute_metrics(_returns(_R), benchmark=None, trades=[], sessions_per_year=252)
    assert isinstance(out, PerformanceMetrics)


# ---- annualization uses sessions_per_year (NOT a hardcoded 252) ----------


def test_annualization_uses_sessions_per_year_not_252(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    returns = _returns(_R)
    daily = compute_metrics(returns, None, [], sessions_per_year=252)
    weekly = compute_metrics(returns, None, [], sessions_per_year=52)

    # Sharpe / volatility annualize by sqrt(sessions_per_year); the ratio between
    # two annualizations of the SAME returns is exactly sqrt(52/252).
    ratio = np.sqrt(52.0 / 252.0)
    assert weekly.sharpe == pytest.approx(daily.sharpe * ratio, rel=1e-9)
    assert weekly.volatility == pytest.approx(daily.volatility * ratio, rel=1e-9)
    # And it genuinely differs from the 252 answer (guards against hardcoding).
    assert weekly.volatility != pytest.approx(daily.volatility, rel=1e-3)


# ---- beta / alpha --------------------------------------------------------


def test_beta_alpha_none_without_benchmark(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    out = compute_metrics(_returns(_R), benchmark=None, trades=[], sessions_per_year=252)
    assert out.beta is None
    assert out.alpha is None


def test_beta_alpha_finite_when_benchmark_aligned(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    returns = _returns(_R)
    # A benchmark correlated with the strategy but not identical.
    bench = _returns([0.0, 0.010, -0.006, 0.015, -0.010, 0.004, 0.012, -0.002, 0.007, -0.008])
    out = compute_metrics(returns, benchmark=bench, trades=[], sessions_per_year=252)
    assert out.beta is not None and np.isfinite(out.beta)
    assert out.alpha is not None and np.isfinite(out.alpha)


def test_beta_one_alpha_zero_when_benchmark_equals_returns(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    returns = _returns(_R)
    out = compute_metrics(returns, benchmark=returns.copy(), trades=[], sessions_per_year=252)
    # Strategy == benchmark => beta 1, alpha 0.
    assert out.beta == pytest.approx(1.0, abs=1e-9)
    assert out.alpha == pytest.approx(0.0, abs=1e-9)


# ---- win_rate / profit_factor from trade round-trips ---------------------


def test_win_rate_and_profit_factor_from_round_trips(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    # Two long round-trips on AAA: one winner (+1000), one loser (-500).
    trades = [
        _trade(4, "buy", "10", "100"),  # open 10 @ 100
        _trade(5, "sell", "10", "200"),  # close 10 @ 200 -> +1000
        _trade(6, "buy", "10", "100"),  # open 10 @ 100
        _trade(7, "sell", "10", "50"),  # close 10 @ 50  -> -500
    ]
    out = compute_metrics(_returns(_R), None, trades, sessions_per_year=252)
    assert out.win_rate == pytest.approx(0.5)
    assert out.profit_factor == pytest.approx(1000.0 / 500.0)


def test_round_trip_pairing_includes_commission_in_pnl(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    # Gross +100, but $150 total commission turns it into a losing round-trip.
    trades = [
        _trade(4, "buy", "10", "100", commission="75"),
        _trade(5, "sell", "10", "110", commission="75"),
    ]
    out = compute_metrics(_returns(_R), None, trades, sessions_per_year=252)
    # Net pnl = (110-100)*10 - 75 - 75 = -50 -> a loss -> win_rate 0.
    assert out.win_rate == pytest.approx(0.0)
    assert out.profit_factor == pytest.approx(0.0)


def test_round_trip_pairing_handles_short_then_cover(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    # Short 10 @ 100, cover @ 80 -> +200 (a winning short round-trip).
    trades = [
        _trade(4, "sell", "10", "100"),
        _trade(5, "buy", "10", "80"),
    ]
    out = compute_metrics(_returns(_R), None, trades, sessions_per_year=252)
    assert out.win_rate == pytest.approx(1.0)
    assert out.profit_factor == pytest.approx(0.0)  # no losing trades => 0.0


def test_win_rate_profit_factor_zero_without_trades(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    out = compute_metrics(_returns(_R), None, [], sessions_per_year=252)
    assert out.win_rate == pytest.approx(0.0)
    assert out.profit_factor == pytest.approx(0.0)


# ---- turnover from trade notional ----------------------------------------


def test_turnover_from_trade_notional_annualized(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    # 252-session window (==1 year at 252/yr). Base capital = first-session gross
    # notional = 100 * 1000 = 100_000. Subsequent sessions add 50_000 + 50_000.
    # turnover = 252 * (100_000 + 50_000 + 50_000)/100_000 / 252 = 2.0
    returns = _returns([0.0] * 252)
    trades = [
        _trade(4, "buy", "100", "1000"),  # base session, notional 100_000
        _trade(5, "sell", "50", "1000"),  # notional 50_000
        _trade(6, "buy", "50", "1000"),  # notional 50_000
    ]
    out = compute_metrics(returns, None, trades, sessions_per_year=252)
    assert out.turnover == pytest.approx(2.0, rel=1e-9)


def test_turnover_zero_without_trades(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    out = compute_metrics(_returns([0.0] * 252), None, [], sessions_per_year=252)
    assert out.turnover == pytest.approx(0.0)


# ---- privacy gate --------------------------------------------------------


def test_compute_metrics_rejects_non_normalized_returns(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    # Absolute dollar levels must never be mistaken for a return series.
    dollars = pd.Series([100000.0, 101000.0, 99990.0])
    with pytest.raises(ValueError):
        compute_metrics(dollars, None, [], sessions_per_year=252)


def test_compute_metrics_rejects_decimal_returns(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics

    _force_fallback(monkeypatch)
    decimals = pd.Series([Decimal("0.01"), Decimal("-0.02")])
    with pytest.raises((TypeError, ValueError)):
        compute_metrics(decimals, None, [], sessions_per_year=252)


# ---- empty input edge ----------------------------------------------------


def test_compute_metrics_empty_returns_is_well_defined(monkeypatch):
    from openbb_backtest.analytics.metrics import compute_metrics
    from openbb_backtest.models import PerformanceMetrics

    _force_fallback(monkeypatch)
    out = compute_metrics(_returns([]), None, [], sessions_per_year=252)
    assert isinstance(out, PerformanceMetrics)
    assert out.sharpe == pytest.approx(0.0)
    assert out.beta is None


# ---- lazy import guard ---------------------------------------------------


def test_metrics_imports_and_runs_with_heavy_deps_absent():
    """Importing/using metrics must not require empyrical/pyfolio/quantstats/ffn."""
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_BACKTEST_ROOT!r})
        for m in ("empyrical", "pyfolio", "quantstats", "ffn", "numba"):
            sys.modules[m] = None
        import numpy as np, pandas as pd
        from openbb_backtest.analytics.metrics import compute_metrics
        idx = pd.date_range("2021-01-04", periods=5, freq="D", tz="UTC")
        r = pd.Series([0.0, 0.01, -0.02, 0.03, -0.01], index=idx, name="returns")
        m = compute_metrics(r, None, [], 252)
        assert m.beta is None
        print("OK", round(float(m.volatility), 6))
        """
    )
    # Fixed, self-authored script via the current interpreter — no untrusted
    # input, which is exactly the S603 precondition.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK ")
