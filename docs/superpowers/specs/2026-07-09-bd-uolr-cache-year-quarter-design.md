# bd-uolr — institutional_ownership cache-read year/quarter filter

**Bead:** OpenBBTechnical-uolr (P0 correctness)
**Base:** origin/develop
**Scope:** single file, ~30 semantic LoC + tests

## Goal

`_get_cached_institutional(symbol)` in
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/institutional_ownership.py:243`
filters ONLY by `symbol`, `is_valid`, and `cached_at >= freshness_cutoff`.
It does NOT filter by year/quarter, so any repeat call within the 7-day TTL
returns whatever period was most-recently cached — silently poisoning any
historical time-series analytics.

Post-fix: cache read filters by exact (symbol, year, quarter) match on the
`data_json` payload. When year OR quarter is None on the query, treat as
cache-miss (fall through to FMP fetch which applies its own defaults).

## Why NOT add year/quarter columns to the table (deferred to bd-porh)

Adding schema columns requires:
- ALTER TABLE migration
- Backfill of existing rows from `data_json`
- Schema-version bump

For a P0 correctness bug, an in-memory JSON filter is:
- 30 LoC vs ~200 LoC (schema + migration + backfill)
- Zero schema risk
- Same query semantics (filters happen client-side after WHERE symbol)
- Correct

Column indexing would be nice for perf if the cache grew huge, but
institutional_ownership has ~4 quarters/year × TTL 7 days ≈ 1-2 rows
per symbol at any time. Full-scan the symbol partition is fine.

**bd-porh** (the architectural PIT refactor) will properly re-shape this
schema. This PR fixes the correctness bug without pre-empting that work.

## Design decisions

### D1 — Add year/quarter parameters to _get_cached_institutional

```python
def _get_cached_institutional(
    symbol: str,
    year: int | None,
    quarter: int | None,
) -> list[dict]:
```

Positional args match the tight scope (called from ONE place —
`aextract_data`'s step-1 loop). Not keyword-only.

### D2 — None year OR None quarter = cache-miss

Rationale: FMP applies default-latest-quarter logic when either is None
(see `openbb_fmp/models/institutional_ownership.py:182-197`). Duplicating
that logic client-side would drift over time. Simpler: if the caller
doesn't specify BOTH, we skip cache and let FMP compute the "latest",
which becomes the cache key on the write. Subsequent explicit-year-quarter
calls will hit cache correctly.

Trade-off: a user who repeatedly calls without year/quarter (relying on
"give me the latest") pays the FMP round-trip every time in that TTL
window. Acceptable — the alternative is silently returning stale "latest"
when the current-quarter has rolled over.

### D3 — In-memory filter on `data_json` payload year/quarter fields

The FMP payload includes integer `year` and `quarter` fields per record.
Filter:

```python
loaded = [
    p for p in loaded_all
    if p.get("year") == year and p.get("quarter") == quarter
]
```

Compare as ints — FMP's payload stores them as ints. If a legacy row has
them as strings, the equality would fail and it'd be treated as
cache-miss (safe degrade — worst case is an unnecessary refetch).

### D4 — aextract_data passes query.year / query.quarter through

The step-1 loop currently:
```python
for symbol in symbols:
    cached = _get_cached_institutional(symbol)
```

Post-fix:
```python
for symbol in symbols:
    cached = _get_cached_institutional(symbol, query.year, query.quarter)
```

### D5 — Do NOT change _store_institutional

Writes already record `year`/`quarter` in the JSON payload (FMP includes
them). No schema change needed. This PR only fixes the READ path.

## Test plan

`test_uolr_cache_year_quarter_filter.py` — new, ~6 tests:

1. **`test_cache_hit_returns_matching_year_quarter`** — cache has AAPL
   {year=2024, quarter=1}; call with (year=2024, quarter=1) → returns it
2. **`test_cache_miss_on_different_year`** — cache has {y=2024, q=1};
   call with (year=2023, quarter=1) → returns [] (cache-miss)
3. **`test_cache_miss_on_different_quarter`** — cache has {y=2024, q=1};
   call with (y=2024, q=2) → returns []
4. **`test_none_year_is_cache_miss`** — cache has {y=2024, q=1}; call
   with (year=None, quarter=1) → returns [] (D2)
5. **`test_none_quarter_is_cache_miss`** — same, quarter=None → []
6. **`test_multiple_periods_cached_returns_only_matching`** — cache has
   {y=2024, q=1} AND {y=2024, q=2}; call with (y=2024, q=1) → returns
   ONLY q=1

### Empirical RED-then-GREEN

Pre-fix code returns any cached row for the symbol regardless of query
year/quarter. All 6 tests will fail (some return wrong data, some return
non-empty when they should be empty).

## Beads closed

- **OpenBBTechnical-uolr** (P0 correctness)
