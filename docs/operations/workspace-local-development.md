# Local Workspace development

This runbook connects local OpenBB development services to the hosted OpenBB
Workspace. **`http://127.0.0.1:6120/viewer` is a local preview; it is not
OpenBB Workspace.** The real Workspace UI remains `https://pro.openbb.co`.

Run commands from the repository root in PowerShell 7 unless stated otherwise.
Keep each long-running backend in its own terminal.

## 1. What is local and what remains hosted

| Surface | Location | Purpose |
| --- | --- | --- |
| OpenBB Workspace | `https://pro.openbb.co` | Hosted, authenticated product UI; it does not run from this repository. |
| Portfolio backend | `https://127.0.0.1:6902` | Local widgets, apps, agent descriptor, and query endpoint. |
| Portfolio Intelligence backend | `http://127.0.0.1:6120` | Local widgets, apps, and API. |
| Portfolio Intelligence viewer | `http://127.0.0.1:6120/viewer` | Local development preview only, not Workspace. |
| Workspace Bench | local process in [`third_party/openbb-workspace-bench`](../../third_party/openbb-workspace-bench) | Deterministic simulator and graders; simulator results do not prove hosted UI parity. |
| OpenBB MCP | `https://backend.openbb.co/mcp` | Hosted bridge used for live surface and parity checks with an operator-issued token. |
| OpenBB Workspace MCP sidecar | unavailable locally | Separate OpenBB artifact not present in this checkout or on this machine. |
| Optional model proxy | `http://127.0.0.1:4141/v1` | Local OpenAI-compatible endpoint used only by Portfolio Copilot. |

The reference repositories are pinned as submodules:

- [OpenBB backend examples](../../third_party/backends-for-openbb)
- [OpenBB agent examples](../../third_party/agents-for-openbb)
- [Workspace Bench](../../third_party/openbb-workspace-bench)

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
.\scripts\run_widget_backend.ps1 -AuthMode required -Token $token
```

The preview is `http://127.0.0.1:6120/viewer`. It helps inspect local widget
behavior, but it is not the hosted Workspace application.

## 6. Connect pro.openbb.co to both loopback services

First visit `https://127.0.0.1:6902/widgets.json` in the same browser profile
used for Workspace and explicitly accept the self-signed development
certificate warning.

Then open `https://pro.openbb.co` and use **Apps → Data connectors → Custom
backend → Add**:

| Name | URL |
| --- | --- |
| Portfolio Local | `https://127.0.0.1:6902` |
| Portfolio Intelligence Local | `http://127.0.0.1:6120` |

The hosted page calls loopback services through the browser; the services
remain local. Confirm that Portfolio Overview exposes Overview, Positions,
Cost Basis & Tax, Trends, ESPP, and Stock Analysis. Confirm that a Portfolio
Intelligence widget requests the `6120` origin.

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

The first run opens Chromium visibly. Log in manually. Later runs reuse
`$HOME\.openbb_browser_test_harness\chrome_profile`; do not copy or commit that
profile. See the browser harness
[Workspace-mode contract](../../openbb_platform/tools/browser_test_harness/docs/workspace-mode.md).

## 9. Run deterministic Workspace Bench evaluations

Validate all bundled tasksets before any model-backed or live run:

```powershell
Push-Location third_party\openbb-workspace-bench
try {
    uv run workspace-bench validate --taskset smoke --min-tasks 80
    uv run workspace-bench validate --taskset enterprise-apps-default --min-tasks 138
    uv run workspace-bench validate --taskset workspace-tasks --min-tasks 120

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

The oracle run must pass and the no-op run must fail, proving the grader
separates valid behavior from no action. These runs use a simulator; they are
not evidence that the hosted UI behaves identically. Keep generated run
artifacts and response transcripts out of Git.

## 10. Run hosted MCP surface and parity checks

Create a token in the hosted Workspace UI and keep it only in the current
PowerShell process:

```powershell
$env:WORKSPACE_MCP_TOKEN = Read-Host -MaskInput "OpenBB Workspace MCP token"
$env:WORKSPACE_MCP_URL = "https://backend.openbb.co/mcp"

Push-Location third_party\openbb-workspace-bench
try {
    uv run --extra live python scripts\audits\audit_hosted_surface.py
    uv run --extra live workspace-bench live-parity `
      --task smoke/get_widget_data/smoke_get_widget_data_level0
} finally {
    Pop-Location
    Remove-Item Env:WORKSPACE_MCP_TOKEN
    Remove-Item Env:WORKSPACE_MCP_URL
}
```

Keep a logged-in Workspace tab open for live parity. Review cleanup results:
the run should remove marker-named live artifacts and restore the previously
active dashboard. Do not commit its report if it contains response data.

> The command shown upstream as
> `workspace-mcp --cors-allow https://pro.openbb.co` requires OpenBB's
> Workspace MCP sidecar artifact. Do not install PyPI `workspace-mcp`; that
> package serves Google Workspace and is incompatible. Use hosted MCP live
> parity until OpenBB supplies the correct sidecar package or source
> repository.

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
5. Remove process-only sensitive variables:

   ```powershell
   Remove-Item Env:WORKSPACE_MCP_TOKEN -ErrorAction SilentlyContinue
   Remove-Item Env:WORKSPACE_MCP_URL -ErrorAction SilentlyContinue
   Remove-Item Env:PI_WIDGET_BACKEND_TOKEN -ErrorAction SilentlyContinue
   Remove-Item Env:COPILOT_PROXY_API_KEY -ErrorAction SilentlyContinue
   ```

6. Confirm development listeners are gone:

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
  unavailable OpenBB local sidecar.
- Before committing, inspect `git status --short`, run `git diff --check`, and
  scan the intended paths for credential patterns.
