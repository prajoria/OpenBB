# Local Workspace development

This runbook covers both the pinned OpenBB Workspace source and the existing
hosted integration path. **`http://127.0.0.1:6120/viewer` is a local preview;
it is not OpenBB Workspace.** Issue #2110 adds and validates a loopback-only
self-hosted development deployment for the pinned source.

Run commands from the repository root in PowerShell 7 unless stated otherwise.
Keep each long-running backend in its own terminal.

## 1. What is local and what remains hosted

| Surface | Location | Purpose |
| --- | --- | --- |
| Self-hosted OpenBB Workspace | `http://127.0.0.1:1420` | Validated local development UI backed by the pinned source and loopback API. |
| OpenBB Workspace source | [`third_party/workspace`](../../third_party/workspace) | Substantial but partial self-host source; Dockerized SQLite development path is validated. |
| Hosted OpenBB Workspace | `https://pro.openbb.co` | Historical hosted integration target. It currently redirects to **BQ Workspace Coming Soon**; retain it only as a record until hosted validation is revisited. |
| Portfolio backend | `https://127.0.0.1:6902` | Local widgets, apps, agent descriptor, and query endpoint. |
| Portfolio Intelligence backend | `http://127.0.0.1:6120` | Local widgets, apps, and API. |
| Portfolio Intelligence viewer | `http://127.0.0.1:6120/viewer` | Local development preview only, not Workspace. |
| Workspace Bench | local process in [`third_party/openbb-workspace-bench`](../../third_party/openbb-workspace-bench) | Deterministic simulator and graders; simulator results do not prove hosted UI parity. |
| OpenBB MCP | `https://backend.openbb.co/mcp` | Hosted bridge used for live surface and parity checks with an operator-issued token. |
| Workspace MCP | integrated backend routes plus standalone package in the pinned source | The integrated self-hosted MCP is certified for the documented surface/parity scope; standalone `workspace_mcp` remains unvalidated. |
| Optional model proxy | `http://127.0.0.1:4141/v1` | Local OpenAI-compatible endpoint used only by Portfolio Copilot. |

The reference repositories are pinned as submodules:

- [OpenBB backend examples](../../third_party/backends-for-openbb)
- [OpenBB agent examples](../../third_party/agents-for-openbb)
- [Workspace Bench](../../third_party/openbb-workspace-bench)
- [OpenBB Workspace source](../../third_party/workspace)

## Source audit (issue #2108)

The audited checkout is pinned at
`be00e95019a55d57af146919ee46b7e1a4859226`. It is Apache-2.0 source containing
the React/Vite frontend (`terminalpro`), FastAPI/SQLAlchemy backend
(`backend-api/backend`), Lite container packaging, Excel add-in, custom backend
and custom-agent support, integrated Workspace MCP routes, and a standalone
`workspace_mcp` package. No nested submodule or Git LFS pointer was found.
TradingView Advanced Charts assets and the hosted OpenBB AI service are not
included, so this is **substantial/partial self-host source**, not a complete
copy of every hosted dependency.

Verify the local source without installing dependencies, creating configuration,
or starting services:

```powershell
git submodule update --init --recursive -- third_party/workspace
git submodule status -- third_party/workspace
git ls-files --stage -- third_party/workspace
git -C third_party/workspace rev-parse HEAD
git -C third_party/workspace status --short
git -C third_party/workspace submodule status --recursive
git -C third_party/workspace grep -Il "version https://git-lfs.github.com/spec/v1"
Test-Path third_party\workspace\backend-api\backend\requirements.txt
Test-Path third_party\workspace\terminalpro\package-lock.json
Test-Path third_party\workspace\terminalpro\bun.lock
```

Expected audit results are a mode-`160000` Gitlink and matching commit hash,
clean submodule status, no recursive submodule or LFS output, `False` for both
`requirements.txt` and `package-lock.json`, and `True` for `bun.lock`. These
commands verify source state only; they do not claim that Workspace builds or
runs.

## Self-hosted SQLite development deployment (issue #2110)

The supported local path uses Docker Desktop's Linux engine for Redis,
FastAPI, RQ, Python 3.13, Alembic, and SQLite. Bun/Vite runs on the Windows
host. Do not install Poetry or Python 3.13 on the host, and do not use the
broken Lite Dockerfile path.

Setup initializes the exact pinned submodule, verifies Docker/Compose/Bun,
generates fresh ignored development secrets, creates a loopback Compose
override, and installs the frontend with the checked-in lockfile:

