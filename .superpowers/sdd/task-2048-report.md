# GitHub Issue #2048 — Tasks 3–5 Implementation Report

## Status

Complete on `feat/windows-service-integration-gh-2048`. Tasks 3–5 were
implemented and committed. Deployment scripts and the operator runbook were
not changed. Existing untracked `.superpowers` artifacts remain untracked.

## Implemented

### Task 3 — health and diagnostics

- Added `IComponentProbe`, `ProbeResult`, bounded-startup/single-request
  steady-state HTTP probes, stale-heartbeat handling, and configured HTTP
  readiness.
- Added `doctor --json` with aggregate status, per-component HTTP results, and
  jobs heartbeat age.
- Extended read-only jobs health with queue depth, current worker heartbeat
  age, and the last successful run for every registered job.
- Health reads only durable metadata and never resolves or invokes handlers.

Files:

- `services/windows/OpenBB.ServiceHost/Health/HttpComponentProbe.cs`
- `services/windows/OpenBB.ServiceHost/Health/JobsHeartbeatProbe.cs`
- `services/windows/OpenBB.ServiceHost/Health/DoctorCommand.cs`
- `services/windows/OpenBB.ServiceHost/Program.cs`
- `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/HealthProbeTests.cs`
- `openbb_platform/core/openbb_core/app/jobs/store.py`
- `openbb_platform/core/openbb_core/app/jobs/sqlite_store.py`
- `openbb_platform/core/tests/api/test_jobs.py`

### Task 4 — exact commands and shutdown

- Added deterministic, secret-free command arrays for the jobs worker,
  Portfolio API, and Portfolio Intelligence UX.
- Added installed-service rejection of `--reload`.
- Closed the jobs-worker stop/claim race while retaining the standalone
  `run_once()` and `run_forever()` interfaces through optional arguments.
- Added a 10-minute jobs-worker host grace period and tests proving an active
  handler can finish while the next queued job remains unclaimed.
- Added lifespan-owned background task cancellation and draining.

Files:

- `services/windows/OpenBB.ServiceHost/Processes/OpenBBComponents.cs`
- `services/windows/OpenBB.ServiceHost/Configuration/ServiceHostOptionsValidator.cs`
- `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/OpenBBComponentsTests.cs`
- `openbb_platform/core/openbb_core/app/jobs/worker.py`
- `openbb_platform/core/tests/app/jobs/test_worker.py`
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/_app.py`
- `openbb_platform/extensions/portfolio_intel/tests/unit/test_widget_backend.py`

### Task 5 — logging and redaction

- Added exact-value `secrets.env` redaction plus bearer-token and URL-query
  redaction, including exception text.
- Loaded protected environment-file values into child environments without
  placing them in command arguments.
- Added structured, UTF-8-no-BOM, daily component files with 14-day/250-MB
  retention and a 16-KiB encoded-line bound.
- Routed structured child stdout/stderr by component and host logs to the host
  rolling file; enabled Windows Event Log through the Generic Host on Windows.

Files:

- `services/windows/OpenBB.ServiceHost/Logging/SecretRedactor.cs`
- `services/windows/OpenBB.ServiceHost/Logging/ComponentLogWriter.cs`
- `services/windows/OpenBB.ServiceHost/Configuration/ServiceHostOptions.cs`
- `services/windows/OpenBB.ServiceHost/Program.cs`
- `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/LoggingTests.cs`

## TDD evidence

Observed RED before implementation:

- Jobs API: `KeyError: 'queue_depth'`.
- Health probes: C# compile failure because `OpenBB.ServiceHost.Health` and
  probe types did not exist.
- Commands: C# compile failure because `OpenBBComponents` did not exist.
- Worker shutdown: `TypeError` for missing `stop_event` on `run_once`.
- Widget shutdown: `AttributeError` for missing `background_tasks`.
- Logging: C# compile failure because `OpenBB.ServiceHost.Logging` did not
  exist.
- Jobs startup retry: assertion failed (`Expected: True`, `Actual: False`) for
  stale heartbeat retries.
- UTF-8 byte bound: assertion failed because the encoded line exceeded 512
  bytes.

Observed GREEN:

- Health probes: 9 passed.
- Logging: 3 passed.
- Commands/configuration: 21 passed in the focused run.
- Jobs API: 12 passed.
- Jobs worker: 12 passed.
- Widget backend: 147 passed.

## Final validation

```text
dotnet test tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore
Passed: 42, Failed: 0, Skipped: 0

python -m pytest tests\api\test_jobs.py tests\app\jobs\test_worker.py -q
24 passed

python -m pytest openbb_platform\extensions\portfolio_intel\tests\unit\test_widget_backend.py -q
147 passed

python -m ruff check <all changed Python files>
All checks passed!

