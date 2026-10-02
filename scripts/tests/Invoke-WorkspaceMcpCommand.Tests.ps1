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
        $script:RequestIndex = 0
        $script:ChildToken = $null
        $script:ChildUrl = $null
        $script:ChildArgs = $null
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
        }
        Mock Invoke-RestMethod {
            $script:RequestIndex++
            switch ($script:RequestIndex) {
                1 { return [pscustomobject]@{ access_token = "session-token" } }
                2 {
                    return [pscustomobject]@{
                        uuid = "11111111-1111-1111-1111-111111111111"
                        token = "mcp-token"
                    }
                }
                default { return $null }
            }
        }
        Mock Invoke-WorkspaceMcpChildCommand {
            $script:ChildToken = $env:WORKSPACE_MCP_TOKEN
            $script:ChildUrl = $env:WORKSPACE_MCP_URL
            $script:ChildArgs = @($ArgumentList)
            return 0
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
    }

    It "provides one token only through the child environment and restores prior state" {
        $exitCode = Invoke-WorkspaceMcpChildWithToken `
            -WorkspaceRoot $TestDrive `
            -FilePath "workspace-bench" `
            -ArgumentList @("live-parity", "--task", "example")

        $exitCode | Should Be 0
        $script:ChildToken | Should Be "mcp-token"
        $script:ChildUrl | Should Be "http://127.0.0.1:8000/mcp"
        ($script:ChildArgs -join " ") | Should Not Match "mcp-token|session-token"
        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
        Assert-MockCalled Invoke-RestMethod -Times 4 -Exactly -Scope It
    }

    It "revokes the MCP token and logs out when the child fails" {
        Mock Invoke-WorkspaceMcpChildCommand {
            throw "child failure"
        }

        {
            Invoke-WorkspaceMcpChildWithToken `
                -WorkspaceRoot $TestDrive `
                -FilePath "workspace-bench"
        } | Should Throw "Workspace MCP child command failed."

        $env:WORKSPACE_MCP_TOKEN | Should Be "prior-token"
        $env:WORKSPACE_MCP_URL | Should Be "prior-url"
        Assert-MockCalled Invoke-RestMethod -Times 4 -Exactly -Scope It
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Delete" -and
            $Uri -like "*/pro/workspace-mcp/tokens/*"
        }
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -Scope It -ParameterFilter {
            $Method -eq "Get" -and $Uri -eq "http://127.0.0.1:8000/logout"
        }
    }
}