The durable architecture, evidence, limitations, and recovery record is the
[self-hosted implementation report](workspace-self-hosted-implementation-report.md).
AI-assisted and repeated operation must follow the
[local-server skill](../../.agents/skills/openbb-workspace-local-server/SKILL.md)
and invoke the checked-in scripts instead of reconstructing their commands.

```powershell
.\scripts\setup_self_hosted_workspace.ps1
```

Setup always manages the single local administrator identity
`workspace-admin@example.com`. Its generated password is rotated on every
setup and is never printed. The next run applies that password to the existing
SQLite user, invalidating the prior credentials without modifying other users.
The backend accepts browser origins only from
`http://127.0.0.1:1420`; both CORS middleware and authenticated origin checks
consume that same backend allowlist.

An earlier development version generated a different administrator email on
every setup. The deployment scripts do not delete those historical accounts,
because an email-pattern deletion could remove an operator-created user. The
disposable issue-validation database was reset once during the upgrade instead;
existing non-disposable installations should review and remove only accounts
they can independently confirm were generated by that earlier script.

Start the stack:

```powershell
.\scripts\run_self_hosted_workspace.ps1
```

The launcher applies migrations, starts the exact Compose project
`openbb-workspace-2110`, initializes the local entity and admin idempotently,
checks login without printing its response, and starts Vite bound exactly to
`127.0.0.1:1420`. Use the authoritative read-only verifier; do not replace it
with manual Docker, listener, login, CORS, or health commands:

```powershell
.\scripts\test_self_hosted_workspace.ps1
```

The pinned backend deliberately configures `docs_url=None`; `/docs` returns
404. Use `/health` for API readiness. This is a source contract, not a failed
health check.

Stop only the recorded Vite process tree and owned Compose project:

```powershell
.\scripts\stop_self_hosted_workspace.ps1
```

Descendants are validated by PID, parent PID, and creation time immediately
before exact PID termination; the parent PID/start time is revalidated after
descendant cleanup as well. PowerShell does not provide an atomic
validate-and-terminate primitive, so a narrow PID-reuse race remains between
the final identity check and `Stop-Process`. Eliminating it would require
replacing the host launcher with Windows Job Object ownership. The scripts
never broaden cleanup to process-name termination.

Runtime configuration is ignored under the submodule and PID/log state is
under the parent repository's ignored `.dev-cycle/workspace-2110` directory.
Never print `.env.sqlite`, `.env.local`, the admin credential file, login
responses, or application data. `user_create.json`, SQLite data, and folder
storage also remain ignored.

### Remaining source boundaries

- `lite/Dockerfile` still expects `package-lock.json`; the supported path uses
  `bun install --frozen-lockfile` and never creates that file.
- TradingView Advanced Charts and hosted OpenBB AI are excluded. The local
  frontend disables AI, Platform, telemetry, and registration integrations.
- This is a development deployment, not a production hardening claim.

## 2. One-time setup

The [setup script](../../scripts/setup_workspace_dev.ps1) verifies `git`,
`python`, and `uv`; initializes the three submodules; creates
`.venv_portfolio`; installs local editable packages; checks MySQL; and syncs
Workspace Bench:

```powershell
.\scripts\setup_workspace_dev.ps1
```

Install Playwright Chromium at the same time when hosted browser checks are
needed:

```powershell
.\scripts\setup_workspace_dev.ps1 -InstallBrowser
```

After packages are already installed, rerun the non-destructive preflight with:

```powershell
.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall
```

