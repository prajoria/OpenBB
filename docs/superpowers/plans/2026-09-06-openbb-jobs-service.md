# OpenBB Jobs Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable OpenBB `JobService` and dedicated worker that schedules, runs, and reports TechTrade scans and portfolio cache warmers.

**Architecture:** Generic job models, registry, schedules, and a SQLite store live in `openbb_core`; extensions register allowlisted typed handlers through `openbb_job_extension`. The REST API is a control plane only, while `openbb-jobs worker` owns durable scheduling and execution. TechTrade snapshots remain a TechTrade concern and are read by widgets without synchronous computation.

**Tech Stack:** Python 3.10+, Pydantic 2, FastAPI, stdlib SQLite/WAL, `importlib_metadata` entry points, pytest.

## Global Constraints

- Production execution occurs only in the dedicated worker process.
- The initial queue is single-host SQLite at `~/.openbb_platform/jobs.db`.
- No Celery, Redis, RabbitMQ, APScheduler, arbitrary imports, or shell-command jobs.
- Persist UTC timestamps; evaluate daily schedules with `zoneinfo`.
- The API and persistence layer never store credentials.
- Existing direct Python and PowerShell entry points remain compatible.
- Use the repository `.venv_portfolio` environment for validation.

---

### Task 1: Core job domain and schedule calculations

**Files:**
- Create: `openbb_platform/core/openbb_core/app/jobs/models.py`
- Create: `openbb_platform/core/openbb_core/app/jobs/schedules.py`
- Create: `openbb_platform/core/openbb_core/app/jobs/registry.py`
- Create: `openbb_platform/core/openbb_core/app/jobs/__init__.py`
- Test: `openbb_platform/core/tests/app/jobs/test_models.py`
- Test: `openbb_platform/core/tests/app/jobs/test_schedules.py`
- Test: `openbb_platform/core/tests/app/jobs/test_registry.py`

**Interfaces:**
- Produces: `JobDefinition`, `JobRun`, `JobResult`, `DailySchedule`,
  `IntervalSchedule`, `JobRegistry`, and `JobHandler`.

- [ ] Write failing model tests for valid state values, bounded JSON payloads,
  and immutable registered definitions.
- [ ] Write failing schedule tests for weekdays, UTC conversion, DST gaps,
  intervals, and strict "next after" behavior.
- [ ] Write failing registry tests for discovery, duplicate names, invalid
  definitions, and Pydantic parameter validation.
- [ ] Implement:

```python
class JobDefinition(BaseModel):
    name: str
    version: int = 1
    description: str
    params_model: type[BaseModel]
    handler: Callable[[JobContext, BaseModel], JobResult]
    schedule: DailySchedule | IntervalSchedule | None = None
    max_attempts: int = 1
    retry_backoff_seconds: int = 60
    overlap_policy: Literal["forbid", "allow"] = "forbid"
```

- [ ] Run:

```powershell
..\OpenBB\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\core\tests\app\jobs -q
```

Expected: all Task 1 tests pass.

- [ ] Commit proposal: `feat(jobs): add typed job domain and schedules (#1934)`

### Task 2: Durable SQLite job store and service

**Files:**
- Create: `openbb_platform/core/openbb_core/app/jobs/store.py`
- Create: `openbb_platform/core/openbb_core/app/jobs/sqlite_store.py`
- Create: `openbb_platform/core/openbb_core/app/service/job_service.py`
- Modify: `openbb_platform/core/openbb_core/app/constants.py`
- Test: `openbb_platform/core/tests/app/jobs/test_sqlite_store.py`
- Test: `openbb_platform/core/tests/app/service/test_job_service.py`

**Interfaces:**
- Consumes: Task 1 models and registry.
- Produces: `JobStore`, `SqliteJobStore`, and `JobService`.

- [ ] Write failing repository contract tests for schema idempotency,
  persistence across reopen, manual idempotency, schedule deduplication,
  competing atomic claims, overlap prevention, retries, queued cancellation,
  and abandoned-run recovery.
- [ ] Write failing service tests for definition reconciliation, enqueue,
  dispatch, claim, completion, failure, retry, and health.
