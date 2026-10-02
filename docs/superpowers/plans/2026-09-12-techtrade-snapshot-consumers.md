# TechTrade Snapshot Consumers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver PII-free, validated post-close snapshots and compute-free
Portfolio Intelligence reads for every data-bearing TechTrade widget.

**Architecture:** Extend `openbb_techtrade.snapshot` with dataset contracts and
compute adapters. Make the old `openbb_techtrade.snapshots` API a compatibility
facade over the generic store, and make Portfolio Intel read only generic LIVE
pointers. One post-close job refreshes selected datasets through the existing
atomic orchestration.

**Tech Stack:** Python 3.10-3.13, Pydantic, SQLite/MySQL snapshot protocols,
exchange-calendars, FastAPI, OpenBB jobs, pytest.

## Global Constraints

- `openbb_techtrade.snapshot` is the only persistence source of truth.
- All nine datasets are `pii_scoped=False`; no credentials or account data may
  enter payloads, diagnostics, GitHub artifacts, or harness output.
- Every write follows stage → dataset validation → atomic publish.
- Any failed key keeps all prior LIVE pointers and records a sanitized targeted
  error.
- Widget requests are compute-free, loudly empty when missing, and complete in
  under 500 ms.
- Every response shows exchange/session freshness and
  `EOD planning snapshot — not a live/intraday quote`.
- `validate`, `tune`, and `audit` are explicitly stamped
  `in-sample · survivorship-uncorrected` unless exact as-of membership exists.
- All agent dispatches use `gpt-5.6-sol`; this plan is executed inline.

---

### Task 1: Dataset registry and validation policy

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/datasets.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/registry.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/refresh.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/__init__.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_datasets.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_refresh.py`

**Interfaces:**
- Produces `TECHTRADE_DATASETS`, `techtrade_entity_key(segment)`,
  `validate_techtrade_snapshot(row, previous=None)`, and
  `DatasetDefinition.validator`.
- `SnapshotRefreshOrchestrator` passes the registered validator and current LIVE
  row to `store.validate`.

- [ ] **Step 1: Write failing registry and validator tests**

```python
def test_all_consumer_datasets_are_public_and_versioned():
    for name in TECHTRADE_DATASETS:
        definition = DEFAULT_DATASET_REGISTRY.require(name)
        assert definition.pii_scoped is False
        assert definition.payload_schema_version == "1"

def test_validator_rejects_all_null_rows_and_non_positive_prices():
    assert not validate_techtrade_snapshot(row({"rows": [{"close": None}]})).ok
    assert not validate_techtrade_snapshot(row({"rows": [{"close": 0}]})).ok

def test_orchestrator_uses_definition_validator(tmp_path):
    job = orchestrator_with_invalid_adapter(tmp_path).run("techtrade.movers")
    assert job.state is SnapshotJobState.FAILED
```

- [ ] **Step 2: Run RED**

Run:

```powershell
..\..\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\techtrade\tests\unit\test_snapshot_datasets.py openbb_platform\extensions\techtrade\tests\unit\test_snapshot_refresh.py -q
```

Expected: collection/import failures for the absent contracts and a failing
orchestrator validator assertion.

- [ ] **Step 3: Implement the shared payload gate**

Create immutable definitions for:

```python
TECHTRADE_DATASETS = (
    "techtrade.movers", "techtrade.scan", "techtrade.signals",
    "techtrade.plan", "techtrade.orders", "techtrade.simulate",
    "techtrade.validate", "techtrade.tune", "techtrade.audit",
)
```

The gate requires `rows`, `segment`, `as_of_session`, and
`exchange_calendar`; checks ISO dates, monotonic row dates, non-positive
price-like fields, all-null columns, and a default 70% previous-row floor when
the previous count is at least five.

- [ ] **Step 4: Wire validation through orchestration**

Extend `DatasetDefinition` with a validator callable. In `run()`, obtain
`previous = store.get_live(...)` and call:

```python
verdict = store.validate(
    definition.name,
    raw_key,
    as_of_session,
    job_run_id,
    lambda row: definition.validator(row, previous),
)
```

Keep the baseline validator for definitions without a custom callable.

- [ ] **Step 5: Run GREEN and commit**

Run the Task 1 command, then commit with `Refs #1968` and `Refs #1969`.

---

### Task 2: Movers adapter, event-risk contract, and atomic publication

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/adapters.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/refresh.py`
- Modify: `openbb_platform/extensions/techtrade/pyproject.toml`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_adapters.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_refresh.py`

