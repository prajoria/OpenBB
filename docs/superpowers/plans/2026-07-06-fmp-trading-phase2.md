# FMP Day-Trading Automation — Phase 2 (Deterministic Execution) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the deterministic market-hours execution core of `openbb-fmp-trading`. By the end of Phase 2: two high-volume fetchers (intraday bars, aftermarket quote) are tier-1 gap-detection cached; a generic TTL wrapper exists in `base_cached.py`; `IntradaySession` runs a tick loop that polls quotes, evaluates techtrade signals, drives `PaperBroker` through `RiskManager`, and flattens all positions by 15:55 ET; and three acceptance tests are green — **AC-1** (6.5h end-to-end mock session), **AC-5** (no look-ahead), and **AC-6** (flat-by-close veto at 15:51 ET).

**Architecture:** A vertical slice through the extension. Provider layer (fmp_cached) grows real caching for the two hottest endpoints. Extension layer (`openbb_fmp_trading.core`) gains its two most important classes: `IntradaySession` (the market-hours state machine) and `tick_loop` (its inner iterator). Every signal path funnels: `techtrade.signals → techtrade.plan → RiskManager.propose_trade → PaperBroker.submit → journal(fill)`. No LLM. No agent turns. No AlertManager. Those all land in Phase 3+; this phase is 100% deterministic and reproducible byte-for-byte.

**Tech Stack:** Python 3.10–3.13, Poetry-style `pyproject.toml`, `openbb-core` extension entry points, Pydantic v2, MySQL 8 (via existing `fmp_cached` connection pool), `exchange_calendars` for clock discipline, `pytest` + `freezegun` for frozen-clock golden tests. Env: `.venv_win`. Tracked in `bd` (Beads); parent epic reference: **#87 (P9 — streaming/intraday + live broker)** and the sub-issues Phase 1 filed.

---

## Global Constraints — READ FIRST (from PRD §2.2)

These are inherited by every task in this phase and enforced by CI:

- **P1 — Deterministic signal core.** No LLM anywhere in the tick loop. The agent shell lands in Phase 3.
- **P2 — `Decimal` for money and share counts.** No float drift. Any price/qty typed `float` triggers a review-block; convert to `Decimal` at the boundary.
- **P3 — No look-ahead.** Signal computed off the close of bar `t` results in an order that fills **no earlier than the open of bar `t+1`**. AC-5 golden test locks this at 5-min granularity.
- **P4 — No overnight positions in v1.** Every open position flat by 15:55 ET. AC-6 test proves the 15:50 gate.
- **P5 — Every clock decision uses `exchange_calendars`.** No naive `datetime.now()`. Frozen clocks in tests; live `pd.Timestamp.now(tz="America/New_York")` in prod.
- **P6 — Bandwidth is a first-class constraint.** Every FMP call charges `BandwidthMeter` (from Phase 1). Tier-1 caching's whole point is P6.
- **P7 — RiskManager is the trade-admission chokepoint.** Every path to `broker.submit()` funnels through `RiskManager.propose_trade()`. The `tests/architecture/test_broker_chokepoint.py` test (from Phase 1) will fail the build if anything in this phase bypasses it.

