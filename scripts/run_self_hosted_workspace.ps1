#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start the pinned Workspace SQLite development stack and Vite frontend.
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
$backendEnv = Join-Path $backendRoot "backend\envs\.env.sqlite"
$adminCredentials = Join-Path $backendRoot "backend\workspace-admin-credentials.secrets"
$frontendEnv = Join-Path $frontendRoot ".env.local"
$runtimeRoot = Join-Path $repoRoot ".dev-cycle\workspace-2110"
$pidPath = Join-Path $runtimeRoot "frontend.pid.json"
$stdoutPath = Join-Path $runtimeRoot "frontend.stdout.log"
$stderrPath = Join-Path $runtimeRoot "frontend.stderr.log"
$composeProject = "openbb-workspace-2110"

function Invoke-WorkspaceCompose {
    param(
        [Parameter(Mandatory)]
        [string[]]$ArgumentList,
        [Parameter(Mandatory)]
        [string]$FailureMessage,
        [switch]$CaptureOutput
    )

    $composeArguments = @(
        "compose", "--project-name", $composeProject,
        "--file", $composeFile, "--file", $composeOverride
    ) + $ArgumentList
    if ($CaptureOutput) {
        $output = & docker @composeArguments 2>$null
    } else {
        & docker @composeArguments | Out-Host
        $output = $null
    }
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
    return $output
}

function Invoke-WorkspaceHealthCheck {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Uri,
        [int]$Attempts = 30
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
        Start-Sleep -Seconds 2
    }
    throw "$Name health check failed after $Attempts attempts."
}

function Assert-WorkspaceLogin {
    param([Parameter(Mandatory)][pscustomobject]$Credentials)

    $body = @{
        email = $Credentials.Email
        password = $Credentials.Password
        remember = $false
    } | ConvertTo-Json -Compress
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/pro/login" `
            -Method Post -ContentType "application/json" -Body $body `
            -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 10
        if ($response.StatusCode -ne 200) {
            throw "Unexpected status"
        }
    } catch {
        throw "Workspace admin login check failed."
    }
}

function Invoke-SelfHostedWorkspaceRun {
    foreach ($requiredPath in @(
        $composeFile, $composeOverride, $backendEnv, $adminCredentials,
        $frontendEnv, (Join-Path $frontendRoot "node_modules")
    )) {
        if (-not (Test-Path $requiredPath)) {
            throw "Workspace setup is incomplete. Run .\scripts\setup_self_hosted_workspace.ps1 first."
        }
    }
    if (Test-Path $pidPath -PathType Leaf) {
        throw "Frontend PID state already exists. Run the stop script before starting again."
    }

    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

    try {
        Push-Location $backendRoot
        try {
            Write-Host "Building Workspace backend images ..."
            Invoke-WorkspaceCompose -ArgumentList @(
                "build", "fastapi", "rq_worker"
            ) -FailureMessage "Workspace backend image build failed."

            Write-Host "Applying Workspace SQLite migrations ..."
            Invoke-WorkspaceCompose -ArgumentList @(
                "run", "--rm", "fastapi", "python", "-m", "alembic", "upgrade", "head"
            ) -FailureMessage "Workspace database migration failed."

            Write-Host "Starting Redis, FastAPI, and RQ ..."
            Invoke-WorkspaceCompose -ArgumentList @(
                "up", "-d", "redis", "fastapi", "rq_worker"
            ) -FailureMessage "Workspace backend stack failed to start."
        } finally {
            Pop-Location
        }

        Invoke-WorkspaceHealthCheck -Name "backend" -Uri "http://127.0.0.1:8000/health"

        Write-Host "Initializing local Workspace users and entity ..."
        Push-Location $backendRoot
        try {
            Invoke-WorkspaceCompose -ArgumentList @(
                "exec", "-T", "fastapi", "python", "-m", "scripts.init_users"
            ) -FailureMessage "Workspace user and entity initialization failed."
        } finally {
            Pop-Location
        }

        $credentials = Get-Content $adminCredentials -Raw | ConvertFrom-Json
        Assert-WorkspaceLogin -Credentials $credentials

        $runningServices = @(
            Invoke-WorkspaceCompose -ArgumentList @(
                "ps", "--status", "running", "--services"
            ) -FailureMessage "Unable to verify Workspace container state." -CaptureOutput
        )
        foreach ($service in @("redis", "fastapi", "rq_worker")) {
            if ($runningServices -notcontains $service) {
                throw "Workspace container state check failed."
            }
        }

        Write-Host "Starting the Workspace Vite frontend ..."
        $frontend = Start-Process -FilePath "bun" -ArgumentList @(
            "run", "dev", "--", "--host", "127.0.0.1", "--port", "1420", "--strictPort"
        ) -WorkingDirectory $frontendRoot -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath -PassThru
        $frontendState = [ordered]@{
            Pid = $frontend.Id
            StartTimeUtcTicks = $frontend.StartTime.ToUniversalTime().Ticks
        }
        $frontendState | ConvertTo-Json |
            Set-Content -Path $pidPath -Encoding utf8NoBOM

        Invoke-WorkspaceHealthCheck -Name "frontend" -Uri "http://127.0.0.1:1420"
        Write-Host "Self-hosted Workspace is healthy on loopback ports 8000 and 1420."
    } catch {
        $safeMessage = $_.Exception.Message
        try {
            & (Join-Path $PSScriptRoot "stop_self_hosted_workspace.ps1") | Out-Null
        } catch {
        }
        throw $safeMessage
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-SelfHostedWorkspaceRun
}
