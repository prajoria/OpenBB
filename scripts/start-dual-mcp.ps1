#!/usr/bin/env pwsh
#Requires -Version 7.0
<#
.SYNOPSIS
    Manage the OpenBB Platform and Workspace MCP servers as separate processes.

.DESCRIPTION
    Starts the OpenBB Platform MCP on port 8001 and the Workspace browser-control
    MCP on port 8787. Runtime state and logs are stored outside the repository.
    This launcher requires Windows.

.EXAMPLE
    .\scripts\start-dual-mcp.ps1
    .\scripts\start-dual-mcp.ps1 -Profile portfolio-read
    .\scripts\start-dual-mcp.ps1 -Action Status
    .\scripts\start-dual-mcp.ps1 -Action Stop
#>

[CmdletBinding()]
param(
    [ValidateSet("Start", "Status", "Stop")]
    [string]$Action = "Start",

    [ValidateSet("platform-standard", "portfolio-read", "portfolio-ops")]
    [string]$Profile = "platform-standard",

    [string]$WorkspaceRoot,

    [string]$PortfolioPython,

    [string]$PortfolioRoot,

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
Import-Module (Join-Path $PSScriptRoot "mcp_stack_lifecycle.psm1") -Force
$StateRoot = Join-Path $env:LOCALAPPDATA "OpenBB\mcp-stack"
$StatePath = Join-Path $StateRoot "processes.json"
$PlatformLog = Join-Path $StateRoot "openbb-platform-mcp.log"
$PlatformErrorLog = Join-Path $StateRoot "openbb-platform-mcp.error.log"
$WorkspaceLog = Join-Path $StateRoot "workspace-mcp.log"
$WorkspaceErrorLog = Join-Path $StateRoot "workspace-mcp.error.log"
$RuntimeResolutionArtifact = Join-Path $StateRoot "runtime-resolution.json"

function Read-State {
    return Read-ProcessState -StatePath $StatePath
}

function Write-Status {
    $state = Read-State
    if ($null -eq $state) {
        Write-Host "No dual MCP process state found at $StatePath."
        return
    }

    if ($null -ne $state.platform) {
        [pscustomobject]@{
            Server = "OpenBB Platform MCP"
            Profile = $state.platform.profile
            PID = $state.platform.pid
            Running = Test-ProcessIdentity -Identity $state.platform
            Endpoint = $state.platform.endpoint
            Listening = $state.platform.port -and (
                Test-PortListening -Port $state.platform.port
            )
            Log = $state.platform.log
        }
    }
    if ($null -ne $state.workspace) {
        [pscustomobject]@{
            Server = "Workspace MCP"
            PID = $state.workspace.pid
            Running = Test-ProcessIdentity -Identity $state.workspace
            Endpoint = $state.workspace.endpoint
            Listening = $state.workspace.port -and (
                Test-PortListening -Port $state.workspace.port
            )
            Log = $state.workspace.log
        }
    }
}

function Assert-PlatformCatalog {
    param(
        [int]$Port,
        [string]$Authorization
    )

    $uri = "http://127.0.0.1:$Port/mcp"
    $headers = @{ Accept = "application/json, text/event-stream" }
    if ($Authorization) {
        $headers["Authorization"] = $Authorization
    }
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
        -ContentType "application/json" -Body $initializeBody `
        -TimeoutSec $StartupTimeoutSeconds
    $sessionId = [string]$initialize.Headers["Mcp-Session-Id"]
    if (-not $sessionId) {
        throw "OpenBB Platform MCP did not return an MCP session ID."
    }
    $headers["Mcp-Session-Id"] = $sessionId
    Invoke-WebRequest -Uri $uri -Method Post -Headers $headers `
        -ContentType "application/json" `
        -Body '{"jsonrpc":"2.0","method":"notifications/initialized"}' `
        -TimeoutSec $StartupTimeoutSeconds | Out-Null
    $catalog = Invoke-WebRequest -Uri $uri -Method Post -Headers $headers `
        -ContentType "application/json" `
        -Body '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"available_categories","arguments":{}}}' `
        -TimeoutSec $StartupTimeoutSeconds
    if ($catalog.Content -notmatch '"name":\s*"equity"' -or
        $catalog.Content -notmatch '"total_tools":\s*[1-9]') {
        throw "OpenBB Platform MCP started without the expected financial tool catalog."
    }
}

$StartMutex = [System.Threading.Mutex]::new(
    $false,
    "Local\OpenBB.DualMcp.Start"
)
$MutexAcquired = if ($Action -eq "Start") {
    $StartMutex.WaitOne(0)
} else {
    $StartMutex.WaitOne($StartupTimeoutSeconds * 1000)
}
if (-not $MutexAcquired) {
    $StartMutex.Dispose()
    throw "Another dual MCP lifecycle operation is already in progress."
}

try {
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
    Stop-PartialStack `
        -PlatformIdentity $state.platform `
        -PlatformLauncherIdentity $state.platform_launcher `
        -WorkspaceIdentity $state.workspace `
        -WorkspaceLauncherIdentity $state.workspace_launcher
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
    Clear-StaleProcessState -State $existing -StatePath $StatePath
}
foreach ($port in @($PlatformPort, $WorkspacePort)) {
    if (Test-PortListening -Port $port) {
        throw "Port $port is already in use."
    }
}

New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
foreach ($runtimeFile in @(
    $PlatformLog,
    $PlatformErrorLog,
    $WorkspaceLog,
    $WorkspaceErrorLog,
    $RuntimeResolutionArtifact
)) {
    Remove-Item -LiteralPath $runtimeFile -Force -ErrorAction SilentlyContinue
}

$LauncherManifestPath = Join-Path $OpenBBRoot `
    "openbb_platform\extensions\mcp_server\openbb_mcp_server\assets\runtime_profiles.json"
$LauncherManifest = Get-Content -LiteralPath $LauncherManifestPath -Raw |
    ConvertFrom-Json
$LauncherProfile = $LauncherManifest.profiles.$Profile
if ($null -eq $LauncherProfile) {
    throw "Runtime profile '$Profile' is not registered in $LauncherManifestPath."
}
$Installation = [string]$LauncherProfile.installation
$ProfileRepositoryRoot = $OpenBBRoot

if ($Installation -eq "portfolio_venv") {
    $portfolioEnvironment = Resolve-PortfolioEnvironment `
        -OpenBBRoot $OpenBBRoot `
        -PortfolioPython $PortfolioPython `
        -PortfolioRoot $PortfolioRoot
    $PlatformExecutable = $portfolioEnvironment.Python
    $ProfileRepositoryRoot = $portfolioEnvironment.RepositoryRoot
    $platformEnvironmentArgs = @()
} else {
    $PlatformExecutable = "uv"
    $platformEnvironmentArgs = @(
        "run",
        "--no-project",
        "--python", "3.13",
        # FastMCP 3.4.6 requires Starlette >=1.0.1, which conflicts with Platform FastAPI.
        "--with", "fastmcp==3.4.0",
        "--with-editable", (Join-Path $OpenBBRoot "openbb_platform"),
        "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\core"),
        "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\extensions\platform_api"),
        "--with-editable", (Join-Path $OpenBBRoot "openbb_platform\extensions\mcp_server")
    )
}

$RuntimeManifestPath = Join-Path $ProfileRepositoryRoot `
    "openbb_platform\extensions\mcp_server\openbb_mcp_server\assets\runtime_profiles.json"
$RuntimeManifest = Get-Content -LiteralPath $RuntimeManifestPath -Raw |
    ConvertFrom-Json
$RuntimeProfile = $RuntimeManifest.profiles.$Profile
if ($null -eq $RuntimeProfile) {
    throw "Runtime profile '$Profile' is not registered in $RuntimeManifestPath."
}
if ([string]$RuntimeProfile.installation -ne $Installation) {
    throw "Profile '$Profile' installation differs between launcher and selected checkout."
}
if (-not $RuntimeProfile.policy_profile -or -not $RuntimeProfile.app.target) {
    throw "Profile '$Profile' is missing its policy or application target."
}
if (
    [string]$RuntimeProfile.policy_profile -ne
        [string]$LauncherProfile.policy_profile -or
    [string]$RuntimeProfile.app.kind -ne [string]$LauncherProfile.app.kind -or
    [string]$RuntimeProfile.app.target -ne [string]$LauncherProfile.app.target
) {
    throw "Profile '$Profile' differs between launcher and selected checkout."
}

$env:OPENBB_MCP_RUNTIME_PROFILE = $Profile
$env:OPENBB_MCP_CAPABILITY_PROFILE = [string]$RuntimeProfile.policy_profile
$env:OPENBB_MCP_INSTALLATION_KIND = $Installation
$env:OPENBB_MCP_APP_TARGET = [string]$RuntimeProfile.app.target
$ServerAuthorization = Get-ServerAuthHeader `
    -SerializedCredentials $env:OPENBB_MCP_SERVER_AUTH `
    -Required:($Profile -eq "portfolio-ops")

$PlatformAppTarget = [string]$RuntimeProfile.app.target
if ($PlatformAppTarget.EndsWith(".py") -and
    -not [System.IO.Path]::IsPathRooted($PlatformAppTarget)) {
    $PlatformAppTarget = Join-Path $ProfileRepositoryRoot $PlatformAppTarget
}
$RuntimeVerifier = Join-Path $ProfileRepositoryRoot "scripts\verify_mcp_runtime.py"
$pythonPrefix = if ($Installation -eq "isolated_uv") {
    @("python")
} else {
    @()
}
$resolutionArgs = $platformEnvironmentArgs + $pythonPrefix + @(
    $RuntimeVerifier,
    "--profile", $Profile,
    "--installation", $Installation,
    "--repository-root", $ProfileRepositoryRoot,
    "--artifact", $RuntimeResolutionArtifact
)
& $PlatformExecutable @resolutionArgs
if ($LASTEXITCODE -ne 0) {
    throw "OpenBB Platform runtime provenance validation failed for '$Profile'."
}
$platformArgs = $platformEnvironmentArgs + $pythonPrefix + @(
    "-m", "openbb_mcp_server.app.app",
    "--host", "127.0.0.1",
    "--port", $PlatformPort,
    "--transport", "streamable-http",
    "--tool-discovery"
)
if ($RuntimeProfile.app.kind -eq "custom") {
    $platformArgs += @("--app", $PlatformAppTarget)
}
$workspaceArgs = @(
    "run",
    "--no-project",
    "--python", "3.13",
    "--with", "fastmcp==3.4.6",
    "--with", "openbb-ai==2.1.0",
    "--with", "pydantic==2.12.5",
    "--with", "starlette==1.6.0",
    "--with", "uvicorn==0.52.3",
    "--directory", $WorkspaceBackend,
    "python", "-m", "workspace_mcp",
    "--host", "127.0.0.1",
    "--port", $WorkspacePort,
    "--cors-allow", "https://pro.openbb.co"
)

$platformProcess = Start-Process -FilePath $PlatformExecutable `
    -ArgumentList (ConvertTo-NativeArguments -Arguments $platformArgs) -PassThru `
    -RedirectStandardOutput $PlatformLog -RedirectStandardError $PlatformErrorLog `
    -WindowStyle Hidden
$platformLauncherIdentity = Get-ProcessIdentity -Process $platformProcess
$partialState = @{
    started_at = (Get-Date).ToString("o")
    platform_launcher = $platformLauncherIdentity
}
$partialState | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $StatePath -Encoding UTF8
try {
    $platformIdentity = Wait-ForOwnedListener -Name "OpenBB Platform MCP" `
        -LauncherIdentity $platformLauncherIdentity -Port $PlatformPort `
        -ErrorLog $PlatformErrorLog -TimeoutSeconds $StartupTimeoutSeconds
    Assert-PlatformCatalog -Port $PlatformPort `
        -Authorization $ServerAuthorization
    $workspaceProcess = Start-Process -FilePath "uv" `
        -ArgumentList (ConvertTo-NativeArguments -Arguments $workspaceArgs) -PassThru `
        -RedirectStandardOutput $WorkspaceLog -RedirectStandardError $WorkspaceErrorLog `
        -WindowStyle Hidden
    $workspaceLauncherIdentity = Get-ProcessIdentity -Process $workspaceProcess
    $partialState.platform = $platformIdentity + @{
        profile = $Profile
        installation = $Installation
        port = $PlatformPort
        endpoint = "http://127.0.0.1:$PlatformPort/mcp"
        log = $PlatformLog
        error_log = $PlatformErrorLog
    }
    $partialState.workspace_launcher = $workspaceLauncherIdentity
    $partialState | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $StatePath -Encoding UTF8
    $workspaceIdentity = Wait-ForOwnedListener -Name "Workspace MCP" `
        -LauncherIdentity $workspaceLauncherIdentity -Port $WorkspacePort `
        -ErrorLog $WorkspaceErrorLog -TimeoutSeconds $StartupTimeoutSeconds
} catch {
    Stop-PartialStack `
        -PlatformIdentity $platformIdentity `
        -PlatformLauncherIdentity $platformLauncherIdentity `
        -WorkspaceIdentity $workspaceIdentity `
        -WorkspaceLauncherIdentity $workspaceLauncherIdentity
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    throw
}

$state = @{
    started_at = (Get-Date).ToString("o")
    platform_launcher = $platformLauncherIdentity
    platform = $platformIdentity + @{
        profile = $Profile
        installation = $Installation
        port = $PlatformPort
        endpoint = "http://127.0.0.1:$PlatformPort/mcp"
        log = $PlatformLog
        error_log = $PlatformErrorLog
    }
    workspace_launcher = $workspaceLauncherIdentity
    workspace = $workspaceIdentity + @{
        port = $WorkspacePort
        endpoint = "http://127.0.0.1:$WorkspacePort/mcp"
        health = "http://127.0.0.1:$WorkspacePort/health"
        log = $WorkspaceLog
        error_log = $WorkspaceErrorLog
    }
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StatePath -Encoding UTF8

Write-Host "OpenBB Platform MCP [$Profile]: http://127.0.0.1:$PlatformPort/mcp"
if ($Installation -eq "portfolio_venv") {
    Write-Host "Portfolio Python:    $PlatformExecutable"
    Write-Host "Portfolio checkout:  $ProfileRepositoryRoot"
}
Write-Host "Workspace MCP:       http://127.0.0.1:$WorkspacePort/mcp"
Write-Host "Workspace health:    http://127.0.0.1:$WorkspacePort/health"
Write-Host "Runtime logs:        $StateRoot"
} finally {
    $StartMutex.ReleaseMutex()
    $StartMutex.Dispose()
}
