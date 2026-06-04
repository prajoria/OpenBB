"""Execution realism: commission, slippage, fills, borrow costs, constraints.

Implements the ``Broker`` protocol (component 02). Both engines call the same
broker so the reconciliation gate is meaningful and same-bar look-ahead is
prevented. All money math uses ``Decimal``; slippage always *worsens* the fill.

See ``docs/designs/backtest-design/06-execution-realism.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

import pandas as pd

from openbb_backtest.models import Bar, CommissionModel, SlippageModel, Trade

_BPS = Decimal("10000")


def _sign(qty: Decimal) -> int:
    if qty > 0:
        return 1
    if qty < 0:
        return -1
    return 0


class Commission:
    """Commission calculator implementing ``Broker.commission``."""

    def __init__(self, model: CommissionModel) -> None:
        self.model = model

    @staticmethod
    def of(model: CommissionModel) -> Commission:
        """Build a :class:`Commission` from a :class:`CommissionModel`."""
        return Commission(model)

    def cost(self, qty: Decimal, price: Decimal) -> Decimal:
        """Commission for trading ``qty`` shares at ``price`` (never negative)."""
        qty = abs(Decimal(qty))
        price = Decimal(price)
        value = self.model.value
        kind = self.model.kind
        if kind == "flat":
            cost = value
        elif kind == "percent":
            cost = qty * price * value
        else:
            # per_share and tiered (tiered falls back to per-share without a
            # volume schedule on the model).
            cost = qty * value
        return max(cost, self.model.min_per_trade)


class Slippage:
    """Slippage calculator implementing ``Broker.slippage``.

    Returns a *signed* per-share price adjustment: positive for buys (fill
    higher) and negative for sells (fill lower) so the fill is always adverse.
    """

    def __init__(self, model: SlippageModel) -> None:
        self.model = model

    @staticmethod
    def of(model: SlippageModel) -> Slippage:
        """Build a :class:`Slippage` from a :class:`SlippageModel`."""
        return Slippage(model)

    def cost(self, qty: Decimal, price: Decimal, bar: Bar) -> Decimal:
        """Adverse per-share price adjustment for ``qty`` at ``price`` on ``bar``."""
        s = _sign(Decimal(qty))
        if s == 0:
            return Decimal("0")
        price = Decimal(price)
        value = self.model.value
        kind = self.model.kind
        if kind == "fixed_bps":
            magnitude = price * value / _BPS
        elif kind == "volume_share":
            volume = Decimal(bar.volume or 0)
            magnitude = (
                Decimal("0")
                if volume <= 0
                else price * value * (abs(Decimal(qty)) / volume)
            )
        elif kind == "spread":
            magnitude = price * (Decimal(str(bar.spread_bps)) / _BPS) / Decimal("2")
        else:  # pragma: no cover - guarded by model Literal
            magnitude = Decimal("0")
        return magnitude * s


@dataclass
class FillModel:
    """Determines the fill price for an order on the fill bar."""

    kind: Literal["next_bar_open", "vwap", "limit"] = "next_bar_open"
    limit_timeout_bars: int = 1

    def reference_price(self, bar: Bar) -> Decimal:
        """Base (pre-slippage) fill price for ``bar`` by fill kind."""
        if self.kind == "vwap":
            return (bar.high + bar.low + Decimal("2") * bar.close) / Decimal("4")
        # next_bar_open (default) and limit both reference the open.
        return bar.open

    def limit_marketable(self, qty: Decimal, limit_price: Decimal, bar: Bar) -> bool:
        """Whether a limit order trades through within the bar's range."""
        if qty > 0:  # buy fills if price drops to or below limit
            return bar.low <= limit_price
        if qty < 0:  # sell fills if price rises to or above limit
            return bar.high >= limit_price
        return False


