# EOD Snapshot Store Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement #1963's reusable, compute-free EOD snapshot persistence layer with SQLite and MySQL backends, validation-gated atomic promotion, keep-last-good behavior, and backend fallback.

**Architecture:** Add a new `openbb_techtrade.snapshot` package. The shared module owns value types, canonicalization, validation, the `SnapshotStore` Protocol, SQLite implementation, and backend factory; the MySQL module mirrors the Protocol over the shared `fmp_cached` connection pool. Writers stage and validate rows before promotion; readers resolve only the explicit `state='live'` pointer.

**Tech Stack:** Python 3.10-3.13, `dataclasses`, `enum`, `typing.Protocol`, `sqlite3`, MySQL Connector-compatible pooled connections, pytest.

## Global Constraints

- This is EOD planning infrastructure only; it must never represent intraday data as current.
- LIVE is an explicit promoted pointer, never a `MAX(as_of_session)` query.
- All writes follow stage -> validate -> atomic promote.
- A lower-ranked snapshot must never displace a higher-ranked LIVE snapshot.
- SQLite stores dates/timestamps as sortable ISO-8601 text; MySQL uses `DATE` and `DATETIME(6)`.
- Exactly one LIVE row per `(dataset, entity_key)` must be enforced by each database.
- Both read and write boundaries canonicalize dataset and entity keys.
- The read path performs no provider calls or computation.
- `PI_SNAPSHOT_ENGINE=mysql` is the default; construction failure logs a warning and falls back to SQLite.
- No account holdings, brokerage values, or other PII may enter this shared store.
- Every load-bearing regression test must be reverse-verified against the primitive it guards.

---

### Task 1: Public snapshot contract and canonicalization

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

**Interfaces:**
- Produces: `SnapshotStatus`, `SnapshotState`, `ValidationResult`, `RetentionPolicy`, `SnapshotRow`, `SnapshotStore`, `canonical_key()`, and `default_validator()`.
- Consumes: standard-library `date`, `datetime`, `Enum`, `dataclass`, and `Protocol`.

- [ ] **Step 1: Write failing value-contract and canonicalization tests**

```python
def test_canonical_key_is_idempotent_and_normalizes_label_pairs() -> None:
    canonical = canonical_key(" Sector = Information_Technology ")
    assert canonical == "sector=information technology"
    assert canonical_key(canonical) == canonical
    # Both halves are case-normalized, so a field name spelled two ways
    # cannot split one logical key into two.
    assert canonical_key("Sector=Technology") == canonical_key("sector=technology")


def test_default_validator_rejects_empty_payload_and_negative_rows() -> None:
    assert not default_validator(_row(payload={})).ok
    assert not default_validator(_row(payload={"rows": []}, row_count=-1)).ok
    assert default_validator(_row(payload={"rows": [{"symbol": "AAPL"}]}, row_count=1)).ok
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py -q
```

Expected: collection fails because `openbb_techtrade.snapshot.store` does not exist.

- [ ] **Step 3: Implement the shared value types and helpers**

```python
class SnapshotStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    STALE = "stale"
    FAILED = "failed"


_STATUS_RANK = {
    SnapshotStatus.FAILED: 0,
    SnapshotStatus.STALE: 1,
    SnapshotStatus.PARTIAL: 2,
    SnapshotStatus.OK: 3,
}


def canonical_key(raw: str) -> str:
    # Casefold the whole value — both halves of a `field=label` pair — so
    # `Sector=Technology` and `sector=technology` are one key, not two.
    value = " ".join(raw.replace("_", " ").casefold().split())
    if "=" not in value:
        return value
    field, label = value.split("=", 1)
    return f"{field.strip()}={label.strip()}"
```

Define the Protocol with the exact signatures from the approved design's section 4.4. Export only public contract names from `snapshot/__init__.py`.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 tests. Expected: canonicalization and validator tests pass.

- [ ] **Step 5: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py
git commit -m "feat(techtrade): define snapshot store contract" -m "Refs #1963" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: SQLite stage, validate, promote, and read path

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

**Interfaces:**
- Consumes: Task 1 value types and helpers.
- Produces: `SqliteSnapshotStore`, `_SQLITE_SCHEMA`, transaction-safe `stage()`, `validate()`, `promote()`, `get_live()`, `get_as_of()`, and `list_history()`.

- [ ] **Step 1: Write failing lifecycle tests**

Add tests for:

```python
def test_fresh_store_has_no_live_snapshot(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    assert store.get_live("techtrade.movers", "sector=technology") is None


def test_clean_stage_validate_promote_is_atomic(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(store, status=SnapshotStatus.OK, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.state == SnapshotState.LIVE


def test_unvalidated_or_empty_stage_cannot_promote(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(store, payload={})
    assert not store.promote(*staged)
    assert not store.validate(*staged).ok
    assert store.get_live("techtrade.movers", "sector=technology") is None
```

