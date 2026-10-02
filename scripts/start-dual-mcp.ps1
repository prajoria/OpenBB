#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Manage the OpenBB Platform and Workspace MCP servers as separate processes.

.DESCRIPTION
    Starts the OpenBB Platform MCP on port 8001 and the Workspace browser-control
    MCP on port 8787. Runtime state and logs are stored outside the repository.
    This launcher requires Windows.

.EXAMPLE
    .\scripts\start-dual-mcp.ps1
    .\scripts\start-dual-mcp.ps1 -Action Status
    .\scripts\start-dual-mcp.ps1 -Action Stop
#>

[CmdletBinding()]
param(
    [ValidateSet("Start", "Status", "Stop")]
    [string]$Action = "Start",

    [string]$WorkspaceRoot,

    [ValidateRange(1, 65535)]
    [int]$PlatformPort = 8001,

    [ValidateRange(1, 65535)]
    [int]$WorkspacePort = 8787,

    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "start-dual-mcp.ps1 currently supports Windows only."
}

$OpenBBRoot = Split-Path $PSScriptRoot -Parent
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

function Get-ProcessIdentity {
    param([System.Diagnostics.Process]$Process)
    return @{
        pid = $Process.Id
        started_at = $Process.StartTime.ToUniversalTime().ToString("o")
        executable = $Process.Path
    }
}

function Test-ProcessIdentity {
    param($Identity)

    if ($null -eq $Identity -or -not $Identity.pid -or -not $Identity.started_at) {
        return $false
    }
    $process = Get-Process -Id $Identity.pid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    $expectedStart = ([datetime]$Identity.started_at).ToUniversalTime()
    $sameStart = $process.StartTime.ToUniversalTime() -eq $expectedStart
    $sameExecutable = -not $Identity.executable -or
        [string]::Equals(
            $process.Path,
            $Identity.executable,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    return $sameStart -and $sameExecutable
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
    param($Identity)

    if (-not (Test-ProcessIdentity -Identity $Identity)) {
        Write-Warning "Skipping stale or reused process ID $($Identity.pid)."
        return
    }
    $descendants = @(Get-DescendantProcessIds -ParentId $Identity.pid)
    [array]::Reverse($descendants)
    foreach ($processId in $descendants) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $Identity.pid -Force -ErrorAction SilentlyContinue
}

function ConvertTo-NativeArguments {
    param([string[]]$Arguments)

    return $Arguments | ForEach-Object {
        if ($_ -notmatch '[\s"]') {
            $_
        } elseif ($_ -match '"') {
            throw "Native argument contains an unsupported quote: $_"
        } else {
            '"' + $_ + '"'
        }
    }
}

function Write-Status {
    $state = Read-State
    if ($null -eq $state) {
        Write-Host "No dual MCP process state found at $StatePath."
        return
    }

    $platformRunning = Test-ProcessIdentity -Identity $state.platform
    $workspaceRunning = Test-ProcessIdentity -Identity $state.workspace
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
        $LauncherIdentity,
        [int]$Port,
        [string]$ErrorLog
    )

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $connection) {
            $launcherProcesses = @($LauncherIdentity.pid) +
                @(Get-DescendantProcessIds -ParentId $LauncherIdentity.pid)
            if ($connection.OwningProcess -notin $launcherProcesses) {
                throw "$Name port $Port was claimed by an unrelated process."
            }
            $serverProcess = Get-Process -Id $connection.OwningProcess -ErrorAction Stop
            return Get-ProcessIdentity -Process $serverProcess
        }
        Start-Sleep -Milliseconds 500
    }
    $launcherStatus = if (Test-ProcessIdentity -Identity $LauncherIdentity) {
        "The uv launcher is still running."
    } else {
        "The uv launcher exited."
    }
    $details = if (Test-Path -LiteralPath $ErrorLog) {
        (Get-Content -LiteralPath $ErrorLog -Tail 30) -join [Environment]::NewLine
    } else {
        "No error log was created."
    }
    throw "$Name did not listen on port $Port within $StartupTimeoutSeconds seconds. " +
        "$launcherStatus$([Environment]::NewLine)$details"
}

