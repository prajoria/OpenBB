# bd-kh08 — Tier-0 DB safety helpers design

**Date:** 2026-07-08
**Bead:** [OpenBBTechnical-kh08](../../.beads) — feat/qc-db-helpers, Tier-0 DB safety helpers
**Author:** Claude Code (openbb-dev-cycle Phase 1)
**Status:** DRAFT — awaiting user approval before Phase 2

---

## 1. Goal

Add two safety helpers to
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/database.py`:

1. **`safe_identifier(name: str) -> str`** — regex-allowlist SQL identifier
   sanitizer. Fixes the CREATE-DATABASE SQL-injection cluster:
   - bd-y5fn: `Tools/load_espp_plan.py:363`
   - bd-v9ri: `Tools/parse_fidelity_positions.py:1224`
   - bd-20zx: `openbb_fmp_cached/utils/cache_schema.py:29`
   - bd-o1oy: `openbb_fmp_cached/utils/database.py:241`
2. **`replace_rows(table, where_col, where_val, rows, *, columns=None) -> int`**
   — transactional DELETE + INSERT that either commits everything or
   rolls back. Fixes the autocommit + DELETE-then-INSERT data-loss cluster:
   - bd-ihdn: `institutional_ownership.py::_store_institutional`
   - bd-n3sf: 11 sibling fmp_cached model sites (balance_sheet, cash_flow,
     income_statement, financial_ratios, key_metrics, equity_quote,
     etf_holdings, analyst_estimates, …)
   - bd-2650/gykp: `Tools/parse_fidelity_positions.py::persist_to_mysql`
   - bd-hyzu (follow-up from PR #355): `_store_financial_ratios` race

**Strategic leverage:** 15+ downstream P0/P1 beads block on this Tier-0
work. Shipping bd-kh08 first unblocks the entire Tier-1/Tier-2 batch
flow.

## 2. Success criteria

- Both helpers have ≥95% line coverage via pytest, including:
  - `safe_identifier` malicious-input rejection (backtick, semicolon,
    quote, whitespace, null byte, length overflow, digit-first)
  - `replace_rows` rollback-on-partial-failure (pre-fix data survives)
- New helpers ship with no regressions in existing
  `openbb_fmp_cached/tests/` — 73 pre-existing unit tests continue to pass.
- Existing callers of `execute_query` / `execute_many` are unchanged.
  (The downstream branches that consume these helpers land in separate PRs
  per the QC remediation plan tiers.)
- Black-clean; ruff-clean on touched files.

## 3. API

### 3.1 `safe_identifier(name: str) -> str`

**Signature:**
```python
def safe_identifier(name: str) -> str:
    """Validate a SQL identifier against a strict regex allowlist.

    MySQL's parameterized-query API does not accept identifier positions
    (DB / table / column names) — only values. This helper is the only
    approved way to interpolate a caller-controlled string into a DDL
    identifier position.

    Rules (matches MySQL 8.x unquoted identifier grammar minus digits-
    first, per SQL-92):
      - 1-64 characters
      - Must start with a letter (A-Z, a-z) or underscore
      - Remaining chars: letters, digits, underscores

    Args:
        name: The candidate identifier. Typically a DB name from a CLI
            arg or config file that will be interpolated into a DDL
            statement (e.g. CREATE DATABASE IF NOT EXISTS {name}).

    Returns:
        `name` unchanged if valid — so callers can write
        ``f"CREATE DATABASE IF NOT EXISTS {safe_identifier(db)}"``.

    Raises:
        ValueError: On any input that doesn't match the allowlist. The
            error message includes ``repr(name)`` so operators can trace
            what was rejected.
    """
```

**Regex:** `^[A-Za-z_][A-Za-z0-9_]{0,63}$`

**Not a general SQL escape.** For value positions, use the pool's
`execute_query(sql, params)` — this helper is *only* for DDL positions
that can't be parameterized.

### 3.2 `replace_rows(table, where_col, where_val, rows, *, columns=None) -> int`

**Signature:**
```python
def replace_rows(
    table: str,
    where_col: str,
    where_val: Any,
    rows: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
) -> int:
    """Atomically DELETE rows matching a WHERE clause then INSERT new rows.

    Wraps DELETE + INSERT in a single explicit transaction with
    commit/rollback. Fixes the autocommit + DELETE-then-INSERT data-loss
    class where a partial-write failure between DELETE and INSERT leaves
    the cache empty (bd-ihdn, bd-n3sf, bd-hyzu).

    Args:
        table: SQL table name. Passed through :func:`safe_identifier`
            (defense in depth).
        where_col: Column name for the DELETE WHERE clause. Passed
            through :func:`safe_identifier`.
        where_val: Value the WHERE clause matches (parameterized —
            NOT interpolated).
        rows: List of row dicts to INSERT. Empty list is a valid
            degenerate case (just does the DELETE atomically).
        columns: Optional explicit column list for the INSERT. If
            None, the columns are inferred from the sorted union of
            keys across all `rows` (deterministic; safe for logs and
            reproducibility).

    Returns:
        Number of rows actually inserted (from ``cursor.rowcount``
        after the INSERT — 0 if `rows` was empty).

    Raises:
        ValueError: If `table` or `where_col` fails `safe_identifier`.
        pymysql.MySQLError: On any DB error. Transaction is rolled back
            first, so the pre-fix data survives.
    """
