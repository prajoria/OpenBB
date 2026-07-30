# build_sp500_constituents.py — Spec

| | |
|---|---|
| **Category** | DB loader |
| **Path** | `Tools/build_sp500_constituents.py` (~100 lines) |
| **Writes** | `sp500_constituents` |
| **Status** | In use — this is the canonical "populate the constituents table" script |

## Purpose

Populate / refresh the `sp500_constituents` table (the S&P 500 symbol
universe). Thin CLI wrapper around
`openbb_fmp_cached.models.index_constituents.populate_cache()` — the provider
module owns the DDL and DML (single source of truth); the script only parses
args and calls the public API.

This is the loader that feeds the `--database`-less default universe used by
`populate_cusip_map.py` (which reads `sp500_constituents` for its ticker list).

## Data source modes

- `--source copy` (default) — copy rows from another database
  (`--source-database`, default `fmp_cache`) into the target. Fast, offline,
  no API key needed; use when the table is already populated in the default
  provider DB and you want it mirrored into `openbb_fmp_cache_test`.
- `--source api` — fetch fresh constituents from FMP (needs `FMP_API_KEY` /
  `fmp_api_key`).

## CLI

```
python Tools/build_sp500_constituents.py                                  # copy from fmp_cache (default)
python Tools/build_sp500_constituents.py --source api                     # fetch from FMP
python Tools/build_sp500_constituents.py --source copy --source-database fmp_cache
python Tools/build_sp500_constituents.py --database openbb_fmp_cache_test --source copy
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--database` | from `DatabaseConfig` | target DB to write |
| `--source` | `copy` | `api` (fetch FMP) or `copy` (mirror another DB) |
| `--source-database` | `fmp_cache` | source DB when `--source copy` |

## Table: `sp500_constituents`

DDL lives in
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/index_constituents.py`
(`CREATE_TABLE_SQL`). Columns: `id, symbol (UNIQUE), security, gics_sector,
gics_sub_industry, headquarters_location, date_added, cik, founded,
fetched_at, updated_at, is_active`. Indexes on `gics_sector`, `is_active`,
`fetched_at`.

**Persistence:** `INSERT ... ON DUPLICATE KEY UPDATE` on the `symbol` unique
key — idempotent upsert that refreshes metadata and `updated_at`. No CUSIP
column (so `populate_cusip_map.py` still calls the FMP profile endpoint for
CUSIPs).

## Notes

- ~514 active rows for the current S&P 500.
- The provider function returns `stats` (`database`, `total_rows`, `sectors`,
  `top_sectors`) which the script prints.
- Loads `.env` for `FMP_API_KEY` (only needed for `--source api`).
