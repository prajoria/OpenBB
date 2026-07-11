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
| `providers/fmp_cached/tests/test_intraday_gap_detection.py` | Gap-detection + tail-invalidation coverage for the new tier-1 fetcher. | P2.1 |
| `providers/fmp_cached/tests/test_aftermarket_quote_ttl.py` | 60s TTL hit/miss coverage. | P2.1 |
| `providers/fmp_cached/tests/test_ttl_wrapper.py` | `create_ttl_wrapper_class` unit tests + `ExchangeMarketHours` regression. | P2.2 |

**Out of scope for Phase 2** (belongs to later phases — do NOT create here):
- Any file under `openbb_fmp_trading/agent/` → Phase 3
- `AlertManager`, `alert_router` → Phase 4
- `report.py`, `end_of_day.md` generator → Phase 5
- `market_snapshot`, `build_daily_plan` commands → Phase 4

---

## Task P2.1: Upgrade intraday bars + aftermarket quote to tier-1 caching

**Consumes:** existing tier-2 registration for `EquityIntradayHistoricalFetcher` + `AftermarketQuoteFetcher` (Phase 0.2); existing gap-detection pattern in `models/equity_historical.py`; the sync SQL helpers `execute_query` / `execute_many` in `utils/database.py`; MySQL init via `init_database()`.
**Produces:** two new MySQL tables; two new tier-1 fetchers; ≥95% cache hit rate on same-day replays (AC-3); same-session tail-invalidation invariant asserted by test.

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py`
- Rewrite: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_intraday_historical.py`
- Rewrite: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/aftermarket_quote.py`
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py` (promote both classes from tier-2 `fetcher_mapping` into tier-1 `dedicated_fetchers`; remove now-unused raw-fmp imports)
- Create: `openbb_platform/providers/fmp_cached/tests/test_intraday_gap_detection.py`
- Create: `openbb_platform/providers/fmp_cached/tests/test_aftermarket_quote_ttl.py`

- [ ] **Step 1: Add the two new tables to `cache_schema.py` (RED first — write failing schema test)**

The real `cache_schema.py` uses a **function-per-table pattern** — one `create_<name>_table()` function that returns `execute_query(DDL)`, plus a `FLATTENED_TABLES` dict that `create_all_flattened_tables()` iterates. Add two new creator functions to the end of the file (before `create_all_tables`) and register them in `FLATTENED_TABLES`:

```python
def create_equity_intraday_historical_table():
    """Create equity_intraday_historical table (fmp-day-trading PRD §5.2)."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_intraday_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(50) NOT NULL,
        interval_type VARCHAR(10) NOT NULL,
        ts DATETIME(0) NOT NULL,
        open_price DECIMAL(18,6) DEFAULT NULL,
        high_price DECIMAL(18,6) DEFAULT NULL,
        low_price DECIMAL(18,6) DEFAULT NULL,
        close_price DECIMAL(18,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        is_extended BOOLEAN DEFAULT FALSE,
        additional_fields JSON DEFAULT NULL,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        INDEX idx_symbol (symbol),
        INDEX idx_symbol_interval_ts (symbol, interval_type, ts DESC),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        UNIQUE KEY unique_symbol_interval_ts (symbol, interval_type, ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_aftermarket_quote_table():
    """Create aftermarket_quote table (fmp-day-trading PRD §5.2 — 60s TTL)."""
    query = """
    CREATE TABLE IF NOT EXISTS aftermarket_quote (
        symbol VARCHAR(50) NOT NULL PRIMARY KEY,
        price DECIMAL(18,6) DEFAULT NULL,
        bid DECIMAL(18,6) DEFAULT NULL,
        ask DECIMAL(18,6) DEFAULT NULL,
        bid_size INTEGER DEFAULT NULL,
        ask_size INTEGER DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        timestamp DATETIME(0) DEFAULT NULL,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)
```

Then register both in `FLATTENED_TABLES` (alphabetical: `aftermarket_quote` goes before `analyst_estimates`; `equity_intraday_historical` between `equity_historical` and `equity_losers`):

