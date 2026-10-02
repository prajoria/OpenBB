#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Run one child command with a short-lived self-hosted Workspace MCP token.
#>

[CmdletBinding()]
param(
    [string]$WorkspaceRoot,
    [string]$FilePath,
    [string[]]$ArgumentList = @(),
    [string]$WorkingDirectory = (Get-Location).Path,
    [string]$BackendUrl = "http://127.0.0.1:8000"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-WorkspaceMcpCredentialIsIgnored {
    param(
        [Parameter(Mandatory)][string]$ResolvedWorkspaceRoot,
        [Parameter(Mandatory)][string]$CredentialPath
    )

    $workspaceSourceRoot = Join-Path $ResolvedWorkspaceRoot "third_party\workspace"
    $relativePath = [System.IO.Path]::GetRelativePath(
        $workspaceSourceRoot,
        $CredentialPath
    )
    & git -C $workspaceSourceRoot check-ignore -q -- $relativePath
    if ($LASTEXITCODE -ne 0) {
        throw "Workspace managed credential file is not ignored."
    }
}

function Invoke-WorkspaceMcpChildCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    $command = Get-Command $FilePath -CommandType Application -ErrorAction Stop
    Push-Location $WorkingDirectory
    try {
        & $command.Source @ArgumentList | Out-Host
        return [int]$LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Invoke-WorkspaceMcpChildWithToken {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = (Get-Location).Path,
        [string]$BackendUrl = "http://127.0.0.1:8000"
    )

    if ($BackendUrl -ne "http://127.0.0.1:8000") {
        throw "Workspace MCP helper only supports the exact self-hosted backend."
    }

    $resolvedWorkspaceRoot = (Resolve-Path $WorkspaceRoot).Path
    $resolvedWorkingDirectory = (Resolve-Path $WorkingDirectory).Path
    $credentialPath = Join-Path $resolvedWorkspaceRoot (
        "third_party\workspace\backend-api\backend\" +
        "workspace-admin-credentials.secrets"
    )
    if (-not (Test-Path $credentialPath -PathType Leaf)) {
        throw "Workspace managed credential file is missing."
    }
    Assert-WorkspaceMcpCredentialIsIgnored `
        -ResolvedWorkspaceRoot $resolvedWorkspaceRoot `
        -CredentialPath $credentialPath

    try {
        $credential = Get-Content $credentialPath -Raw | ConvertFrom-Json
        if (
            $credential.Email -isnot [string] -or
            [string]::IsNullOrWhiteSpace($credential.Email) -or
            $credential.Password -isnot [string] -or
            [string]::IsNullOrWhiteSpace($credential.Password)
        ) {
            throw "Invalid credential shape."
        }
    } catch {
        throw "Workspace managed credential file is invalid."
    }

    $priorToken = [Environment]::GetEnvironmentVariable(
        "WORKSPACE_MCP_TOKEN",
        "Process"
    )
    $priorUrl = [Environment]::GetEnvironmentVariable(
        "WORKSPACE_MCP_URL",
        "Process"
    )
    $sessionToken = $null
    $mcpTokenUuid = $null
    $childFailure = $false
    $cleanupFailure = $null

    try {
        $loginBody = @{
            email = $credential.Email
            password = $credential.Password
            remember = $false
        } | ConvertTo-Json -Compress
        try {
            $login = Invoke-RestMethod `
                -Uri "$BackendUrl/pro/login" `
                -Method Post `
                -ContentType "application/json" `
                -Body $loginBody `
                -ConnectionTimeoutSeconds 3 `
                -OperationTimeoutSeconds 10
            if (
                $login.access_token -isnot [string] -or
                [string]::IsNullOrWhiteSpace($login.access_token)
            ) {
                throw "Missing session token."
            }
            $sessionToken = $login.access_token
        } catch {
            throw "Workspace managed administrator login failed."
        }

        $sessionHeaders = @{ Authorization = "Bearer $sessionToken" }
        try {
            $created = Invoke-RestMethod `
                -Uri "$BackendUrl/pro/workspace-mcp/tokens" `
                -Method Post `
                -Headers $sessionHeaders `
                -ContentType "application/json" `
                -Body (@{
                    name = "workspace-bench-$([guid]::NewGuid().ToString('N'))"
                } | ConvertTo-Json -Compress) `
                -ConnectionTimeoutSeconds 3 `
                -OperationTimeoutSeconds 10
            if (
                $null -eq $created.uuid -or
                $created.token -isnot [string] -or
                [string]::IsNullOrWhiteSpace($created.token)
            ) {
                throw "Invalid MCP token response."
            }
            $mcpTokenUuid = [string]$created.uuid
        } catch {
            throw "Workspace MCP token creation failed."
        }

        [Environment]::SetEnvironmentVariable(
            "WORKSPACE_MCP_TOKEN",
            $created.token,
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "WORKSPACE_MCP_URL",
            "$BackendUrl/mcp",
            "Process"
        )
        try {
            return Invoke-WorkspaceMcpChildCommand `
                -FilePath $FilePath `
                -ArgumentList $ArgumentList `
                -WorkingDirectory $resolvedWorkingDirectory
        } catch {
            $childFailure = $true
            throw
        }
    } catch {
        if ($childFailure) {
            throw "Workspace MCP child command failed."
        }
        throw
    } finally {
        [Environment]::SetEnvironmentVariable(
            "WORKSPACE_MCP_TOKEN",
            $priorToken,
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "WORKSPACE_MCP_URL",
            $priorUrl,
            "Process"
        )

        if ($sessionToken -and $mcpTokenUuid) {
            try {
                Invoke-RestMethod `
                    -Uri "$BackendUrl/pro/workspace-mcp/tokens/$mcpTokenUuid" `
                    -Method Delete `
                    -Headers @{ Authorization = "Bearer $sessionToken" } `
                    -ConnectionTimeoutSeconds 3 `
                    -OperationTimeoutSeconds 10 | Out-Null
            } catch {
                $cleanupFailure = "Workspace MCP token revocation failed."
            }
        }
        if ($sessionToken) {
            try {
                Invoke-RestMethod `
                    -Uri "$BackendUrl/logout" `
                    -Method Get `
                    -Headers @{ Authorization = "Bearer $sessionToken" } `
                    -ConnectionTimeoutSeconds 3 `
                    -OperationTimeoutSeconds 10 | Out-Null
            } catch {
                if (-not $cleanupFailure) {
                    $cleanupFailure = "Workspace administrator logout failed."
                }
            }
        }
        if ($cleanupFailure) {
            throw $cleanupFailure
        }
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    if (
        [string]::IsNullOrWhiteSpace($WorkspaceRoot) -or
        [string]::IsNullOrWhiteSpace($FilePath)
    ) {
        throw "WorkspaceRoot and FilePath are required."
    }
    $exitCode = Invoke-WorkspaceMcpChildWithToken `
        -WorkspaceRoot $WorkspaceRoot `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -BackendUrl $BackendUrl
    exit $exitCode
}
