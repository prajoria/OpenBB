"""Interface protocols shared by engines, strategies, brokers and feeds.

Imports only from :mod:`openbb_backtest.models` to remain near-leaf and
cycle-free. See ``docs/designs/backtest-design/02-data-models.md``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

import pandas as pd

from openbb_backtest.models import BacktestConfig, BacktestResult, Bar, Trade


@runtime_checkable
class MarketData(Protocol):
    """A point-in-time view of market data exposed to a strategy.

    Implementations MUST only expose data up to the current bar so a strategy
    cannot peek at the future.
    """

    def window(self, symbols: list[str], lookback: int) -> pd.DataFrame:
        """Return the trailing ``lookback`` bars for ``symbols`` up to now."""
        ...

    @property
    def now(self) -> pd.Timestamp:
        """Current session timestamp."""
        ...


@runtime_checkable
class Strategy(Protocol):
    """Runs identically in both engines.

    MUST only use data up to the current bar. ``generate`` returns a DataFrame
    (not engine-specific objects) so the same strategy feeds both the vectorized
    matrix path and the event-driven loop.
    """

    id: str

    def generate(self, data: MarketData) -> pd.DataFrame:
        """Return per-symbol target weights or signals indexed by symbol.

        Columns: ``['weight']`` (target weights) OR ``['signal']`` in {-1, 0, 1}.
        """
        ...


@runtime_checkable
class DataFeed(Protocol):
    """Point-in-time market data access; never returns future bars."""

    def history(
        self, symbols: list[str], end: pd.Timestamp, lookback: int
    ) -> pd.DataFrame:
        """Return ``lookback`` bars per symbol ending at ``end`` (inclusive)."""
        ...

    def sessions(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        """Return trading sessions in ``[start, end]``."""
        ...


@runtime_checkable
class Broker(Protocol):
    """Applies execution realism: turns target orders into filled trades.

    The single seam where execution realism (component 06) is injected; both
    engines call it identically, which is what makes the reconciliation gate
    meaningful.
    """

    def fill(self, orders: pd.DataFrame, bar: Bar) -> list[Trade]:
        """Convert desired orders into filled trades at ``bar``."""
        ...

    def commission(self, qty: Decimal, price: Decimal) -> Decimal:
        """Commission for trading ``qty`` at ``price``."""
        ...

    def slippage(self, qty: Decimal, price: Decimal, bar: Bar) -> Decimal:
        """Adverse price adjustment for trading ``qty`` at ``price`` on ``bar``."""
        ...


@runtime_checkable
class Engine(Protocol):
    """Both vectorized and event-driven engines implement this."""

    name: str

    def run(
        self,
        strategy: Strategy,
        config: BacktestConfig,
        feed: DataFeed,
        broker: Broker,
    ) -> BacktestResult:
        """Execute the backtest and return the canonical result."""
        ...
