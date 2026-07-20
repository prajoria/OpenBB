"""Paper fill engine v0 — market + limit orders (#563).

PRD §16.4 first-cut fill engine. Handles:

- **Order types:** market, limit
- **Time-in-force:** day, gtc
- **Quote source:** injected via a ``QuoteFetcher`` seam (unit tests
  patch; router wires ``obb.equity.price.quote`` via ``fmp_cached``).
- **Slippage:** applied as a fixed basis-point adjustment to the mid /
  quote at fill time. Default 5 bps (per PRD §16.4).
- **Commission:** delegated to the account's ``commission_model``.
- **Quote freshness:** 60-second staleness check (PRD §16.4).

## Design

- **Composed, not entangled.** The fill engine calls ``apply_fill``
  from #548 for cost-basis / P&L math and reads/writes cash through
  the ``AccountStore`` from #562 — no duplication of that logic here.
- **Pluggable seams.** ``QuoteFetcher`` is a Protocol; ``PositionStore``
  is a Protocol; both have in-memory defaults so tests need zero I/O.
- **Deterministic fills.** ``now`` and ``quote_snapshot_id`` are inputs
  to ``submit_order``, matching the pattern from #543 (``today``) and
  #562 (``now``). Enables reproducible fixtures + replay.
- **Immediate market fills, immediate limit-price-check fills.** No
  event-driven queueing in v0. A limit order priced OUTSIDE the fresh
  quote is REJECTED (v0), not queued — stops + open-book queueing land
  in #544 (Fills v1).
- **Position tracking via #548's Lot.** After ``apply_fill`` yields
  ``(new_lot, realized_pnl)``, this engine writes both to the
  ``PositionStore`` and debits/credits cash on the ``AccountStore``.

## Cash arithmetic

- BUY: cash -= (price * qty + commission)  (spend)
- SELL: cash += (price * qty - commission)  (receive proceeds)

Both invariants are property-tested. Cash + market_value(positions)
after N fills == starting_cash + realized_pnl by the round-trip
identity — verified in ``test_fill_conservation``.

## Out of scope (deferred)

- **Stop / stop-limit / trailing-stop** — #544 Fills v1.
- **Partials modeled by ADV** — #544 covers qty/ADV < 0.5% partials.
- **IOC / FOK** — #544.
- **Race hardening** — #547 explicit lock ordering (single-writer per
  account_id).
- **Ledger persistence** — #545 owns paper_ledger.
- **Corporate actions** — #545 ledger + follow-up on cost-basis adjust.
"""

# pylint: disable=unused-argument  # commission signatures accept unused args for API uniformity
# pylint: disable=too-many-return-statements  # submit_order fans out 10+ terminal branches

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from threading import Lock
from typing import Protocol
from uuid import uuid4

from openbb_portfolio_intel.paper.accounts import (
    AccountConfigError,
    AccountStore,
    PaperAccount,
)
from openbb_portfolio_intel.paper.cost_basis import (
    FillEvent,
    Lot,
    apply_fill,
)

QUOTE_FRESHNESS_SECONDS: int = 60  # PRD §16.4


class OrderType(str, Enum):
    """Supported order types in v0 (#563)."""

    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    """Supported TIF in v0 (#563). IOC/FOK land in #544."""

    DAY = "day"
    GTC = "gtc"


class OrderStatus(str, Enum):
    """Terminal statuses after v0 submit_order returns."""

    FILLED = "filled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Quote:
    """One point-in-time equity quote for a symbol.

    ``last`` is the reference price for market orders. ``bid`` / ``ask``
    are informational in v0 (limit orders check ``last`` for
    marketability). Populated by the router from
    ``obb.equity.price.quote``.
    """

    symbol: str
    last: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    quoted_at: datetime | None = None
    snapshot_id: str = ""  # ties fill to the underlying quote row


@dataclass(frozen=True)
class OrderRequest:
    """Caller-supplied order intent."""

    symbol: str
    qty: Decimal  # signed: > 0 = buy, < 0 = sell
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY


