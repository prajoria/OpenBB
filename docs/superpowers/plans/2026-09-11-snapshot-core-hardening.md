# Snapshot Core Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete issues #1964-#1967 by hardening the generic EOD snapshot
store with an authoritative LIVE pointer, provenance/schema contracts, strict
PII routing, US-equity session semantics, and standalone post-close
orchestration.

**Architecture:** Extend only `openbb_techtrade.snapshot`; leave the legacy
`openbb_techtrade.snapshots` scan store unchanged. SQLite and MySQL keep
immutable snapshot history while an explicit pointer controls visibility.
Focused registry, semantics, job-contract, and refresh modules keep policy out
of the already-large SQL backend files.

**Tech Stack:** Python 3.10-3.13, sqlite3, PyMySQL-compatible pooled
connections, exchange-calendars, pandas, argparse, importlib.metadata, pytest.

## Global Constraints

- LIVE is resolved only through `pi_eod_live_pointer`, never `MAX(as_of_session)`.
- Only validated `ok` rows may move LIVE; rollback targets an exact good row.
- `snapshot_input_hash()` includes `engine_version`.
- Unknown payload schema versions fail closed.
- PII-scoped datasets never write to shared MySQL and route only to an
  outside-repository local SQLite store.
- Job errors and display metadata contain no account data, positions, values,
  entity keys, or raw exception messages.
- XNYS session closes define freshness; there is no intraday freshness mode.
- Consumer fan-out in #1968/#1969/#1942-#1945 is excluded.
- Use `.venv\Scripts\python.exe` from the repository root.

---

### Task 1: SQLite pointer, rollback, hash, and migration

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

**Interfaces:**
- Produces:
  `snapshot_input_hash(inputs: object, engine_version: str) -> str`,
  `SnapshotStore.rollback(dataset, entity_key, as_of_session, job_run_id) -> bool`.
- Consumes: existing `SnapshotRow`, stage/validate/promote lifecycle, schema
  verification helpers.

- [ ] **Step 1: Add failing SQLite tests**

Add tests that assert:

```python
def test_partial_never_moves_live_pointer(store):
    good = stage_ok(store, session=date(2026, 9, 9), run="good")
    assert store.promote(*good)
    partial = stage_partial(store, session=date(2026, 9, 10), run="partial")
    assert not store.promote(*partial)
    assert store.get_live(DATASET, KEY).job_run_id == "good"

def test_rollback_repoints_exact_good_history(store):
    first = stage_ok(store, session=date(2026, 9, 9), run="first")
    second = stage_ok(store, session=date(2026, 9, 10), run="second")
    assert store.promote(*first)
    assert store.promote(*second)
    assert store.rollback(DATASET, KEY, date(2026, 9, 9), "first")
    assert store.get_live(DATASET, KEY).job_run_id == "first"

def test_hash_changes_with_engine_version():
    inputs = {"symbols": ["AAPL"], "close": [100.0]}
    assert snapshot_input_hash(inputs, "engine-a") != snapshot_input_hash(
        inputs, "engine-b"
    )
```