git diff --check 129306647d8..HEAD
No errors.
```

`ruff format --check` was also inspected; it proposes broad formatting changes
in six pre-existing Python files, so those unrelated rewrites were not applied.

## Self-review

- Verified startup HTTP retries are bounded and stale jobs-heartbeat retries
  occur only in startup mode; steady-state calls perform one request.
- Verified successful-run health data comes only from SQLite metadata.
- Verified command arrays contain no fixture secrets and retain the existing
  Python entry points.
- Verified stop is checked immediately before claiming and active work is not
  interrupted by the worker.
- Verified fixture secret values do not appear in generated logs, including
  exception output, and the byte bound applies after UTF-8 encoding.
- Verified every commit references `#2048` and contains the required
  `Co-authored-by` trailer.
- No deployment scripts or runbook were added.

## Commits

- `8928c6b3ac70a6754f40c16feebd4cbd0bb96e6a` — health diagnostics
- `4a20ee4e610c7bcabba503487d3036fbb1ed9f1c` — child commands and lifecycle
- `14d10ea6d8d5ff512211eec1022494225e4c416f` — log routing and redaction
- `6ab49cccbfdebf87ec15faf9c63b5070dbc0c741` — startup heartbeat retry coverage
- `b58f5d6e063b0c759814c1d328c2ba26c73cc9d9` — UTF-8 byte-bounded logs
- `6511d836076f4acd1c20f71e8b6479271dd8071d` — all configured secret sources
- `0397efba06b7e31e40b2f3a606df0f2e831b283d` — Event Log child-output isolation

## Concerns

- Windows Event Log registration compiles with the complete host suite, but
  live SCM/Event Log verification belongs to the later Windows harness task
  and was not performed here.

## Task-review finding fix — bounded pathological log envelopes

Implemented:

- Updated `ComponentLogWriter.SerializeBounded()` to stop shrinking once the
  message is empty and emit a deterministic minimal fallback JSON record that
  preserves `timestamp` and `level` and sets `truncated: true`.
- Added a regression test with pathological component/event/correlation values
  at `maxLineLength=256` proving the call terminates, the output is valid JSON
  decoded from UTF-8, and the encoded line stays within the configured byte
  bound.

Observed GREEN:

```text
dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --filter "FullyQualifiedName~Falls_back_to_minimal_record_when_metadata_envelope_exceeds_byte_limit" --no-restore
Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1

dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore
Passed!  - Failed:     0, Passed:    44, Skipped:     0, Total:    44
```

## Task-review finding fix — retained-bytes accounting

Observed RED:

```text
dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore --filter "FullyQualifiedName~Retention_counts_only_bytes_for_files_it_keeps"
[xUnit.net 00:00:01.42]     OpenBB.ServiceHost.Tests.LoggingTests.Retention_counts_only_bytes_for_files_it_keeps [FAIL]
Assert.True() Failure
Expected: True
Actual:   False
Failed!  - Failed:     1, Passed:     0, Skipped:     0, Total:     1
```

Observed GREEN:

```text
dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore --filter "FullyQualifiedName~Retention_counts_only_bytes_for_files_it_keeps"
Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1

dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore
Passed!  - Failed:     0, Passed:    43, Skipped:     0, Total:    43, Duration: 1 s
```

## Issue #2048 fix — documented camelCase service-host config

### Reproduction

Added a regression fixture that writes a realistic `service.json` with the documented camelCase keys under `serviceHost`, including:

- `schemaVersion`
- `environmentFile`
- `logDirectory`
- `components`
- nested component fields (`name`, `executablePath`, `arguments`, `workingDirectory`, `bindAddress`, `port`, `startupOrder`, `required`, `readinessTimeout`, `gracefulShutdownTimeout`, `restartWindow`, `maxRestarts`, `restartDelays`, `environment`)

The test binds that JSON through `AddServiceHostOptions()` and then verifies the strict-binding contract explicitly exposes every documented camelCase property name via `ConfigurationKeyName` so real-harness strict binding accepts the documented keys while still rejecting unknown ones.

### Observed RED

```text
dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore --filter "FullyQualifiedName~Strict_binding_accepts_documented_camel_case_json_configuration"
[xUnit.net 00:00:00.74]     OpenBB.ServiceHost.Tests.ServiceHostOptionsTests.Strict_binding_accepts_documented_camel_case_json_configuration [FAIL]
Assert.NotNull() Failure: Value is null
Failed!  - Failed:     1, Passed:     0, Skipped:     0, Total:     1
```

### Observed GREEN

```text
dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore --filter "FullyQualifiedName~Strict_binding_accepts_documented_camel_case_json_configuration"
Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1, Duration: 57 ms - OpenBB.ServiceHost.Tests.dll (net10.0)

dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests\OpenBB.ServiceHost.Tests.csproj --no-restore --verbosity minimal
Passed!  - Failed:     0, Passed:    45, Skipped:     0, Total:    45, Duration: 1 s - OpenBB.ServiceHost.Tests.dll (net10.0)
```
