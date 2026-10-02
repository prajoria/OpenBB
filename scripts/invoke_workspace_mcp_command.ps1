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
    [string]$BackendUrl = "http://127.0.0.1:8000",
    [ValidateRange(1, 3600)]
    [int]$ChildTimeoutSeconds = 300,
    [ValidateRange(1, 300)]
    [int]$LifecycleLockTimeoutSeconds = 30
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
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$McpToken,
        [Parameter(Mandatory)][string]$McpUrl,
        [ValidateRange(1, 3600)]
        [int]$TimeoutSeconds = 300
    )

    $command = @(
        Get-Command $FilePath -CommandType Application -ErrorAction Stop
    ) | Where-Object {
        $_.Source -and (Test-Path -LiteralPath $_.Source -PathType Leaf)
    } | Select-Object -First 1
    if (-not $command) {
        throw "Workspace MCP child executable is unavailable."
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $command.Source
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    foreach ($argument in $ArgumentList) {
        $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.Environment["WORKSPACE_MCP_TOKEN"] = $McpToken
    $startInfo.Environment["WORKSPACE_MCP_URL"] = $McpUrl

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Workspace MCP child command failed."
        }
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                $process.Kill($true)
                if (-not $process.WaitForExit(5000)) {
                    throw "Workspace MCP child process cleanup failed."
                }
            } catch {
                throw "Workspace MCP child process cleanup failed."
            }
            throw "Workspace MCP child command timed out."
        }
        return [int]$process.ExitCode
    } finally {
        $process.Dispose()
    }
}

function Get-WorkspaceMcpTokenUuid {
    param([object]$Token)

    if ($null -eq $Token) {
        return $null
    }
    $uuidProperty = $Token.PSObject.Properties["uuid"]
    if ($null -eq $uuidProperty) {
        return $null
    }
    $parsed = [guid]::Empty
    if (-not [guid]::TryParse([string]$uuidProperty.Value, [ref]$parsed)) {
        return $null
    }
    return $parsed.ToString()
}

function Find-CreatedWorkspaceMcpTokenUuid {
    param(
        [Parameter(Mandatory)][object[]]$Tokens,
        [Parameter(Mandatory)][string]$TokenName,
        [Parameter(Mandatory)]
        [System.Collections.Generic.HashSet[string]]$ExistingTokenUuids
    )

    $matches = @(
        foreach ($token in $Tokens) {
            $nameProperty = $token.PSObject.Properties["name"]
            $uuid = Get-WorkspaceMcpTokenUuid -Token $token
            if (
                $null -ne $nameProperty -and
                [string]$nameProperty.Value -eq $TokenName -and
                $uuid -and
                -not $ExistingTokenUuids.Contains($uuid)
            ) {
                $uuid
            }
        }
    )
    if ($matches.Count -ne 1) {
        throw "Workspace MCP token recovery failed."
    }
    return $matches[0]
}

