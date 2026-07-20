"""Unit tests for paper fill engine v0 (#563)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from openbb_portfolio_intel.paper import (
    AccountConfig,
    Fill,
    InMemoryAccountStore,
    InMemoryPositionStore,
    OrderRejected,
    OrderRequest,
    OrderStatus,
    OrderType,
    Quote,
    QuoteFetcher,
    SubmitResult,
    submit_order,
)

D = Decimal
NOW = datetime(2026, 7, 20, 9, 30, 0)


class StubQuoteFetcher:
    """Deterministic quote source for tests."""

    def __init__(self, quotes: dict[str, Quote]) -> None:
        self._quotes = quotes
        self.calls: list[str] = []

    def fetch(self, symbol: str, *, now: datetime) -> Quote:
        self.calls.append(symbol)
        return self._quotes[symbol]


class RaisingQuoteFetcher:
    """QuoteFetcher that always raises — for the fetch-failure path."""

    def fetch(self, symbol: str, *, now: datetime) -> Quote:
        raise RuntimeError("simulated quote API 503")


def _mk_env(
    *,
    cash: Decimal = D("100000"),
    slippage_bps: int = 5,
    commission_model: str = "zero",
):
    account_store = InMemoryAccountStore()
    position_store = InMemoryPositionStore()
    account = account_store.create(
        user_id="daisy",
        config=AccountConfig(
            starting_cash=cash,
            slippage_bps=slippage_bps,
            commission_model=commission_model,
        ),
        now=NOW,
    )
    return account_store, position_store, account


def _mk_quote(symbol: str, last: Decimal, quoted_at: datetime | None = NOW) -> Quote:
    return Quote(
        symbol=symbol,
        last=last,
        bid=last - D("0.05"),
        ask=last + D("0.05"),
        quoted_at=quoted_at,
        snapshot_id=f"snap_{symbol}_{quoted_at.isoformat() if quoted_at else 'na'}",
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_market_buy_fills_and_debits_cash() -> None:
    astore, pstore, acc = _mk_env()
    q = _mk_quote("AAPL", D("100"))
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10"), order_type=OrderType.MARKET),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q}),
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED
    assert isinstance(r.fill, Fill)
    # 5bps slippage adverse: buy at 100 * 1.0005 = 100.05
    assert r.fill.price == D("100.0500")
    # cash debited: starting 100000 - 100.05 * 10 = 100000 - 1000.5 = 98999.5
    assert r.account.cash_balance == D("98999.5000")
    assert r.lot.qty == D("10")
    assert r.lot.avg_cost == D("100.0500")
    # quote_snapshot_id threaded through for replay
    assert r.fill.quote_snapshot_id == q.snapshot_id


def test_market_sell_credits_cash() -> None:
    astore, pstore, acc = _mk_env()
    # Establish a long position first via buy
    submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    # Now sell at 110
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("-10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("110"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED
    # 5bps slippage adverse on sell: 110 * 0.9995 = 109.945
    assert r.fill.price == D("109.9450")
    # cash: after buy at 100.05 * 10 = 98999.5; sell at 109.945 * 10 = 1099.45
    # → 98999.5 + 1099.45 = 100098.95
    assert r.account.cash_balance == D("100098.9500")
    assert r.lot.qty == D("0")  # flat after full close


def test_limit_buy_marketable_fills() -> None:
    astore, pstore, acc = _mk_env()
    q = _mk_quote("AAPL", D("100"))  # last 100
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.LIMIT,
            limit_price=D("100.10"),  # buy limit at/above last → marketable
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q}),
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED


def test_commission_per_share_applied() -> None:
    astore, pstore, acc = _mk_env(commission_model="per_share")
    q = _mk_quote("AAPL", D("100"))
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q}),
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED
    # 10 shares * $0.005 = $0.05 commission
    assert r.fill.commission == D("0.050")


# ---------------------------------------------------------------------------
# Business rejections (return REJECTED, not raise)
# ---------------------------------------------------------------------------


def test_account_not_found_returns_rejected() -> None:
    astore, pstore, _ = _mk_env()
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("1")),
        user_id="mallory",
        account_id="does_not_exist",
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "not found" in r.reason


def test_foreign_user_account_returns_rejected() -> None:
    """Cross-account isolation seed (#546): mallory can't trade daisy's book."""
    astore, pstore, acc = _mk_env()
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("1")),
        user_id="mallory",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "not found" in r.reason


def test_stale_quote_returns_rejected() -> None:
    astore, pstore, acc = _mk_env()
    old_quote = _mk_quote("AAPL", D("100"), quoted_at=NOW - timedelta(seconds=120))
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": old_quote}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "stale" in r.reason