**Interfaces:**
- Produces `MarketEvent`, `EventRisk`, `MoversSnapshotAdapter`,
  `get_snapshot_adapters()`, and the `openbb_snapshot_dataset` plugin.
- Movers keys are exactly `segment=<GICS>` and compute calls
  `list_movers(segment=..., as_of=..., top_n=...)` once for each key.

- [ ] **Step 1: Write failing mover and event tests**

```python
def test_movers_computes_one_public_segment_payload():
    result = adapter.compute(
        "segment=Information Technology", date(2026, 9, 11)
    )
    assert calls == [("Information Technology", date(2026, 9, 11))]
    assert result.payload["exchange_calendar"] == "XNYS"
    assert result.payload["rows"][0]["close"] > 0

def test_earnings_and_inactive_symbols_change_refresh_inputs():
    result = adapter_with_events.compute(KEY, SESSION)
    assert result.payload["earnings_symbols"] == ["NVDA"]
    assert result.payload["excluded_symbols"] == ["OLD", "HALT"]
    assert all(row["symbol"] not in {"OLD", "HALT"} for row in result.payload["rows"])
```

- [ ] **Step 2: Run RED**

Run `pytest ...\test_snapshot_adapters.py ...\test_snapshot_refresh.py -q`;
expect absent-adapter failures.

- [ ] **Step 3: Implement safe model serialization and mover compute**

Normalize Pydantic models with `model_dump(mode="json")`, mappings by copying,
and reject unsupported values. Event providers return public symbol/status
metadata only. Include events in `ComputedSnapshot.inputs`, filter delisted and
halted symbols, and never persist exception messages.

- [ ] **Step 4: Prove the four #1968 paths**

Add real `SqliteSnapshotStore` tests for success, partial failure, all-null and
row-count rejection, and cold-start `None`. Assert partial runs do not move any
pointer and `retry_entity_keys()` contains only failed keys.

- [ ] **Step 5: Run GREEN and commit**

Run both adapter and refresh suites, then commit with `Refs #1968`.

---

### Task 3: Fan-out adapters and post-close jobs

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/adapters.py`
- Rewrite: `openbb_platform/extensions/techtrade/openbb_techtrade/jobs.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_jobs.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_adapters.py`

**Interfaces:**
- Produces one adapter per `TECHTRADE_DATASETS`, `EodSnapshotParams`, and
  `techtrade.eod_snapshots`.
- The job parameter `datasets` defaults to all nine dataset names and invokes
  one `SnapshotRefreshOrchestrator.run(name)` per name.

- [ ] **Step 1: Write failing fan-out and schedule tests**

```python
@pytest.mark.parametrize("dataset", TECHTRADE_DATASETS)
def test_adapter_registry_covers_every_dataset(dataset):
    assert dataset in get_snapshot_adapters()

def test_eod_job_runs_after_close_and_has_no_legacy_store():
    definition = definitions["techtrade.eod_snapshots"]
    assert definition.schedule.hour >= 17
    assert "SqliteScanSnapshotStore" not in inspect.getsource(jobs)
```

- [ ] **Step 2: Run RED**

Run adapter and job test files; expect missing fan-out adapters and the legacy
store assertion to fail.

- [ ] **Step 3: Implement adapter fan-out**

Use existing TechTrade engines and injected seams to build widget-shaped rows.
`orders` and `simulate` materialize plan artifacts. `validate`, `tune`, and
`audit` include:

```python
"survivorship": "in-sample · survivorship-uncorrected"
```

unless the exact membership provider returns the requested session and calendar.

- [ ] **Step 4: Replace legacy scheduled writes**

Register `techtrade.eod_snapshots` at 18:00 `America/New_York`, plus prune.
Construct one generic store/router/orchestrator, run selected datasets, close
once, and return bounded per-dataset states and warnings. The endpoint trigger
enqueues this job and performs no compute.

- [ ] **Step 5: Run GREEN and commit**

Run adapter, refresh, and jobs suites, then commit with `Refs #1969`,
`Refs #1942`, `Refs #1943`, `Refs #1944`, and `Refs #1945`.

---

### Task 4: Eliminate the competing legacy store

**Files:**
- Rewrite: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshots/sqlite.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshots/store.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_scan_snapshot_store.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_scan_snapshot_plan.py`

**Interfaces:**
- `SqliteScanSnapshotStore` remains import-compatible but wraps
  `SqliteSnapshotStore`.
- Legacy `kind` maps to `techtrade.scan`; `segment` maps through
  `techtrade_entity_key`; no `scan_snapshot` table exists.

- [ ] **Step 1: Write a failing compatibility test**

```python
def test_legacy_facade_uses_generic_tables_only(tmp_path):
    store = SqliteScanSnapshotStore(tmp_path / "snapshots.db")
    store.write_snapshot(snapshot)
    tables = sqlite_tables(tmp_path / "snapshots.db")
    assert "pi_eod_snapshot" in tables
    assert "scan_snapshot" not in tables
    assert store.read_latest(kind="daily_scan", segment="Technology") == snapshot