@dataclass(frozen=True)
class Fill:
    """One executed fill — the output of a successful submit_order."""

    fill_id: str
    order_id: str
    account_id: str
    symbol: str
    qty: Decimal  # signed
    price: Decimal  # AFTER slippage
    commission: Decimal
    slippage_bps: int
    quote_snapshot_id: str
    filled_at: datetime


@dataclass(frozen=True)
class SubmitResult:
    """What submit_order returns.

    ``status == FILLED``: ``fill`` is populated, ``account`` reflects
    the debited/credited cash, ``lot`` is the post-fill snapshot.
    ``status == REJECTED``: ``reason`` populated; account / lot
    unchanged; ``fill`` is None.
    """

    status: OrderStatus
    fill: Fill | None = None
    account: PaperAccount | None = None
    lot: Lot | None = None
    reason: str = ""


class OrderRejected(Exception):
    """Raised only for programmer-error inputs (e.g. malformed OrderRequest).

    Business rejections (limit not marketable, stale quote, etc.) are
    returned as ``SubmitResult(status=REJECTED, reason=...)`` — not raised.
    """


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class QuoteFetcher(Protocol):
    """Symbol → Quote. Wraps ``obb.equity.price.quote`` in production."""

    def fetch(self, symbol: str, *, now: datetime) -> Quote:
        """Return the latest available quote for ``symbol``."""


class PositionStore(Protocol):
    """Read/write per-account lots.

    Same isolation posture as ``AccountStore`` (#562): ``user_id``
    scoped, foreign accounts return None from ``get``.
    """

    def get(self, account_id: str, symbol: str, *, user_id: str) -> Lot:
        """Return the lot; if none, return a flat Lot(symbol, 0, 0, 0)."""

    def put(self, account_id: str, lot: Lot, *, user_id: str) -> None:
        """Write the lot back."""


# ---------------------------------------------------------------------------
# In-memory PositionStore
# ---------------------------------------------------------------------------


@dataclass
class InMemoryPositionStore:
    """Non-persistent PositionStore. Fine for unit tests + demo.

    Cross-account isolation: keyed on ``(user_id, account_id, symbol)``.
    Foreign users querying an account they don't own get a fresh flat
    ``Lot`` (never see another user's position). Mirrors the
    ``AccountStore`` posture from #562.
    """

    _positions: dict[tuple[str, str, str], Lot] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def get(self, account_id: str, symbol: str, *, user_id: str) -> Lot:
        """Return the lot for (user_id, account_id, symbol) or a flat Lot."""
        with self._lock:
            lot = self._positions.get((user_id, account_id, symbol))
            if lot is None:
                return Lot(
                    symbol=symbol,
                    qty=Decimal("0"),
                    avg_cost=Decimal("0"),
                    realized_pnl=Decimal("0"),
                )
            return lot

    def put(self, account_id: str, lot: Lot, *, user_id: str) -> None:
        """Write the lot back under (user_id, account_id, lot.symbol)."""
        with self._lock:
            self._positions[(user_id, account_id, lot.symbol)] = lot


# ---------------------------------------------------------------------------
# Fill engine
# ---------------------------------------------------------------------------


def _validate_request(req: OrderRequest) -> None:
    if not req.symbol:
        raise OrderRejected("symbol is empty")
    if req.qty == 0:
        raise OrderRejected("qty must be non-zero")
    if req.order_type == OrderType.LIMIT and req.limit_price is None:
        raise OrderRejected("limit_price required for LIMIT order")
    if req.order_type == OrderType.MARKET and req.limit_price is not None:
        raise OrderRejected("limit_price must not be set for MARKET order")
    if req.limit_price is not None and (
        not req.limit_price.is_finite() or req.limit_price <= 0
    ):
        raise OrderRejected(f"limit_price {req.limit_price} must be finite and > 0")


def _quote_is_fresh(quote: Quote, *, now: datetime) -> bool:
    """Return True iff the quote is stamped AND within the freshness window.

    Security: reject unstamped (quoted_at is None) quotes. Under the
    prior "trust the caller" default a buggy fetcher returning a Quote
    without quoted_at silently bypassed the staleness check, allowing
    arbitrary-old data to fill orders. If an offline/backtest mode
    needs unstamped quotes, gate that behind an explicit config flag
    (not a silent fallback).
    """
    if quote.quoted_at is None:
        return False
    age = now - quote.quoted_at
    return age <= timedelta(seconds=QUOTE_FRESHNESS_SECONDS)


