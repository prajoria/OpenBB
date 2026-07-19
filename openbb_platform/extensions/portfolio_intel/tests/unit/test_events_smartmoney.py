"""Unit tests for events_smartmoney (#537, #538)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from openbb_portfolio_intel.analytics.events_smartmoney import (
    CalendarEvent,
    EventType,
    SmartMoneyScore,
    SmartMoneySignal,
    SmartMoneySource,
    aggregate_smart_money,
    events_by_symbol,
    merge_event_calendars,
    top_conviction,
)

# ---------------------------------------------------------------------------
# Event Calendar (#537)
# ---------------------------------------------------------------------------


def _ev(
    sym: str, y: int, m: int, d: int, t: EventType, src: str = "fmp_cached"
) -> CalendarEvent:
    """Terser fixture builder."""
    return CalendarEvent(symbol=sym, date=date(y, m, d), event_type=t, source=src)


def test_merge_scopes_to_portfolio_symbols() -> None:
    """Events for symbols not in the portfolio are dropped."""
    feed_a = [_ev("AAPL", 2026, 7, 25, EventType.EARNINGS)]
    feed_b = [_ev("TSLA", 2026, 7, 26, EventType.EARNINGS)]  # not in portfolio
    result = merge_event_calendars({"AAPL", "MSFT"}, feed_a, feed_b)
    assert len(result) == 1
    assert result[0].symbol == "AAPL"


def test_merge_deduplicates_by_symbol_date_type() -> None:
    """Same (symbol, date, type) from two feeds → first-seen wins."""
    fmp = _ev("AAPL", 2026, 7, 25, EventType.EARNINGS, src="fmp_cached")
    sec = _ev("AAPL", 2026, 7, 25, EventType.EARNINGS, src="sec")
    result = merge_event_calendars({"AAPL"}, [fmp], [sec])
    assert len(result) == 1
    assert result[0].source == "fmp_cached"  # first feed wins


def test_merge_returns_chronological_order() -> None:
    """Merged timeline sorted by date, then symbol, then type."""
    events = [
        _ev("MSFT", 2026, 8, 1, EventType.EARNINGS),
        _ev("AAPL", 2026, 7, 25, EventType.EARNINGS),
        _ev("AAPL", 2026, 7, 25, EventType.DIVIDEND),
        _ev("GOOGL", 2026, 7, 30, EventType.SPLIT),
    ]
    result = merge_event_calendars({"AAPL", "MSFT", "GOOGL"}, events)
    dates_symbols = [(e.date.isoformat(), e.symbol, e.event_type.value) for e in result]
    assert dates_symbols == [
        ("2026-07-25", "AAPL", "dividend"),
        ("2026-07-25", "AAPL", "earnings"),
        ("2026-07-30", "GOOGL", "split"),
        ("2026-08-01", "MSFT", "earnings"),
    ]


def test_events_by_symbol_groups_correctly() -> None:
    """Grouper produces per-symbol lists preserving order."""
    events = [
        _ev("AAPL", 2026, 7, 25, EventType.EARNINGS),
        _ev("AAPL", 2026, 8, 10, EventType.DIVIDEND),
        _ev("MSFT", 2026, 8, 1, EventType.EARNINGS),
    ]
    grouped = events_by_symbol(events)
    assert set(grouped.keys()) == {"AAPL", "MSFT"}
    assert len(grouped["AAPL"]) == 2
    assert len(grouped["MSFT"]) == 1


# ---------------------------------------------------------------------------
# Smart-Money Aggregator (#538)
# ---------------------------------------------------------------------------


def _sm(
    sym: str, src: SmartMoneySource, direction: int, weight: str
) -> SmartMoneySignal:
    """Terser fixture builder."""
    return SmartMoneySignal(
        symbol=sym, source=src, direction=direction, weight=Decimal(weight)
    )


def test_aggregate_sums_directional_weights_per_symbol() -> None:
    """Two insider buys + one 13F sell → net composite reflects both."""
    signals = [
        _sm("AAPL", SmartMoneySource.INSIDER, +1, "1000"),  # $1000 insider buy
        _sm("AAPL", SmartMoneySource.INSIDER, +1, "500"),  # $500 insider buy
        _sm("AAPL", SmartMoneySource.FORM_13F, -1, "800"),  # $800 13F sell
    ]
    scores = aggregate_smart_money(signals)
    assert "AAPL" in scores
    # +1000 + 500 - 800 = +700 net.
    assert scores["AAPL"].composite == Decimal("700")
    assert scores["AAPL"].signal_count == 3
    # By source: insider = +1500, 13F = -800.
    assert scores["AAPL"].by_source[SmartMoneySource.INSIDER] == Decimal("1500")
    assert scores["AAPL"].by_source[SmartMoneySource.FORM_13F] == Decimal("-800")


def test_aggregate_scopes_to_portfolio_symbols() -> None:
    """portfolio_symbols filter drops non-held tickers."""
    signals = [
        _sm("AAPL", SmartMoneySource.INSIDER, +1, "100"),
        _sm("TSLA", SmartMoneySource.INSIDER, +1, "500"),  # not held
    ]
    scores = aggregate_smart_money(signals, portfolio_symbols={"AAPL", "MSFT"})
    assert set(scores.keys()) == {"AAPL"}


def test_aggregate_returns_empty_for_no_signals() -> None:
    """Empty input → empty output; no crashes."""
    assert aggregate_smart_money([]) == {}


def test_zero_direction_still_counts_as_a_signal() -> None:
    """A neutral disclosure (direction=0) increments count but contributes 0."""
    signals = [_sm("AAPL", SmartMoneySource.SENATE, 0, "1000")]
    scores = aggregate_smart_money(signals)
    assert scores["AAPL"].composite == Decimal("0")
    assert scores["AAPL"].signal_count == 1


def test_top_conviction_absolute_ranks_by_magnitude() -> None:
    """|composite| ordering — most-conviction-either-way first."""
    scores = {
        "AAPL": SmartMoneyScore("AAPL", composite=Decimal("100")),
        "MSFT": SmartMoneyScore("MSFT", composite=Decimal("-500")),  # bigger magnitude
        "GOOGL": SmartMoneyScore("GOOGL", composite=Decimal("50")),
    }
    result = top_conviction(scores, n=2, absolute=True)
    assert [s.symbol for s in result] == ["MSFT", "AAPL"]


def test_top_conviction_signed_ranks_bullish_first() -> None:
    """When absolute=False, biggest positive first."""
    scores = {
        "AAPL": SmartMoneyScore("AAPL", composite=Decimal("100")),
        "MSFT": SmartMoneyScore("MSFT", composite=Decimal("-500")),
        "GOOGL": SmartMoneyScore("GOOGL", composite=Decimal("300")),
    }
    result = top_conviction(scores, n=2, absolute=False)
    assert [s.symbol for s in result] == ["GOOGL", "AAPL"]


def test_top_conviction_respects_n_limit() -> None:
    """n=1 returns exactly one item."""
    scores = {
        "AAPL": SmartMoneyScore("AAPL", composite=Decimal("1")),
        "MSFT": SmartMoneyScore("MSFT", composite=Decimal("2")),
    }
    assert len(top_conviction(scores, n=1)) == 1