```

- [ ] **Step 2: Run RED**

Run the two legacy snapshot suites; expect `scan_snapshot` to exist.

- [ ] **Step 3: Implement the facade**

Translate `ScanSnapshot` to a generic envelope, stage with the snapshot id as
job id, run the registered validator, promote, and reconstruct the legacy DTO
on reads. Implement history and pruning through the generic protocol.

- [ ] **Step 4: Run GREEN and commit**

Run all TechTrade snapshot tests, then commit with `Refs #1968` and
`Refs #1942`.

---

### Task 5: Compute-free Portfolio Intel widgets

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py`
- Create: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tt_snapshot_consumers.py`
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tt_morning_scan.py`
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tt_position_workbench.py`
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tt_t13_3_through_7.py`

**Interfaces:**
- Produces `_get_snapshot_store()`, `_read_snapshot_rows(dataset, ...)`,
  `_snapshot_display(...)`, and compute-free implementations for all named
  `tt_*` endpoints.

- [ ] **Step 1: Write failing endpoint tests**

Seed a real generic SQLite store, patch only `_get_snapshot_store`, and assert
every endpoint returns seeded content, correct badge/disclaimer, cold loud-empty,
stale color, survivorship warning, and completes under 500 ms. Patch all engine
compute symbols to raise and prove no endpoint calls them.

- [ ] **Step 2: Run RED**

Run the three existing widget suites plus
`test_tt_snapshot_consumers.py`; expect legacy-store and stub-content failures.

- [ ] **Step 3: Implement bounded generic reads**

Read explicit `segment=<GICS>` LIVE keys only. Render chart/table responses
without changing manifest contracts. Render markdown cards with the display
header. Return deterministic loud-empty rows/cards containing
`No EOD snapshot available — run the post-close snapshot job`.

- [ ] **Step 4: Remove replaced stub markers**

Remove only the `gh-1696`, `gh-1697`, `gh-1698`, and `gh-1699` stub markers
whose endpoint bodies are now generic snapshot reads.

- [ ] **Step 5: Run GREEN and commit**

Run all TechTrade widget tests and commit with references to #1942-#1945 and
#1969.

---

### Task 6: Exchange-aware semantics and final verification

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/semantics.py`
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_semantics.py`
- Modify: `docs/operations/eod-snapshot-refresh.md`
- Create: `.dev-cycle/verify-phase6.log` (evidence only; do not commit)

**Interfaces:**
- `build_eod_display(..., calendar_name=payload["exchange_calendar"])` is the
  sole badge/freshness calculation.
- Resolves #2086 (exchange-calendar-aware snapshot `as_of` badges).

- [ ] **Step 1: Write failing multi-exchange tests**

```python
def test_xlon_display_uses_xlon_completed_session():
    display = build_eod_display(
        date(2026, 9, 11), NOW, calendar_name="XLON"
    )
    assert display.calendar_name == "XLON"
    assert "XLON" in display.label
```

Also assert an invalid calendar fails loudly.

- [ ] **Step 2: Run RED, implement, and run GREEN**

Add `calendar_name` to `EodDisplay`, validate through
`exchange_calendars.get_calendar`, and name the calendar in the label. Run
snapshot semantics and consumer tests.

- [ ] **Step 3: Run broad diagnostics and regressions**

Run Ruff on changed Python files, all TechTrade unit tests, all Portfolio Intel
unit tests, and the affected job tests with the portfolio virtual environment.

- [ ] **Step 4: Run the real SQLite Phase 6 harness**

Create an outside-repository database in a disposable sibling of the worktree,
run all acceptance paths with synthetic public rows and injected compute
functions, reopen the database, invoke the actual widget helpers, assert
sub-500 ms reads, redirect sanitized stdout to
`.dev-cycle/verify-phase6.log`, and delete the disposable sibling.

- [ ] **Step 5: Review, converge, and ship**

Run simplification, code, and security reviews using `gpt-5.6-sol`; resolve
every finding and re-run affected verification. Push once, open one PR to
`portfolio`, add one exact `Closes #NN` line for each of #1968, #1969,
#1942, #1943, #1944, #1945, and #2086, converge review feedback, merge, verify
all seven issues are closed and Project #4 items are Done, then remove the local
branch and worktree.
