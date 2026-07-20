# Design — /portfolio_intel/events route (`openbb_portfolio_intel.routers.events_router`)

- **Date:** 2026-07-19
- **Issue:** [#542](https://github.com/prajoria/OpenBB/issues/542)
- **Parent epic:** #491
- **Branch:** `feat/pi-app/events-route-gh-542`
- **Base:** `portfolio` @ 34744c380 (post-#528)
- **Status:** Draft (pattern-mirror of #541/#528)

---

## 1. Purpose

Expose the event-calendar merge substrate (`analytics.events_smartmoney.merge_event_calendars` + `events_by_symbol`) as a route at `obb.portfolio_intel.events.timeline(basket, days_ahead)`. Unblocks Lane D's Event Calendar timeline widget (#531).

## 2. Scope

**In scope:**

- Sub-router at pre-reserved `openbb_portfolio_intel.routers.events_router`.
- **One command:** `obb.portfolio_intel.events.timeline(basket, days_ahead=30, provider=None)` → sorted chronological timeline (list) + per-symbol grouping (dict).
- Fetches from `obb.equity.calendar.earnings`, `.dividend`, `.splits`, `.ipo` for the basket's date range and portfolio symbols only. Non-basket symbols dropped in the merge step.
- Response model `EventTimelineResult` in `openbb_portfolio_intel.models` (top-level, per generator quirk).
- Route surface: `basket: list[dict]`, `days_ahead: int = 30`. Bare `OBBject` return.

**Out of scope (documented, deferred):**

- **News / press-release events** — belong on a separate `/events/news` route or a follow-up (P3 already tracks News).
- **8-K / SEC filings** — separate P3 issue.
- **Historical events (past N days)** — this cut is forward-looking only. `days_back` parameter deferred.
- **Custom event sources** — only fmp_cached provider fed. Follow-up will add multi-provider dispatch.
- **Basket weights ignored** — events are per-symbol, weight-agnostic. Empty basket still raises (a portfolio_intel route with no symbols isn't sensible).
- **No portfolio_basket saved-lookup** — inline basket only (mirror #541/#528).

## 3. Public API

New model in `openbb_portfolio_intel/models.py`:

```python
class CalendarEventItem(BaseModel):
    """One event in the merged timeline."""
    symbol: str
    date: str  # ISO YYYY-MM-DD (serializable; datetime.date can't cross the JSON boundary cleanly)
    event_type: str  # "earnings" | "dividend" | "split" | "ipo"
    source: str  # provider tag ("fmp_cached")
    details: dict = Field(default_factory=dict)


class EventTimelineResult(BaseModel):
    """Nested response for the /events/timeline route."""
    timeline: list[CalendarEventItem]                # chronological
    by_symbol: dict[str, list[CalendarEventItem]]    # grouped
    warnings: list[str] = Field(default_factory=list)
```

Route:

```python
@router.command(methods=["POST"], examples=[...])
def timeline(
    basket: list[dict],
    days_ahead: int = 30,
    provider: str | None = None,
) -> OBBject:
    """Corporate-action + earnings calendar for basket symbols, next N days."""
```

## 4. Design decisions

### 4.1 date serialized as ISO string, not `datetime.date`

Pydantic v2 handles `date` fields fine over the wire, but OpenBB's static-generator quirks around extension-local Pydantic types (see #541 phase-6) make it safer to keep the boundary simple. `str` is trivially JSON-serializable; the widget layer parses back to `Date` in JS/TS. Also avoids cross-timezone confusion.

### 4.2 Provider fetch pattern

For each `EventType`, one `obb.<endpoint>.<subroute>` call:
- `earnings`: `obb.equity.calendar.earnings(start_date=..., end_date=...)` filtered to basket symbols.
- `dividend`: `obb.equity.calendar.dividend(...)` — same.
- `splits`: `obb.equity.calendar.splits(...)`.
- `ipo`: `obb.equity.calendar.ipo(...)`.

Each per-call fetch is wrapped in try/except — a provider outage for one type shouldn't kill the whole route. Warnings collect per-type failures.

### 4.3 Portfolio-scoped filter

`merge_event_calendars` accepts `portfolio_symbols: set[str]` and drops non-matching events. So we can pull the entire market-wide calendar for the date range and the substrate filters. That's O(N_events + N_basket) — cheap.

### 4.4 Route surface — same `list[dict]` basket

`basket` isn't used for weights (events are per-symbol) but the shape is kept identical to `/xray`, `/risk` for API consistency. `weight` is ignored; only `symbol` is read. Documented in the docstring.

## 5. Testing plan

`openbb_platform/extensions/portfolio_intel/tests/unit/test_events_router.py`. ~8 tests + 1 integration.

1. Happy path — 2-symbol basket, 4 mocked event feeds → timeline chronological + by_symbol correct.
2. Portfolio-scoped filter — event for out-of-basket symbol is dropped.
3. Empty basket → ValueError.
4. Days ahead = 0 → ValueError (or accept 0 as "today only"? — pick a rule).
5. Provider fetch failure for one event type → warning + partial result.
6. Duplicate event across sources → deduplicated (merge_event_calendars honors first-source-wins).
7. Response envelope shape (bare `OBBject.results` = `EventTimelineResult`).
8. Determinism.

Integration smoke: `@pytest.mark.integration` fetches SPY's actual next-30-day calendar.

## 6. File layout

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/
│   ├── models.py                     # EXTEND — CalendarEventItem + EventTimelineResult
│   └── routers/
│       └── events_router.py          # NEW (~180 lines)
└── tests/
    └── unit/
        └── test_events_router.py     # NEW (~200 lines)
```

## 7. Verdict

Ship §3 as one PR. Pattern-mirror of #541/#528 — same lint pragmas pre-applied. Expect 1-2 CI iterations max.
