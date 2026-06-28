"""``buy_and_hold`` — a static equal-weight reference strategy (component 10.3).

The simplest possible :class:`~openbb_backtest.strategies.base.WeightStrategy`:
spreads a fixed gross exposure equally across the configured universe and never
looks at the data, so its weights are identical on every session. Useful as the
trivial baseline every other strategy is measured against.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from openbb_backtest.interfaces import MarketData
from openbb_backtest.registry import register_strategy
from openbb_backtest.strategies.base import WeightStrategy


@register_strategy("buy_and_hold")
class BuyAndHold(WeightStrategy):
    """Static equal-weight allocation summing to ``gross`` across ``symbols``."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        gross: float = 1.0,
        id: str = "buy_and_hold",  # noqa: A002 - mirrors the Strategy protocol field
    ) -> None:
        super().__init__(id)
        self.symbols = list(symbols)
        self.gross = float(gross)
        if not self.symbols:
            raise ValueError("buy_and_hold requires a non-empty symbol universe")

    def target_weights(self, data: MarketData) -> pd.Series:
        """Equal weights across the universe summing to ``gross`` (data-independent)."""
        weight = self.gross / len(self.symbols)
        return pd.Series({sym: weight for sym in self.symbols})
