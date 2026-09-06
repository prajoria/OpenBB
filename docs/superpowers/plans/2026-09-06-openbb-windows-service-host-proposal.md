# OpenBB Windows Service Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one production-grade Windows Service that starts, supervises, health-checks, and stops the OpenBB web UX, Portfolio API, and durable jobs worker as one locally hosted system.

**Architecture:** A small .NET 10 Generic Host runs as the native Windows Service through the public `Microsoft.Extensions.Hosting.WindowsServices` framework. It supervises three existing Python entry points as child processes: the Portfolio API, the Portfolio Intelligence web UX/backend, and `openbb-jobs worker`. OpenBB domain, API, widget, and job logic remain in Python; the .NET service owns only Windows lifecycle, process supervision, health checks, logging, restart policy, and installation.

**Tech Stack:** .NET 10 LTS Generic Host, `Microsoft.Extensions.Hosting.WindowsServices` 10.x, Windows Service Control Manager, Python 3.12 virtual environment, Uvicorn/OpenBB Platform API, OpenBB `JobService`, SQLite/WAL job state, PowerShell deployment scripts.

## Global Constraints

- The Windows Service host MUST contain no financial, portfolio, provider, scan, or scheduling business logic.
- The service MUST bind web endpoints to `127.0.0.1` by default.
- The service MUST supervise exactly one instance of each configured component.
- The web processes MUST NOT execute long-running job handlers.
- The jobs worker MUST remain the only process that executes registered OpenBB jobs.
- Service configuration and data MUST live under `%ProgramData%\OpenBB Portfolio`; binaries MUST live under `%ProgramFiles%\OpenBB Portfolio`.
- Credentials MUST NOT appear in source control, command-line arguments, service XML, process listings, or logs.
- The service MUST run under a least-privilege Windows virtual service account, not `LocalSystem`.
- Child processes MUST be terminated as a process tree during service stop or failed startup.
- Deployment MUST be self-contained for `win-x64`; the target machine MUST NOT require a separately installed .NET runtime.
- The service MUST refuse startup if its Python executable, configuration, required packages, ports, or protected secret file are invalid.
- The service MUST preserve existing standalone developer commands; service hosting is an additional production mode.

---

## GitHub Delivery and Branch Topology