def test_unstamped_quote_rejected() -> None:
    """Security: a quote missing quoted_at MUST NOT bypass the freshness check."""
    astore, pstore, acc = _mk_env()
    unstamped = Quote(
        symbol="AAPL", last=D("100"), quoted_at=None, snapshot_id="unstamped"
    )
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": unstamped}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "stale" in r.reason


def test_quote_fetch_failure_returns_rejected() -> None:
    astore, pstore, acc = _mk_env()
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=RaisingQuoteFetcher(),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "quote fetch failed" in r.reason


def test_buy_limit_below_last_rejected() -> None:
    astore, pstore, acc = _mk_env()
    q = _mk_quote("AAPL", D("100"))  # last 100
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.LIMIT,
            limit_price=D("95"),  # buy limit below last → non-marketable
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "non-marketable" in r.reason


def test_sell_limit_above_last_rejected() -> None:
    astore, pstore, acc = _mk_env()
    # Establish long
    submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    # Sell limit at 110 with last at 100 — not marketable
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("-5"),
            order_type=OrderType.LIMIT,
            limit_price=D("110"),
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED


def test_insufficient_cash_rejected() -> None:
    astore, pstore, acc = _mk_env(cash=D("100"))  # tiny book
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("100")),  # need ~10000
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "insufficient cash" in r.reason


def test_inactive_account_rejected() -> None:
    astore, pstore, acc = _mk_env()
    astore.delete(acc.account_id, user_id="daisy", now=NOW)
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("1")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "inactive" in r.reason


# ---------------------------------------------------------------------------
# Structural rejections (RAISE — programmer error, not business logic)
# ---------------------------------------------------------------------------


def test_zero_qty_raises() -> None:
    astore, pstore, acc = _mk_env()
    with pytest.raises(OrderRejected, match=r"non-zero"):
        submit_order(
            OrderRequest(symbol="AAPL", qty=D("0")),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=StubQuoteFetcher({}),
            now=NOW,
        )


def test_limit_without_limit_price_raises() -> None:
    astore, pstore, acc = _mk_env()
    with pytest.raises(OrderRejected, match=r"limit_price required"):
        submit_order(
            OrderRequest(symbol="AAPL", qty=D("1"), order_type=OrderType.LIMIT),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=StubQuoteFetcher({}),
            now=NOW,
        )


def test_market_with_limit_price_raises() -> None:
    astore, pstore, acc = _mk_env()
    with pytest.raises(OrderRejected, match=r"must not be set"):
        submit_order(
            OrderRequest(
                symbol="AAPL",
                qty=D("1"),
                order_type=OrderType.MARKET,
                limit_price=D("100"),
            ),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=StubQuoteFetcher({}),
            now=NOW,
        )


# ---------------------------------------------------------------------------
# Property: cash + position value conservation
# ---------------------------------------------------------------------------


def test_fill_conservation_across_round_trip() -> None:
    """Round-trip: buy N + sell N → cash net delta == -realized_pnl - commissions.

    On a zero-slippage account, buying 10 @ 100 and selling 10 @ 100 with zero
    commission should return cash to exactly the starting balance. Verifies the
    debit/credit arithmetic is symmetric.
    """
    astore, pstore, acc = _mk_env(slippage_bps=0, commission_model="zero")
    start = acc.cash_balance
    for _ in range(3):
        submit_order(
            OrderRequest(symbol="AAPL", qty=D("10")),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
            now=NOW,
        )
        submit_order(
            OrderRequest(symbol="AAPL", qty=D("-10")),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
            now=NOW,
        )
    final = astore.get(acc.account_id, user_id="daisy").cash_balance
    assert final == start


# ---------------------------------------------------------------------------
# R7.11 — slippage direction must be adverse
# ---------------------------------------------------------------------------


def test_r711_slippage_is_adverse_to_trader() -> None:
    """Slippage MUST be adverse: buy fills above reference, sell fills below.

    Mutation check: if slippage flipped to favorable, this test breaks.
    """
    astore, pstore, acc = _mk_env(slippage_bps=100)  # 100bp for clarity
    q = _mk_quote("AAPL", D("100"))
    buy = submit_order(
        OrderRequest(symbol="AAPL", qty=D("1")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q}),
        now=NOW,
    )
    # 100bp = 1% adverse on buy
    assert buy.fill.price == D("101.00")
    sell = submit_order(
        OrderRequest(symbol="AAPL", qty=D("-1")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q}),
        now=NOW,
    )
    # 100bp adverse on sell
    assert sell.fill.price == D("99.00")
    # If slippage were flipped (favorable), buy would fill at 99 and sell at 101.


