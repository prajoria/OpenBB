Describe "Self-hosted Workspace stop" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\stop_self_hosted_workspace.ps1"
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

    BeforeEach {
        Mock Get-Process {
            [pscustomobject]@{
                Id = 41
                StartTime = [datetime]::new(2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
            }
        }
        Mock Get-CimInstance { @() }
        Mock Stop-Process {}
        Mock Write-Warning {}
    }

    It "is valid PowerShell" {
        $ParseErrors.Count | Should Be 0
    }

    It "stops the recorded process when PID and start time match" {
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            ).Ticks
        }

        Stop-WorkspaceFrontendProcess -State $state

        Assert-MockCalled Stop-Process -Times 1 -Exactly -ParameterFilter {
            $Id -eq 41
        }
    }

    It "does not stop a reused PID" {
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = 1
        }

        Stop-WorkspaceFrontendProcess -State $state

        Assert-MockCalled Stop-Process -Times 0 -Scope It
    }

    It "does not use broad process-name termination" {
        $ScriptText | Should Not Match 'Stop-Process\s+-(Name|InputObject)'
        $ScriptText | Should Not Match 'taskkill.+/IM'
    }

    It "stops only the exact Compose project and checked-in stack" {
        $ScriptText | Should Match 'openbb-workspace-2110'
        $ScriptText | Should Match 'docker-compose-local-dev-sqlite\.yml'
        $ScriptText | Should Match 'down\s+--remove-orphans'
        $ScriptText | Should Not Match 'down\s+-v'
    }
}