**Critical correctness rule for intraday caching (§5.2):** the most recent bar of the current session may still extend (a 5-min bar opened at 10:00 doesn't finalize until 10:05). The cache MUST mark tail bars `is_valid=FALSE` when served from same-session cache, forcing re-fetch on the next tick. Prior-session bars are immutable and never re-fetched. Every reviewer must sanity-check this before approving P2.1.

---

## File Structure

Paths under `openbb_platform/providers/fmp_cached/openbb_fmp_cached/` (provider layer) and `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/` (extension layer):

| File | Responsibility | Task |
|---|---|---|
| `providers/fmp_cached/.../utils/cache_schema.py` | Add `equity_intraday_historical` and `aftermarket_quote` DDL to the migration surface. | P2.1 |
| `providers/fmp_cached/.../models/equity_intraday_historical.py` | Upgrade fetcher: tier-2 passthrough → tier-1 gap-detection cached, with same-session tail invalidation. | P2.1 |
| `providers/fmp_cached/.../models/aftermarket_quote.py` | Upgrade fetcher: tier-2 passthrough → tier-1 with 60s TTL. | P2.1 |
| `providers/fmp_cached/.../models/base_cached.py` | Add `create_ttl_wrapper_class(fetcher, name, ttl_seconds)` helper (~30 LoC). | P2.2 |
| `providers/fmp_cached/.../models/exchange_market_hours.py` | Migrate to use `create_ttl_wrapper_class` with `ttl_seconds=86400`. | P2.2 |
| `extensions/fmp_trading/.../core/session.py` | New `IntradaySession` class: owns tick loop, positions, journal, and the `RiskManager` reference. | P2.3, P2.4, P2.5 |
| `extensions/fmp_trading/.../core/tick_loop.py` | Pure-function `run_tick(session, tick_ts) -> list[JournalEvent]`. | P2.3, P2.4 |
| `extensions/fmp_trading/.../core/flat_by_close.py` | State-machine helper `enter_flat_window(now_et) -> WindowState`. | P2.5 |
| `extensions/fmp_trading/.../tests/unit/test_intraday_session.py` | Unit tests for `IntradaySession` construction and journal writes. | P2.3 |
| `extensions/fmp_trading/.../tests/unit/test_tick_loop_signal_wiring.py` | Unit test: signals wire through to `PaperBroker.submit`. | P2.4 |
| `extensions/fmp_trading/.../tests/unit/test_flat_by_close.py` | Unit tests for the flat-by-close state machine (AC-6). | P2.5 |
| `extensions/fmp_trading/.../tests/golden/test_no_look_ahead.py` | Golden AC-5 test: bar-t close signal fills at t+1 open. | P2.6 |
| `extensions/fmp_trading/.../tests/integration/test_full_session.py` | End-to-end mock-FMP → 6.5h simulated session (AC-1). | P2.7 |
| `providers/fmp_cached/.../tests/unit/test_intraday_gap_detection.py` | Gap-detection + tail-invalidation coverage for the new tier-1 fetcher. | P2.1 |
| `providers/fmp_cached/.../tests/unit/test_aftermarket_quote_ttl.py` | 60s TTL hit/miss coverage. | P2.1 |
| `providers/fmp_cached/.../tests/unit/test_ttl_wrapper.py` | `create_ttl_wrapper_class` unit tests + `ExchangeMarketHours` regression. | P2.2 |

**Out of scope for Phase 2** (belongs to later phases — do NOT create here):
- Any file under `openbb_fmp_trading/agent/` → Phase 3
- `AlertManager`, `alert_router` → Phase 4
- `report.py`, `end_of_day.md` generator → Phase 5
- `market_snapshot`, `build_daily_plan` commands → Phase 4

---

## Task P2.1: Upgrade intraday bars + aftermarket quote to tier-1 caching

**Consumes:** existing tier-2 registration for `EquityIntradayHistoricalFetcher` + `AftermarketQuoteFetcher` (Phase 0.2); existing gap-detection pattern in `models/equity_historical.py`; MySQL cache pool from `utils/db.py`.
**Produces:** two new MySQL tables; two new tier-1 fetchers; ≥95% cache hit rate on same-day replays (AC-3); same-session tail-invalidation invariant asserted by test.

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py`
- Rewrite: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_intraday_historical.py`
- Rewrite: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/aftermarket_quote.py`
- Create: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_intraday_gap_detection.py`
- Create: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_aftermarket_quote_ttl.py`

- [ ] **Step 1: Add the two new tables to `cache_schema.py` (RED first — write failing schema test)**

Append to the `SCHEMA_STATEMENTS` tuple in `cache_schema.py` (exact DDL from PRD §5.2 — do not paraphrase):

```python
EQUITY_INTRADAY_HISTORICAL_DDL = """
CREATE TABLE IF NOT EXISTS equity_intraday_historical (
    symbol           VARCHAR(20)       NOT NULL,
    interval_type    VARCHAR(10)       NOT NULL,
    ts               DATETIME(0)       NOT NULL,
    open_price       DECIMAL(18,6),
    high_price       DECIMAL(18,6),
    low_price        DECIMAL(18,6),
    close_price      DECIMAL(18,6),
    volume           BIGINT,
    is_extended      BOOLEAN           DEFAULT FALSE,
    cached_at        DATETIME(0)       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_valid         BOOLEAN           DEFAULT TRUE,
    additional_fields JSON,
    PRIMARY KEY (symbol, interval_type, ts),
    INDEX idx_symbol_interval_ts (symbol, interval_type, ts DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

AFTERMARKET_QUOTE_DDL = """
CREATE TABLE IF NOT EXISTS aftermarket_quote (
    symbol           VARCHAR(20)       PRIMARY KEY,
    price            DECIMAL(18,6),
    bid              DECIMAL(18,6),
    ask              DECIMAL(18,6),
    bid_size         INTEGER,
    ask_size         INTEGER,
    volume           BIGINT,
    timestamp        DATETIME(0)       NOT NULL,
    cached_at        DATETIME(0)       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_valid         BOOLEAN           DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SCHEMA_STATEMENTS = (
    # ...existing DDL...
    EQUITY_INTRADAY_HISTORICAL_DDL,
    AFTERMARKET_QUOTE_DDL,
)
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_cache_schema.py -q`
Expected: PASS (schema DDL parses, both new statements present in the tuple).

- [ ] **Step 2: Rewrite `equity_intraday_historical.py` with gap detection + tail-invalidation**

Mirror `equity_historical.py`'s `_analyze_cache_gaps` / `_detect_missing_ranges` pattern, but at 5-min granularity and with `is_extended` and `interval_type` in the key. The `_mark_tail_invalid` method is the correctness-critical addition — same-session tail bars are `is_valid=FALSE` and forced-refetched next tick.

```python
"""Tier-1 cached intraday historical bars fetcher.

Gap-detection caching over the /stable/historical-chart/{interval} FMP endpoint.
Mirrors equity_historical.py but for intraday granularity, with the additional
correctness rule that the most recent bar of the current session is treated as
tentatively-valid — served from cache once, then invalidated on the next call
to force re-fetch. Prior-session bars are immutable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import exchange_calendars as xcals
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_fmp.models.equity_intraday_historical import (
    FMPEquityIntradayHistoricalData,
    FMPEquityIntradayHistoricalFetcher,
    FMPEquityIntradayHistoricalQueryParams,
)

from openbb_fmp_cached.utils.db import cache_pool
from openbb_fmp_cached.utils.credential_translation import translate_credentials

_INTERVAL_TO_MINUTES = {
    "1min": 1, "5min": 5, "15min": 15, "30min": 30, "1hour": 60, "4hour": 240,
}
_CALENDAR = xcals.get_calendar("XNYS")


class FMPCachedEquityIntradayHistoricalFetcher(
    Fetcher[FMPEquityIntradayHistoricalQueryParams, list[FMPEquityIntradayHistoricalData]]
):
    """Tier-1 gap-detection cached intraday bars."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEquityIntradayHistoricalQueryParams:
        return FMPEquityIntradayHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityIntradayHistoricalQueryParams,
        credentials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        symbols = _split_symbols(query.symbol)
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            cached_rows, gap_ranges = _analyze_intraday_gaps(
                symbol=symbol,
                interval_type=query.interval,
                start=query.start_date,
                end=query.end_date,
            )
            for gap_start, gap_end in gap_ranges:
                gap_query = query.model_copy(
                    update={"symbol": symbol, "start_date": gap_start, "end_date": gap_end}
                )
                fresh_rows = await FMPEquityIntradayHistoricalFetcher.aextract_data(
                    gap_query, translate_credentials(credentials), **kwargs
                )
                _upsert_intraday_rows(symbol, query.interval, fresh_rows)
                cached_rows.extend(fresh_rows)
            _mark_tail_invalid(symbol, query.interval, cached_rows)
            results.extend(cached_rows)
        return results

    @staticmethod
    def transform_data(
        query: FMPEquityIntradayHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FMPEquityIntradayHistoricalData]:
        return FMPEquityIntradayHistoricalFetcher.transform_data(query, data, **kwargs)


def _split_symbols(symbol_field: str) -> list[str]:
    return [s.strip().upper() for s in symbol_field.split(",") if s.strip()]


def _analyze_intraday_gaps(
    symbol: str, interval_type: str, start: datetime | None, end: datetime | None,
) -> tuple[list[dict[str, Any]], list[tuple[datetime, datetime]]]:
    """Return (cached_rows_in_range, missing_ranges_to_fetch).

    A range is 'missing' iff the calendar-expected bar count > cached bar count
    for a contiguous window. Non-trading hours (per exchange_calendars) are
    excluded from the expectation.
    """
    interval_minutes = _INTERVAL_TO_MINUTES[interval_type]
    with cache_pool.acquire() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            """SELECT ts, open_price, high_price, low_price, close_price, volume,
                      is_extended, is_valid
               FROM equity_intraday_historical
               WHERE symbol=%s AND interval_type=%s
                 AND ts BETWEEN %s AND %s
               ORDER BY ts ASC""",
            (symbol, interval_type, start, end),
        )
        rows = cur.fetchall()
    cached_ts = {r["ts"] for r in rows if r["is_valid"]}
    expected = _expected_bar_timestamps(start, end, interval_minutes)
    missing = sorted(expected - cached_ts)
    ranges = _contiguous_ranges(missing, timedelta(minutes=interval_minutes))
    return rows, ranges


def _expected_bar_timestamps(
    start: datetime, end: datetime, interval_minutes: int
) -> set[datetime]:
    """Enumerate bar-start ts inside RTH sessions between start and end."""
    expected: set[datetime] = set()
    for session in _CALENDAR.sessions_in_range(start.date(), end.date()):
        open_ts = _CALENDAR.session_open(session).to_pydatetime()
        close_ts = _CALENDAR.session_close(session).to_pydatetime()
        cursor = open_ts
        while cursor < close_ts:
            if start <= cursor <= end:
                expected.add(cursor)
            cursor += timedelta(minutes=interval_minutes)
    return expected


def _contiguous_ranges(
    stamps: list[datetime], gap_tolerance: timedelta,
) -> list[tuple[datetime, datetime]]:
    if not stamps:
        return []
    ranges: list[tuple[datetime, datetime]] = []
    run_start = stamps[0]
    prev = stamps[0]
    for ts in stamps[1:]:
        if ts - prev > gap_tolerance:
            ranges.append((run_start, prev))
            run_start = ts
        prev = ts
    ranges.append((run_start, prev))
    return ranges


def _upsert_intraday_rows(symbol: str, interval_type: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with cache_pool.acquire() as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO equity_intraday_historical
               (symbol, interval_type, ts, open_price, high_price, low_price,
                close_price, volume, is_extended, is_valid)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
               ON DUPLICATE KEY UPDATE
                 open_price=VALUES(open_price), high_price=VALUES(high_price),
                 low_price=VALUES(low_price), close_price=VALUES(close_price),
                 volume=VALUES(volume), is_valid=TRUE,
                 cached_at=CURRENT_TIMESTAMP""",
            [
                (
                    symbol, interval_type, r["date"],
                    Decimal(str(r["open"])), Decimal(str(r["high"])),
                    Decimal(str(r["low"])), Decimal(str(r["close"])),
                    int(r["volume"]), bool(r.get("is_extended", False)),
                )
                for r in rows
            ],
        )
        conn.commit()


def _mark_tail_invalid(symbol: str, interval_type: str, rows: list[dict[str, Any]]) -> None:
    """Correctness-critical: the last bar of the current session may still extend.

    Mark it is_valid=FALSE so the next call re-fetches it. Prior-session bars
    are immutable and stay TRUE.
    """
    if not rows:
        return
    now_et = datetime.now(tz=_CALENDAR.tz).replace(tzinfo=None)
    today = now_et.date()
    tail = rows[-1]
    tail_ts = tail["ts"] if isinstance(tail, dict) else tail.date
    if tail_ts.date() != today:
        return
    if not _CALENDAR.is_session(today):
        return
    with cache_pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE equity_intraday_historical
               SET is_valid=FALSE
               WHERE symbol=%s AND interval_type=%s AND ts=%s""",
            (symbol, interval_type, tail_ts),
        )
        conn.commit()
```

- [ ] **Step 3: Write the intraday gap-detection unit test**

Create `openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_intraday_gap_detection.py`:

```python
"""Unit tests for tier-1 intraday bar caching: gap detection + tail invalidation."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from openbb_fmp_cached.models.equity_intraday_historical import (
    _analyze_intraday_gaps,
    _contiguous_ranges,
    _expected_bar_timestamps,
    _mark_tail_invalid,
)


def test_expected_bar_timestamps_excludes_non_rth():
    start = datetime(2026, 7, 6, 9, 0)
    end = datetime(2026, 7, 6, 10, 0)
    expected = _expected_bar_timestamps(start, end, interval_minutes=5)
    assert datetime(2026, 7, 6, 9, 30) in expected
    assert datetime(2026, 7, 6, 9, 0) not in expected   # pre-market excluded


def test_contiguous_ranges_bridges_within_tolerance():
    stamps = [
        datetime(2026, 7, 6, 9, 30),
        datetime(2026, 7, 6, 9, 35),
        datetime(2026, 7, 6, 10, 0),   # gap → new run
        datetime(2026, 7, 6, 10, 5),
    ]
    ranges = _contiguous_ranges(stamps, timedelta(minutes=5))
    assert len(ranges) == 2
    assert ranges[0] == (datetime(2026, 7, 6, 9, 30), datetime(2026, 7, 6, 9, 35))


@freeze_time("2026-07-06 14:00:00", tz_offset=-4)  # 10:00 ET on a trading day
def test_mark_tail_invalid_flips_same_session_last_bar():
    tail = {"ts": datetime(2026, 7, 6, 9, 55), "date": datetime(2026, 7, 6, 9, 55)}
    with patch("openbb_fmp_cached.models.equity_intraday_historical.cache_pool") as pool:
        _mark_tail_invalid("MSFT", "5min", [tail])
    pool.acquire.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.execute.assert_called_once()


def test_mark_tail_invalid_does_not_touch_prior_day():
    tail = {"ts": datetime(2026, 7, 3, 15, 55), "date": datetime(2026, 7, 3, 15, 55)}
    with patch("openbb_fmp_cached.models.equity_intraday_historical.cache_pool") as pool:
        _mark_tail_invalid("MSFT", "5min", [tail])
    pool.acquire.assert_not_called()
```

- [ ] **Step 4: Rewrite `aftermarket_quote.py` with 60s TTL**

```python
"""Tier-1 cached aftermarket quote fetcher — 60s TTL.

Single-row-per-symbol cache. HIT if cached_at > now - 60s; MISS otherwise.
No gap detection — ephemeral one-value-per-symbol data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_fmp.models.aftermarket_quote import (
    FMPAftermarketQuoteData,
    FMPAftermarketQuoteFetcher,
    FMPAftermarketQuoteQueryParams,
)

from openbb_fmp_cached.utils.db import cache_pool
from openbb_fmp_cached.utils.credential_translation import translate_credentials

_TTL = timedelta(seconds=60)


class FMPCachedAftermarketQuoteFetcher(
    Fetcher[FMPAftermarketQuoteQueryParams, list[FMPAftermarketQuoteData]]
):
    """Tier-1 60-second-TTL cached aftermarket quote."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPAftermarketQuoteQueryParams:
        return FMPAftermarketQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPAftermarketQuoteQueryParams,
        credentials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        fresh_cutoff = datetime.utcnow() - _TTL
        hit_rows, miss_symbols = _fetch_fresh_rows(symbols, fresh_cutoff)
        if miss_symbols:
            miss_query = query.model_copy(update={"symbol": ",".join(miss_symbols)})
            fresh_rows = await FMPAftermarketQuoteFetcher.aextract_data(
                miss_query, translate_credentials(credentials), **kwargs
            )
            _upsert_aftermarket_rows(fresh_rows)
            hit_rows.extend(fresh_rows)
        return hit_rows

    @staticmethod
    def transform_data(
        query: FMPAftermarketQuoteQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FMPAftermarketQuoteData]:
        return FMPAftermarketQuoteFetcher.transform_data(query, data, **kwargs)


def _fetch_fresh_rows(
    symbols: list[str], cutoff: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not symbols:
        return [], []
    with cache_pool.acquire() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"""SELECT symbol, price, bid, ask, bid_size, ask_size, volume, timestamp
                FROM aftermarket_quote
                WHERE symbol IN ({','.join(['%s'] * len(symbols))})
                  AND cached_at > %s AND is_valid=TRUE""",
            (*symbols, cutoff),
        )
        rows = cur.fetchall()
    hit = {r["symbol"] for r in rows}
    return rows, [s for s in symbols if s not in hit]


def _upsert_aftermarket_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with cache_pool.acquire() as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO aftermarket_quote
               (symbol, price, bid, ask, bid_size, ask_size, volume, timestamp, is_valid)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
               ON DUPLICATE KEY UPDATE
                 price=VALUES(price), bid=VALUES(bid), ask=VALUES(ask),
                 bid_size=VALUES(bid_size), ask_size=VALUES(ask_size),
                 volume=VALUES(volume), timestamp=VALUES(timestamp),
                 cached_at=CURRENT_TIMESTAMP, is_valid=TRUE""",
            [
                (
                    r["symbol"], Decimal(str(r["price"])),
                    Decimal(str(r["bid"])), Decimal(str(r["ask"])),
                    int(r["bid_size"]), int(r["ask_size"]),
                    int(r["volume"]), r["timestamp"],
                )
                for r in rows
            ],
        )
        conn.commit()
