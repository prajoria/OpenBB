# Local OpenBB Workspace Development Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a repeatable Windows development workflow that runs the portfolio backends, local viewer, custom agent, Workspace Bench, and the pinned Workspace source on this machine, with staged validation of both self-hosted and hosted integration paths.

**Architecture:** The pinned [`third_party/workspace`](../../../third_party/workspace) source provides a substantial but partial self-host path: audit the source and build contracts first, then provision and build it in a supported Linux container environment, deploy it with Docker Desktop/WSL2, and only then perform runtime validation. The existing hosted path at `https://pro.openbb.co` remains a separate integration target and historical fallback; it is not evidence that the pinned source builds or runs. Local portfolio processes continue to provide the Portfolio backend on `https://127.0.0.1:6902`, Portfolio Intelligence and its local viewer on `http://127.0.0.1:6120`, an optional OpenAI-compatible model proxy on `http://127.0.0.1:4141`, and deterministic Workspace Bench evaluations. Workspace MCP validation can eventually use the integrated or standalone implementation in the pinned source after self-host deployment is proven; hosted automation still requires the hosted endpoint and an operator-issued token.

**Tech Stack:** Windows 11, PowerShell 7.4, Git submodules, Docker Desktop/WSL2, Python 3.12 for portfolio services, Poetry with Python ~3.13 for Workspace, Bun/Vite, FastAPI/Uvicorn, Redis/RQ, MySQL 8 on `127.0.0.1:3306`, Playwright Chromium, OpenBB Workspace, Workspace Bench.

## Global Constraints

- Distinguish the hosted UI at `https://pro.openbb.co` from the unvalidated self-host source; do not claim either local build or deployment works before runtime validation.
- Use Docker Desktop/WSL2 as the self-host deployment target; Windows-native production is unsupported.
- Bind every development service to `127.0.0.1`; never expose portfolio services on `0.0.0.0`.
- Keep raw financial data, account identifiers, API keys, database credentials, MCP tokens, and model-provider credentials out of Git and command output.
- Use the existing `.venv_portfolio` for local OpenBB packages and let `uv` manage the isolated Workspace Bench environment.
- Use `https://127.0.0.1:6902` for the Portfolio backend and `http://127.0.0.1:6120` for Portfolio Intelligence.
- Run Portfolio Intelligence with `PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev` only while bound to loopback.
- Do not install the PyPI package named `workspace-mcp`; version `1.30.1` is a Google Workspace MCP server, not the OpenBB Workspace sidecar.
- Do not use simulator results as evidence of live Workspace UI parity.
- Preserve the user-modified `notebooks/portfolio/02-single-name-deep-dive.ipynb`.
- Do not commit `.env`, generated TLS keys, browser profiles, MCP tokens, benchmark response transcripts, or real portfolio data.

---

## GitHub Delivery Sequence

