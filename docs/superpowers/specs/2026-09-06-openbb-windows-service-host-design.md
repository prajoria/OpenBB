# OpenBB Windows Service Host Design

**Status:** Approved for implementation  
**Program:** Portfolio Intelligence Engine, Project #4  
**Integration branch:** `feat/pi-jobs-service-gh-1934`

## Purpose

Provide one production Windows Service that owns the lifecycle of the local
OpenBB Portfolio system:

1. the OpenBB Portfolio API on loopback port 6902;
2. the Portfolio Intelligence web UX/backend on loopback port 6120;
3. the durable OpenBB jobs worker.

The service replaces ad hoc interactive startup and external-only scheduled
tasks without moving OpenBB business logic out of Python.

## Success Criteria

- Windows starts the complete local system before interactive logon.
- The service starts, health-checks, restarts, and stops each child process.
- The web processes never execute long-running job handlers.
- The jobs worker remains the only process that executes registered jobs.
- A child crash is isolated until its bounded restart budget is exhausted.
- Service stop leaves no Python descendants.
- Credentials do not appear in source control, process arguments, or logs.
- Persistent job and scan data survive service upgrades and rollbacks.
- Existing standalone developer commands remain supported.

## Alternatives Considered

### 1. .NET Generic Host Windows Service — selected

Use .NET 10 LTS with
`Microsoft.Extensions.Hosting.WindowsServices`. The host supervises existing
Python entry points as independent child processes.

Advantages:

- Microsoft-maintained native Service Control Manager integration;
- first-class cancellation, configuration, dependency injection, and logging;
- self-contained single-file deployment;
- explicit app-aware startup order and health policy;
- reliable process-tree termination through .NET `Process`.

Cost:

- introduces one small C# project and .NET build lane.

### 2. Servy wrapping a Python supervisor

Servy is an active, signed, MIT-licensed service wrapper with health and restart
features. It would still require a custom Python process supervisor for
coordinated readiness across three components.

This is acceptable for a pilot but not selected because the OpenBB-specific
supervisor remains custom while operational behavior is split across two
configuration systems.

### 3. WinSW or one service per process

WinSW is a mature MIT wrapper but primarily supervises one top-level command.
Installing one wrapper service per component improves fault isolation but
conflicts with the requested single system service and creates more operator
surface.

This remains a future option if the components need independent maintenance
windows or service accounts.

## Architecture

```text
Windows Service Control Manager
             |
             v
  OpenBB.ServiceHost.exe
  (.NET Generic Host)
             |
     +-------+------------------+------------------+
     |                          |                  |
     v                          v                  v
Portfolio API             Portfolio Intel UX    Jobs worker
127.0.0.1:6902            127.0.0.1:6120        jobs.db
```

The .NET host contains no portfolio, provider, scan, cache, or scheduling
logic. It owns only:

- validated configuration;
- child process creation;
- sanitized environment propagation;
- readiness and liveness probes;
- bounded restart/backoff;
- structured log routing and redaction;
- ordered graceful shutdown;
- Windows Service status and exit codes.

## Component Boundaries

### Service host

The service host consumes a versioned `service.json` and protected
`secrets.env`. It creates one `ComponentSupervisor` per configured child and
coordinates them through a top-level hosted service.

Public host commands:

```text
OpenBB.ServiceHost.exe --validate-config
OpenBB.ServiceHost.exe doctor --json
OpenBB.ServiceHost.exe run
```

### Portfolio API

The host launches the existing Portfolio/OpenBB API entry point on
`127.0.0.1:6902`. Readiness uses a lightweight existing or dedicated endpoint
that does not call providers.

### Portfolio Intelligence web UX

The host launches
`openbb_portfolio_intel.widget_backend.main:app` on `127.0.0.1:6120`.
Readiness requires both `/widgets.json` and `/viewer`.

### Jobs worker

The host launches `openbb-jobs worker`. Readiness requires a fresh worker
heartbeat in the durable SQLite store. The host never claims or executes a job.

## Startup and Shutdown

Startup is dependency ordered:

