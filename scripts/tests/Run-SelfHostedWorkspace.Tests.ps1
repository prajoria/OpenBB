Describe "Self-hosted Workspace launcher" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\run_self_hosted_workspace.ps1"
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

    It "uses the checked-in SQLite Compose stack and an exact project" {
        $ScriptText | Should Match 'docker-compose-local-dev-sqlite\.yml'
        $ScriptText | Should Match 'openbb-workspace-2110'
        $ScriptText | Should Match '"run",\s*"--rm",\s*"fastapi",\s*"python",\s*"-m",\s*"alembic",\s*"upgrade",\s*"head"'
        $ScriptText | Should Match '"up",\s*"-d",\s*"redis",\s*"fastapi",\s*"rq_worker"'
    }

    It "initializes users and entities explicitly and idempotently" {
        $ScriptText | Should Match '"exec",\s*"-T",\s*"fastapi",\s*"python",\s*"-m",\s*"scripts\.init_users"'
        $ScriptText | Should Not Match 'Remove-Item.+user_create\.json'
    }

    It "binds Vite exactly to loopback port 1420" {
        $ScriptText | Should Match '"run",\s*"dev",\s*"--",\s*"--host",\s*"127\.0\.0\.1",\s*"--port",\s*"1420",\s*"--strictPort"'
    }

    It "uses finite sanitized health checks" {
        Mock Invoke-WebRequest { throw "sensitive response body" }

        $captured = ""
        try {
            Invoke-WorkspaceHealthCheck -Name "backend" -Uri "http://127.0.0.1:8000/docs" -Attempts 1
        } catch {
            $captured = $_ | Out-String
        }

        $captured | Should Match "backend health check failed"
        $captured | Should Not Match "sensitive response body"
        Assert-MockCalled Invoke-WebRequest -Times 1 -Exactly -ParameterFilter {
            $ConnectionTimeoutSeconds -eq 3 -and $OperationTimeoutSeconds -eq 5
        }
    }

    It "stores only PID metadata and sanitized logs in ignored state" {
        $ScriptText | Should Match '\.dev-cycle[\\/]workspace-2110'
        $ScriptText | Should Match 'frontend\.pid\.json'
        $ScriptText | Should Match 'frontend\.(stdout|stderr)\.log'
        $ScriptText | Should Not Match 'ConvertTo-Json.+(Password|Secret|Token)'
    }
}