**Program epic:** [#2096 Local OpenBB Workspace development environment](https://github.com/prajoria/OpenBB/issues/2096)
**Project board:** [Portfolio Intelligence Engine — Board](https://github.com/users/prajoria/projects/4/views/2)
**Integration branch:** `portfolio`

Work is strictly sequential. Each issue starts only after the preceding issue is
verified, reviewed, merged to `portfolio`, and marked Done.

| Order | Issue | Deliverable | Branch | Project fields |
| --- | --- | --- | --- | --- |
| 1 | [#2097](https://github.com/prajoria/OpenBB/issues/2097) | Pin reference repositories and this execution plan | `chore/workspace-dev-foundation-gh-2097` | M0 / PM / Task |
| 2 | [#2098](https://github.com/prajoria/OpenBB/issues/2098) | Idempotent Windows setup preflight | `build/workspace-dev-setup-gh-2098` | P0 / D-Widgets+QA / Feature |
| 3 | [#2099](https://github.com/prajoria/OpenBB/issues/2099) | Portfolio Intelligence launcher | `feat/workspace-intel-launcher-gh-2099` | P0 / D-Widgets+QA / Feature |
| 4 | [#2100](https://github.com/prajoria/OpenBB/issues/2100) | Privacy-safe smoke checks and operator runbook | `docs/workspace-dev-runbook-gh-2100` | P0 / QA / Feature |
| 5 | [#2108](https://github.com/prajoria/OpenBB/issues/2108) | Pin and audit self-hosted Workspace source | `chore/self-hosted-workspace-source-gh-2108` | P1 / Workspace+Tools / Task |
| 6 | [#2110](https://github.com/prajoria/OpenBB/issues/2110) | Deploy self-hosted Workspace development stack | `feat/self-hosted-workspace-deploy-gh-2110` | P1 / Workspace+Tools / Feature |
| 7 | [#2111](https://github.com/prajoria/OpenBB/issues/2111) | Add authoritative verifier, report, and replay skill | `feat/workspace-replay-skill-gh-2111` | P1 / Workspace+Tools / Feature |
| 8 | [#2101](https://github.com/prajoria/OpenBB/issues/2101) | Hosted Workspace and browser-harness validation | `test/workspace-hosted-browser-gh-2101` | P1 / QA / Task |
| 9 | [#2102](https://github.com/prajoria/OpenBB/issues/2102) | Workspace Bench and hosted MCP certification | `test/workspace-bench-mcp-gh-2102` | P1 / QA / Task |
| 10 | [#2103](https://github.com/prajoria/OpenBB/issues/2103) | Optional Portfolio Copilot proxy validation | `test/workspace-copilot-proxy-gh-2103` | P1 / B-Analytics / Task |

For each issue:

1. Update the project item from **Todo** to **In Progress**.
2. Synchronize `portfolio` with `origin/portfolio`.
3. Create the issue's exact branch from the synchronized integration branch.
4. Implement only the files listed in the issue.
5. Run the issue's targeted validation commands.
6. Review the diff for secrets, unrelated changes, and worktree contamination.
7. Commit with `Closes #<issue>` and the required Copilot co-author trailer.
8. Push the branch and open a PR to `portfolio`.
9. Wait for required CI and review checks; correct failures on the same branch.
10. Merge the PR, update the project item to **Done**, then begin the next issue.

---

## Current Machine Baseline

| Capability | Current state |
| --- | --- |
| Python | `3.12.10`, supported by local OpenBB packages and Workspace Bench |
| `uv` | `0.11.26` installed |
| PowerShell | `7.4.20` installed |
| Node | `24.17.0` installed |
| Docker CLI | Docker Desktop Linux engine `29.5.3`; required by the self-host deployment |
| Bun | installed; frontend dependencies use checked-in `bun.lock` |
| MySQL | `mysqld` is listening on port `3306` |
| Portfolio venv | `.venv_portfolio` exists |
| Root `.env` | absent |
| Portfolio TLS certificate | absent; the existing launch script generates it |
| Workspace browser profile | absent; first live browser run requires interactive login |
| Ollama | installed, with no models currently present |
| Self-hosted Workspace | Dockerized SQLite backend and Bun/Vite frontend validated by #2110 on loopback |
| Workspace MCP | integrated route starts with the backend; standalone package certification remains separate |

## File Structure

- Modify: `.gitmodules` — records the three OpenBB reference/evaluation repositories.
- Add: `third_party/backends-for-openbb` — pinned backend examples submodule.
- Add: `third_party/agents-for-openbb` — pinned custom-agent examples submodule.
- Add: `third_party/openbb-workspace-bench` — pinned benchmark submodule.
- Add: `third_party/workspace` — pinned substantial/partial Workspace self-host source, audited before any build or deployment attempt.
- Create: `scripts/setup_workspace_dev.ps1` — idempotent machine/environment preflight and dependency setup.
- Create: `scripts/run_widget_backend.ps1` — supported Portfolio Intelligence launcher for port `6120`.
- Create: `scripts/test_workspace_dev.ps1` — endpoint and manifest smoke checks without printing response data.
- Create: `scripts/setup_self_hosted_workspace.ps1` — secure ignored runtime configuration and locked Bun setup.
- Create: `scripts/run_self_hosted_workspace.ps1` — SQLite Compose lifecycle, bootstrap, login, and Vite launcher.
- Create: `scripts/test_self_hosted_workspace.ps1` — non-mutating exact-state, health, login, CORS, source, ignore, and lockfile verifier.
- Create: `scripts/stop_self_hosted_workspace.ps1` — exact PID-tree and Compose-project shutdown.
- Create: `.agents/skills/openbb-workspace-local-server/SKILL.md` — script-only state-aware replay and recovery contract.
- Create: `docs/operations/workspace-self-hosted-implementation-report.md` — durable implementation and evidence record.
- Create: `docs/operations/workspace-local-development.md` — operator runbook with local-only, hosted-integration, agent, and benchmark modes.
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/README.md` — replace stale launcher instructions with the supported script.

### Task 1: Pin and verify the side repositories

**Files:**
- Modify: `.gitmodules`
- Add: `third_party/backends-for-openbb`
- Add: `third_party/agents-for-openbb`
- Add: `third_party/openbb-workspace-bench`

**Interfaces:**
- Consumes: Git submodule support and the `prajoria` GitHub forks.
- Produces: reproducible source pins available to documentation, tests, and developers.

- [ ] **Step 1: Verify the staged submodule definitions**

Run:

```powershell
git diff --cached -- .gitmodules
git submodule status third_party/backends-for-openbb third_party/agents-for-openbb third_party/openbb-workspace-bench
```

Expected pins:

```text
third_party/backends-for-openbb       a6293707576e16edda8305adda95b07b6a4b968b
third_party/agents-for-openbb         aa1073d2b098ae6cf597dabf0635822aa808dd81
third_party/openbb-workspace-bench    b11572b59b7a5722e4c4ec60676d7613c1b05ac5
```

- [ ] **Step 2: Verify a clean-clone initialization path**

Run:

```powershell
git submodule sync -- `
  third_party/backends-for-openbb `
  third_party/agents-for-openbb `
  third_party/openbb-workspace-bench
git submodule update --init --recursive -- `
  third_party/backends-for-openbb `
  third_party/agents-for-openbb `
  third_party/openbb-workspace-bench
```

Expected: all three commands exit `0`; no submodule has a leading `-` in `git submodule status`.

- [ ] **Step 3: Confirm the parent worktree did not absorb submodule contents**

Run:

```powershell
git ls-files --stage third_party/backends-for-openbb third_party/agents-for-openbb third_party/openbb-workspace-bench
```

Expected: three entries with mode `160000`.

- [ ] **Step 4: Commit only the submodule pins**

```powershell
git add .gitmodules third_party/backends-for-openbb third_party/agents-for-openbb third_party/openbb-workspace-bench
git commit -m "chore: add OpenBB Workspace reference submodules" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add an idempotent Workspace development setup script

**Files:**
- Create: `scripts/setup_workspace_dev.ps1`

**Interfaces:**
- Consumes: `.venv_portfolio`, local editable package directories, MySQL on port `3306`, and the three initialized submodules.
- Produces: a validated Python environment containing the Portfolio backend, Portfolio Intelligence backend, browser harness, and Playwright dependency.

- [ ] **Step 1: Write the setup script**

Create `scripts/setup_workspace_dev.ps1` with this behavior:

```powershell
#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [switch]$InstallBrowser,
    [switch]$SkipPackageInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv_portfolio\Scripts\python.exe"
$requiredCommands = @("git", "python", "uv")

foreach ($command in $requiredCommands) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $command"
    }
}

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $repoRoot ".venv_portfolio")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv_portfolio"
    }
}

git -C $repoRoot submodule update --init --recursive -- `
    third_party/backends-for-openbb `
    third_party/agents-for-openbb `
    third_party/openbb-workspace-bench
if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize Workspace development submodules"
}

if (-not $SkipPackageInstall) {
    $editablePackages = @(
        "openbb_platform\core",
        "openbb_platform\extensions\platform_api",
        "openbb_platform\extensions\backtest",
        "openbb_platform\extensions\techtrade",
        "openbb_platform\extensions\portfolio",
        "openbb_platform\extensions\portfolio_intel",
        "openbb_platform\tools\browser_test_harness[workspace,test]"
    )
    $pipArgs = @("-m", "pip", "install", "--upgrade", "pip")
    & $python @pipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip"
    }

    $installArgs = @("-m", "pip", "install")
    foreach ($package in $editablePackages) {
        $installArgs += @("-e", (Join-Path $repoRoot $package))
    }
    $installArgs += "cryptography"
    & $python @installArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install local Workspace development packages"
    }
}

$mysql = Get-NetTCPConnection -State Listen -LocalPort 3306 -ErrorAction SilentlyContinue
if (-not $mysql) {
    throw "MySQL is not listening on 127.0.0.1:3306"
}

$envPath = Join-Path $repoRoot ".env"
if (-not (Test-Path $envPath)) {
    Write-Warning ".env is absent. Portfolio and ESPP routes will not have database credentials."
}

Push-Location (Join-Path $repoRoot "third_party\openbb-workspace-bench")
try {
    uv sync --extra dev --extra live
    if ($LASTEXITCODE -ne 0) {
        throw "Workspace Bench dependency sync failed"
    }
} finally {
    Pop-Location
}

if ($InstallBrowser) {
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright Chromium installation failed"
    }
}

Write-Host "Workspace development prerequisites are ready." -ForegroundColor Green
```

- [ ] **Step 2: Run the setup without browser installation**

Run:

```powershell
.\scripts\setup_workspace_dev.ps1
```

Expected: editable installs and `uv sync` succeed; the only permitted warning is the missing root `.env`.

- [ ] **Step 3: Run the idempotence path**

Run:

```powershell
.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall
```

Expected: submodule, MySQL, and Workspace Bench checks pass without reinstalling the local OpenBB packages.

- [ ] **Step 4: Commit the setup script**

```powershell
git add scripts/setup_workspace_dev.ps1
git commit -m "build: add Workspace development setup" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add the missing Portfolio Intelligence launcher

**Files:**
- Create: `scripts/run_widget_backend.ps1`
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/README.md`

**Interfaces:**
- Consumes: `.venv_portfolio`, installed `openbb_portfolio_intel`, and `PI_WIDGET_BACKEND_AUTH_MODE`.
- Produces: Portfolio Intelligence discovery, widget APIs, apps, and local viewer on `http://127.0.0.1:6120`.

- [ ] **Step 1: Write the launcher**

Create `scripts/run_widget_backend.ps1`:

```powershell
#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [int]$Port = 6120,
    [switch]$Reload,
    [ValidateSet("loopback-dev", "required")]
    [string]$AuthMode = "loopback-dev",
    [string]$Token
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv_portfolio\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw ".venv_portfolio is absent. Run scripts/setup_workspace_dev.ps1 first."
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use."
}
if ($AuthMode -eq "required" -and [string]::IsNullOrWhiteSpace($Token)) {
    throw "-Token is required when -AuthMode required."
}

$env:PI_WIDGET_BACKEND_AUTH_MODE = $AuthMode
if ($AuthMode -eq "required") {
    $env:PI_WIDGET_BACKEND_TOKEN = $Token
} else {
    Remove-Item Env:PI_WIDGET_BACKEND_TOKEN -ErrorAction SilentlyContinue
}

$arguments = @(
    "-m", "uvicorn",
    "openbb_portfolio_intel.widget_backend.main:app",
    "--host", "127.0.0.1",
    "--port", "$Port"
)
if ($Reload) {
    $arguments += "--reload"
}

Push-Location (Join-Path $repoRoot "openbb_platform\extensions\portfolio_intel")
try {
    & $python @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
```

- [ ] **Step 2: Replace the stale README command**

Document these supported commands in the backend README:

```powershell
# Loopback-only development:
.\scripts\run_widget_backend.ps1

# Auto-reload:
.\scripts\run_widget_backend.ps1 -Reload

# Explicit bearer authentication:
$token = Read-Host -MaskInput "Portfolio Intelligence bearer token"
.\scripts\run_widget_backend.ps1 -AuthMode required -Token $token
```

State that the local viewer is `http://127.0.0.1:6120/viewer`, while the real Workspace UI remains `https://pro.openbb.co`.

- [ ] **Step 3: Run the existing backend unit tests**

Run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\extensions\portfolio_intel\tests\unit\test_widget_backend.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Launch and probe Portfolio Intelligence**

In terminal A:

```powershell
.\scripts\run_widget_backend.ps1
```

In terminal B:

```powershell
$widgets = Invoke-RestMethod http://127.0.0.1:6120/widgets.json
$apps = Invoke-RestMethod http://127.0.0.1:6120/apps.json
if ($widgets.PSObject.Properties.Count -lt 1) { throw "No widgets discovered" }
if (@($apps).Count -lt 1) { throw "No apps discovered" }
```

Expected: both checks pass without printing portfolio response bodies.

- [ ] **Step 5: Commit the launcher and corrected documentation**

```powershell
git add scripts/run_widget_backend.ps1 openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/README.md
git commit -m "feat: add Portfolio Intelligence launcher" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Configure local secrets and start both backend surfaces

**Files:**
- Runtime only: `.env`
- Runtime only: `portfolio_app/cert.pem`
- Runtime only: `portfolio_app/key.pem`

**Interfaces:**
- Consumes: MySQL credentials, Portfolio launch script, Portfolio Intelligence launch script.
- Produces: Portfolio backend at `https://127.0.0.1:6902` and Portfolio Intelligence at `http://127.0.0.1:6120`.

- [ ] **Step 1: Create `.env` without echoing its values**

Run interactively:

```powershell
$mysqlUser = Read-Host "MySQL application user"
$mysqlPassword = Read-Host -MaskInput "MySQL application password"
$mysqlDatabase = Read-Host "MySQL database name"
@(
    "MYSQL_HOST=127.0.0.1"
    "MYSQL_PORT=3306"
    "MYSQL_USER=$mysqlUser"
    "MYSQL_PASSWORD=$mysqlPassword"
    "MYSQL_DATABASE=$mysqlDatabase"
) | Set-Content .env -Encoding utf8NoBOM
```

Expected: `.env` exists and remains ignored by Git.

- [ ] **Step 2: Confirm Git does not track secrets**

Run:

```powershell
git check-ignore -v .env
git status --short
```

Expected: `.env` is reported as ignored and does not appear in `git status`.

- [ ] **Step 3: Start the Portfolio backend**

In terminal A:

```powershell
.\scripts\run_portfolio_backend.ps1
```

Expected: the script creates the self-signed certificate if needed and listens on `https://127.0.0.1:6902`.

- [ ] **Step 4: Start Portfolio Intelligence**

In terminal B:

```powershell
.\scripts\run_widget_backend.ps1
```

Expected: Uvicorn listens on `http://127.0.0.1:6120`.

- [ ] **Step 5: Trust the generated loopback certificate**

Open `https://127.0.0.1:6902/widgets.json` in the same browser profile used for Workspace and accept the self-signed development certificate warning.

Expected: the browser displays the widget manifest after the one-time trust action.

### Task 5: Add a privacy-safe smoke checker

**Files:**
- Create: `scripts/test_workspace_dev.ps1`

**Interfaces:**
- Consumes: running local services.
- Produces: pass/fail evidence for discovery manifests and agent registration without logging widget data.

- [ ] **Step 1: Write the smoke checker**

Create `scripts/test_workspace_dev.ps1`:

```powershell
#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [switch]$SkipCertificateCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$portfolioBase = "https://127.0.0.1:6902"
$intelBase = "http://127.0.0.1:6120"
$webArgs = @{}
if ($SkipCertificateCheck) {
    $webArgs["SkipCertificateCheck"] = $true
}

$portfolioWidgets = Invoke-RestMethod "$portfolioBase/widgets.json" @webArgs
$portfolioApps = Invoke-RestMethod "$portfolioBase/apps.json" @webArgs
$agents = Invoke-RestMethod "$portfolioBase/agents.json" @webArgs
$intelWidgets = Invoke-RestMethod "$intelBase/widgets.json"
$intelApps = Invoke-RestMethod "$intelBase/apps.json"

$checks = [ordered]@{
    PortfolioWidgets = $portfolioWidgets.PSObject.Properties.Count
    PortfolioApps = @($portfolioApps).Count
    PortfolioAgents = $agents.PSObject.Properties.Count
    IntelWidgets = $intelWidgets.PSObject.Properties.Count
    IntelApps = @($intelApps).Count
}

foreach ($entry in $checks.GetEnumerator()) {
    if ($entry.Value -lt 1) {
        throw "$($entry.Key) discovery returned no entries"
    }
    Write-Host "[PASS] $($entry.Key): $($entry.Value)"
}
```

- [ ] **Step 2: Run the smoke checker**

Run:

```powershell
.\scripts\test_workspace_dev.ps1 -SkipCertificateCheck
```

Expected: five `[PASS]` lines; no widget rows, credentials, or financial values are printed.

- [ ] **Step 3: Commit the smoke checker**

```powershell
git add scripts/test_workspace_dev.ps1
git commit -m "test: add Workspace development smoke checks" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Deploy the self-hosted Workspace development stack (#2110)

**Files:**
- Create: `scripts/setup_self_hosted_workspace.ps1`
- Create: `scripts/run_self_hosted_workspace.ps1`
- Create: `scripts/stop_self_hosted_workspace.ps1`
- Create: focused Pester tests under `scripts/tests/`
- Modify: `docs/operations/workspace-local-development.md`

**Interfaces:**
- Consumes: pinned `third_party/workspace`, Docker Desktop Linux engine, Compose, and Bun.
- Produces: Redis/FastAPI/RQ/SQLite on an exact Compose project and Vite on `127.0.0.1:1420`.

- [x] **Step 1: Verify focused lifecycle tests**

```powershell
Invoke-Pester -Path @(
  "scripts/tests/Setup-SelfHostedWorkspace.Tests.ps1",
  "scripts/tests/Run-SelfHostedWorkspace.Tests.ps1",
  "scripts/tests/Stop-SelfHostedWorkspace.Tests.ps1"
)
```

- [x] **Step 2: Generate ignored runtime configuration and install frontend dependencies**

```powershell
.\scripts\setup_self_hosted_workspace.ps1
```

- [x] **Step 3: Build and start the local stack**

```powershell
.\scripts\run_self_hosted_workspace.ps1
```

- [x] **Step 4: Verify readiness without printing bodies or credentials**

```powershell
(Invoke-WebRequest http://127.0.0.1:8000/health `
  -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 5).StatusCode
(Invoke-WebRequest http://127.0.0.1:1420 `
  -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 5).StatusCode
docker compose --project-name openbb-workspace-2110 `
  --file third_party\workspace\backend-api\docker-compose-local-dev-sqlite.yml `
  --file third_party\workspace\backend-api\backend\workspace-compose.secrets `
  ps --status running --services
```

Expected and verified: both HTTP statuses are `200`; `fastapi`, `redis`, and
`rq_worker` are running; ports `8000` and `1420` listen only on `127.0.0.1`.
The launch script separately verifies admin login with generated credentials
without printing the response. The pinned backend disables `/docs`, so readiness
uses `/health`.

- [x] **Step 5: Stop only owned processes and containers**

```powershell
.\scripts\stop_self_hosted_workspace.ps1
git -C third_party/workspace status --short --untracked-files=no
git status --short
git diff --check
```

Expected and verified: no owned container remains and no tracked submodule file
is modified.

### Task 7: Connect the hosted Workspace UI to local services

**Files:**
- Runtime only: OpenBB Workspace account configuration.
- Runtime only: `%USERPROFILE%\.openbb_browser_test_harness\chrome_profile`.

**Interfaces:**
- Consumes: the two running local backends and a valid OpenBB Workspace login.
- Produces: Portfolio Overview and Portfolio Intelligence apps in the real Workspace UI.

- [ ] **Step 1: Add the Portfolio backend**

In `https://pro.openbb.co`, open **Apps → Data connectors → Custom backend → Add** and enter:

```text
Name: Portfolio Local
URL: https://127.0.0.1:6902
```

Expected: the connection test succeeds and the Portfolio Overview app is available.

- [ ] **Step 2: Add Portfolio Intelligence**

Add:

```text
Name: Portfolio Intelligence Local
URL: http://127.0.0.1:6120
```

Expected: Portfolio Intelligence widgets and apps are available.

- [ ] **Step 3: Verify app composition**

Open Portfolio Overview and verify:

```text
Overview
Positions
Cost Basis & Tax
Trends
ESPP
Stock Analysis
```

Open a Portfolio Intelligence app and verify at least one widget completes a request against origin `http://127.0.0.1:6120`.

- [ ] **Step 4: Install the browser harness and create its persistent profile**

Run:

```powershell
.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall -InstallBrowser
$env:RUN_WORKSPACE_HARNESS = "1"
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\tools\browser_test_harness\tests\test_workspace_driver.py -v
```

Expected: Chromium opens visibly on first run; log in manually. Cookies persist under `%USERPROFILE%\.openbb_browser_test_harness\chrome_profile`.

### Task 8: Validate Workspace Bench locally before enabling model calls

**Files:**
- Runtime only: `third_party/openbb-workspace-bench/.venv`
- Generated and ignored: `third_party/openbb-workspace-bench/runs/`

**Interfaces:**
- Consumes: the pinned benchmark and `uv`.
- Produces: deterministic simulator validation and oracle/no-op baseline evidence.

- [ ] **Step 1: Validate all bundled tasksets**

Run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run workspace-bench validate --taskset smoke --min-tasks 80
    uv run workspace-bench validate --taskset enterprise-apps-default --min-tasks 138
    uv run workspace-bench validate --taskset workspace-tasks --min-tasks 120
} finally {
    Pop-Location
}
```

Expected: all three tasksets validate at or above their minimum task counts.

- [ ] **Step 2: Prove the grader separates success from no-op behavior**

Run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run workspace-bench run `
      --task workspace-tasks/portfolio_manager/morning_briefing_level0 `
      --agent oracle
    uv run workspace-bench run `
      --task workspace-tasks/portfolio_manager/morning_briefing_level0 `
      --agent noop
} finally {
    Pop-Location
}
```

Expected: the oracle passes and the no-op agent fails.

- [ ] **Step 3: Run the benchmark unit suite**

Run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run --extra dev pytest
} finally {
    Pop-Location
}
```

Expected: all benchmark tests pass.

### Task 9: Enable live MCP validation through the supported hosted path

**Files:**
- Runtime only: process environment or ignored `third_party/openbb-workspace-bench/.env`.

**Interfaces:**
- Consumes: an MCP token issued in OpenBB Workspace and the hosted endpoint `https://backend.openbb.co/mcp`.
- Produces: hosted-surface audit and live parity evidence against the real user Workspace.

- [ ] **Step 1: Obtain a Workspace MCP token**

Create a token in the Workspace UI. Store it only for the current PowerShell process:

```powershell
$env:WORKSPACE_MCP_TOKEN = Read-Host -MaskInput "OpenBB Workspace MCP token"
$env:WORKSPACE_MCP_URL = "https://backend.openbb.co/mcp"
```

Expected: neither value is written to disk or printed.

- [ ] **Step 2: Run the hosted surface audit**

Run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run --extra live python scripts\audits\audit_hosted_surface.py
} finally {
    Pop-Location
}
```

Expected: the hosted tool surface is compared against the committed compatibility baseline.

- [ ] **Step 3: Run one eligible live parity task**

Keep a logged-in Workspace tab open, then run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run --extra live workspace-bench live-parity `
      --task smoke/get_widget_data/smoke_get_widget_data_level0
} finally {
    Pop-Location
}
```

Expected: the benchmark creates a marker-named dashboard, grades live and simulated legs, writes a parity report, then removes its live artifacts and restores the previously active dashboard.

- [ ] **Step 4: Record the self-host MCP source boundary**

Document this warning in the runbook:

```text
The pinned Workspace source contains integrated MCP routes and a standalone
`workspace_mcp` package, but neither path has been built or run locally.
Do not install PyPI `workspace-mcp`; that package serves Google Workspace and
is incompatible. Keep hosted MCP validation separate until the self-host stack
is deployed and verified.
```

### Task 10: Validate the optional custom-agent path

**Files:**
- Runtime only: an OpenAI-compatible proxy on `127.0.0.1:4141`, or environment overrides for another loopback endpoint.

**Interfaces:**
- Consumes: the Portfolio backend `/agents.json` and `/query`, plus an OpenAI-compatible model endpoint.
- Produces: streamed Portfolio Copilot replies in Workspace.

- [ ] **Step 1: Verify agent discovery without starting a model proxy**

Run:

```powershell
$agents = Invoke-RestMethod https://127.0.0.1:6902/agents.json -SkipCertificateCheck
if (-not $agents.portfolio_copilot_proxy) {
    throw "Portfolio Copilot descriptor is missing"
}
if ($agents.portfolio_copilot_proxy.endpoints.query -ne "https://127.0.0.1:6902/query") {
    throw "Portfolio Copilot query URL is incorrect"
}
```

Expected: descriptor and query URL checks pass.

- [ ] **Step 2: Select one OpenAI-compatible local proxy**

The existing implementation defaults to:

```text
COPILOT_PROXY_BASE_URL=http://127.0.0.1:4141/v1
COPILOT_PROXY_API_KEY=copilot
COPILOT_PROXY_MODEL=gpt-4o
```

Initialize and follow the existing `copilot-api` submodule documentation if GitHub Copilot proxying is desired:

```powershell
git submodule update --init --recursive copilot-api
```

Alternatively, set the three variables to a loopback OpenAI-compatible server already approved for local use. Do not start this step until that server has at least one model available.

- [ ] **Step 3: Verify streaming through Workspace**

Add the agent endpoint `https://127.0.0.1:6902` in Workspace, select **Portfolio Copilot (local proxy)**, and send:

```text
Explain the fields in the Portfolio Summary widget without giving investment advice.
```

Expected: Workspace receives streamed text chunks; the response explains data and does not issue a buy, sell, or hold recommendation.

### Task 11: Publish the operator runbook and perform final verification

**Files:**
- Create: `docs/operations/workspace-local-development.md`

**Interfaces:**
- Consumes: the completed setup, launch, smoke, browser, benchmark, and MCP procedures.
- Produces: one canonical entry point for future operators.

- [ ] **Step 1: Write the runbook**

The runbook must contain these sections and commands:

```text
1. What is local and what remains hosted
2. One-time setup
3. Required ignored configuration
4. Start Portfolio backend
5. Start Portfolio Intelligence and local viewer
6. Connect pro.openbb.co to both loopback services
7. Run privacy-safe smoke checks
8. Create/reuse the Playwright Workspace profile
9. Run deterministic Workspace Bench evaluations
10. Run hosted MCP surface and parity checks
11. Enable the optional Portfolio Copilot
12. Troubleshooting ports 3306, 6120, 6902, 4141, and TLS trust
13. Shutdown procedure
14. Security and data-handling cautions
```

Use Markdown links to the local scripts and the three submodules. State prominently that `http://127.0.0.1:6120/viewer` is a local preview, not OpenBB Workspace.

- [ ] **Step 2: Run all noninteractive validations**

Run:

```powershell
.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall
.\scripts\test_workspace_dev.ps1 -SkipCertificateCheck
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\extensions\portfolio_intel\tests\unit\test_widget_backend.py -q
Push-Location third_party\openbb-workspace-bench
try {
    uv run workspace-bench validate --taskset smoke --min-tasks 80
    uv run workspace-bench validate --taskset enterprise-apps-default --min-tasks 138
    uv run workspace-bench validate --taskset workspace-tasks --min-tasks 120
} finally {
    Pop-Location
}
```

Expected: every command exits `0`.

- [ ] **Step 3: Check the final change set for secrets and unrelated files**

Run:

```powershell
git status --short
git diff --check
git grep -n -I -E "obb_mcp_|sk-[A-Za-z0-9]|MYSQL_PASSWORD=.+" -- `
  scripts docs/operations .gitmodules
```

Expected: the secret scan returns no matches; the pre-existing modified notebook remains unstaged and unchanged by this work.

- [ ] **Step 4: Commit the runbook**

```powershell
git add docs/operations/workspace-local-development.md
git commit -m "docs: add local Workspace development runbook" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Acceptance Criteria

- A fresh clone can initialize the three new submodules recursively.
- One setup command validates the toolchain, installs local packages, syncs Workspace Bench, and optionally installs Chromium.
- Portfolio discovery, apps, and agent descriptors respond on `https://127.0.0.1:6902`.
- Portfolio Intelligence discovery, apps, and local viewer respond on `http://127.0.0.1:6120`.
- The hosted Workspace UI can connect to both local backends.
- The browser harness creates and reuses a persistent authenticated profile.
- All three bundled Workspace Bench tasksets validate.
- An oracle task passes and its no-op counterpart fails.
- Hosted MCP auditing and one eligible live parity task can run using an operator-issued token.
- Documentation clearly distinguishes the local viewer, simulator, historical hosted Workspace path, hosted MCP bridge, and unvalidated integrated and standalone self-host MCP source.
- No secrets, generated certificates, browser profiles, raw financial data, or benchmark transcripts enter Git.
