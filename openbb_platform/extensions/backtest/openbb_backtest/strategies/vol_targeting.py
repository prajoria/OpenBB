"""``vol_targeting`` — volatility-targeted allocation (component 10.4).

A :class:`~openbb_backtest.strategies.base.WeightStrategy` that equal-weights the
universe then scales the book's **gross exposure** so its realized annualized
volatility (estimated from a trailing return window) matches a target. When
trailing volatility is high the scale shrinks (de-risking); when it is low the
scale grows, capped by ``max_leverage``.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from openbb_backtest.interfaces import MarketData
from openbb_backtest.registry import register_strategy
from openbb_backtest.strategies.base import WeightStrategy

#: Trading days per year used to annualize the trailing volatility estimate.
_TRADING_DAYS_PER_YEAR = 252.0


@register_strategy("vol_targeting")
class VolTargeting(WeightStrategy):
    """Equal-weight book scaled so realized annualized vol hits ``target_vol``."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        target_vol: float = 0.10,
        lookback: int = 60,
        max_leverage: float = 1.0,
        id: str = "vol_targeting",  # noqa: A002 - mirrors the Strategy protocol field
    ) -> None:
        super().__init__(id)
        self.symbols = list(symbols)
        self.target_vol = float(target_vol)
        self.lookback = int(lookback)
        self.max_leverage = float(max_leverage)
        if not self.symbols:
            raise ValueError("vol_targeting requires a non-empty symbol universe")
        if self.target_vol <= 0 or self.lookback < 2 or self.max_leverage <= 0:
            raise ValueError("vol_targeting needs target_vol>0, lookback>=2, max_leverage>0")

    def target_weights(self, data: MarketData) -> pd.Series:
        """Equal weights scaled so the equal-weight book's annualized vol == target."""
        base = pd.Series(1.0 / len(self.symbols), index=self.symbols)
        realized = self._realized_vol(data)
        if realized <= 0.0:
            return base * self.max_leverage
        scale = min(self.target_vol / realized, self.max_leverage)
        return base * scale

    def _realized_vol(self, data: MarketData) -> float:
        """Annualized volatility of the equal-weight book over the trailing window."""
        win = data.window(self.symbols, self.lookback + 1)
        closes = win.pivot_table(index="session", columns="symbol", values="close")
        present = [s for s in self.symbols if s in closes.columns]
        if len(present) == 0:
            return 0.0
        rets = closes[present].pct_change().dropna(how="all")
        if len(rets) < 2:
            return 0.0
        book = rets.mean(axis=1)  # equal-weight portfolio daily returns
        daily = float(book.std())
        return daily * np.sqrt(_TRADING_DAYS_PER_YEAR)
