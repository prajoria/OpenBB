"""Unit tests for the analytics shared foundation (component 07, §1).

Covers ``analytics/_common.py``: :func:`to_returns` (Decimal equity curve ->
normalized float returns, agreeing with the vectorized engine's
``simple_returns``), :func:`assert_normalized` (the fork privacy gate that
rejects Decimal/non-finite/absolute-dollar series), and :func:`optional_import`
(lazy heavy-dependency loader with an actionable, pip-named ImportError).

The whole point of this layer is that it imports with **zero heavy deps**, so
the suite must stay green with empyrical/pyfolio/quantstats/ffn all absent.

See ``docs/designs/backtest-design/07-analytics.md`` §1.
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


def _equity_curve(values: list[float]):
    """Build a list[EquityPoint] (Decimal equity) over consecutive sessions."""
    from openbb_backtest.models import EquityPoint

    sessions = pd.date_range("2021-01-04", periods=len(values), freq="D", tz="UTC")
    return [
        EquityPoint(
            date=ts.to_pydatetime(),
            equity=Decimal(str(v)),
            cash=Decimal("0"),
            exposure=1.0,
        )
        for ts, v in zip(sessions, values)
    ]


# ---- to_returns ----------------------------------------------------------


def test_to_returns_matches_vectorized_simple_returns():
    from openbb_backtest.analytics._common import to_returns
    from openbb_backtest.engine.vectorized import simple_returns

    values = [100000.0, 101000.0, 99990.0, 102000.0]
    out = to_returns(_equity_curve(values))
    expected = simple_returns(np.array(values, dtype=float))
    np.testing.assert_allclose(out.to_numpy(), expected, atol=1e-12)


def test_to_returns_is_normalized_float_series_indexed_by_date():
    from openbb_backtest.analytics._common import to_returns

    out = to_returns(_equity_curve([100.0, 110.0, 99.0]))
    assert isinstance(out, pd.Series)
    assert out.dtype == float
    # First period has no prior bar -> 0.0 (the simple_returns convention).
    assert out.iloc[0] == pytest.approx(0.0)
    assert out.iloc[1] == pytest.approx(0.10)
    assert out.iloc[2] == pytest.approx(-0.10)
    assert isinstance(out.index, pd.DatetimeIndex)


def test_to_returns_carries_no_decimal_or_dollar_amounts():
    from openbb_backtest.analytics._common import assert_normalized, to_returns

    # The output of to_returns must itself pass the privacy gate.
    out = to_returns(_equity_curve([250000.0, 255000.0, 251000.0]))
    assert_normalized(out)  # must not raise


# ---- assert_normalized (privacy gate) ------------------------------------


def test_assert_normalized_passes_plain_float_returns():
    from openbb_backtest.analytics._common import assert_normalized

    assert_normalized(pd.Series([0.01, -0.02, 0.005, 0.5]))  # must not raise


def test_assert_normalized_rejects_decimal_values():
    from openbb_backtest.analytics._common import assert_normalized

    series = pd.Series([Decimal("0.01"), Decimal("-0.02")])
    with pytest.raises((TypeError, ValueError)):
        assert_normalized(series)


def test_assert_normalized_rejects_non_finite():
    from openbb_backtest.analytics._common import assert_normalized

    with pytest.raises(ValueError):
        assert_normalized(pd.Series([0.01, np.nan, 0.02]))
    with pytest.raises(ValueError):
        assert_normalized(pd.Series([0.01, np.inf]))


def test_assert_normalized_rejects_absolute_dollar_amounts():
    from openbb_backtest.analytics._common import assert_normalized

    # Equity levels (dollar amounts) must never be mistaken for returns.
    with pytest.raises(ValueError):
        assert_normalized(pd.Series([100000.0, 101000.0, 99990.0]))


# ---- optional_import -----------------------------------------------------


def test_optional_import_returns_module_when_present():
    from openbb_backtest.analytics._common import optional_import

    mod = optional_import("empyrical")
    assert mod.__name__ == "empyrical"


def test_optional_import_absent_names_pip_package_and_is_actionable():
    from openbb_backtest.analytics._common import optional_import

    with pytest.raises(ImportError) as exc:
        optional_import("pyfolio")
    message = str(exc.value)
    # Actionable: names the pip-installable package (not just the import name).
    assert "pyfolio-reloaded" in message
    assert "pip install" in message


def test_optional_import_unknown_module_falls_back_to_its_name():
    from openbb_backtest.analytics._common import optional_import

    with pytest.raises(ImportError) as exc:
        optional_import("definitely_absent_xyz")
    assert "definitely_absent_xyz" in str(exc.value)


# ---- zero-heavy-deps import guard ----------------------------------------


def test_analytics_common_imports_and_runs_with_heavy_deps_absent():
    """Blocking empyrical/pyfolio/quantstats/ffn/numba must not break import.

    The foundation only lazy-loads heavy libs (via optional_import), so a clean
    subprocess with those modules forced absent can still import the module and
    compute returns / run the privacy gate.
    """
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_BACKTEST_ROOT!r})
        for m in ("empyrical", "pyfolio", "quantstats", "ffn", "numba"):
            sys.modules[m] = None
        from decimal import Decimal
        from datetime import datetime, timezone
        import openbb_backtest.analytics._common as c
        from openbb_backtest.models import EquityPoint
        utc = timezone.utc
        curve = [
            EquityPoint(date=datetime(2021, 1, 4, tzinfo=utc),
                        equity=Decimal("100000"), cash=Decimal("0"), exposure=1.0),
            EquityPoint(date=datetime(2021, 1, 5, tzinfo=utc),
                        equity=Decimal("101000"), cash=Decimal("0"), exposure=1.0),
        ]
        r = c.to_returns(curve)
        c.assert_normalized(r)
        print("OK", round(float(r.iloc[1]), 5))
        """
    )
    # Fixed, self-authored script run via the current interpreter — no untrusted
    # input, which is exactly the S603 precondition.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK 0.01" in result.stdout