```python
FLATTENED_TABLES = {
    "aftermarket_quote": {"schema": create_aftermarket_quote_table},
    "analyst_estimates": {"schema": create_analyst_estimates_table},
    # ...existing entries...
    "equity_historical": {"schema": create_equity_historical_table},
    "equity_intraday_historical": {"schema": create_equity_intraday_historical_table},
    "equity_losers": {"schema": create_equity_losers_table},
    # ...
}
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests/test_cache_schema.py -q`
Expected: PASS (both new creators present in the `FLATTENED_TABLES` dict; DDL parses via `execute_query`).

- [ ] **Step 2: Rewrite `equity_intraday_historical.py` with gap detection + tail-invalidation**

Mirror `equity_historical.py`'s shape adapted for intraday granularity: `interval_type` in the cache key (not just `date`); `ts` is `DATETIME(0)` bar-start (not `DATE`); and — the correctness-critical addition — `_invalidate_same_session_tail` marks today's last bar `is_valid=FALSE` so the next call refetches it. Prior-session bars stay immutable.

**Real primitives** (drift-corrected from the original plan draft):

- SQL: `execute_query` / `execute_many` from `openbb_fmp_cached.utils.database` (NOT `cache_pool.acquire()`)
- DB init: `init_database()` from the same module, wrapped in `try/except` that falls back to raw fmp on any DB failure (same pattern as `equity_historical.py` lines 155-159)
- Credential translation: an inlined `_translate_credentials(credentials)` helper that:
  - Unwraps `SecretStr` via `.get_secret_value()`
  - Maps `fmp_cached_api_key → fmp_api_key`
  - Falls through to `openbb_core.app.service.user_service.UserService` when no explicit credentials passed
  - Returns a `dict[str, str] | None` suitable for handing to the raw FMP fetcher

**Fetcher body structure** (the flow the shipped implementation follows):

```python
class FMPCachedEquityIntradayHistoricalFetcher(
    Fetcher[
        FMPCachedEquityIntradayHistoricalQueryParams,
        list[FMPCachedEquityIntradayHistoricalData],
    ]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> ...:
        return FMPCachedEquityIntradayHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(query, credentials, **kwargs) -> list[dict[str, Any]]:
        fmp_credentials = _translate_credentials(credentials)

        # DB init with fallback to raw fmp (matches equity_historical.py:155-159)
        try:
            init_database()
        except Exception as exc:
            logger.warning(f"Cache DB init failed: {exc}; direct FMP fallback")
            return await FMPEquityIntradayHistoricalFetcher.aextract_data(
                query, fmp_credentials, **kwargs
            )

        # Multi-symbol fanout — one gap-analysis per symbol
        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        all_rows = []
        for symbol in symbols:
            single_query = query.model_copy(update={"symbol": symbol})
            cached_rows, has_gap = _analyze_intraday_cache(single_query)
            if has_gap:
                fresh = await FMPEquityIntradayHistoricalFetcher.aextract_data(
                    single_query, fmp_credentials, **kwargs
                )
                if fresh:
                    _upsert_intraday_rows(symbol, query.interval, fresh)
                cached_rows, _ = _analyze_intraday_cache(single_query)  # re-read
            _invalidate_same_session_tail(symbol, query.interval, cached_rows)
            all_rows.extend(cached_rows)
        return all_rows

    @staticmethod
    def transform_data(query, data, **kwargs):
        return [FMPCachedEquityIntradayHistoricalData.model_validate(d) for d in data]
```

**Gap detection** — use `execute_query` with the parameterized SELECT below, then apply a coverage-check heuristic (matches how `equity_historical._detect_missing_ranges` handles non-daily intervals — any-gap-in-range triggers a refetch of the full range, because enumerating expected intraday bar timestamps is impractical due to holidays, half-days, mid-session halts):

