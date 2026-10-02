#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Prepare the pinned self-hosted Workspace development stack.

.DESCRIPTION
    Verifies Git, Docker Desktop's Linux engine, Docker Compose, and Bun;
    initializes and verifies the pinned Workspace submodule; writes only
    ignored local configuration with newly generated development secrets; and
    installs frontend dependencies from the checked-in Bun lockfile.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Join-Path $repoRoot "third_party\workspace"
$backendRoot = Join-Path $workspaceRoot "backend-api"
$frontendRoot = Join-Path $workspaceRoot "terminalpro"
$backendEnvPath = Join-Path $backendRoot "backend\envs\.env.sqlite"
$backendTemplatePath = Join-Path $backendRoot "backend\envs\.env.sqlite.example"
$frontendEnvPath = Join-Path $frontendRoot ".env.local"
$composeOverridePath = Join-Path $backendRoot "backend\workspace-compose.secrets"
$adminConfigPath = Join-Path $backendRoot "backend\workspace-admin-config.secrets"
$adminCredentialsPath = Join-Path $backendRoot "backend\workspace-admin-credentials.secrets"

function Invoke-WorkspaceSetupCommand {
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory)]
        [string]$FailureMessage,
        [switch]$CaptureOutput
    )

    if ($CaptureOutput) {
        $output = & $FilePath @ArgumentList 2>$null
    } else {
        & $FilePath @ArgumentList | Out-Host
        $output = $null
    }
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
    return $output
}

