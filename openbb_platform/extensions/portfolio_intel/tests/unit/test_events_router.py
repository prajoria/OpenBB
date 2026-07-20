"""Unit tests for /portfolio_intel/events route (#542).

All offline — provider fetchers patched at the route seam. One
@pytest.mark.integration smoke against live fmp_cached.

Design: docs/superpowers/specs/2026-07-19-events-route-design.md
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from openbb_portfolio_intel.models import (
    CalendarEventItem,
    EventTimelineResult,
)
from openbb_portfolio_intel.routers.events_router import timeline

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _mk_row(symbol: str, event_date: date, extra: dict | None = None) -> MagicMock:
    """Row shaped like an OpenBB calendar response entry."""
    row = MagicMock()
    row.symbol = symbol
    row.date = event_date
    d = {"symbol": symbol, "date": event_date}
    if extra:
        d.update(extra)
    row.model_dump.return_value = d
    return row


def _mk_response(rows: list[MagicMock]) -> MagicMock:
    resp = MagicMock()
    resp.results = rows
    return resp


def _fake_provider(feeds: dict[str, list[MagicMock]]):
    """Build a fake dispatcher: (endpoint_name) -> response."""

    def _dispatch(kind: str, **_kwargs):
        return _mk_response(feeds.get(kind, []))

    return _dispatch


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_timeline_happy_path_merges_all_event_types() -> None:
    """2-symbol basket + 4 event feeds → merged chronological timeline."""
    today = date(2026, 8, 1)
    feeds = {
        "earnings": [
            _mk_row("AAPL", today + timedelta(days=5), {"eps": 1.5}),
        ],
        "dividend": [
            _mk_row("MSFT", today + timedelta(days=10), {"amount": 0.75}),
        ],
        "splits": [
            _mk_row("AAPL", today + timedelta(days=20), {"ratio": "2:1"}),
        ],
        "ipo": [],
    }
    dispatcher = _fake_provider(feeds)

    with patch(
        "openbb_portfolio_intel.routers.events_router._fetch_calendar",
        side_effect=dispatcher,
    ):
        obj = timeline(
            basket=[
                {"symbol": "AAPL", "weight": Decimal("0.5")},
                {"symbol": "MSFT", "weight": Decimal("0.5")},
            ],
            days_ahead=30,
            provider="fmp_cached",
        )
    res = obj.results
    assert isinstance(res, EventTimelineResult)
    assert len(res.timeline) == 3  # 1 earnings + 1 dividend + 1 split
    # Chronological order
    dates = [item.date for item in res.timeline]
    assert dates == sorted(dates)
    # by_symbol grouping
    assert set(res.by_symbol.keys()) == {"AAPL", "MSFT"}
    assert len(res.by_symbol["AAPL"]) == 2  # earnings + split
    assert len(res.by_symbol["MSFT"]) == 1  # dividend


def test_timeline_portfolio_scoped_filter_drops_out_of_basket() -> None:
    """Event for a non-basket symbol must be filtered out."""
    today = date(2026, 8, 1)
    feeds = {
        "earnings": [
            _mk_row("AAPL", today + timedelta(days=5)),
            _mk_row("TSLA", today + timedelta(days=6)),  # not in basket
        ],
        "dividend": [],
        "splits": [],
        "ipo": [],
    }
    dispatcher = _fake_provider(feeds)
    with patch(
        "openbb_portfolio_intel.routers.events_router._fetch_calendar",
        side_effect=dispatcher,
    ):
        obj = timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=30,
            provider="fmp_cached",
        )
    res = obj.results
    assert len(res.timeline) == 1
    assert res.timeline[0].symbol == "AAPL"
    assert "TSLA" not in res.by_symbol


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_timeline_empty_basket_raises() -> None:
    """A portfolio-intel route without symbols isn't sensible."""
    with pytest.raises(ValueError, match=r"empty|at least one"):
        timeline(basket=[], days_ahead=30, provider="fmp_cached")


def test_timeline_negative_days_ahead_raises() -> None:
    """Negative or zero days_ahead → ValueError."""
    with pytest.raises(ValueError, match=r"days_ahead"):
        timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=0,
            provider="fmp_cached",
        )
    with pytest.raises(ValueError, match=r"days_ahead"):
        timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=-5,
            provider="fmp_cached",
        )


# ---------------------------------------------------------------------------
# Failure mode
# ---------------------------------------------------------------------------


def test_timeline_provider_failure_per_type_degrades_partial_result() -> None:
    """A fetch failure for one event type → warning + partial timeline."""
    today = date(2026, 8, 1)

    def _dispatch(kind: str, **_kwargs):
        if kind == "earnings":
            raise RuntimeError("simulated provider outage")
        if kind == "dividend":
            return _mk_response([_mk_row("AAPL", today + timedelta(days=10))])
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.events_router._fetch_calendar",
        side_effect=_dispatch,
    ):
        obj = timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=30,
            provider="fmp_cached",
        )
    res = obj.results
    # Dividend still landed
    assert len(res.timeline) == 1
    assert res.timeline[0].event_type == "dividend"
    # Earnings failure warned
    assert any("earnings" in w.lower() for w in res.warnings)


# ---------------------------------------------------------------------------
# Determinism + envelope shape
# ---------------------------------------------------------------------------


def test_timeline_response_envelope_is_bare_obbject() -> None:
    """OBBject envelope with .results = EventTimelineResult, no double-wrap."""
    with patch(
        "openbb_portfolio_intel.routers.events_router._fetch_calendar",
        return_value=_mk_response([]),
    ):
        obj = timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=7,
            provider="fmp_cached",
        )
    assert hasattr(obj, "results")
    assert isinstance(obj.results, EventTimelineResult)
    assert not hasattr(obj.results, "results")


def test_timeline_determinism_same_input_same_output() -> None:
    """Deterministic — same inputs → same outputs."""
    today = date(2026, 8, 1)

    def _dispatch(kind: str, **_kwargs):
        if kind == "earnings":
            return _mk_response([_mk_row("AAPL", today + timedelta(days=3))])
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.events_router._fetch_calendar",
        side_effect=_dispatch,
    ):
        r1 = timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=30,
            provider="fmp_cached",
        ).results
        r2 = timeline(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            days_ahead=30,
            provider="fmp_cached",
        ).results
    assert len(r1.timeline) == len(r2.timeline)
    assert [(e.symbol, e.date, e.event_type) for e in r1.timeline] == [
        (e.symbol, e.date, e.event_type) for e in r2.timeline
    ]


def test_calendar_event_item_serializes_date_as_string() -> None:
    """Date field must be a JSON-friendly str, not a datetime.date."""
    item = CalendarEventItem(
        symbol="AAPL",
        date="2026-08-01",
        event_type="earnings",
        source="fmp_cached",
    )
    dumped = item.model_dump()
    assert isinstance(dumped["date"], str)


# ---------------------------------------------------------------------------
# Integration smoke
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_events_timeline_spy_via_obb() -> None:
    """End-to-end live: SPY basket via real fmp_cached calendar endpoints."""
    from openbb import obb

    obj = obb.portfolio_intel.events.timeline(
        basket=[{"symbol": "SPY", "weight": 1.0}],
        days_ahead=90,
        provider="fmp_cached",
    )
    res = obj.results
    # SPY itself is an ETF; dividend calendar may or may not have entries
    # — smoke test just confirms the route runs without raising.
    assert isinstance(res.timeline, list)
    assert isinstance(res.by_symbol, dict)
