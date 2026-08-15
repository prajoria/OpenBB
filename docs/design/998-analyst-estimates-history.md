# Design — historical analyst-estimate snapshotting (#998 / #1024)

**Date:** 2026-07-21
**Author:** portfolio-team session
**Status:** DRAFT — awaiting user sign-off before #1025 implementation
**Related:** #998 epic · #1025 impl · #1026 widget wiring · #1022 (analyst_recommendations peer pattern)

## 1. Problem

Equity Profile §5C ("Historical EPS + Revenue Surprise") needs
per-quarter estimates **as they stood before each earnings release**
so surprise% is meaningful:

    surprise_pct(fiscal_period) = (actual_reported - estimate_as_of_release_date) / estimate_as_of_release_date

The current `analyst_estimates` table only stores the **latest**
consensus per `(symbol, fiscal_period)`. Once a quarter's estimate
gets refreshed post-earnings the pre-release value is lost.

## 2. Existing surface (#1024 spike findings)

**Table:** `analyst_estimates`
- Primary key: `id BIGINT AUTO_INCREMENT`
- Uniqueness: `UNIQUE KEY unique_symbol_date_period (symbol, date, period)`
- Fetcher: `openbb_fmp_cached/models/analyst_estimates.py:_store_in_cache`
- Insert strategy: `INSERT ... ON DUPLICATE KEY UPDATE` on every estimated_*
  field + `updated_at = CURRENT_TIMESTAMP`
- **Verdict:** OVERWRITES on `(symbol, date, period)`. Historical
  snapshots are LOST.

**Timestamp columns:**
- `cached_at` (originally set at first insert; docstring)
- `updated_at` (bumped on every overwrite via `ON DUPLICATE KEY UPDATE`)

`updated_at` tells us **when** the current row was last refreshed but
NOT **what the value was** at any prior point in time.

## 3. Design decisions

### 3.1 Storage model — companion history table (recommended)

Introduce a **companion table** rather than migrate the primary key on
the existing `analyst_estimates`. Rationale:

- Existing callers (any code doing `SELECT ... FROM analyst_estimates
  WHERE symbol = ? AND period = ?`) continue to work — they get the
  latest consensus, no query change needed.
- A schema migration on a production mirror table with
  `INSERT ... ON DUPLICATE KEY UPDATE` is high-risk: adding
  `snapshot_date` to the unique key changes upsert semantics from
  "overwrite" to "append", and existing rows all get the same
  `snapshot_date` (NULL or `updated_at`), which pollutes the history.
- The companion approach is fully additive: no existing behavior
  changes; new callers opt-in to `analyst_estimates_history`.

**Proposed schema:**

```sql
CREATE TABLE IF NOT EXISTS analyst_estimates_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    date DATE NOT NULL,                    -- fiscal_period_end_date (same key shape as parent)
    period VARCHAR(20) NOT NULL,           -- 'annual' | 'quarter'
    snapshot_date DATE NOT NULL,           -- date of the FETCH that captured this value
    -- Same value columns as analyst_estimates
    estimated_revenue_low DECIMAL(20,2),
    estimated_revenue_high DECIMAL(20,2),
    estimated_revenue_avg DECIMAL(20,2),
    estimated_eps_low DECIMAL(10,4),
    estimated_eps_high DECIMAL(10,4),
    estimated_eps_avg DECIMAL(10,4),
    number_analysts_estimated_revenue INT,
    number_analysts_estimated_eps INT,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_history_symbol_period_snapshot (symbol, date, period, snapshot_date),
    INDEX idx_history_symbol_period (symbol, period),
    INDEX idx_history_snapshot (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
```

Insert strategy: `INSERT ... ON DUPLICATE KEY UPDATE` on the same
composite key. Same-day re-fetches overwrite (idempotent); across-day
fetches append a new row.

### 3.2 Snapshot cadence — opportunistic (recommended)

**Recommendation:** every call to `FMPCachedAnalystEstimatesFetcher.aextract_data`
that hits the wire ALSO writes a row to `analyst_estimates_history`
with `snapshot_date = today()`.

- No new infrastructure (no cron job, no scheduler config).
- Coverage naturally follows demand — symbols the app cares about
  get snapshotted whenever they're viewed.
- Symbols never viewed accumulate no history; that's fine because
  §5C only renders for symbols the user is looking at.

**Fallback:** if coverage gaps appear in production (users complain
"Q1 2026 shows no surprise data"), add an off-hours cron that walks
held symbols nightly. File that as a separate issue **only when
observed**, not preemptively.

### 3.3 Retention — 2 years default, sweep older nightly

- 2 years × 4 fiscal_period × ~4 refetches/quarter × ~5000 tickers ≈
  ~160k rows. Trivial for MySQL; no partitioning needed.
- Nightly sweep: `DELETE FROM analyst_estimates_history WHERE
  snapshot_date < DATE_SUB(CURRENT_DATE, INTERVAL 2 YEAR)`. File as
  a separate ops issue once the table starts landing rows;
  premature optimization otherwise.

### 3.4 Exact-period query helper — `get_estimate_for_period_before_release`

New public function in the model:

```python
def get_estimate_for_period_before_release(
    symbol: str,
    fiscal_period_end: date,
    release_date: date,
    period: str = "quarter",
) -> AnalystEstimatesData | None:
    """Return the estimate for this exact fiscal period as it stood on or
    before its release date. None if no pre-release snapshot exists."""
    query = """
    SELECT * FROM analyst_estimates_history
    WHERE symbol = %s AND date = %s AND period = %s
      AND snapshot_date <= %s
    ORDER BY snapshot_date DESC
    LIMIT 1
    """
    ...
```

The widget first resolves the issuer's actual latest fiscal-period end and
earnings-release date from provider data, then calls this helper with those
exact values. It **must not** replace a missing snapshot with the preceding
fiscal period: returning `None` is the intentional loud state for a latest
period without a pre-release snapshot. The lower-level `get_estimate_as_of`
helper remains available for callers that already have an exact as-of date.

## 4. Migration plan

Zero-risk because it's a NEW table. Order:

1. Land DDL for `analyst_estimates_history` via a new
   `create_analyst_estimates_history_table()` in `cache_schema.py`.
   Add to `FLATTENED_TABLES` registry.
2. In `FMPCachedAnalystEstimatesFetcher.aextract_data`, wrap the
   existing `_store_in_cache` call so it ALSO calls
   `_store_history(symbol, fmp_data, snapshot_date=today)`.
3. Ship `get_estimate_for_period_before_release()` helper.
4. Wire Equity Profile §5C to compute real surprise% via #1026.

No backfill: the history table is empty until first fetch after ship;
that's fine because surprise% only becomes possible for post-ship
quarters anyway.

## 5. Non-goals

- Nightly cron backfill — deferred (see §3.2 fallback).
- Retention sweep automation — deferred (see §3.3).
- Cross-provider snapshotting (yfinance / intrinio historical estimates
  would need their own tables) — out of scope for #998.

## 6. Sign-off checklist

- [ ] Companion table approach approved (vs primary-key migration on
  existing table)
- [ ] Opportunistic snapshotting approved (vs nightly cron)
- [ ] Column set on `analyst_estimates_history` matches what §5C needs
- [ ] Retention deferral acceptable (2-year sweep filed as separate
  issue when table starts growing)

Once signed off, #1025 lands the DDL + fetcher wiring; #1026 lands the
widget compute.
