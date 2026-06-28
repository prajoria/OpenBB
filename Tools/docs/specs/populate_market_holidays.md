# populate_market_holidays.py — Spec

| | |
|---|---|
| **Category** | DB loader |
| **Path** | `Tools/populate_market_holidays.py` |
| **Writes** | `market_holidays` |

## Purpose

Populate the `market_holidays` table with all US stock-market (NYSE/NASDAQ)
observed holidays for 2016-2026. Computes holidays algorithmically (no API) and
upserts them, so it is safe to re-run.

## Holidays covered

New Year's Day, MLK Jr. Day (3rd Mon Jan), Presidents' Day (3rd Mon Feb),
Good Friday (Friday before Easter), Memorial Day (last Mon May),
Juneteenth (Jun 19, observed — from 2022), Independence Day (Jul 4, observed),
Labor Day (1st Mon Sep), Thanksgiving (4th Thu Nov), Christmas (Dec 25,
observed), plus special closures (state funerals, etc.). "Observed" rules shift
weekend holidays to the adjacent weekday.

## Key helpers

| Function | Purpose |
|----------|---------|
| `_nth_weekday(year, month, weekday, n)` | n-th given weekday in a month |
| `_last_weekday(year, month, weekday)` | last given weekday in a month |
| `_easter(year)` | Anonymous Gregorian algorithm (for Good Friday) |

## CLI

```
python Tools/populate_market_holidays.py
python Tools/populate_market_holidays.py --database openbb_fmp_cache_test
```

| Flag | Meaning |
|------|---------|
| `--database` | target DB (default from `DatabaseConfig`) |
| (rebuild range) | when rebuilding, `DELETE` US rows in `[start_year, end_year]` then re-insert |

## Table: `market_holidays`

Columns: `holiday_date`, `market` (`'US'`), `holiday_name`. The DDL is **not**
created here (`FMP_CACHE_AUTO_CREATE_DB=false`) — the table is provided by the
`fmp_cached` cache schema. Unique key on `(holiday_date, market)`.

**Persistence:** `INSERT ... ON DUPLICATE KEY UPDATE holiday_name = VALUES(...)`
(idempotent); optional `DELETE`+re-insert for a year range rebuild.

## Notes

- Consumed by `fetch_position_history.py` (holiday pre-step) and any code that
  needs trading-day calendars.
- Pure computation — no network, no API key.
