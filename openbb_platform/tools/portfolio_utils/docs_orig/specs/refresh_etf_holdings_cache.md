# refresh_etf_holdings_cache.py — Spec

| | |
|---|---|
| **Category** | DB loader (cache pre-warm) |
| **Path** | `Tools/refresh_etf_holdings_cache.py` (~280 lines) |
| **Reads** | `Portfolio_Positions` (filtered through `KNOWN_ETFS`) |
| **Writes** | `etf_holdings` (indirectly, via the `fmp_cached` provider's multi-tier fallback chain) |
| **Design** | [`docs/superpowers/specs/2026-06-26-refresh-etf-holdings-cache-design.md`](../../../docs/superpowers/specs/2026-06-26-refresh-etf-holdings-cache-design.md) |
| **Sibling** | [`fetch_position_history.py`](fetch_position_history.md) (same skeleton; that one warms `equity_historical` for held symbols, this one warms `etf_holdings` for held + relevant ETFs) |
| **Related** | [#97](https://github.com/prajoria/OpenBB/issues/97) (ETF holdings multi-tier fallback — fixes the source chain that this tool calls on a schedule) |

## Purpose

Pre-warm the `fmp_cached` `etf_holdings` MySQL cache for the ETFs that
matter to this checkout — the **11 GICS sector SPDRs** that
`obb.techtrade.scan` resolves universes through, **plus any ETFs you
actually hold** in `Portfolio_Positions`, **plus any extras** you pass via
`--etfs`.

The tool is a thin orchestrator. It calls
`obb.etf.holdings(symbol=X, provider="fmp_cached")` for each ETF and lets
the provider's multi-tier fallback chain (FMP → issuer-file → SEC N-PORT)
populate the cache. **This tool knows nothing about which tier feeds each
ETF.** That's by design (L2) — when [#97](https://github.com/prajoria/OpenBB/issues/97)
adds new tiers, this tool needs zero changes.

Until #97 lands: every SPDR ETF logs `402 Restricted Endpoint` as an
error, the cache stays empty, the tool exits 0. After #97 lands: the same
`.ps1`, the same CLI, the same code path — but `data_source` reads
`"issuer_ssga"` and the cache fills up.

## How it works

1. **Resolve the universe** — union of:
   * `SPDR_SECTORS` (11 tuples, derived from `openbb_techtrade.engine.screener.GICS_SECTOR_ETFS.values()` at module load — L9, so the two declarations cannot drift).
   * Distinct `Portfolio_Positions.symbol` rows that match the built-in `KNOWN_ETFS` frozenset (~20 well-known ETF tickers — SPDRs + S&P trackers + bonds + commodities + thematics). Skipped if `--skip-portfolio`.
   * Comma-separated extras from `--etfs`. Upper-cased, trimmed, blank tokens dropped.
2. **For each ETF**, call `obb.etf.holdings(symbol=ETF, provider="fmp_cached")` and record `(etf, row_count, data_source, elapsed_ms, error_or_None)`. Errors are caught per-ETF — never raised.
3. **Print a human-facing summary banner** + emit a structured INFO log line per ETF so the scheduler log is grep-able.
4. **Exit 0** even on errors; a partial win is still a win, and 402s under today's FMP-only provider are expected.

## CLI

```bash
python Tools/refresh_etf_holdings_cache.py --dry-run            # plan only, no API
python Tools/refresh_etf_holdings_cache.py                      # SPDRs + portfolio + any defaults
python Tools/refresh_etf_holdings_cache.py --etfs IVV,VOO,QQQ   # add extras
python Tools/refresh_etf_holdings_cache.py --skip-portfolio     # SPDRs + --etfs only
python Tools/refresh_etf_holdings_cache.py --database openbb_fmp_cache_test
python Tools/refresh_etf_holdings_cache.py -v                   # DEBUG-level logging
```

| Flag | Default | Meaning |
|---|---|---|
| `--database` | from `DatabaseConfig` | source for Portfolio_Positions lookup; also sets `DB_NAME` env so `_db()` writes target the chosen DB |
| `--etfs` | none | extra comma-separated ETF tickers to refresh atop the defaults |
| `--skip-portfolio` | off | skip the Portfolio_Positions read; SPDRs + `--etfs` only |
| `--dry-run` | off | print plan + universe; no API calls, no DB writes |
| `--api-key` | none | override `FMP_API_KEY` (else env `FMP_API_KEY`, else `user_settings`, else none) |
| `-v / --verbose` | off | DEBUG-level logging |

## Output format

```
======================================================================
  REFRESH etf_holdings CACHE
======================================================================
  SPDR sectors  : 11 (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY)
  Portfolio ETFs: 3 (IVV, QQQ, VTI)
  Extra (--etfs): 0 (-)
  Total universe: 14

  Refreshing ...
    XLK    [issuer_ssga]    rows=75      elapsed=120ms
    XLF    [issuer_ssga]    rows=72      elapsed=110ms
    ...
    IVV    [-]              rows=0       elapsed=15ms   ERROR: 402 Restricted Endpoint
    ...

======================================================================
  RESULTS
======================================================================
  Requested : 14
  Populated : 12
  Errored   :  2   ← will resolve once #97 ships
  Empty     :  0
  Elapsed   : 4.1s
======================================================================
```

## Key functions

| Function | Purpose |
|----------|---------|
| `SPDR_SECTORS` | Module constant: tuple of the 11 GICS sector SPDRs, derived from `openbb_techtrade.engine.screener.GICS_SECTOR_ETFS.values()` (L9). |
| `KNOWN_ETFS` | Module constant: frozenset of ~20 ETF tickers used to filter Portfolio_Positions (L4). |
| `list_portfolio_etfs(database)` | Distinct `Portfolio_Positions.symbol` values that are in `KNOWN_ETFS`. Returns `[]` on any DB error (graceful). |
| `resolve_universe(database, skip_portfolio, extra_etfs)` | Union of SPDRs + portfolio + extras; deduplicated, sorted, upper-cased. |
| `refresh_one_etf(etf, dry_run, api_key)` | Call `obb.etf.holdings` once; return `(etf, row_count, data_source, elapsed_ms, error_or_None)`. Never raises. |
| `refresh_universe(etfs, dry_run, api_key)` | Loop `refresh_one_etf` over the universe; aggregate `{"requested","populated","errored","empty"}` stats. |
| `main()` | argparse, banner, run, summary. Returns process exit code. |

## Persistence

The tool writes nothing of its own. The `obb.etf.holdings` call inside
`refresh_one_etf` flows through the `fmp_cached` provider, which manages
the `etf_holdings` MySQL cache table and TTL (see
[`openbb_fmp_cached.utils.cache_schema`](../../../openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py)
+ #97's L8 for TTL philosophy: issuer 1d, N-PORT 30d).

## Notes / gotchas

- **`SPDR_SECTORS` is derived, not duplicated** (L9). Any change to
  `GICS_SECTOR_ETFS` automatically propagates; the regression test
  `test_spdr_sectors_matches_techtrade_gics_sector_etfs` catches drift if
  the runtime import ever falls back to the hardcoded fallback tuple.
- **`--database` sets `DB_NAME` env** before any `_connect()` call —
  mirrors the #93 review-fix pattern for `enrich_cusip_figi.py`.
- **`.env` loaded at module import** via `dotenv.load_dotenv(PROJECT_ROOT/.env, override=True)`
  so `FMP_API_KEY` from `.env` reaches the provider's env tier.
- **Windows console fix** mirrors `fetch_position_history.py` exactly —
  `sys.platform == "win32"` guard + `errors="replace"` on both std{out,err}.
- **Per-ETF errors are non-fatal** (L7). Today's 402 storm logs at
  WARNING and the loop continues. Exit code is always 0 in normal runs.
- **Scheduled separately** from `fetch_position_history` (L8) — different
  failure modes, different re-run cadences.
- **CUSIP / fund codes** are not an issue here because the tool's
  universe is filtered through `KNOWN_ETFS`; non-ETF symbols never reach
  the `obb.etf.holdings` call.
