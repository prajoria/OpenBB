<#
.SYNOPSIS
    Replay both dual-MCP environments from their committed, hashed locks in a clean uv cache.

.DESCRIPTION
    Builds the Platform and Workspace MCP environments with exactly the code
    start-dual-mcp.ps1 uses (Initialize-McpLockedEnvironment: uv pip sync
    --require-hashes, then checkout editables), against an empty temporary
    UV_CACHE_DIR and environment root. Each environment must match its lock pin
    for pin and import its server module. A copy of the Workspace lock with one
    corrupted hash must then fail to install (#2282).

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

$Scratch = Join-Path ([System.IO.Path]::GetTempPath()) `
    "openbb-mcp-replay-$([guid]::NewGuid().ToString('N'))"
$EnvironmentRoot = Join-Path $Scratch "envs"
$PreviousCache = $env:UV_CACHE_DIR
$env:UV_CACHE_DIR = Join-Path $Scratch "uv-cache"
try {
    # Each build runs the lock asserter, so a returned interpreter matches its lock.
    $replays = [ordered]@{
        "Platform MCP" = @{
            Python = Get-PlatformLockedPython -OpenBBRoot $OpenBBRoot `
                -EnvironmentRoot $EnvironmentRoot
            Module = "openbb_mcp_server.app.app"
            Directory = $OpenBBRoot
        }
        "Workspace MCP" = @{
            Python = Get-WorkspaceLockedPython -OpenBBRoot $OpenBBRoot `
                -EnvironmentRoot $EnvironmentRoot
            Module = "workspace_mcp"
            Directory = $WorkspaceBackend
        }
    }
    foreach ($name in $replays.Keys) {
        $replay = $replays[$name]
        Push-Location -LiteralPath $replay.Directory
        try {
            & $replay.Python -c "import $($replay.Module)"
        } finally {
            Pop-Location
        }
        if ($LASTEXITCODE -ne 0) {
            throw "$name replay could not import $($replay.Module)."
        }
        Write-Host "$name replay matches its hash-verified lock."
    }

    # A package whose artifact matches none of its locked hashes must never
    # install. Every hash of one package is corrupted: uv, like pip, accepts an
    # artifact when any one of the package's hashes matches.
    $tamperedRoot = Join-Path $Scratch "tampered"
    $tamperedLocks = Join-Path $tamperedRoot "scripts\mcp_locks"
    New-Item -ItemType Directory -Path $tamperedLocks -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "mcp_locks\assert_lock_replay.py") `
        -Destination $tamperedLocks
    $lockText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "mcp_locks\workspace-mcp.txt") -Raw
    $block = [regex]::Match($lockText, '(?ms)^[A-Za-z0-9][^\r\n]*==.*?(?=^[A-Za-z0-9]|\z)')
    $corrupted = [regex]::Replace($block.Value, 'sha256:[0-9a-f]{64}', ('sha256:' + ('0' * 64)))
    $tampered = $lockText.Remove($block.Index, $block.Length).Insert($block.Index, $corrupted)
    if (-not $block.Success -or $tampered -eq $lockText) {
        throw "workspace-mcp.txt carries no sha256 hash to tamper with."
    }
    Set-Content -LiteralPath (Join-Path $tamperedLocks "workspace-mcp.txt") -Value $tampered -NoNewline
    $refused = $false
    try {
        Initialize-McpLockedEnvironment -OpenBBRoot $tamperedRoot -LockName "workspace-mcp.txt" `
            -EnvironmentRoot (Join-Path $Scratch "tampered-envs") | Out-Null
    } catch {
        if ($_.Exception.Message -notlike "*failed its hash-verified install*") {
            throw
        }
        $refused = $true
    }
    if (-not $refused) {
        throw "A lock with a tampered hash installed; hash verification is not enforced."
    }
    Write-Host "Tampered lock refused before install."
} finally {
    $env:UV_CACHE_DIR = $PreviousCache
    Remove-Item -LiteralPath $Scratch -Recurse -Force -ErrorAction SilentlyContinue
}
