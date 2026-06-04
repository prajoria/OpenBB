# 03 — fmp_cached Data Bundle & Data Layer

**GitHub:** [#40](https://github.com/prajoria/OpenBB/issues/40) · **Depends on:** [#39](https://github.com/prajoria/OpenBB/issues/39)
**Beads:** OpenBB-crw, OpenBB-b5r, OpenBB-wz7

Ingests the existing `openbb_fmp_cache` MySQL cache into a fast columnar store the engines
read directly — **no new download path, no second source of truth**.

---

## 1. Bundle schema + columnar store

The bundle (`data/bundle.py`) materializes a per-symbol, per-session columnar store
(Parquet on disk, NumPy arrays in memory) keyed by `(symbol, session)`.

```
.openbb_backtest/bundles/<bundle_name>/
├── metadata.json          # symbols, date range, calendar, ingest timestamp, source hash
├── ohlcv/<symbol>.parquet # columns: session(UTC), open, high, low, close, volume, adj_factor
├── fundamentals.parquet   # long: symbol, available_date, field, value  (PIT, see §2)
└── adjustments.parquet    # symbol, ex_date, kind{split,div}, ratio, amount
```

```python
class BundleIngestor:
    def __init__(self, db: DatabaseConfig, calendar: ExchangeCalendar): ...
    def ingest(self, symbols: list[str], start: date, end: date,
               name: str = "default") -> BundleMetadata:
        # 1. read equity_historical (already gap-aware via is_gap_fill)
        # 2. align to calendar.sessions_in_range(start, end)  (§3)
        # 3. compute adj_factor from adjustments (§3)
        # 4. write parquet partitions atomically (temp dir -> rename)
        ...
    def load(self, name: str) -> "Bundle": ...      # returns memory-mapped reader
```

- **OHLCV source:** `equity_historical` (gap-aware via `is_gap_fill`). Missing sessions are
  forward-filled only for `adj_factor`, never for price/volume (left NaN → excluded).
- **Reader** exposes the `DataFeed` Protocol (component 02): `history(symbols, end, lookback)`
  slices arrays with a hard upper bound at `end` so **no future bar is ever returned**.
- **Atomic refresh:** ingest writes to a temp directory then renames, so concurrent reads
  never see a partial bundle.

---

## 2. Point-in-time fundamentals lagging

Fundamentals from `income_statement`, `balance_sheet`, `cash_flow`, `financial_ratios` are
stored in long form with an explicit **`available_date`** (filing/availability date), not the
fiscal period end.

```python
def availability_date(row) -> date:
    # prefer filing_date; else period_end + reporting lag (default 45d for 10-Q, 90d for 10-K)
    return row.filing_date or (row.period_end + reporting_lag(row.period_type))
```

- **As-of join:** when the engine requests fundamentals at session *t*, the loader returns the
  latest record with `available_date <= t`. Restated values carry a **later** `available_date`
  and therefore never leak backward.
- **Restated-data fixture** (tested in component 12): a symbol with an original + restated
  filing must return the original value for dates between the two filings.

---

## 3. Calendars + corporate-action adjustment

```python
# data/calendars.py
import exchange_calendars as xcals

def get_calendar(code: str = "XNYS") -> xcals.ExchangeCalendar:
    return xcals.get_calendar(code)     # frozen version pinned for determinism
```

- **Sessions/holidays/half-days** come from `exchange_calendars` (default `XNYS`). This
  **supersedes the hand-maintained `market_holidays` table** for backtest correctness.
- **Adjustment factor:** built from `calendar_splits` (multiplicative) and `calendar_dividend`
  (cash). The bundle stores raw OHLCV plus a cumulative `adj_factor`; engines request either
  raw or total-return-adjusted series. Adjustment is applied **backward** from the most recent
  session so the latest price equals the unadjusted close.
- **Survivorship bias:** the universe for a backtest is resolved from the **point-in-time
  constituent set** (delisted symbols retained with their last valid sessions), not from the
  set of currently-active symbols. Universe membership is stored per session in the bundle
  metadata when a screen reference (e.g. `SP500`) is used.
- **Look-ahead at the calendar boundary:** `history(..., end=t)` includes session *t* only if
  the strategy runs at/after the close; intraday frequencies use the session's bar index.

---

## 4. Privacy & portfolio seeding

- Personal tables (`Portfolio_Positions`, `ESPP_Plan`) stay in local MySQL and are **never**
  written into a bundle.
- A backtest may be *seeded* from current holdings (component 06 constraints) but the bundle
  itself only ever contains public market data; outward-facing results emit synthetic series.

---

## Acceptance mapping (#40)

| Acceptance criterion | Satisfied by |
|---|---|
| Bundle schema | §1 |
| Ingestion pipeline | §1 `BundleIngestor.ingest` |
| Calendar/adjustment handling | §3 |
| Survivorship-bias mitigation | §3 (point-in-time constituents) |
| Look-ahead mitigation | §1 (bounded `history`), §2 (as-of join), §3 boundary rule |
| No new download path (cache-first) | §1 (reads existing tables only) |
