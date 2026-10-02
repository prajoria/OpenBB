Describe "Self-hosted Workspace setup" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\setup_self_hosted_workspace.ps1"
        $ScriptText = Get-Content $ScriptPath -Raw
        $Tokens = $null
        $ParseErrors = $null
        $ScriptAst = [System.Management.Automation.Language.Parser]::ParseFile(
            $ScriptPath,
            [ref]$Tokens,
            [ref]$ParseErrors
        )
        . $ScriptPath
    }

    It "is valid PowerShell" {
        $ParseErrors.Count | Should Be 0
    }

    It "initializes only the pinned Workspace submodule" {
        $ScriptText | Should Match '"submodule",\s*"update",\s*"--init",\s*"--recursive",\s*"--",\s*"third_party/workspace"'
        $ScriptText | Should Match '"ls-tree",\s*"HEAD",\s*"third_party/workspace"'
    }

    It "requires the Linux Docker engine, Compose, and Bun" {
        $ScriptText | Should Match 'FilePath\s+"docker"\s+`\s*\r?\n\s*-ArgumentList\s+@\("version"'
        $ScriptText | Should Match 'Server\.Os'
        $ScriptText | Should Match '"compose",\s*"version"'
        $ScriptText | Should Match 'FilePath\s+"bun"\s+`\s*\r?\n\s*-ArgumentList\s+@\("--version"'
    }

    It "uses the locked Bun dependency graph" {
        $ScriptText | Should Match '"install",\s*"--frozen-lockfile"'
        $ScriptText | Should Not Match 'npm\s+(install|ci)'
    }

    It "creates the ignored folder-storage directory before migrations" {
        $ScriptText | Should Match 'New-Item.+local_storage.+-ItemType\s+Directory'
    }

    It "builds safe SQLite configuration from the checked-in schema" {
        $template = @(
            ""
            "DATABASE_TYPE=sqlite",
            "DB_PATH=test_sqlite.db",
            "REDIS_HOST=localhost",
            "JWT_SECRET=committed-example",
            "OPENBB_AUTH_TOKEN=committed-example",
            "OPENBB_AES_KEY=committed-example",
            "FRONTENDURL=http://localhost",
            "SELFURL=http://localhost:8000",
            "PROURL=http://localhost:1420",
            "STORAGE_PROVIDER=folder",
            "FOLDER_STORAGE_PATH=/opt/code/local_storage",
            "LOCAL_STORAGE_SECRET_KEY=committed-example",
            "DISABLE_REGISTRATION=0",
            "DISABLE_CORS=1",
            "BACKEND_CORS_ORIGINS=http://host.example"
        )
        $secrets = @{
            Jwt = "fresh-jwt"
            Auth = "fresh-auth"
            Aes = "fresh-aes"
            Storage = "fresh-storage"
        }

        $result = New-WorkspaceBackendEnvironment -TemplateLines $template -Secrets $secrets
        $text = $result -join "`n"

        $text | Should Not Match "committed-example"
        $text | Should Match "DATABASE_TYPE=sqlite"
        $text | Should Match "DB_PATH=/opt/code/local_storage/workspace.db"
        $text | Should Match "REDIS_HOST=redis"
        $text | Should Match "FRONTENDURL=http://127.0.0.1:1420"
        $text | Should Match "SELFURL=http://127.0.0.1:8000"
        $text | Should Match "PROURL=http://127.0.0.1:1420"
        $text | Should Match "STORAGE_PROVIDER=folder"
        $text | Should Match "DISABLE_REGISTRATION=1"
        $text | Should Match "DISABLE_CORS=0"
        $text | Should Match "BACKEND_CORS_ORIGINS=http://127.0.0.1:1420"
    }

    It "uses one exact CORS allowlist for middleware and auth origin checks" {
        $secrets = @{
            Jwt = "jwt"
            Auth = "auth"
            Aes = "aes"
            Storage = "storage"
        }
        $environment = New-WorkspaceBackendEnvironment -TemplateLines @(
            "DATABASE_TYPE=sqlite"
            "DB_PATH=test.db"
            "REDIS_HOST=localhost"
            "JWT_SECRET=example"
            "OPENBB_AUTH_TOKEN=example"
            "OPENBB_AES_KEY=example"
            "FRONTENDURL=http://localhost"
            "SELFURL=http://localhost:8000"
            "PROURL=http://localhost:1420"
            "STORAGE_PROVIDER=folder"
            "FOLDER_STORAGE_PATH=/data"
            "LOCAL_STORAGE_SECRET_KEY=example"
            "DISABLE_REGISTRATION=0"
            "DISABLE_CORS=1"
        ) -Secrets $secrets
        $corsLines = @($environment | Where-Object {
            $_ -match '^(DISABLE_CORS|BACKEND_CORS_ORIGINS)='
        })

        $corsLines.Count | Should Be 2
        ($corsLines -contains "DISABLE_CORS=0") | Should Be $true
        (
            $corsLines -contains
            "BACKEND_CORS_ORIGINS=http://127.0.0.1:1420"
        ) | Should Be $true
    }

    It "disables unavailable hosted frontend services" {
        $text = (New-WorkspaceFrontendEnvironment) -join "`n"

        $text | Should Match "VITE_PAYMENTS_URL=http://127.0.0.1:8000"
        $text | Should Match 'VITE_AI_API_URL=""'
        $text | Should Match 'VITE_PLATFORM_URL=""'
        $text | Should Match 'VITE_DATABASE_API_URL=""'
        $text | Should Match 'VITE_AUTHENTICATION_ALLOW_EMAIL_LOGIN="true"'
        $text | Should Match 'VITE_AUTHENTICATION_ALLOW_REGISTRATION="false"'
        $text | Should Match 'VITE_AI_COPILOT_ENABLED="false"'
        $text | Should Match 'VITE_SERVICES_POSTHOG="false"'
    }

    It "never prints secret values or full environment files" {
        $ScriptText | Should Not Match 'Write-(Host|Output|Verbose).*(JWT_SECRET|OPENBB_AUTH_TOKEN|OPENBB_AES_KEY|LOCAL_STORAGE_SECRET_KEY|AdminPassword)'
        $ScriptText | Should Not Match 'Get-Content.+\.env'
    }

    It "keeps one managed admin identity while rotating credentials on repeated setup" {
        $artifactRoot = Join-Path $RepoRoot ".dev-cycle\workspace-2110\setup-test"
        $configPath = Join-Path $artifactRoot "admin-config.toml"
        $credentialsPath = Join-Path $artifactRoot "admin-credentials.json"
        New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
        try {
            Write-WorkspaceAdminArtifacts -ConfigPath $configPath `
                -CredentialsPath $credentialsPath
            $first = Get-Content $credentialsPath -Raw | ConvertFrom-Json

            Write-WorkspaceAdminArtifacts -ConfigPath $configPath `
                -CredentialsPath $credentialsPath
            $second = Get-Content $credentialsPath -Raw | ConvertFrom-Json
            $config = Get-Content $configPath -Raw

            $first.Email | Should Be "workspace-admin@example.com"
            $second.Email | Should Be $first.Email
            $second.Password | Should Not Be $first.Password
            ([regex]::Matches($config, '\[\[admins\]\]')).Count | Should Be 1
            $config | Should Match 'email = "workspace-admin@example\.com"'
        } finally {
            Remove-Item $artifactRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It "generates a signed service JWT accepted by backend authentication" {
        $token = New-WorkspaceServiceToken -SigningSecret "unit-test-signing-secret"
        $parts = $token.Split(".")
        $payloadText = [Text.Encoding]::UTF8.GetString(
            [Convert]::FromBase64String(
                $parts[1].Replace("-", "+").Replace("_", "/").PadRight(
                    [Math]::Ceiling($parts[1].Length / 4) * 4,
                    "="
                )
            )
        )
        $payload = $payloadText | ConvertFrom-Json

        $parts.Count | Should Be 3
        $payload.sub | Should Be "pro"
    }
}