- [ ] Implement `JobStore` as a protocol and `SqliteJobStore` using WAL,
  foreign keys, a busy timeout, and short explicit transactions.
- [ ] Implement:

```python
class JobService:
    def list_definitions(self) -> list[JobDefinitionView]: ...
    def enqueue(self, job_name: str, params: dict[str, object],
                idempotency_key: str | None = None) -> JobRun: ...
    def enqueue_due(self, now: datetime | None = None) -> list[JobRun]: ...
    def claim_next(self, worker_id: str,
                   now: datetime | None = None) -> JobRun | None: ...
    def complete(self, run_id: str, result: JobResult) -> JobRun: ...
    def fail(self, run_id: str, error: Exception) -> JobRun: ...
    def cancel(self, run_id: str) -> JobRun: ...
    def health(self) -> JobHealth: ...
```

- [ ] Run the Task 2 tests and the existing service tests.
- [ ] Commit proposal: `feat(jobs): add durable job service (#1934)`

### Task 3: Extension discovery, worker CLI, and API control plane

**Files:**
- Modify: `openbb_platform/core/openbb_core/app/extension_loader.py`
- Create: `openbb_platform/core/openbb_core/app/jobs/worker.py`
- Create: `openbb_platform/core/openbb_core/api/dependency/jobs.py`
- Create: `openbb_platform/core/openbb_core/api/router/jobs.py`
- Modify: `openbb_platform/core/openbb_core/api/rest_api.py`
- Modify: `openbb_platform/core/openbb_core/env.py`
- Modify: `openbb_platform/core/pyproject.toml`
- Test: `openbb_platform/core/tests/app/jobs/test_worker.py`
- Test: `openbb_platform/core/tests/api/test_jobs.py`

**Interfaces:**
- Consumes: `JobService` and `openbb_job_extension` providers.
- Produces: `openbb-jobs` CLI and authenticated `/jobs` endpoints.

- [ ] Write failing extension-loader tests for sorted job entry points and
  duplicate-name failure.
- [ ] Write failing worker tests for once mode, retry, heartbeat, recovery,
  and clean shutdown.
- [ ] Write failing API tests for list, `202` trigger, run lookup, queued
  cancellation, authentication, unknown jobs, and invalid parameters.
- [ ] Add `OpenBBGroups.job = "openbb_job_extension"` and load providers
  without importing optional extension modules from core.
- [ ] Implement worker commands:

```text
openbb-jobs list
openbb-jobs trigger <job-name> [--params-json JSON] [--wait]
openbb-jobs worker [--once] [--poll-seconds N]
```

- [ ] Include the jobs router only when `OPENBB_JOBS_ENABLED=true`.
- [ ] Run Task 3 tests and import `openbb_core.api.rest_api`.
- [ ] Commit proposal: `feat(jobs): expose worker and control API (#1934)`

### Task 4: TechTrade snapshot persistence and job adapter

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshots/models.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshots/store.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshots/sqlite.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshots/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan_runner.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/jobs.py`
- Modify: `openbb_platform/extensions/techtrade/pyproject.toml`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_scan_snapshot_store.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_scan_runner.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_jobs.py`

**Interfaces:**
- Consumes: `scan_segments()` and the core job provider protocol.
- Produces: `ScanSnapshotStore`, `SqliteScanSnapshotStore`, `run_scan()`, and
  TechTrade job definitions.

- [ ] Write failing snapshot contract tests for round trips, latest-by-segment,
  list, retention, and last-good behavior after a failed write.
- [ ] Write failing runner tests using injected scan functions and recorded
  realistic payload shapes.
- [ ] Implement an append-only SQLite store and:

```python
def run_scan(
    *,
    segments: list[str] | None = None,
    top_n: int = 3,
    preset: str = "trend_follow",
    as_of: date | str | None = None,
    store: ScanSnapshotStore | None = None,
    scan_fn: Callable[..., list[TradePlan]] = scan_segments,
) -> ScanRunResult: ...
```

- [ ] Register `techtrade.daily_scan` and
  `techtrade.prune_snapshots` with weekday 03:00 and daily 04:00 defaults.
