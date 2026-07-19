"""SimpleFillModel — minimal ``Broker`` Protocol impl for paper trading.

Ships #498's A' resolution: portfolio-intel's paper trading builds on
the existing ``openbb_backtest.interfaces.Broker`` Protocol rather than
inventing a new interface. See ``docs/superpowers/plans/
2026-07-16-portfolio-intel-roadmap.md`` § M3 for the sequencing.

This implementation is scoped to **Market orders only** — the minimum
that makes the Protocol callable end-to-end. Limit / Stop / Stop-Limit
/ Trailing-Stop and TIF (day/gtc) semantics land in follow-up issues
(#563, #544).

Design invariants:
- Strictly Protocol-compliant so isinstance() checks + a future swap to
  RealisticBroker work without changing call sites.
- Delegates commission + slippage to injected models (openbb_backtest's
  ``CommissionModel`` + ``SlippageModel``) — no math redefined here.
- Uses ``Decimal`` for all money math (matches Broker Protocol contract).
- No hidden state: fills depend only on (orders, bar) and injected
  config. No caches, no time-dependent behavior beyond bar.timestamp.
"""

# pylint: disable=disallowed-name
# 'bar' is domain vocabulary (an OHLCV market bar), used identically by
# openbb_backtest. Suppressing pylint's default 'bar' → disallowed-name
# rule at file level since it appears in every method signature.

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from openbb_backtest.engine.execution import Commission, Slippage
from openbb_backtest.models import Bar, CommissionModel, SlippageModel, Trade

if TYPE_CHECKING:
    import pandas as pd


class SimpleFillModel:
    """Minimal ``Broker`` implementation for paper trading.

    Handles Market orders only in the initial scope. Rejects Limit /
    Stop / other order types with a clear ``NotImplementedError`` — the
    follow-up issues (#563 Fills v0 for Limit + TIF; #544 Fills v1 for
    Stop family) extend this class rather than replacing it.

    Constructor
    ~~~~~~~~~~~
    ``commission`` / ``slippage``: injected ``openbb_backtest`` models.
    Defaults are zero-commission and zero-slippage — override in real
    paper accounts. #563's body specifies 5 bps default slippage; this
    class does not force that default so tests can be deterministic.
    """

    def __init__(
        self,
        commission: CommissionModel | None = None,
        slippage: SlippageModel | None = None,
    ) -> None:
        self._commission = Commission.of(commission or CommissionModel())
        self._slippage = Slippage.of(slippage or SlippageModel())

    # ---- Broker Protocol methods ----

    def fill(self, orders: pd.DataFrame, bar: Bar) -> list[Trade]:
        """Convert desired orders into Market-order fills at ``bar``.

        Parameters
        ----------
        orders : pd.DataFrame
            Indexed by symbol. Required columns:
              - ``quantity`` : signed Decimal-convertible; positive = buy,
                negative = sell, zero = skip.
            Optional columns:
              - ``order_type`` : "market" (default). Any other value
                raises ``NotImplementedError`` — Limit / Stop land in
                follow-up issues.
        bar : Bar
            The market bar to fill against. Orders whose symbol doesn't
            match ``bar.symbol`` are silently skipped (matches
            RealisticBroker behavior).

        Returns
        -------
        list[Trade]
            One Trade per non-zero, matching order. Empty list if
            nothing to fill (out-of-bar-symbol, zero qty).
        """
        trades: list[Trade] = []
        for symbol, row in orders.iterrows():
            qty = Decimal(str(row["quantity"]))
            if qty == 0:
                continue
            if symbol != bar.symbol:
                continue

            order_type = str(row.get("order_type", "market")).lower()
            if order_type != "market":
                raise NotImplementedError(
                    f"SimpleFillModel: order_type={order_type!r} not supported yet. "
                    "Market only in this issue (#892); Limit + TIF land in #563, "
                    "Stop family in #544."
                )

            # Market order: fill at bar open + adverse slippage.
            base_price = bar.open
            slip = self._slippage.cost(qty, base_price, bar)
            fill_price = base_price + slip
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

    def commission(self, qty: Decimal, price: Decimal) -> Decimal:
        """Commission for trading ``qty`` at ``price`` (never negative)."""
        return self._commission.cost(qty, price)

    def slippage(self, qty: Decimal, price: Decimal, bar: Bar) -> Decimal:
        """Adverse per-share price adjustment (signed: + for buys, − for sells)."""
        return self._slippage.cost(qty, price, bar)