```

**Isolation contract:** uses a fresh `pymysql.connect(..., autocommit=False)`
connection — NOT the pool's `get_connection()` (which sets `autocommit=True`
at get-time). Fresh connection is closed in a `finally` clause.

**Ordering:** DELETE runs before INSERT within the transaction. If INSERT
fails mid-batch (say row 5 of 10 violates a NOT NULL), the DELETE is
rolled back too — the pre-existing rows survive.

## 4. Test plan

New file: `openbb_platform/providers/fmp_cached/tests/test_db_safety_helpers.py`

### 4.1 `safe_identifier` tests (7)

- `test_valid_simple_name` — `"my_table"` returns unchanged
- `test_valid_max_length_64` — 64-char name accepted
- `test_valid_with_digits_and_underscores` — `"tbl_2026_q1"` accepted
- `test_valid_leading_underscore` — `"_hidden"` accepted
- `test_rejects_length_65` — raises ValueError with `repr` in message
- `test_rejects_leading_digit` — `"9table"` rejected
- `test_rejects_malicious_inputs` — parametrized over `["", "a b", "a;b",
  "a'b", "a`b", 'a"b', "a\\x00b", "a-b", "a.b", "'; DROP TABLE users; --"]`
  → all raise ValueError

### 4.2 `replace_rows` tests (7)

Uses a real `sqlite3` in-memory DB for isolation (portable + doesn't
require MySQL). If the helpers need pymysql-specific behavior, mock the
connection instead.

**Actually — MySQL vs SQLite semantics differ enough that mocking is
safer.** Use `unittest.mock.patch` on `pymysql.connect` and assert the
correct SQL was executed in order.

- `test_happy_path_inserts_rows` — 3 rows inserted; assert DELETE
  executed first, then executemany INSERT, then commit
- `test_empty_rows_deletes_only` — empty `rows` list runs DELETE +
  commit, no INSERT call
- `test_rejects_invalid_table` — `"my; DROP"` raises ValueError from
  `safe_identifier`
- `test_rejects_invalid_where_col` — same for where_col
- `test_insert_failure_rolls_back` — INSERT raises → assert rollback()
  called and commit() NOT called (DELETE undone)
- `test_columns_inferred_from_row_keys_sorted` — no explicit columns →
  assert INSERT SQL uses sorted key order
- `test_columns_explicit_used_verbatim` — explicit `columns=[...]` →
  assert INSERT SQL uses that exact order

### 4.3 Coverage target

Run `pytest --cov=openbb_fmp_cached.utils.database`; helper functions
should be ≥95% line coverage. Existing coverage on the rest of the file
is unchanged.

## 5. Design decisions to review

| # | Decision | Alternative | Rationale |
|---|----------|-------------|-----------|
| **D1** | Regex allowlist for identifiers | Backtick-quote every identifier (MySQL-specific) | Allowlist rejects unknown-shape inputs LOUDLY. Backtick-quote silently accepts anything (including backticks-in-input as covert-injection). Allowlist also stays portable if we ever migrate off MySQL. |
| **D2** | Two new helpers, don't modify `execute_query` / `execute_many` | Wrap those with transaction logic | Preserves ALL existing callers (unchanged behavior) and gives the downstream batch fixes (bd-9loj, bd-n3sf) a clean seam. Non-breaking change. |
| **D3** | `replace_rows` uses a fresh `pymysql.connect(..., autocommit=False)` | Reuse pool + toggle autocommit mid-connection | Pool connections are baked with `autocommit=True` at get-time. Toggling mid-connection is a known pymysql footgun that leaks state across pool users. Fresh connection is simpler and correct. |
| **D4** | Column ordering when inferred: sorted alphabetically | First-row-dict iteration order | Sorted is deterministic across Python versions AND makes the resulting SQL diff-stable in logs (aids debugging + reproducibility). |
| **D5** | Empty `rows` still opens a transaction for the DELETE | Skip transaction, execute DELETE via pool | Consistency — every caller can rely on "either everything happens or nothing happens" including the degenerate empty-rows case. Also simpler contract to document. |
| **D6** | Helpers ship in `openbb_fmp_cached/utils/database.py`, not `openbb_core` | Ship in openbb_core so all providers can reuse | Bead scope is fmp_cached; cross-provider promotion is deferred until we have a second provider that needs them. Non-breaking for openbb_core. |

## 6. Out of scope

- Downstream consumption: the 15+ P0/P1 beads that USE these helpers
  land in separate PRs per the QC remediation plan tiers (bd-9loj,
  bd-n3sf, bd-2650, bd-gykp, bd-hyzu, etc.).
- MySQL-specific optimizations (`ON DUPLICATE KEY UPDATE`, `REPLACE
  INTO`): can be follow-ups if a unique index is added later. This PR
  intentionally uses the portable DELETE+INSERT-in-transaction pattern
  matching bead-n3sf's contract.
- Promotion to `openbb_core`: deferred until a second provider needs
  these (see D6).
- Migration of existing callers: separate PRs.

## 7. Rollout

1. **This PR (bd-kh08)**: ships helpers + tests only. No behavior
   change for existing callers.
2. **bd-9loj follow-up**: 4-site DDL-injection fix using `safe_identifier`.
3. **bd-n3sf follow-up**: 11-site cache-replace using `replace_rows`.
4. **bd-2650/gykp follow-up**: Fidelity autocommit fix using
   `replace_rows`.
5. **bd-hyzu follow-up**: `_store_financial_ratios` race fix using
   `replace_rows`.

Each downstream PR runs its own openbb-dev-cycle loop with parallel
review agents.

## 8. Estimated effort

- **This PR**: 1 loop (~1 session): helpers + 14 tests + PR + review-fix
  cycle.
- **Full downstream drain**: 4-5 additional loops as batched above.