Also assert `as_of_session` returns as `date` and `created_at` as UTC-aware `datetime`.

- [ ] **Step 2: Verify RED**

Run the lifecycle tests. Expected: import or attribute failure for `SqliteSnapshotStore`.

- [ ] **Step 3: Implement SQLite schema and persistence**

Create `pi_eod_snapshot` with the approved columns, both read indexes, and:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_pi_eod_snapshot_live
ON pi_eod_snapshot(dataset, entity_key)
WHERE state = 'live';
```

Open SQLite with `check_same_thread=False`, `isolation_level=None`, and `sqlite3.Row`. Serialize payloads with deterministic JSON and parse stored values back into `SnapshotRow`.

- [ ] **Step 4: Implement atomic promotion and keep-last-good**

Inside one `_tx()`:

```python
if not candidate.validated:
    logger.warning("snapshot promotion refused: candidate is not validated")
    return False
live = self.get_live(dataset, entity_key)
if live and _STATUS_RANK[candidate.status] < _STATUS_RANK[live.status]:
    logger.warning("snapshot promotion refused: candidate status is worse than LIVE")
    return False
self._conn.execute(... prior live -> superseded ...)
self._conn.execute(... candidate -> live ...)
return True
```

No read method may call a compute/provider function.

- [ ] **Step 5: Add and run invariant tests**

Cover:

- caller validator rejection;
- PARTIAL cannot displace OK;
- newer OK supersedes prior OK while history retains both;
- direct second-LIVE insertion raises `sqlite3.IntegrityError`;
- differently formatted keys resolve the same LIVE row.

Expected: all Task 1-2 tests pass.

- [ ] **Step 6: Reverse-verify load-bearing tests**

Temporarily remove each of the validated check, rank guard, unique index, and read-boundary canonicalization. Confirm its corresponding test fails, then restore production code and rerun green.

- [ ] **Step 7: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py
git commit -m "feat(techtrade): add SQLite snapshot lifecycle" -m "Refs #1963" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Idempotency, restamping, and retention hook

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

**Interfaces:**
- Produces: `should_skip()`, `restamp_live()`, and `prune()`.
- Consumes: Task 2 atomic lifecycle and history reads.

- [ ] **Step 1: Write failing idempotency and retention tests**

```python
def test_matching_input_hash_can_be_restamped_without_recompute(tmp_path) -> None:
    store = _live_store(tmp_path, input_hash="same-input")
    assert store.should_skip("techtrade.movers", "sector=technology", "same-input")
    assert store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 4), "run-2"
    )
    assert store.get_live(...).as_of_session == date(2026, 9, 4)
    assert len(store.list_history(...)) == 2


def test_default_prune_keeps_all_and_bounded_policy_preserves_live(tmp_path) -> None:
    store = _store_with_three_sessions(tmp_path)
    assert store.prune() == 0
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 2
    assert store.get_live(...) is not None
```

- [ ] **Step 2: Verify RED**

Expected: methods are absent or return incorrect results.

- [ ] **Step 3: Implement idempotency and auditable restamping**

`restamp_live()` must insert a new validated row with the same payload/provenance, new session/run IDs, then promote it through the same atomic path. It must not mutate the prior row in place.

- [ ] **Step 4: Implement retention**

Default `RetentionPolicy()` returns zero. A bounded policy deletes only non-LIVE rows outside the newest N distinct sessions for each key.

- [ ] **Step 5: Verify and reverse-verify**

Run all snapshot tests. Then temporarily make restamp mutate the old row and confirm the history assertion fails; restore and rerun green.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py
git commit -m "feat(techtrade): add snapshot restamp and retention" -m "Refs #1963" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: MySQL backend parity

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_mysql_snapshot_store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`

**Interfaces:**
- Consumes: Task 1 public types and Task 2-3 behavioral contract.
- Produces: `MysqlSnapshotStore` with Protocol parity and `_make_mysql_store()`.

- [ ] **Step 1: Write failing MySQL contract tests**

Use a realistic connection/cursor fake matching the `mysql-connector` pool API. Assert:

- DDL uses native `DATE` and `DATETIME(6)`;
- generated `live_key` plus unique key enforces the single-LIVE design;
- all user values use `%s` bindings rather than SQL interpolation;
- `stage`, `validate`, `promote`, reads, restamp, and prune use commit/rollback correctly;
- returned rows normalize to the same `SnapshotRow` types as SQLite.

- [ ] **Step 2: Verify RED**

Expected: `openbb_techtrade.snapshot.mysql_store` is missing.

- [ ] **Step 3: Implement MySQL schema and pool acquisition**

Mirror `MysqlPaperEngine`:

