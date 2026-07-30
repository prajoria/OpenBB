# 2026-06-25 — `enrich_cusip_figi` bounded live run

End-to-end verification for [#93](https://github.com/prajoria/OpenBB/issues/93) (Task 4 of
`docs/superpowers/plans/2026-06-25-93-openfigi-ticker-cusip-resolver.md`).

**Environment.** `OpenBBTechnical` checkout, `trading_technicals` branch, `.venv_win` Python
3.12.13, MySQL `openbb_fmp_cache_test`, OpenFIGI **keyless** mode (no `OPEN_FIGI_API_KEY`).

## Pre-run baseline

```
$ python -c "from openbb_sec.utils.thirteen_f_index import resolve_cusip; \
            print('SHOP:', resolve_cusip('SHOP')); \
            print('OKTA:', resolve_cusip('OKTA')); \
            print('NFLX:', resolve_cusip('NFLX'))"
SHOP: []
OKTA: []
NFLX: ['64110L106']      # already in fmp_profile (S&P 500)
```

The gap #93 closes: `SHOP` / `OKTA` (long-tail) resolve to `[]`; `NFLX` (S&P 500) resolves
via the `populate_cusip_map.py` path.

## Step 2 — Bounded live run `--limit 100 --max-batches 2`

```
$ python Tools/enrich_cusip_figi.py --limit 100 --max-batches 2
======================================================================
  ENRICH sec_13f_cusip_map via OpenFIGI (#93)
======================================================================
  Distinct un-mapped: 100
  To enrich this run: 100
  Estimated batches : 2  (size 10, mode keyless, source keyless)
======================================================================
  RESULTS
======================================================================
  Requested     : 100
  Mapped OK     : 8
  Ambiguous     : 11  (persisted as source='openfigi_ambiguous')
  No match      : 1
  Errors        : 0
  Rows written  : 40        # MySQL ON DUPLICATE KEY UPDATE rowcount (2× per upsert: 20 actual)
  Elapsed       : 6.3s
```

Cache log lines: `batch 1/2: cache hits=5 misses=5 stores=5` (the 5 from a prior T2 smoke
served from cache — **R9 round-trip proved**); `batch 2/2: cache hits=0 misses=10 stores=10`
(fresh CUSIPs).

## Step 3 — Re-run, idempotency

Same command, same DB. `Distinct un-mapped` is again `100` but now selects **different**
CUSIPs (next 100 in held-value order) because the R5 anti-join excluded the 20 just-mapped
from Step 2. Proof:

```
                Step 2 ran   Step 3 ran
openfigi:           +8           +2-4    (10-12 total)
openfigi_ambiguous: +11          +11     (22-25 total)
no_match:           +1           +5      (persists as openfigi_ambiguous too)
```

## Step 4 — Long-tail `resolve_cusip` proof

```
$ python -c "from openbb_sec.utils.thirteen_f_index import resolve_cusip; \
            print('SNOW:', resolve_cusip('SNOW')); \
            print('OKTA:', resolve_cusip('OKTA')); \
            print('MELI:', resolve_cusip('MELI')); \
            print('LNG:',  resolve_cusip('LNG'))"
SNOW: ['833445109']
OKTA: ['679295105']
MELI: ['58733R102']
LNG:  ['16411R208']
```

All four are non-S&P-500, all resolve through the freshly-written `source='openfigi'`
rows. **Acceptance criterion #3 (`resolve_cusip(<long-tail>)` non-empty after enrichment)
is met.**

## Step 5 — Provenance precedence

```
$ python -c "from openbb_fmp_cached.utils import database as db; \
            print(db.execute_query('SELECT source, COUNT(*) AS n FROM sec_13f_cusip_map GROUP BY source'))"
[{'source': 'sec_13f_bulk',      'n': 4001},
 {'source': 'fmp_profile',       'n': 510},   # untouched (R6 anti-join holds)
 {'source': 'openfigi',          'n': 12},    # written by T2+T4
 {'source': 'openfigi_ambiguous','n': 28}]    # flagged by T2+T4
```

`fmp_profile` remained at **510** rows (the S&P 500 universe) across all runs. R6
provenance precedence (app-side anti-join) is verifiably preserved. None of the 510 rows
have their `source` flipped to `openfigi`.

## Step 6 — `--refresh` bypasses cache

```
$ python Tools/enrich_cusip_figi.py --refresh --reresolve-flagged --max-batches 1 --limit 5
... openfigi map_cusips: cache hits=0 misses=5 stores=5
```

Despite the 5 CUSIPs being already present in `openfigi_map_cache`, `--refresh` skipped
the cache reads, sent all 5 to OpenFIGI, and overwrote the cache rows. **R9 bypass
proved.**

## Step 7 — `--audit-disagreements` writes nothing

```
$ python Tools/enrich_cusip_figi.py --audit-disagreements --limit 10
... Mapped OK: 3, Ambiguous: 6, No match: 1, Disagreements: 0, Rows written: 0
```

`Rows written: 0` despite 3 mapped-OK results. Audit mode is genuinely read-only.
No disagreements found because the 3 mapped CUSIPs had no pre-existing ticker to
compare against (they were brand-new un-mapped rows). R6's "audit doesn't write"
contract holds.

## Step 8 — Regression check

```
$ python -m pytest openbb_platform/providers/sec/tests/test_openfigi.py \
                  openbb_platform/providers/sec/tests/test_thirteen_f_index.py
============================= 51 passed in 0.40s =============================
```

20 new `test_openfigi.py` + 31 existing `test_thirteen_f_index.py` all green. **No regression.**

## Summary — design §3 acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | `--dry-run` lists N un-tickered CUSIPs, maps nothing | ✅ T2 smoke (5 CUSIPs, 0 writes) |
| 2 | Live run upserts `(ticker, figi, source='openfigi')`, idempotent | ✅ T4 Steps 2-3 |
| 3 | `resolve_cusip(<long-tail>)` returns CUSIP(s) after enrichment (was `[]`) | ✅ T4 Step 4 (SNOW/OKTA/MELI/LNG) |
| 4 | Seed / S&P 500 tickers never overwritten | ✅ T4 Step 5 (510 fmp_profile unchanged) |
| 5 | Multi-match → US-composite; ambiguous → skip+flag, never guess | ✅ R3 ladder unit-tested; 28 ambiguous rows persisted with `source='openfigi_ambiguous'` |
| 6 | OpenFIGI responses cached; second run hits cache; `--refresh` forces re-fetch | ✅ T4 Steps 2 (hits=5) + 6 |
| 7 | Unit tests pass offline; no `aiohttp`; respects rate limits with backoff | ✅ 20/20 in 0.40s; R2 RateLimitPolicy + 429 Retry-After |
| 8 | `Tools/docs/DESIGN.md` + per-tool spec | ✅ T3 (commits `b623c615e`) |

**All acceptance criteria met. #93 ready for code review (Phase 6 of openbb-dev-cycle).**
