#!/usr/bin/env pwsh

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:CopilotApiRuntimeRoot = Join-Path (
    Split-Path -Parent $PSScriptRoot
) ".dev-cycle\copilot-api-2103"
$script:CopilotApiPidPath = Join-Path $script:CopilotApiRuntimeRoot "proxy.pid.json"

. (Join-Path $PSScriptRoot "copilot_api_process.ps1")

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

    return (
        (Get-CopilotApiProcessIdentityStatus -State $State) -eq "Match"
    )
}

function Stop-CopilotApiOwnedProcess {
    param(
        [Parameter(Mandatory)][pscustomobject]$State,
        [object]$Process
    )

    $ownedProcess = $Process
    try {
        if ($null -eq $ownedProcess) {
            $snapshot = Get-CopilotApiProcessIdentitySnapshot -State $State
            if ($snapshot.Status -ne "Match") {
                throw "PID state does not match the running process."
            }
            $ownedProcess = $snapshot.Process
        } elseif (
            $ownedProcess.Id -ne [int]$State.Pid -or
            $ownedProcess.StartTime.ToUniversalTime().Ticks -ne
                [long]$State.StartTimeUtcTicks
        ) {
            throw "PID state does not match the running process."
        }

        Stop-Process -InputObject $ownedProcess -Force -ErrorAction Stop
        $stopped = Wait-CopilotApiProcessExit -IsOwnedProcessRunning {
            Test-CopilotApiProcessIdentity -State $State
        }
        if (-not $stopped) {
            throw "Copilot API process did not stop within the finite timeout."
        }
    } finally {
        if ($null -ne $ownedProcess) {
            $ownedProcess.Dispose()
        }
    }
}

function Stop-CopilotApi {
    if (-not (Test-Path $script:CopilotApiPidPath -PathType Leaf)) {
        Write-Host "Copilot API has no owned PID state; nothing was stopped."
        return
    }

    $state = Read-CopilotApiPidState -Path $script:CopilotApiPidPath `
        -InvalidMessage "Copilot API PID state is invalid; no process was stopped."

    $snapshot = Get-CopilotApiProcessIdentitySnapshot -State $state
    if ($snapshot.Status -eq "Missing") {
        Remove-Item $script:CopilotApiPidPath -Force
        Write-Host "Copilot API stale PID state removed; service is stopped."
        return
    }
    if ($snapshot.Status -eq "Mismatch") {
        throw "PID state does not match the running process."
    }
    Stop-CopilotApiOwnedProcess -State $state -Process $snapshot.Process
    Remove-Item $script:CopilotApiPidPath -Force
    Write-Host "Stopped the exact owned Copilot API process."
}

if ($MyInvocation.InvocationName -ne ".") {
    Stop-CopilotApi
}
