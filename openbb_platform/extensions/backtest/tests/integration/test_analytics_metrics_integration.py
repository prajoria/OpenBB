"""Integration tests for ``analytics/metrics.py`` against real ``empyrical``.

These exercise the **empyrical-present** path of :func:`compute_metrics` and are
skipped entirely when ``empyrical-reloaded`` is not installed (``importorskip``),
so the default unit run (heavy deps absent) stays green. They assert that the
empyrical-backed fields equal calling empyrical directly with the same
``annualization=sessions_per_year`` — i.e. ``compute_metrics`` is a faithful,
correctly-annualized wrapper, not a reimplementation.

Marked ``integration`` so ``-m "not integration"`` excludes them.

See ``docs/designs/backtest-design/07-analytics.md`` §1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

empyrical = pytest.importorskip("empyrical")

pytestmark = pytest.mark.integration


def _returns(values: list[float]) -> pd.Series:
    idx = pd.date_range("2021-01-04", periods=len(values), freq="D", tz="UTC")
    return pd.Series(np.asarray(values, dtype=float), index=idx, name="returns")


_R = [0.0, 0.012, -0.008, 0.021, -0.015, 0.006, 0.018, -0.004, 0.009, -0.011]


def test_empyrical_backed_fields_match_empyrical_directly():
    from openbb_backtest.analytics.metrics import compute_metrics

    spy = 252
    returns = _returns(_R)
    out = compute_metrics(returns, benchmark=None, trades=[], sessions_per_year=spy)

    assert out.cagr == pytest.approx(
        float(empyrical.annual_return(returns, annualization=spy)), rel=1e-9
    )
    assert out.sharpe == pytest.approx(
        float(empyrical.sharpe_ratio(returns, annualization=spy)), rel=1e-9
    )
    assert out.sortino == pytest.approx(
        float(empyrical.sortino_ratio(returns, annualization=spy)), rel=1e-9
    )
    assert out.calmar == pytest.approx(
        float(empyrical.calmar_ratio(returns, annualization=spy)), rel=1e-9
    )
    assert out.max_drawdown == pytest.approx(
        float(empyrical.max_drawdown(returns)), rel=1e-9
    )
    assert out.volatility == pytest.approx(
        float(empyrical.annual_volatility(returns, annualization=spy)), rel=1e-9
    )
    assert out.var_95 == pytest.approx(
        float(empyrical.value_at_risk(returns, cutoff=0.05)), rel=1e-9
    )
    assert out.cvar_95 == pytest.approx(
        float(empyrical.conditional_value_at_risk(returns, cutoff=0.05)), rel=1e-9
    )


def test_empyrical_annualization_respects_sessions_per_year():
    from openbb_backtest.analytics.metrics import compute_metrics

    returns = _returns(_R)
    out52 = compute_metrics(returns, None, [], sessions_per_year=52)
    assert out52.sharpe == pytest.approx(
        float(empyrical.sharpe_ratio(returns, annualization=52)), rel=1e-9
    )
    assert out52.volatility == pytest.approx(
        float(empyrical.annual_volatility(returns, annualization=52)), rel=1e-9
    )


def test_empyrical_beta_alpha_match_when_benchmark_aligned():
    from openbb_backtest.analytics.metrics import compute_metrics

    spy = 252
    returns = _returns(_R)
    bench = _returns([0.0, 0.010, -0.006, 0.015, -0.010, 0.004, 0.012, -0.002, 0.007, -0.008])
    out = compute_metrics(returns, benchmark=bench, trades=[], sessions_per_year=spy)

    assert out.beta == pytest.approx(float(empyrical.beta(returns, bench)), rel=1e-9)
    assert out.alpha == pytest.approx(
        float(empyrical.alpha(returns, bench, annualization=spy)), rel=1e-9
    )
