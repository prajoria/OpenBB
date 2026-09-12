# MysqlPaperEngine Shared Pool Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `MysqlPaperEngine` correctly borrow shared PyMySQL connections and preserve atomic writes under the pool's autocommit default.

**Architecture:** Keep the public engine and schema unchanged while adding transactional locking clauses to mutation reads. Model the production context-manager contract in tests, delegate connection cleanup to `ConnectionPool`, and explicitly begin every engine write transaction before commit or rollback.

**Tech Stack:** Python, PyMySQL, SQLite test shim, pytest, Ruff

## Global Constraints

- Borrow every connection with `with pool.get_connection() as conn`.
- Never close a pooled connection directly from the engine.
- Call `conn.begin()` before SQL in every write transaction.
- Keep reads non-transactional and preserve SQLite/execution behavior.
- Use the real shared `ConnectionPool` in a network-free contract test.
- Do not modify or start work for #1719 or any other issue.

---

### Task 1: Realistic pool contract tests

**Files:**
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_mysql_paper_engine.py`

**Interfaces:**
- Consumes: `ConnectionPool.get_connection() -> AbstractContextManager[pymysql.Connection]`
- Produces: a SQLite-backed context-manager pool with observable `begin`, `commit`, `rollback`, entry, and exit events

- [ ] **Step 1: Change the SQLite double to the PyMySQL lifecycle**

Add `contextmanager` and `MagicMock` imports. Give `_SqliteConn` a `begin()`
method that executes `BEGIN`, track transaction calls, and make
`_FakePool.get_connection()` a `@contextmanager` that yields the wrapper.
Update direct test borrows to use `with pool.get_connection() as conn`.

- [ ] **Step 2: Add lifecycle and production contract tests**

Add tests equivalent to:

```python
def test_write_begins_and_commits(engine, pool):
    pool.events.clear()
    engine.submit_batch(_batch(_tk("MSFT")))
    assert pool.events == ["enter", "begin", "commit", "exit"]

def test_failed_write_rolls_back(engine, pool):
    pool.events.clear()
    with pytest.raises(PaperEngineError, match="unknown order_id"):
        engine.record_fill("missing", Decimal("1"), Decimal("1"), _t())
    assert pool.events == ["enter", "begin", "rollback", "exit"]

def test_read_does_not_begin(engine, pool):
    pool.events.clear()
    engine.get_account()
    assert pool.events == ["enter", "exit"]
```

Instantiate the real `ConnectionPool` with a config mock whose
`connection_params` is `{}`. Monkeypatch
`openbb_fmp_cached.utils.database.pymysql.connect` to open a fresh
SQLite-backed connection per borrow, then construct `MysqlPaperEngine` and call
`get_account()`. Assert the connect mock received `cursorclass=DictCursor` and
`autocommit=True`. Add a deterministic two-session interleaving test that
pauses one fill after reading prior fills, observes the other session waiting
on the simulated `FOR UPDATE` order lock, and confirms the second fill rejects
an overfill after the first commits.

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
& .venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_mysql_paper_engine.py -q
```

Expected: failures show `_GeneratorContextManager` has no `cursor`/`close`, or
that `begin()` was not called.

### Task 2: Minimal engine contract fix

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/mysql_paper_engine.py:1-32,237-254`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_mysql_paper_engine.py`

**Interfaces:**
- Consumes: the context manager returned by `self._pool.get_connection()`
- Produces: `_acquire() -> Iterator[Any]` and `transaction() -> Iterator[Any]`
  with pool-owned cleanup and explicit transaction boundaries

- [ ] **Step 1: Correct the documented dialect and lifecycle**

Change the module documentation from mysql-connector to PyMySQL and document
context-managed borrowing plus explicit transactions for autocommit sessions.

- [ ] **Step 2: Implement the minimal lifecycle**

```python
@contextmanager
def _acquire(self) -> Iterator[Any]:
    with self._pool.get_connection() as conn:
        yield conn

@contextmanager
def transaction(self) -> Iterator[Any]:
    with self._acquire() as conn:
        conn.begin()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
```

- [ ] **Step 3: Lock rows used to derive ledger mutations**

Append `FOR UPDATE` to the scoped order reads in `record_fill()` and
`cancel_order()`, and to the account, open-lot, and materialized-position reads
inside fill side effects. This keeps concurrent connections from validating or
calculating updates from stale rows after explicit transactions make the
production path usable. Replace account bootstrap's check-then-insert with an
`INSERT ... ON DUPLICATE KEY UPDATE` no-op so concurrent constructors cannot
split execution between MySQL and a fallback backend after a duplicate-key
error.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run the Task 1 pytest command.

Expected: all tests pass.

### Task 3: Regression, diagnostics, and safe real-path harness

**Files:**
- Create (untracked evidence): `.dev-cycle/verify-phase6.log`
- Verify only: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/paper_engine.py`
- Verify only: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py`

**Interfaces:**
- Consumes: both paper-engine backends and the shared `ConnectionPool`
- Produces: test and harness evidence that MySQL lifecycle changed without altering SQLite semantics

- [ ] **Step 1: Run focused regression tests**

```powershell
& .venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\extensions\techtrade\tests\unit\test_mysql_paper_engine.py `
  openbb_platform\extensions\techtrade\tests\unit\test_paper_engine.py `
  openbb_platform\extensions\techtrade\tests\unit\test_paper_engine_p3b.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run diagnostics**

```powershell
& .venv_portfolio\Scripts\python.exe -m ruff check `
  openbb_platform\extensions\techtrade\openbb_techtrade\execution\mysql_paper_engine.py `
  openbb_platform\extensions\techtrade\tests\unit\test_mysql_paper_engine.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Drive the production pool path**

Run a Python harness that imports the real `ConnectionPool`, monkeypatches only
`pymysql.connect`, constructs `MysqlPaperEngine`, executes account/order/fill
operations through SQLite storage, asserts transaction events and final cash,
and writes sanitized stdout to `.dev-cycle/verify-phase6.log`.

Expected evidence includes context entry/exit, explicit begin/commit, rollback
on a rejected fill, and unchanged paper-account arithmetic.

### Task 4: Review, publish, and converge

**Files:**
- Modify only if review finds an in-scope defect
- Create (untracked evidence): `.dev-cycle/findings-pr<PR>-iter<N>.md`

**Interfaces:**
- Consumes: the completed issue #2059 diff and validation evidence
- Produces: a merged PR to `portfolio` that closes #2059

- [ ] **Step 1: Run simplify, code, and security reviews**

Review only the issue #2059 diff. Apply and re-verify in-scope findings; do not
start unrelated lanes.

- [ ] **Step 2: Commit and push**

Commit code and tests with:

```text
fix(techtrade): honor shared PyMySQL pool contract (#2059)

Closes #2059

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

Push `fix/pi-execution-foundation-gh-2059`.

- [ ] **Step 3: Open and converge the PR**

Create one PR targeting `portfolio`, title
`fix(techtrade): honor shared PyMySQL pool contract (#2059)`, with a body line
`Closes #2059`. Resolve all current-head review threads and required checks,
merge, verify issue #2059 is closed, and remove the worktree/branch when safe.
