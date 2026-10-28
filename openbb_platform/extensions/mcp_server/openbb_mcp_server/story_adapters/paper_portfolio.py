"""Portfolio Intelligence paper books in story sandboxes (#2333, N09c).

A sandbox created with ``engine="portfolio"`` holds a Portfolio Intelligence
paper account, its lots and its append-only ledger in one SQLite file under
the sandbox directory, through the durable ``SqliteAccountStore``,
``SqlitePositionStore`` and ``SqliteLedgerStore``. Its one action,
``submit_order``, runs the existing ``submit_order`` fill engine behind the
N09a approval gate, so it is prepared, approved by a person and applied once,
exactly like a TechTrade action.

The quote is part of the approved arguments: the person approves the price
the order fills against, and the fill is stamped at the quote's
``quoted_at``. At apply time the quote must not be stamped in the future, be
older than ``MAX_QUOTE_AGE`` or predate the book's last ledger entry, so the
ledger's order is the order fills were applied in.

A business rejection, such as an order the cash cannot cover, is an applied
result with ``status: "rejected"``, its reason, and the alert the Portfolio
alerts pipeline raises for it; it changes nothing in the book. Every order,
filled or rejected, lands on the sandbox's blotter. ``state`` replays the
ledger and reports whether it reconciles with the live account and lots.

Seed positions given at sandbox creation enter the ledger as a deposit of
their cost and a trade at their average cost, so the opening cash is the
starting cash and the replay holds from the first moment.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from openbb_mcp_server.story_adapters import paper as _paper
from openbb_mcp_server.story_adapters.paper import (
    SeedLot,
    _Amount,
    _Strict,
)

MAX_QUOTE_AGE = timedelta(minutes=30)
FUTURE_SKEW = timedelta(seconds=5)
BOOK_FILE = "portfolio.sqlite"
LOCK_FILE = "portfolio.lock"
_BLOTTER = (
    "CREATE TABLE IF NOT EXISTS story_blotter ("
    " seq INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL,"
    " symbol TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,"
    " order_type TEXT NOT NULL, limit_price TEXT, status TEXT NOT NULL,"
    " fill_price TEXT, commission TEXT, reason TEXT NOT NULL,"
    " quoted_at TEXT NOT NULL)"
)


class OrderQuote(_Strict):
    """The quote a person approves the order to fill against."""

    last: _Amount
    bid: _Amount | None = None
    ask: _Amount | None = None
    quoted_at: AwareDatetime
    snapshot_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{0,80}$")] = ""


class SubmitOrder(_Strict):
    """Submit one market or limit order to the Portfolio paper book."""

    symbol: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9./\-]{0,15}$")]
    side: Literal["buy", "sell"]
    quantity: _Amount
    order_type: Literal["market", "limit"] = "market"
    limit_price: _Amount | None = None
    time_in_force: Literal["day", "gtc"] = "day"
    quote: OrderQuote

    @model_validator(mode="after")
    def _limit_price_matches_type(self) -> SubmitOrder:
        if (self.order_type == "limit") != (self.limit_price is not None):
            raise ValueError("a limit order needs limit_price; a market order has none")
        return self


ACTIONS: dict[str, type[_Strict]] = {"submit_order": SubmitOrder}


def engine_errors() -> tuple[type[Exception], ...]:
    """Exceptions that mean the book refused the action."""
    # pylint: disable=import-outside-toplevel
    from openbb_portfolio_intel.paper.fills import OrderRejected
    from openbb_portfolio_intel.paper.ledger import LedgerError

    return (OrderRejected, LedgerError, ValueError)


@dataclass(frozen=True)
class _FixedQuote:
    """``QuoteFetcher`` that returns the approved quote and nothing else."""

    quote: Any

    # pylint: disable-next=unused-argument
    def fetch(self, symbol: str, *, now: datetime) -> Any:  # noqa: ARG002
        """Return the approved quote; the engine checks the symbol."""
        return self.quote


class PortfolioBook:
    """One sandbox's Portfolio paper account, lots, ledger and blotter."""

    def __init__(
        self, directory: Path, *, user_id: str, account_id: str, starting_cash: Decimal
    ):
        """Bind the book to its sandbox directory; stores open lazily."""
        # pylint: disable=import-outside-toplevel
        from openbb_portfolio_intel.paper.sqlite_stores import (
            SqliteAccountStore,
            SqliteLedgerStore,
            SqlitePositionStore,
        )

        self.path = directory / BOOK_FILE
        self.lock_path = directory / LOCK_FILE
        self.user_id = user_id
        self.account_id = account_id
        self.starting_cash = starting_cash
        self.accounts = SqliteAccountStore(self.path)
        self.positions = SqlitePositionStore(self.path)
        self.ledger = SqliteLedgerStore(self.path)
        self.errors = engine_errors()

    def close(self) -> None:
        """Nothing to release; every store call opens its own connection."""

    @contextmanager
    def _blotter(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute(_BLOTTER)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Serialize orders on this book across threads and processes."""
        connection = sqlite3.connect(self.lock_path, isolation_level=None, timeout=60)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield
        finally:
            connection.execute("ROLLBACK")
            connection.close()

    def open_account(self, seeds: list[SeedLot], *, at: datetime) -> None:
        """Create the account and enter any seed positions; once, at creation."""
        # pylint: disable=import-outside-toplevel
        from openbb_portfolio_intel.paper.accounts import AccountConfig
        from openbb_portfolio_intel.paper.cost_basis import Lot
        from openbb_portfolio_intel.paper.ledger import deposit_entry, trade_entry

        self.accounts.create(
            user_id=self.user_id,
            config=AccountConfig(starting_cash=self.starting_cash),
            now=at,
            account_id=self.account_id,
        )
        sequence = 0
        for seed in seeds:
            cost = seed.quantity * seed.avg_cost
            for entry in (
                deposit_entry(
                    account_id=self.account_id,
                    user_id=self.user_id,
                    sequence=(sequence := sequence + 1),
                    occurred_at=at,
                    amount=cost,
                    notes=f"seed {seed.symbol} cost",
                ),
                trade_entry(
                    account_id=self.account_id,
                    user_id=self.user_id,
                    sequence=(sequence := sequence + 1),
                    occurred_at=at,
                    symbol=seed.symbol,
                    quantity=seed.quantity,
                    price=seed.avg_cost,
                    notes="seed",
                ),
            ):
                self.ledger.append(entry)
            self.positions.put(
                self.account_id,
                Lot(symbol=seed.symbol, qty=seed.quantity, avg_cost=seed.avg_cost),
                user_id=self.user_id,
            )

    def _entries(self) -> list[Any]:
        return self.ledger.list_for_account(self.account_id, user_id=self.user_id)

    def _stale(self, quoted_at: datetime) -> str:
        now = _paper._now()  # pylint: disable=protected-access
        if quoted_at > now + FUTURE_SKEW:
            return f"the quote is stamped in the future ({quoted_at.isoformat()})"
        if now - quoted_at > MAX_QUOTE_AGE:
            minutes = int(MAX_QUOTE_AGE.total_seconds() // 60)
            return f"the quote is older than {minutes} minutes; prepare it again"
        entries = self._entries()
        if entries and quoted_at < entries[-1].occurred_at:
            return "the quote predates the book's last entry; prepare it again"
        return ""

    def run(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Apply one validated order and record it on the blotter."""
        # pylint: disable=import-outside-toplevel
        from openbb_portfolio_intel.paper.fills import (
            OrderRequest,
            OrderStatus,
            OrderType,
            Quote,
            TimeInForce,
            submit_order,
        )
        from openbb_portfolio_intel.paper.ledger import trade_entry
        from openbb_portfolio_intel.paper.locking import AccountLockManager

        typed = ACTIONS[action].model_validate(arguments)
        assert isinstance(typed, SubmitOrder)  # noqa: S101  # ACTIONS is closed
        quoted_at = typed.quote.quoted_at
        signed = typed.quantity if typed.side == "buy" else -typed.quantity
        with self._exclusive():
            reason = self._stale(quoted_at)
            if reason:
                return self._record(typed, "rejected", reason=reason)
            result = submit_order(
                OrderRequest(
                    symbol=typed.symbol,
                    qty=signed,
                    order_type=OrderType(typed.order_type),
                    limit_price=typed.limit_price,
                    time_in_force=TimeInForce(typed.time_in_force),
                ),
                user_id=self.user_id,
                account_id=self.account_id,
                account_store=self.accounts,
                position_store=self.positions,
                quote_fetcher=_FixedQuote(
                    Quote(
                        symbol=typed.symbol,
                        last=typed.quote.last,
                        bid=typed.quote.bid,
                        ask=typed.quote.ask,
                        quoted_at=quoted_at,
                        snapshot_id=typed.quote.snapshot_id,
                    )
                ),
                now=quoted_at,
                # The book lock above serializes orders; a private manager
                # keeps the process-wide one from coupling sandboxes.
                lock_manager=AccountLockManager(),
            )
            if result.status is not OrderStatus.FILLED or result.fill is None:
                return self._record(typed, "rejected", reason=result.reason)
            fill = result.fill
            self.ledger.append(
                trade_entry(
                    account_id=self.account_id,
                    user_id=self.user_id,
                    sequence=len(self._entries()) + 1,
                    occurred_at=fill.filled_at,
                    symbol=fill.symbol,
                    quantity=fill.qty,
                    price=fill.price,
                    commission=fill.commission,
                    entry_id=fill.fill_id,
                    notes=fill.order_id,
                )
            )
            return self._record(typed, "filled", fill=fill, cash=result.account)

    def _record(
        self,
        order: SubmitOrder,
        status: str,
        *,
        reason: str = "",
        fill: Any = None,
        cash: Any = None,
    ) -> dict[str, Any]:
        """Add the order to the blotter and describe its outcome."""
        order_id = fill.order_id if fill is not None else f"rej_{uuid.uuid4().hex[:16]}"
        with self._blotter() as connection:
            connection.execute(
                "INSERT INTO story_blotter (order_id, symbol, side, quantity,"
                " order_type, limit_price, status, fill_price, commission, reason,"
                " quoted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order_id,
                    order.symbol,
                    order.side,
                    str(order.quantity),
                    order.order_type,
                    None if order.limit_price is None else str(order.limit_price),
                    status,
                    None if fill is None else str(fill.price),
                    None if fill is None else str(fill.commission),
                    reason,
                    order.quote.quoted_at.isoformat(),
                ),
            )
        outcome: dict[str, Any] = {
            "order_id": order_id,
            "symbol": order.symbol,
            "status": status,
        }
        if fill is not None:
            outcome["fill"] = {
                "fill_id": fill.fill_id,
                "quantity": str(fill.qty),
                "price": str(fill.price),
                "commission": str(fill.commission),
                "slippage_bps": fill.slippage_bps,
                "filled_at": fill.filled_at.isoformat(),
            }
            outcome["cash"] = str(cash.cash_balance)
            return outcome
        outcome["reason"] = reason
        outcome["alert"] = _rejection_alert(order, reason)
        return outcome

    def state(self) -> dict[str, Any]:
        """Account, lots, blotter, and whether the ledger replays to the book."""
        # pylint: disable=import-outside-toplevel
        from openbb_portfolio_intel.paper.ledger import replay

        account = self.accounts.get(self.account_id, user_id=self.user_id)
        if account is None:
            raise ValueError("The sandbox's paper account is missing.")
        lots = self.positions.lots(self.account_id, user_id=self.user_id)
        entries = self._entries()
        replayed = replay(entries, starting_cash=account.config.starting_cash)
        live = {lot.symbol: (lot.qty, lot.avg_cost) for lot in lots if lot.qty != 0}
        rebuilt = {s: (lot.qty, lot.avg_cost) for s, lot in replayed.positions.items()}
        with self._blotter() as connection:
            blotter = [
                {key: value for key, value in dict(row).items() if key != "seq"}
                for row in connection.execute(
                    "SELECT * FROM story_blotter ORDER BY seq"
                ).fetchall()
            ]
        return {
            "account": {
                "starting_cash": str(account.config.starting_cash),
                "cash": str(account.cash_balance),
                "realized_pl": str(sum((lot.realized_pnl for lot in lots), Decimal(0))),
            },
            "positions": [
                {
                    "symbol": lot.symbol,
                    "quantity": str(lot.qty),
                    "avg_cost": str(lot.avg_cost),
                    "realized_pnl": str(lot.realized_pnl),
                }
                for lot in lots
            ],
            "blotter": blotter,
            "ledger": {
                "entries": len(entries),
                "reconciled": replayed.cash == account.cash_balance and rebuilt == live,
            },
        }


def _rejection_alert(order: SubmitOrder, reason: str) -> dict[str, Any]:
    """Return the alert the Portfolio alerts pipeline raises for this rejection."""
    # pylint: disable=import-outside-toplevel
    from openbb_portfolio_intel.analytics.alerts import (
        PaperTradingEvent,
        evaluate_paper_trading_events,
    )

    when = order.quote.quoted_at
    (alert,) = evaluate_paper_trading_events(
        [
            PaperTradingEvent(
                symbol=order.symbol,
                when=when,
                status="REJECTED",
                reason=reason,
                quantity=order.quantity,
            )
        ],
        since=when,
    )
    return {
        "kind": (
            "low_buying_power"
            if reason.startswith("insufficient cash")
            else "order_rejected"
        ),
        "trigger": alert.trigger.value,
        "severity": alert.severity.value,
        "message": alert.message,
        "key": alert.key,
    }
