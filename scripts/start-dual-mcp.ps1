#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Manage the OpenBB Platform and Workspace MCP servers as separate processes.

.DESCRIPTION
    Starts the OpenBB Platform MCP on port 8001 and the Workspace browser-control
    MCP on port 8787. Runtime state and logs are stored outside the repository.

.EXAMPLE
    .\scripts\start-dual-mcp.ps1
    .\scripts\start-dual-mcp.ps1 -Action Status
    .\scripts\start-dual-mcp.ps1 -Action Stop
#>

[CmdletBinding()]
param(
    [ValidateSet("Start", "Status", "Stop")]
    [string]$Action = "Start",

    [string]$WorkspaceRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) "..\workspace"),

    [ValidateRange(1, 65535)]
    [int]$PlatformPort = 8001,

    [ValidateRange(1, 65535)]
    [int]$WorkspacePort = 8787,

    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

$OpenBBRoot = Split-Path $PSScriptRoot -Parent
$WorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$WorkspaceBackend = Join-Path $WorkspaceRoot "backend-api\backend"
$StateRoot = Join-Path $env:LOCALAPPDATA "OpenBB\mcp-stack"
$StatePath = Join-Path $StateRoot "processes.json"
$PlatformLog = Join-Path $StateRoot "openbb-platform-mcp.log"
$PlatformErrorLog = Join-Path $StateRoot "openbb-platform-mcp.error.log"
$WorkspaceLog = Join-Path $StateRoot "workspace-mcp.log"
$WorkspaceErrorLog = Join-Path $StateRoot "workspace-mcp.error.log"

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return $null
    }
    Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
}

function Test-ProcessRunning {
    param([int]$ProcessId)
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Test-PortListening {
    param([int]$Port)
    return $null -ne (
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
}

function Get-DescendantProcessIds {
    param([int]$ParentId)

    $childrenByParent = @{}
    Get-CimInstance Win32_Process | ForEach-Object {
        $key = [int]$_.ParentProcessId
        if (-not $childrenByParent.ContainsKey($key)) {
            $childrenByParent[$key] = [System.Collections.Generic.List[int]]::new()
        }
        $childrenByParent[$key].Add([int]$_.ProcessId)
    }

    $result = [System.Collections.Generic.List[int]]::new()
    $pending = [System.Collections.Generic.Stack[int]]::new()
    $pending.Push($ParentId)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        if (-not $childrenByParent.ContainsKey($current)) {
            continue
        }
        foreach ($childId in $childrenByParent[$current]) {
            $result.Add($childId)
            $pending.Push($childId)
        }
    }
    return $result
}

function Stop-ProcessTree {
    param([int]$RootId)

    $descendants = @(Get-DescendantProcessIds -ParentId $RootId)
    [array]::Reverse($descendants)
    foreach ($processId in $descendants) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $RootId -Force -ErrorAction SilentlyContinue
}

function Write-Status {
    $state = Read-State
    if ($null -eq $state) {
        Write-Host "No dual MCP process state found at $StatePath."
        return
    }

    $platformRunning = Test-ProcessRunning -ProcessId $state.platform.pid
    $workspaceRunning = Test-ProcessRunning -ProcessId $state.workspace.pid
    [pscustomobject]@{
        Server = "OpenBB Platform MCP"
        PID = $state.platform.pid
        Running = $platformRunning
        Endpoint = $state.platform.endpoint
        Listening = Test-PortListening -Port $state.platform.port
        Log = $state.platform.log
    }
    [pscustomobject]@{
        Server = "Workspace MCP"
        PID = $state.workspace.pid
        Running = $workspaceRunning
        Endpoint = $state.workspace.endpoint
        Listening = Test-PortListening -Port $state.workspace.port
        Log = $state.workspace.log
    }
}

function Wait-ForServer {
    param(
        [string]$Name,
        [int]$ProcessId,
        [int]$Port,
        [string]$ErrorLog
    )

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-ProcessRunning -ProcessId $ProcessId)) {
            $details = if (Test-Path -LiteralPath $ErrorLog) {
                (Get-Content -LiteralPath $ErrorLog -Tail 30) -join [Environment]::NewLine
            } else {
                "No error log was created."
            }
            throw "$Name exited during startup.$([Environment]::NewLine)$details"
        }
        if (Test-PortListening -Port $Port) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not listen on port $Port within $StartupTimeoutSeconds seconds."
}

if ($Action -eq "Status") {
    Write-Status
    exit 0
}

