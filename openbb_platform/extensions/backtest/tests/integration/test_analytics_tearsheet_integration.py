"""Integration tests for ``analytics/tearsheet.py`` against real ``pyfolio``.

pyfolio-reloaded pins ``pandas<3.0`` and is intentionally **not installed** in this
environment (installing it would downgrade pandas and break the fork), so these are
skipped via ``importorskip``. They exist to assert that the pyfolio-backed path of
:func:`build_tearsheet` agrees with pyfolio's own drawdown table when the library is
available; the in-house pandas path is the canonical, unit-tested source of truth.

Marked ``integration`` so ``-m "not integration"`` excludes them.

See ``docs/designs/backtest-design/07-analytics.md`` §2 and memory
``backtest-impl-env-constraints``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pyfolio = pytest.importorskip("pyfolio")

pytestmark = pytest.mark.integration


def _returns(seed: int = 5, periods: int = 300) -> pd.Series:
    idx = pd.date_range("2021-01-04", periods=periods, freq="B", tz="UTC")
    rng = np.random.default_rng(seed)
    vals = rng.normal(0.0006, 0.011, periods)
    vals[0] = 0.0
    return pd.Series(vals, index=idx, name="returns")


def test_worst_drawdown_matches_pyfolio():
    from openbb_backtest.analytics.tearsheet import build_tearsheet

    returns = _returns()
    ts = build_tearsheet(returns, None, [], sessions_per_year=252)

    table = pyfolio.timeseries.gen_drawdown_table(returns, top=1)
    # pyfolio reports net drawdown as a positive percent; ours is a negative frac.
    pf_worst = -float(table["Net drawdown in %"].iloc[0]) / 100.0
    assert ts.drawdown_periods[0].depth == pytest.approx(pf_worst, abs=1e-6)


def test_tearsheet_populates_via_pyfolio_path():
    from openbb_backtest.analytics.tearsheet import build_tearsheet
    from openbb_backtest.models import TearSheet

    returns = _returns(seed=7)
    ts = build_tearsheet(returns, None, [], sessions_per_year=252)
    assert isinstance(ts, TearSheet)
    assert len(ts.rolling_sharpe) > 0
    assert len(ts.monthly_returns) > 0