**Program epic:** [#491 Portfolio Intelligence Engine](https://github.com/prajoria/OpenBB/issues/491)  
**Feature epic:** [#2046 OpenBB Portfolio Windows Service Host](https://github.com/prajoria/OpenBB/issues/2046)  
**Jobs foundation:** [#1934 Async scan + ScanSnapshotStore](https://github.com/prajoria/OpenBB/issues/1934)  
**Integration branch:** `feat/pi-jobs-service-gh-1934`

Every related issue carries `program:openbb-service-host`,
`area:windows-service`, one `type:*` label, one `phase:service-host-*` label,
and `priority:P2`.

| Order | GitHub issue | Plan scope | Side branch | PR base |
| --- | --- | --- | --- | --- |
| 1 | [#2047 Native Windows host configuration and supervision](https://github.com/prajoria/OpenBB/issues/2047) | Tasks 1-2 | `feat/windows-service-host-gh-2047` | `feat/pi-jobs-service-gh-1934` |
| 2 | [#2048 OpenBB health, logging, and runtime integration](https://github.com/prajoria/OpenBB/issues/2048) | Tasks 3-5 | `feat/windows-service-integration-gh-2048` | `feat/pi-jobs-service-gh-1934` |
| 3 | [#2049 Secure Windows install, update, rollback, and uninstall](https://github.com/prajoria/OpenBB/issues/2049) | Task 6 | `feat/windows-service-deploy-gh-2049` | `feat/pi-jobs-service-gh-1934` |
| 4 | [#2050 Windows acceptance harness and operator runbook](https://github.com/prajoria/OpenBB/issues/2050) | Task 7 | `test/windows-service-verify-gh-2050` | `feat/pi-jobs-service-gh-1934` |

The branches are dependency ordered. A later branch starts from the updated
integration branch only after the preceding PR merges. Each child PR uses a
`Closes #NNNN` line for its own issue. After all four child PRs land, the
integration branch opens or updates one final PR to `portfolio` that closes
#2046 and the remaining #1934 work.

## 1. Executive Proposal

### 1.1 Proposed service

Install one Windows service:

```text
Service name: OpenBBPortfolio
Display name: OpenBB Portfolio Services
Startup: Automatic (Delayed Start)
Account: NT SERVICE\OpenBBPortfolio
Recovery: restart after 15s, 30s, 60s; reset after 24h
```

The service starts and supervises:

| Component | Existing entry point | Bind/transport | Purpose |
| --- | --- | --- | --- |
| `portfolio-api` | `python -m openbb_platform_api.main --app openbb_platform/extensions/portfolio/launch.py` | `127.0.0.1:6902` | Portfolio/OpenBB API and Workspace backend |
| `portfolio-intel-ux` | `python -m uvicorn openbb_portfolio_intel.widget_backend.main:app` | `127.0.0.1:6120` | Local viewer at `/viewer`, widgets, apps, and TechTrade UX |
| `jobs-worker` | `python -m openbb_core.app.jobs.worker worker` | SQLite and provider/database connections | Durable scheduled scans and cache warming |

The service reports `RUNNING` only after both web health probes pass and the
jobs worker heartbeat appears in the durable job store.

### 1.2 Framework decision

Use the public Microsoft framework:

- [`Microsoft.Extensions.Hosting.WindowsServices`](https://learn.microsoft.com/dotnet/core/extensions/windows-service)
- [`BackgroundService`](https://learn.microsoft.com/dotnet/core/extensions/workers)
- .NET `Process.Kill(entireProcessTree: true)` for bounded process-tree cleanup
- Windows Event Log through the Generic Host logging stack

The service host is published as a self-contained, single-file `win-x64`
executable.

### 1.3 Why this framework

| Option | Decision | Reason |
| --- | --- | --- |
| .NET Generic Host Windows Service | **Selected** | Actively maintained by Microsoft; native SCM lifecycle; self-contained deployment; structured configuration/logging; straightforward supervision of multiple child processes |
| Servy | Pilot alternative | MIT licensed, signed, active, and feature-rich, but app-aware coordination would still require an OpenBB supervisor process and introduces a smaller third-party operational dependency |
| WinSW stable 2.x | Not selected | Mature MIT wrapper, but it primarily monitors one executable and its stable line is old; coordinated readiness and per-component policy would remain custom |
| NSSM | Not selected | Suitable for wrapping one process, but not the preferred foundation for a new coordinated host |
| pywin32 service | Not selected | Keeps one language but requires custom SCM integration and machine-global Windows/Python installation considerations |
| One Windows service per component | Deferred | Stronger fault isolation, but conflicts with the requested single overall service and complicates installation and operator workflow |

Official references:

- Microsoft Windows Service worker guidance:
  <https://learn.microsoft.com/dotnet/core/extensions/windows-service>
- WinSW project and MIT license: <https://github.com/winsw/winsw>
- Servy project and MIT license: <https://github.com/aelassas/servy>
- pywin32 Windows service notes: <https://github.com/mhammond/pywin32>

## 2. System Architecture

```text
Windows Service Control Manager
             |
             v
  OpenBB.ServiceHost.exe (.NET 10)
             |
     +-------+----------------------+----------------------+
     |                              |                      |
     v                              v                      v
Portfolio API                Portfolio Intel UX       OpenBB Jobs Worker
127.0.0.1:6902              127.0.0.1:6120           jobs.db + providers
     |                              |                      |
     +--------------+---------------+----------------------+
                    |
                    v
        MySQL/provider caches and scan snapshots
```

### 2.1 Host responsibilities

The host:

1. loads and validates `service.json`;
2. loads secrets from a protected environment file without logging values;
3. verifies the Python environment and required modules;
4. checks configured ports before launch;
5. starts children in dependency order;
6. drains stdout/stderr into structured per-component logs;
7. probes readiness and liveness;
8. restarts a failed child with bounded exponential backoff;
9. exits non-zero after a component exceeds its restart budget so Windows SCM
   recovery can restart the entire service;
10. stops children in reverse dependency order and kills remaining process
    trees after the configured grace period.

The host does not enqueue, claim, execute, or inspect job payloads.

### 2.2 Startup order

1. Validate filesystem, configuration, secrets, imports, and ports.
2. Start `jobs-worker`.
3. Wait for a new worker heartbeat in `jobs.db`.
4. Start `portfolio-api`.
5. Wait for `GET /api/v1/coverage/commands` or a dedicated health route.
6. Start `portfolio-intel-ux`.
7. Wait for `GET /widgets.json` and `GET /viewer`.
8. Mark aggregate readiness healthy.

If any required component does not become ready within 60 seconds, stop all
children and fail service startup.

### 2.3 Shutdown order

1. Stop accepting new restart attempts.
2. Signal `portfolio-intel-ux`.
3. Signal `portfolio-api`.
4. Signal `jobs-worker`; allow the active handler its configured grace period.
5. Wait up to 30 seconds per child.
6. Kill any remaining process tree.
7. Flush logs and return control to SCM.

### 2.4 Failure policy

Each component has a five-minute rolling restart window:

```json
{
  "maxRestarts": 3,
  "restartDelaysSeconds": [2, 10, 30],
  "stabilityResetSeconds": 300
}
```

- First three failures restart only the failed child.
- The fourth failure exits the service with a non-zero code.
- SCM restarts the complete service according to the configured recovery
  actions.
- A failed web health probe is treated the same as a process exit.
- A stale jobs heartbeat is treated as a failed jobs worker.
- No fallback starts a second in-process scheduler or executes work in a web
  process.

## 3. Configuration

### 3.1 Public configuration

Create `%ProgramData%\OpenBB Portfolio\service.json`:

```json
{
  "schemaVersion": 1,
  "pythonExecutable": "C:\\Program Files\\OpenBB Portfolio\\venv\\Scripts\\python.exe",
  "workingDirectory": "C:\\Program Files\\OpenBB Portfolio\\app",
  "environmentFile": "C:\\ProgramData\\OpenBB Portfolio\\secrets.env",
  "dataDirectory": "C:\\ProgramData\\OpenBB Portfolio\\data",
  "logDirectory": "C:\\ProgramData\\OpenBB Portfolio\\logs",
  "components": {
    "portfolioApi": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 6902,
      "healthPath": "/api/v1/coverage/commands",
      "startupTimeoutSeconds": 60
    },
    "portfolioIntelUx": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 6120,
      "healthPath": "/widgets.json",
      "viewerPath": "/viewer",
      "startupTimeoutSeconds": 60
    },
    "jobsWorker": {
      "enabled": true,
      "pollSeconds": 5,
      "heartbeatMaxAgeSeconds": 90,
      "shutdownGraceSeconds": 600
    }
  },
  "restartPolicy": {
    "maxRestarts": 3,
    "restartDelaysSeconds": [2, 10, 30],
    "stabilityResetSeconds": 300
  }
}
```

Unknown properties and unsupported `schemaVersion` values fail validation.
Relative executable, working-directory, data, log, and secret paths are
rejected for the installed-service mode.

### 3.2 Secret configuration

Create `%ProgramData%\OpenBB Portfolio\secrets.env`, ACL-readable only by
Administrators and `NT SERVICE\OpenBBPortfolio`.

It may contain:

```text
PI_WIDGET_BACKEND_AUTH_MODE=required
PI_WIDGET_BACKEND_TOKEN=<generated during install>
OPENBB_JOBS_ENABLED=true
OPENBB_JOBS_DB=C:\ProgramData\OpenBB Portfolio\data\jobs.db
PI_SCAN_DB=C:\ProgramData\OpenBB Portfolio\data\techtrade_scan.db
MYSQL_HOST=<operator supplied>
MYSQL_USER=<operator supplied>
MYSQL_PASSWORD=<operator supplied>
MYSQL_DATABASE=<operator supplied>
FMP_API_KEY=<operator supplied>
```

The installer generates `PI_WIDGET_BACKEND_TOKEN` when absent. It never
generates, prints, or logs provider/database credentials.

### 3.3 Deployment layout

```text
C:\Program Files\OpenBB Portfolio\
  OpenBB.ServiceHost.exe
  app\
  venv\
  version.json

C:\ProgramData\OpenBB Portfolio\
  service.json
  secrets.env
  data\
    jobs.db
    techtrade_scan.db
  logs\
    service-host-YYYYMMDD.log
    portfolio-api-YYYYMMDD.log
    portfolio-intel-ux-YYYYMMDD.log
    jobs-worker-YYYYMMDD.log
```

Application upgrades replace the immutable `Program Files` release directory.
They never replace `ProgramData` state or secrets.

## 4. Security Model

- Bind both HTTP servers to `127.0.0.1`; remote binding requires a separate
  reviewed reverse-proxy design.
- Run the service under `NT SERVICE\OpenBBPortfolio`.
- Grant that account read/execute on the release directory and modify access
  only to the data/log directories.
- Grant Administrators and the service account read access to `secrets.env`;
  remove inherited user access.
- Never pass secrets in child command lines.
- Scrub configured secret keys from child stdout/stderr before writing logs.
- Disable Uvicorn reload mode.
- Do not generate self-signed certificates at service startup. Loopback HTTP
  is the default; optional TLS certificates are provisioned before service
  installation.
- Reject configuration that binds `0.0.0.0`, `::`, or a non-loopback address
  unless `allowRemoteBinding` is explicitly enabled and the auth mode is
  `required`.
- Use Windows Firewall rules only if remote binding is separately approved.

## 5. Observability and Operations

### 5.1 Logs

- Windows Event Log: service lifecycle, aggregate readiness, exhausted restart
  budget, invalid configuration.
- Rolling files: host and one stream per child.
- Default retention: 14 daily files or 250 MB per component, whichever comes
  first.
- Every host record includes timestamp, level, component, process ID, event,
  restart count, and correlation ID where available.

### 5.2 Health

Provide:

```powershell
OpenBB.ServiceHost.exe doctor --config "C:\ProgramData\OpenBB Portfolio\service.json" --json
```

The command returns non-zero if:

- the Windows service is not running;
- either HTTP probe is unhealthy;
- the jobs heartbeat is stale;
- a required port is owned by an unexpected process;
- the SQLite stores fail read/write integrity checks;
- required modules cannot be imported from the configured Python environment.

### 5.3 Operator commands

```powershell
Get-Service OpenBBPortfolio
Start-Service OpenBBPortfolio
Stop-Service OpenBBPortfolio
Restart-Service OpenBBPortfolio

OpenBB.ServiceHost.exe doctor --json
openbb-jobs list
openbb-jobs trigger techtrade.daily_scan --wait
openbb-jobs trigger portfolio.position_history --wait
openbb-jobs trigger portfolio.etf_holdings --wait
```

## 6. Implementation File Map

### New Windows host project

```text
services/windows/OpenBB.ServiceHost/
  OpenBB.ServiceHost.csproj
  Program.cs
  Configuration/ServiceHostOptions.cs
  Configuration/ServiceHostOptionsValidator.cs
  Processes/ComponentDefinition.cs
  Processes/ComponentSupervisor.cs
  Processes/ChildProcess.cs
  Health/HttpComponentProbe.cs
  Health/JobsHeartbeatProbe.cs
  Health/DoctorCommand.cs
  Logging/SecretRedactor.cs
  appsettings.json
  tests/OpenBB.ServiceHost.Tests/
```

### Deployment assets

```text
deploy/windows/
  install-openbb-service.ps1
  update-openbb-service.ps1
  uninstall-openbb-service.ps1
  service.example.json
  secrets.example.env
  README.md
```

### Existing Python files to modify

```text
openbb_platform/core/openbb_core/app/jobs/worker.py
openbb_platform/core/openbb_core/api/router/jobs.py
openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/main.py
openbb_platform/core/pyproject.toml
```

Python changes are limited to stable readiness/shutdown surfaces:

- expose a jobs-worker heartbeat/status command;
- expose lightweight authenticated health without executing jobs;
- ensure web apps handle termination signals and drain cleanly;
- preserve all current standalone entry points.

## 7. Implementation Plan

### Task 1: Create and validate the service-host configuration model

**Files:**
- Create: `services/windows/OpenBB.ServiceHost/OpenBB.ServiceHost.csproj`
- Create: `services/windows/OpenBB.ServiceHost/Program.cs`
- Create: `services/windows/OpenBB.ServiceHost/Configuration/ServiceHostOptions.cs`
- Create: `services/windows/OpenBB.ServiceHost/Configuration/ServiceHostOptionsValidator.cs`
- Create: `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/ServiceHostOptionsTests.cs`

**Interfaces:**
- Produces: `ServiceHostOptions`, `ComponentOptions`, and
  `ServiceHostOptionsValidator`.

- [ ] Create a .NET 10 worker project referencing:

```xml
<PackageReference Include="Microsoft.Extensions.Hosting.WindowsServices" Version="10.*" />
<PackageReference Include="Microsoft.Extensions.Http.Resilience" Version="10.*" />
```

- [ ] Add failing tests for schema version, absolute paths, loopback-only
  bindings, unique ports, positive timeouts, and restart-delay cardinality.
- [ ] Implement options binding with `ValidateOnStart()`.
- [ ] Add a `--validate-config` command that performs no process launch.
- [ ] Run:

```powershell
dotnet test services\windows\OpenBB.ServiceHost\tests\OpenBB.ServiceHost.Tests
```

Expected: all configuration tests pass.

### Task 2: Implement child process lifecycle supervision

**Files:**
- Create: `services/windows/OpenBB.ServiceHost/Processes/ComponentDefinition.cs`
- Create: `services/windows/OpenBB.ServiceHost/Processes/ChildProcess.cs`
- Create: `services/windows/OpenBB.ServiceHost/Processes/ComponentSupervisor.cs`
- Create: `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/ComponentSupervisorTests.cs`

**Interfaces:**
- Consumes: validated `ServiceHostOptions`.
- Produces: `ComponentSupervisor : BackgroundService`.

- [ ] Add a deterministic fake-child executable used only by tests.
- [ ] Test startup order, readiness timeout, isolated restart, backoff,
  restart-budget exhaustion, reverse-order shutdown, and process-tree kill.
- [ ] Launch children with `UseShellExecute=false`, redirected output/error,
  inherited sanitized environment, and explicit working directory.
- [ ] Use `WaitForExitAsync(CancellationToken)` and
  `Kill(entireProcessTree: true)` after the graceful stop timeout.
- [ ] Set `Environment.ExitCode` non-zero when a required component exhausts
  its restart budget so SCM recovery runs.
- [ ] Run the supervisor tests and verify no child process remains afterward.

### Task 3: Add readiness and liveness probes

**Files:**
- Create: `services/windows/OpenBB.ServiceHost/Health/HttpComponentProbe.cs`
- Create: `services/windows/OpenBB.ServiceHost/Health/JobsHeartbeatProbe.cs`
- Create: `services/windows/OpenBB.ServiceHost/Health/DoctorCommand.cs`
- Create: `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/HealthProbeTests.cs`
- Modify: `openbb_platform/core/openbb_core/api/router/jobs.py`
- Test: `openbb_platform/core/tests/api/test_jobs.py`

**Interfaces:**
- Produces: `IComponentProbe`, `ProbeResult`, and `doctor --json`.

- [ ] Test healthy, failed, timeout, malformed response, and stale jobs
  heartbeat cases.
- [ ] Add a read-only jobs health payload containing queue depth, current
  worker heartbeat age, and last successful run per registered job.
- [ ] Ensure the health route never imports or invokes a handler.
- [ ] Implement bounded HTTP retries only during startup; steady-state probes
  use one request per interval.
- [ ] Run .NET health tests and Python jobs API tests.

### Task 4: Define exact OpenBB child commands and graceful shutdown

**Files:**
- Create: `services/windows/OpenBB.ServiceHost/Processes/OpenBBComponents.cs`
- Modify: `openbb_platform/core/openbb_core/app/jobs/worker.py`
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/main.py`
- Test: `openbb_platform/core/tests/app/jobs/test_worker.py`
- Test: `openbb_platform/extensions/portfolio_intel/tests/unit/test_widget_backend.py`

**Interfaces:**
- Produces: deterministic command/argument arrays for all three components.

- [ ] Test command construction without embedding secrets.
- [ ] Add a worker shutdown test proving no new job is claimed after stop and
  the active job receives the configured grace period.
- [ ] Add a widget-backend lifespan test proving shutdown completes without
  leaving background tasks.
- [ ] Reject `--reload` in installed-service mode.
- [ ] Run focused Python and .NET component tests.

### Task 5: Implement log routing and secret redaction

**Files:**
- Create: `services/windows/OpenBB.ServiceHost/Logging/SecretRedactor.cs`
- Create: `services/windows/OpenBB.ServiceHost/Logging/ComponentLogWriter.cs`
- Create: `services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests/LoggingTests.cs`

**Interfaces:**
- Produces: redacted structured log records and daily rolling component logs.

- [ ] Test redaction for exact values loaded from `secrets.env`, bearer
  headers, URL query strings, and exception messages.
- [ ] Test bounded line length and UTF-8 output.
- [ ] Route host lifecycle messages to Windows Event Log and rolling files.
- [ ] Route child stdout/stderr to component-specific rolling files.
- [ ] Verify test logs contain no fixture secret values.

### Task 6: Build secure install, update, and uninstall scripts

**Files:**
- Create: `deploy/windows/install-openbb-service.ps1`
- Create: `deploy/windows/update-openbb-service.ps1`
- Create: `deploy/windows/uninstall-openbb-service.ps1`
- Create: `deploy/windows/service.example.json`
- Create: `deploy/windows/secrets.example.env`
- Test: `deploy/windows/tests/OpenBBService.Install.Tests.ps1`

**Interfaces:**
- Produces: idempotent elevated deployment commands.

- [ ] Test install parameter validation and `-WhatIf` behavior with Pester.
- [ ] Publish the host:

```powershell
dotnet publish services\windows\OpenBB.ServiceHost `
  -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true
```

- [ ] Install Python packages into the service-owned virtual environment.
- [ ] Create the virtual service account ACLs with `icacls`.
- [ ] Generate the widget token only when absent.
- [ ] Register `OpenBBPortfolio` with `sc.exe create`, delayed automatic
  startup, description, and recovery actions.
- [ ] Start the service and run `doctor --json`.
- [ ] Make updates transactional: stage new release, stop, swap, start,
  verify, and roll back on failed health.
- [ ] Preserve `ProgramData` during uninstall unless `-PurgeData` is explicit.

### Task 7: End-to-end service verification and operator documentation

**Files:**
- Create: `deploy/windows/README.md`
- Create: `docs/operations/openbb-windows-service.md`
- Create: `.dev-cycle/windows-service-verify.log`

**Interfaces:**
- Consumes: the published host, deployment scripts, OpenBB web apps, and jobs
  worker.
- Produces: installation, recovery, upgrade, backup, and troubleshooting
  guidance.

- [ ] Install into a clean Windows VM or disposable test host.
- [ ] Reboot and verify the service starts before interactive logon.
- [ ] Verify:

```text
GET http://127.0.0.1:6120/viewer
GET http://127.0.0.1:6120/widgets.json
GET http://127.0.0.1:6902/api/v1/coverage/commands
openbb-jobs trigger portfolio.etf_holdings --params-json "{\"dry_run\":true}" --wait
```

- [ ] Kill each child process independently and prove isolated restart.
- [ ] Force four rapid failures and prove SCM restarts the aggregate service.
- [ ] Stop the service during a long fake job and prove bounded graceful
  shutdown followed by process-tree cleanup.
- [ ] Verify logs and process command lines contain no secrets.
- [ ] Back up and restore `jobs.db`, `techtrade_scan.db`, service configuration,
  and secrets into a clean install.
- [ ] Record commands and outputs in
  `.dev-cycle/windows-service-verify.log`.

## 8. Acceptance Criteria

1. `OpenBBPortfolio` starts automatically after reboot without user logon.
2. `/viewer`, `/widgets.json`, and the Portfolio API become ready within 60
   seconds on the reference machine.
3. Exactly one jobs worker heartbeat is active.
4. A scheduled or manually queued job survives service restart.
5. Killing one child restarts only that child until its restart budget is
   exhausted.
6. Exhausting a child restart budget causes a non-zero service exit and SCM
   recovery.
7. `Stop-Service OpenBBPortfolio` leaves no Python child process.
8. The service account cannot modify application binaries.
9. No secret appears in logs, command lines, committed files, or diagnostic
   output.
10. Existing developer commands continue to run outside the service.
11. Update rollback restores the previous healthy release without changing
    persistent databases or secrets.
12. Unit, Pester, Python integration, and Windows VM end-to-end tests pass.

## 9. Rollout Recommendation

### Phase A: Shadow host

- Install the service with all schedules disabled.
- Run both web children and verify health for 24 hours.
- Trigger dry-run jobs manually.

### Phase B: Jobs migration

- Enable `portfolio.position_history`, `portfolio.etf_holdings`, and
  `techtrade.daily_scan` schedules.
- Disable equivalent Windows Scheduled Tasks to prevent duplicate runs.
- Verify persisted job history and scan freshness for five trading days.

### Phase C: Default startup path

- Make the Windows Service the documented production startup method.
- Retain standalone PowerShell/Python commands for break-glass operation.
- Remove obsolete scheduled-task registration guidance after one release.

## 10. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| One aggregate service increases blast radius | Restart children independently; exit aggregate host only after bounded repeated failures |
| Python child ignores shutdown | Grace period followed by `Kill(entireProcessTree: true)` |
| Job duplicated after worker crash | Existing durable lease/recovery model and idempotent job handlers |
| SQLite corruption or lock contention | WAL, short transactions, periodic integrity check, documented backups |
| Port conflict | Preflight ownership check and fail-fast startup |
| Secret leakage through child output | Environment-only secrets plus value-aware redaction and tests |
| Service account cannot access user-local venv/settings | Service-owned immutable venv and ProgramData configuration |
| .NET adds another build stack | Keep host small, self-contained, isolated from domain code, and pinned to .NET 10 LTS |
| Local viewer/API starts before dependencies | Explicit ordered readiness gates |
| Future multi-host deployment | Replace the single-host SQLite `JobStore`; Windows host contract remains unchanged |

## 11. Approved Decision

Implement the .NET 10 Generic Host architecture through issues #2047-#2050 and
merge each side-branch PR into `feat/pi-jobs-service-gh-1934`.

Servy wrapping one Python supervisor remains a documented fallback only. It is
not part of the implementation scope.