def test_r711_quote_freshness_is_load_bearing() -> None:
    """Boundary test: quote at exactly 60s is fresh, at 61s is stale.

    Mutation check: if the boundary were <, both would reject; if <=, both fill.
    """
    astore, pstore, acc = _mk_env()
    q_60s = _mk_quote("AAPL", D("100"), quoted_at=NOW - timedelta(seconds=60))
    q_61s = _mk_quote("AAPL", D("100"), quoted_at=NOW - timedelta(seconds=61))
    r_ok = submit_order(
        OrderRequest(symbol="AAPL", qty=D("1")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q_60s}),
        now=NOW,
    )
    assert r_ok.status is OrderStatus.FILLED
    r_stale = submit_order(
        OrderRequest(symbol="AAPL", qty=D("1")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": q_61s}),
        now=NOW,
    )
    assert r_stale.status is OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# Security guards (background review findings)
# ---------------------------------------------------------------------------


def test_sell_more_than_owned_rejected_when_margin_disabled() -> None:
    """Selling more than owned WITHOUT margin must reject (no implicit short)."""
    astore, pstore, acc = _mk_env()
    # Open a 10-share long
    submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    # Try to sell 15 → projected qty = -5 → REJECT (no margin)
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("-15")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "short" in r.reason


def test_sell_when_flat_rejected_when_margin_disabled() -> None:
    """Selling with no position at all is also rejected (would open a short)."""
    astore, pstore, acc = _mk_env()
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("-10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED


def test_sell_more_than_owned_allowed_with_margin_enabled() -> None:
    """Margin=True permits shorts; the guard only trips when margin=False."""
    astore = InMemoryAccountStore()
    pstore = InMemoryPositionStore()
    acc = astore.create(
        user_id="daisy",
        config=AccountConfig(
            starting_cash=D("100000"),
            slippage_bps=0,
            commission_model="zero",
            margin_enabled=True,
        ),
        now=NOW,
    )
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("-10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=StubQuoteFetcher({"AAPL": _mk_quote("AAPL", D("100"))}),
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED
    assert r.lot.qty == D("-10")


def test_quote_symbol_mismatch_rejected() -> None:
    """A fetcher returning a quote for a different symbol → REJECT.

    Prevents silent mis-execution if a fetcher bug returns MSFT's quote
    for an AAPL request.
    """

    class MismatchedFetcher:
        def fetch(self, symbol: str, *, now: datetime) -> Quote:
            # Requested symbol is ignored; always return MSFT
            return Quote(symbol="MSFT", last=D("300"), quoted_at=now, snapshot_id="s")

    astore, pstore, acc = _mk_env()
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=MismatchedFetcher(),
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "symbol mismatch" in r.reason


def test_quote_symbol_case_normalized() -> None:
    """Fetcher may return 'aapl' vs request 'AAPL' — case-normalized comparison."""

    class LowercaseFetcher:
        def fetch(self, symbol: str, *, now: datetime) -> Quote:
            return Quote(
                symbol=symbol.lower(),
                last=D("100"),
                quoted_at=now,
                snapshot_id="s",
            )

    astore, pstore, acc = _mk_env()
    r = submit_order(
        OrderRequest(symbol="AAPL", qty=D("10")),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=LowercaseFetcher(),
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED


def test_position_store_isolates_foreign_user_reads() -> None:
    """PositionStore is keyed by user_id — foreign users can't see others' lots."""
    pstore = InMemoryPositionStore()
    # daisy owns 10 AAPL in account acc-1
    from openbb_portfolio_intel.paper import Lot

    daisy_lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    pstore.put("acc-1", daisy_lot, user_id="daisy")
    # mallory tries to read acc-1 as her own → gets flat, not daisy's 10
    mallory_view = pstore.get("acc-1", "AAPL", user_id="mallory")
    assert mallory_view.qty == D("0")
    assert mallory_view.avg_cost == D("0")
    # daisy still sees her position
    daisy_view = pstore.get("acc-1", "AAPL", user_id="daisy")
    assert daisy_view == daisy_lot


def test_position_store_isolates_foreign_user_writes() -> None:
    """Foreign write can't clobber the owner's lot."""
    pstore = InMemoryPositionStore()
    from openbb_portfolio_intel.paper import Lot

    daisy_lot = Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))
    pstore.put("acc-1", daisy_lot, user_id="daisy")
    # mallory writes her own lot under acc-1 — daisy's stays intact
    mallory_lot = Lot(symbol="AAPL", qty=D("999"), avg_cost=D("1"), realized_pnl=D("0"))
    pstore.put("acc-1", mallory_lot, user_id="mallory")
    assert pstore.get("acc-1", "AAPL", user_id="daisy") == daisy_lot
    assert pstore.get("acc-1", "AAPL", user_id="mallory") == mallory_lot
