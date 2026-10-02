Describe "Copilot API lifecycle" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $StartSource = Join-Path $RepoRoot "copilot-api\src\start.ts"
        $StartSourceText = Get-Content $StartSource -Raw
        $RunScript = Join-Path $RepoRoot "scripts\run_copilot_api.ps1"
        $TestScript = Join-Path $RepoRoot "scripts\test_copilot_api.ps1"
        $StopScript = Join-Path $RepoRoot "scripts\stop_copilot_api.ps1"
        $RunText = Get-Content $RunScript -Raw
        $TestText = Get-Content $TestScript -Raw
        $StopText = Get-Content $StopScript -Raw
        $Tokens = $null
        $RunParseErrors = $null
        $TestParseErrors = $null
        $StopParseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $RunScript, [ref]$Tokens, [ref]$RunParseErrors
        ) | Out-Null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $TestScript, [ref]$Tokens, [ref]$TestParseErrors
        ) | Out-Null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $StopScript, [ref]$Tokens, [ref]$StopParseErrors
        ) | Out-Null
        . $TestScript
        . $StopScript
    }

    It "supports an explicit loopback host" {
        $StartSourceText | Should Match 'default:\s*"127\.0\.0\.1"'
        $StartSourceText | Should Match 'hostname:\s*options\.host'
        $StartSourceText | Should Match 'description:\s*"Host to listen on"'
    }

    It "provides checked-in run test and stop scripts" {
        (Test-Path $RunScript -PathType Leaf) | Should Be $true
        (Test-Path $TestScript -PathType Leaf) | Should Be $true
        (Test-Path $StopScript -PathType Leaf) | Should Be $true
    }

    It "keeps all lifecycle scripts valid PowerShell" {
        $RunParseErrors.Count | Should Be 0
        $TestParseErrors.Count | Should Be 0
        $StopParseErrors.Count | Should Be 0
    }

    It "starts only the pinned source on exact loopback port 4141" {
        $RunText | Should Match '"copilot-api"'
        $RunText | Should Match '"src[\\/]main\.ts"'
        $RunText | Should Match '"--host",\s*"127\.0\.0\.1"'
        $RunText | Should Match '"--port",\s*"4141"'
        $RunText | Should Match '\.dev-cycle[\\/]copilot-api-2103'
        $RunText | Should Match 'StartTimeUtcTicks'
        $RunText | Should Not Match 'github-token|show-token'
    }

    It "uses finite sanitized model verification" {
        Mock Invoke-RestMethod { throw "secret response content" }
        Mock Get-NetTCPConnection {
            [pscustomobject]@{
                LocalAddress = "127.0.0.1"
                LocalPort = 4141
                OwningProcess = 41
                State = "Listen"
            }
        }
        Mock Get-Process {
            [pscustomobject]@{
                Id = 41
                StartTime = [datetime]::new(
                    2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
                )
            }
        }
        Mock Start-Sleep {}

        $captured = ""
        try {
            Test-CopilotApiHealth -ExpectedPid 41 -Attempts 1
        } catch {
            $captured = $_ | Out-String
        }

        $captured | Should Match "Copilot API verification failed"
        $captured | Should Not Match "secret response content"
        Assert-MockCalled Invoke-RestMethod -Times 1 -Exactly -ParameterFilter {
            $Uri -eq "http://127.0.0.1:4141/v1/models" -and
            $ConnectionTimeoutSeconds -eq 3 -and
            $OperationTimeoutSeconds -eq 10
        }
    }

    It "returns only a non-sensitive model identifier on success" {
        Mock Invoke-RestMethod {
            [pscustomobject]@{
                data = @(
                    [pscustomobject]@{ id = "model-safe"; secret = "ignored" }
                )
            }
        }
        Mock Get-NetTCPConnection {
            [pscustomobject]@{
                LocalAddress = "127.0.0.1"
                LocalPort = 4141
                OwningProcess = 41
                State = "Listen"
            }
        }
        Mock Get-Process {
            [pscustomobject]@{
                Id = 41
                StartTime = [datetime]::new(
                    2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
                )
            }
        }

        $result = Test-CopilotApiHealth -ExpectedPid 41 -Attempts 1

        $result.Healthy | Should Be $true
        $result.ModelId | Should Be "model-safe"
        ($result.PSObject.Properties.Name -join ",") |
            Should Be "Healthy,ModelId"
    }

    It "stops only a matching recorded PID identity" {
        Mock Get-Process {
            [pscustomobject]@{
                Id = 41
                StartTime = [datetime]::new(
                    2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
                )
            }
        }
        Mock Stop-Process {}
        Mock Wait-CopilotApiProcessExit { $true }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            ).Ticks
        }

        Stop-CopilotApiOwnedProcess -State $state

        Assert-MockCalled Stop-Process -Times 1 -Exactly -ParameterFilter {
            $Id -eq 41
        }
    }

    It "does not stop a reused PID" {
        Mock Get-Process {
            [pscustomobject]@{
                Id = 41
                StartTime = [datetime]::new(
                    2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
                )
            }
        }
        Mock Stop-Process {}
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = 1
        }

        { Stop-CopilotApiOwnedProcess -State $state } |
            Should Throw "PID state does not match the running process."

        Assert-MockCalled Stop-Process -Times 0 -Scope It
    }

    It "never uses broad process termination" {
        ($RunText + $TestText + $StopText) |
            Should Not Match 'Stop-Process\s+-(Name|InputObject)'
    }
}
