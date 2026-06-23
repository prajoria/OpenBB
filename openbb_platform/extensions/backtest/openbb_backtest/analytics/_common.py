"""Shared analytics foundation (component 07, §1).

Every downstream analytics module (metrics, tear sheets, exports) consumes these
three primitives, so they live in one dependency-light place:

- :func:`to_returns` — turn a :class:`~openbb_backtest.models.EquityPoint` curve
  (Decimal equity) into a normalized float return :class:`pandas.Series`,
  computed via the vectorized engine's ``simple_returns`` so the two agree to
  machine precision.
- :func:`assert_normalized` — the fork **privacy gate**: anything emitted outward
  must be normalized returns, never Decimal, non-finite, or absolute dollar
  amounts / account detail.
- :func:`optional_import` — lazy-load a heavy, optional dependency and raise an
  *actionable* :class:`ImportError` (naming the pip package) when it is absent,
  so importing this module never requires empyrical/pyfolio/quantstats/ffn.

See ``docs/designs/backtest-design/07-analytics.md`` §1.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from decimal import Decimal
from types import ModuleType
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from openbb_backtest.models import EquityPoint

# Import name -> pip-installable package, for actionable ImportErrors. Several
# "-reloaded" forks import under a legacy name, which is the actionable gap.
_PIP_NAMES = {
    "empyrical": "empyrical-reloaded",
    "pyfolio": "pyfolio-reloaded",
    "quantstats": "quantstats",
    "ffn": "ffn",
}

# Beyond this magnitude a "return" is almost certainly an absolute amount
# (dollar equity level), so the privacy gate treats it as non-normalized. A
# +10,000%/period return is implausible, while portfolio dollar levels dwarf it.
_MAX_RETURN_ABS = 100.0


def to_returns(equity_curve: Sequence[EquityPoint]) -> pd.Series:
    """Convert an equity curve into a normalized float return series.

    The Decimal ``equity`` levels are cast to float and differenced via the
    vectorized engine's :func:`~openbb_backtest.engine.vectorized.simple_returns`
    (so the analytics layer and the engine agree by construction). The first
    period has no prior bar and is ``0.0``. The result is indexed by the curve's
    session dates and carries no dollar amounts.
    """
    if not equity_curve:
        return pd.Series([], dtype=float, index=pd.DatetimeIndex([]), name="returns")

    # Local import keeps ``import ..._common`` light and engine-agnostic.
    from openbb_backtest.engine.vectorized import simple_returns

    dates = pd.DatetimeIndex([pd.Timestamp(p.date) for p in equity_curve])
    closes = np.array([float(p.equity) for p in equity_curve], dtype=float)
    return pd.Series(simple_returns(closes), index=dates, name="returns")


def assert_normalized(series: pd.Series, *, max_abs: float = _MAX_RETURN_ABS) -> None:
    """Raise unless ``series`` is a normalized float return series (privacy gate).

    Enforces the fork privacy rule that outward-facing analytics expose only
    normalized returns:

    - non-``Series`` or object/Decimal dtype -> :class:`TypeError`,
    - any non-finite value (NaN/inf) -> :class:`ValueError`,
    - any ``|value| > max_abs`` (i.e. an absolute dollar amount, not a return)
      -> :class:`ValueError`.
    """
    if not isinstance(series, pd.Series):
        raise TypeError(f"expected a pandas Series of returns, got {type(series).__name__}")
    if series.dtype == object or any(isinstance(v, Decimal) for v in series.to_numpy()):
        raise TypeError(
            "normalized returns must be a float Series — got Decimal/object dtype "
            "(dollar amounts and lot detail must never be emitted)"
        )
    arr = series.to_numpy(dtype=float)
    if arr.size and not np.all(np.isfinite(arr)):
        raise ValueError("normalized returns must be finite (no NaN/inf)")
    if arr.size and float(np.max(np.abs(arr))) > max_abs:
        raise ValueError(
            "series looks like absolute amounts (|value| > "
            f"{max_abs}), not normalized returns — refusing to emit dollar detail"
        )


def optional_import(name: str) -> ModuleType:
    """Import optional heavy dependency ``name`` or raise an actionable error.

    Returns the imported module when present. When absent (or stubbed out), the
    raised :class:`ImportError` names the pip-installable package so the caller
    knows exactly how to enable the feature, e.g. ``pip install pyfolio-reloaded``.
    """
    try:
        return importlib.import_module(name)
    except Exception as exc:  # ModuleNotFoundError, or stubbed None in sys.modules
        package = _PIP_NAMES.get(name, name)
        raise ImportError(
            f"optional dependency '{name}' is required for this feature but is "
            f"not installed. Install it with: pip install {package}"
        ) from exc
