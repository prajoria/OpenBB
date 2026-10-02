#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Run the Portfolio Intelligence widget backend for OpenBB Workspace.

.DESCRIPTION
    Starts the installed openbb_portfolio_intel backend on loopback. The
    loopback-dev authentication mode is an explicit local-only opt-out;
    required mode needs a bearer token. The /viewer route is a local preview,
    not OpenBB Workspace.

.PARAMETER Port
    Loopback port to bind. Defaults to 6120.

.PARAMETER Reload
    Restart uvicorn automatically when source files change.

.PARAMETER AuthMode
    Use loopback-dev for local development or required for bearer auth.

.PARAMETER Token
    Bearer token. Required when AuthMode is required.
#>

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
$backendRoot = Join-Path $repoRoot "openbb_platform\extensions\portfolio_intel"

function Invoke-WidgetBackendProcess {
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,

        [Parameter(Mandatory)]
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList | Out-Host
    $exitCode = $LASTEXITCODE
    return $exitCode
}

function Invoke-PortfolioIntelligenceBackend {
    param(
        [int]$Port = 6120,
        [switch]$Reload,
        [ValidateSet("loopback-dev", "required")]
        [string]$AuthMode = "loopback-dev",
        [string]$Token
    )

    if (-not (Test-Path $python -PathType Leaf)) {
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

    Push-Location $backendRoot
    try {
        return Invoke-WidgetBackendProcess -FilePath $python -ArgumentList $arguments
    } finally {
        Pop-Location
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-PortfolioIntelligenceBackend `
        -Port $Port `
        -Reload:$Reload `
        -AuthMode $AuthMode `
        -Token $Token)
}