function New-WorkspaceRandomSecret {
    param([int]$ByteCount = 48)

    $bytes = [byte[]]::new($ByteCount)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function ConvertTo-WorkspaceBase64Url {
    param([Parameter(Mandatory)][byte[]]$Bytes)

    return [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function New-WorkspaceServiceToken {
    param([Parameter(Mandatory)][string]$SigningSecret)

    $encoding = [Text.Encoding]::UTF8
    $header = ConvertTo-WorkspaceBase64Url -Bytes $encoding.GetBytes(
        '{"alg":"HS256","typ":"JWT"}'
    )
    $payload = ConvertTo-WorkspaceBase64Url -Bytes $encoding.GetBytes(
        '{"sub":"pro"}'
    )
    $unsignedToken = "$header.$payload"
    $hmac = [System.Security.Cryptography.HMACSHA256]::new(
        $encoding.GetBytes($SigningSecret)
    )
    try {
        $signature = ConvertTo-WorkspaceBase64Url -Bytes $hmac.ComputeHash(
            $encoding.GetBytes($unsignedToken)
        )
    } finally {
        $hmac.Dispose()
    }
    return "$unsignedToken.$signature"
}

function New-WorkspaceBackendEnvironment {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string[]]$TemplateLines,
        [Parameter(Mandatory)]
        [hashtable]$Secrets
    )

    $values = [ordered]@{}
    foreach ($line in $TemplateLines) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    $overrides = [ordered]@{
        DATABASE_TYPE = "sqlite"
        DB_PATH = "/opt/code/local_storage/workspace.db"
        REDIS_HOST = "redis"
        REDIS_PASS = ""
        MODE = "onprem"
        JWT_SECRET = $Secrets.Jwt
        OPENBB_AUTH_TOKEN = $Secrets.Auth
        OPENBB_AES_KEY = $Secrets.Aes
        FRONTENDURL = "http://127.0.0.1:1420"
        SELFURL = "http://127.0.0.1:8000"
        PROURL = "http://127.0.0.1:1420"
        OPENBB_FRONTEND_USER_AGENT = "workspace-local-development"
        OPENBB_AI_USER_AGENT = "workspace-local-development"
        STORAGE_PROVIDER = "folder"
        FOLDER_STORAGE_PATH = "/opt/code/local_storage"
        LOCAL_STORAGE_SECRET_KEY = $Secrets.Storage
        DISABLE_REGISTRATION = "1"
        DISABLE_CORS = "0"
        BACKEND_CORS_ORIGINS = "http://127.0.0.1:1420"
        HUBSPOT = "0"
        PROMETHEUS = "0"
        WORKERS = "1"
    }
    foreach ($requiredKey in @(
        "DATABASE_TYPE", "DB_PATH", "REDIS_HOST", "JWT_SECRET",
        "OPENBB_AUTH_TOKEN", "OPENBB_AES_KEY", "FRONTENDURL", "SELFURL",
        "PROURL", "STORAGE_PROVIDER", "FOLDER_STORAGE_PATH",
        "LOCAL_STORAGE_SECRET_KEY", "DISABLE_REGISTRATION", "DISABLE_CORS"
    )) {
        if (-not $values.Contains($requiredKey)) {
            throw "SQLite environment template is missing required key: $requiredKey"
        }
    }
    foreach ($entry in $overrides.GetEnumerator()) {
        $values[$entry.Key] = $entry.Value
    }

    return @(
        foreach ($entry in $values.GetEnumerator()) {
            "{0}={1}" -f $entry.Key, $entry.Value
        }
    )
}

function New-WorkspaceFrontendEnvironment {
    return @(
        'VITE_PAYMENTS_URL=http://127.0.0.1:8000'
        'VITE_AI_API_URL=""'
        'VITE_PLATFORM_URL=""'
        'VITE_DATABASE_API_URL=""'
        'VITE_AUTHENTICATION_ALLOW_EMAIL_LOGIN="true"'
        'VITE_AUTHENTICATION_ALLOW_REGISTRATION="false"'
        'VITE_AUTHENTICATION_ALLOW_FORGOT_PASSWORD="false"'
        'VITE_AUTHENTICATION_IDENTITY_PROVIDERS=""'
        'VITE_AUTHENTICATION_SEND_USER_EMAIL_AS_HEADER="false"'
        'VITE_AI_COPILOT_ENABLED="false"'
        'VITE_AI_COPILOT_OPENBB_COPILOT="false"'
        'VITE_AI_COPILOT_DOCUMENTATION_LINKS="false"'
        'VITE_AI_COPILOT_WEB_SEARCH="false"'
        'VITE_AI_COPILOT_JINA_AI="false"'
        'VITE_AI_COPILOT_AI_ENHANCEMENTS="false"'
        'VITE_SERVICES_POSTHOG="false"'
        'VITE_SERVICES_HUBSPOT_FORMS="false"'
        'VITE_SERVICES_EMAIL="false"'
        'VITE_POSTHOG_KEY=""'
        'VITE_POSTHOG_URL=""'
        'VITE_MCP_DEFAULT_SERVER_ENABLED="false"'
    )
}

function Write-WorkspaceAdminArtifacts {
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$CredentialsPath
    )

    $adminEmail = "workspace-admin@example.com"
    $adminPassword = "{0}A1!" -f (New-WorkspaceRandomSecret -ByteCount 24)

    @"
[entity]
name = "Local Development"
seats = 10
aum = 0
company_type = "CORPORATION"
organization_size = "SMALL"
country = "DOM"

[[admins]]
email = "$adminEmail"
first_name = "Local"
last_name = "Admin"
password = "$adminPassword"
"@ | Set-Content -Path $ConfigPath -Encoding utf8NoBOM

    [ordered]@{
        Email = $adminEmail
        Password = $adminPassword
    } | ConvertTo-Json | Set-Content -Path $CredentialsPath -Encoding utf8NoBOM
}

function Assert-WorkspaceRuntimePathIgnored {
    param([Parameter(Mandatory)][string]$Path)

    & git -C $workspaceRoot check-ignore -q -- $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Refusing to create a runtime file that is not ignored by the Workspace submodule."
    }
}