The setup requires MySQL to have an **exact** listener on
`127.0.0.1:3306`. See [port 3306 troubleshooting](#port-3306-mysql) before
running setup on this machine.

## 3. Required ignored configuration

Database-backed Portfolio and ESPP routes read a root `.env`. It is ignored by
Git. Create it interactively without printing the password:

```powershell
$mysqlUser = Read-Host "MySQL application user"
$mysqlPassword = Read-Host -MaskInput "MySQL application password"
$mysqlDatabase = Read-Host "MySQL database name"
@(
    "MYSQL_HOST=127.0.0.1"
    "MYSQL_PORT=3306"
    "MYSQL_USER=$mysqlUser"
    ("{0}={1}" -f "MYSQL_PASSWORD", $mysqlPassword)
    "MYSQL_DATABASE=$mysqlDatabase"
) | Set-Content .env -Encoding utf8NoBOM
Remove-Variable mysqlPassword

git check-ignore -v .env
```

Do not paste credentials into commands, transcripts, issues, or this document.
The backend can still serve non-database market-data routes when `.env` is
absent.

The Portfolio launcher generates `portfolio_app/cert.pem` and
`portfolio_app/key.pem` on first use. Both files and `.env` must remain
untracked. Browser profiles and benchmark run artifacts are also local-only.

## 4. Start Portfolio backend

Use the existing [Portfolio launcher](../../scripts/run_portfolio_backend.ps1):

```powershell
.\scripts\run_portfolio_backend.ps1
```

It installs dependencies when needed, generates a self-signed loopback
certificate, and binds HTTPS to `127.0.0.1:6902`. For subsequent starts:

```powershell
.\scripts\run_portfolio_backend.ps1 -SkipInstall
```

Never change the binding to `0.0.0.0`. Keep this terminal open.

## 5. Start Portfolio Intelligence and local viewer

In a second terminal, use the
[Portfolio Intelligence launcher](../../scripts/run_widget_backend.ps1):

```powershell
.\scripts\run_widget_backend.ps1
```

The default `loopback-dev` authentication mode is allowed only because the
launcher binds to `127.0.0.1:6120`. Use `-Reload` during source development:

```powershell
.\scripts\run_widget_backend.ps1 -Reload
```

For explicit bearer authentication, read a token without echoing it:

```powershell
$token = Read-Host -MaskInput "Portfolio Intelligence bearer token"
$env:PI_WIDGET_BACKEND_TOKEN = $token
Remove-Variable token
try {
    .\scripts\run_widget_backend.ps1 `
        -AuthMode required `
        -Token $env:PI_WIDGET_BACKEND_TOKEN
} finally {
    Remove-Item Env:PI_WIDGET_BACKEND_TOKEN -ErrorAction SilentlyContinue
}
```

The preview is `http://127.0.0.1:6120/viewer`. It helps inspect local widget
behavior, but it is not the hosted Workspace application.

## 6. Connect Workspace to both loopback services

First visit `https://127.0.0.1:6902/widgets.json` in the same browser profile
used for Workspace and explicitly accept the self-signed development
certificate warning.

Then open Workspace and use **Connections → Connect Backend**:

| Name | URL |
| --- | --- |
| Portfolio Local | `https://127.0.0.1:6902` |
| Portfolio Intelligence Local | `http://127.0.0.1:6120` |

The Workspace page calls loopback services through the browser; the services
remain local. Confirm that Portfolio Overview exposes Overview, Positions,
Cost Basis & Tax, Trends, ESPP, and Stock Analysis. Confirm that a Portfolio
Intelligence widget requests the `6120` origin.

Issue #2101 acceptance on 2026-10-02 used the hardened persistent-profile
`WorkspaceDriver` against `http://127.0.0.1:1420` with development TLS bypass
enabled only for that exact self-hosted Workspace URL. It validated both
connector names and origins, rendered all six Portfolio Overview tab names,
opened Portfolio Intelligence - Overview, rendered a widget, and observed
`GET http://127.0.0.1:6120/pi/xray/sector` return HTTP 200. Evidence contained
only control/tab names and origin/path/status metadata.

The acceptance run also fixed two browser-integration contracts. Discovery
responses now send `Cache-Control: no-store`, preventing the required direct
TLS trust visit from poisoning a later cross-origin manifest fetch in the
persistent profile. Portfolio Intelligence now allows the exact self-hosted
Workspace origin in addition to the hosted origin, and its three explicit app
IDs use the pinned Workspace `custom-` prefix contract.

## 7. Run privacy-safe smoke checks

With both backends running, execute the
[smoke checker](../../scripts/test_workspace_dev.ps1):

```powershell
.\scripts\test_workspace_dev.ps1 -SkipCertificateCheck
```

`-SkipCertificateCheck` is an explicit opt-in for the self-signed Portfolio
certificate. Omit it when the certificate is trusted by PowerShell. The
checker prints only the number of entries in five discovery surfaces:
Portfolio widgets, apps, and agents plus Portfolio Intelligence widgets and
apps. It fails on an empty surface and never prints response rows, financial
values, secrets, tokens, or credentials.

## 8. Create or reuse the Playwright Workspace profile

Install Chromium if it was not installed during initial setup:

```powershell
.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall -InstallBrowser
```

Start the opt-in hosted test:

```powershell
$env:RUN_WORKSPACE_HARNESS = "1"
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\tools\browser_test_harness\tests\test_workspace_driver.py -v
Remove-Item Env:RUN_WORKSPACE_HARNESS
```

Only an exact `http://127.0.0.1:1420` target (with an optional trailing slash)
enables managed login. `WorkspaceDriver` verifies that the live page remains
on that exact origin after navigation and immediately before credential
access, then reads the ignored
`third_party/workspace/backend-api/backend/workspace-admin-credentials.secrets`
file directly, fills the source-backed Email and Password fields, and never
prints or accepts those values as command-line arguments. The first run opens
Chromium visibly and logs in automatically. Later runs reuse
`$HOME\.openbb_browser_test_harness\chrome_profile`; do not copy, inspect,
archive, or commit that profile. Hosted Workspace continues to require
operator-managed authentication. Local profile reuse is accepted only on the
exact origin's `/app` route family; authentication routes and external routes
are rejected. The narrowly named
`ignore_local_self_hosted_https_errors=True` option is likewise rejected for
hosted or non-exact Workspace URLs. See the browser harness
[Workspace-mode contract](../../openbb_platform/tools/browser_test_harness/docs/workspace-mode.md).

Issue #2101 validation on 2026-10-02 proved both first-run managed login and a
second run that reused the profile without submitting the login form. The
authoritative self-hosted verifier remained healthy. Issue #2115 then fixed the
empty authenticated `/app` shell in `prajoria/workspace` PR #1: on-prem login
had incorrectly required hosted onboarding data, causing `AuthGuard` to return
`null`. The fixed source renders the app layout after both fresh login and
profile reuse. The source-excluded TradingView UDF bundle still returns 404 but
does not block the shell. The same #2101 acceptance subsequently validated
both loopback connectors, all six Portfolio Overview tabs, and a rendered
Portfolio Intelligence widget request to the 6120 origin.

## 9. Run deterministic Workspace Bench evaluations

Validate all bundled tasksets before any model-backed or live run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run workspace-bench validate --taskset smoke --min-tasks 80
    uv run workspace-bench validate --taskset enterprise-apps-default --min-tasks 138
    uv run workspace-bench validate --taskset workspace-tasks --min-tasks 120

    $oracleOutput = & uv run workspace-bench run `
      --task workspace-tasks/portfolio_manager/morning_briefing_level0 `
      --agent oracle `
      --json
    $oracleExit = $LASTEXITCODE
    $oracleResult = $oracleOutput | ConvertFrom-Json
    if (
        $oracleExit -ne 0 -or
        $oracleResult.summary.total -ne 1 -or
        $oracleResult.summary.passed -ne 1 -or
        -not $oracleResult.results[0].passed
    ) {
        throw "Workspace Bench oracle did not return the required passing result."
    }

    $noopOutput = & uv run workspace-bench run `
      --task workspace-tasks/portfolio_manager/morning_briefing_level0 `
      --agent noop `
      --json
    $noopExit = $LASTEXITCODE
    $noopResult = $noopOutput | ConvertFrom-Json
    if (
        $noopExit -ne 1 -or
        $noopResult.summary.total -ne 1 -or
        $noopResult.summary.failed -ne 1 -or
        $noopResult.results[0].passed
    ) {
        throw "Workspace Bench no-op did not return the required failing result."
    }
} finally {
    Pop-Location
}
```

The CLI contract is exit code `0` plus a passing JSON result for the oracle,
and exit code `1` plus a failing JSON result for the no-op. The explicit checks
make an unexpected oracle failure or unexpected no-op success fail the
procedure. These runs prove that the grader separates valid behavior from no
action. They use a simulator; they are not evidence that the hosted UI behaves
identically. Keep generated run artifacts and response transcripts out of Git.

## 10. Run self-hosted MCP surface and parity checks

First use the hardened persistent browser profile to open
`http://127.0.0.1:1420`, enable **Workspace MCP Companion**, and keep that tab
open. Self-hosted setup enables that companion control in the local frontend
configuration. The integrated endpoint is `http://127.0.0.1:8000/mcp`.

