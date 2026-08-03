<#
.SYNOPSIS
    Set up and run the OpenBB Portfolio extension backend for OpenBB Workspace.

    Serves the unified `portfolio` extension (openbb-api --app launch.py):
    the Portfolio Overview app with tabs Overview / Positions / Cost Basis &
    Tax / Trends / ESPP / Stock Analysis, plus /portfolio/*, /stock/*,
    /espp/*, /equity/historical and the merged /widgets.json + /apps.json.

    This is the SECOND, distinct backend in this repo. Do not confuse it
    with `scripts/run_widget_backend.ps1`, which starts the SEPARATE
    `portfolio_intel` widget backend on port 6120 (a different set of
    apps). The saved "Portfolio Overview" app in OpenBB Workspace points
    at https://127.0.0.1:6902 -- THIS backend. See issue #1786.

    The script exists so the everyday "boot the portfolio backend and point
    Workspace at it" loop needs no AI assistance:

      1. Creates .venv_portfolio if missing.
      2. Installs the editable packages the backend needs
         (openbb-core, platform_api, portfolio) unless -SkipInstall.
      3. Checks for a MySQL .env (warns, non-fatal -- /stock/* and /api/v1/*
         work without it; /portfolio/* and /espp/* need the DB).
      4. Ensures a self-signed TLS cert exists (unless -NoSsl), generating
         one via scripts/gen_selfsigned_cert.py when absent.
      5. Launches openbb-api on 127.0.0.1:<Port> (HTTPS by default).

.PARAMETER Port
    Port to bind. Default 6902 -- the port the saved Portfolio Overview app
    expects over HTTPS. Use 6900 with -NoSsl for the plain-HTTP dev path.

.PARAMETER NoSsl
    Serve plain HTTP instead of HTTPS (skips the cert step). Point Workspace
    at http://127.0.0.1:<Port> in this mode. Loopback HTTP is a browser
    secure-context exception, so Workspace accepts http://127.0.0.1.

.PARAMETER CertDir
    Directory holding cert.pem / key.pem. Default `portfolio_app` (matches
    the extension README and launch.py). Gitignored -- never committed.

.PARAMETER SkipInstall
    Skip the venv-create + editable-install step and go straight to
    launching the server (use once the environment is already set up).

.PARAMETER Reload
    Enable auto-restart on source edits (dev only).

.USAGE
    # First run (installs deps, self-signed cert, serves HTTPS on :6902):
    .\scripts\run_portfolio_backend.ps1

    # Subsequent runs (skip install, faster):
    .\scripts\run_portfolio_backend.ps1 -SkipInstall

    # Plain-HTTP dev path (no certs), on :6900:
    .\scripts\run_portfolio_backend.ps1 -NoSsl -Port 6900

    Then in OpenBB Workspace: Apps / Data connectors -> Custom backend ->
    Add -> URL https://127.0.0.1:6902 (or http://127.0.0.1:6900 with -NoSsl).
#>

[CmdletBinding()]
param(
    [int]$Port = 6902,
    [switch]$NoSsl,
    [string]$CertDir = "portfolio_app",
    [switch]$SkipInstall,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's directory (scripts/).
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $projectRoot "openbb_platform"))) {
    $projectRoot = $PWD.Path
}

$venvDir        = Join-Path $projectRoot ".venv_portfolio"
$python         = Join-Path $venvDir "Scripts\python.exe"
$openbbPlatform = Join-Path $projectRoot "openbb_platform"
$launchApp      = Join-Path $openbbPlatform "extensions\portfolio\launch.py"
# Pass --app as a repo-root-relative path: the openbb-api launcher splits the
# --app value on ":" to detect a "module:instance" spec, which corrupts a
# Windows absolute path (the drive-letter colon in "H:\..."). A relative path
# has no colon; the launcher resolves it against the process CWD, so we run
# python from $projectRoot below.
$launchAppRel   = "openbb_platform/extensions/portfolio/launch.py"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  OpenBB Portfolio Extension Backend (OpenBB Workspace)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $launchApp)) {
    throw "launch.py not found at $launchApp -- is this the OpenBB repo root?"
}

# --- [1/4] venv + editable install --------------------------------------
if (-not $SkipInstall) {
    if (-not (Test-Path $venvDir)) {
        Write-Host "[1/4] Creating virtual environment: $venvDir" -ForegroundColor Yellow
        python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Failed to create venv" }
        & $python -m pip install --upgrade pip --quiet
        Write-Host "      Created." -ForegroundColor Green
    } else {
        Write-Host "[1/4] Virtual environment already exists: $venvDir" -ForegroundColor Green
    }

    Write-Host "[2/4] Installing portfolio-backend packages (editable) ..." -ForegroundColor Yellow
    Write-Host "      openbb-core, platform_api, portfolio" -ForegroundColor DarkGray
    & $python -m pip install `
        -e (Join-Path $openbbPlatform "core") `
        -e (Join-Path $openbbPlatform "extensions\platform_api") `
        -e (Join-Path $openbbPlatform "extensions\portfolio")
    if ($LASTEXITCODE -ne 0) { throw "Editable install failed" }
    Write-Host "      Done." -ForegroundColor Green
} else {
    Write-Host "[1/4] -SkipInstall set; using existing $venvDir" -ForegroundColor Green
    Write-Host "[2/4] Skipping editable install." -ForegroundColor Green
    if (-not (Test-Path $python)) {
        throw ".venv_portfolio not found at $venvDir. Run once without -SkipInstall first."
    }
}

# --- [3/4] MySQL .env check (non-fatal) ---------------------------------
$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    $envText  = Get-Content $envFile -Raw
    $required = @("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    $missing  = $required | Where-Object { $envText -notmatch "(?m)^\s*$_\s*=" }
    if ($missing.Count -gt 0) {
        Write-Host "[3/4] .env present but missing keys: $($missing -join ', ')" -ForegroundColor Yellow
        Write-Host "      /portfolio/* and /espp/* widgets need MySQL; /stock/* and /api/v1/* still work." -ForegroundColor DarkGray
    } else {
        Write-Host "[3/4] MySQL .env OK ($envFile)." -ForegroundColor Green
    }
} else {
    Write-Host "[3/4] No .env at $envFile." -ForegroundColor Yellow
    Write-Host "      /portfolio/* and /espp/* widgets need MySQL (MYSQL_HOST/USER/PASSWORD/DATABASE)." -ForegroundColor DarkGray
    Write-Host "      /stock/* and /api/v1/* market-data widgets still work without it." -ForegroundColor DarkGray
}

# --- [4/4] TLS cert + launch --------------------------------------------
$launchArgs = @(
    "-m", "openbb_platform_api.main",
    "--app", $launchAppRel,
    "--port", "$Port"
)

if ($NoSsl) {
    $scheme = "http"
    Write-Host "[4/4] TLS: disabled (-NoSsl). Serving plain HTTP." -ForegroundColor Yellow
} else {
    $scheme   = "https"
    $certDirAbs = if ([System.IO.Path]::IsPathRooted($CertDir)) { $CertDir } else { Join-Path $projectRoot $CertDir }
    $certPath = Join-Path $certDirAbs "cert.pem"
    $keyPath  = Join-Path $certDirAbs "key.pem"

    if ((Test-Path $certPath) -and (Test-Path $keyPath)) {
        Write-Host "[4/4] TLS: using existing cert in $certDirAbs" -ForegroundColor Green
    } else {
        Write-Host "[4/4] TLS: generating self-signed cert in $certDirAbs ..." -ForegroundColor Yellow
        & $python (Join-Path $projectRoot "scripts\gen_selfsigned_cert.py") `
            --cert $certPath --key $keyPath
        if ($LASTEXITCODE -ne 0) { throw "Self-signed cert generation failed" }
    }

    $launchArgs += @("--ssl_certfile", $certPath, "--ssl_keyfile", $keyPath)
}

if ($Reload) { $launchArgs += @("--reload", "true") }

$baseUrl = "${scheme}://127.0.0.1:$Port"

Write-Host ""
Write-Host "  Serving on $baseUrl" -ForegroundColor Green
Write-Host "  Manifest:  $baseUrl/widgets.json" -ForegroundColor Green
Write-Host "  Apps:      $baseUrl/apps.json" -ForegroundColor Green
Write-Host ""
Write-Host "  In OpenBB Workspace: Data connectors -> Custom backend -> Add" -ForegroundColor Cyan
Write-Host "  Name: portfolio   URL: $baseUrl" -ForegroundColor Cyan
if (-not $NoSsl) {
    Write-Host "  (self-signed cert: accept the browser warning for 127.0.0.1 on first use)" -ForegroundColor DarkGray
}
Write-Host "  (Ctrl+C to stop)" -ForegroundColor DarkGray
Write-Host ""

# Run from the repo root so the relative --app path resolves (see $launchAppRel).
Push-Location $projectRoot
try {
    & $python @launchArgs
} finally {
    Pop-Location
}
