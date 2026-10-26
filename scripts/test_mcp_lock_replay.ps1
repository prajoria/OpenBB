<#
.SYNOPSIS
    Replay both dual-MCP environments from their committed locks in a clean uv cache.

.DESCRIPTION
    Builds the Platform and Workspace MCP environments with exactly the uv
    arguments start-dual-mcp.ps1 uses, against an empty temporary UV_CACHE_DIR,
    then asserts each environment matches its lock pin for pin and imports its
    server module. Fails if either environment diverges from its lock.

.PARAMETER WorkspaceRoot
    Workspace checkout containing backend-api\backend\workspace_mcp. Defaults
    to third_party\workspace.

.EXAMPLE
    .\scripts\test_mcp_lock_replay.ps1
#>

[CmdletBinding()]
param(
    [string]$WorkspaceRoot
)

#Requires -Version 7.0
$ErrorActionPreference = "Stop"

$OpenBBRoot = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot "mcp_stack_lifecycle.psm1") -Force

if (-not $WorkspaceRoot) {
    $WorkspaceRoot = Join-Path $OpenBBRoot "third_party\workspace"
}
$WorkspaceBackend = Join-Path ([System.IO.Path]::GetFullPath($WorkspaceRoot)) `
    "backend-api\backend"
if (-not (Test-Path -LiteralPath (Join-Path $WorkspaceBackend "workspace_mcp"))) {
    throw "Workspace MCP package not found under $WorkspaceBackend."
}

$Asserter = Join-Path $PSScriptRoot "mcp_locks\assert_lock_replay.py"
$Replays = [ordered]@{
    "Platform MCP" = @{
        Arguments = @(Get-PlatformUvArguments -OpenBBRoot $OpenBBRoot)
        Lock = "platform-mcp.txt"
        Module = "openbb_mcp_server.app.app"
    }
    "Workspace MCP" = @{
        Arguments = @(Get-WorkspaceUvArguments -OpenBBRoot $OpenBBRoot `
            -WorkspaceBackend $WorkspaceBackend)
        Lock = "workspace-mcp.txt"
        Module = "workspace_mcp"
    }
}

$PreviousCache = $env:UV_CACHE_DIR
$ReplayCache = Join-Path ([System.IO.Path]::GetTempPath()) `
    "openbb-mcp-replay-$([guid]::NewGuid().ToString('N'))"
$env:UV_CACHE_DIR = $ReplayCache
try {
    foreach ($name in $Replays.Keys) {
        $replay = $Replays[$name]
        $lock = Join-Path $PSScriptRoot "mcp_locks\$($replay.Lock)"
        & uv @($replay.Arguments) python $Asserter $lock
        if ($LASTEXITCODE -ne 0) {
            throw "$name replay diverged from its lock."
        }
        & uv @($replay.Arguments) python -c "import $($replay.Module)"
        if ($LASTEXITCODE -ne 0) {
            throw "$name replay could not import $($replay.Module)."
        }
        Write-Host "$name replay matches $($replay.Lock)."
    }
} finally {
    $env:UV_CACHE_DIR = $PreviousCache
    Remove-Item -LiteralPath $ReplayCache -Recurse -Force -ErrorAction SilentlyContinue
}
