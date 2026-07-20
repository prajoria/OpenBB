"""Unit tests for #572-#574 P3 app routes.

Coverage:
- #572 /news/timeline severity filtering + sort order + fetch-failure warnings
- #572 /sentiment/rollup weighting, coverage_pct threshold warning, empty basket
- #573 /backtest/run stub payload + live handoff seam
- #574 /paper/alerts ledger mapping + low-BP + GTC-expiring triggers

All routes are called with dependency-injected seams so we never touch
``obb.*`` or a real ledger store from the unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from openbb_portfolio_intel.routers import (
    backtest_router,
    news_sentiment_router,
    paper_alerts_router,
)

D = Decimal
NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# #572 news timeline
# ---------------------------------------------------------------------------


class _StubResp:
    def __init__(self, rows):
        self.results = rows


def _news_row(title="Widget shipped", when=None, published_key="date", url=""):
    ns = SimpleNamespace()
    setattr(ns, published_key, when or NOW - timedelta(hours=1))
    ns.title = title
    ns.url = url
    return ns


def _filing_row(form_type="8-K", when=None):
    return SimpleNamespace(
        form_type=form_type, filing_date=when or NOW - timedelta(hours=2), url=""
    )


def test_news_timeline_filters_by_severity_info_returns_all(monkeypatch) -> None:
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_news_company",
        lambda s, provider: _StubResp([_news_row(title=f"{s} beat")]),
    )
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_filings",
        lambda s, provider: _StubResp([_filing_row()]),
    )
    result = news_sentiment_router.timeline(
        basket=[{"symbol": "AAPL", "weight": 1.0}], severity="info", days_back=7
    ).results
    # one news + one 8-K
    assert len(result.items) == 2


def test_news_timeline_severity_warning_drops_info_items(monkeypatch) -> None:
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_news_company",
        lambda s, provider: _StubResp([_news_row(title="just news")]),
    )
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_filings",
        lambda s, provider: _StubResp([_filing_row()]),
    )
    result = news_sentiment_router.timeline(
        basket=[{"symbol": "AAPL", "weight": 1.0}], severity="warning"
    ).results
    # info news dropped, only 8-K warning survives
    assert len(result.items) == 1
    assert result.items[0].source == "8k"


def test_news_timeline_fetch_failure_becomes_warning(monkeypatch) -> None:
    def _boom(_symbol, provider=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(news_sentiment_router, "_fetch_news_company", _boom)
    monkeypatch.setattr(
        news_sentiment_router, "_fetch_filings", lambda s, provider: _StubResp([])
    )
    result = news_sentiment_router.timeline(
        basket=[{"symbol": "AAPL", "weight": 1.0}]
    ).results
    assert any("news fetch failed" in w for w in result.warnings)


def test_news_timeline_sort_newest_first(monkeypatch) -> None:
    older = _news_row(title="old", when=NOW - timedelta(hours=5))
    newer = _news_row(title="new", when=NOW - timedelta(minutes=5))
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_news_company",
        lambda s, provider: _StubResp([older, newer]),
    )
    monkeypatch.setattr(
        news_sentiment_router, "_fetch_filings", lambda s, provider: _StubResp([])
    )
    result = news_sentiment_router.timeline(
        basket=[{"symbol": "AAPL", "weight": 1.0}]
    ).results
    titles = [i.title for i in result.items]
    assert titles == ["new", "old"]


# ---------------------------------------------------------------------------
# #572 sentiment rollup
# ---------------------------------------------------------------------------


def _stub_price(px):
    return _StubResp([SimpleNamespace(last_price=px)])


def _stub_pt(target):
    return _StubResp([SimpleNamespace(price_target=target)])


def _stub_consensus(rating, count):
    return _StubResp(
        [SimpleNamespace(consensus_rating=rating, analyst_count=count)]
    )


def test_sentiment_rollup_computes_weighted_rating(monkeypatch) -> None:
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_quote",
        lambda s, provider: _stub_price(100),
    )
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_price_target",
        lambda s, provider: _stub_pt(115),
    )
    monkeypatch.setattr(
        news_sentiment_router,
        "_fetch_consensus",
        lambda s, provider: _stub_consensus(4.0, 20),
    )
    result = news_sentiment_router.rollup(
        basket=[
            {"symbol": "AAPL", "weight": 0.5},
            {"symbol": "MSFT", "weight": 0.5},
        ]
    ).results
    assert result.rating == pytest.approx(4.0)
    assert result.upside_pct == pytest.approx(0.15)
    assert result.coverage_pct == pytest.approx(1.0)


def test_sentiment_rollup_low_coverage_emits_warning(monkeypatch) -> None:
    """Any symbol that provider fetch fails on drops out of coverage_pct."""

    def _quote(sym, provider=None):
        return _stub_price(100)

    def _pt(sym, provider=None):
        return _stub_pt(110)

    def _cons(sym, provider=None):
        if sym == "AAPL":
            return _stub_consensus(4.0, 20)
        return _StubResp([])  # MSFT: no consensus

    monkeypatch.setattr(news_sentiment_router, "_fetch_quote", _quote)
    monkeypatch.setattr(news_sentiment_router, "_fetch_price_target", _pt)
    monkeypatch.setattr(news_sentiment_router, "_fetch_consensus", _cons)
    result = news_sentiment_router.rollup(
        basket=[
            {"symbol": "AAPL", "weight": 0.3},
            {"symbol": "MSFT", "weight": 0.7},
        ]
    ).results
    assert result.coverage_pct == pytest.approx(0.3)
    assert any("thin" in w for w in result.warnings)


def test_sentiment_rollup_rejects_invalid_weighting() -> None:
    with pytest.raises(ValueError, match="weighting"):
        news_sentiment_router.rollup(
            basket=[{"symbol": "AAPL", "weight": 1.0}], weighting="banana"
        )


# ---------------------------------------------------------------------------
# #573 backtest handoff
# ---------------------------------------------------------------------------


def test_backtest_stub_payload_is_deterministic(monkeypatch) -> None:
    """live=False always returns mode=stub even when endpoint is available."""
    monkeypatch.setattr(
        backtest_router, "_resolve_backtest_endpoint", lambda: lambda **kw: None
    )
    r1 = backtest_router.run(
        basket=[
            {"symbol": "AAPL", "weight": 0.5},
            {"symbol": "MSFT", "weight": 0.5},
        ],
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        live=False,
    ).results
    r2 = backtest_router.run(
        basket=[
            {"symbol": "AAPL", "weight": 0.5},
            {"symbol": "MSFT", "weight": 0.5},
        ],
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        live=False,
    ).results
    assert r1.mode == "stub"
    assert r2.mode == "stub"
    assert r1.payload == r2.payload  # deterministic


def test_backtest_live_falls_back_to_stub_when_endpoint_missing(monkeypatch) -> None:
    monkeypatch.setattr(backtest_router, "_resolve_backtest_endpoint", lambda: None)
    result = backtest_router.run(
        basket=[{"symbol": "AAPL", "weight": 1.0}],
        start=date(2025, 1, 1),
        end=date(2025, 6, 30),
        live=True,
    ).results
    assert result.mode == "stub"
    assert any("not installed" in w for w in result.warnings)


def test_backtest_live_hands_off_when_endpoint_present(monkeypatch) -> None:
    calls = {}

    def _endpoint(**kw):
        calls.update(kw)
        return SimpleNamespace(results=SimpleNamespace(model_dump=lambda: {"sharpe": 1.2}))

    monkeypatch.setattr(backtest_router, "_resolve_backtest_endpoint", lambda: _endpoint)
    result = backtest_router.run(
        basket=[{"symbol": "AAPL", "weight": 1.0}],
        start=date(2025, 1, 1),
        end=date(2025, 6, 30),
        live=True,
    ).results
    assert result.mode == "live"
    assert result.payload == {"sharpe": 1.2}
    assert calls["weights"] == {"AAPL": 1.0}


def test_backtest_live_handoff_exception_downgrades_to_stub(monkeypatch) -> None:
    def _endpoint(**kw):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(backtest_router, "_resolve_backtest_endpoint", lambda: _endpoint)
    result = backtest_router.run(
        basket=[{"symbol": "AAPL", "weight": 1.0}],
        start=date(2025, 1, 1),
        end=date(2025, 6, 30),
        live=True,
    ).results
    assert result.mode == "stub"
    assert any("failed" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# #574 paper alerts
# ---------------------------------------------------------------------------


@dataclass
class _StubLedgerEntry:
    entry_type: str
    symbol: str
    quantity: Decimal
    price: Decimal
    at: datetime


@dataclass
class _StubLedgerStore:
    entries: list[_StubLedgerEntry]

    def list_for_account(self, *, user_id, account_id):
        return list(self.entries)


@dataclass
class _StubOpenOrder:
    order_id: str
    symbol: str
    time_in_force: str
    expires_at: datetime


@dataclass
class _StubAccount:
    account_id: str
    cash_balance: Decimal
    starting_cash: Decimal
    open_orders: list = None


@dataclass
class _StubAccountStore:
    account: _StubAccount

    def get(self, *, user_id, account_id):
        return self.account


def test_paper_alerts_fills_produce_info_alerts(monkeypatch) -> None:
    # Anchor to real "now" (route uses datetime.now internally) so the
    # fill lands inside the lookback window.
    now = datetime.now(tz=timezone.utc)
    ledger = _StubLedgerStore(
        entries=[
            _StubLedgerEntry(
                entry_type="TRADE",
                symbol="AAPL",
                quantity=D("10"),
                price=D("100"),
                at=now - timedelta(minutes=5),
            )
        ]
    )
    acct = _StubAccount(
        account_id="a1", cash_balance=D("50000"), starting_cash=D("100000")
    )
    monkeypatch.setattr(
        paper_alerts_router, "_default_ledger_store", lambda: ledger
    )
    monkeypatch.setattr(
        paper_alerts_router,
        "_default_account_store",
        lambda: _StubAccountStore(account=acct),
    )
    result = paper_alerts_router.alerts(
        user_id="daisy", account_id="a1", since_seconds=3600
    ).results
    fill_alerts = [a for a in result.alerts if "filled" in a.message.lower()]
    assert len(fill_alerts) == 1
    assert fill_alerts[0].severity == "info"


def test_paper_alerts_low_buying_power_fires_below_threshold(monkeypatch) -> None:
    ledger = _StubLedgerStore(entries=[])
    acct = _StubAccount(
        account_id="a1", cash_balance=D("5000"), starting_cash=D("100000")
    )
    monkeypatch.setattr(paper_alerts_router, "_default_ledger_store", lambda: ledger)
    monkeypatch.setattr(
        paper_alerts_router,
        "_default_account_store",
        lambda: _StubAccountStore(account=acct),
    )
    result = paper_alerts_router.alerts(
        user_id="daisy", account_id="a1", low_buying_power_pct=0.10
    ).results
    bp = [a for a in result.alerts if "Buying power low" in a.message]
    assert len(bp) == 1
    assert bp[0].severity == "warning"


def test_paper_alerts_low_buying_power_silent_above_threshold(monkeypatch) -> None:
    ledger = _StubLedgerStore(entries=[])
    acct = _StubAccount(
        account_id="a1", cash_balance=D("60000"), starting_cash=D("100000")
    )
    monkeypatch.setattr(paper_alerts_router, "_default_ledger_store", lambda: ledger)
    monkeypatch.setattr(
        paper_alerts_router,
        "_default_account_store",
        lambda: _StubAccountStore(account=acct),
    )
    result = paper_alerts_router.alerts(
        user_id="daisy", account_id="a1"
    ).results
    assert not any("Buying power" in a.message for a in result.alerts)


def test_paper_alerts_gtc_expiring_within_horizon(monkeypatch) -> None:
    now = datetime.now(tz=timezone.utc)
    orders = [
        _StubOpenOrder(
            order_id="o1",
            symbol="AAPL",
            time_in_force="gtc",
            expires_at=now + timedelta(days=2),
        ),
        _StubOpenOrder(
            order_id="o2",
            symbol="MSFT",
            time_in_force="gtc",
            expires_at=now + timedelta(days=30),
        ),
        _StubOpenOrder(
            order_id="o3",
            symbol="TSLA",
            time_in_force="day",
            expires_at=now + timedelta(days=1),
        ),
    ]
    ledger = _StubLedgerStore(entries=[])
    acct = _StubAccount(
        account_id="a1",
        cash_balance=D("60000"),
        starting_cash=D("100000"),
        open_orders=orders,
    )
    monkeypatch.setattr(paper_alerts_router, "_default_ledger_store", lambda: ledger)
    monkeypatch.setattr(
        paper_alerts_router,
        "_default_account_store",
        lambda: _StubAccountStore(account=acct),
    )
    result = paper_alerts_router.alerts(
        user_id="daisy", account_id="a1", gtc_horizon_days=3
    ).results
    expiring = [a for a in result.alerts if "expires" in a.message]
    assert len(expiring) == 1
    assert expiring[0].symbol == "AAPL"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# (no shared helpers currently — each test constructs its own stubs)