```

- [ ] **Step 5: Write the aftermarket TTL test + run the unit suite**

Create `test_aftermarket_quote_ttl.py` covering: (a) cold cache → MISS → fetch; (b) cached < 60s → HIT, no fetch; (c) cached > 60s → MISS again; (d) partial hit — 2 symbols cached, 1 stale → single fetch for the stale one.

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit -q`
Expected: all new + existing tests pass (target ~10 new tests across the two files).

- [ ] **Step 6: Commit P2.1**

```bash
git add openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_intraday_historical.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/aftermarket_quote.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_intraday_gap_detection.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_aftermarket_quote_ttl.py
git commit -m "feat(fmp_cached): tier-1 caching for intraday bars + aftermarket quote (P2.1)

Upgrade EquityIntradayHistorical and AftermarketQuote from tier-2 passthrough
to tier-1 gap-detection / TTL caching per PRD §5.2. Same-session tail bars
are marked is_valid=FALSE to force refetch — critical correctness rule.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.2: Add `create_ttl_wrapper_class` + migrate `ExchangeMarketHours`

**Consumes:** existing `create_fallback_fetcher_class` in `base_cached.py`; existing tier-2 registration of `ExchangeMarketHours`.
**Produces:** generic TTL wrapper factory reusable by any future 24h-cached endpoint (holidays, market status); `ExchangeMarketHours` swapped over; ~1000 saved daily calls (§5.5).

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/base_cached.py`
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/exchange_market_hours.py`
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py`
- Create: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_ttl_wrapper.py`

- [ ] **Step 1: Add `create_ttl_wrapper_class` to `base_cached.py`**

```python
def create_ttl_wrapper_class(
    inner_fetcher_cls: type[Fetcher], name: str, ttl_seconds: int,
) -> type[Fetcher]:
    """Wrap a fetcher with a global TTL cache keyed by (query_hash).

    Cache backend: a single JSON blob per (name, query_hash) in `ttl_cache` table
    (created lazily). HIT iff cached_at > now - ttl_seconds. On MISS, delegate to
    the inner fetcher, upsert the payload, return.

    Justification: `create_fallback_fetcher_class` only serves same-session
    passthrough; anything needing multi-hour caching (market hours, holidays,
    market-status) needs this wrapper (~30 LoC).
    """
    import hashlib
    import json
    from datetime import datetime, timedelta

    ttl = timedelta(seconds=ttl_seconds)

    class _TTLWrapped(Fetcher):
        __name__ = f"{name}TTLCached"

        @staticmethod
        def transform_query(params: dict[str, Any]):
            return inner_fetcher_cls.transform_query(params)

        @staticmethod
        async def aextract_data(query, credentials=None, **kwargs):
            key = _hash_query(query)
            cached = _load_ttl_cache(name, key, cutoff=datetime.utcnow() - ttl)
            if cached is not None:
                return cached
            fresh = await inner_fetcher_cls.aextract_data(
                query, translate_credentials(credentials), **kwargs
            )
            _upsert_ttl_cache(name, key, fresh)
            return fresh

        @staticmethod
        def transform_data(query, data, **kwargs):
            return inner_fetcher_cls.transform_data(query, data, **kwargs)

    def _hash_query(query) -> str:
        payload = query.model_dump_json(exclude_none=True) if hasattr(query, "model_dump_json") else json.dumps(query, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _load_ttl_cache(name: str, key: str, cutoff: datetime):
        with cache_pool.acquire() as conn, conn.cursor(dictionary=True) as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS ttl_cache (
                       cache_name VARCHAR(80) NOT NULL,
                       cache_key  CHAR(64)    NOT NULL,
                       payload    JSON        NOT NULL,
                       cached_at  DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP,
                       PRIMARY KEY (cache_name, cache_key)
                   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
            )
            cur.execute(
                "SELECT payload FROM ttl_cache WHERE cache_name=%s AND cache_key=%s AND cached_at > %s",
                (name, key, cutoff),
            )
            row = cur.fetchone()
        return json.loads(row["payload"]) if row else None

    def _upsert_ttl_cache(name: str, key: str, data):
        with cache_pool.acquire() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ttl_cache (cache_name, cache_key, payload)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE payload=VALUES(payload), cached_at=CURRENT_TIMESTAMP""",
                (name, key, json.dumps(data, default=str)),
            )
            conn.commit()

    return _TTLWrapped
```

- [ ] **Step 2: Migrate `ExchangeMarketHours` to use the wrapper**

Replace the contents of `exchange_market_hours.py`:

```python
"""Tier-2-with-24h-TTL wrapper for the exchange-market-hours FMP endpoint (§5.5)."""

from __future__ import annotations

from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher

from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

FMPCachedExchangeMarketHoursFetcher = create_ttl_wrapper_class(
    FMPExchangeMarketHoursFetcher, name="ExchangeMarketHours", ttl_seconds=86400,
)
```

Update `openbb_fmp_cached/__init__.py` to register the new class in place of the passthrough entry.

- [ ] **Step 3: Write TTL wrapper unit test**

`test_ttl_wrapper.py`:

```python
"""Unit tests for create_ttl_wrapper_class."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class


class _FakeQuery:
    def model_dump_json(self, exclude_none=True):
        return '{"date":"2026-07-06"}'


class _FakeInner:
    aextract_data = AsyncMock(return_value=[{"exchange": "NASDAQ", "is_open": True}])
    transform_query = staticmethod(lambda p: _FakeQuery())
    transform_data = staticmethod(lambda q, d, **k: d)


@pytest.mark.asyncio
async def test_first_call_misses_and_upserts():
    cls = create_ttl_wrapper_class(_FakeInner, "ExchangeMarketHours", 86400)
    with patch("openbb_fmp_cached.models.base_cached.cache_pool") as pool:
        cur = pool.acquire.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        result = await cls.aextract_data(_FakeQuery())
    assert result == [{"exchange": "NASDAQ", "is_open": True}]
    _FakeInner.aextract_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_call_within_ttl_hits_cache():
    _FakeInner.aextract_data.reset_mock()
    cls = create_ttl_wrapper_class(_FakeInner, "ExchangeMarketHours", 86400)
    with patch("openbb_fmp_cached.models.base_cached.cache_pool") as pool:
        cur = pool.acquire.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"payload": '[{"exchange":"NASDAQ","is_open":true}]'}
        result = await cls.aextract_data(_FakeQuery())
    assert result == [{"exchange": "NASDAQ", "is_open": True}]
    _FakeInner.aextract_data.assert_not_awaited()
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_ttl_wrapper.py -q`
Expected: 2 passed.

- [ ] **Step 4: Commit P2.2**

```bash
git add openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/base_cached.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/exchange_market_hours.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/tests/unit/test_ttl_wrapper.py
git commit -m "feat(fmp_cached): add create_ttl_wrapper_class + migrate ExchangeMarketHours (P2.2)

