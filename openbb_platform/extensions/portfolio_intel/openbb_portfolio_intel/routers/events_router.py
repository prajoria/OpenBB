"""Events-calendar timeline route (#542).

One command:
- ``obb.portfolio_intel.events.timeline(basket, days_ahead, provider)``
  Fetches earnings + dividend + splits + ipo calendars from the
  provider for the next ``days_ahead`` days, filters to basket symbols,
  merges via ``analytics.events_smartmoney.merge_event_calendars``, and
  returns a chronological timeline + per-symbol grouping.

Composes:
- ``openbb_portfolio_intel.analytics.events_smartmoney`` for the merge
  + portfolio-scope + dedup logic (#537).
- Provider fetch via ``obb.equity.calendar.{earnings,dividend,splits,ipo}``.

Pattern-mirror of #541 (xray) + #528 (risk):
- Public models in ``openbb_portfolio_intel.models`` (top-level).
- Route input ``list[dict]`` basket, bare ``OBBject`` return.
- All lint pragmas pre-applied (module-level).

Design: ``docs/superpowers/specs/2026-07-19-events-route-design.md``.

Scope narrowed vs PRD §14 (documented):
- **Forward-looking only** (``days_ahead``, no ``days_back``).
- **fmp_cached provider only** (matches project rule).
- **4 event types only** (earnings/dividend/split/ipo). News + 8-K are
  P3 follow-ups.
- **Weight-agnostic** — ``basket`` weight field is ignored (events are
  per-symbol); shape kept identical to other routes for API consistency.
"""

# pylint: disable=unused-argument  # timeline() 'provider' param reserved for multi-provider follow-up
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_portfolio_intel.analytics.events_smartmoney import (
    CalendarEvent,
    EventType,
    events_by_symbol,
    merge_event_calendars,
)
from openbb_portfolio_intel.models import (
    BasketPosition,
    CalendarEventItem,
    EventTimelineResult,
)
from openbb_portfolio_intel.routers.xray_router import _validate_basket

logger = logging.getLogger(__name__)

router = Router(
    prefix="/events",
    description=(
        "Corporate-action + earnings calendar for basket symbols. Merges "
        "earnings / dividend / split / ipo feeds, filters to portfolio, "
        "returns a chronological timeline + per-symbol grouping."
    ),
)


# ---------------------------------------------------------------------------
# Collaborator seam (patched in unit tests; lazy in production)
# ---------------------------------------------------------------------------


_CALENDAR_ENDPOINTS: dict[str, tuple[str, EventType]] = {
    "earnings": ("earnings", EventType.EARNINGS),
    "dividend": ("dividend", EventType.DIVIDEND),
    "splits": ("splits", EventType.SPLIT),
    "ipo": ("ipo", EventType.IPO),
}


def _fetch_calendar(
    kind: str, *, start_date: date, end_date: date, provider: str | None = None
):
    """Fetch one calendar type via ``obb.equity.calendar.<kind>``.

    Seam: unit tests patch this to avoid ``obb`` import + network. In
    production it resolves ``obb.equity.calendar.<kind>`` and returns the
    OBBject response.
    """
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    endpoint_name, _ = _CALENDAR_ENDPOINTS[kind]
    endpoint = getattr(obb.equity.calendar, endpoint_name)
    return endpoint(start_date=start_date, end_date=end_date, provider=provider)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _positions_from_basket(basket: list[dict]) -> list[BasketPosition]:
    """Coerce basket dicts → BasketPosition and reject empty/negative."""
    positions = [
        BasketPosition(symbol=str(r["symbol"]), weight=Decimal(str(r["weight"])))
        for r in basket
    ]
    _validate_basket(positions)
    return positions


def _extract_rows(response) -> list:
    """Unwrap ``.results`` from an OBBject-like envelope."""
    return getattr(response, "results", response) or []


def _coerce_date(v: Any) -> date | None:
    """Best-effort coercion to ``datetime.date`` from provider row values."""
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v).date()
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v.date()
    return None


