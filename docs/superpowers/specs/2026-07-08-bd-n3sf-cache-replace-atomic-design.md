# bd-n3sf — Cache-replace atomic-transaction refactor (Tier 2)

**Bead:** OpenBBTechnical-n3sf
**Base:** origin/develop
**Depends on:** bd-kh08 (PR #414 — `safe_identifier` + `replace_rows` helpers, MERGED)
**Estimated PR size:** ~250 LoC semantic diff + tests

## Goal

Route **8 sibling `_store_*` sites** in `openbb_fmp_cached/models/` through
`replace_rows()` from Tier-0 helpers (PR #414). Each site currently runs
per-symbol `DELETE FROM <table> WHERE symbol = %s` in a loop followed by a bulk
`execute_many(INSERT ...)`, both on the shared `autocommit=True` connection
pool. A partial-write failure between DELETE and INSERT (network blip, server
crash, MySQL disconnect, pool exhaustion) leaves the cache **empty of the
symbol's history**. This is the P0 data-loss class flagged by bd-ihdn.

Post-fix all 8 sites do DELETE + INSERT in a single transaction on a fresh
`autocommit=False` connection — either everything commits or nothing does.

## In-scope sites (8)

| # | File | Function | Bead |
|---|---|---|---|
| 1 | `models/institutional_ownership.py:268` | `_store_institutional` | **bd-ihdn** (P0 CONFIRMED) |
| 2 | `models/balance_sheet.py:178` | `_store_balance_sheets` | (child of n3sf) |
| 3 | `models/cash_flow.py:178` | `_store_cash_flow_statements` | (child of n3sf) |
| 4 | `models/income_statement.py:178` | `_store_income_statement` | (child of n3sf) |
| 5 | `models/financial_ratios.py:291` | `_store_financial_ratios` | (child of n3sf) |
| 6 | `models/key_metrics.py:167` | `_store_key_metrics` | (child of n3sf) |
| 7 | `models/equity_quote.py:134` | `_store_quotes` | (child of n3sf) |
| 8 | `models/etf_holdings.py:74` | `_store_etf_holdings` | (child of n3sf) |

All 8 share the identical antipattern:
```python
cleanup_query = "DELETE FROM <table> WHERE symbol = %s"
symbols = {(item.get("symbol") or "").strip() for item in records if item.get("symbol")}
for symbol in symbols:
    execute_query(cleanup_query, (symbol,))     # autocommit=True — commits each DELETE
params_list = [...]
if params_list:
    execute_many(insert_query, params_list)     # autocommit=True — if this fails, rows already gone
```

## Explicitly OUT of scope (documented, follow-up beads filed if not already)

| File | Site | Why out of scope |
|---|---|---|
| `models/equity_peers.py:120` | `_store_peers` cleanup | Non-symbol WHERE clause (`JSON_UNQUOTE(JSON_EXTRACT(additional_fields, '$.parent_symbol'))`) — current `replace_rows(table, where_col, where_val, rows)` API only supports single-column equality. Would need `replace_rows_where(table, where_sql, where_params, rows)` API extension. **File as bd-follow-up.** |
| `models/equity_historical.py:1672,1690` | `clear_cache_for_symbol`, `clean_old_cache` | Pure DELETE utilities (no INSERT), not the DELETE+INSERT antipattern. NOT the bd-ihdn class. No fix needed. |
| `models/analyst_estimates.py:314` | `_store_in_cache` | Uses `INSERT ... ON DUPLICATE KEY UPDATE` (upsert), NOT DELETE+INSERT. Different pattern — atomic per-row via MySQL upsert. Ambiguously bead-listed but structurally different. **NO fix needed.** |
| `models/analyst_estimates.py:535,538` | `clear_cache_for_symbol` | Pure DELETE utility (no INSERT). Same as equity_historical. |
| `models/financial_ratios.py:284` | `_evict_symbols_from_cache` | Pre-fetch DELETE only (no INSERT) — the eviction is unconditional by design (bd-ygoh). NOT the bd-ihdn class. |
| `Tools/parse_fidelity_positions.py:1224` | Fidelity DELETE loop | **bd-2650/gykp** — separate PR, different codebase (Tools/, not providers/). |

**Adjustment vs planning doc:** The plan said "~11 sites"; deep enumeration
found 8 clean matches + 3 non-conversions (JSON_EXTRACT WHERE, upsert-not-
DELETE-INSERT, plain-DELETE utilities). Documenting this discrepancy in the PR
body so future readers understand why the count differs.

## API alignment with `replace_rows` (from PR #414)

```python
def replace_rows(
    table: str,
    where_col: str,
    where_val: Any,
    rows: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
) -> int:
    """Atomically DELETE + INSERT rows in a single transaction (bd-kh08)."""
```

Contract confirmed:
- **Empty `rows`** = DELETE-only, still atomic
- **`columns=None`** = inferred from sorted union of row keys
- **Explicit `columns`** = raises `KeyError` on missing keys (from PR #414 P2 fix)
- **DDL identifier positions** validated via `safe_identifier`

## Refactor pattern (per site)

**Before:**
```python
def _store_balance_sheets(statements: list[dict[str, Any]]) -> None:
    cleanup_query = "DELETE FROM balance_sheet WHERE symbol = %s"
    insert_query = """
    INSERT INTO balance_sheet (
        symbol, date, period, currency,
        total_assets, total_liabilities, total_equity,
        data_json, is_valid, cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """
    symbols = {(item.get("symbol") or "").strip() for item in statements if item.get("symbol")}
    for symbol in symbols:
        execute_query(cleanup_query, (symbol,))
    params_list = [(item.get("symbol"), item.get("date"), ...) for item in statements]
    if params_list:
        execute_many(insert_query, params_list)
```

**After:**
```python
def _store_balance_sheets(statements: list[dict[str, Any]]) -> None:
    """Persist balance sheet records atomically per symbol (bd-n3sf)."""
    # Group by symbol so each symbol's DELETE+INSERT is one transaction.
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in statements:
        sym = (item.get("symbol") or "").strip()
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(_row_for_balance_sheet(item))

    for symbol, rows in by_symbol.items():
        replace_rows(
            "balance_sheet",
            "symbol",
            symbol,
            rows,
            columns=[
                "symbol", "date", "period", "currency",
                "total_assets", "total_liabilities", "total_equity",
                "data_json",
            ],
        )

def _row_for_balance_sheet(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": item.get("symbol"),
        "date": item.get("date"),
        "period": item.get("period"),
        "currency": item.get("reportedCurrency"),
        "total_assets": item.get("totalAssets"),
        "total_liabilities": item.get("totalLiabilities"),
        "total_equity": item.get("totalStockholdersEquity") or item.get("totalEquity"),
        "data_json": json.dumps(item),
    }
```

**Key design decisions (D1-D6):**

### D1 — Group by symbol; one transaction per symbol (NOT one big transaction)
- Each symbol's DELETE+INSERT is atomic on its own
- If MSFT's write fails, AAPL's still commits (bulk-load ergonomics)
- Alternative: bind all symbols to one big transaction. **Rejected** — a single
  bad symbol would fail the whole batch; violates "best-effort per-symbol" that
  the current code intends (implicitly)

### D2 — Pass `columns=[...]` explicitly (NOT infer from row keys)
- Explicit column order matches the pre-fix INSERT schema exactly — reviewers
  can verify by grep
- Row-key inference from PR #414 sorts keys alphabetically; `symbol` would land
  after `data_json` and INSERT would use sorted order. Works functionally
  (columns are named in the SQL) but harder to review
- **Explicit** also gets the PR #414 P2 KeyError-on-missing behavior — a typo
  in the row builder raises immediately instead of silently NULL-filling

### D3 — `is_valid=TRUE, cached_at=CURRENT_TIMESTAMP` moved from SQL literal to defaults column strategy
- Pre-fix: `VALUES (..., TRUE, CURRENT_TIMESTAMP)` — MySQL evaluates
- Post-fix option A: pass literal `True` and `datetime.now()` in the row dict —
  loses `CURRENT_TIMESTAMP` server-side clock consistency
- Post-fix option B (chosen): rely on **column DEFAULTs at the schema level** —
  all `cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` and `is_valid BOOL DEFAULT
  TRUE`. Verify via `cache_schema.py` before proceeding.

**Verification step:** Read `cache_schema.py` for each of the 8 tables and
confirm `is_valid` and `cached_at` have appropriate DEFAULTs. If NOT, either:
  - Include `is_valid` and `cached_at` in the columns list + pass Python values
  - Or add the DEFAULTs to schema (separate PR — this PR shouldn't touch schema)

If a table lacks DEFAULTs, use the explicit-value approach and file follow-up
to add DEFAULTs.

### D4 — Preserve exception-swallowing behavior at outer call sites
- Some `_store_*` functions have callers that swallow exceptions
  (`try: _store_xxx(...) except Exception: pass`) so cache failures don't break
  the read path
- Post-fix `replace_rows` propagates the transaction exception; callers see the
  same exception surface they already handle
- Do NOT catch inside `_store_*` — the atomic guarantee is worthless if we
  swallow. Callers already know to handle it.

### D5 — `refresh` flag NOT propagated
- Some callers pass a `refresh` flag to bust the connection pool. `replace_rows`
  has a `refresh` keyword-only argument from PR #414 that forces a fresh
  connection. **Default is False** — the connection pool suffices.
- Only wire `refresh=True` if a specific site's tests demonstrate stale
  connections cause issues (they don't — pool auto-heals on disconnect)

### D6 — Empty input remains a no-op (no DELETE)
- Pre-fix: `if not records: return` early exit → nothing happens
- Post-fix: keep the guard. Do NOT call `replace_rows(rows=[])` on empty input
  because that would DELETE any pre-existing rows for zero symbols (still fine
  functionally since `by_symbol` is empty → no loop iterations, but the guard
  documents intent)

## Test plan

### Per-site unit tests (`test_cache_replace_atomic.py`)

For each of the 8 sites, a test class with:

1. **`test_happy_path_stores_records`** — Regression lock: call `_store_*`
   with a valid records list; assert `replace_rows` called with expected
   `(table, "symbol", symbol, [row_dict, ...])` shape
2. **`test_empty_records_is_noop`** — Call with `[]`; assert `replace_rows`
   NOT called (D6)
3. **`test_multi_symbol_batches_by_symbol`** — Call with 3 symbols × 2
   records each; assert `replace_rows` called 3 times (one per symbol) with
   correct rows-per-symbol partition
4. **`test_delete_and_insert_are_atomic`** — Mock `replace_rows` to raise on
   the 2nd call; assert:
   - 1st call's data is committed (mock signals commit)
   - 2nd call raises; DB state consistent (no half-write)
   - 3rd call did NOT fire (fail-fast, not fail-continue)

**Total:** 8 sites × 4 tests = 32 tests

### Empirical RED-then-GREEN protocol

Before committing the semantic fix:
1. Write all 32 tests → 32 GREEN (against pre-fix code — establishes the
   contract: "these are what the code DOES today")
2. Apply the refactor → tests still GREEN if refactor preserves behavior
3. **Revert step 3 (refactor), re-run tests** → confirm which tests would
   catch a regression. If ALL 32 tests still pass on pre-fix code, they're
   testing shape not behavior — rewrite to be atomicity-sensitive.

### Integration verification (manual + optional)

Since `fmp_cached` integration tests need live API + MySQL:
1. Quick smoke: `import openbb; obb.equity.fundamental.balance(symbol='MSFT',
   provider='fmp_cached')` — verify no ValueErrors, cache write succeeds
2. Optionally add `pytest.mark.integration` for one round-trip test per site
   (only if bandwidth allows — 8 integration tests × ~2min = ~15min)

## Rollout — single PR (`fix/qc-cache-replace-atomic`)

Sub 1: `_store_institutional` (bd-ihdn — the P0)
Sub 2: `_store_balance_sheets`
Sub 3: `_store_cash_flow_statements`
Sub 4: `_store_income_statement`
Sub 5: `_store_financial_ratios`
Sub 6: `_store_key_metrics`
Sub 7: `_store_quotes`
Sub 8: `_store_etf_holdings`

**Single PR, 8 semantic commits + 1 style-prep + 1 test commit.** Each semantic
commit is small (30-60 LoC), reviewer can walk them one by one. All 8 sites
share identical pattern — reviewer confidence builds after site 1 is validated.

Follow-up beads to file:
- **bd-n3sf-followup-1** — `equity_peers.py:120` — needs `replace_rows_where`
  API extension for JSON_EXTRACT WHERE clauses
- **bd-n3sf-followup-2** — Confirm cache_schema.py DEFAULTs for all 8 tables
  (if any table lacks DEFAULT, add in separate schema PR)

## Beads closed by this PR

- **OpenBBTechnical-n3sf** (tracker, P0)
- **OpenBBTechnical-ihdn** (institutional_ownership DELETE-then-INSERT, P0)

**NOT closed by this PR** (out of scope):
- **OpenBBTechnical-uolr** (institutional_ownership cache-read year/quarter
  bug — separate concern; the read path filter is orthogonal to the write-path
  atomicity fix). File separate PR after this merges.