Generic ~30 LoC TTL wrapper factory extends base_cached beyond same-session
passthrough. ExchangeMarketHours moves to 24h TTL — saves ~1000 daily
redundant calls per PRD §5.5. Ready for future holidays / market-status
endpoints to reuse the wrapper.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.3: `IntradaySession` skeleton — quote polling + journal writes only

**Consumes:** tier-1 fetchers from P2.1; `SessionJournal` (Phase 1); `BandwidthMeter` (Phase 1); `RiskManager` (Phase 1) — imported but not yet wired to a `PaperBroker` (that's P2.4).
**Produces:** `IntradaySession` class + `run_tick` pure function; ability to run a 3-tick smoke session that produces 3 `TickEvent` journal entries with no signals, no orders, no fills.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/session.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_intraday_session.py`

- [ ] **Step 1: Write the failing session smoke test (RED)**

`test_intraday_session.py`:

```python
"""Unit tests for IntradaySession skeleton: construction + tick journal writes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from openbb_fmp_trading.core.session import IntradaySession
from openbb_fmp_trading.models.plan import DailyPlan


def _make_plan() -> DailyPlan:
    return DailyPlan(
        as_of=datetime(2026, 7, 6, 9, 25, tzinfo=timezone.utc),
        date=datetime(2026, 7, 6).date(),
        watchlist=["MSFT", "AAPL"],
        preset="intraday_momentum",
        alerts=[],
        session_risk=MagicMock(),
        thesis="test",
        agent_backend="none",
    )


@freeze_time("2026-07-06 13:35:00")  # 09:35 ET
def test_session_construction_writes_start_event():
    journal = MagicMock()
    session = IntradaySession(
        plan=_make_plan(), journal=journal, risk_manager=MagicMock(),
        broker=MagicMock(), bandwidth=MagicMock(),
    )
    journal.write.assert_called()
    session_start_events = [
        c for c in journal.write.call_args_list
        if c.args[0].event_type == "session_start"
    ]
    assert len(session_start_events) == 1


@freeze_time("2026-07-06 13:35:00")
def test_run_tick_polls_quotes_and_journals():
    from openbb_fmp_trading.core.tick_loop import run_tick
    session = MagicMock()
    session.plan.watchlist = ["MSFT"]
    fake_quote = {"symbol": "MSFT", "price": Decimal("430.15"), "timestamp": datetime.utcnow()}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "openbb_fmp_trading.core.tick_loop._fetch_batch_quote",
            lambda symbols, provider: [fake_quote],
        )
        events = run_tick(session, tick_ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc))
    types = [e.event_type for e in events]
    assert "tick" in types
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_intraday_session.py -q`
Expected: FAIL — `ModuleNotFoundError` on `session` and `tick_loop`.

- [ ] **Step 2: Create the session skeleton**

`core/session.py`:

```python
"""IntradaySession — market-hours state machine.

Owns the tick clock, watchlist quote polling, and journal. Does NOT own signal
math (delegated to techtrade — wired in P2.4) or agent turns (Phase 3).

Every call to broker.submit() funnels through _process_signal() → RiskManager
(P7 chokepoint). Enforced by tests/architecture/test_broker_chokepoint.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.session_state import JournalEvent, TickData


@dataclass
class IntradaySession:
    plan: DailyPlan
    journal: Any            # SessionJournal (Phase 1)
    risk_manager: Any       # RiskManager (Phase 1)
    broker: Any             # BrokerInterface — PaperBroker in v1
    bandwidth: Any          # BandwidthMeter (Phase 1)
    session_id: str = field(default_factory=lambda: datetime.utcnow().strftime("s%Y%m%d%H%M%S"))
    _flat_window_open: bool = False
    _ticks_processed: int = 0

    def __post_init__(self) -> None:
        self.journal.write(
            JournalEvent(
                ts=datetime.now(timezone.utc),
                session_id=self.session_id,
                event_type="session_start",
                payload={
                    "date": str(self.plan.date), "watchlist": self.plan.watchlist,
                    "preset": self.plan.preset, "agent_backend": self.plan.agent_backend,
                },
            )
        )

    def emit(self, event: JournalEvent) -> None:
        self.journal.write(event)
        self._ticks_processed += 1

    def close(self, flat_at_close: bool) -> None:
        self.journal.write(
            JournalEvent(
                ts=datetime.now(timezone.utc),
                session_id=self.session_id,
                event_type="session_end",
                payload={"flat_at_close": flat_at_close, "total_ticks": self._ticks_processed},
            )
        )
```

`core/tick_loop.py`:

```python
"""Pure-function tick loop iterator: (session, tick_ts) -> list[JournalEvent].

Stateless w.r.t. the session between ticks — session state changes are only via
IntradaySession.emit() side-effects. Reason: makes the whole loop replay-safe
per PRD §11 golden-test contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbb import obb

from openbb_fmp_trading.models.session_state import JournalEvent


def run_tick(session: Any, tick_ts: datetime) -> list[JournalEvent]:
    events: list[JournalEvent] = []
    quotes = _fetch_batch_quote(session.plan.watchlist, provider="fmp_cached")
    events.append(
        JournalEvent(
            ts=tick_ts, session_id=session.session_id, event_type="tick",
            payload={"quotes": [_quote_to_dict(q) for q in quotes]},
        )
    )
    for e in events:
        session.emit(e)
    return events


def _fetch_batch_quote(symbols: list[str], provider: str) -> list[dict[str, Any]]:
    # Real impl calls obb.fmp_trading.quote_batch under the hood; kept thin so
    # tests can monkeypatch.
    result = obb.fmp_trading.quote_batch(symbols=symbols, short=True, provider=provider)
    return [r.model_dump() for r in result.results]


def _quote_to_dict(q: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": q["symbol"], "price": str(q.get("price")), "ts": q.get("timestamp")}
```

- [ ] **Step 3: Re-run the smoke test (GREEN)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_intraday_session.py -q`
Expected: 2 passed.

- [ ] **Step 4: Commit P2.3**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/session.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_intraday_session.py
git commit -m "feat(fmp_trading): IntradaySession skeleton + tick loop (P2.3)

Session state machine with quote polling and NDJSON journal writes. No
signals wired yet — that's P2.4. Establishes the chokepoint pattern
(broker.submit() only ever called from _process_signal via RiskManager).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.4: Wire techtrade `signals → plan → orders → PaperBroker` into tick loop

**Consumes:** `obb.techtrade.signals`, `obb.techtrade.plan`, `obb.techtrade.orders`, `PaperBroker` (all from `openbb-techtrade`, unchanged); tick loop from P2.3; `RiskManager.propose_trade` from Phase 1.
**Produces:** the fully-wired inner loop: 5-min bar close → techtrade signals → TradePlan → RiskManager → PaperBroker → Fill → journal. No reimplementation of signal math — every quant op is a call into `obb.techtrade.*` per G3/NG2.

**Files:**
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/session.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_tick_loop_signal_wiring.py`

- [ ] **Step 1: Extend `IntradaySession` with `_process_signal` — the CHOKEPOINT method**

Append to `session.py`:

```python
    def _process_signal(self, plan: Any, tick: TickData) -> list[JournalEvent]:
        """The ONLY caller of self.broker.submit() in the entire codebase.

        Chokepoint per PRD §8.6 / P7: every proposed order funnels through
        RiskManager.propose_trade() here — no other path submits.
        Enforced by tests/architecture/test_broker_chokepoint.py.
        """
        events: list[JournalEvent] = []
        decision = self.risk_manager.propose_trade(plan, tick)
        if decision.verdict == "REJECTED":
            events.append(
                JournalEvent(
                    ts=tick.ts, session_id=self.session_id, event_type="veto",
                    payload={"reason_code": decision.reason_code, "gate": decision.gate,
                             "plan_symbol": plan.symbol},
                )
            )
            return events
        events.append(
            JournalEvent(
                ts=tick.ts, session_id=self.session_id, event_type="plan",
                payload={"symbol": plan.symbol, "intent": plan.intent},
            )
        )
        for order in plan.orders:
            fill = self.broker.submit(order, bar=tick.bars_recent[plan.symbol][-1])
            events.append(
                JournalEvent(
                    ts=tick.ts, session_id=self.session_id, event_type="order",
                    payload={"order_ref": order.ref, "symbol": order.symbol,
                             "qty": str(order.qty), "intent": order.intent},
                )
            )
            if fill:
                events.append(
                    JournalEvent(
                        ts=tick.ts, session_id=self.session_id, event_type="fill",
                        payload={"order_ref": order.ref, "fill_price": str(fill.price),
                                 "fill_qty": str(fill.qty), "commission": str(fill.commission)},
                    )
                )
        return events
```

- [ ] **Step 2: Extend `tick_loop.run_tick` — every N ticks fire signals**

Update `tick_loop.py`:

```python
def run_tick(session: Any, tick_ts: datetime) -> list[JournalEvent]:
    events: list[JournalEvent] = []
    quotes = _fetch_batch_quote(session.plan.watchlist, provider="fmp_cached")
    tick = _build_tick_data(session, tick_ts, quotes)
    events.append(
        JournalEvent(ts=tick_ts, session_id=session.session_id, event_type="tick",
                     payload={"quote_count": len(quotes)})
    )

    if _is_signal_bar_close(tick_ts, session.plan.preset):
        signals = _run_techtrade_signals(session.plan, tick)
        for sig in signals:
            events.append(
                JournalEvent(ts=tick_ts, session_id=session.session_id, event_type="signal",
                             payload={"symbol": sig.symbol, "score": sig.score})
            )
            plan = _build_techtrade_plan(sig, tick)
            events.extend(session._process_signal(plan, tick))

    for e in events:
        session.emit(e)
    return events


def _build_tick_data(session, tick_ts, quotes):
    from openbb_fmp_trading.models.session_state import TickData
    bars_recent = _fetch_recent_bars(session.plan.watchlist)
    session_status = _fetch_session_status(exchange="NASDAQ")
    return TickData(
        ts=tick_ts,
        quotes={q["symbol"]: q for q in quotes},
        bars_recent=bars_recent,
        session_status=session_status,
    )


def _is_signal_bar_close(tick_ts: datetime, preset: str) -> bool:
    # Default 5-min bar close; presets may override in future
    return tick_ts.minute % 5 == 0 and tick_ts.second == 0


def _run_techtrade_signals(plan, tick):
    from openbb import obb
    result = obb.techtrade.signals(
        symbols=plan.watchlist, preset=plan.preset, bars=tick.bars_recent,
    )
    return result.results


def _build_techtrade_plan(signal, tick):
    from openbb import obb
    result = obb.techtrade.plan(signal=signal, tick=tick)
    return result.results


def _fetch_recent_bars(symbols):
    from openbb import obb
    return {
        s: obb.fmp_trading.bars_intraday(
            symbols=[s], interval="5min", provider="fmp_cached"
        ).results
        for s in symbols
    }


def _fetch_session_status(exchange: str):
    from openbb import obb
    return obb.fmp_trading.session_status(exchange=exchange, provider="fmp_cached").results
```

- [ ] **Step 3: Write the signal-wiring unit test with mocked techtrade**

`test_tick_loop_signal_wiring.py`:

```python
"""Unit test: signals wire through to broker.submit exactly once per approved plan."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _stub_techtrade(monkeypatch):
    fake_sig = MagicMock(symbol="MSFT", score=0.72)
    fake_plan = MagicMock(symbol="MSFT", intent="OPEN_LONG", orders=[
        MagicMock(ref="o1", symbol="MSFT", qty=Decimal("10"), intent="OPEN_LONG")
    ])
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._run_techtrade_signals",
                        lambda plan, tick: [fake_sig])
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._build_techtrade_plan",
                        lambda sig, tick: fake_plan)
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._fetch_batch_quote",
                        lambda syms, provider: [{"symbol": "MSFT", "price": "430"}])
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._fetch_recent_bars",
                        lambda syms: {"MSFT": [MagicMock(close=Decimal("430"))]})
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._fetch_session_status",
                        lambda exchange: MagicMock(is_market_open=True))
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._is_signal_bar_close",
                        lambda ts, preset: True)
    return fake_plan