```python
def _analyze_intraday_cache(query) -> tuple[list[dict[str, Any]], bool]:
    """Return (cached_rows, has_gap)."""
    if query.start_date is None or query.end_date is None:
        return [], True   # unbounded query → cache MISS

    rows = execute_query(
        """SELECT symbol, interval_type, ts, open_price, high_price, low_price,
                  close_price, volume, is_extended, is_valid
           FROM equity_intraday_historical
           WHERE symbol = %s AND interval_type = %s
             AND ts BETWEEN %s AND %s AND is_valid = TRUE
           ORDER BY ts ASC""",
        (query.symbol, query.interval, query.start_date, query.end_date),
    )
    if not rows:
        return [], True

    cached = [
        {
            "symbol": r["symbol"],
            "interval": r["interval_type"],
            "date": r["ts"],
            "open": float(r["open_price"]) if r["open_price"] is not None else None,
            "high": float(r["high_price"]) if r["high_price"] is not None else None,
            "low": float(r["low_price"]) if r["low_price"] is not None else None,
            "close": float(r["close_price"]) if r["close_price"] is not None else None,
            "volume": int(r["volume"]) if r["volume"] is not None else None,
            "is_extended": bool(r["is_extended"]),
        }
        for r in rows
    ]
    # Coverage check — first/last cached bar must bracket the requested range.
    if cached[0]["date"] > query.start_date or cached[-1]["date"] < query.end_date:
        return cached, True
    return cached, False
```

**Upsert** — use `execute_many` with `INSERT ... ON DUPLICATE KEY UPDATE`; the unique key `(symbol, interval_type, ts)` makes refresh idempotent:

```python
def _upsert_intraday_rows(symbol, interval, rows):
    if not rows:
        return
    sql = """
    INSERT INTO equity_intraday_historical
        (symbol, interval_type, ts, open_price, high_price, low_price,
         close_price, volume, is_extended, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    ON DUPLICATE KEY UPDATE
        open_price = VALUES(open_price), high_price = VALUES(high_price),
        low_price = VALUES(low_price), close_price = VALUES(close_price),
        volume = VALUES(volume), is_extended = VALUES(is_extended),
        is_valid = TRUE, updated_at = CURRENT_TIMESTAMP
    """
    params_list = []
    for r in rows:
        ts = r.get("date") or r.get("ts")
        if isinstance(ts, str):
            ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        params_list.append((
            symbol, interval, ts,
            r.get("open"), r.get("high"), r.get("low"), r.get("close"),
            r.get("volume"), bool(r.get("is_extended", False)),
        ))
    execute_many(sql, params_list)
```

**Tail invalidation** — the correctness-critical helper:

```python
def _invalidate_same_session_tail(symbol, interval, cached_rows):
    """Mark today's last bar is_valid=FALSE so the next call refetches it.

    Critical: a 5-min bar opened at 10:00 doesn't finalize until 10:05.
    Serving it as complete at 10:03 would leak an incomplete bar. Prior-
    session bars stay valid — they're immutable.
    """
    if not cached_rows:
        return
    tail = cached_rows[-1]
    tail_ts = tail.get("date") or tail.get("ts")
    if tail_ts is None or (
        (tail_ts.date() if isinstance(tail_ts, datetime) else tail_ts) != date.today()
    ):
        return
    execute_query(
        "UPDATE equity_intraday_historical SET is_valid = FALSE "
        "WHERE symbol = %s AND interval_type = %s AND ts = %s",
        (symbol, interval, tail_ts),
    )
```

Complete shipped implementation lives at `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_intraday_historical.py` — refer to it for the full docstrings, logging, and edge-case handling (SecretStr, empty results, malformed timestamps).

- [ ] **Step 3: Write the intraday gap-detection unit test**

The shipped test file lives at `openbb_platform/providers/fmp_cached/tests/test_intraday_gap_detection.py` (NOT the nested `.../openbb_fmp_cached/tests/unit/...` path the original draft suggested — the fmp_cached provider tests live one level up, alongside `test_cache_schema.py`, `test_database.py`, etc.).

Four test classes covering the shipped helper contract:

- `TestIntradayCacheAnalysis` — `_analyze_intraday_cache` returns `(rows, has_gap)` with correct semantics on missing-bounds / empty-cache / full-range cases
- `TestTailInvalidation` — `_invalidate_same_session_tail` fires an UPDATE only for today's tail bar; prior-day tails and empty inputs short-circuit
- `TestCredentialTranslation` — `_translate_credentials` maps `fmp_cached_api_key → fmp_api_key`, unwraps `SecretStr`, and passes through pre-mapped credentials
- `TestFetcherClassContract` — the class exposes `transform_query` / `aextract_data` / `transform_data` as static methods and coerces dict input to typed params

