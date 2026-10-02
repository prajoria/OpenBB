#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Prepare local dependencies for OpenBB Workspace development on Windows.

.DESCRIPTION
    Initializes the three Workspace development submodules, creates the shared
    portfolio virtual environment when needed, installs local editable packages,
    checks for a local MySQL listener, and synchronizes Workspace Bench.

    This script never creates or modifies .env. The Workspace UI remains hosted.

.PARAMETER InstallBrowser
    Install the Playwright Chromium browser after dependency setup.

.PARAMETER SkipPackageInstall
    Skip pip upgrades and editable package installation. Submodule, MySQL, and
    Workspace Bench checks still run.
#>

[CmdletBinding()]
param(
    [switch]$InstallBrowser,
    [switch]$SkipPackageInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $repoRoot ".venv_portfolio"
$python = Join-Path $venvDir "Scripts\python.exe"
$workspaceBench = Join-Path $repoRoot "third_party\openbb-workspace-bench"
$requiredCommands = @("git", "python", "uv")

foreach ($command in $requiredCommands) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $command"
    }
}

if (-not (Test-Path $python -PathType Leaf)) {
    Write-Host "Creating .venv_portfolio ..." -ForegroundColor Yellow
    & python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv_portfolio"
    }
}

Write-Host "Initializing Workspace development submodules ..." -ForegroundColor Yellow
& git -C $repoRoot submodule update --init --recursive -- `
    "third_party/backends-for-openbb" `
    "third_party/agents-for-openbb" `
    "third_party/openbb-workspace-bench"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize Workspace development submodules"
}

if (-not $SkipPackageInstall) {
    Write-Host "Installing local Workspace development packages ..." -ForegroundColor Yellow
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip"
    }

    $editablePackages = @(
        "openbb_platform\core",
        "openbb_platform\extensions\platform_api",
        "openbb_platform\extensions\backtest",
        "openbb_platform\extensions\techtrade",
        "openbb_platform\extensions\portfolio",
        "openbb_platform\tools\browser_test_harness[workspace,test]"
    )
    $installArgs = @("-m", "pip", "install")
    foreach ($package in $editablePackages) {
        $installArgs += @("-e", (Join-Path $repoRoot $package))
    }
    $installArgs += "cryptography"

    & $python @installArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install local Workspace development packages"
    }

    # portfolio_intel declares techtrade as a local path dependency. Installing
    # both as top-level editables in one resolver pass makes pip treat the same
    # package as conflicting direct references, so install it after its editable
    # dependencies are present.
    $portfolioIntelArgs = @(
        "-m", "pip", "install", "--no-deps", "-e",
        (Join-Path $repoRoot "openbb_platform\extensions\portfolio_intel")
    )
    & $python @portfolioIntelArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install portfolio_intel"
    }
} else {
    Write-Host "Skipping local package installation (-SkipPackageInstall)." -ForegroundColor Green
}

$mysql = Get-NetTCPConnection -State Listen -LocalPort 3306 -ErrorAction SilentlyContinue
if (-not $mysql) {
    throw "MySQL is not listening on local port 3306"
}
Write-Host "MySQL is listening on local port 3306." -ForegroundColor Green

$envPath = Join-Path $repoRoot ".env"
if (-not (Test-Path $envPath -PathType Leaf)) {
    Write-Warning ".env is absent. Portfolio and ESPP routes will not have database credentials."
}

if (-not (Test-Path (Join-Path $workspaceBench "pyproject.toml") -PathType Leaf)) {
    throw "Workspace Bench is not initialized"
}

Write-Host "Synchronizing Workspace Bench dependencies ..." -ForegroundColor Yellow
Push-Location $workspaceBench
try {
    & uv sync --extra dev --extra live
    if ($LASTEXITCODE -ne 0) {
        throw "Workspace Bench dependency sync failed"
    }
} finally {
    Pop-Location
}

if ($InstallBrowser) {
    Write-Host "Installing Playwright Chromium ..." -ForegroundColor Yellow
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright Chromium installation failed"
    }
}

Write-Host "Workspace development prerequisites are ready." -ForegroundColor Green
