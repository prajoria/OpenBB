"""``mean_reversion`` — z-score fade reference strategy (component 10.3).

A contrarian :class:`~openbb_backtest.strategies.base.SignalStrategy`: for each
symbol it computes the z-score of the latest close against its trailing window
mean and standard deviation, then **fades** extremes — a close far *below* the
mean (z below ``-entry_z``) is a long (+1); far *above* (z above ``+entry_z``)
is a short (-1); anything inside the band is flat (0). The base template maps
those ``{-1, 0, 1}`` signals to equal-gross weights.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from openbb_backtest.interfaces import MarketData
from openbb_backtest.registry import register_strategy
from openbb_backtest.strategies.base import SignalStrategy


@register_strategy("mean_reversion")
class MeanReversion(SignalStrategy):
    """Long depressed names, short elevated ones, by trailing z-score."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        lookback: int = 21,
        entry_z: float = 1.0,
        gross: float = 1.0,
        id: str = "mean_reversion",  # noqa: A002 - mirrors the Strategy protocol field
    ) -> None:
        super().__init__(id, target_gross=gross)
        self.symbols = list(symbols)
        self.lookback = int(lookback)
        self.entry_z = float(entry_z)
        if not self.symbols:
            raise ValueError("mean_reversion requires a non-empty symbol universe")
        if self.lookback < 2:
            raise ValueError("mean_reversion needs lookback >= 2")

    def signal(self, data: MarketData) -> pd.Series:
        """Fade the trailing z-score: -1 above the band, +1 below, else 0."""
        win = data.window(self.symbols, self.lookback)
        closes = win.pivot_table(index="session", columns="symbol", values="close")
        signals: dict[str, float] = {}
        for sym in self.symbols:
            if sym not in closes.columns:
                signals[sym] = 0.0
                continue
            series = closes[sym].dropna()
            std = float(series.std())
            if len(series) < 2 or std == 0.0:
                signals[sym] = 0.0
                continue
            z = (float(series.iloc[-1]) - float(series.mean())) / std
            if z <= -self.entry_z:
                signals[sym] = 1.0   # depressed -> long (revert up)
            elif z >= self.entry_z:
                signals[sym] = -1.0  # elevated -> short (revert down)
            else:
                signals[sym] = 0.0
        return pd.Series(signals)