Also build a version-1 SQLite file, open it with the new store, and prove the
existing `state='live'` row is seeded into the pointer without data loss.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py -q
```

Expected: failures for the absent pointer table, `rollback`, and hash helper.

- [ ] **Step 3: Implement schema-v2 migration**

Add:

```sql
CREATE TABLE IF NOT EXISTS pi_eod_live_pointer (
    dataset TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    as_of_session TEXT NOT NULL,
    job_run_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (dataset, entity_key),
    FOREIGN KEY (dataset, entity_key, as_of_session, job_run_id)
      REFERENCES pi_eod_snapshot(dataset, entity_key, as_of_session, job_run_id)
);
```

Set `SNAPSHOT_SCHEMA_VERSION = 2`. For version 1, run one immediate
transaction: create the pointer table, insert one pointer per existing LIVE
row, verify every LIVE row has a pointer, and then stamp version 2. Versions
outside `{0, 1, 2}` remain refused.

- [ ] **Step 4: Make the pointer authoritative**

Change `get_live()` to an indexed join. In `promote()`, reject every status
other than `SnapshotStatus.OK`, update audit states, and upsert the pointer in
the same transaction. Implement `rollback()` with exact-key validation and the
same transaction discipline.

Implement the hash helper as deterministic JSON:

```python
def snapshot_input_hash(inputs: object, engine_version: str) -> str:
    if not engine_version.strip():
        raise ValueError("engine_version must be non-empty")
    material = json.dumps(
        {"engine_version": engine_version, "inputs": inputs},
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
```

- [ ] **Step 5: Run GREEN and reverse checks**

Run the Task 1 test file. Then temporarily change the pointer join back to a
state-only read and confirm the pointer/state divergence test fails; restore
and rerun green.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py
git commit -m "feat(techtrade): add authoritative snapshot pointers" -m "Refs #1964" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: MySQL pointer and rollback parity

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_mysql_snapshot_store.py`

**Interfaces:**
- Consumes: Task 1 schema-v2 contract and `SnapshotStore.rollback`.
- Produces: MySQL pointer DDL, migration/adoption checks, pointer-join reads,
  atomic promote and rollback parity.

- [ ] **Step 1: Add failing MySQL-double tests**

Extend the existing PyMySQL-shaped double tests to prove:

```python
assert "CREATE TABLE IF NOT EXISTS pi_eod_live_pointer" in executed_sql
assert mysql_store.get_live(DATASET, KEY).job_run_id == pointer_job_id
assert mysql_store.rollback(DATASET, KEY, old_session, old_run)
```

Cover a partial candidate, a nonexistent rollback target, a non-OK rollback
target, and rollback on commit failure. Assert all values remain `%s` bound.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py -q
```

Expected: missing pointer DDL and rollback behavior failures.

- [ ] **Step 3: Implement MySQL parity**

Create `pi_eod_live_pointer` with binary-collated bounded key columns, an
InnoDB composite foreign key, and `DATETIME(6) updated_at`. Verify its columns,
collations, engine, primary key, and foreign key from `information_schema`.
Migrate version 1 by seeding from the single-LIVE guard before stamping 2.

Lock candidate, pointer, and pointed-to row with `FOR UPDATE`. Update history
states and pointer in one explicit transaction. Treat duplicate/deadlock
outcomes as a clean lifecycle refusal where the existing store does so.

- [ ] **Step 4: Run GREEN**

Run both snapshot store suites and the MySQL contract/introspection tests.

- [ ] **Step 5: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py openbb_platform/extensions/techtrade/tests/unit/test_mysql_snapshot_store.py
git commit -m "feat(techtrade): add MySQL snapshot pointer parity" -m "Refs #1964" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Dataset registry, schema dispatch, and PII routing

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/registry.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_registry.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/config.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_config.py`

**Interfaces:**
- Produces:
  `DatasetDefinition`, `SnapshotDatasetRegistry`,
  `SnapshotStoreRouter.for_dataset(name) -> SnapshotStore`,
  `read_live_payload(store, registry, dataset, entity_key) -> object`,
  `ConfigError`, `_validate_outside_repo(name, path, repo_root=None)`.
- Consumes: Task 1 pointer-backed `get_live`.

- [ ] **Step 1: Add failing registry and path tests**

Cover:

```python
registry.register(
    DatasetDefinition(
        name="pi.account.weights",
        pii_scoped=True,
        payload_schema_version="1",
        readers={"1": lambda payload: payload["weights"]},
    )
)
assert router.for_dataset("pi.account.weights") is local_store
with pytest.raises(PiiStoreRequired):
    SnapshotStoreRouter(shared_store, None, registry).for_dataset(
        "pi.account.weights"
    )
with pytest.raises(ConfigError):
    snapshot_db_path(repo_root / "snapshot.db")
```

Assert the default registry marks `techtrade.movers` and `techtrade.scan`
`pii_scoped=False`. Assert an unknown stored schema version raises
`UnsupportedPayloadSchema`.

- [ ] **Step 2: Run RED**

Run registry and config tests. Expected: missing types and in-repository path
currently accepted.

- [ ] **Step 3: Implement strict path validation**

Resolve and expand both the candidate and repository root before comparison.
Reject equality and descendants with `ConfigError` before
`SqliteSnapshotStore` creates a parent directory. Apply this to explicit paths,
environment paths, defaults passed by callers, and MySQL fallback paths.

- [ ] **Step 4: Implement registry, dispatch, and routing**

Canonicalize names on registration and lookup. Reject duplicate definitions.
Dispatch only by the stored `payload_schema_version`; do not silently fall back
to the current renderer. Route PII definitions only to local SQLite.

Inject a registry into `MysqlSnapshotStore`; `stage()` refuses a registered
PII-scoped dataset even when a caller bypasses the router. Do not log the
dataset's entity key or payload.

- [ ] **Step 5: Run GREEN**

Run snapshot, registry, config, and MySQL snapshot tests.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/config.py openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit
git commit -m "feat(techtrade): enforce snapshot PII routing" -m "Refs #1965" -m "Refs #1964" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: US-equity EOD display semantics

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/semantics.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_semantics.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`

**Interfaces:**
- Produces:
  `last_completed_session(now, calendar_name="XNYS") -> date`,
  `snapshot_staleness(as_of_session, now, calendar_name="XNYS") -> SnapshotStaleness`,
  `build_eod_display(as_of_session, now, reports_before_next_open=False) -> EodDisplay`.
- Consumes: `exchange_calendars`, `pandas`.

- [ ] **Step 1: Add failing calendar tests**

Use fixed UTC instants to prove:

- Friday after close, Saturday, Sunday, and Monday before open all resolve to
  Friday.
- July 4 resolves to the prior completed XNYS session.
- A normal close and an early close switch to the just-completed session only
  after the calendar-provided close.
- zero/one/two missed sessions map to green/amber/red.
- missing `as_of_session` is red.
- every display carries
  `EOD planning snapshot — not a live/intraday quote`.
- `reports_before_next_open=True` yields `Reports before next open`.

- [ ] **Step 2: Run RED**

Run the new semantics test file. Expected: module import failure.

- [ ] **Step 3: Implement calendar-derived semantics**

Convert `now` to UTC, enumerate XNYS sessions through its local date, and
select the newest session whose calendar close is not after `now`. Count
completed sessions strictly after `as_of_session` through that session. Return
frozen dataclasses/enums without any entity or account field.

- [ ] **Step 4: Run GREEN**

Run the semantics tests twice, including once with a non-UTC aware input to
prove it is rejected rather than guessed.

- [ ] **Step 5: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit/test_snapshot_semantics.py
git commit -m "feat(techtrade): define EOD snapshot semantics" -m "Refs #1966" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Job bookkeeping and targeted retry storage

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/job.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_job_store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_mysql_snapshot_store.py`

**Interfaces:**
- Produces:
  `SnapshotJobState`, `SnapshotJob`, `SnapshotJobAlreadyRunning`,
  `SnapshotJobStore.start_job`, `finish_job`, `record_job_errors`,
  `retry_entity_keys`, and `get_job`.
- Consumes: Task 1/2 backend transactions and Task 3 canonical dataset names.

- [ ] **Step 1: Add failing SQLite job tests**

At fixed UTC times assert:

```python
store.start_job(DATASET, "run-1", started_at=t0)
with pytest.raises(SnapshotJobAlreadyRunning):
    store.start_job(DATASET, "run-2", started_at=t0 + timedelta(minutes=5))
store.start_job(DATASET, "run-3", started_at=t0 + timedelta(hours=2, seconds=1))
assert store.get_job("run-1").state is SnapshotJobState.FAILED
```

Record two failures, assert `retry_entity_keys("run-1")` returns only their
canonical entity keys, then finish the run with exact counts. Assert persisted
errors contain stable exception class/category names and never raw messages.

- [ ] **Step 2: Run RED**

Run the new job test file. Expected: absent tables and methods.

- [ ] **Step 3: Implement shared job types and SQLite operations**

Create `pi_eod_snapshot_job` and `pi_eod_snapshot_job_error`. Add an indexed
uniqueness mechanism that permits at most one running row per dataset. In
`start_job`, atomically refuse a fresh lease or mark a lease older than two
hours failed with `stale_reclaimed` before inserting the new run.

`finish_job` may transition only the named running row and records UTC
`finished_at`, `n_ok`, `n_failed`, and a bounded category. Error recording
stores canonical entity keys for targeted retry but exposes no key in logs.

- [ ] **Step 4: Add and implement MySQL parity**

Extend the MySQL double with the two job tables, the generated nullable
`running_dataset` unique key, catalogue verification, `%s`-bound operations,
and `FOR UPDATE` locking. Mirror every SQLite lifecycle assertion.

- [ ] **Step 5: Run GREEN**

Run job, SQLite snapshot, and MySQL snapshot test files.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit
git commit -m "feat(techtrade): add snapshot job bookkeeping" -m "Refs #1967" -m "Refs #1964" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Standalone refresh orchestration

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/refresh.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_refresh.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/registry.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`

**Interfaces:**
- Produces:
  `ComputedSnapshot`, `SnapshotDatasetAdapter`,
  `SnapshotRefreshOrchestrator.run(dataset, retry_job_run_id=None)`,
  `main(argv=None) -> int`.
- Consumes: Task 1 hash/promotion, Task 3 registry/router, Task 4 completed
  session calculation, Task 5 leases/errors.

- [ ] **Step 1: Add failing orchestration tests**

With a synthetic PII-free adapter assert:

- a complete run starts, stages, validates, promotes, and finishes succeeded;
- a second concurrent run is refused without invoking compute;
- stale reclaim computes normally;
- a partial run records only failed keys and does not move LIVE;
- retry invokes compute only for `retry_entity_keys`;
- a fully recovered retry promotes all candidates and finishes succeeded;
- a still-partial retry preserves every prior pointer;
- `main(["--dataset", name])` executes on the calling main thread.

- [ ] **Step 2: Run RED**

Run the new refresh test file. Expected: module import failure.

- [ ] **Step 3: Implement orchestration**

Define an adapter contract with `entity_keys()` and
`compute(entity_key, as_of_session) -> ComputedSnapshot`. Resolve
`as_of_session` once per run. Compute every requested key into staging, record
sanitized failure categories, validate all successes, and promote only if the
entire requested set succeeds. Finish the job in `finally` on every accepted
run.

Use `snapshot_input_hash(computed.inputs, computed.engine_version)` and require
non-empty engine/payload schema versions.

- [ ] **Step 4: Implement CLI discovery**

Load adapters from the `openbb_snapshot_dataset` entry-point group. Parse
`--dataset` and optional `--retry-job-run-id`; construct the default router and
return a nonzero code with a PII-free message for an unknown/uninstalled
adapter. Do not call the legacy jobs service or worker-thread path.

- [ ] **Step 5: Run GREEN**

Run refresh plus all snapshot-core tests.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit/test_snapshot_refresh.py
git commit -m "feat(techtrade): orchestrate post-close snapshots" -m "Refs #1967" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Diagnostics, safe harness, and acceptance

**Files:**
- Create: `.dev-cycle/verify-phase6.log` (ignored evidence only)
- Modify: `docs/MEMORIES.md` only if a durable new convention is discovered

**Interfaces:**
- Consumes: all prior tasks.
- Produces: reviewable evidence for phases 5-9.

- [ ] **Step 1: Run targeted tests and diagnostics**

```powershell
.\.venv\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py openbb_platform\extensions\techtrade\tests\unit\test_snapshot_registry.py openbb_platform\extensions\techtrade\tests\unit\test_snapshot_semantics.py openbb_platform\extensions\techtrade\tests\unit\test_snapshot_job_store.py openbb_platform\extensions\techtrade\tests\unit\test_snapshot_refresh.py -q
.\.venv\Scripts\python.exe -m ruff check openbb_platform\extensions\techtrade\openbb_techtrade\snapshot openbb_platform\extensions\techtrade\tests\unit
.\.venv\Scripts\python.exe -m black --check openbb_platform\extensions\techtrade\openbb_techtrade\snapshot openbb_platform\extensions\techtrade\tests\unit
```

Expected: all pass.

- [ ] **Step 2: Run the full techtrade regression suite**

```powershell
.\.venv\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests -q
```

Expected: all pass.

- [ ] **Step 3: Exercise the real SQLite path**

Create a uniquely named database under the user's normal application-data
directory, outside the repository. Run a synthetic public-market adapter
through success, partial, targeted recovery, promote, rollback, close, reopen,
and EOD-display generation. Capture stdout in
`.dev-cycle/verify-phase6.log`, then delete the database. Do not print an
absolute local path.

- [ ] **Step 4: Review and publish**

Run the simplify, code-review, and security-review gates. Apply and verify every
in-scope finding. Commit, push, and open one PR into `portfolio` with exactly:

```text
Closes #1964.
Closes #1965.
Closes #1966.
Closes #1967.
```

Converge until checks and active review threads are clear, merge, verify all
four issues closed, and clean the worktree/branch.
