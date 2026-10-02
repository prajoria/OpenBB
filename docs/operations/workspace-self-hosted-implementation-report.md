# Self-hosted Workspace implementation report

**Recorded:** 2026-10-02

**Program:** [#2096](https://github.com/prajoria/OpenBB/issues/2096)

**Replay layer:** [#2111](https://github.com/prajoria/OpenBB/issues/2111)

## Executive verdict

The pinned OpenBB Workspace source has a repeatable, loopback-only Windows
development deployment. On the recorded machine, the authoritative sequence
`setup → run → test → stop` completed successfully. The verifier proved the
exact Compose project and services, loopback listeners, backend and frontend
health, managed administrator login, exact allowed/rejected CORS behavior,
pinned source with no tracked or unexpected untracked files, ignored runtime
state, and lockfile policy.

This is a **development deployment**, not a production hardening or complete
hosted-product parity claim. Future operators and AI sessions must invoke the
checked-in scripts rather than reconstruct Docker, Bun, environment, process,
credential, or health commands.

## Source audit and verdict

`third_party/workspace` is a mode-`160000` Git submodule pinned at
`2a1d897247d42b683039e820e26c477b6f15b83d`. The #2108 audit found Apache-2.0
source for the React/Vite frontend, FastAPI/SQLAlchemy backend, SQLite
development Compose path, Redis/RQ, Excel add-in, custom backends and agents,
integrated MCP routes, and a standalone MCP package. It found no nested
submodule or Git LFS payload.

The source is substantial but partial. TradingView Advanced Charts assets and
the hosted OpenBB AI service are absent. The supported deployment deliberately
uses the SQLite Compose development stack and Bun lockfile; the Lite image path
that expects npm-generated state is not supported.

## Architecture and data flow

```text
Browser
  │ http://127.0.0.1:1420
  ▼
Bun/Vite frontend (Windows host, exact owned PID tree)
  │ CORS origin: http://127.0.0.1:1420 only
  ▼
FastAPI (Docker, 127.0.0.1:8000)
  ├── SQLite + folder storage (ignored local volume/state)
  ├── Redis (Docker, 127.0.0.1:6379)
  └── RQ worker (Docker, internal service traffic)
```

The Compose project is exactly `openbb-workspace-2110`; its configured and
running service set is exactly `redis`, `fastapi`, and `rq_worker`. Migrations
run before service startup. User/entity initialization is idempotent. Setup
manages one stable local administrator identity and rotates its ignored
password; verification reads that file without printing it and sends a login
request without printing the response.

## Recorded machine baseline

| Component | Recorded value |
| --- | --- |
| Windows | NT `10.0.26200.0` |
| PowerShell | `7.4.20` |
| Git | `2.54.0.windows.1` |
| Docker Desktop Linux engine | `29.5.3` |
| Docker Compose | `5.1.4` |
| Bun | `1.3.14` |
| Parent baseline | `edc999249f31` (merged PR #2112) |
| Workspace pin | `2a1d897247d42b683039e820e26c477b6f15b83d` |

Docker Desktop must be running its Linux engine. Git, Docker Compose, and Bun
must be available to PowerShell 7. Host Poetry and Python 3.13 are not required
for this deployment.

## Issue and pull-request history (#2096–#2112)

| Number | Kind | Outcome |
| --- | --- | --- |
| #2096 | Epic | Defines the local Workspace development program. |
| #2097 | Issue | Pins reference repositories and the execution plan. |
| #2098 | Issue | Adds the Windows setup preflight. |
| #2099 | Issue | Adds the Portfolio Intelligence launcher. |
| #2100 | Issue | Adds privacy-safe smoke checks and the operator runbook. |
| #2101 | Issue | Next: hosted Workspace and browser-harness validation. |
| #2102 | Issue | Later: Workspace Bench and hosted MCP certification. |
| #2103 | Issue | Later: optional Portfolio Copilot proxy validation. |
| #2104 | PR | Merges #2097 foundations. |
| #2105 | PR | Merges #2098 setup. |
| #2106 | PR | Merges #2099 launcher. |
| #2107 | PR | Merges #2100 runbook and smoke checks. |
| #2108 | Issue | Pins and audits self-hosted Workspace source. |
| #2109 | PR | Merges #2108 source audit. |
| #2110 | Issue | Implements the secure self-hosted development stack. |
| #2111 | Issue | Adds this durable verifier, report, and replay skill. |
| #2112 | PR | Merges #2110 deployment and follow-up fixes. |

The required order after #2111 is #2101, #2102, then optional #2103.

## Browser replay evidence (#2101)

On 2026-10-02, a fresh authoritative `setup → run → test` replay passed. A
visible Playwright run then read the ignored managed credential JSON locally,
submitted the source-backed Email, Password, and Login controls, and reached an
authenticated route. A second headless run used the same existing ignored
`$HOME\.openbb_browser_test_harness\chrome_profile` and reached the
authenticated route without submitting the form. No credential value, cookie,
profile content, screenshot, or response body was persisted or reported.

Review hardening now restricts managed login and development TLS opt-in to the
exact `http://127.0.0.1:1420` configuration. The driver revalidates the live
origin after navigation and before credential reads/fills, recognizes
authentication only on the exact origin's `/app` route family, and rejects
aliases, alternate ports, HTTPS, userinfo, query-shaped configuration, auth
routes, and off-origin redirects without credential access. Mocked Playwright
tests prove off-origin credential loaders and input fills remain untouched,
successful local submission still works, and an authenticated profile is
reused without reading credentials.

Portfolio Intelligence and Portfolio were started through
`run_widget_backend.ps1` and `run_portfolio_backend.ps1`. The privacy-safe
backend verifier reported 61 Intelligence widgets, three Intelligence apps,
17 Portfolio widgets, one Portfolio app, and one Portfolio agent. One
Intelligence widget endpoint returned HTTP 200 with non-empty content without
logging its body. Portfolio served HTTPS on loopback with the generated
development certificate; the browser context was explicitly limited to
ignoring development TLS errors.

The initial UI acceptance run exposed an empty authenticated `/app` shell.
Issue #2115 traced the root cause to on-prem login state: a missing hosted
`developer_onboarding_info` record was persisted as `needsOnboarding=true`,
and `AuthGuard` returned `null` before the layout or redirect helper mounted.
The source fix in `prajoria/workspace` PR #1 treats on-prem sessions as
onboarding-complete while preserving hosted onboarding behavior. A regression
test, focused auth tests, production build, fresh login, and profile reuse all
passed. The source-excluded TradingView UDF bundle still returns 404, but the
shell renders while it is absent, proving it is not the shell blocker.

Connector, six-tab, and rendered-widget validation remain tracked by #2101.
Separately, the authoritative Portfolio
launcher reported the exact expected data-path prerequisite blocker: no root
`.env`, so `/portfolio/*` and `/espp/*` require the absent
`MYSQL_HOST`/`MYSQL_USER`/`MYSQL_PASSWORD`/`MYSQL_DATABASE` binding. Discovery,
stock, and API surfaces remained available; no database credentials were
invented.

## Authoritative scripts and contracts

| Script | Mutates state | Contract |
| --- | --- | --- |
| [`setup_self_hosted_workspace.ps1`](../../scripts/setup_self_hosted_workspace.ps1) | Yes | Validate prerequisites/pin, generate ignored local configuration and secrets, install exactly from `bun.lock`. |
| [`run_self_hosted_workspace.ps1`](../../scripts/run_self_hosted_workspace.ps1) | Yes | Build/migrate/start the exact project, initialize users, validate login, and start loopback Vite with owned PID metadata. |
| [`test_self_hosted_workspace.ps1`](../../scripts/test_self_hosted_workspace.ps1) | **No** | Authoritative read-only verification with bounded Docker/Git process-tree cleanup, sanitized errors, and tracked/untracked source checks that permit ignored runtime files. |
| [`stop_self_hosted_workspace.ps1`](../../scripts/stop_self_hosted_workspace.ps1) | Yes | Stop only the recorded frontend PID tree and exact Compose project. |

The replay skill is
[`openbb-workspace-local-server`](../../.agents/skills/openbb-workspace-local-server/SKILL.md).
It chooses these scripts based on observed state. It does not reproduce their
internal commands.

## Generated and ignored runtime files

Setup creates only ignored local state:

| Path relative to `third_party/workspace` | Purpose |
| --- | --- |
| `backend-api/backend/envs/.env.sqlite` | Backend development configuration and generated secrets. |
| `backend-api/backend/workspace-compose.secrets` | Loopback port and read-only admin-config override. |
| `backend-api/backend/workspace-admin-config.secrets` | Initial managed entity/admin input. |
| `backend-api/backend/workspace-admin-credentials.secrets` | Managed login credential used by run/test. |
| `backend-api/backend/local_storage/` | SQLite and folder-storage runtime data. |
| `terminalpro/.env.local` | Disabled hosted integrations and local API URL. |

Frontend PID metadata and sanitized stdout/stderr logs are under the parent
repository's ignored `.dev-cycle/workspace-2110/` directory. `bun.lock` is
tracked and required. `package-lock.json` must remain absent.

## Security controls

- Redis, FastAPI, and Vite publish only on `127.0.0.1`.
- CORS allows exactly `http://127.0.0.1:1420`; `http://localhost:1420` is
  rejected during authoritative preflight validation.
- Registration, hosted AI, Platform, telemetry, and unrelated integrations are
  disabled in generated frontend/backend configuration.
- Secrets use cryptographic random generation and live only in ignored files.
- Scripts never print credentials, tokens, response bodies, environment
  contents, or application data.
- Every verifier Docker/Git command has a finite timeout, captures only required
  bounded stdout, discards diagnostics, and is created suspended before
  assignment to a scoped Windows Job Object. The helper resumes only after
  assignment, then terminates and verifies the exact child process tree on
  every exit path before emitting a fixed sanitized logical failure. No
  PowerShell background job is created.
- Stop validates PID, start time, parentage, and descendant creation time before
  exact-PID termination. It never kills by process name.
- Setup rejects a dirty or unpinned tracked submodule. Test additionally rejects
  unexpected untracked files while Git-ignored runtime files remain permitted.
- Setup refuses to write runtime files unless Git confirms they are ignored.

## Exact validation evidence

The following evidence was recorded on 2026-10-01:

| Validation | Result |
| --- | --- |
| Focused verifier Pester suite | `17 passed, 0 failed`, including executed success, safe executable resolution, nonzero sanitization, timeout/process-tree cleanup, exited-root descendant cleanup, and unexpected-untracked coverage |
| All self-hosted Workspace Pester suites | `54 passed, 0 failed` |
| Setup | Completed; ignored development state generated; frozen Bun install completed |
| Run | Images built; migrations applied; exact services started; admin initialized; frontend started |
| Verifier | `Self-hosted Workspace verification passed: exact services, loopback listeners, health, login, CORS, and source state.` |
| Stop | Exact containers/network removed; owned frontend state removed |
| Post-stop PID state | Absent |
| Tracked `bun.lock` | Present |
| Generated `package-lock.json` | Absent |
| Skill validator | `quick_validate.py`: `Skill is valid!`; eval JSON: 3 schema-valid prompts |

No response bodies, credentials, tokens, environment values, or application
data were captured as evidence.

## Known limitations

- This is a local development stack, not production deployment guidance.
- TradingView assets and hosted OpenBB AI behavior are not locally reproduced.
- Integrated and standalone Workspace MCP operation is not certified here.
- Browser-level parity is separate from script verification and may require
  interactive profile/login handling.
- PowerShell cannot atomically validate and terminate a PID. A narrow reuse race
  remains between the final identity check and exact-PID termination; a Windows
  Job Object launcher would be needed to remove it.
- The verifier is Windows-specific because listener and owned-process checks use
  Windows facilities.
- Skill eval prompts are checked in, but comparative human/model evaluation is
  intentionally deferred; no expensive model loop is evidence for this issue.

## Replay procedure

From a PowerShell 7 repository-root terminal, use only:

```powershell
.\scripts\setup_self_hosted_workspace.ps1
.\scripts\run_self_hosted_workspace.ps1
.\scripts\test_self_hosted_workspace.ps1
```

Open `http://127.0.0.1:1420` only after the verifier passes. For an already
running deployment, run only the verifier. For normal shutdown:

```powershell
.\scripts\stop_self_hosted_workspace.ps1
```

Setup rotates credentials, so do not rerun it for status checks or healthy
restarts.

## Troubleshooting decision tree

1. **Need status/verify only?** Run only `test_self_hosted_workspace.ps1` and
   report its sanitized result; never recover by changing state.
2. **Need stop?** Run only `stop_self_hosted_workspace.ps1`. If Docker is
   unavailable, report that Compose shutdown could not be confirmed, ask the
   operator to start Docker Desktop's Linux engine, and retry stop. Do not run
   setup, rotate credentials, or start services.
3. **Need setup/start/replay and setup is incomplete?** Run setup, then run,
   then test.
4. **Docker unavailable during setup/start/replay?** Report setup's sanitized
   prerequisite failure and ask the operator to start Docker Desktop's Linux
   engine. Never start Docker manually.
5. **PID state already exists during start/replay?** Run stop, then run, then
   test.
6. **Health or exact-state verification fails during start/replay?** Run stop,
   run, and test once.
7. **A checked-in script still fails?** Diagnose only that script's sanitized
   failure with narrow read-only inspection. Do not replace script behavior.
8. **Browser validation blocked but verifier passes?** Record browser validation
   as blocked; do not call browser behavior verified.
9. **Verifier fails?** Status is failed regardless of what the browser or a
   single port appears to show.

## Recovery and cleanup

Use `stop_self_hosted_workspace.ps1` for interrupted launches, stale PID state,
or health recovery. It is idempotent with respect to absent frontend state and
targets the exact Compose project. Never kill Bun, Docker, Node, or Python by
name. Runtime files remain ignored for the next replay; rerun setup only when
configuration must be regenerated or setup is incomplete.

If stop reports Docker unavailable, start Docker Desktop and rerun stop so the
owned Compose project can be removed. If tracked or unexpected untracked
submodule changes exist, do not overwrite them; preserve or intentionally
resolve that work before setup. Ignored runtime files do not make this check
dirty.

## Next issue sequence

1. Merge #2111 and retain this report as the replay source of truth.
2. Execute #2101 hosted UI/browser-harness validation, keeping hosted and local
   verdicts separate.
3. Execute #2102 Workspace Bench and hosted MCP certification.
4. Execute optional #2103 model-proxy validation only with an approved
   loopback model service.
5. Run human comparative evaluation of the three checked-in skill prompts and
   refine the skill if operators find ambiguous recovery behavior.
