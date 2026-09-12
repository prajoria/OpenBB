# FMP Cached Database Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure an explicit warmer database selects every downstream `fmp_cached` cache read and write without process-global mutation.

**Architecture:** Add a validated `ContextVar`-backed scope at the provider database boundary. Thread the warmer's existing `database` argument into that scope around the complete position-history and ETF-holdings provider operations.

**Tech Stack:** Python 3.10+, `contextvars`, `contextlib`, pytest, PyMySQL, OpenBB provider framework.

## Global Constraints

- Do not mutate `DB_NAME` temporarily around provider calls.
- Existing callers without a database override must retain configured singleton-pool behavior.
- Jobs adapters remain unable to accept database or credential overrides.
- Do not modify execution, configuration, snapshot, viewer, or risk files.

---

### Task 1: Request-scoped provider database selection

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/database.py`
- Test: `openbb_platform/providers/fmp_cached/tests/test_database.py`

**Interfaces:**
- Produces: `database_override(database: str | None) -> Iterator[None]`
- Produces: `get_connection_pool() -> ConnectionPool`, honoring the active override without mutating `_connection_pool`

- [ ] **Step 1: Write failing tests**

Add tests proving an active override changes `connection_params["database"]`,
nested scopes restore their parents, invalid identifiers fail before connection,
and leaving the scope restores the configured singleton.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest openbb_platform/providers/fmp_cached/tests/test_database.py -q`

Expected: failures because `database_override` does not exist.

- [ ] **Step 3: Implement the scope**

Use `ContextVar[str | None]`, validate non-`None` names with `safe_identifier`,
set/reset with the context variable token, and have `get_connection_pool`
return a new `ConnectionPool` built from copied configured parameters only
while an override is active.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command; expect all tests to pass.

### Task 2: Position-history propagation

**Files:**
- Modify: `openbb_platform/tools/portfolio_utils/portfolio_utils/fetch_position_history.py`
- Test: `openbb_platform/tools/portfolio_utils/tests/test_fetch_position_history.py`

**Interfaces:**
- Consumes: `database_override(database)`
- Changes: `_fetch_one_symbol_history(..., database: str | None = None)`
- Changes: `fetch_history(..., database: str | None = None)`

- [ ] **Step 1: Write failing tests**

Add a test whose fake default fetch observes the active provider pool database
and assert `run_position_history_warm(database="alternate_db")` observes
`alternate_db`; add a no-override regression.

- [ ] **Step 2: Verify RED**

Run the position-history test module and expect the explicit database assertion
to fail against the configured default.

- [ ] **Step 3: Implement propagation**

Thread `database` from `run_position_history_warm` to `fetch_history`; for the
default fetcher, pass it into `_fetch_one_symbol_history` and wrap all cache
operations in `database_override(database)`. Do not add the kwarg to injected
fetchers.

- [ ] **Step 4: Verify GREEN**

Run the position-history test module; expect all tests to pass.

### Task 3: ETF-holdings propagation and full validation

**Files:**
- Modify: `openbb_platform/tools/portfolio_utils/portfolio_utils/refresh_etf_holdings_cache.py`
- Test: `openbb_platform/tools/portfolio_utils/tests/test_refresh_etf_holdings_cache.py`

**Interfaces:**
- Consumes: `database_override(database)`
- Changes: `refresh_one_etf(..., database: str | None = None)`
- Changes: `refresh_universe(..., database: str | None = None)`

- [ ] **Step 1: Write failing tests**

Add a test whose injected holdings function reads the active provider pool
database and assert `run_etf_holdings_warm(database="alternate_db")` observes
`alternate_db`; add no-leakage and no-override assertions.

- [ ] **Step 2: Verify RED**

Run the ETF warmer test module and expect the explicit database assertion to
fail against the configured default.

- [ ] **Step 3: Implement propagation**

Thread `database` from `run_etf_holdings_warm` through `refresh_universe` and
`refresh_one_etf`; wrap the provider/injected holdings call in
`database_override(database)`.

- [ ] **Step 4: Verify GREEN and regressions**

Run all three changed test modules, then the repository's targeted Ruff checks.
Drive both warmer paths with injected offline collaborators and save output to
`.dev-cycle/verify-phase6.log`.

- [ ] **Step 5: Review and ship**

Run local code/security/simplification review, commit with `Refs #2051`, push,
open a PR to `portfolio` containing a standalone `Closes #2051.` line, converge
review feedback, merge, and verify issue closure.