function Invoke-WorkspaceMcpChildWithTokenCore {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = (Get-Location).Path,
        [string]$BackendUrl = "http://127.0.0.1:8000",
        [ValidateRange(1, 3600)]
        [int]$ChildTimeoutSeconds = 300
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
    $cleanupFailure = $null

    try {
        $loginBody = @{
            email = $credential.Email
            password = $credential.Password
            remember = $false
            ip_address = ""
            source = "excel"
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
            $tokensBeforeCreate = @(
                Invoke-RestMethod `
                    -Uri "$BackendUrl/pro/workspace-mcp/tokens" `
                    -Method Get `
                    -Headers $sessionHeaders `
                    -ConnectionTimeoutSeconds 3 `
                    -OperationTimeoutSeconds 10
            )
        } catch {
            throw "Workspace MCP token creation failed."
        }
        $existingTokenUuids = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::OrdinalIgnoreCase
        )
        foreach ($token in $tokensBeforeCreate) {
            $existingUuid = Get-WorkspaceMcpTokenUuid -Token $token
            if ($existingUuid) {
                $null = $existingTokenUuids.Add($existingUuid)
            }
        }

        $tokenName = "workspace-bench-$([guid]::NewGuid().ToString('N'))"
        $createAttempted = $false
        try {
            $createAttempted = $true
            $created = Invoke-RestMethod `
                -Uri "$BackendUrl/pro/workspace-mcp/tokens" `
                -Method Post `
                -Headers $sessionHeaders `
                -ContentType "application/json" `
                -Body (@{ name = $tokenName } | ConvertTo-Json -Compress) `
                -ConnectionTimeoutSeconds 3 `
                -OperationTimeoutSeconds 10
            $mcpTokenUuid = Get-WorkspaceMcpTokenUuid -Token $created
            $tokenProperty = $created.PSObject.Properties["token"]
            if (
                -not $mcpTokenUuid -or
                $null -eq $tokenProperty -or
                $tokenProperty.Value -isnot [string] -or
                [string]::IsNullOrWhiteSpace($tokenProperty.Value)
            ) {
                throw "Invalid MCP token response."
            }
        } catch {
            if ($createAttempted -and -not $mcpTokenUuid) {
                try {
                    $tokensAfterCreate = @(
                        Invoke-RestMethod `
                            -Uri "$BackendUrl/pro/workspace-mcp/tokens" `
                            -Method Get `
                            -Headers $sessionHeaders `
                            -ConnectionTimeoutSeconds 3 `
                            -OperationTimeoutSeconds 10
                    )
                    $mcpTokenUuid = Find-CreatedWorkspaceMcpTokenUuid `
                        -Tokens $tokensAfterCreate `
                        -TokenName $tokenName `
                        -ExistingTokenUuids $existingTokenUuids
                } catch {
                    throw "Workspace MCP token recovery failed."
                }
            }
            throw "Workspace MCP token creation failed."
        }

        try {
            $exitCode = Invoke-WorkspaceMcpChildCommand `
                -FilePath $FilePath `
                -ArgumentList $ArgumentList `
                -WorkingDirectory $resolvedWorkingDirectory `
                -McpToken ([string]$created.token) `
                -McpUrl "$BackendUrl/mcp" `
                -TimeoutSeconds $ChildTimeoutSeconds
            if ($exitCode -ne 0) {
                throw "Workspace MCP child command returned a nonzero exit code."
            }
            return $exitCode
        } catch {
            if (
                $_.Exception.Message -eq
                    "Workspace MCP child command timed out." -or
                $_.Exception.Message -eq
                    "Workspace MCP child process cleanup failed."
            ) {
                throw $_.Exception.Message
            }
            throw "Workspace MCP child command failed."
        }
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

function Invoke-WorkspaceMcpChildWithToken {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = (Get-Location).Path,
        [string]$BackendUrl = "http://127.0.0.1:8000",
        [ValidateRange(1, 3600)]
        [int]$ChildTimeoutSeconds = 300,
        [ValidateRange(1, 300)]
        [int]$LifecycleLockTimeoutSeconds = 30
    )

    $mutex = [System.Threading.Mutex]::new(
        $false,
        "Local\OpenBBWorkspaceMcpManagedAdmin"
    )
    $lockAcquired = $false
    try {
        try {
            $lockAcquired = $mutex.WaitOne($LifecycleLockTimeoutSeconds * 1000)
        } catch [System.Threading.AbandonedMutexException] {
            $lockAcquired = $true
        }
        if (-not $lockAcquired) {
            throw "Workspace MCP token lifecycle is already active."
        }
        return Invoke-WorkspaceMcpChildWithTokenCore `
            -WorkspaceRoot $WorkspaceRoot `
            -FilePath $FilePath `
            -ArgumentList $ArgumentList `
            -WorkingDirectory $WorkingDirectory `
            -BackendUrl $BackendUrl `
            -ChildTimeoutSeconds $ChildTimeoutSeconds
    } finally {
        if ($lockAcquired) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
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
        -BackendUrl $BackendUrl `
        -ChildTimeoutSeconds $ChildTimeoutSeconds `
        -LifecycleLockTimeoutSeconds $LifecycleLockTimeoutSeconds
    exit $exitCode
}
