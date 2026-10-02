Describe "Copilot API lifecycle" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $StartSource = Join-Path $RepoRoot "copilot-api\src\start.ts"
        $StartSourceText = Get-Content $StartSource -Raw
        $RunScript = Join-Path $RepoRoot "scripts\run_copilot_api.ps1"
        $TestScript = Join-Path $RepoRoot "scripts\test_copilot_api.ps1"
        $StopScript = Join-Path $RepoRoot "scripts\stop_copilot_api.ps1"
        $PwshPath = (Get-Process -Id $PID).Path
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
        . $RunScript
    }

    function New-MissingProcessError {
        return [System.Management.Automation.ErrorRecord]::new(
            [System.ArgumentException]::new("not found"),
            "NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.GetProcessCommand",
            [System.Management.Automation.ErrorCategory]::ObjectNotFound,
            41
        )
    }

    It "supports an explicit loopback host" {
        $StartSourceText |
            Should Match 'DEFAULT_HOST\s*=\s*"127\.0\.0\.1"'
        $StartSourceText | Should Match 'default:\s*DEFAULT_HOST'
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

    It "rolls startup back through only the retained process object" {
        $child = Start-Process -FilePath $PwshPath -ArgumentList @(
            "-NoLogo",
            "-NoProfile",
            "-Command",
            "Start-Sleep -Seconds 30"
        ) -PassThru
        $childHandle = $child.SafeHandle
        $script:ReplacementProcess =
            [System.Diagnostics.Process]::GetProcessById($PID)
        try {
            Mock Get-Process { $script:ReplacementProcess }
            Mock Stop-Process {
                $InputObject.Kill()
            }

            Stop-CopilotApiStartedProcess -Process $child

            Assert-MockCalled Get-Process -Times 0 -Exactly -Scope It
            Assert-MockCalled Stop-Process -Times 1 -Exactly -Scope It `
                -ParameterFilter {
                    $InputObject -eq $child -and $null -eq $Id
                }
            $childHandle.IsClosed | Should Be $true
        } finally {
            if (-not $childHandle.IsClosed -and -not $child.HasExited) {
                $child.Kill()
                $child.WaitForExit(5000) | Out-Null
            }
            if (-not $childHandle.IsClosed) {
                $child.Dispose()
            }
        }
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

    It "returns only a model count on success" {
        Mock Invoke-RestMethod {
            [pscustomobject]@{
                data = @(
                    [pscustomobject]@{
                        id = ("model`r`n" + ("x" * 300))
                        secret = "ignored"
                    }
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
        $result.ModelCount | Should Be 1
        ($result.PSObject.Properties.Name -join ",") |
            Should Be "Healthy,ModelCount"
    }

    It "stops only a matching recorded PID identity" {
        $script:OwnedProcessForTest =
            [System.Diagnostics.Process]::GetProcessById($PID)
        Mock Get-Process { $script:OwnedProcessForTest }
        Mock Stop-Process {}
        Mock Wait-CopilotApiProcessExit { $true }
        $state = [pscustomobject]@{
            Pid = $script:OwnedProcessForTest.Id
            StartTimeUtcTicks =
                $script:OwnedProcessForTest.StartTime.ToUniversalTime().Ticks
        }

        Stop-CopilotApiOwnedProcess -State $state

        Assert-MockCalled Stop-Process -Times 1 -Exactly -Scope It `
            -ParameterFilter {
                $InputObject.Id -eq $script:OwnedProcessForTest.Id
            }
    }

    It "terminates the retained matching process without reopening its PID" {
        $originalPidPath = $script:CopilotApiPidPath
        $script:CopilotApiPidPath = "TestDrive:\proxy.pid.json"
        $script:OwnedProcessForTest =
            [System.Diagnostics.Process]::GetProcessById($PID)
        [ordered]@{
            Pid = $script:OwnedProcessForTest.Id
            StartTimeUtcTicks =
                $script:OwnedProcessForTest.StartTime.ToUniversalTime().Ticks
        } | ConvertTo-Json |
            Set-Content $script:CopilotApiPidPath
        Mock Get-Process { $script:OwnedProcessForTest }
        Mock Stop-Process {}
        Mock Wait-CopilotApiProcessExit { $true }

        Stop-CopilotApi

        Assert-MockCalled Get-Process -Times 1 -Exactly -Scope It
        Assert-MockCalled Stop-Process -Times 1 -Exactly -Scope It `
            -ParameterFilter {
                $InputObject -eq $script:OwnedProcessForTest -and
                    $null -eq $Id
            }
        $script:CopilotApiPidPath = $originalPidPath
    }

    It "retains a native handle for the validated process" {
        $ownedProcess = [System.Diagnostics.Process]::GetProcessById($PID)
        $state = [pscustomobject]@{
            Pid = $ownedProcess.Id
            StartTimeUtcTicks =
                $ownedProcess.StartTime.ToUniversalTime().Ticks
        }
        Mock Get-Process { $ownedProcess }

        $snapshot = Get-CopilotApiProcessIdentitySnapshot -State $state
        $handleField = [System.Diagnostics.Process].GetField(
            "_haveProcessHandle",
            [System.Reflection.BindingFlags]"Instance,NonPublic"
        )

        $snapshot.Status | Should Be "Match"
        $handleField.GetValue($snapshot.Process) | Should Be $true
        $snapshot.Process.Dispose()
    }

    It "opens the native handle before reading process start time" {
        $script:ExpectedStartForOrdering = [datetime]::new(
            2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
        )
        $script:OrderingProcess = [pscustomobject]@{
            Id = 41
            HandleOpened = $false
        }
        $script:OrderingProcess | Add-Member -MemberType ScriptProperty `
            -Name SafeHandle -Value {
                $this.HandleOpened = $true
                return 1
            }
        $script:OrderingProcess | Add-Member -MemberType ScriptProperty `
            -Name StartTime -Value {
                if (-not $this.HandleOpened) {
                    throw "StartTime read before SafeHandle."
                }
                return $script:ExpectedStartForOrdering
            }
        Mock Get-Process { $script:OrderingProcess }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = $script:ExpectedStartForOrdering.Ticks
        }

        $snapshot = Get-CopilotApiProcessIdentitySnapshot -State $state

        $snapshot.Status | Should Be "Match"
        $snapshot.Process.HandleOpened | Should Be $true
    }

    It "disposes a supplied process when its identity mismatches" {
        $suppliedProcess = [pscustomobject]@{
            Id = 42
            StartTime = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            )
            Disposed = $false
        }
        $suppliedProcess | Add-Member -MemberType ScriptMethod `
            -Name Dispose -Value {
                $this.Disposed = $true
            }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = $suppliedProcess.StartTime.Ticks
        }

        {
            Stop-CopilotApiOwnedProcess -State $state `
                -Process $suppliedProcess
        } | Should Throw "PID state does not match the running process."

        $suppliedProcess.Disposed | Should Be $true
    }

    It "does not stop a reused PID" {
        $script:ReusedProcessForTest =
            [System.Diagnostics.Process]::GetProcessById($PID)
        Mock Get-Process { $script:ReusedProcessForTest }
        Mock Stop-Process {}
        $state = [pscustomobject]@{
            Pid = $script:ReusedProcessForTest.Id
            StartTimeUtcTicks = 1
        }

        { Stop-CopilotApiOwnedProcess -State $state } |
            Should Throw "PID state does not match the running process."

        Assert-MockCalled Stop-Process -Times 0 -Scope It
    }

    It "removes crashed-process stale state and reports stopped" {
        $originalPidPath = $script:CopilotApiPidPath
        $script:CopilotApiPidPath = "TestDrive:\proxy.pid.json"
        Set-Content $script:CopilotApiPidPath `
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        Mock Get-Process { throw (New-MissingProcessError) }
        Mock Stop-Process {}

        $output = Stop-CopilotApi 6>&1 | Out-String

        (Test-Path $script:CopilotApiPidPath) | Should Be $false
        $output | Should Match "stopped"
        Assert-MockCalled Stop-Process -Times 0 -Scope It
        $script:CopilotApiPidPath = $originalPidPath
    }

    It "keeps reused-PID state and never kills the reused process" {
        $originalPidPath = $script:CopilotApiPidPath
        $script:CopilotApiPidPath = "TestDrive:\proxy.pid.json"
        $script:ReusedProcessForTest =
            [System.Diagnostics.Process]::GetProcessById($PID)
        [ordered]@{
            Pid = $script:ReusedProcessForTest.Id
            StartTimeUtcTicks = 1
        } | ConvertTo-Json |
            Set-Content $script:CopilotApiPidPath
        Mock Get-Process { $script:ReusedProcessForTest }
        Mock Stop-Process {}

        { Stop-CopilotApi } |
            Should Throw "PID state does not match the running process."

        (Test-Path $script:CopilotApiPidPath) | Should Be $true
        Assert-MockCalled Stop-Process -Times 0 -Scope It
        $script:CopilotApiPidPath = $originalPidPath
    }

    It "clears crashed-process stale state before start proceeds" {
        $stalePath = "TestDrive:\proxy.pid.json"
        Set-Content $stalePath `
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        Mock Get-Process { throw (New-MissingProcessError) }

        Resolve-CopilotApiStartState -Path $stalePath

        (Test-Path $stalePath) | Should Be $false
    }

    It "fails closed on reused PID before start" {
        $reusedPath = "TestDrive:\proxy.pid.json"
        $script:ReusedProcessForTest =
            [System.Diagnostics.Process]::GetProcessById($PID)
        [ordered]@{
            Pid = $script:ReusedProcessForTest.Id
            StartTimeUtcTicks = 1
        } | ConvertTo-Json | Set-Content $reusedPath
        Mock Get-Process { $script:ReusedProcessForTest }

        { Resolve-CopilotApiStartState -Path $reusedPath } |
            Should Throw "PID state does not match the running process."

        (Test-Path $reusedPath) | Should Be $true
    }

    It "fails closed when process identity cannot be inspected" {
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = 1
        }
        Mock Get-Process {
            throw [System.UnauthorizedAccessException]::new("denied")
        }

        { Get-CopilotApiProcessIdentityStatus -State $state } |
            Should Throw "Copilot API process identity could not be inspected."
    }

    It "never uses broad process termination" {
        ($RunText + $TestText + $StopText) |
            Should Not Match 'Stop-Process\s+-Name'
    }
}
