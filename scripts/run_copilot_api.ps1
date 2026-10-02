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

. (Join-Path $PSScriptRoot "copilot_api_process.ps1")

function Resolve-CopilotApiStartState {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path $Path -PathType Leaf)) {
        return
    }
    $state = Read-CopilotApiPidState -Path $Path `
        -InvalidMessage "Copilot API PID state is invalid; start refused."
    switch (Get-CopilotApiProcessIdentityStatus -State $state) {
        "Missing" {
            Remove-Item $Path -Force
        }
        "Match" {
            throw "Copilot API is already running with recorded PID state."
        }
        default {
            throw "PID state does not match the running process."
        }
    }
}

function Stop-CopilotApiStartedProcess {
    param(
        [Parameter(Mandatory)][object]$Process,
        [int]$TimeoutMilliseconds = 5000
    )

    try {
        if ($Process.HasExited) {
            return
        }
        Stop-Process -InputObject $Process -Force -ErrorAction Stop
        if (-not $Process.WaitForExit($TimeoutMilliseconds)) {
            throw "Copilot API process did not stop within the finite timeout."
        }
    } finally {
        $Process.Dispose()
    }
}

function Invoke-CopilotApiStart {
    if (-not (Test-Path $proxyEntry -PathType Leaf)) {
        throw "Pinned copilot-api source is not initialized."
    }
    if (-not (Test-Path (Join-Path $proxyRoot "node_modules"))) {
        throw "copilot-api dependencies are absent. Run bun install in the submodule."
    }
    Resolve-CopilotApiStartState -Path $pidPath
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
        $null = $process.SafeHandle
        $startTimeUtcTicks =
            $process.StartTime.ToUniversalTime().Ticks
        [ordered]@{
            Pid = $process.Id
            StartTimeUtcTicks = $startTimeUtcTicks
        } | ConvertTo-Json |
            Set-Content -Path $pidPath -Encoding utf8NoBOM

        . (Join-Path $PSScriptRoot "test_copilot_api.ps1")
        $result = Test-CopilotApi -ExpectedPid $process.Id
        Write-Host (
            "Copilot API started on 127.0.0.1:4141; models={0}." -f
            $result.ModelCount
        )
    } catch {
        $safeMessage = $_.Exception.Message
        if ($process) {
            try {
                Stop-CopilotApiStartedProcess -Process $process
            } finally {
                $process = $null
            }
        }
        if (Test-Path $pidPath -PathType Leaf) {
            Remove-Item $pidPath -Force
        }
        throw $safeMessage
    } finally {
        if ($process) {
            $process.Dispose()
        }
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-CopilotApiStart
}