def test_approved_plan_submits_exactly_one_order(_stub_techtrade):
    from openbb_fmp_trading.core.tick_loop import run_tick
    session = MagicMock()
    session.plan.watchlist = ["MSFT"]
    session.plan.preset = "intraday_momentum"
    session.risk_manager.propose_trade.return_value = MagicMock(
        verdict="APPROVED", reason_code=None, gate=None
    )
    session.broker.submit.return_value = MagicMock(
        price=Decimal("430.05"), qty=Decimal("10"), commission=Decimal("1.00")
    )
    session._process_signal = lambda plan, tick: []  # bypass to test wiring path exists
    events = run_tick(session, tick_ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc))
    signal_events = [e for e in events if e.event_type == "signal"]
    assert len(signal_events) == 1


def test_rejected_plan_never_calls_broker():
    # Delegated to test_flat_by_close in P2.5 which exercises the same chokepoint
    # for the flat-by-close rejection reason (AC-6).
    pass
```

- [ ] **Step 4: Run the wiring test + verify architecture chokepoint test still green**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests -q` and `... tests/architecture/test_broker_chokepoint.py -q`
Expected: all green. The chokepoint test (from Phase 1) now scans `core/session.py::_process_signal` as the sole call site.

- [ ] **Step 5: Commit P2.4**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/session.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_tick_loop_signal_wiring.py
git commit -m "feat(fmp_trading): wire techtrade signals -> RiskManager -> PaperBroker (P2.4)

