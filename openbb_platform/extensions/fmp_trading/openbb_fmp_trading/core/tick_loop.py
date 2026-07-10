"""Pure-function tick loop iterator: ``(session, tick_ts) -> list[TickEvent]``.

Stateless w.r.t. the session between ticks — the session's mutable state
changes only through ``IntradaySession.emit()`` side effects. Rationale:
makes the whole loop replay-safe per PRD §11 golden-test contract. If
run_tick could stash state in module globals or closures, a mid-session
crash would leave the replay unable to reconstruct the missing state
from the journal alone.

P2.3 scope: quote polling + one ``TickEvent`` per tick. No signals, no
plans, no orders, no fills — those wire in at P2.4.

The ``_fetch_batch_quote`` helper is a thin seam (a module-level function
rather than a method) specifically so unit tests can monkey-patch it
without spinning up a full OpenBB runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbb_fmp_trading.models.journal_events import TickEvent


def run_tick(session: Any, tick_ts: datetime) -> list[TickEvent]:
    """Execute one tick: poll batch quotes, journal one TickEvent, return it.

    Returns the emitted events so tests can assert directly on the shape
    of what was journaled without having to introspect the mock writer.
    """
    quotes = _fetch_batch_quote(session.plan.watchlist, provider="fmp_cached")
    tick_event = TickEvent(
        ts=tick_ts,
        session_id=session.session_id,
        payload={
            "watchlist_size": len(session.plan.watchlist),
            "quotes_fetched": len(quotes),
            "quotes": [_quote_to_dict(q) for q in quotes],
        },
    )
    session.emit(tick_event)
    return [tick_event]


def _fetch_batch_quote(symbols: list[str], provider: str) -> list[dict[str, Any]]:
    """Fetch batched quotes for the watchlist.

    Real impl calls ``obb.fmp_trading.quote_batch`` under the hood; kept
    thin + module-level so tests can monkeypatch ``core.tick_loop._fetch_batch_quote``
    without patching the whole ``openbb`` import chain.
    """
    from openbb import obb  # local import: avoid runtime cost when tests patch

    result = obb.fmp_trading.quote_batch(symbols=symbols, short=True, provider=provider)
    return [r.model_dump() for r in result.results]


def _quote_to_dict(q: dict[str, Any]) -> dict[str, Any]:
    """Coerce quote fields to JSON-safe primitives for the journal payload."""
    return {
        "symbol": q.get("symbol"),
        "price": str(q["price"]) if q.get("price") is not None else None,
        "ts": str(q["timestamp"]) if q.get("timestamp") is not None else None,
    }
