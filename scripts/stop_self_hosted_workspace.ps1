#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Stop only the self-hosted Workspace processes owned by these scripts.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "third_party\workspace\backend-api"
$composeFile = Join-Path $backendRoot "docker-compose-local-dev-sqlite.yml"
$composeOverride = Join-Path $backendRoot "backend\workspace-compose.secrets"
$runtimeRoot = Join-Path $repoRoot ".dev-cycle\workspace-2110"
$pidPath = Join-Path $runtimeRoot "frontend.pid.json"
$composeProject = "openbb-workspace-2110"

function Get-WorkspaceDescendantProcessIds {
    param([Parameter(Mandatory)][int]$ParentId)

    $allProcesses = @(Get-CimInstance Win32_Process)
    $result = [System.Collections.Generic.List[int]]::new()
    $queue = [System.Collections.Generic.Queue[int]]::new()
    $queue.Enqueue($ParentId)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($child in $allProcesses | Where-Object { $_.ParentProcessId -eq $current }) {
            $result.Add([int]$child.ProcessId)
            $queue.Enqueue([int]$child.ProcessId)
        }
    }
    return @($result)
}

function Stop-WorkspaceFrontendProcess {
    param([Parameter(Mandatory)][pscustomobject]$State)

    $process = Get-Process -Id ([int]$State.Pid) -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }
    if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$State.StartTimeUtcTicks) {
        Write-Warning "Recorded frontend PID was reused; no process was stopped."
        return
    }

    $descendants = @(Get-WorkspaceDescendantProcessIds -ParentId $process.Id)
    [array]::Reverse($descendants)
    foreach ($processId in $descendants) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}

function Invoke-SelfHostedWorkspaceStop {
    if (Test-Path $pidPath -PathType Leaf) {
        try {
            $state = Get-Content $pidPath -Raw | ConvertFrom-Json
            Stop-WorkspaceFrontendProcess -State $state
        } finally {
            Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
        }
    }

    if ((Test-Path $composeFile -PathType Leaf) -and
        (Test-Path $composeOverride -PathType Leaf)) {
        Push-Location $backendRoot
        try {
            & docker compose --project-name $composeProject `
                --file $composeFile --file $composeOverride `
                down --remove-orphans | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "Workspace Compose project failed to stop cleanly."
            }
        } finally {
            Pop-Location
        }
    }

    Write-Host "Self-hosted Workspace processes owned by this deployment are stopped."
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-SelfHostedWorkspaceStop
}
