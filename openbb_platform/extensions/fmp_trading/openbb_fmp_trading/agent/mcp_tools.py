"""Concrete read-only handlers for the Daytrade MCP surface."""

# OpenBB and journal dependencies stay lazy so core extension import is cheap.
# pylint: disable=import-outside-toplevel

from typing import Any


def quote_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """Return normalized cached quotes for the requested symbols."""
    from openbb import obb

    result = obb.equity.quote(
        symbol=",".join(symbols),
        provider="fmp_cached",
    )
    return [item.model_dump(mode="json") for item in result.results]


def market_movers(direction: str, limit: int = 20) -> Any:
    """Return cached market movers through the existing OpenBB command."""
    from openbb import obb

    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    command = {
        "gainers": obb.equity.discovery.gainers,
        "losers": obb.equity.discovery.losers,
        "actives": obb.equity.discovery.active,
    }[direction]
    result = command(provider="fmp_cached")
    return [item.model_dump(mode="json") for item in list(result.results)[:limit]]


def company_news(symbol: str, limit: int = 10) -> Any:
    """Return cached company news through the existing OpenBB command."""
    from openbb import obb

    return obb.news.company(
        symbol=symbol,
        limit=limit,
        provider="fmp_cached",
    )


def session_status() -> Any:
    """Return current NASDAQ status from the installed exchange calendar."""
    from datetime import datetime, timezone

    import exchange_calendars as xcals
    import pandas as pd

    calendar = xcals.get_calendar("XNAS")
    now = pd.Timestamp(datetime.now(timezone.utc))
    is_open = calendar.is_open_on_minute(now, ignore_breaks=True)
    session = calendar.minute_to_session(now, direction="next")
    close = calendar.session_close(session)
    return {
        "exchange": "NASDAQ",
        "is_market_open": bool(is_open),
        "session": session.isoformat(),
        "next_close": close.isoformat(),
    }


def journal_summary(session_id: str) -> dict[str, Any]:
    """Return bounded aggregate metrics for one traversal-safe session ID."""
    from openbb_fmp_trading.reporting.journal_reader import (
        compute_metrics_from_events,
        read_session_events,
    )

    metrics = compute_metrics_from_events(read_session_events(session_id))
    return metrics.model_dump(mode="json")


def fills_for_session(session_id: str) -> list[dict[str, Any]]:
    """Return fill events for one traversal-safe session ID."""
    from openbb_fmp_trading.reporting.journal_reader import read_session_events

    return [
        event.model_dump(mode="json")
        for event in read_session_events(session_id)
        if getattr(event, "event_type", None) == "fill"
    ]


__all__ = [
    "company_news",
    "fills_for_session",
    "journal_summary",
    "market_movers",
    "quote_batch",
    "session_status",
]