Use the checked-in wrapper to create one short-lived user-scoped token from the
ignored managed administrator credential, expose it only to one child process,
and revoke it in `finally`. The wrapper logs in with the isolated `excel`
session source; using `source=pro` would invalidate the browser's authenticated
Pro session. A named cross-process lock serializes this managed identity's full
login/create/child/revoke/logout lifecycle so concurrent wrappers cannot
invalidate each other's cleanup sessions. It never reads browser cookies or
profile files.

`$WorkspaceDeploymentRoot` must be the worktree that owns the verified running
deployment. These are the exact certification replay commands; do not add
`--update-baseline` because `runs/hosted-surface` is the retained hosted
contract, not a self-host capture:

```powershell
$WorkspaceDeploymentRoot = (Resolve-Path ".").Path
$BenchRoot = Join-Path $PWD "third_party\openbb-workspace-bench"
$ReadOnlyTask = (
  "smoke/list_available_widgets/" +
  "smoke_list_available_widgets_level0"
)

.\scripts\invoke_workspace_mcp_command.ps1 `
  -WorkspaceRoot $WorkspaceDeploymentRoot `
  -WorkingDirectory $BenchRoot `
  -FilePath uv `
  -ChildTimeoutSeconds 180 `
  -ArgumentList @(
    "run", "--extra", "live", "python",
    "scripts\audits\audit_hosted_surface.py"
  )

