"""Unit tests for #544 Fills v1 wire-type acceptance.

## Scope

v1 adds these OrderRequest fields + enum values:

- OrderType.STOP, STOP_LIMIT, TRAILING_STOP
- TimeInForce.IOC, FOK
- OrderRequest.stop_price, trail_amount, trail_percent

The stop-trigger evaluator + peak tracker are DEFERRED to a
scheduler follow-up. This suite verifies:

1. Validation surface: bad shapes raise ``OrderRejected`` cleanly.
2. Well-formed stop / stop_limit / trailing_stop OrderRequests
   pass validation and reach ``submit_order``, which returns a
   documented REJECTED("pending scheduler") result — NOT a crash
   or a silent partial fill.
3. IOC / FOK TIF accepted at the wire level; on v0 fill path they
   collapse to DAY semantics (fill-or-reject-now) — documented,
   ready to diverge when partials land.

The purpose is to lock down the wire contract now so widgets, the
router, and the scheduler follow-up all build against a stable API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from openbb_portfolio_intel.paper import (
    AccountConfig,
    InMemoryAccountStore,
    InMemoryPositionStore,
    OrderRejected,
    OrderRequest,
    OrderStatus,
    OrderType,
    Quote,
    TimeInForce,
    submit_order,
)

D = Decimal
NOW = datetime(2026, 7, 20, 9, 30, 0)


class StubQuoteFetcher:
    def __init__(self, quote: Quote) -> None:
        self._quote = quote

    def fetch(self, symbol: str, *, now: datetime) -> Quote:
        return self._quote


def _mk_env():
    astore = InMemoryAccountStore()
    pstore = InMemoryPositionStore()
    acc = astore.create(
        user_id="daisy",
        config=AccountConfig(
            starting_cash=D("100000"), slippage_bps=0, commission_model="zero"
        ),
        now=NOW,
    )
    fetcher = StubQuoteFetcher(
        Quote(
            symbol="AAPL",
            last=D("100"),
            bid=D("99.95"),
            ask=D("100.05"),
            quoted_at=NOW,
            snapshot_id="s",
        )
    )
    return astore, pstore, acc, fetcher


# ---------------------------------------------------------------------------
# Validation surface — bad shapes raise OrderRejected
# ---------------------------------------------------------------------------


def test_stop_without_stop_price_raises() -> None:
    with pytest.raises(OrderRejected, match=r"stop_price required"):
        astore, pstore, acc, fetcher = _mk_env()
        submit_order(
            OrderRequest(symbol="AAPL", qty=D("10"), order_type=OrderType.STOP),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=fetcher,
            now=NOW,
        )


def test_stop_limit_missing_prices_raises() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    with pytest.raises(OrderRejected, match=r"stop_price AND limit_price"):
        submit_order(
            OrderRequest(
                symbol="AAPL",
                qty=D("10"),
                order_type=OrderType.STOP_LIMIT,
                stop_price=D("95"),  # missing limit_price
            ),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=fetcher,
            now=NOW,
        )


def test_trailing_stop_without_trail_field_raises() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    with pytest.raises(OrderRejected, match=r"trail_amount OR trail_percent"):
        submit_order(
            OrderRequest(
                symbol="AAPL", qty=D("10"), order_type=OrderType.TRAILING_STOP
            ),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=fetcher,
            now=NOW,
        )


def test_negative_stop_price_raises() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    with pytest.raises(OrderRejected, match=r"stop_price"):
        submit_order(
            OrderRequest(
                symbol="AAPL",
                qty=D("10"),
                order_type=OrderType.STOP,
                stop_price=D("-1"),
            ),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=fetcher,
            now=NOW,
        )


def test_trail_percent_out_of_range_raises() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    for bad in (D("0"), D("1"), D("2"), D("-0.5")):
        with pytest.raises(OrderRejected, match=r"trail_percent"):
            submit_order(
                OrderRequest(
                    symbol="AAPL",
                    qty=D("10"),
                    order_type=OrderType.TRAILING_STOP,
                    trail_percent=bad,
                ),
                user_id="daisy",
                account_id=acc.account_id,
                account_store=astore,
                position_store=pstore,
                quote_fetcher=fetcher,
                now=NOW,
            )


# ---------------------------------------------------------------------------
# Well-formed v1 requests return REJECTED("pending scheduler")
# ---------------------------------------------------------------------------


def test_well_formed_stop_returns_pending_scheduler_rejected() -> None:
    """Wire type accepted; evaluator deferred; REJECTED with clear reason."""
    astore, pstore, acc, fetcher = _mk_env()
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.STOP,
            stop_price=D("95"),
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=fetcher,
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "stop" in r.reason.lower()
    assert "pending" in r.reason.lower() or "scheduler" in r.reason.lower()


def test_well_formed_stop_limit_returns_pending_scheduler_rejected() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.STOP_LIMIT,
            stop_price=D("95"),
            limit_price=D("94"),
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=fetcher,
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "stop_limit" in r.reason.lower()


def test_well_formed_trailing_stop_returns_pending_scheduler_rejected() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("-10"),  # trailing stop typically closes a long
            order_type=OrderType.TRAILING_STOP,
            trail_percent=D("0.05"),  # 5%
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=fetcher,
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "trailing_stop" in r.reason.lower()


def test_trailing_stop_accepts_amount_or_percent() -> None:
    """Either trail_amount OR trail_percent suffices; only both-None fails."""
    astore, pstore, acc, fetcher = _mk_env()
    for tp in (D("0.05"),):
        r = submit_order(
            OrderRequest(
                symbol="AAPL",
                qty=D("-10"),
                order_type=OrderType.TRAILING_STOP,
                trail_percent=tp,
            ),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=fetcher,
            now=NOW,
        )
        assert r.status is OrderStatus.REJECTED  # pending scheduler
    for ta in (D("5"),):
        r = submit_order(
            OrderRequest(
                symbol="AAPL",
                qty=D("-10"),
                order_type=OrderType.TRAILING_STOP,
                trail_amount=ta,
            ),
            user_id="daisy",
            account_id=acc.account_id,
            account_store=astore,
            position_store=pstore,
            quote_fetcher=fetcher,
            now=NOW,
        )
        assert r.status is OrderStatus.REJECTED  # pending scheduler


# ---------------------------------------------------------------------------
# TIF v1 (IOC / FOK) — accepted at wire level, collapse to DAY on v0 fill path
# ---------------------------------------------------------------------------


def test_ioc_market_order_fills_immediately() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.IOC,
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=fetcher,
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED


def test_fok_market_order_fills_immediately() -> None:
    astore, pstore, acc, fetcher = _mk_env()
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.FOK,
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=fetcher,
        now=NOW,
    )
    assert r.status is OrderStatus.FILLED


def test_fok_limit_non_marketable_rejects() -> None:
    """FOK on non-marketable limit rejects same as DAY — correct semantics."""
    astore, pstore, acc, fetcher = _mk_env()
    r = submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=D("10"),
            order_type=OrderType.LIMIT,
            limit_price=D("90"),  # last=100, buy limit 90 is non-marketable
            time_in_force=TimeInForce.FOK,
        ),
        user_id="daisy",
        account_id=acc.account_id,
        account_store=astore,
        position_store=pstore,
        quote_fetcher=fetcher,
        now=NOW,
    )
    assert r.status is OrderStatus.REJECTED
    assert "non-marketable" in r.reason.lower()
