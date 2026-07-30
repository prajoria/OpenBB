# fetch_position_history.py — Spec

| | |
|---|---|
| **Category** | DB loader (price cache pre-warm) |
| **Path** | `Tools/fetch_position_history.py` |
| **Writes** | `equity_historical` (indirectly, via the `fmp_cached` MySQL cache) |

## Purpose

Pre-cache daily equity price history for every symbol held in
`Portfolio_Positions`. Reads the distinct symbols from the positions table and
fetches daily history through the OpenBB `fmp_cached` provider, which caches the
data in MySQL with **intelligent gap detection** — subsequent runs only fetch
the missing date ranges.

This warms the price data consumed by the Portfolio App. It does **not** create
or populate the portfolio tables themselves (those have their own loaders:
`parse_fidelity_positions.py`, `load_espp_plan.py`).

## How it works

1. Read distinct symbols from `Portfolio_Positions` (or `--symbols`).
2. Skip non-tradable identifiers: CUSIP/fund codes (digit-prefixed), cash, and
   a known skip list (`Cash, NSAV, MVVYF, EADSF, NXDR, NHX202764, NHX203309`).
3. For each symbol, call the `fmp_cached` provider for `--years` of daily
   history; the provider handles cache gap detection + MySQL writes.

## CLI

```
python Tools/fetch_position_history.py --dry-run            # plan only, no API calls
python Tools/fetch_position_history.py                      # all symbols, 5y
python Tools/fetch_position_history.py --symbols AAPL,MSFT  # specific symbols
python Tools/fetch_position_history.py --years 5            # custom lookback
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--symbols` | all from DB | comma-separated symbols |
| `--years` | `5` | years of history to fetch |
| `--database` | from `DatabaseConfig` | source positions DB / cache DB |
| `--dry-run` | off | show plan, no API calls |
| `--skip-holiday-prestep` | off | skip the `market_holidays` pre-step (not recommended) |

## Notes / gotchas

- Sets `FMP_CACHE_AUTO_CREATE_DB=false` to avoid 67 redundant
  `CREATE TABLE IF NOT EXISTS` calls per symbol (and the Windows cp1252 emoji
  crash in `cache_schema.py`).
- The module docstring still references the old name `fetch_equity_history.py`;
  the current filename is `fetch_position_history.py`.
- This is the **reference template** for the other DB loaders (sys.path
  bootstrap, encoding fix, logging setup, skip list, per-symbol try/except).
- Runs on a schedule via `Tools/scheduler/run_fetch_position_history.ps1`
  (`--database openbb_fmp_cache_test --years 5`).
- Depends on the `market_holidays` table being populated
  (`populate_market_holidays.py`) for the holiday pre-step.