function Assert-PlatformCatalog {
    param([int]$Port)

    $uri = "http://127.0.0.1:$Port/mcp"
    $headers = @{ Accept = "application/json, text/event-stream" }
    $initializeBody = @{
        jsonrpc = "2.0"
        id = 1
        method = "initialize"
        params = @{
            protocolVersion = "2025-06-18"
            capabilities = @{}
            clientInfo = @{ name = "dual-mcp-readiness"; version = "1.0" }
        }
    } | ConvertTo-Json -Depth 5 -Compress
    $initialize = Invoke-WebRequest -Uri $uri -Method Post -Headers $headers `
        -ContentType "application/json" -Body $initializeBody
    $sessionId = [string]$initialize.Headers["Mcp-Session-Id"]
    if (-not $sessionId) {
        throw "OpenBB Platform MCP did not return an MCP session ID."
    }
    $headers["Mcp-Session-Id"] = $sessionId
    Invoke-WebRequest -Uri $uri -Method Post -Headers $headers `
        -ContentType "application/json" `
        -Body '{"jsonrpc":"2.0","method":"notifications/initialized"}' | Out-Null
    $catalog = Invoke-WebRequest -Uri $uri -Method Post -Headers $headers `
        -ContentType "application/json" `
        -Body '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"available_categories","arguments":{}}}'
    if ($catalog.Content -notmatch '"name":"equity"' -or
        $catalog.Content -notmatch '"total_tools":[1-9]') {
        throw "OpenBB Platform MCP started without the expected financial tool catalog."
    }
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
    foreach ($identity in @($state.platform, $state.workspace)) {
        if (Test-ProcessIdentity -Identity $identity) {
            Stop-ProcessTree -Identity $identity
        }
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped the OpenBB Platform and Workspace MCP servers."
    exit 0
}

if (-not $WorkspaceRoot) {
    $workspaceCandidates = @(
        (Join-Path $OpenBBRoot "third_party\workspace"),
        (Join-Path $OpenBBRoot "..\workspace")
    )
    $WorkspaceRoot = $workspaceCandidates |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ "backend-api\backend\workspace_mcp") } |
        Select-Object -First 1
    if (-not $WorkspaceRoot) {
        throw "Workspace MCP source was not found. Initialize third_party/workspace or pass -WorkspaceRoot."
    }
}
$WorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$WorkspaceBackend = Join-Path $WorkspaceRoot "backend-api\backend"

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
    $running = @($existing.platform, $existing.workspace) |
        Where-Object { Test-ProcessIdentity -Identity $_ }
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
    "--with-editable", (Join-Path $OpenBBRoot "openbb_platform"),
    "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\core"),
    "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\extensions\mcp_server"),
    "python", "-m", "openbb_mcp_server.app.app",
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

$platformProcess = Start-Process -FilePath "uv" `
    -ArgumentList (ConvertTo-NativeArguments -Arguments $platformArgs) -PassThru `
    -RedirectStandardOutput $PlatformLog -RedirectStandardError $PlatformErrorLog `
    -WindowStyle Hidden
$platformLauncherIdentity = Get-ProcessIdentity -Process $platformProcess
try {
    $platformIdentity = Wait-ForServer -Name "OpenBB Platform MCP" `
        -LauncherIdentity $platformLauncherIdentity -Port $PlatformPort `
        -ErrorLog $PlatformErrorLog
    Assert-PlatformCatalog -Port $PlatformPort
    $workspaceProcess = Start-Process -FilePath "uv" `
        -ArgumentList (ConvertTo-NativeArguments -Arguments $workspaceArgs) -PassThru `
        -RedirectStandardOutput $WorkspaceLog -RedirectStandardError $WorkspaceErrorLog `
        -WindowStyle Hidden
    $workspaceLauncherIdentity = Get-ProcessIdentity -Process $workspaceProcess
    $workspaceIdentity = Wait-ForServer -Name "Workspace MCP" `
        -LauncherIdentity $workspaceLauncherIdentity -Port $WorkspacePort `
        -ErrorLog $WorkspaceErrorLog
} catch {
    if ($null -ne $workspaceIdentity) {
        Stop-ProcessTree -Identity $workspaceIdentity
    } elseif ($null -ne $workspaceLauncherIdentity) {
        Stop-ProcessTree -Identity $workspaceLauncherIdentity
    }
    if ($null -ne $platformIdentity) {
        Stop-ProcessTree -Identity $platformIdentity
    } else {
        Stop-ProcessTree -Identity $platformLauncherIdentity
    }
    throw
}

$state = @{
    started_at = (Get-Date).ToString("o")
    platform = $platformIdentity + @{
        port = $PlatformPort
        endpoint = "http://127.0.0.1:$PlatformPort/mcp"
        log = $PlatformLog
        error_log = $PlatformErrorLog
    }
    workspace = $workspaceIdentity + @{
        port = $WorkspacePort
        endpoint = "http://127.0.0.1:$WorkspacePort/mcp"
        health = "http://127.0.0.1:$WorkspacePort/health"
        log = $WorkspaceLog
        error_log = $WorkspaceErrorLog
    }
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StatePath -Encoding UTF8

Write-Host "OpenBB Platform MCP: http://127.0.0.1:$PlatformPort/mcp"
Write-Host "Workspace MCP:       http://127.0.0.1:$WorkspacePort/mcp"
Write-Host "Workspace health:    http://127.0.0.1:$WorkspacePort/health"
Write-Host "Runtime logs:        $StateRoot"