if ($Action -eq "Stop") {
    $state = Read-State
    if ($null -eq $state) {
        Write-Host "No dual MCP processes are recorded."
        exit 0
    }
    foreach ($processId in @($state.platform.pid, $state.workspace.pid)) {
        if (Test-ProcessRunning -ProcessId $processId) {
            Stop-ProcessTree -RootId $processId
        }
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped the OpenBB Platform and Workspace MCP servers."
    exit 0
}

if ($PlatformPort -eq $WorkspacePort) {
    throw "PlatformPort and WorkspacePort must be different."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/."
}
if (-not (Test-Path -LiteralPath (Join-Path $OpenBBRoot "openbb_platform\pyproject.toml"))) {
    throw "OpenBB Platform project not found under $OpenBBRoot."
}
if (-not (Test-Path -LiteralPath (Join-Path $WorkspaceBackend "workspace_mcp"))) {
    throw "Workspace MCP package not found under $WorkspaceBackend."
}

$existing = Read-State
if ($null -ne $existing) {
    $running = @($existing.platform.pid, $existing.workspace.pid) |
        Where-Object { Test-ProcessRunning -ProcessId $_ }
    if ($running.Count -gt 0) {
        throw "A recorded MCP stack is still running. Use -Action Status or -Action Stop first."
    }
    Remove-Item -LiteralPath $StatePath -Force
}
foreach ($port in @($PlatformPort, $WorkspacePort)) {
    if (Test-PortListening -Port $port) {
        throw "Port $port is already in use."
    }
}

New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
foreach ($log in @($PlatformLog, $PlatformErrorLog, $WorkspaceLog, $WorkspaceErrorLog)) {
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
}

$platformArgs = @(
    "run",
    "--no-project",
    "--python", "3.13",
    "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\core"),
    "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\extensions\mcp_server"),
    "openbb-mcp",
    "--host", "127.0.0.1",
    "--port", $PlatformPort,
    "--transport", "streamable-http",
    "--tool-discovery"
)
$workspaceArgs = @(
    "run",
    "--no-project",
    "--python", "3.13",
    "--with", "fastmcp>=3.4.6",
    "--with", "openbb-ai>=2.1.0",
    "--with", "pydantic>=2.12.5",
    "--with", "starlette>=1.6.0",
    "--with", "uvicorn>=0.52.3",
    "--directory", $WorkspaceBackend,
    "python", "-m", "workspace_mcp",
    "--host", "127.0.0.1",
    "--port", $WorkspacePort,
    "--cors-allow", "https://pro.openbb.co"
)

$platformProcess = Start-Process -FilePath "uv" -ArgumentList $platformArgs -PassThru `
    -RedirectStandardOutput $PlatformLog -RedirectStandardError $PlatformErrorLog `
    -WindowStyle Hidden
try {
    $workspaceProcess = Start-Process -FilePath "uv" -ArgumentList $workspaceArgs -PassThru `
        -RedirectStandardOutput $WorkspaceLog -RedirectStandardError $WorkspaceErrorLog `
        -WindowStyle Hidden
} catch {
    Stop-ProcessTree -RootId $platformProcess.Id
    throw
}

$state = @{
    started_at = (Get-Date).ToString("o")
    platform = @{
        pid = $platformProcess.Id
        port = $PlatformPort
        endpoint = "http://127.0.0.1:$PlatformPort/mcp"
        log = $PlatformLog
        error_log = $PlatformErrorLog
    }
    workspace = @{
        pid = $workspaceProcess.Id
        port = $WorkspacePort
        endpoint = "http://127.0.0.1:$WorkspacePort/mcp"
        health = "http://127.0.0.1:$WorkspacePort/health"
        log = $WorkspaceLog
        error_log = $WorkspaceErrorLog
    }
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StatePath -Encoding UTF8

try {
    Wait-ForServer -Name "OpenBB Platform MCP" -ProcessId $platformProcess.Id `
        -Port $PlatformPort -ErrorLog $PlatformErrorLog
    Wait-ForServer -Name "Workspace MCP" -ProcessId $workspaceProcess.Id `
        -Port $WorkspacePort -ErrorLog $WorkspaceErrorLog
} catch {
    Stop-ProcessTree -RootId $platformProcess.Id
    Stop-ProcessTree -RootId $workspaceProcess.Id
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host "OpenBB Platform MCP: http://127.0.0.1:$PlatformPort/mcp"
Write-Host "Workspace MCP:       http://127.0.0.1:$WorkspacePort/mcp"
Write-Host "Workspace health:    http://127.0.0.1:$WorkspacePort/health"
Write-Host "Runtime logs:        $StateRoot"