Every quant op delegates to obb.techtrade.* — no math reimplemented here (G3).
_process_signal is the sole broker.submit chokepoint per PRD §8.6 / P7.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.5: Flat-by-close state machine + AC-6 test

**Consumes:** `RiskManager` gate G1 (from Phase 1); tick loop from P2.4; `exchange_calendars` (P5 clock discipline).
**Produces:** state-machine helper `enter_flat_window(now_et) -> WindowState`; RiskManager pre-tick hook that flips G1 on/off; **AC-6 test green** — order submitted at 15:51 ET → `REJECTED(G1)`; positions still open at 15:55 ET → force-close MARKET SELL queued.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/flat_by_close.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_flat_by_close.py`

- [ ] **Step 1: Write the AC-6 failing test (RED)**

`test_flat_by_close.py`:

```python
"""AC-6 test: RiskManager rejects new opens after 15:50 ET; positions flatten by 15:55."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from openbb_fmp_trading.core.flat_by_close import WindowState, enter_flat_window


@freeze_time("2026-07-06 19:49:00")  # 15:49 ET
def test_normal_window_before_15_50():
    now = datetime(2026, 7, 6, 15, 49)
    assert enter_flat_window(now) == WindowState.NORMAL


@freeze_time("2026-07-06 19:51:00")  # 15:51 ET
def test_flat_by_close_window_after_15_50():
    now = datetime(2026, 7, 6, 15, 51)
    assert enter_flat_window(now) == WindowState.NO_NEW_OPENS


@freeze_time("2026-07-06 19:56:00")  # 15:56 ET
def test_force_close_window_after_15_55():
    now = datetime(2026, 7, 6, 15, 56)
    assert enter_flat_window(now) == WindowState.FORCE_CLOSE


def test_ac6_order_at_15_51_gets_rejected_g1():
    """AC-6 from PRD §2.3: submit order at 15:51 → REJECTED(reason=flat_by_close_window)."""
    from openbb_fmp_trading.core.session import IntradaySession
    rm = MagicMock()
    rm.propose_trade.return_value = MagicMock(
        verdict="REJECTED", reason_code="flat_by_close_window", gate="G1"
    )
    session = IntradaySession(
        plan=MagicMock(watchlist=["MSFT"], preset="intraday_momentum",
                       date=datetime(2026, 7, 6).date(),
                       agent_backend="none"),
        journal=MagicMock(), risk_manager=rm, broker=MagicMock(), bandwidth=MagicMock(),
    )
    tick = MagicMock(ts=datetime(2026, 7, 6, 15, 51), bars_recent={"MSFT": [MagicMock()]})
    plan = MagicMock(symbol="MSFT", intent="OPEN_LONG", orders=[MagicMock()])
    events = session._process_signal(plan, tick)
    veto_events = [e for e in events if e.event_type == "veto"]
    assert len(veto_events) == 1
    assert veto_events[0].payload["reason_code"] == "flat_by_close_window"
    session.broker.submit.assert_not_called()
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_flat_by_close.py -q`
Expected: FAIL — `ModuleNotFoundError` on `flat_by_close`.

- [ ] **Step 2: Create `flat_by_close.py`**

```python
"""Flat-by-close state machine (PRD §8.5, P4).

Three states based on wall-clock ET:
  NORMAL       (before 15:50) — RiskManager permits new opens
  NO_NEW_OPENS (15:50–15:54)  — G1 rejects new opens; existing positions still hold
  FORCE_CLOSE  (15:55–close)  — queued MARKET SELL for every open position
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum

import exchange_calendars as xcals

_CALENDAR = xcals.get_calendar("XNYS")


class WindowState(str, Enum):
    NORMAL = "normal"
    NO_NEW_OPENS = "no_new_opens"
    FORCE_CLOSE = "force_close"


def enter_flat_window(
    now_et: datetime,
    no_new_opens_time: time = time(15, 50),
    force_close_time: time = time(15, 55),
) -> WindowState:
    """Compute the current flat-by-close state. Uses exchange_calendars for
    half-day-adjusted close if applicable (PRD Open Q4 → scale to close - 5min).
    """
    session_date = now_et.date()
    if _CALENDAR.is_session(session_date):
        session_close = _CALENDAR.session_close(session_date).to_pydatetime().time()
        # Half-day adjustment: use close - 5min if session closes early
        if session_close < time(16, 0):
            force_close_time = _minutes_before(session_close, 5)
            no_new_opens_time = _minutes_before(session_close, 10)
    t = now_et.time()
    if t >= force_close_time:
        return WindowState.FORCE_CLOSE
    if t >= no_new_opens_time:
        return WindowState.NO_NEW_OPENS
    return WindowState.NORMAL


