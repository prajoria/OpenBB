"""Round-trip: every model.model_dump_json() → model_validate_json() must equal the original."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from openbb_fmp_trading.models import (
    Alert,
    AlertEvent,
    AftermarketQuote,
    AftermarketTrade,
    BandwidthState,
    DailyConfig,
    DailyPlan,
    HealthReport,
    IndicatorValue,
    IntradayBar,
    JournalEvent,
    MarketSnapshot,
    MoverRow,
    PercentChangeSpec,
    PnLSnapshot,
    PriceThresholdSpec,
    Quote,
    ReportManifest,
    RiskConfig,
    RiskState,
    SessionResult,
    SessionStatus,
    TickData,
    TradeDecision,
    VolumeSpikeSpec,
)

_NOW = datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc)


def _samples():
    """Yield (name, instance) for every model under test."""
    risk = RiskConfig()
    yield "RiskConfig", risk
    yield "DailyConfig", DailyConfig(
        starting_equity=Decimal("100000"), default_risk=risk
    )
    yield "DailyPlan", DailyPlan(
        as_of=_NOW, date=date(2026, 7, 6), watchlist=["AAPL", "MSFT"],
        preset="intraday_momentum", alerts=[], session_risk=risk,
        thesis="test", agent_backend="none",
    )
    yield "MoverRow", MoverRow(
        symbol="AAPL", type="gainer", name="Apple Inc.", price=Decimal("180.00"),
        change=Decimal("2.50"), change_pct=1.4, volume=50_000_000,
    )
    yield "MarketSnapshot", MarketSnapshot(
        as_of=_NOW, movers=[], sentiment_ratio=1.2, top_gainer=None, top_loser=None,
    )
    yield "IntradayBar", IntradayBar(
        symbol="AAPL", interval="5min", ts=_NOW,
        open=Decimal("180"), high=Decimal("181"), low=Decimal("179.5"),
        close=Decimal("180.75"), volume=1_000_000,
    )
    yield "Quote", Quote(
        symbol="AAPL", price=Decimal("180.75"), change=Decimal("0.75"),
        change_pct=0.42, volume=50_000_000, timestamp=_NOW,
    )
    yield "AftermarketQuote", AftermarketQuote(
        symbol="AAPL", price=Decimal("181"), bid=Decimal("180.95"),
        ask=Decimal("181.05"), bid_size=100, ask_size=200, volume=10_000, timestamp=_NOW,
    )
    yield "AftermarketTrade", AftermarketTrade(
        symbol="AAPL", price=Decimal("181"), size=100, timestamp=_NOW,
    )
    yield "SessionStatus", SessionStatus(
        exchange="NASDAQ", is_market_open=True, is_pre_market=False,
        is_after_market=False, is_early_close_day=False, next_open=_NOW, next_close=_NOW,
    )
    yield "IndicatorValue", IndicatorValue(
        symbol="AAPL", indicator="RSI", ts=_NOW, value=55.2,
        period_length=14, timeframe="5min",
    )
    for spec in (
        PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")),
        PercentChangeSpec(symbol="AAPL", threshold_pct=5.0, window="session"),
        VolumeSpikeSpec(symbol="AAPL", ratio_vs_avg=3.0),
    ):
        yield f"AlertSpec::{spec.kind}", spec
    yield "Alert", Alert(
        id="a1", spec=PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")),
        created_at=_NOW,
    )
    yield "AlertEvent", AlertEvent(
        alert_id="a1", ts=_NOW, symbol="AAPL", condition="price > 180", context={"p": "180.5"},
    )
    yield "TickData", TickData(ts=_NOW, quotes={}, bars_recent={},
        session_status=SessionStatus(
            exchange="NASDAQ", is_market_open=True, is_pre_market=False,
            is_after_market=False, is_early_close_day=False, next_open=_NOW, next_close=_NOW,
        ))
    yield "PnLSnapshot", PnLSnapshot(
        ts=_NOW, realized_pnl=Decimal("100"), unrealized_pnl=Decimal("50"),
        day_pnl=Decimal("150"), day_dd_pct=0.0, positions_open=0, positions_closed=0,
    )
    yield "BandwidthState", BandwidthState(
        month_used_bytes=1_000_000, month_budget_bytes=50 * 1024**3,
        month_used_pct=0.002, mode="normal", session_used_bytes=100_000,
    )
    yield "RiskState", RiskState(
        ts=_NOW, gates_active=[], gates_tripped_today=[], cooldowns={},
        flat_by_close_window_open=False, day_dd_pct=0.0,
        open_position_count=0, max_open_positions=5,
    )
    yield "JournalEvent", JournalEvent(
        ts=_NOW, session_id="s1", event_type="tick", payload={"n": 1},
    )
    yield "TradeDecision::approved", TradeDecision(verdict="APPROVED", plan={})
    yield "TradeDecision::rejected", TradeDecision(
        verdict="REJECTED", reason="in cooldown", reason_code="G4",
        gate="per_symbol_cooldown", plan={},
    )
    yield "SessionResult", SessionResult(
        session_id="s1", date=date(2026, 7, 6), exchange="NASDAQ",
        started_at=_NOW, ended_at=_NOW, exit_code=0,
        daily_plan=DailyPlan(
            as_of=_NOW, date=date(2026, 7, 6), watchlist=["AAPL"],
            preset="intraday_momentum", alerts=[], session_risk=risk,
            thesis="t", agent_backend="none",
        ),
        final_pnl=PnLSnapshot(
            ts=_NOW, realized_pnl=Decimal("0"), unrealized_pnl=Decimal("0"),
            day_pnl=Decimal("0"), day_dd_pct=0.0,
            positions_open=0, positions_closed=0,
        ),
        final_bandwidth=BandwidthState(
            month_used_bytes=0, month_budget_bytes=1, month_used_pct=0.0,
            mode="normal", session_used_bytes=0,
        ),
        total_ticks=0, total_signals=0, total_orders=0, total_fills=0,
        total_vetoes=0, total_alerts_fired=0, flat_at_close=True,
        journal_path="/tmp/j.ndjson",
    )
    yield "HealthReport", HealthReport(
        ts=_NOW, fmp_credentials_ok=True, mysql_cache_ok=True,
        exchange_calendars_ok=True, techtrade_version="0.1.0", techtrade_ok=True,
        agent_extra_installed=False, xlsxwriter_extra_installed=False,
        validation_extra_installed=False, bandwidth_remaining_pct=95.0,
        warnings=[], errors=[],
    )
    yield "ReportManifest", ReportManifest(
        session_id="s1", md_path=None, xlsx_path=None, json_path=None,
        included_agent_narrative=False,
    )


@pytest.mark.parametrize(
    "name,instance", list(_samples()),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_roundtrip(name, instance):
    payload = instance.model_dump_json()
    revived = type(instance).model_validate_json(payload)
    assert revived == instance