@dataclass
class ShortModel:
    """Short-selling rules and borrow costs."""

    borrow_fee_bps_annual: Decimal = Decimal("0")
    require_locate: bool = False
    hard_to_borrow: set[str] = field(default_factory=set)

    def borrow_cost(self, market_value: Decimal, days: int = 1) -> Decimal:
        """Daily borrow cost accrued on short ``market_value`` over ``days``."""
        mv = abs(Decimal(market_value))
        return mv * (self.borrow_fee_bps_annual / _BPS) * Decimal(days) / Decimal("252")

    def can_short(self, symbol: str) -> bool:
        """Whether ``symbol`` may be shorted."""
        return symbol not in self.hard_to_borrow


@dataclass
class Constraints:
    """Pre-fill portfolio / regulatory constraints."""

    espp_lockup: dict[str, date] = field(default_factory=dict)
    tax_lot_method: Literal["fifo", "lifo", "specific_id"] = "fifo"
    restricted: set[str] = field(default_factory=set)
    max_position_pct: float = 1.0

    def reject_reason(
        self, symbol: str, qty: Decimal, as_of: date | None = None
    ) -> str | None:
        """Return a rejection reason for an order, or ``None`` if allowed."""
        if symbol in self.restricted:
            return "restricted"
        lock = self.espp_lockup.get(symbol)
        if lock is not None and qty < 0 and as_of is not None and as_of < lock:
            return "espp_lockup"
        return None


class RealisticBroker:
    """Concrete ``Broker`` composing commission, slippage, fills, constraints."""

    def __init__(
        self,
        commission: CommissionModel,
        slippage: SlippageModel,
        fill: FillModel | None = None,
        short: ShortModel | None = None,
        constraints: Constraints | None = None,
    ) -> None:
        self._commission = Commission.of(commission)
        self._slippage = Slippage.of(slippage)
        self._fill = fill or FillModel()
        self._short = short or ShortModel()
        self._constraints = constraints or Constraints()
        self.rejected_orders: int = 0

    def commission(self, qty: Decimal, price: Decimal) -> Decimal:
        """Commission for ``qty`` at ``price``."""
        return self._commission.cost(qty, price)

    def slippage(self, qty: Decimal, price: Decimal, bar: Bar) -> Decimal:
        """Adverse per-share price adjustment for ``qty`` at ``price`` on ``bar``."""
        return self._slippage.cost(qty, price, bar)

    def fill(self, orders: pd.DataFrame, bar: Bar) -> list[Trade]:
        """Turn desired orders into filled :class:`Trade` objects at ``bar``.

        ``orders`` is indexed by symbol with a signed ``quantity`` column and an
        optional ``limit`` column. Orders for symbols other than ``bar.symbol``
        are ignored (the engine drives one bar/symbol at a time or passes a
        matching bar).
        """
        trades: list[Trade] = []
        as_of = bar.timestamp.date()
        for symbol, row in orders.iterrows():
            qty = Decimal(str(row["quantity"]))
            if qty == 0:
                continue
            if symbol != bar.symbol:
                continue
            reason = self._constraints.reject_reason(str(symbol), qty, as_of)
            if reason is not None:
                self.rejected_orders += 1
                continue
            if qty < 0 and not self._short.can_short(str(symbol)):
                self.rejected_orders += 1
                continue
            base = self._fill.reference_price(bar)
            if self._fill.kind == "limit":
                limit_price = Decimal(str(row.get("limit", base)))
                if not self._fill.limit_marketable(qty, limit_price, bar):
                    self.rejected_orders += 1
                    continue
            slip = self._slippage.cost(qty, base, bar)
            fill_price = base + slip
            commission = self._commission.cost(qty, fill_price)
            trades.append(
                Trade(
                    timestamp=bar.timestamp,
                    symbol=str(symbol),
                    side="buy" if qty > 0 else "sell",
                    quantity=abs(qty),
                    price=fill_price,
                    commission=commission,
                    slippage=abs(slip) * abs(qty),
                )
            )
        return trades
