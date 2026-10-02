Describe "Workspace MCP child command wrapper" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\invoke_workspace_mcp_command.ps1"
        $ScriptText = Get-Content $ScriptPath -Raw
        $Tokens = $null
        $ParseErrors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile(
            $ScriptPath,
            [ref]$Tokens,
            [ref]$ParseErrors
        )
        . $ScriptPath
    }

    BeforeEach {
        $script:TokenListCalls = 0
        $credentialDirectory = Join-Path $TestDrive (
            "third_party\workspace\backend-api\backend"
        )
        $null = New-Item $credentialDirectory -ItemType Directory -Force
        Set-Content `
            -Path (Join-Path $credentialDirectory "workspace-admin-credentials.secrets") `
            -Value "{}"
        $env:WORKSPACE_MCP_TOKEN = "prior-token"
        $env:WORKSPACE_MCP_URL = "prior-url"

        Mock Assert-WorkspaceMcpCredentialIsIgnored {}
        Mock Get-Content {
            [pscustomobject]@{
                Email = "admin@example.invalid"
                Password = "not-a-real-password"
            } | ConvertTo-Json
        } -ParameterFilter {
            $Path -like "*workspace-admin-credentials.secrets"
        }
        Mock Invoke-RestMethod {
            if ($Uri -eq "http://127.0.0.1:8000/pro/login") {
                return [pscustomobject]@{ access_token = "session-token" }
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Get"
            ) {
                $script:TokenListCalls++
                return @()
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Post"
            ) {
                return [pscustomobject]@{
                    uuid = "11111111-1111-1111-1111-111111111111"
                    token = "mcp-token"
                }
            }
            return $null
        }
    }

    AfterEach {
        Remove-Item Env:WORKSPACE_MCP_TOKEN -ErrorAction SilentlyContinue
        Remove-Item Env:WORKSPACE_MCP_URL -ErrorAction SilentlyContinue
    }

    It "is valid PowerShell and never persists or prints sensitive values" {
        $ParseErrors.Count | Should Be 0
        $ScriptText | Should Not Match 'Set-Content|Add-Content|Out-File|Tee-Object'
        $ScriptText | Should Not Match 'Write-(Host|Output|Verbose|Debug).*(token|credential|password)'
        $ScriptText | Should Not Match 'Start-Process'
        $ScriptText | Should Not Match 'Stop-Process\s+-(Name|InputObject)'
    }

    It "passes arguments literally and scopes MCP environment to the real child" {
        $probePath = Join-Path $TestDrive "child-probe.ps1"
        $resultPath = Join-Path $TestDrive "child-result.json"
        @'
param(
    [string]$Value,
    [string]$OutputPath
)
@{
    value = $Value
    token = $env:WORKSPACE_MCP_TOKEN
    url = $env:WORKSPACE_MCP_URL
} | ConvertTo-Json | Set-Content -Path $OutputPath
'@ | Set-Content -Path $probePath
        $unsafeArgument = 'literal; Write-Output "argument-injection"'

        $exitCode = Invoke-WorkspaceMcpChildCommand `
            -FilePath (Get-Command pwsh).Source `
            -ArgumentList @(
                "-NoProfile",
                "-File",
                $probePath,
                "-Value",
                $unsafeArgument,
                "-OutputPath",
                $resultPath
            ) `
            -WorkingDirectory $TestDrive `
            -McpToken "child-token" `
            -McpUrl "http://127.0.0.1:8000/mcp" `
            -TimeoutSeconds 10

        $exitCode | Should Be 0
        $result = Get-Content $resultPath -Raw | ConvertFrom-Json
        $result.value | Should Be $unsafeArgument
        $result.token | Should Be "child-token"
        $result.url | Should Be "http://127.0.0.1:8000/mcp"
        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
    }

    It "resolves a bare executable name to one existing application" {
        $exitCode = Invoke-WorkspaceMcpChildCommand `
            -FilePath "pwsh" `
            -ArgumentList @("-NoProfile", "-Command", "exit 0") `
            -WorkingDirectory $TestDrive `
            -McpToken "child-token" `
            -McpUrl "http://127.0.0.1:8000/mcp" `
            -TimeoutSeconds 10

        $exitCode | Should Be 0
    }

    It "times out and terminates the exact real child process tree" {
        $probePath = Join-Path $TestDrive "hanging-child.ps1"
        $pidPath = Join-Path $TestDrive "child-pids.json"
        @'
param([string]$PidPath)
$grandchild = Start-Process pwsh -ArgumentList @(
    "-NoProfile",
    "-Command",
    "Start-Sleep -Seconds 60"
) -PassThru
@{
    parent = $PID
    grandchild = $grandchild.Id
} | ConvertTo-Json | Set-Content -Path $PidPath
Start-Sleep -Seconds 60
'@ | Set-Content -Path $probePath

        {
            Invoke-WorkspaceMcpChildCommand `
                -FilePath (Get-Command pwsh).Source `
                -ArgumentList @("-NoProfile", "-File", $probePath, "-PidPath", $pidPath) `
                -WorkingDirectory $TestDrive `
                -McpToken "child-token" `
                -McpUrl "http://127.0.0.1:8000/mcp" `
                -TimeoutSeconds 1
        } | Should Throw "Workspace MCP child command timed out."

        $pids = Get-Content $pidPath -Raw | ConvertFrom-Json
        Start-Sleep -Milliseconds 300
        (Get-Process -Id $pids.parent -ErrorAction SilentlyContinue) | Should BeNullOrEmpty
        (Get-Process -Id $pids.grandchild -ErrorAction SilentlyContinue) |
            Should BeNullOrEmpty
    }

    It "uses an isolated session source and exact bearer-authenticated endpoints" {
        $exitCode = Invoke-WorkspaceMcpChildWithToken `
            -WorkspaceRoot $TestDrive `
            -FilePath (Get-Command pwsh).Source `
            -ArgumentList @("-NoProfile", "-Command", "exit 0") `
            -ChildTimeoutSeconds 10

        $exitCode | Should Be 0
        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Post" -and
            $Uri -eq "http://127.0.0.1:8000/pro/login" -and
            ($Body | ConvertFrom-Json).source -eq "excel"
        }
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Post" -and
            $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
            $Headers.Authorization -eq "Bearer session-token"
        }
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Delete" -and
            $Uri -eq (
                "http://127.0.0.1:8000/pro/workspace-mcp/tokens/" +
                "11111111-1111-1111-1111-111111111111"
            ) -and
            $Headers.Authorization -eq "Bearer session-token"
        }
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Get" -and
            $Uri -eq "http://127.0.0.1:8000/logout" -and
            $Headers.Authorization -eq "Bearer session-token"
        }
        Assert-MockCalled Invoke-RestMethod -Times 0 -Exactly -Scope It -ParameterFilter {
            $Uri -eq "http://127.0.0.1:8000/pro/logout"
        }
    }

    It "revokes and restores environment after a real nonzero child exit" {
        {
            Invoke-WorkspaceMcpChildWithToken `
                -WorkspaceRoot $TestDrive `
                -FilePath (Get-Command pwsh).Source `
                -ArgumentList @("-NoProfile", "-Command", "exit 17") `
                -ChildTimeoutSeconds 10
        } | Should Throw "Workspace MCP child command failed."

        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Delete"
        }
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Get" -and $Uri -eq "http://127.0.0.1:8000/logout"
        }
    }

    It "recovers and revokes a created token after a malformed create response" {
        Mock Invoke-RestMethod {
            if ($Uri -eq "http://127.0.0.1:8000/pro/login") {
                return [pscustomobject]@{ access_token = "session-token" }
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Get"
            ) {
                $script:TokenListCalls++
                if ($script:TokenListCalls -eq 1) {
                    return @(
                        [pscustomobject]@{
                            uuid = "22222222-2222-2222-2222-222222222222"
                            name = "existing-token"
                        }
                    )
                }
                return @(
                    [pscustomobject]@{
                        uuid = "22222222-2222-2222-2222-222222222222"
                        name = "existing-token"
                    },
                    [pscustomobject]@{
                        uuid = "33333333-3333-3333-3333-333333333333"
                        name = $script:CreatedTokenName
                    }
                )
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Post"
            ) {
                $script:CreatedTokenName = ($Body | ConvertFrom-Json).name
                return [pscustomobject]@{ unexpected = "shape" }
            }
            return $null
        }

        {
            Invoke-WorkspaceMcpChildWithToken `
                -WorkspaceRoot $TestDrive `
                -FilePath (Get-Command pwsh).Source `
                -ArgumentList @("-NoProfile", "-Command", "exit 0") `
                -ChildTimeoutSeconds 10
        } | Should Throw "Workspace MCP token creation failed."

        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Delete" -and
            $Uri -eq (
                "http://127.0.0.1:8000/pro/workspace-mcp/tokens/" +
                "33333333-3333-3333-3333-333333333333"
            )
        }
        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
    }

    It "surfaces a sanitized cleanup failure after restoring environment" {
        Mock Invoke-RestMethod {
            if ($Uri -eq "http://127.0.0.1:8000/pro/login") {
                return [pscustomobject]@{ access_token = "session-token" }
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Get"
            ) {
                return @()
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Post"
            ) {
                return [pscustomobject]@{
                    uuid = "11111111-1111-1111-1111-111111111111"
                    token = "mcp-token"
                }
            }
            if ($Method -eq "Delete") {
                throw "sensitive backend detail"
            }
            return $null
        }

        {
            Invoke-WorkspaceMcpChildWithToken `
                -WorkspaceRoot $TestDrive `
                -FilePath (Get-Command pwsh).Source `
                -ArgumentList @("-NoProfile", "-Command", "exit 0") `
                -ChildTimeoutSeconds 10
        } | Should Throw "Workspace MCP token revocation failed."

        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Get" -and $Uri -eq "http://127.0.0.1:8000/logout"
        }
    }

    It "preserves a child timeout with a sanitized revocation failure" {
        Mock Invoke-WorkspaceMcpChildCommand {
            throw "Workspace MCP child command timed out."
        }
        Mock Invoke-RestMethod {
            if ($Uri -eq "http://127.0.0.1:8000/pro/login") {
                return [pscustomobject]@{ access_token = "session-token" }
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Get"
            ) {
                return @()
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Post"
            ) {
                return [pscustomobject]@{
                    uuid = "11111111-1111-1111-1111-111111111111"
                    token = "mcp-token"
                }
            }
            if ($Method -eq "Delete") {
                throw "raw revocation response"
            }
            return $null
        }

        $captured = ""
        try {
            Invoke-WorkspaceMcpChildWithToken `
                -WorkspaceRoot $TestDrive `
                -FilePath (Get-Command pwsh).Source `
                -ChildTimeoutSeconds 10
        } catch {
            $captured = $_.Exception.Message
        }

        $captured | Should Match "Workspace MCP child command timed out"
        $captured | Should Match "Workspace MCP token revocation failed"
        $captured | Should Not Match "raw revocation response"
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Get" -and $Uri -eq "http://127.0.0.1:8000/logout"
        }
    }

    It "preserves a nonzero child failure with sanitized cleanup failures" {
        Mock Invoke-WorkspaceMcpChildCommand { 17 }
        Mock Invoke-RestMethod {
            if ($Uri -eq "http://127.0.0.1:8000/pro/login") {
                return [pscustomobject]@{ access_token = "session-token" }
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Get"
            ) {
                return @()
            }
            if (
                $Uri -eq "http://127.0.0.1:8000/pro/workspace-mcp/tokens" -and
                $Method -eq "Post"
            ) {
                return [pscustomobject]@{
                    uuid = "11111111-1111-1111-1111-111111111111"
                    token = "mcp-token"
                }
            }
            if ($Method -eq "Delete") {
                throw "raw revocation response"
            }
            if ($Uri -eq "http://127.0.0.1:8000/logout") {
                throw "raw logout response"
            }
            return $null
        }

        $captured = ""
        try {
            Invoke-WorkspaceMcpChildWithToken `
                -WorkspaceRoot $TestDrive `
                -FilePath (Get-Command pwsh).Source `
                -ChildTimeoutSeconds 10
        } catch {
            $captured = $_.Exception.Message
        }

        $captured | Should Match "Workspace MCP child command failed"
        $captured | Should Match "Workspace MCP token revocation failed"
        $captured | Should Match "Workspace administrator logout failed"
        $captured | Should Not Match "raw revocation response|raw logout response"
    }

    It "rejects an overlapping managed-administrator token lifecycle" {
        $readyPath = Join-Path $TestDrive "lifecycle-lock-ready"
        $job = Start-Job -ScriptBlock {
            param($ReadyPath)
            $mutex = [System.Threading.Mutex]::new(
                $false,
                "Local\OpenBBWorkspaceMcpManagedAdmin"
            )
            $acquired = $mutex.WaitOne(5000)
            try {
                if (-not $acquired) {
                    throw "test lifecycle lock was not acquired"
                }
                Set-Content -Path $ReadyPath -Value "ready"
                Start-Sleep -Seconds 30
            } finally {
                if ($acquired) {
                    $mutex.ReleaseMutex()
                }
                $mutex.Dispose()
            }
        } -ArgumentList $readyPath
        try {
            for ($attempt = 0; $attempt -lt 50 -and -not (Test-Path $readyPath); $attempt++) {
                Start-Sleep -Milliseconds 100
            }
            Test-Path $readyPath | Should Be $true

            {
                Invoke-WorkspaceMcpChildWithToken `
                    -WorkspaceRoot $TestDrive `
                    -FilePath (Get-Command pwsh).Source `
                    -ArgumentList @("-NoProfile", "-Command", "exit 0") `
                    -ChildTimeoutSeconds 10 `
                    -LifecycleLockTimeoutSeconds 1
            } | Should Throw "Workspace MCP token lifecycle is already active."

            Assert-MockCalled Invoke-RestMethod -Times 0 -Exactly -Scope It
            $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
            $env:WORKSPACE_MCP_URL | Should Be "prior-url"
        } finally {
            Stop-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -Force -ErrorAction SilentlyContinue
        }
    }
}
