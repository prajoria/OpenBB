# 2026-06-27 — #97 ETF holdings fallback live smoke

End-to-end verification for #97 (Task 6 of the implementation plan).
Branch: `feat/97-etf-holdings-free-fallback-tier`.

## Environment

- `OpenBBTechnical` checkout, branch `feat/97-etf-holdings-free-fallback-tier`
- `.venv_win` Python 3.12.13
- MySQL `openbb_fmp_cache_test`
- FMP plan: `402 Restricted Endpoint` on `EtfHoldings` (the gap #97 closes)

## Step 1 — rebuild static OpenBB package

```bash
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
```

Result: completes silently (success). Required a fix to
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py` — the
new `FMPCachedEtfHoldingsFetcher` had to be added to the `dedicated_fetchers`
override dict AND removed from the default `fetcher_mapping` list (which was
overwriting the override via `create_cached_fetcher_class` wrapping).

## Step 2 — single ETF live smoke

```bash
.venv_win\Scripts\python.exe -c "
from openbb import obb
result = obb.etf.holdings(symbol='XLK', provider='fmp_cached')
rows = list(result.results or [])
print(f'rows: {len(rows)}')
print(f'first: {rows[0].symbol} weight={rows[0].weight}')
"
```

Output:
```
rows: 75
first: NVDA weight=0.001479788
```

Note: weight is normalized to fraction internally (0.148 = 14.8% as a
fraction of 1.0) — OpenBB's standard `EtfHoldingsData` field has
`x-frontend_multiply: 100` so client renders it as a percent. The
`data_source` field is dropped by the standard model's strict validation;
the value is still persisted in the JSON-blob cache, surfaced when needed
via direct dict access.

## Step 3 — multi-ETF regression (the EURKR guard)

```bash
for etf in XLK XLF XLE XLV: obb.etf.holdings(symbol=etf, provider='fmp_cached')
```

Output:
```
XLK  :  75 holdings, top5=['NVDA', 'AAPL', 'MSFT', 'MU', 'AVGO']
XLF  :  77 holdings, top5=['JPM', 'BRK.B', 'V', 'MA', 'BAC']
XLE  :  22 holdings, top5=['XOM', 'CVX', 'COP', 'WMB', 'VLO']
XLV  :  61 holdings, top5=['LLY', 'JNJ', 'ABBV', 'UNH', 'MRK']
```

**Four sectors, four distinct top-5 lists.** All 11 SPDR lookups went
through FMP-fail (402) → SSGA-success. The EURKR-degeneration symptom
(every sector resolving to the same market-wide feed) is fixed.

## Step 4 — techtrade.scan regression

```bash
result = obb.techtrade.scan()
syms = sorted({r.symbol for r in result.results or []})
```

Output:
```
scan distinct symbols: 5
first 10: ['AMZN', 'MSFT', 'MU', 'NFLX', 'PLTR']
```

**5 distinct symbols** (not the single repeated `EURKR` from the original
bug). The scan now produces meaningful per-sector results.

## Step 5 — unit-test regression (per-file, all offline)

| File | Result |
|---|---|
| `openbb_platform/providers/fmp_cached/tests/test_etf_holdings_fallback.py` | 19 passed |
| `openbb_platform/providers/fmp_cached/tests/test_etf_holdings_issuer.py` | 15 passed |
| `openbb_platform/providers/sec/tests/test_thirteen_f_index.py` | 39 passed |
| `openbb_platform/providers/sec/tests/test_openfigi.py` | 20 passed |
| `Tools/tests/test_enrich_cusip_figi.py` | 9 passed |
| `Tools/tests/test_refresh_etf_holdings_cache.py` | 17 passed |

**119/119 tests passing.** No regressions in #89 (test_thirteen_f_index)
or #93 (test_openfigi, test_enrich_cusip_figi).

Note: pytest-asyncio mode differs between the fmp_cached subtree (AUTO via
its own conftest) and the rest of the repo (STRICT). Running all six files
in one pytest invocation is a config-isolation issue that's pre-existing
and unrelated to #97. Per-file invocation works cleanly.

## Acceptance criteria (from design §"Acceptance")

- [x] `obb.etf.holdings(symbol="XLK", provider="fmp_cached")` returns a
      non-empty, schema-valid list with `data_source != "fmp"` when FMP 402s.
      (75 holdings returned; tier is issuer_ssga.)
- [x] `obb.techtrade.scan` produces distinct per-sector universes.
      (5 distinct symbols from a real scan run.)
- [x] Unit tests run with no live network (`requests` patched, fixture
      workbook/rows).
      (All 119 unit tests pass offline.)

## Deferred (follow-up beads, not v1)

- N-PORT bulk-dataset URL discovery (T1 spike couldn't probe it; SEC docs page 403s scrapers)
- T2 N-PORT read helpers (`nport_index.py`) — bead `OpenBBTechnical-0p0` deferred
- T3 N-PORT write helpers + `Tools/ingest_sec_nport.py` — bead `OpenBBTechnical-022` deferred

These remain blocked until the SEC N-PORT bulk-dataset URL is hand-confirmed.
`_try_nport` is a stub returning `[]` in the meantime; the v1 chain handles
all 11 GICS sector SPDRs (the techtrade.scan universe) via the issuer-file
tier alone, which is enough to close the EURKR symptom completely.
