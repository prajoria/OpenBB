#!/usr/bin/env pwsh

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:CopilotApiRuntimeRoot = Join-Path (
    Split-Path -Parent $PSScriptRoot
) ".dev-cycle\copilot-api-2103"
$script:CopilotApiPidPath = Join-Path $script:CopilotApiRuntimeRoot "proxy.pid.json"

function Wait-CopilotApiProcessExit {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$IsOwnedProcessRunning,
        [int]$Attempts = 20,
        [int]$DelayMilliseconds = 250
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if (-not (& $IsOwnedProcessRunning)) {
            return $true
        }
        if ($attempt -lt $Attempts) {
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
    }
    return $false
}

function Test-CopilotApiProcessIdentity {
    param([Parameter(Mandatory)][pscustomobject]$State)

    try {
        $process = Get-Process -Id ([int]$State.Pid) -ErrorAction Stop
    } catch {
        return $false
    }
    return (
        $process.StartTime.ToUniversalTime().Ticks -eq
        [long]$State.StartTimeUtcTicks
    )
}

function Stop-CopilotApiOwnedProcess {
    param([Parameter(Mandatory)][pscustomobject]$State)

    if (-not (Test-CopilotApiProcessIdentity -State $State)) {
        throw "PID state does not match the running process."
    }

    Stop-Process -Id ([int]$State.Pid) -Force -ErrorAction Stop
    $stopped = Wait-CopilotApiProcessExit -IsOwnedProcessRunning {
        Test-CopilotApiProcessIdentity -State $State
    }
    if (-not $stopped) {
        throw "Copilot API process did not stop within the finite timeout."
    }
}

function Stop-CopilotApi {
    if (-not (Test-Path $script:CopilotApiPidPath -PathType Leaf)) {
        Write-Host "Copilot API has no owned PID state; nothing was stopped."
        return
    }

    try {
        $state = Get-Content $script:CopilotApiPidPath -Raw |
            ConvertFrom-Json
        $state = [pscustomobject]@{
            Pid = [int]$state.Pid
            StartTimeUtcTicks = [long]$state.StartTimeUtcTicks
        }
    } catch {
        throw "Copilot API PID state is invalid; no process was stopped."
    }

    Stop-CopilotApiOwnedProcess -State $state
    Remove-Item $script:CopilotApiPidPath -Force
    Write-Host "Stopped the exact owned Copilot API process."
}

if ($MyInvocation.InvocationName -ne ".") {
    Stop-CopilotApi
}
