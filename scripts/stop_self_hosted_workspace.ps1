#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Stop only the self-hosted Workspace processes owned by these scripts.
#>

[CmdletBinding()]
param(
    [Parameter(DontShow)]
    [object]$FrontendProcess
)

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
    param(
        [Parameter(Mandatory)][int]$ParentId,
        [Parameter(Mandatory)][datetime]$ParentStartTime
    )

    $allProcesses = @(Get-CimInstance Win32_Process)
    $parentStartUtc = $ParentStartTime.ToUniversalTime()
    $rootSnapshot = $allProcesses | Where-Object {
        $_.ProcessId -eq $ParentId
    } | Select-Object -First 1
    $parentStartTicks = $parentStartUtc.Ticks
    $rootStartTicks = if ($rootSnapshot -and $rootSnapshot.CreationDate) {
        ([datetime]$rootSnapshot.CreationDate).ToUniversalTime().Ticks
    } else {
        [long]0
    }
    if (
        -not $rootSnapshot -or
        -not $rootSnapshot.CreationDate -or
        ($rootStartTicks - ($rootStartTicks % 10)) -ne
            ($parentStartTicks - ($parentStartTicks % 10))
    ) {
        return @()
    }

    $result = [System.Collections.Generic.List[object]]::new()
    $queue = [System.Collections.Generic.Queue[object]]::new()
    $visited = [System.Collections.Generic.HashSet[int]]::new()
    $null = $visited.Add($ParentId)
    $queue.Enqueue([pscustomobject]@{
        ProcessId = $ParentId
        CreationDate = $parentStartUtc
    })
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($child in $allProcesses | Where-Object {
            $_.ParentProcessId -eq $current.ProcessId
        }) {
            if (-not $child.CreationDate) {
                continue
            }
            $childStart = ([datetime]$child.CreationDate).ToUniversalTime()
            $childId = [int]$child.ProcessId
            if (
                $childStart -le $current.CreationDate -or
                -not $visited.Add($childId)
            ) {
                continue
            }
            $result.Add($child)
            $queue.Enqueue([pscustomobject]@{
                ProcessId = $childId
                CreationDate = $childStart
            })
        }
    }
    return @($result)
}

function Test-WorkspaceProcessIdentity {
    param([Parameter(Mandatory)][pscustomobject]$Snapshot)

    $current = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $([int]$Snapshot.ProcessId)" `
        -ErrorAction SilentlyContinue
    if (-not $current) {
        return $false
    }
    return (
        [int]$current.ParentProcessId -eq [int]$Snapshot.ParentProcessId -and
        $current.CreationDate -eq $Snapshot.CreationDate
    )
}

function Test-WorkspaceFrontendIdentity {
    param([Parameter(Mandatory)][pscustomobject]$State)

    $current = Get-Process -Id ([int]$State.Pid) -ErrorAction SilentlyContinue
    return (
        $null -ne $current -and
        $current.StartTime.ToUniversalTime().Ticks -eq
            [long]$State.StartTimeUtcTicks
    )
}

function Wait-WorkspaceProcessExit {
    param(
        [Parameter(Mandatory)][scriptblock]$IsOwnedProcessRunning,
        [ValidateRange(1, 100)][int]$Attempts = 10,
        [ValidateRange(1, 1000)][int]$DelayMilliseconds = 100
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

    $descendants = @(
        Get-WorkspaceDescendantProcessIds -ParentId $process.Id `
            -ParentStartTime $process.StartTime
    )
    $terminationFailed = $false
    [array]::Reverse($descendants)
    foreach ($descendant in $descendants) {
        if (Test-WorkspaceProcessIdentity -Snapshot $descendant) {
            try {
                Stop-Process -Id ([int]$descendant.ProcessId) -Force `
                    -ErrorAction Stop
            } catch {
                $terminationFailed = $true
            }
            if (-not (Wait-WorkspaceProcessExit -IsOwnedProcessRunning {
                Test-WorkspaceProcessIdentity -Snapshot $descendant
            })) {
                $terminationFailed = $true
            }
        } elseif (Get-Process -Id ([int]$descendant.ProcessId) `
                -ErrorAction SilentlyContinue) {
            Write-Warning "A frontend descendant no longer matched its recorded identity; it was not stopped."
        }
    }
    $currentParent = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
    if (
        $currentParent -and
        $currentParent.StartTime.ToUniversalTime().Ticks -eq
            [long]$State.StartTimeUtcTicks
    ) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        } catch {
            $terminationFailed = $true
        }
        if (-not (Wait-WorkspaceProcessExit -IsOwnedProcessRunning {
            Test-WorkspaceFrontendIdentity -State $State
        })) {
            $terminationFailed = $true
        }
    } elseif ($currentParent) {
        Write-Warning "Recorded frontend PID was reused; no process was stopped."
    }
    if ($terminationFailed) {
        throw "Owned frontend process cleanup did not complete."
    }
}

function Invoke-WorkspaceComposeDown {
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

function Invoke-SelfHostedWorkspaceStop {
    param([object]$FrontendProcess)

    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    try {
        try {
            $state = $null
            if ($null -ne $FrontendProcess) {
                $state = [pscustomobject]@{
                    Pid = [int]$FrontendProcess.Id
                    StartTimeUtcTicks =
                        $FrontendProcess.StartTime.ToUniversalTime().Ticks
                }
            } elseif (Test-Path $pidPath -PathType Leaf) {
                try {
                    $state = Get-Content $pidPath -Raw | ConvertFrom-Json
                    $parsedPid = 0
                    $parsedStartTicks = [long]0
                    if (
                        -not [int]::TryParse(
                            [string]$state.Pid, [ref]$parsedPid
                        ) -or
                        -not [long]::TryParse(
                            [string]$state.StartTimeUtcTicks,
                            [ref]$parsedStartTicks
                        ) -or
                        $parsedPid -le 0 -or
                        $parsedStartTicks -le 0 -or
                        $parsedStartTicks -gt [datetime]::MaxValue.Ticks
                    ) {
                        throw "Invalid frontend PID state."
                    }
                    $state = [pscustomobject]@{
                        Pid = $parsedPid
                        StartTimeUtcTicks = $parsedStartTicks
                    }
                } catch {
                    $state = $null
                    Write-Warning "Frontend PID state was invalid and has been discarded."
                }
            }
            if ($null -ne $state) {
                Stop-WorkspaceFrontendProcess -State $state
            }
        } catch {
            $cleanupErrors.Add("Frontend cleanup failed.")
        } finally {
            Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
        }
    } finally {
        try {
            if ((Test-Path $composeFile -PathType Leaf) -and
                (Test-Path $composeOverride -PathType Leaf)) {
                Invoke-WorkspaceComposeDown
            }
        } catch {
            $cleanupErrors.Add("Compose cleanup failed.")
        }
    }

    if ($cleanupErrors.Count -gt 0) {
        throw ($cleanupErrors -join " ")
    }
    Write-Host "Self-hosted Workspace processes owned by this deployment are stopped."
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-SelfHostedWorkspaceStop -FrontendProcess $FrontendProcess
}