function Invoke-SelfHostedWorkspaceSetup {
    foreach ($command in @("git", "docker", "bun")) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Required command is unavailable: $command"
        }
    }

    $engineOs = Invoke-WorkspaceSetupCommand -FilePath "docker" `
        -ArgumentList @("version", "--format", "{{.Server.Os}}") `
        -FailureMessage "Docker Desktop engine is unavailable." -CaptureOutput
    if (($engineOs | Select-Object -First 1).Trim() -ne "linux") {
        throw "Docker Desktop must be running the Linux engine."
    }
    $null = Invoke-WorkspaceSetupCommand -FilePath "docker" `
        -ArgumentList @("compose", "version", "--short") `
        -FailureMessage "Docker Compose is unavailable." -CaptureOutput
    $null = Invoke-WorkspaceSetupCommand -FilePath "bun" `
        -ArgumentList @("--version") `
        -FailureMessage "Bun is unavailable." -CaptureOutput

    Write-Host "Initializing the pinned Workspace submodule ..."
    Invoke-WorkspaceSetupCommand -FilePath "git" -ArgumentList @(
        "-C", $repoRoot, "submodule", "update", "--init", "--recursive", "--",
        "third_party/workspace"
    ) -FailureMessage "Workspace submodule initialization failed."

    $gitlink = Invoke-WorkspaceSetupCommand -FilePath "git" -ArgumentList @(
        "-C", $repoRoot, "ls-tree", "HEAD", "third_party/workspace"
    ) -FailureMessage "Unable to read the pinned Workspace gitlink." -CaptureOutput
    if (($gitlink -join "") -notmatch '^160000 commit ([0-9a-f]{40})\s+third_party/workspace$') {
        throw "The Workspace gitlink is missing or malformed."
    }
    $expectedCommit = $Matches[1]
    $actualCommit = (
        Invoke-WorkspaceSetupCommand -FilePath "git" -ArgumentList @(
            "-C", $workspaceRoot, "rev-parse", "HEAD"
        ) -FailureMessage "Unable to read the Workspace submodule commit." -CaptureOutput |
            Select-Object -First 1
    ).Trim()
    if ($actualCommit -ne $expectedCommit) {
        throw "Workspace submodule does not match the commit pinned by the parent repository."
    }
    $trackedChanges = Invoke-WorkspaceSetupCommand -FilePath "git" -ArgumentList @(
        "-C", $workspaceRoot, "status", "--short", "--untracked-files=no"
    ) -FailureMessage "Unable to verify Workspace source state." -CaptureOutput
    if (@($trackedChanges).Count -gt 0) {
        throw "Workspace submodule contains tracked modifications; setup will not overwrite them."
    }

    foreach ($requiredFile in @(
        $backendTemplatePath,
        (Join-Path $backendRoot "docker-compose-local-dev-sqlite.yml"),
        (Join-Path $frontendRoot "bun.lock"),
        (Join-Path $frontendRoot "package.json")
    )) {
        if (-not (Test-Path $requiredFile -PathType Leaf)) {
            throw "Pinned Workspace source is missing a required deployment file."
        }
    }

    foreach ($runtimePath in @(
        "backend-api/backend/envs/.env.sqlite",
        "backend-api/backend/workspace-compose.secrets",
        "backend-api/backend/workspace-admin-config.secrets",
        "backend-api/backend/workspace-admin-credentials.secrets",
        "backend-api/backend/local_storage/",
        "terminalpro/.env.local"
    )) {
        Assert-WorkspaceRuntimePathIgnored -Path $runtimePath
    }
    New-Item -Path (Join-Path $backendRoot "backend\local_storage") -ItemType Directory -Force |
        Out-Null

    $jwtSecret = New-WorkspaceRandomSecret -ByteCount 64
    $secrets = @{
        Jwt = $jwtSecret
        Auth = New-WorkspaceServiceToken -SigningSecret $jwtSecret
        Aes = New-WorkspaceRandomSecret -ByteCount 32
        Storage = New-WorkspaceRandomSecret -ByteCount 48
    }
    $templateLines = [System.IO.File]::ReadAllLines($backendTemplatePath)
    New-WorkspaceBackendEnvironment -TemplateLines $templateLines -Secrets $secrets |
        Set-Content -Path $backendEnvPath -Encoding utf8NoBOM
    New-WorkspaceFrontendEnvironment |
        Set-Content -Path $frontendEnvPath -Encoding utf8NoBOM

    @"
services:
  redis:
    ports: !override
      - "127.0.0.1:6379:6379"
  fastapi:
    ports: !override
      - "127.0.0.1:8000:8000"
    volumes:
      - ./backend/workspace-admin-config.secrets:/opt/code/scripts/cfgs/config.toml:ro
"@ | Set-Content -Path $composeOverridePath -Encoding utf8NoBOM

    Write-WorkspaceAdminArtifacts -ConfigPath $adminConfigPath `
        -CredentialsPath $adminCredentialsPath

    Write-Host "Installing frontend dependencies from bun.lock ..."
    Push-Location $frontendRoot
    try {
        Invoke-WorkspaceSetupCommand -FilePath "bun" `
            -ArgumentList @("install", "--frozen-lockfile") `
            -FailureMessage "Bun dependency installation failed."
    } finally {
        Pop-Location
    }

    Write-Host "Self-hosted Workspace setup is ready. Development secrets were written to ignored files."
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-SelfHostedWorkspaceSetup
}
