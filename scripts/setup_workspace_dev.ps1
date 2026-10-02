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

function Invoke-ExternalProcess {
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,

        [string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList | Out-Host
    $exitCode = $LASTEXITCODE
    return $exitCode
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,

        [string[]]$ArgumentList = @(),

        [Parameter(Mandatory)]
        [string]$FailureMessage
    )

    $exitCode = Invoke-ExternalProcess -FilePath $FilePath -ArgumentList $ArgumentList
    if ($exitCode -ne 0) {
        throw $FailureMessage
    }
}

function Invoke-WorkspaceDevSetup {
    param(
        [switch]$InstallBrowser,
        [switch]$SkipPackageInstall
    )

foreach ($command in $requiredCommands) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $command"
    }
}

if (-not (Test-Path $python -PathType Leaf)) {
    Write-Host "Creating .venv_portfolio ..." -ForegroundColor Yellow
    Invoke-CheckedCommand `
        -FilePath "python" `
        -ArgumentList @("-m", "venv", $venvDir) `
        -FailureMessage "Failed to create .venv_portfolio"
}

Write-Host "Initializing Workspace development submodules ..." -ForegroundColor Yellow
Invoke-CheckedCommand `
    -FilePath "git" `
    -ArgumentList @(
        "-C", $repoRoot, "submodule", "update", "--init", "--recursive", "--",
        "third_party/backends-for-openbb",
        "third_party/agents-for-openbb",
        "third_party/openbb-workspace-bench"
    ) `
    -FailureMessage "Failed to initialize Workspace development submodules"

if (-not $SkipPackageInstall) {
    Write-Host "Installing local Workspace development packages ..." -ForegroundColor Yellow
    Invoke-CheckedCommand `
        -FilePath $python `
        -ArgumentList @("-m", "pip", "install", "--upgrade", "pip") `
        -FailureMessage "Failed to upgrade pip"

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

    Invoke-CheckedCommand `
        -FilePath $python `
        -ArgumentList $installArgs `
        -FailureMessage "Failed to install local Workspace development packages"

    # portfolio_intel declares techtrade as a local path dependency. Installing
    # both as top-level editables in one resolver pass makes pip treat the same
    # package as conflicting direct references, so install it after its editable
    # dependencies are present.
    $portfolioIntelArgs = @(
        "-m", "pip", "install", "--no-deps", "-e",
        (Join-Path $repoRoot "openbb_platform\extensions\portfolio_intel")
    )
    Invoke-CheckedCommand `
        -FilePath $python `
        -ArgumentList $portfolioIntelArgs `
        -FailureMessage "Failed to install portfolio_intel"
} else {
    Write-Host "Skipping local package installation (-SkipPackageInstall)." -ForegroundColor Green
}

$mysql = @(
    Get-NetTCPConnection -State Listen -LocalPort 3306 -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -eq "127.0.0.1" }
)
if (-not $mysql) {
    throw "MySQL is not listening on 127.0.0.1:3306"
}
Write-Host "MySQL is listening on 127.0.0.1:3306." -ForegroundColor Green

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
    Invoke-CheckedCommand `
        -FilePath "uv" `
        -ArgumentList @("sync", "--extra", "dev", "--extra", "live") `
        -FailureMessage "Workspace Bench dependency sync failed"
} finally {
    Pop-Location
}

if ($InstallBrowser) {
    Write-Host "Installing Playwright Chromium ..." -ForegroundColor Yellow
    Invoke-CheckedCommand `
        -FilePath $python `
        -ArgumentList @("-m", "playwright", "install", "chromium") `
        -FailureMessage "Playwright Chromium installation failed"
}

Write-Host "Workspace development prerequisites are ready." -ForegroundColor Green
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-WorkspaceDevSetup `
        -InstallBrowser:$InstallBrowser `
        -SkipPackageInstall:$SkipPackageInstall
}