- [ ] Preserve `python -m openbb_techtrade.engine.scan_runner`.
- [ ] Run all Task 4 tests plus existing `tests/unit/test_scan.py`.
- [ ] Commit proposal: `feat(techtrade): persist scans through jobs service (#1934)`

### Task 5: Portfolio cache-warmer job adapters

**Files:**
- Modify: `openbb_platform/tools/portfolio_utils/portfolio_utils/fetch_position_history.py`
- Modify: `openbb_platform/tools/portfolio_utils/portfolio_utils/refresh_etf_holdings_cache.py`
- Create: `openbb_platform/tools/portfolio_utils/portfolio_utils/jobs.py`
- Modify: `openbb_platform/tools/portfolio_utils/pyproject.toml`
- Test: `openbb_platform/tools/portfolio_utils/tests/test_fetch_position_history.py`
- Modify: `openbb_platform/tools/portfolio_utils/tests/test_refresh_etf_holdings_cache.py`
- Create: `openbb_platform/tools/portfolio_utils/tests/test_jobs.py`

**Interfaces:**
- Consumes: core job definitions and existing fetch/refresh primitives.
- Produces: structured warmer results and portfolio job definitions.

- [ ] Write failing tests for structured success, partial, and configuration
  failure results while preserving legacy CLI exit behavior.
- [ ] Extract:

```python
def run_position_history_warm(...) -> PositionHistoryWarmResult: ...
def run_etf_holdings_warm(...) -> EtfHoldingsWarmResult: ...
```

- [ ] Register `portfolio.position_history` at weekday 01:00 and
  `portfolio.etf_holdings` at weekday 02:00.
- [ ] Keep provider calls injectable and check cancellation between items.
- [ ] Run all portfolio-utils tests.
- [ ] Commit proposal: `feat(portfolio-utils): register cache warming jobs (#1934)`

### Task 6: Replace Morning Scan stubs with snapshot reads

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py`
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/main.py`
- Modify: `openbb_platform/extensions/portfolio_intel/pyproject.toml`
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tt_morning_scan.py`

**Interfaces:**
- Consumes: `ScanSnapshotStore` and `JobService.enqueue`.
- Produces: compute-free Morning Scan endpoints and compatibility trigger.

- [ ] Replace static rows with `read_latest()` results and add explicit
  `computed_at`, `as_of_session`, and `is_stale` metadata.
- [ ] Return loud-empty results when no snapshot exists.
- [ ] Add `POST /tt/scan/trigger` as an authenticated enqueue alias returning
  `202`; never call `scan_segments()` in the request.
- [ ] Measure populated and empty endpoint calls and assert each completes
  below 500 ms in the local contract test.
- [ ] Run the Morning Scan and widget manifest tests.
- [ ] Commit proposal: `feat(portfolio-intel): serve persisted morning scans (#1934)`

### Task 7: Operational wrappers, documentation, and end-to-end verification

**Files:**
- Create: `openbb_platform/tools/portfolio_utils/scheduler/run_openbb_jobs.ps1`
- Modify: `openbb_platform/tools/portfolio_utils/scheduler/run_fetch_position_history.ps1`
- Modify: `openbb_platform/tools/portfolio_utils/scheduler/run_refresh_etf_holdings_cache.ps1`
- Create: `openbb_platform/core/docs/jobs.md`
- Create: `.dev-cycle/verify-phase6.log`

**Interfaces:**
- Consumes: worker CLI and all registered jobs.
- Produces: operator startup instructions and compatibility wrappers.

- [ ] Make legacy wrappers invoke `openbb-jobs trigger <name> --wait` while
  preserving their log locations and exit codes.
- [ ] Document environment variables, Windows startup task, systemd example,
  schedules, retries, recovery, database backup, and migration from old tasks.
- [ ] Run targeted Ruff and pytest commands for all touched packages.
- [ ] Start a temporary jobs database, enqueue a dry-run cache job through
  `JobService`, execute `worker --once`, query the persisted result, and capture
  stdout in `.dev-cycle/verify-phase6.log`.
- [ ] Import the REST API with jobs enabled and verify route registration.
- [ ] Run `git diff --check` and confirm no credentials, PII, local paths, or
  generated artifacts are staged.
- [ ] Commit proposal: `docs(jobs): document worker operations (#1934)`