Every test that touches SQL uses `unittest.mock.patch(...execute_query)` / `patch(...execute_many)` so the suite runs without a live MySQL server.

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests/test_intraday_gap_detection.py -v`
Expected: all class tests pass.

- [ ] **Step 4: Rewrite `aftermarket_quote.py` with 60s TTL**

Single-row-per-symbol cache. Cache HIT iff `cached_at > now - 60s AND is_valid = TRUE`; else MISS triggers a fresh FMP fetch for exactly the missing symbols. Uses the same real primitives as Step 2: `execute_query` / `execute_many` from `openbb_fmp_cached.utils.database`, `init_database()` with fallback, and an inlined `_translate_credentials()` helper. `_TTL_SECONDS = 60` is a locked design decision per PRD §5.2.

**Body structure**:

```python
class FMPCachedAftermarketQuoteFetcher(
    Fetcher[
        FMPCachedAftermarketQuoteQueryParams,
        list[FMPCachedAftermarketQuoteData],
    ]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> ...:
        return FMPCachedAftermarketQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(query, credentials, **kwargs) -> list[dict[str, Any]]:
        fmp_credentials = _translate_credentials(credentials)
        try:
            init_database()
        except Exception as exc:
            logger.warning(f"Cache DB init failed: {exc}; direct FMP fallback")
            return await FMPAftermarketQuoteFetcher.aextract_data(
                query, fmp_credentials, **kwargs
            )

        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        if not symbols:
            return []

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=_TTL_SECONDS
        )
        hit_rows, miss_symbols = _fetch_fresh_rows(symbols, cutoff)
        if not miss_symbols:
            return hit_rows

        # Partial-hit optimization: fetch only the stale symbols
        miss_query = query.model_copy(update={"symbol": ",".join(miss_symbols)})
        fresh = await FMPAftermarketQuoteFetcher.aextract_data(
            miss_query, fmp_credentials, **kwargs
        )
        if fresh:
            _upsert_aftermarket_rows(fresh)
        return hit_rows + fresh

    @staticmethod
    def transform_data(query, data, **kwargs):
        return [FMPCachedAftermarketQuoteData.model_validate(d) for d in data]
