"""Cross-sectional factor abstraction (component 05, §2).

A :class:`Factor` declares the columns it consumes (``inputs``) and the trailing
``window_length`` it needs, then computes one value per asset from a long
point-in-time window frame. Insufficient history yields ``NaN`` (never a
look-ahead-biased fill). Concrete factors port the ``Analysis/`` Phase 2-5
computations into reusable nodes; ``rank``/``zscore`` standardize a single
session's cross-section.

Independent of zipline — ``to_zipline()`` is a deferred hook (component 05.6).

See ``docs/designs/backtest-design/05-event-driven-engine.md`` §2.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class Factor(ABC):
    """A cross-sectional factor: trailing-window inputs -> one value per asset.

    Subclasses declare :attr:`inputs` (required columns) and
    :attr:`window_length` (trailing bars needed) and implement
    :meth:`compute`, which receives a long frame (``symbol``/``session`` plus the
    declared inputs) bounded at the current session and returns a per-symbol
    :class:`pandas.Series`.
    """

    inputs: list[str]
    window_length: int

    @property
    def name(self) -> str:
        """Stable factor name used as the panel column label."""
        return type(self).__name__.lower()

    @abstractmethod
    def compute(self, window: pd.DataFrame) -> pd.Series:
        """Return one factor value per symbol from the trailing ``window``."""

    def to_zipline(self):  # pragma: no cover - deferred backend (C05.6)
        """Translate to a ``zipline`` ``CustomFactor`` (deferred, optional)."""
        raise NotImplementedError(
            "zipline translation is a deferred optional backend (component 05.6)"
        )


def _per_symbol(window: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Group a long window frame into per-symbol session-ordered sub-frames."""
    out: dict[str, pd.DataFrame] = {}
    for sym, grp in window.groupby("symbol"):
        out[str(sym)] = grp.sort_values("session")
    return out


class Momentum(Factor):
    """Trailing total return over ``window_length`` bars (technical, Phase 4).

    ``close[-1] / close[-window_length] - 1`` per asset; assets with fewer than
    ``window_length`` bars in the window resolve to ``NaN``.
    """

    inputs = ["close"]

    def __init__(self, window_length: int = 21) -> None:
        if window_length < 2:
            raise ValueError("momentum window_length must be >= 2")
        self.window_length = window_length

    @property
    def name(self) -> str:
        """Window-tagged name, e.g. ``momentum_21``."""
        return f"momentum_{self.window_length}"

    def compute(self, window: pd.DataFrame) -> pd.Series:
        """Window total return per asset (NaN on insufficient history)."""
        values: dict[str, float] = {}
        for sym, grp in _per_symbol(window).items():
            closes = grp["close"].to_numpy(dtype=float)
            if closes.shape[0] < self.window_length or closes[-self.window_length] == 0:
                values[sym] = float("nan")
            else:
                values[sym] = float(closes[-1] / closes[-self.window_length] - 1.0)
        return pd.Series(values, name=self.name)


class EarningsYield(Factor):
    """Earnings yield ``eps / close`` (valuation, Phase 3); higher = cheaper."""

    inputs = ["close", "eps"]
    window_length = 1

    @property
    def name(self) -> str:
        """Stable factor name ``earnings_yield``."""
        return "earnings_yield"

    def compute(self, window: pd.DataFrame) -> pd.Series:
        """Latest-bar earnings yield per asset (NaN when price is missing/zero)."""
        values: dict[str, float] = {}
        for sym, grp in _per_symbol(window).items():
            last = grp.iloc[-1]
            close = float(last["close"])
            eps = float(last["eps"])
            values[sym] = float(eps / close) if close else float("nan")
        return pd.Series(values, name=self.name)


def zscore(values: pd.Series) -> pd.Series:
    """Cross-sectional z-score (mean 0, unit sample std).

    A constant cross-section has zero dispersion and resolves to all-zeros
    rather than dividing by zero into NaN/inf.
    """
    arr = values.to_numpy(dtype=float)
    finite = arr[~np.isnan(arr)]
    if finite.size < 2:
        return pd.Series(np.zeros_like(arr), index=values.index, name=values.name)
    std = float(finite.std(ddof=1))
    if std == 0.0:
        return pd.Series(np.zeros_like(arr), index=values.index, name=values.name)
    mean = float(finite.mean())
    return (values - mean) / std


def rank(values: pd.Series) -> pd.Series:
    """Ascending cross-sectional percentile rank in ``(0, 1]``.

    The smallest value maps to ``1/n`` and the largest to ``1.0``, so a higher
    rank always means a larger factor value.
    """
    return values.rank(method="average", pct=True)
