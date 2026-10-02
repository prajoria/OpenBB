#!/usr/bin/env pwsh

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$proxyRoot = Join-Path $repoRoot "copilot-api"
$proxyEntry = Join-Path $proxyRoot "src\main.ts"
$runtimeRoot = Join-Path $repoRoot ".dev-cycle\copilot-api-2103"
$pidPath = Join-Path $runtimeRoot "proxy.pid.json"
$stdoutPath = Join-Path $runtimeRoot "proxy.stdout.log"
$stderrPath = Join-Path $runtimeRoot "proxy.stderr.log"

function Stop-CopilotApiStartedProcess {
    param([Parameter(Mandatory)][object]$Process)

    try {
        $current = Get-Process -Id $Process.Id -ErrorAction Stop
    } catch {
        return
    }
    if (
        $current.StartTime.ToUniversalTime().Ticks -ne
        $Process.StartTime.ToUniversalTime().Ticks
    ) {
        throw "Started Copilot API PID identity changed during cleanup."
    }
    Stop-Process -Id $Process.Id -Force -ErrorAction Stop
}

function Invoke-CopilotApiStart {
    if (-not (Test-Path $proxyEntry -PathType Leaf)) {
        throw "Pinned copilot-api source is not initialized."
    }
    if (-not (Test-Path (Join-Path $proxyRoot "node_modules"))) {
        throw "copilot-api dependencies are absent. Run bun install in the submodule."
    }
    if (Test-Path $pidPath -PathType Leaf) {
        throw "Copilot API PID state already exists. Run the stop script first."
    }
    if (
        Get-NetTCPConnection -LocalPort 4141 -State Listen `
            -ErrorAction SilentlyContinue
    ) {
        throw "Port 4141 is already in use."
    }

    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $process = $null
    try {
        $process = Start-Process -FilePath "bun" -ArgumentList @(
            "run", $proxyEntry, "start",
            "--host", "127.0.0.1",
            "--port", "4141"
        ) -WorkingDirectory $proxyRoot -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath -PassThru
        [ordered]@{
            Pid = $process.Id
            StartTimeUtcTicks = $process.StartTime.ToUniversalTime().Ticks
        } | ConvertTo-Json |
            Set-Content -Path $pidPath -Encoding utf8NoBOM

        . (Join-Path $PSScriptRoot "test_copilot_api.ps1")
        $result = Test-CopilotApi -ExpectedPid $process.Id
        Write-Host (
            "Copilot API started on 127.0.0.1:4141; model={0}." -f
            $result.ModelId
        )
    } catch {
        $safeMessage = $_.Exception.Message
        if ($process) {
            Stop-CopilotApiStartedProcess -Process $process
        }
        if (Test-Path $pidPath -PathType Leaf) {
            Remove-Item $pidPath -Force
        }
        throw $safeMessage
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-CopilotApiStart
}
