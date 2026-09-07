# OpenBB Jobs Service Design

## Status

Approved for implementation by the unattended-session instruction to choose the
pragmatic recommended option.

This design supersedes the "external cron/Task Scheduler only" constraint in
#1934 (Async scan and ScanSnapshotStore persistence). It keeps the snapshot
requirements while moving scheduling, execution history, retries, and manual
triggers into an OpenBB service.

## Problem

OpenBB currently has long-running maintenance and analytics operations, but no
application-level job abstraction:

- `openbb_techtrade.engine.scan.scan_segments()` is synchronous and can take
  tens of minutes for all sectors.
- the Morning Scan widgets still return static rows because an HTTP request
  cannot safely perform that scan;
- position-history and ETF-holdings cache warmers are standalone scripts;
- scheduling is delegated to cron or Windows Task Scheduler, so the API cannot
  report job health, run history, progress, or failures;
- direct HTTP subprocess launching would not provide durable ownership,
  retries, deduplication, or recovery.

## Goals

1. Add a reusable `JobService` to `openbb_core.app.service`.
2. Run scheduling and execution in a dedicated `openbb-jobs` worker process.
3. Persist schedules and runs so API and worker restarts do not lose state.
4. Discover typed job definitions from installed OpenBB extensions.
5. Expose authenticated list, trigger, cancel, status, and health endpoints.
6. Register the TechTrade scan and both existing cache warmers as jobs.
7. Persist TechTrade scan results and make Morning Scan widget reads
   compute-free.
8. Preserve the existing Python and PowerShell entry points as compatibility
   wrappers.
9. Work on Windows and Linux without Redis, RabbitMQ, or a second service
   dependency.

## Non-goals

- distributed execution across multiple hosts;
- arbitrary user-provided Python imports, shell commands, or executable paths;
- real-time market-data streaming;
- replacing provider caches;
- a general workflow DAG engine;
- live interruption of a running synchronous provider call.

## Considered approaches

### A. Keep external schedulers and add only scan persistence

This is the smallest change, but it leaves no unified status, retries,
deduplication, or API trigger semantics. It does not address the core request.

### B. Embed APScheduler in the API

APScheduler handles cron and time zones, but an embedded scheduler can execute
the same occurrence in every Uvicorn worker. Its persistent store would also
become the application's run-history contract. Long scans would share failure
and shutdown fate with HTTP serving.

### C. Dedicated OpenBB jobs worker with an application-owned store

This is the selected approach. The API is a control plane only. A separate
worker evaluates schedules, claims durable runs, executes allowlisted handlers,
and records outcomes. The first release uses a deliberately small daily and
interval schedule model instead of importing a full distributed task system.

## Architecture

### Core domain

`openbb_core.app.jobs` owns:

- immutable `JobDefinition` objects supplied by installed extensions;
- Pydantic parameter models and JSON-safe result summaries;
- `DailySchedule` and `IntervalSchedule`;
- `JobRun` state and transition rules;
- the `JobHandler` and `JobProvider` protocols;
- a `JobRegistry` keyed by stable job name.

Handlers are never persisted. The database stores only the job name, handler
version, validated parameters, and policy snapshot. A missing or incompatible
handler fails visibly.

### Extension discovery

Add `openbb_job_extension` to `OpenBBGroups`. Each entry point loads a callable
returning `list[JobDefinition]`.

Initial providers:

- `openbb_techtrade.jobs:get_job_definitions`
- `portfolio_utils.jobs:get_job_definitions`

Duplicate names or invalid definitions fail service startup instead of silently
overriding another extension.

### Job service

`JobService`, following the existing OpenBB service namespace, coordinates:

- extension discovery and registry construction;
- durable schedule reconciliation;
- manual enqueue with optional idempotency key;
- due-schedule enqueue;
- atomic next-run claim;
- state transitions, retry scheduling, and cancellation;
- run and health queries.

The API creates `JobService` instances but never calls handlers. The worker is
the only executor.

### Persistence

The initial `SqliteJobStore` is single-host and durable. It defaults to
`~/.openbb_platform/jobs.db` and is overridden by `OPENBB_JOBS_DB`.

SQLite is appropriate for the current one-machine deployment and permits the
API and dedicated worker to share state without another dependency. WAL,
foreign keys, a busy timeout, short transactions, and `BEGIN IMMEDIATE` claims
provide safe multi-process access on one host. A `JobStore` protocol prevents
the service or handlers from depending on SQLite and leaves room for a MySQL
adapter when multi-host execution is required.

Tables:

`job_schedule`

- `job_name` primary key;
- `handler_version`;
- `enabled`;
- `schedule_kind` and `schedule_json`;
- `timezone`;
- `default_params_json`;
- `max_attempts`, `retry_backoff_seconds`, `overlap_policy`;
- `next_run_at`, `last_scheduled_at`;
- `updated_at`.

`job_run`

- UUID `run_id` primary key;
- `job_name`, `handler_version`;
- `source` (`schedule`, `manual`, `retry`);
- `status` (`queued`, `running`, `succeeded`,
  `succeeded_with_warnings`, `failed`, `cancelled`);
- immutable `params_json`;
- `scheduled_for`, `available_at`;
- `attempt`, `max_attempts`;
- `dedupe_key` unique when present;
- `worker_id`, `heartbeat_at`;
- timestamps and duration;
- bounded result, warning, error type, and sanitized error message JSON.

`job_worker`

