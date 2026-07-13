# bd-2650/gykp — Fidelity persist autocommit fix (Tier 2)

**Beads:** OpenBBTechnical-2650 (tracker P0), OpenBBTechnical-gykp (finding P0)
**Base:** origin/develop
**Depends on:** none (structurally independent of bd-kh08 — needs explicit txn, not `replace_rows`)

## Goal

Convert `Tools/parse_fidelity_positions.py` from autocommit=True + DELETE-then-per-row-INSERT to autocommit=False with an explicit `conn.commit()`/`conn.rollback()` wrapper across the ENTIRE persist operation.

Pre-fix data-loss scenario (bd-gykp P0):
```
1. get_connection() returns autocommit=True conn
2. persist_to_mysql:
   - CREATE TABLE ... (committed)
   - DELETE FROM Portfolio_Positions WHERE snapshot_date = %s   (committed IMMEDIATELY)
   - for _, row in df.iterrows():
       INSERT ... (committed row-by-row)
       # any exception here → partial import, prior snapshot GONE
```

## Why NOT replace_rows

Unlike bd-n3sf's 8 sibling sites, this one bundles:
- Schema DDL (`CREATE TABLE`, `_ensure_portfolio_positions_schema`)
- `Account_Owner` population
- The `Portfolio_Positions` DELETE+INSERT
- `_rebuild_portfolio_basket_for_snapshot` (deletes + re-inserts the derived basket)
- Final COUNT queries

All must be atomic together — a failure during basket rebuild should roll back the whole snapshot import, not just the basket delta. `replace_rows()` handles only the DELETE+INSERT-per-key pattern; it can't wrap multi-statement multi-table operations.

## Design decisions

### D1 — `get_connection` returns autocommit=False by default
- Add keyword-only `autocommit: bool = False` parameter for backward compat with any caller that expects autocommit=True
- All 3 in-tree callers (`persist_to_mysql`, `persist_basket_positions_to_mysql`, `parse_baskets_workflow` at line ~1104) switch to the default (autocommit=False)
- Any external tool importing `get_connection` continues to work with explicit `autocommit=True` opt-in

### D2 — Explicit try/commit/except/rollback pattern
```python
conn = get_connection(database)
try:
    with conn.cursor() as cur:
        # ... all DDL, DELETE, INSERT, basket rebuild ...
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
```

Rationale:
- If ANY step fails (schema error, DELETE fails, INSERT fails, basket rebuild fails), the rollback restores the pre-import state
- The `raise` re-throws so callers see the failure (this is a CLI tool — failures should exit non-zero, not silently succeed)
- The `finally: conn.close()` is essential — pymysql doesn't auto-close on exception

### D3 — 3 persist functions all get the same treatment
- `persist_to_mysql` (line 1291)
- `persist_basket_positions_to_mysql` (line 1149)
- `parse_baskets` workflow at line ~1093 (does DELETE + rebuild basket from Portfolio_Positions)

Each gets the same try/commit/except/rollback/finally block.

### D4 — Do NOT change `INSERT_SQL` or the loop body
- pymysql cursor operations under autocommit=False buffer until commit; the loop stays as-is
- executemany-style optimization is out of scope (bd-followup if profile shows it matters)

## Test plan

### Unit tests (`test_parse_fidelity_persist_atomicity.py` — new)

For each of the 3 persist functions:

1. **`test_happy_path_commits`** — mock a working connection; assert `conn.commit()` called exactly once, `conn.rollback()` NOT called, no exception
2. **`test_insert_failure_triggers_rollback`** — mock `cur.execute` to raise on the 5th INSERT (mid-loop); assert `conn.rollback()` called, `conn.commit()` NOT called, exception propagates
3. **`test_delete_failure_triggers_rollback`** — mock `cur.execute` to raise on the DELETE; assert rollback + propagate
4. **`test_connection_closed_on_success_and_failure`** — assert `conn.close()` called in both paths (via try/finally)

**Total:** 3 sites × 4 tests = 12 tests

### RED-then-GREEN verification

Before committing the semantic fix:
1. Write all 12 tests → 12 FAIL on pre-fix code (no rollback, no commit — autocommit=True never calls .commit())
2. Apply the fix → all 12 PASS
3. Revert (put back autocommit=True in `get_connection`) → tests fail again
4. Re-apply → PASS

## Rollout — single PR (`fix/qc-tools-parse-fidelity-autocommit`)

Sub 1: `get_connection` — add autocommit kwarg, default False
Sub 2: `persist_to_mysql` — wrap in try/commit/except/rollback/finally
Sub 3: `persist_basket_positions_to_mysql` — same wrap
Sub 4: `parse_baskets` workflow persist block — same wrap
Sub 5: 12 unit tests

**Commits:**
1. `docs(qc)`: design spec
2. `fix(tools)`: autocommit=False + explicit transaction wrap (3 sites) + tests

## Beads closed by this PR

- **OpenBBTechnical-2650** (tracker)
- **OpenBBTechnical-gykp** (Tools/parse_fidelity_positions.py autocommit + DELETE+INSERT loop P0)