.\scripts\invoke_workspace_mcp_command.ps1 `
  -WorkspaceRoot $WorkspaceDeploymentRoot `
  -WorkingDirectory $BenchRoot `
  -FilePath uv `
  -ChildTimeoutSeconds 180 `
  -ArgumentList @(
    "run", "--extra", "live", "workspace-bench", "live-parity",
    "--task", $ReadOnlyTask,
    "--url", "http://127.0.0.1:8000/mcp"
  )

# A second bridge-backed replay starts only after the first wrapper invocation
# revoked its MCP token and deleted its isolated automation login session.
# Success proves the browser's source=pro bridge session stayed connected.
.\scripts\invoke_workspace_mcp_command.ps1 `
  -WorkspaceRoot $WorkspaceDeploymentRoot `
  -WorkingDirectory $BenchRoot `
  -FilePath uv `
  -ChildTimeoutSeconds 180 `
  -ArgumentList @(
    "run", "--extra", "live", "workspace-bench", "live-parity",
    "--task", $ReadOnlyTask,
    "--url", "http://127.0.0.1:8000/mcp"
  )
```

The selected parity task is on the explicit read-only no-dashboard allowlist
and creates no Workspace artifacts. Navigation or mutating traces always seed
an isolated marker dashboard even when their task has no initial dashboard.
Delete its generated `parity.json` after recording only the sanitized grade
counts. Never commit response transcripts, credentials, cookies, or token
values. Do not install PyPI `workspace-mcp`; that unrelated package serves
Google Workspace.

The surface audit always compares with the original hosted baselines under
`runs/hosted-surface`. A schema result of zero compatibility issues is distinct
from resource-descriptor equality; report either independently. Self-host
captures belong in session evidence, not `runs/hosted-surface`.

## 11. Enable the optional Portfolio Copilot

Agent discovery is part of the port `6902` smoke check. To use the agent,
provide an approved loopback OpenAI-compatible service. The implementation
defaults are:

```text
COPILOT_PROXY_BASE_URL=http://127.0.0.1:4141/v1
COPILOT_PROXY_API_KEY=copilot
COPILOT_PROXY_MODEL=gpt-4o
```

The API key shown is the local proxy's documented placeholder, not a hosted
credential. If GitHub Copilot proxying is intended, initialize the existing
[`copilot-api`](../../copilot-api) submodule and follow its documentation:

```powershell
git submodule update --init --recursive copilot-api
```

Otherwise set the three process environment variables for an approved
loopback model server. Start only after the server reports an available model.
In Workspace, add agent endpoint `https://127.0.0.1:6902`, select **Portfolio
Copilot (local proxy)**, and verify a non-advisory streamed response.

## 12. Troubleshooting ports 3306, 6120, 6902, 4141, and TLS trust

List loopback and wildcard listeners without exposing process environment or
credentials:

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 3306, 6120, 6902, 4141 |
    Sort-Object LocalPort, LocalAddress |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Ports `6120`, `6902`, and `4141` must be free before their respective local
services start. Use the reported PID to identify an unexpected owner:

```powershell
Get-Process -Id <OwningProcess>
```

Stop a process only after confirming it is the process you started. Prefer
`Ctrl+C` in its terminal.

### Port 3306 (MySQL)

