#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Verify the running self-hosted Workspace without changing its state.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Join-Path $repoRoot "third_party\workspace"
$backendRoot = Join-Path $workspaceRoot "backend-api"
$frontendRoot = Join-Path $workspaceRoot "terminalpro"
$composeFile = Join-Path $backendRoot "docker-compose-local-dev-sqlite.yml"
$composeOverride = Join-Path $backendRoot "backend\workspace-compose.secrets"
$adminCredentials = Join-Path $backendRoot "backend\workspace-admin-credentials.secrets"
$composeProject = "openbb-workspace-2110"
$expectedServices = @("fastapi", "redis", "rq_worker")

function Invoke-WorkspaceVerificationCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][string]$FailureMessage
    )

    $output = & $FilePath @ArgumentList 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
    return @($output)
}

function Assert-WorkspaceExactServices {
    param([Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Actual)

    $expected = @($expectedServices | Sort-Object)
    $observed = @($Actual | Where-Object { $_ } | Sort-Object -Unique)
    if (
        $observed.Count -ne $expected.Count -or
        (Compare-Object -ReferenceObject $expected -DifferenceObject $observed)
    ) {
        throw "Workspace Compose services do not exactly match the expected running set."
    }
}

function Assert-WorkspaceComposeState {
    foreach ($requiredPath in @($composeFile, $composeOverride)) {
        if (-not (Test-Path $requiredPath -PathType Leaf)) {
            throw "Workspace setup is incomplete."
        }
    }
    $baseArguments = @(
        "compose", "--project-name", $composeProject,
        "--file", $composeFile, "--file", $composeOverride
    )
    $configured = Invoke-WorkspaceVerificationCommand -FilePath "docker" `
        -ArgumentList ($baseArguments + @("config", "--services")) `
        -FailureMessage "Unable to inspect Workspace Compose configuration."
    Assert-WorkspaceExactServices -Actual $configured

    $running = Invoke-WorkspaceVerificationCommand -FilePath "docker" `
        -ArgumentList ($baseArguments + @(
            "ps", "--status", "running", "--services"
        )) -FailureMessage "Unable to inspect running Workspace services."
    Assert-WorkspaceExactServices -Actual $running
}

function Assert-WorkspaceLoopbackListeners {
    $listeners = @(
        Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $_.LocalPort -in 8000, 1420 }
    )
    foreach ($port in @(8000, 1420)) {
        $portListeners = @($listeners | Where-Object { $_.LocalPort -eq $port })
        if (
            $portListeners.Count -eq 0 -or
            @($portListeners | Where-Object {
                $_.LocalAddress -ne "127.0.0.1"
            }).Count -gt 0
        ) {
            throw "Workspace listener validation failed."
        }
    }
}

function Assert-WorkspaceHealth {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Uri,
        [ValidateRange(1, 30)][int]$Attempts = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri `
                -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        } catch {
            if ($attempt -eq $Attempts) {
                throw "$Name health check failed after $Attempts attempts."
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name health check failed after $Attempts attempts."
}

function Assert-WorkspaceManagedAdminLogin {
    param([Parameter(Mandatory)][pscustomobject]$Credential)

    $requestBody = @{
        email = $Credential.Email
        password = $Credential.Password
        remember = $false
    } | ConvertTo-Json -Compress
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/pro/login" -Method Post `
            -ContentType "application/json" -Body $requestBody `
            -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 10
        if ($response.StatusCode -ne 200) {
            throw "Unexpected status."
        }
    } catch {
        throw "Workspace managed administrator login check failed."
    }
}

function Get-WorkspaceHeaderValue {
    param(
        [Parameter(Mandatory)][object]$Headers,
        [Parameter(Mandatory)][string]$Name
    )

    $value = $Headers[$Name]
    if ($null -eq $value) {
        return ""
    }
    return [string]($value -join ",")
}

function Assert-WorkspaceCorsContractCore {
    $preflightHeaders = @{
        "Access-Control-Request-Method" = "POST"
        "Access-Control-Request-Headers" = "content-type"
    }
    $allowedOrigin = "http://127.0.0.1:1420"
    $allowedResponse = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/pro/login" -Method Options `
        -Headers ($preflightHeaders + @{ Origin = $allowedOrigin }) `
        -SkipHttpErrorCheck -ConnectionTimeoutSeconds 3 `
        -OperationTimeoutSeconds 5
    if (
        $allowedResponse.StatusCode -ne 200 -or
        (Get-WorkspaceHeaderValue -Headers $allowedResponse.Headers `
            -Name "Access-Control-Allow-Origin") -ne $allowedOrigin
    ) {
        throw "Workspace allowed-origin CORS check failed."
    }

    $rejectedResponse = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/pro/login" -Method Options `
        -Headers ($preflightHeaders + @{ Origin = "http://localhost:1420" }) `
        -SkipHttpErrorCheck -ConnectionTimeoutSeconds 3 `
        -OperationTimeoutSeconds 5
    if (
        $rejectedResponse.StatusCode -ne 400 -or
        (Get-WorkspaceHeaderValue -Headers $rejectedResponse.Headers `
            -Name "Access-Control-Allow-Origin")
    ) {
        throw "Workspace rejected-origin CORS check failed."
    }
}

function Assert-WorkspaceCorsContract {
    try {
        Assert-WorkspaceCorsContractCore
    } catch {
        throw "Workspace CORS verification failed."
    }
}

function Assert-WorkspaceSourceAndRuntimeState {
    $gitlink = Invoke-WorkspaceVerificationCommand -FilePath "git" `
        -ArgumentList @(
            "-C", $repoRoot, "ls-tree", "HEAD", "third_party/workspace"
        ) -FailureMessage "Unable to inspect the pinned Workspace source."
    if (
        ($gitlink -join "") -notmatch
            '^160000 commit ([0-9a-f]{40})\s+third_party/workspace$'
    ) {
        throw "Workspace gitlink validation failed."
    }
    $expectedCommit = $Matches[1]
    $actualCommitOutput = @(
        Invoke-WorkspaceVerificationCommand -FilePath "git" -ArgumentList @(
            "-C", $workspaceRoot, "rev-parse", "HEAD"
        ) -FailureMessage "Unable to inspect the Workspace source commit."
    )
    $actualCommit = ([string]$actualCommitOutput[0]).Trim()
    if ($actualCommit -ne $expectedCommit) {
        throw "Workspace source does not match the pinned commit."
    }
    $trackedChanges = @(
        Invoke-WorkspaceVerificationCommand -FilePath "git" -ArgumentList @(
            "-C", $workspaceRoot, "status", "--short",
            "--untracked-files=no"
        ) -FailureMessage "Unable to inspect Workspace source cleanliness."
    )
    if ($trackedChanges.Count -gt 0) {
        throw "Workspace submodule contains tracked changes."
    }

    foreach ($runtimePath in @(
        "backend-api/backend/envs/.env.sqlite",
        "backend-api/backend/workspace-compose.secrets",
        "backend-api/backend/workspace-admin-config.secrets",
        "backend-api/backend/workspace-admin-credentials.secrets",
        "backend-api/backend/local_storage/",
        "terminalpro/.env.local"
    )) {
        $null = Invoke-WorkspaceVerificationCommand -FilePath "git" `
            -ArgumentList @(
                "-C", $workspaceRoot, "check-ignore", "-q", "--", $runtimePath
            ) -FailureMessage "A Workspace runtime path is not ignored."
    }

    if (-not (Test-Path (Join-Path $frontendRoot "bun.lock") -PathType Leaf)) {
        throw "Workspace Bun lockfile is missing."
    }
    if (Test-Path (Join-Path $frontendRoot "package-lock.json")) {
        throw "Generated package-lock.json must be absent."
    }
}

function Invoke-SelfHostedWorkspaceTest {
    Assert-WorkspaceComposeState
    Assert-WorkspaceLoopbackListeners
    Assert-WorkspaceHealth -Name "backend" `
        -Uri "http://127.0.0.1:8000/health"
    Assert-WorkspaceHealth -Name "frontend" `
        -Uri "http://127.0.0.1:1420"
    Assert-WorkspaceSourceAndRuntimeState

    $null = Invoke-WorkspaceVerificationCommand -FilePath "git" `
        -ArgumentList @(
            "-C", $workspaceRoot, "check-ignore", "-q", "--",
            "backend-api/backend/workspace-admin-credentials.secrets"
        ) -FailureMessage "Workspace administrator credentials are not ignored."
    if (-not (Test-Path $adminCredentials -PathType Leaf)) {
        throw "Workspace setup is incomplete."
    }
    try {
        $credential = Get-Content $adminCredentials -Raw | ConvertFrom-Json
    } catch {
        throw "Workspace administrator credential file is invalid."
    }
    Assert-WorkspaceManagedAdminLogin -Credential $credential
    Assert-WorkspaceCorsContract
    Write-Host (
        "Self-hosted Workspace verification passed: exact services, " +
        "loopback listeners, health, login, CORS, and source state."
    )
}

if ($MyInvocation.InvocationName -ne ".") {
    try {
        Invoke-SelfHostedWorkspaceTest
    } catch {
        Write-Error "Verification failed: $($_.Exception.Message)"
        exit 1
    }
}
