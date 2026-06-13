"""``momentum_12_1`` — cross-sectional 12-1 momentum (component 10.3).

The classic academic momentum factor (Jegadeesh & Titman): rank symbols on their
trailing 12-month return **skipping the most recent month** (the 1-month skip
avoids the well-documented short-term reversal), then go long the winners and
short the losers as a dollar-neutral book.

Implemented as a :class:`~openbb_backtest.strategies.base.CrossSectionalStrategy`
so the demeaned ranks normalize straight to dollar-neutral weights.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from openbb_backtest.interfaces import MarketData
from openbb_backtest.registry import register_strategy
from openbb_backtest.strategies.base import CrossSectionalStrategy

#: 12 months / 1 month expressed in trading days (the canonical 12-1 horizon).
_TRADING_DAYS_PER_YEAR = 252
_TRADING_DAYS_PER_MONTH = 21


@register_strategy("momentum_12_1")
class Momentum(CrossSectionalStrategy):
    """Long-winners / short-losers on the skip-adjusted trailing return."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        lookback: int = _TRADING_DAYS_PER_YEAR,
        skip: int = _TRADING_DAYS_PER_MONTH,
        gross: float = 1.0,
        id: str = "momentum_12_1",  # noqa: A002 - mirrors the Strategy protocol field
    ) -> None:
        super().__init__(id, target_gross=gross)
        self.symbols = list(symbols)
        self.lookback = int(lookback)
        self.skip = int(skip)
        if not self.symbols:
            raise ValueError("momentum requires a non-empty symbol universe")
        if self.lookback < 1 or self.skip < 0:
            raise ValueError("momentum needs lookback >= 1 and skip >= 0")

    def rank(self, data: MarketData) -> pd.Series:
        """Trailing return over ``lookback`` bars ending ``skip`` bars before now."""
        win = data.window(self.symbols, self.lookback + self.skip)
        closes = win.pivot_table(index="session", columns="symbol", values="close")
        scores: dict[str, float] = {}
        for sym in self.symbols:
            if sym not in closes.columns:
                scores[sym] = 0.0
                continue
            series = closes[sym].dropna()
            measured = series.iloc[: len(series) - self.skip] if self.skip else series
            if len(measured) < 2 or measured.iloc[0] == 0:
                scores[sym] = 0.0
            else:
                scores[sym] = float(measured.iloc[-1] / measured.iloc[0] - 1.0)
        return pd.Series(scores)