On this machine, MySQL currently listens on the IPv6 wildcard
**`[::]:3306`**. The setup contract intentionally requires the exact IPv4
loopback listener **`127.0.0.1:3306`**, so setup will fail until corrected.
Do not weaken the setup check and do not expose MySQL on `0.0.0.0`.

Verify the current state:

```powershell
$mysqlListeners = Get-NetTCPConnection -State Listen -LocalPort 3306 |
    Select-Object LocalAddress, LocalPort, OwningProcess
$mysqlListeners
if (-not ($mysqlListeners.LocalAddress -contains "127.0.0.1")) {
    Write-Warning "MySQL lacks the required exact 127.0.0.1:3306 listener."
}
```

Correct it safely:

1. From the listener's `OwningProcess`, identify the Windows service without
   displaying its command line or environment:

   ```powershell
   $mysqlPid = ($mysqlListeners | Select-Object -First 1).OwningProcess
   $mysqlService = Get-CimInstance Win32_Service |
       Where-Object ProcessId -eq $mysqlPid |
       Select-Object -First 1
   if (-not $mysqlService) {
       throw "No Windows service owns the selected MySQL listener process."
   }
   $mysqlService | Select-Object Name, DisplayName, State
   ```

2. In an elevated editor, back up that service's active MySQL option file
   (commonly under `%PROGRAMDATA%\MySQL\`) and set the server option
   `bind-address=127.0.0.1` in the `[mysqld]` section. Do not add usernames or
   passwords to the option file, shell history, or this repository. Consult
   the installed service documentation if its active option-file location is
   unclear; do not guess or edit multiple files.
3. Restart only the service identified above:

   ```powershell
   Restart-Service -Name $mysqlService.Name
   ```

4. Repeat the listener query. Proceed only when it includes exactly
   `127.0.0.1:3306` and no wildcard listener (`::` or `0.0.0.0`) remains.
   Then rerun `.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall`.

This network correction does not require database credentials and must not
change the application user's password.

### TLS trust on port 6902

Use a browser-only trust exception for the generated development certificate,
or run the smoke checker with its explicit `-SkipCertificateCheck` switch.
Never disable certificate validation globally. If trust becomes stale, stop
the backend, delete only the ignored generated `portfolio_app\cert.pem` and
`portfolio_app\key.pem`, restart the launcher, and accept the new certificate
in the Workspace browser profile.

## 13. Shutdown procedure

1. Press `Ctrl+C` in the Portfolio Intelligence terminal.
2. Press `Ctrl+C` in the Portfolio backend terminal.
3. Stop the optional port `4141` proxy using its documented shutdown command.
4. Close Playwright Chromium after a harness run has completed.
5. Stop the self-hosted Workspace through its authoritative owner:

   ```powershell
   .\scripts\stop_self_hosted_workspace.ps1
   ```

6. Remove process-only sensitive variables:

   ```powershell
   Remove-Item Env:WORKSPACE_MCP_TOKEN -ErrorAction SilentlyContinue
   Remove-Item Env:WORKSPACE_MCP_URL -ErrorAction SilentlyContinue
   Remove-Item Env:PI_WIDGET_BACKEND_TOKEN -ErrorAction SilentlyContinue
   Remove-Item Env:COPILOT_PROXY_API_KEY -ErrorAction SilentlyContinue
   ```

7. Confirm development listeners are gone:

   ```powershell
   Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
       Where-Object LocalPort -In 6120, 6902, 4141 |
       Select-Object LocalAddress, LocalPort, OwningProcess
   ```

MySQL can remain running on the required exact loopback binding.

## 14. Security and data-handling cautions

- Bind development backends, MySQL, and model proxies only to `127.0.0.1`.
- Never commit `.env`, PEM files, browser profiles, tokens, credentials,
  benchmark transcripts, screenshots containing account data, or raw financial
  data.
- Never print discovery response bodies. The smoke checker reports counts only.
- Read passwords and tokens with `Read-Host -MaskInput`; clear process
  variables after use.
- Do not treat the local viewer or benchmark simulator as the hosted Workspace.
- Use the hosted OpenBB MCP endpoint only with an operator-issued token.
- Do not install PyPI `workspace-mcp`; it is Google Workspace software, not the
  integrated or standalone MCP implementation in the pinned Workspace source.
- Before committing, inspect `git status --short`, run `git diff --check`, and
  scan the intended paths for credential patterns.