def _apply_slippage(
    reference_price: Decimal, is_buy: bool, slippage_bps: int
) -> Decimal:
    """Slippage moves the price ADVERSE to the trader.

    Buy: price = ref * (1 + bps/10000) — pay more
    Sell: price = ref * (1 - bps/10000) — receive less
    """
    factor = Decimal(slippage_bps) / Decimal("10000")
    if is_buy:
        return reference_price * (Decimal("1") + factor)
    return reference_price * (Decimal("1") - factor)


def _commission_for(account: PaperAccount, qty: Decimal, price: Decimal) -> Decimal:
    """Compute commission per account.config.commission_model.

    v0 supports 'zero' and 'per_share' + 'per_trade' + 'tiered' stubs.
    """
    model = account.config.commission_model
    abs_qty = abs(qty)
    if model == "zero":
        return Decimal("0")
    if model == "per_share":
        # $0.005/share, matches IBKR Lite convention
        return abs_qty * Decimal("0.005")
    if model == "per_trade":
        return Decimal("1.00")
    if model == "tiered":
        # Simple stub: 0.35/trade + $0.0035/share (IBKR Pro rough)
        return Decimal("0.35") + abs_qty * Decimal("0.0035")
    # Should be unreachable — validation happens at account create
    return Decimal("0")


