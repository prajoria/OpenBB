#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [int]$ExpectedPid
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:CopilotApiPort = 4141
$script:CopilotApiUri = "http://127.0.0.1:4141/v1/models"
$script:CopilotApiRuntimeRoot = Join-Path (
    Split-Path -Parent $PSScriptRoot
) ".dev-cycle\copilot-api-2103"
$script:CopilotApiPidPath = Join-Path $script:CopilotApiRuntimeRoot "proxy.pid.json"

function Test-CopilotApiHealth {
    param(
        [Parameter(Mandatory)]
        [int]$ExpectedPid,
        [int]$Attempts = 30
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $listeners = @(
                Get-NetTCPConnection -LocalPort $script:CopilotApiPort `
                    -State Listen -ErrorAction Stop
            )
            if (
                $listeners.Count -ne 1 -or
                $listeners[0].LocalAddress -ne "127.0.0.1" -or
                [int]$listeners[0].OwningProcess -ne $ExpectedPid
            ) {
                throw "Listener identity mismatch."
            }

            $process = Get-Process -Id $ExpectedPid -ErrorAction Stop
            if ($process.Id -ne $ExpectedPid) {
                throw "Process identity mismatch."
            }

            $models = Invoke-RestMethod -Uri $script:CopilotApiUri `
                -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 10
            $modelIds = @(
                $models.data |
                    ForEach-Object { $_.id } |
                    Where-Object { $_ -is [string] -and $_.Length -gt 0 }
            )
            if ($modelIds.Count -lt 1) {
                throw "No models are available."
            }

            return [pscustomobject][ordered]@{
                Healthy = $true
                ModelId = $modelIds[0]
            }
        } catch {
            if ($attempt -eq $Attempts) {
                throw "Copilot API verification failed after $Attempts attempts."
            }
        }
        Start-Sleep -Seconds 2
    }

    throw "Copilot API verification failed after $Attempts attempts."
}

function Get-CopilotApiRecordedState {
    if (-not (Test-Path $script:CopilotApiPidPath -PathType Leaf)) {
        throw "Copilot API PID state is absent. Run scripts\run_copilot_api.ps1 first."
    }

    try {
        $state = Get-Content $script:CopilotApiPidPath -Raw | ConvertFrom-Json
        $pidValue = [int]$state.Pid
        $startTicks = [long]$state.StartTimeUtcTicks
    } catch {
        throw "Copilot API PID state is invalid."
    }
    if ($pidValue -le 0 -or $startTicks -le 0) {
        throw "Copilot API PID state is invalid."
    }

    return [pscustomobject]@{
        Pid = $pidValue
        StartTimeUtcTicks = $startTicks
    }
}

function Test-CopilotApi {
    param([int]$ExpectedPid)

    $state = Get-CopilotApiRecordedState
    if ($ExpectedPid -gt 0 -and $ExpectedPid -ne $state.Pid) {
        throw "Copilot API PID state does not match the started process."
    }

    try {
        $process = Get-Process -Id $state.Pid -ErrorAction Stop
    } catch {
        throw "Copilot API recorded process is not running."
    }
    if (
        $process.StartTime.ToUniversalTime().Ticks -ne
        $state.StartTimeUtcTicks
    ) {
        throw "Copilot API PID state does not match the running process."
    }

    return Test-CopilotApiHealth -ExpectedPid $state.Pid
}

if ($MyInvocation.InvocationName -ne ".") {
    $result = Test-CopilotApi -ExpectedPid $ExpectedPid
    Write-Host (
        "Copilot API is healthy on 127.0.0.1:4141; model={0}." -f
        $result.ModelId
    )
}