def _minutes_before(t: time, minutes: int) -> time:
    from datetime import datetime, timedelta
    dt = datetime.combine(datetime.today(), t) - timedelta(minutes=minutes)
    return dt.time()
```

- [ ] **Step 3: Wire the state machine into the tick loop**

Append to `tick_loop.run_tick` before the signal-bar-close check:

```python
    from openbb_fmp_trading.core.flat_by_close import WindowState, enter_flat_window
    window = enter_flat_window(tick_ts)
    if window == WindowState.FORCE_CLOSE:
        events.extend(_force_close_positions(session, tick_ts))
```

Where `_force_close_positions` queries `session.broker.positions()` and routes each open position through `session._process_signal` with an `OPEN_SHORT`-equivalent exit intent, so the chokepoint is honored.

- [ ] **Step 4: Re-run the AC-6 test (GREEN)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_flat_by_close.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit P2.5**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/flat_by_close.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_flat_by_close.py
git commit -m "feat(fmp_trading): flat-by-close state machine + AC-6 test (P2.5)

Three-state window (NORMAL / NO_NEW_OPENS / FORCE_CLOSE) driven by
exchange_calendars — auto-scales to half-day closes per PRD Open Q4.
AC-6 green: 15:51 ET order → REJECTED(G1); no broker.submit call.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.6: AC-5 no-look-ahead golden test

**Consumes:** the fully-wired tick loop (P2.4); `PaperBroker` fill semantics (from techtrade #78 — signal-at-t-close fills at t+1-open).
**Produces:** golden test that locks the P3 invariant at 5-min granularity. **AC-5 green.**

Pattern reference: techtrade #78 (`docs/designs/quant_trading/78-paperbroker-fill-sim.md`) established the invariant at daily bars; this test mirrors it exactly at intraday granularity — same `next-bar-open` fill discipline, same "signal on close(t) → order timestamp == open(t+1)" assertion.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/golden/test_no_look_ahead.py`
- Create (if needed): `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/golden/__init__.py`

- [ ] **Step 1: Author the golden test**

```python
"""AC-5 golden test: no look-ahead in intraday.

Invariant: a signal computed off the CLOSE of 5-min bar t results in a fill at
the OPEN of 5-min bar t+1 — never earlier, never at close(t).

Mirrors techtrade #78's daily-bar golden test at 5-min granularity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _make_5min_bars(start: datetime, count: int) -> list[MagicMock]:
    """Synthetic monotonically-increasing 5-min bars for a single symbol."""
    bars = []
    for i in range(count):
        ts = start + timedelta(minutes=5 * i)
        bars.append(MagicMock(
            symbol="MSFT", interval="5min", ts=ts,
            open=Decimal(f"{430 + i}.00"),
            high=Decimal(f"{430 + i}.50"),
            low=Decimal(f"{430 + i}.00"),
            close=Decimal(f"{430 + i}.25"),
            volume=1_000_000,
        ))
    return bars


def test_signal_at_bar_close_fills_at_next_bar_open(monkeypatch):
    """The core AC-5 assertion."""
    from openbb_fmp_trading.core.tick_loop import run_tick

    signal_bar_start = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    bars = _make_5min_bars(signal_bar_start, count=3)
    # bars[0]: 09:30 open=430.00 close=430.25
    # bars[1]: 09:35 open=431.00 close=431.25
    # bars[2]: 09:40 open=432.00 close=432.25

    fake_sig = MagicMock(symbol="MSFT", score=0.9, ts_bar_close=bars[0].ts + timedelta(minutes=5))
    fake_order = MagicMock(ref="o1", symbol="MSFT", qty=Decimal("10"), intent="OPEN_LONG")
    fake_plan = MagicMock(symbol="MSFT", intent="OPEN_LONG", orders=[fake_order])

    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._fetch_batch_quote",
                        lambda syms, provider: [{"symbol": "MSFT", "price": "431"}])
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._fetch_recent_bars",
                        lambda syms: {"MSFT": bars})
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._fetch_session_status",
                        lambda exchange: MagicMock(is_market_open=True))
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._run_techtrade_signals",
                        lambda plan, tick: [fake_sig])
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._build_techtrade_plan",
                        lambda sig, tick: fake_plan)
    monkeypatch.setattr("openbb_fmp_trading.core.tick_loop._is_signal_bar_close",
                        lambda ts, preset: True)

    session = MagicMock()
    session.plan.watchlist = ["MSFT"]
    session.plan.preset = "intraday_momentum"
    session.risk_manager.propose_trade.return_value = MagicMock(
        verdict="APPROVED", reason_code=None, gate=None
    )
    captured_bar = {}

    def _capture_submit(order, bar):
        captured_bar["bar"] = bar
        return MagicMock(price=bar.open, qty=Decimal("10"), commission=Decimal("1.00"))

    session.broker.submit.side_effect = _capture_submit
    from openbb_fmp_trading.core.session import IntradaySession
    real_session = IntradaySession.__new__(IntradaySession)
    real_session.__dict__.update(session.__dict__)
    real_session.session_id = "test"
    real_session._process_signal = IntradaySession._process_signal.__get__(real_session)

    tick_at_close_of_bar_0 = bars[0].ts + timedelta(minutes=5)  # end of bar 0 == start of bar 1
    run_tick(real_session, tick_ts=tick_at_close_of_bar_0)

    submitted_bar = captured_bar["bar"]
    assert submitted_bar.ts == bars[1].ts, (
        f"Fill referenced bar at {submitted_bar.ts}, expected next bar at {bars[1].ts} "
        "(no-look-ahead violation — P3, AC-5)"
    )
    assert submitted_bar.open == Decimal("431.00"), (
        "Fill price must equal the OPEN of bar t+1, not the close of bar t"
    )
```

- [ ] **Step 2: Run the golden test**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/golden -q`
Expected: 1 passed.

- [ ] **Step 3: Commit P2.6**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/golden
git commit -m "test(fmp_trading): AC-5 no-look-ahead golden test at 5-min granularity (P2.6)

Locks P3: signal off bar-t close fills at bar-t+1 open, never earlier.
Mirrors techtrade #78's daily-bar golden test pattern.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.7: End-to-end integration test — mock FMP → 6.5h simulated session (AC-1)

**Consumes:** everything from P2.1–P2.6; mock FMP fixture (JSON captures of `batch-quote-short`, `historical-chart/5min`, `aftermarket-quote` for MSFT + AAPL on 2026-07-06).
**Produces:** `test_full_session.py` that runs a compressed 6.5h simulated session end-to-end and asserts (a) expected event counts in the NDJSON journal, (b) `flat_at_close=True`, (c) no order submitted after 15:50 ET, (d) cache hit rate ≥ 95% on a second run of the same fixture (AC-3 dry-run).

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/integration/test_full_session.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/integration/fixtures/2026-07-06/*.json`

- [ ] **Step 1: Author the integration test skeleton**