def submit_order(  # noqa: PLR0911  # 10+ terminal REJECTED branches (see docstring)
    req: OrderRequest,
    *,
    user_id: str,
    account_id: str,
    account_store: AccountStore,
    position_store: PositionStore,
    quote_fetcher: QuoteFetcher,
    now: datetime,
) -> SubmitResult:
    """Execute one order end-to-end. Deterministic given (req, now, quote).

    Fill algorithm (v0):
      1. Validate req (raises OrderRejected on structural bugs).
      2. Load account (foreign / missing → REJECTED, not raise).
      3. Fetch quote; check freshness → REJECTED if stale.
      4. For LIMIT: check marketability against last price → REJECTED if not.
      5. Compute fill price with slippage.
      6. Compute commission.
      7. Cash check for BUY (available cash >= price * qty + commission) →
         REJECTED if insufficient (margin is #547 scope).
      8. apply_fill → new lot + realized_pnl (#548).
      9. Debit/credit cash on account.
      10. Persist new lot in position_store.
      11. Return SubmitResult.
    """
    _validate_request(req)
    account = account_store.get(account_id, user_id=user_id)
    if account is None:
        return SubmitResult(
            status=OrderStatus.REJECTED,
            reason=f"account {account_id!r} not found for user {user_id!r}",
        )
    if not account.is_active:
        return SubmitResult(
            status=OrderStatus.REJECTED,
            reason=f"account {account_id!r} is inactive",
        )

    try:
        quote = quote_fetcher.fetch(req.symbol, now=now)
    except Exception as exc:  # noqa: BLE001
        return SubmitResult(
            status=OrderStatus.REJECTED,
            reason=f"quote fetch failed: {type(exc).__name__}: {exc}",
        )
    # Security: fetcher must return a quote for the SAME symbol we asked
    # for. A rogue / buggy fetcher returning a different symbol's price
    # would fill an AAPL order at MSFT's price — silent mis-execution.
    # Case-normalize to be tolerant of upstream capitalization drift.
    if quote.symbol.upper() != req.symbol.upper():
        return SubmitResult(
            status=OrderStatus.REJECTED,
            reason=(
                f"quote symbol mismatch: requested {req.symbol!r}, fetcher "
                f"returned {quote.symbol!r}. Refuse to fill on a foreign quote."
            ),
        )
    if not _quote_is_fresh(quote, now=now):
        return SubmitResult(
            status=OrderStatus.REJECTED,
            reason=(
                f"quote for {req.symbol} is stale (quoted_at={quote.quoted_at}, "
                f"now={now}, max_age={QUOTE_FRESHNESS_SECONDS}s)"
            ),
        )

    reference_price = quote.last
    is_buy = req.qty > 0

    # Limit marketability check
    if req.order_type == OrderType.LIMIT:
        # A buy limit is marketable if last <= limit_price; sell limit if last >= limit_price.
        # _validate_request ensured limit_price is not None on LIMIT orders;
        # explicit runtime check to narrow the type for mypy.
        if req.limit_price is None:  # pragma: no cover  # unreachable
            return SubmitResult(
                status=OrderStatus.REJECTED,
                reason="internal: LIMIT order missing limit_price after validation",
            )
        limit = req.limit_price
        if is_buy and reference_price > limit:
            return SubmitResult(
                status=OrderStatus.REJECTED,
                reason=(
                    f"buy limit {limit} below last {reference_price}; "
                    "v0 rejects non-marketable limits (queueing lands in #544)"
                ),
            )
        if not is_buy and reference_price < limit:
            return SubmitResult(
                status=OrderStatus.REJECTED,
                reason=(
                    f"sell limit {limit} above last {reference_price}; "
                    "v0 rejects non-marketable limits (queueing lands in #544)"
                ),
            )

    fill_price = _apply_slippage(reference_price, is_buy, account.config.slippage_bps)
    commission = _commission_for(account, req.qty, fill_price)

    # Load lot early — needed for the sell-oversell guard below AND for
    # apply_fill downstream.
    lot = position_store.get(account_id, req.symbol, user_id=user_id)

    # Signed cash delta. Buys negative, sells positive. Sufficient-cash
    # check happens ATOMICALLY inside apply_cash_delta (post-refactor of
    # #563 security review) — passing min_balance=0 on non-margin accounts
    # so concurrent submit_orders cannot race the balance below zero.
    trade_value = fill_price * req.qty  # signed
    cash_delta = -(trade_value + commission)

    # Security: sell-oversell guard for cash-only accounts. Without this
    # a caller could sell more shares than they own, opening an implicit
    # short — that's ONLY legal when margin is enabled. Enforce
    # projected_qty >= 0 on non-margin sells. Same guard trips on any
    # sell against a flat or short lot.
    if not is_buy and not account.config.margin_enabled:
        # req.qty is negative on a sell; projected_qty = lot.qty + req.qty
        projected_qty = lot.qty + req.qty
        if projected_qty < 0:
            return SubmitResult(
                status=OrderStatus.REJECTED,
                reason=(
                    f"sell of {abs(req.qty)} would drive {req.symbol} qty "
                    f"from {lot.qty} to {projected_qty} (short); short "
                    "sales require margin_enabled=True (v0 rejects; "
                    "explicit short-sell API lands in a follow-up)"
                ),
            )

    # Apply to cost basis / P&L (#548)
    fill_event = FillEvent(
        symbol=req.symbol,
        qty=req.qty,
        price=fill_price,
        commission=commission,
    )
    new_lot, _realized_pnl_from_fill = apply_fill(lot, fill_event)

    # Atomic cash mutation via the store's own primitive. Includes the
    # sufficiency check (min_balance=0 for non-margin accounts) under
    # the same lock as the write — cannot race a concurrent submit_order.
    min_balance = None if account.config.margin_enabled else Decimal("0")
    try:
        updated_account = account_store.apply_cash_delta(
            account_id,
            cash_delta,
            user_id=user_id,
            now=now,
            min_balance=min_balance,
        )
    except AccountConfigError as exc:
        return SubmitResult(
            status=OrderStatus.REJECTED,
            reason=f"insufficient cash: {exc}",
        )
    position_store.put(account_id, new_lot, user_id=user_id)

    fill = Fill(
        fill_id=f"fill_{uuid4().hex[:16]}",
        order_id=f"ord_{uuid4().hex[:16]}",
        account_id=account_id,
        symbol=req.symbol,
        qty=req.qty,
        price=fill_price,
        commission=commission,
        slippage_bps=account.config.slippage_bps,
        quote_snapshot_id=quote.snapshot_id,
        filled_at=now,
    )
    return SubmitResult(
        status=OrderStatus.FILLED,
        fill=fill,
        account=updated_account,
        lot=new_lot,
    )
