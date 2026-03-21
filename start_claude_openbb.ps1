#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start Claude CLI for OpenBB development with different focus areas.

.DESCRIPTION
    This script starts Claude Code CLI in the OpenBB repository with
    appropriate context and focus for different development areas.

.PARAMETER Focus
    The development focus area: api, desktop, cli, providers, deploy, or general (default)

.EXAMPLE
    .\start_claude_openbb.ps1
    .\start_claude_openbb.ps1 -Focus api
    .\start_claude_openbb.ps1 -Focus desktop
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("api", "desktop", "cli", "providers", "deploy", "general")]
    [string]$Focus = "general",

    [Parameter()]
    [bool]$UseProxy = $true
)

$OpenBBRoot = "i:\masterswork\git\OpenBB"
Set-Location $OpenBBRoot

$focusContext = switch ($Focus) {
    "api" { "OpenBB Platform API development (focus: openbb_platform/)" }
    "desktop" { "OpenBB Desktop app development (focus: desktop/)" }
    "cli" { "OpenBB CLI development (focus: cli/)" }
    "providers" { "OpenBB Platform providers and extensions (focus: openbb_platform/providers/, openbb_platform/extensions/)" }
    "deploy" { "OpenBB deployment and DevOps (focus: *.ps1, *.sh, docker*, *.yml, *.yaml)" }
    default { "Working on OpenBB Platform development" }
}

Write-Host "Starting Claude in: $OpenBBRoot" -ForegroundColor Cyan
Write-Host "Focus: $focusContext" -ForegroundColor DarkCyan

$proxyScript = Join-Path $OpenBBRoot "setup_copilot_claud\start-copilot-claude-proxy.ps1"

if ($UseProxy) {
    if (-not (Test-Path $proxyScript)) {
        Write-Warning "Proxy script not found at $proxyScript. Continuing without proxy launcher."
    } else {
        $proxyRunning = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match "node|pwsh|powershell" -and
                $_.CommandLine -match "copilot-api@latest start --claude-code"
            } |
            Select-Object -First 1

        if (-not $proxyRunning) {
            Write-Host "Starting Copilot-Claude proxy from setup_copilot_claud..." -ForegroundColor Cyan
            Start-Process -FilePath "pwsh" -ArgumentList @(
                "-NoLogo",
                "-ExecutionPolicy", "Bypass",
                "-File", $proxyScript
            ) -WindowStyle Minimized
            Start-Sleep -Seconds 2
        } else {
            Write-Host "Copilot-Claude proxy is already running." -ForegroundColor DarkCyan
        }
    }
}

switch ($Focus) {
    "api" {
        & claude --dangerously-skip-permissions
    }
    "desktop" {
        & claude --dangerously-skip-permissions
    }
    "cli" {
        & claude --dangerously-skip-permissions
    }
    "providers" {
        & claude --dangerously-skip-permissions
    }
    "deploy" {
        & claude --dangerously-skip-permissions
    }
    default {
        & claude --dangerously-skip-permissions
    }
}