```python
from openbb_fmp_cached.utils.database import get_connection_pool

class MysqlSnapshotStore:
    def __init__(self) -> None:
        self._pool = get_connection_pool()
        self._ensure_schema()
```

Use a generated nullable `live_key`:

```sql
live_key VARCHAR(512)
  GENERATED ALWAYS AS (
    IF(state='live', CONCAT(dataset, CHAR(31), entity_key), NULL)
  ) STORED,
UNIQUE KEY ux_pi_eod_snapshot_live (live_key)
```

- [ ] **Step 4: Implement Protocol parity**

Keep SQL dialect differences private. Reuse shared row conversion, validation, ranking, and canonicalization logic rather than duplicating policy.

The `live_key` column and its `UNIQUE KEY` are **verified, not assumed**
(PR #2062 review). `CREATE TABLE IF NOT EXISTS` is a no-op against a
pre-existing table of any shape, and MySQL declares the unique key
*inside* that statement — so a table restored from a columns-only dump
gets no guard, and every later promotion silently leaves a second LIVE
row. `_verify_schema` therefore re-reads
`information_schema.COLUMNS.GENERATION_EXPRESSION` and
`information_schema.STATISTICS` and refuses when `live_key` is missing,
is an ordinary (non-generated) column, or has no UNIQUE index over
exactly `(live_key)`. The check runs before the version stamp is written,
so a refused table is never adopted and stamped, and it runs
unconditionally — a current stamp proves who wrote the table, never that
its keys survived.

The symmetric SQLite check lives in `_check_sqlite_live_guard` and looks
for a *partial* unique index instead: SQLite has partial indexes, so it
needs no `live_key`, and requiring one there would refuse every correct
SQLite database. `live_key` is deliberately absent from the shared
`_EXPECTED_COLUMNS`.

- [ ] **Step 5: Verify tests**

Run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py -q
```

Expected: all tests pass without a live MySQL server.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit/test_mysql_snapshot_store.py
git commit -m "feat(techtrade): add MySQL snapshot backend" -m "Refs #1963" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Backend factory and acceptance verification

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

**Interfaces:**
- Produces: `get_default_snapshot_store(db_path: Path | str | None = None) -> SnapshotStore`.
- Consumes: both concrete backends.

- [ ] **Step 1: Write failing selector/fallback tests**

```python
def test_selector_uses_sqlite_when_requested(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "sqlite")
    store = get_default_snapshot_store(tmp_path / "snapshot.db")
    assert isinstance(store, SqliteSnapshotStore)


def test_mysql_failure_warns_and_falls_back(monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    monkeypatch.setenv("PI_SNAPSHOT_DB", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.snapshot.store"):
        store = get_default_snapshot_store()
    assert isinstance(store, SqliteSnapshotStore)
    assert "falling back to SQLite" in caplog.text
```

- [ ] **Step 2: Verify RED**

Expected: selector is absent or fallback warning assertion fails.

- [ ] **Step 3: Implement the factory**

Default to MySQL. Catch construction failures only around MySQL creation, log the exception type/message, and return SQLite at `PI_SNAPSHOT_DB` or `~/.portfolio_intel/snapshot.db`. Do not swallow SQLite construction errors.

- [ ] **Step 4: Run the complete acceptance suite**

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py -q
.\.venv_portfolio\Scripts\python.exe -m black --check openbb_platform\extensions\techtrade\openbb_techtrade\snapshot openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py
.\.venv_portfolio\Scripts\python.exe -m ruff check openbb_platform\extensions\techtrade\openbb_techtrade\snapshot openbb_platform\extensions\techtrade\tests\unit\test_snapshot_store.py openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py
```

Expected: all tests and checks pass.

- [ ] **Step 5: Exercise the real SQLite path**

Create a temporary SQLite store, stage/validate/promote one synthetic non-personal row, close and reopen the store, and verify `get_live()` returns the persisted row with the same date, UTC timestamp, payload, and provenance.

- [ ] **Step 6: Commit**

```powershell
git add openbb_platform/extensions/techtrade/openbb_techtrade/snapshot openbb_platform/extensions/techtrade/tests/unit
git commit -m "feat(techtrade): select snapshot storage backend" -m "Closes #1963" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Final review and PR gate

- [ ] Run the targeted tests and changed-file Black, Ruff, mypy, and pylint checks.
- [ ] Run a security review focused on SQL parameterization, shared-store PII boundaries, and unsafe fallback behavior.
- [ ] Run an independent code review and fix every high-confidence finding.
- [ ] Push `feat/pi-eod-snapshot-store-gh-1963`.
- [ ] Open a PR into `portfolio` inside `prajoria/OpenBB` with `Closes #1963.` on its own line.
- [ ] Continue review/fix iterations until checks pass and there are zero unresolved active threads.