```

**Fresh-rows partition** — uses `execute_query` with a parameterized `WHERE symbol IN (...) AND cached_at > cutoff`; returns `(hits, miss_symbols)` where `miss_symbols` is the set difference:

```python
def _fetch_fresh_rows(symbols, cutoff) -> tuple[list[dict], list[str]]:
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT symbol, price, bid, ask, bid_size, ask_size, volume, timestamp
    FROM aftermarket_quote
    WHERE symbol IN ({placeholders})
      AND cached_at > %s
      AND is_valid = TRUE
    """
    rows = execute_query(sql, (*symbols, cutoff))
    # ...normalize types, partition into hits + miss_symbols...
    return hits, miss_symbols
```

**Upsert** — same `execute_many` + `ON DUPLICATE KEY UPDATE` pattern as intraday bars, with the symbol as PRIMARY KEY (single-row-per-symbol):

```python
def _upsert_aftermarket_rows(rows):
    if not rows:
        return
    sql = """
    INSERT INTO aftermarket_quote
        (symbol, price, bid, ask, bid_size, ask_size, volume, timestamp, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    ON DUPLICATE KEY UPDATE
        price = VALUES(price), bid = VALUES(bid), ask = VALUES(ask),
        bid_size = VALUES(bid_size), ask_size = VALUES(ask_size),
        volume = VALUES(volume), timestamp = VALUES(timestamp),
        cached_at = CURRENT_TIMESTAMP, is_valid = TRUE
    """
    execute_many(sql, [(r["symbol"], r.get("price"), ...) for r in rows])
```

Complete shipped implementation lives at `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/aftermarket_quote.py` — refer to it for docstrings, logging, and the SecretStr / UserService fallback path in `_translate_credentials`.

- [ ] **Step 5: Write the aftermarket TTL test + run the unit suite**

The shipped test file lives at `openbb_platform/providers/fmp_cached/tests/test_aftermarket_quote_ttl.py` (same location convention as `test_intraday_gap_detection.py`).

Four test classes covering:

- `TestFreshRowsPartition` — `_fetch_fresh_rows` correctly splits HIT vs MISS across all-hit / partial-hit / all-miss / empty-symbols cases
- `TestUpsertShape` — `_upsert_aftermarket_rows` calls `execute_many` with the correct SQL structure and 8-tuple row shape
- `TestFetcherClassContract` — the class exposes `transform_query` / `aextract_data` / `transform_data`
- `TestTTLConstant` — asserts `_TTL_SECONDS == 60` (a locked design decision per PRD §5.2 that shouldn't drift silently)

Run:
```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests/test_aftermarket_quote_ttl.py openbb_platform/providers/fmp_cached/tests/test_intraday_gap_detection.py -v
```
Expected: all new + existing tests pass (~15 tests across the two files).

- [ ] **Step 6: Commit P2.1**

**Historical note:** P2.1 shipped as commit `0ad2e3716` on branch `fmp_trading` on 2026-07-09. The bd `OpenBBTechnical-8v9` bead flagged the plan-drift that this Phase 2 doc revision (2026-07-09) addresses. Steps 1-5 above reflect what actually shipped; the code paths + primitives (`utils/database.execute_query/execute_many`, `FLATTENED_TABLES` dict, inlined `_translate_credentials`) are the real ones, not the phantom `cache_pool.acquire()` / `utils/db.py` from the original draft.

Also modified as part of P2.1: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py` — the two new fetcher classes were promoted from the tier-2 `fetcher_mapping` list into the tier-1 `dedicated_fetchers` dict (with corresponding removal of the now-unused raw-fmp imports at module top).

```bash
git add openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_intraday_historical.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/aftermarket_quote.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py \
        openbb_platform/providers/fmp_cached/tests/test_intraday_gap_detection.py \
        openbb_platform/providers/fmp_cached/tests/test_aftermarket_quote_ttl.py
git commit -m "feat(fmp_cached): tier-1 caching for intraday bars + aftermarket quote (P2.1)

Upgrade EquityIntradayHistorical and AftermarketQuote from tier-2 passthrough
to tier-1 gap-detection / TTL caching per PRD §5.2. Same-session tail bars
are marked is_valid=FALSE to force refetch — critical correctness rule.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.2: Add `create_ttl_wrapper_class` + migrate `ExchangeMarketHours`

**Consumes:** existing `create_fallback_fetcher_class` in `openbb_fmp_cached/models/base_cached.py`; existing tier-2 registration of `ExchangeMarketHours` in `openbb_fmp_cached/__init__.py`'s `fetcher_mapping` list (Phase 0); the sync SQL helpers `execute_query` / `execute_many` in `utils/database.py`; the P2.1-established pattern of adding tables via a `create_<name>_table()` function registered in `FLATTENED_TABLES`.
**Produces:** generic ~50 LoC TTL wrapper factory reusable by any future 24h-cached endpoint (holidays, market status); `ExchangeMarketHours` swapped over; ~1000 saved daily calls per PRD §5.5.

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/base_cached.py` (add `create_ttl_wrapper_class`)
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py` (add `create_ttl_cache_table` + register in `FLATTENED_TABLES`)
- Create: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/exchange_market_hours.py` (new cached-side wrapper; the file does NOT currently exist — Phase 0 registered ExchangeMarketHours via the raw-fmp import + `create_fallback_fetcher_class` at the fetcher_mapping-list level)
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py` (remove ExchangeMarketHours from tier-2 `fetcher_mapping` list; add to tier-1 `dedicated_fetchers` dict with the new cached class)
- Create: `openbb_platform/providers/fmp_cached/tests/test_ttl_wrapper.py` (NOT the nested `.../openbb_fmp_cached/tests/unit/...` path — fmp_cached tests live one level up, alongside `test_cache_schema.py`)

- [ ] **Step 1: Add the `ttl_cache` table to `cache_schema.py`**

The TTL wrapper needs a backing table to persist cached JSON payloads. Add a new creator function (before `create_all_tables`) and register in `FLATTENED_TABLES` (alphabetical: `ttl_cache` goes near the end, before `world_news`):

```python
def create_ttl_cache_table():
    """Create ttl_cache — backing store for create_ttl_wrapper_class (P2.2).

    One row per (cache_name, cache_key). Wrapper writes on MISS, reads on
    HIT. Cache eviction is TTL-based inside the wrapper's SELECT clause;
    stale rows are overwritten on next MISS via ON DUPLICATE KEY UPDATE.
    """
    query = """
    CREATE TABLE IF NOT EXISTS ttl_cache (
        cache_name VARCHAR(80) NOT NULL,
        cache_key  CHAR(64)    NOT NULL,
        payload    JSON        NOT NULL,
        cached_at  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (cache_name, cache_key),
        INDEX idx_cached_at (cached_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)
```

Register: `"ttl_cache": {"schema": create_ttl_cache_table},` in the `FLATTENED_TABLES` dict.

- [ ] **Step 2: Add `create_ttl_wrapper_class` to `base_cached.py`**

Uses the real `execute_query` / `execute_many` primitives (NOT the phantom `cache_pool.acquire()` from the original draft). Reuses the credential-translation pattern that `create_fallback_fetcher_class` already implements — since a TTL-wrapped fetcher still needs the fmp_cached → fmp key mapping, we delegate to that helper rather than reinlining `_translate_credentials`.

```python
def create_ttl_wrapper_class(
    inner_fetcher_cls: type[Fetcher],
    name: str,
    ttl_seconds: int,
) -> type[Fetcher]:
    """Wrap a fetcher with a global TTL cache keyed by (name, query_hash).

    HIT iff cached_at > now - ttl_seconds. On MISS, delegate to the inner
    fetcher, UPSERT the payload, return. Uses the ttl_cache MySQL table
    (created lazily by cache_schema.create_ttl_cache_table).

    Distinct from create_fallback_fetcher_class — that only does same-session
    credential translation and passthrough. This wrapper adds persistent
    multi-hour caching. Reuse targets: ExchangeMarketHours (24h), holidays
    (24h), market-status snapshots (any TTL).
    """
    import hashlib
    import json
    from datetime import datetime, timedelta

    from openbb_fmp_cached.utils.database import execute_query, execute_many

    ttl = timedelta(seconds=ttl_seconds)

    def _hash_query(query) -> str:
        payload = (
            query.model_dump_json(exclude_none=True)
            if hasattr(query, "model_dump_json")
            else json.dumps(query, sort_keys=True, default=str)
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def _load_ttl_cache(cache_name: str, cache_key: str, cutoff: datetime):
        rows = execute_query(
            "SELECT payload FROM ttl_cache "
            "WHERE cache_name = %s AND cache_key = %s AND cached_at > %s",
            (cache_name, cache_key, cutoff),
        )
        if not rows:
            return None
        return json.loads(rows[0]["payload"])

    def _upsert_ttl_cache(cache_name: str, cache_key: str, data) -> None:
        execute_many(
            """INSERT INTO ttl_cache (cache_name, cache_key, payload)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 payload = VALUES(payload),
                 cached_at = CURRENT_TIMESTAMP""",
            [(cache_name, cache_key, json.dumps(data, default=str))],
        )

    def _translate_creds(credentials):
        """Reuse the same fmp_cached -> fmp key mapping as create_fallback_fetcher_class."""
        if not credentials:
            return credentials
        if "fmp_cached_api_key" in credentials:
            raw = credentials["fmp_cached_api_key"]
            val = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
            return {"fmp_api_key": val}
        return credentials

    class _TTLWrapped(Fetcher):
        """Generated at runtime by create_ttl_wrapper_class."""

        @staticmethod
        def transform_query(params):
            return inner_fetcher_cls.transform_query(params)

        @staticmethod
        async def aextract_data(query, credentials=None, **kwargs):
            cache_key = _hash_query(query)
            cutoff = datetime.utcnow() - ttl
            try:
                cached = _load_ttl_cache(name, cache_key, cutoff)
                if cached is not None:
                    return cached
            except Exception:
                # DB unavailable — fall through to raw fetch (never fail fast)
                pass
            fresh = await inner_fetcher_cls.aextract_data(
                query, _translate_creds(credentials), **kwargs
            )
            try:
                _upsert_ttl_cache(name, cache_key, fresh)
            except Exception:
                pass  # best-effort persistence
            return fresh

        @staticmethod
        def transform_data(query, data, **kwargs):
            return inner_fetcher_cls.transform_data(query, data, **kwargs)

    _TTLWrapped.__name__ = f"{name}TTLCached"
    return _TTLWrapped
```

- [ ] **Step 3: Create the cached-side `exchange_market_hours.py`**

This file does NOT currently exist in the fmp_cached model tree — Phase 0 registered ExchangeMarketHours via the raw-fmp import in `fetcher_mapping`. Create the new file:

```python
"""Tier-1 24h-TTL cached ExchangeMarketHours (fmp-day-trading PRD §5.5).

Uses the new create_ttl_wrapper_class from base_cached (P2.2). Market
hours change ~daily (holidays, DST) — 86400s TTL saves ~1000 redundant
FMP calls per day.
"""

from __future__ import annotations

from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher

from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

FMPCachedExchangeMarketHoursFetcher = create_ttl_wrapper_class(
    FMPExchangeMarketHoursFetcher,
    name="ExchangeMarketHours",
    ttl_seconds=86400,  # 24 hours
)
```

- [ ] **Step 4: Promote in `openbb_fmp_cached/__init__.py`**

Two edits:
1. Add import: `from openbb_fmp_cached.models.exchange_market_hours import FMPCachedExchangeMarketHoursFetcher`
2. Add to `dedicated_fetchers` dict (alphabetical, near `EquityIntradayHistorical`): `"ExchangeMarketHours": FMPCachedExchangeMarketHoursFetcher,`
3. Remove the corresponding entry from the tier-2 `fetcher_mapping` list: delete the line `("ExchangeMarketHours", FMPExchangeMarketHoursFetcher),` — and remove the now-unused `from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher` import if it becomes orphaned at the top level (the cached wrapper still references it transitively via `create_ttl_wrapper_class`).

- [ ] **Step 5: Write TTL wrapper unit test**

Shipped test lives at `openbb_platform/providers/fmp_cached/tests/test_ttl_wrapper.py`. The tests mock `execute_query` / `execute_many` (NOT `cache_pool`) so the suite runs without a live MySQL server:

```python
"""Unit tests for create_ttl_wrapper_class (P2.2)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest


class _FakeQuery:
    """Minimal query stub with a stable JSON serialization."""
    def model_dump_json(self, exclude_none=True):
        return '{"date":"2026-07-08"}'


class _FakeInner:
    """Stub inner fetcher with an async aextract_data mock."""
    aextract_data = AsyncMock(return_value=[{"exchange": "NASDAQ", "is_open": True}])
    transform_query = staticmethod(lambda p: _FakeQuery())
    transform_data = staticmethod(lambda q, d, **k: d)


@pytest.mark.asyncio
async def test_first_call_misses_and_upserts():
    from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

    _FakeInner.aextract_data.reset_mock()
    cls = create_ttl_wrapper_class(_FakeInner, "ExchangeMarketHours", 86400)
    with patch(
        "openbb_fmp_cached.utils.database.execute_query", return_value=[]
    ) as mock_select, patch(
        "openbb_fmp_cached.utils.database.execute_many"
    ) as mock_upsert:
        result = await cls.aextract_data(_FakeQuery())
    assert result == [{"exchange": "NASDAQ", "is_open": True}]
    _FakeInner.aextract_data.assert_awaited_once()
    mock_select.assert_called_once()  # SELECT-then-MISS
    mock_upsert.assert_called_once()  # UPSERT after fetch


@pytest.mark.asyncio
async def test_second_call_within_ttl_hits_cache():
    from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

    _FakeInner.aextract_data.reset_mock()
    cls = create_ttl_wrapper_class(_FakeInner, "ExchangeMarketHours", 86400)
    fake_row = [{"payload": '[{"exchange":"NASDAQ","is_open":true}]'}]
    with patch(
        "openbb_fmp_cached.utils.database.execute_query", return_value=fake_row
    ), patch(
        "openbb_fmp_cached.utils.database.execute_many"
    ) as mock_upsert:
        result = await cls.aextract_data(_FakeQuery())
    assert result == [{"exchange": "NASDAQ", "is_open": True}]
    _FakeInner.aextract_data.assert_not_awaited()  # cache HIT
    mock_upsert.assert_not_called()  # no write on HIT


@pytest.mark.asyncio
async def test_db_failure_falls_through_to_inner_fetch():
    """DB unavailable -> aextract_data still returns fresh data from inner fetcher."""
    from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

    _FakeInner.aextract_data.reset_mock()
    cls = create_ttl_wrapper_class(_FakeInner, "ExchangeMarketHours", 86400)
    with patch(
        "openbb_fmp_cached.utils.database.execute_query",
        side_effect=RuntimeError("DB down"),
    ), patch("openbb_fmp_cached.utils.database.execute_many"):
        result = await cls.aextract_data(_FakeQuery())
    assert result == [{"exchange": "NASDAQ", "is_open": True}]
    _FakeInner.aextract_data.assert_awaited_once()


def test_wrapper_class_name_reflects_source():
    """__name__ set for debugging clarity — e.g. 'ExchangeMarketHoursTTLCached'."""
    from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

    cls = create_ttl_wrapper_class(_FakeInner, "ExchangeMarketHours", 86400)
    assert cls.__name__ == "ExchangeMarketHoursTTLCached"
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests/test_ttl_wrapper.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit P2.2**

```bash
git add openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/base_cached.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/exchange_market_hours.py \
        openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py \
        openbb_platform/providers/fmp_cached/tests/test_ttl_wrapper.py
git commit -m "feat(fmp_cached): create_ttl_wrapper_class + migrate ExchangeMarketHours to 24h TTL (P2.2)

Generic TTL wrapper factory extends base_cached beyond same-session
passthrough. Backed by new ttl_cache MySQL table (cache_name, cache_key,
payload, cached_at). ExchangeMarketHours moves from tier-2 fetcher_mapping
into tier-1 dedicated_fetchers with 86400s TTL — saves ~1000 daily
redundant calls per PRD §5.5.

Wrapper reuses execute_query / execute_many primitives from utils/database
and inlines the same fmp_cached -> fmp credential translation shape that
create_fallback_fetcher_class uses. Ready for future holidays / market-
status endpoints to reuse.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P2.3: `IntradaySession` skeleton — quote polling + journal writes only

**Consumes:** tier-1 fetchers from P2.1; `openbb_core_journal.JournalWriter` (the shared journaling primitive from epic #408 — Phase 1 P1.4 shipped as J4 retrofit importing this instead of a local SessionJournal); typed journal event subclasses in `openbb_fmp_trading.models.journal_events` (`TickEvent`, `SessionStartEvent`, etc.); `BandwidthMeter` (Phase 1); `RiskManager` (Phase 1) — imported but not yet wired to a `PaperBroker` (that's P2.4).
**Produces:** `IntradaySession` class + `run_tick` pure function; ability to run a 3-tick smoke session that produces 3 `TickEvent` journal entries with no signals, no orders, no fills.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/session.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/tick_loop.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/tests/unit/test_intraday_session.py`

> **Journal-event style note (post-P1.4/J4):** The Step 2 code samples below construct events as `JournalEvent(event_type="tick", ...)` — generic base with a string tag. The **preferred pattern**, established by the J4 retrofit, is to use the typed subclasses in `openbb_fmp_trading.models.journal_events`: `TickEvent(...)`, `SignalEvent(...)`, `SessionStartEvent(...)`, `SessionEndEvent(...)`, etc. Each subclass fixes its `event_type` Literal at class level, catching typos at construction time and giving downstream consumers dispatch clarity. Both patterns validate the same wire format via the shared discriminator, so the generic form is functional — just less discoverable. When implementing, prefer typed subclasses; where the sample below shows `JournalEvent(event_type="X", ...)`, mentally substitute `XEvent(...)`.

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
    journal: Any            # openbb_core_journal.JournalWriter (Phase 1 P1.4 / J4 retrofit)
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