- `worker_id` primary key;
- process metadata;
- start and heartbeat timestamps.

The service guarantees at-least-once execution. Scheduled occurrences use
`schedule:<job_name>:<UTC instant>` dedupe keys. Handlers must therefore be
idempotent. A worker crash changes an abandoned `running` run back to `queued`
after its lease timeout.

### Worker

`openbb-jobs worker` runs a polling loop:

1. synchronize installed definitions;
2. heartbeat its worker record;
3. recover expired runs;
4. enqueue due occurrences and advance their schedules transactionally;
5. atomically claim one runnable job;
6. resolve its allowlisted handler from the registry;
7. execute it in the dedicated worker process;
8. record success, partial success, retry, or terminal failure.

`openbb-jobs worker --once` performs one scheduling and execution drain and
exits, which is useful for tests and break-glass operation. Production uses the
long-running mode. Shutdown stops claiming new work and completes the current
handler.

### API

The core REST API includes an authenticated `/jobs` router when
`OPENBB_JOBS_ENABLED=true`:

- `GET /jobs/definitions`
- `GET /jobs/runs`
- `GET /jobs/runs/{run_id}`
- `POST /jobs/{job_name}/trigger` returning `202`
- `POST /jobs/runs/{run_id}/cancel`
- `GET /jobs/health`

Only registered job names and Pydantic-validated parameters are accepted.
Arguments, results, and errors are size bounded. Credentials are read by the
handler from the normal OpenBB environment/settings path and never persisted.

### Initial jobs

| Job | Default schedule | Dependency | Result |
| --- | --- | --- | --- |
| `portfolio.position_history` | weekdays 01:00 local | none | symbol and row counts |
| `portfolio.etf_holdings` | weekdays 02:00 local | none | populated/empty/error counts |
| `techtrade.daily_scan` | weekdays 03:00 local | latest successful ETF warm | snapshot IDs and segment counts |
| `techtrade.prune_snapshots` | daily 04:00 local | none | deleted snapshot count |

Schedules are disabled unless `OPENBB_JOBS_ENABLED=true`. Individual defaults
can be overridden in the persisted schedule table without changing code.

### TechTrade snapshot flow

The TechTrade package adds a `ScanSnapshotStore` protocol and SQLite
implementation. The initial store defaults to
`~/.openbb_platform/techtrade_scan.db` and supports:

- `write_snapshot`;
- `read_latest`;
- `read_by_id`;
- `list_snapshots`;
- `prune_snapshots`.

Each segment is an append-only snapshot. `computed_at` is UTC and
`as_of_session` is the market session represented by the data. Writes complete
in one transaction. Readers continue to see the previous committed snapshot if
a later run fails.

`run_scan()` executes the existing `scan_segments()` function and writes
widget-ready rows. A failed segment is recorded as a job warning and never
replaces its last good snapshot. Retention keeps the latest 10 snapshots per
job kind and segment by default.

The Morning Scan endpoints read snapshots only. If none exists, they return an
empty result with explicit freshness metadata; they never execute market-data
work. `POST /tt/scan/trigger` becomes a compatibility alias that enqueues
`techtrade.daily_scan`.

### Cache warmer adapters

The two script modules expose importable functions returning structured
results. Their existing CLIs retain compatible arguments and output.

- per-symbol/per-ETF failures become warnings and produce
  `succeeded_with_warnings`;
- configuration or connection failures before useful work produce `failed`;
- the PowerShell wrappers enqueue the registered job and optionally wait,
  rather than executing provider logic directly.

## Error handling

- Invalid job names or parameters return a 4xx response.
- Queue/store failures are surfaced as service errors; the API does not return
  success-shaped fallbacks.
- Only explicitly retryable handler errors are retried.
- Retry delay is capped exponential backoff.
- `overlap_policy=forbid` prevents another active run of the same definition.
- Queued jobs can be cancelled immediately. Running jobs expose
  `cancel_requested`; handlers check between symbols or segments.
- Full tracebacks stay in worker logs. Stored/API errors contain type and a
  bounded sanitized message.

## Compatibility and rollout

1. Ship the framework disabled by default.
2. Run `openbb-jobs worker --once` with dry-run job parameters.
3. Enable the worker with schedules disabled and manually trigger each job.
4. Enable the three daily schedules.
5. Replace legacy scheduled tasks with one worker-at-startup registration.
6. Keep the legacy scripts for one release as queueing wrappers.

## Testing

- schedule calculations across weekdays, time zones, and DST boundaries;
- SQLite schema creation, persistence, atomic claims, deduplication, retries,
  cancellation, and stale-run recovery;
- registry discovery, duplicate rejection, and parameter validation;
- authenticated API contracts and `202` trigger behavior;
- worker once-mode and graceful shutdown;
- cache adapters using injected provider/database seams;
- snapshot round trips, retention, and last-good behavior;
- TechTrade job integration using recorded realistic payloads;
- Morning Scan empty and populated contracts with measured read latency;
- a subprocess smoke test proving API enqueue -> worker execute -> persisted
  success.

## Success criteria

- no long-running scan or cache work runs in an API process;
- a scheduled occurrence is enqueued at most once;
- a run and its outcome survive API and worker restarts;
- all three operational jobs are visible and manually triggerable through the
  API and CLI;
- Morning Scan endpoints use persisted snapshots and return within 500 ms;
- existing direct CLIs continue to work;
- targeted unit, integration, lint, and real-path verification pass.