def _row_to_event(row: Any, event_type: EventType, source: str) -> CalendarEvent | None:
    """Convert one provider row to a ``CalendarEvent`` — or None if malformed."""
    symbol = getattr(row, "symbol", None)
    d = _coerce_date(getattr(row, "date", None))
    if not symbol or d is None:
        return None
    # Best-effort details payload (whatever the row exposes beyond symbol/date).
    details: dict = {}
    dump = getattr(row, "model_dump", None)
    if callable(dump):
        try:
            details = {k: v for k, v in dump().items() if k not in ("symbol", "date")}
        except Exception:  # noqa: BLE001
            details = {}
    return CalendarEvent(
        symbol=str(symbol).upper(),
        date=d,
        event_type=event_type,
        source=source,
        details=details,
    )


def _to_item(event: CalendarEvent) -> CalendarEventItem:
    """Convert internal CalendarEvent → response-model CalendarEventItem."""
    return CalendarEventItem(
        symbol=event.symbol,
        date=event.date.isoformat(),
        event_type=event.event_type.value,
        source=event.source,
        details=event.details,
    )


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Next 30 days of earnings/dividends/splits for a 2-symbol basket.",
            code=[
                "basket = [",
                '    {"symbol": "AAPL", "weight": 0.5},',
                '    {"symbol": "MSFT", "weight": 0.5},',
                "]",
                'r = obb.portfolio_intel.events.timeline(basket=basket, days_ahead=30, provider="fmp_cached")',
                "print(len(r.results.timeline), 'events')",
            ],
        ),
    ],
)
def timeline(
    basket: list[dict],
    days_ahead: int = 30,
    provider: str | None = None,
) -> OBBject:
    """Corporate-action + earnings calendar for basket symbols, next N days.

    Fetches ``earnings``, ``dividend``, ``splits``, ``ipo`` calendars
    from ``obb.equity.calendar.*`` for the next ``days_ahead`` days,
    filters to basket symbols, merges + dedups via
    :func:`openbb_portfolio_intel.analytics.events_smartmoney.merge_event_calendars`,
    and returns a chronological timeline plus per-symbol grouping.

    Weight-agnostic — ``basket`` weights are IGNORED; only ``symbol``
    is read. The dict shape is kept identical to /xray + /risk for API
    consistency.

    Per-event-type fetch failures are non-fatal — a warning is added to
    ``result.warnings`` and the timeline includes whatever other event
    types succeeded.

    Returns
    -------
    OBBject[:class:`~openbb_portfolio_intel.models.EventTimelineResult`]
        Bare ``OBBject`` at the signature level (see #541 phase-6 discovery);
        ``.results`` is always an ``EventTimelineResult``.

    Raises
    ------
    ValueError
        - Empty basket
        - ``days_ahead <= 0``
    """
    positions = _positions_from_basket(basket)
    if days_ahead <= 0:
        raise ValueError(
            f"days_ahead must be positive; got {days_ahead}. This route "
            "is forward-looking only (historical follow-up planned)."
        )

    portfolio_symbols = {p.symbol.upper() for p in positions}
    today = date.today()
    end = today + timedelta(days=days_ahead)

    warnings: list[str] = []
    feeds: list[list[CalendarEvent]] = []

    for kind, (_endpoint, event_type) in _CALENDAR_ENDPOINTS.items():
        try:
            response = _fetch_calendar(
                kind, start_date=today, end_date=end, provider=provider
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("events: %s calendar fetch failed: %s", kind, exc)
            warnings.append(
                f"{kind}: fetch raised ({type(exc).__name__}) — that "
                "event type omitted from timeline"
            )
            continue

        rows = _extract_rows(response)
        feed: list[CalendarEvent] = []
        for row in rows:
            event = _row_to_event(row, event_type, source=provider or "unknown")
            if event is not None:
                feed.append(event)
        feeds.append(feed)

    merged = merge_event_calendars(portfolio_symbols, *feeds)
    grouped = events_by_symbol(merged)

    timeline_items = [_to_item(e) for e in merged]
    by_symbol_items = {sym: [_to_item(e) for e in evs] for sym, evs in grouped.items()}

    return OBBject(
        results=EventTimelineResult(
            timeline=timeline_items,
            by_symbol=by_symbol_items,
            warnings=warnings,
        )
    )