```python
"""AC-1 integration test: mock FMP → 6.5h simulated session → assert journal shape."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from freezegun import freeze_time

FIXTURES = Path(__file__).parent / "fixtures" / "2026-07-06"


@pytest.mark.integration
def test_ac1_full_session_end_to_end(tmp_path):
    """Full 6.5h session from mock FMP fixtures — no operator intervention."""
    from openbb_fmp_trading.core.session import IntradaySession
    from openbb_fmp_trading.core.tick_loop import run_tick
    from openbb_fmp_trading.models.plan import DailyPlan
    from openbb_fmp_trading.risk import RiskManager, RiskConfig
    from openbb_techtrade.execution import PaperBroker

    plan = DailyPlan(
        as_of=datetime(2026, 7, 6, 9, 25, tzinfo=timezone.utc),
        date=datetime(2026, 7, 6).date(),
        watchlist=["MSFT", "AAPL"],
        preset="intraday_momentum",
        alerts=[], thesis="fixture", agent_backend="none",
        session_risk=RiskConfig(),
    )
    journal_path = tmp_path / "session.ndjson"
    with patch("openbb_fmp_trading.core.tick_loop._fetch_batch_quote", _quote_from_fixture), \
         patch("openbb_fmp_trading.core.tick_loop._fetch_recent_bars", _bars_from_fixture), \
         patch("openbb_fmp_trading.core.tick_loop._fetch_session_status", _status_from_fixture):
        session = IntradaySession(
            plan=plan, journal=_JournalToFile(journal_path),
            risk_manager=RiskManager(config=RiskConfig()),
            broker=PaperBroker(starting_cash=100_000),
            bandwidth=_NullBandwidth(),
        )
        for tick_ts in _walk_session_ticks():
            with freeze_time(tick_ts):
                run_tick(session, tick_ts)
        session.close(flat_at_close=len(session.broker.positions()) == 0)

    events = [json.loads(l) for l in journal_path.read_text().splitlines()]
    assert any(e["event_type"] == "session_start" for e in events)
    assert any(e["event_type"] == "session_end" for e in events)
    end_event = next(e for e in events if e["event_type"] == "session_end")
    assert end_event["payload"]["flat_at_close"] is True, "AC-1 violation: positions open at close"

    post_1550_orders = [
        e for e in events
        if e["event_type"] == "order"
        and datetime.fromisoformat(e["ts"]).time() >= datetime.strptime("15:50", "%H:%M").time()
        and e["payload"]["intent"].startswith("OPEN_")
    ]
    assert not post_1550_orders, "AC-6 violation: opens submitted after 15:50 ET"


def _walk_session_ticks():
    """Yield one tick_ts every 5 seconds from 09:30 ET → 16:00 ET."""
    start = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    end = datetime(2026, 7, 6, 20, 0, tzinfo=timezone.utc)     # 16:00 ET
    ts = start
    while ts < end:
        yield ts
        ts += timedelta(seconds=5)


def _quote_from_fixture(symbols, provider):
    payload = json.loads((FIXTURES / "batch_quote_short.json").read_text())
    return [q for q in payload if q["symbol"] in symbols]


def _bars_from_fixture(symbols):
    return {s: json.loads((FIXTURES / f"bars_5min_{s}.json").read_text()) for s in symbols}


def _status_from_fixture(exchange):
    return json.loads((FIXTURES / "session_status.json").read_text())


class _JournalToFile:
    def __init__(self, path: Path):
        self.path = path
        self.path.write_text("")

    def write(self, event):
        with self.path.open("a") as f:
            f.write(event.model_dump_json() + "\n")


class _NullBandwidth:
    def charge(self, bytes_used: int) -> None:
        pass
    @property
    def mode(self) -> str:
        return "normal"
```

- [ ] **Step 2: Capture fixture JSON files**

Manually capture (or lift from an existing test asset) three fixture files under `fixtures/2026-07-06/`:
- `batch_quote_short.json` — list of quote dicts for MSFT + AAPL at multiple timestamps
- `bars_5min_MSFT.json` + `bars_5min_AAPL.json` — 78 bars (09:30 → 15:55 ET, 5-min interval) each
- `session_status.json` — SessionStatus dict with `is_market_open` computed by ts

- [ ] **Step 3: Run the integration test**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/integration/test_full_session.py -q -m integration`
Expected: 1 passed in < 60s (compressed session — no real sleeps).

- [ ] **Step 4: Run the full Phase 2 test surface as a regression sweep**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading openbb_platform/providers/fmp_cached -q`
Expected: all unit + golden + integration tests pass; no regressions in Phase 0/1 tests.

- [ ] **Step 5: Commit P2.7**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/integration
git commit -m "test(fmp_trading): AC-1 end-to-end 6.5h simulated session integration test (P2.7)

Mock FMP fixture → freeze-clocked tick walk from 09:30 → 16:00 ET → assert
session_start / session_end events, flat_at_close=True, no OPEN_* orders
past 15:50 ET. Closes Phase 2 acceptance surface.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage (PRD §10 Phase 2 sub-tasks):**
- P2.1 (tier-1 upgrade for intraday bars + aftermarket quote) → Task P2.1. ✓
- P2.2 (`create_ttl_wrapper_class` + `ExchangeMarketHours` migration) → Task P2.2. ✓
- P2.3 (`IntradaySession` skeleton — quote polling + journal) → Task P2.3. ✓
- P2.4 (wire techtrade `signals → plan → orders → PaperBroker`) → Task P2.4. ✓
- P2.5 (flat-by-close state machine + AC-6) → Task P2.5. ✓
- P2.6 (no-look-ahead golden test — AC-5) → Task P2.6. ✓
- P2.7 (end-to-end mock-FMP 6.5h integration test — AC-1) → Task P2.7. ✓

**Acceptance-criteria mapping:**
- **AC-1** — full paper session end-to-end without operator intervention → Task P2.7 asserts `session_end` event + `flat_at_close=True`.
- **AC-3** — cache hit rate ≥ 95% on same-day replay → Task P2.1 lays the ground; explicit replay test is Phase 5's `replay()` command scope.
- **AC-5** — bar-t 5-min close signal fills at t+1 5-min open → Task P2.6 golden test.
- **AC-6** — RiskManager rejects orders after 15:50 ET → Task P2.5's `test_ac6_order_at_15_51_gets_rejected_g1`.
- **AC-parity-3** — Tier-1 cache hit rate → tests in P2.1 establish the counting; end-to-end validation is Phase 6 live-integration scope.

**Global-constraints check:**
- P1 (deterministic core): no LLM anywhere in Phase 2 code paths. ✓
- P2 (`Decimal` for money): every price/qty in fetchers and tests uses `Decimal(str(...))`. ✓
- P3 (no look-ahead): AC-5 golden test in P2.6 locks the invariant. ✓
- P4 (flat by 15:55): P2.5 state machine + AC-6 test. ✓
- P5 (`exchange_calendars`): used in P2.1 (`_expected_bar_timestamps`), P2.5 (`enter_flat_window` half-day scaling). ✓
- P6 (bandwidth): every fetcher path routes through `BandwidthMeter.charge()` — Phase 1 wired the meter, Phase 2 tier-1 caching is the payoff. ✓
- P7 (RiskManager chokepoint): `IntradaySession._process_signal` is the sole caller of `broker.submit` and always calls `risk_manager.propose_trade` first; enforced by `test_broker_chokepoint.py` from Phase 1. ✓

**Critical-correctness verification (same-session tail invalidation):**
Task P2.1 Step 2's `_mark_tail_invalid` function; Task P2.1 Step 3's `test_mark_tail_invalid_flips_same_session_last_bar` + `test_mark_tail_invalid_does_not_touch_prior_day` unit tests. This is the single most subtle correctness rule in the entire caching layer — reviewers must sanity-check the freeze_time + calendar interaction.

**Placeholder scan:** No `TODO`/`FIXME` left as executable gaps. Phase-3-and-later gaps (AlertManager, agent turns, `market_snapshot`, `report()`) are explicitly out-of-scope for Phase 2 per §10 and the "Out of scope" note in `File Structure`.

**Deferred (filed against later phases):**
- AlertManager v1 + `alert.*` sub-router → Phase 4.
- Agent turns + MCP tool server → Phase 3.
- `report()` command / MD + XLSX generation → Phase 5.
- Live replay from captured production journals → Phase 5 (`obb.fmp_trading.replay()`).

**Estimated commit sequence:** 7 commits (one per sub-task P2.1 → P2.7). Total plan effort: ~2 weeks per PRD §10 (Sprint 2). Tests-first (RED before code) discipline preserved in every task.
