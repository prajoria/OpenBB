# populate_cusip_map.py — Spec

| | |
|---|---|
| **Category** | DB loader |
| **Path** | `Tools/populate_cusip_map.py` (~360 lines) |
| **Writes** | `sec_13f_cusip_map` |
| **Issue** | #89 (broaden the ticker -> CUSIP cache) |

## Purpose

Offline batch loader that fills `sec_13f_cusip_map` for the S&P 500 universe
so `resolve_cusip` (used by the `fmp_cached` SEC 13F tier) covers far more than
the built-in B4 seed (~15 rows). Keeps live resolution **offline** — once
populated, `resolve_cusip` is a pure MySQL read with no per-request API calls.

## How it works

1. Read the symbol universe from the local `sp500_constituents` table
   (`SELECT symbol, security FROM sp500_constituents WHERE is_active = 1`) —
   **no index-constituents API call**. (Populated by
   `build_sp500_constituents.py`.)
2. For each ticker, resolve ticker -> CUSIP via the FMP stable `profile`
   endpoint (`https://financialmodelingprep.com/stable/profile`, `cusip` field),
   zero-padded to 9 chars.
3. Upsert `(cusip, issuer_name, ticker, title_class=None, figi=None,
   source="fmp_profile", updated_at)` rows via
   `openbb_sec.utils.thirteen_f_index.upsert_cusip_map` (idempotent;
   `ticker = COALESCE(VALUES(ticker), ticker)`).

> CUSIP still comes from the profile endpoint because **no local table has a
> CUSIP column** (`sp500_constituents` has none; `equity_profile` had no cusip).

## CLI

```
python Tools/populate_cusip_map.py --dry-run            # plan only (reads table, no API)
python Tools/populate_cusip_map.py                      # full S&P 500 (~514 profile calls)
python Tools/populate_cusip_map.py --symbols AAPL,MSFT  # explicit tickers
python Tools/populate_cusip_map.py --limit 25           # first N (smoke test)
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--database` | from `DatabaseConfig` | target / source DB |
| `--symbols` | none | comma-separated tickers (overrides the table) |
| `--limit` | none | only first N symbols |
| `--sleep` | `0.3` | seconds between profile calls |
| `--dry-run` | off | reads the table + prints plan; no API calls, no writes |

## Key functions

| Function | Purpose |
|----------|---------|
| `_resolve_api_key()` | FMP key from user settings / `.env` |
| `get_sp500_symbols(database)` | read active `(symbol, security)` from `sp500_constituents` |
| `fetch_cusip(symbol, api_key)` | FMP profile -> `(cusip, issuer_name)`; `None` on failure, never raises |
| `populate(symbols, api_key, dry_run, sleep)` | init index tables, build rows, `upsert_cusip_map` |
| `main()` | argparse, universe resolution, plan/print, stats |

## Persistence

Target table `sec_13f_cusip_map` DDL is owned by
`openbb_sec/utils/thirteen_f_index.py`. `upsert_cusip_map(rows)` upserts on the
CUSIP key, idempotent. `source` tag `fmp_profile` distinguishes these rows from
B4-seeded / 13F-ingested rows.

## Notes / gotchas

- DB read is allowed in `--dry-run` (cheap); only FMP calls + writes are gated.
- Full populate is ~514 profile calls (~3 min at 0.3s) — confirm intent before
  running the full universe; a `--limit` / `--symbols` smoke test validates the
  path.
- Verified: `--limit 3` resolved A/AAPL/ABBV; `resolve_cusip('NFLX')` returns
  `64110L106` (not in the seed).
- CUSIP identifiers are **licensed** (CUSIP Global Services / S&P) — local use
  only, do not redistribute the table.
- Deferred follow-up (bead `cse`): full-universe-beyond-S&P-500 + fuzzy
  issuer-name matching.