1. validate configuration, secrets, paths, imports, stores, and ports;
2. start the jobs worker and await a fresh heartbeat;
3. start the Portfolio API and await readiness;
4. start the web UX and await `/widgets.json` and `/viewer`;
5. report aggregate readiness.

Each step has a 60-second default timeout. A failed required step stops every
started child and fails service startup.

Shutdown is reverse ordered:

1. stop restart attempts;
2. stop the web UX;
3. stop the Portfolio API;
4. request jobs-worker shutdown and allow the active handler its configured
   grace period;
5. kill any remaining process tree;
6. flush logs and exit.

## Failure and Recovery

Each component gets three restarts within a five-minute rolling window with
delays of 2, 10, and 30 seconds.

- A process exit or failed liveness probe restarts only that child.
- A fourth failure exits the aggregate host non-zero.
- Windows SCM recovery restarts the whole service after 15, 30, then 60
  seconds.
- Stable operation for five minutes resets the child restart counter.
- No fallback starts an in-process scheduler or a second jobs worker.

## Configuration and Security

Installed layout:

```text
%ProgramFiles%\OpenBB Portfolio\
  OpenBB.ServiceHost.exe
  app\
  venv\

%ProgramData%\OpenBB Portfolio\
  service.json
  secrets.env
  data\
  logs\
```

Security requirements:

- service account: `NT SERVICE\OpenBBPortfolio`;
- web binds: loopback only by default;
- application files: read/execute for the service account;
- data/log directories: modify for the service account;
- secret file: readable only by Administrators and the service account;
- secrets passed only through the child environment;
- configured secret values and bearer tokens redacted from logs;
- no dependency installation, certificate generation, or source checkout at
  steady-state service startup.

## Observability

- Windows Event Log records service lifecycle, invalid configuration,
  aggregate readiness, and exhausted restart budgets.
- Rolling UTF-8 files record host and per-component stdout/stderr.
- `doctor --json` reports service state, HTTP readiness, worker heartbeat age,
  store integrity, import preflight, and port ownership.
- The jobs health API remains read-only and never imports or invokes handlers.

## Testing Strategy

### Unit tests

- configuration schema and path/bind validation;
- process startup order and reverse shutdown;
- isolated restarts and exhausted budgets;
- HTTP health timeout and malformed-response handling;
- stale worker heartbeat detection;
- secret redaction;
- process-tree termination.

### Integration tests

- fake child executables for deterministic lifecycle tests;
- Python tests for the jobs health payload and graceful worker shutdown;
- Pester tests for install/update/uninstall scripts;
- self-contained host publish and config validation.

### Windows harness

On a disposable Windows host:

1. install the service;
2. reboot without logon;
3. verify ports 6902 and 6120 plus the jobs heartbeat;
4. kill each child and observe isolated restart;
5. exceed a restart budget and observe SCM recovery;
6. stop during a long fake job and verify bounded cleanup;
7. update and force failed health to verify rollback;
8. scan logs and process arguments for fixture secrets.

## Git and Issue Delivery Model

The existing branch `feat/pi-jobs-service-gh-1934` is the integration branch
because it owns the durable jobs foundation on which the Windows host depends.

The implementation is delivered through dependency-ordered child branches:

1. `feat/windows-service-host-gh-<issue>`  
   Native host, configuration, process supervision, health, and logging.
2. `feat/windows-service-deploy-gh-<issue>`  
   Secure installation, update, rollback, uninstall, and packaging.
3. `test/windows-service-verify-gh-<issue>`  
   Windows harness, operations documentation, and acceptance evidence.

Every child branch opens a PR whose base is
`feat/pi-jobs-service-gh-1934`. The next child branch starts only after its
dependency PR has merged into the integration branch. The integration branch
then opens or updates one final PR to `portfolio`.

This ordering keeps each PR independently reviewable while ensuring the final
system lands on the requested integration branch before portfolio merge.

## Non-Goals

- multi-host job coordination;
- remote/public web exposure;
- replacing SQLite with a distributed queue;
- rewriting OpenBB web or job business logic in C#;
- dependency installation during every service start;
- a GUI service manager;
- independent Windows services per child process.
