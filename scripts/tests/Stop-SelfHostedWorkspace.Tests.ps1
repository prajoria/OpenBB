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

    It "does not stop a descendant whose PID identity changed after discovery" {
        Mock Get-CimInstance {
            @(
                [pscustomobject]@{
                    ProcessId = 42
                    ParentProcessId = 41
                    CreationDate = [datetime]::new(
                        2026, 1, 1, 0, 0, 1, [DateTimeKind]::Utc
                    )
                }
            )
        } -ParameterFilter { -not $Filter }
        Mock Get-CimInstance {
            [pscustomobject]@{
                ProcessId = 42
                ParentProcessId = 99
                CreationDate = [datetime]::new(
                    2026, 1, 1, 0, 0, 2, [DateTimeKind]::Utc
                )
            }
        } -ParameterFilter { $Filter -eq "ProcessId = 42" }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            ).Ticks
        }

        Stop-WorkspaceFrontendProcess -State $state

        Assert-MockCalled Stop-Process -Times 0 -ParameterFilter { $Id -eq 42 }
        Assert-MockCalled Stop-Process -Times 1 -ParameterFilter { $Id -eq 41 }
    }

    It "does not adopt a stale child relationship from before the parent started" {
        Mock Get-CimInstance {
            @(
                [pscustomobject]@{
                    ProcessId = 42
                    ParentProcessId = 41
                    CreationDate = [datetime]::new(
                        2025, 12, 31, 23, 59, 59, [DateTimeKind]::Utc
                    )
                }
            )
        } -ParameterFilter { -not $Filter }
        Mock Get-CimInstance {
            [pscustomobject]@{
                ProcessId = 42
                ParentProcessId = 41
                CreationDate = [datetime]::new(
                    2025, 12, 31, 23, 59, 59, [DateTimeKind]::Utc
                )
            }
        } -ParameterFilter { $Filter -eq "ProcessId = 42" }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            ).Ticks
        }

        Stop-WorkspaceFrontendProcess -State $state

        Assert-MockCalled Stop-Process -Times 0 -ParameterFilter { $Id -eq 42 }
        Assert-MockCalled Stop-Process -Times 1 -ParameterFilter { $Id -eq 41 }
    }

    It "does not adopt descendants when the parent PID changed in the snapshot" {
        Mock Get-CimInstance {
            @(
                [pscustomobject]@{
                    ProcessId = 41
                    ParentProcessId = 10
                    CreationDate = [datetime]::new(
                        2026, 1, 1, 0, 0, 2, [DateTimeKind]::Utc
                    )
                },
                [pscustomobject]@{
                    ProcessId = 42
                    ParentProcessId = 41
                    CreationDate = [datetime]::new(
                        2026, 1, 1, 0, 0, 3, [DateTimeKind]::Utc
                    )
                }
            )
        } -ParameterFilter { -not $Filter }
        Mock Get-CimInstance {
            [pscustomobject]@{
                ProcessId = 42
                ParentProcessId = 41
                CreationDate = [datetime]::new(
                    2026, 1, 1, 0, 0, 3, [DateTimeKind]::Utc
                )
            }
        } -ParameterFilter { $Filter -eq "ProcessId = 42" }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            ).Ticks
        }

        Stop-WorkspaceFrontendProcess -State $state

        Assert-MockCalled Stop-Process -Times 0 -ParameterFilter { $Id -eq 42 }
        Assert-MockCalled Stop-Process -Times 1 -ParameterFilter { $Id -eq 41 }
    }

    It "stops a descendant from the matching parent snapshot" {
        Mock Get-Process {
            [pscustomobject]@{
                Id = 41
                StartTime = [datetime]::new(
                    2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
                ).AddTicks(9)
            }
        }
        Mock Get-CimInstance {
            @(
                [pscustomobject]@{
                    ProcessId = 41
                    ParentProcessId = 10
                    CreationDate = [datetime]::new(
                        2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
                    )
                },
                [pscustomobject]@{
                    ProcessId = 42
                    ParentProcessId = 41
                    CreationDate = [datetime]::new(
                        2026, 1, 1, 0, 0, 1, [DateTimeKind]::Utc
                    )
                }
            )
        } -ParameterFilter { -not $Filter }
        Mock Get-CimInstance {
            [pscustomobject]@{
                ProcessId = 42
                ParentProcessId = 41
                CreationDate = [datetime]::new(
                    2026, 1, 1, 0, 0, 1, [DateTimeKind]::Utc
                )
            }
        } -ParameterFilter { $Filter -eq "ProcessId = 42" }
        $state = [pscustomobject]@{
            Pid = 41
            StartTimeUtcTicks = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            ).AddTicks(9).Ticks
        }

        Stop-WorkspaceFrontendProcess -State $state

        Assert-MockCalled Stop-Process -Times 1 -ParameterFilter { $Id -eq 42 }
        Assert-MockCalled Stop-Process -Times 1 -ParameterFilter { $Id -eq 41 }
    }

    It "removes malformed PID state and still performs exact Compose cleanup" {
        Mock Test-Path { $true }
        Mock Remove-Item {}
        Mock Stop-WorkspaceFrontendProcess {}
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        foreach ($badState in @(
            '{"Pid":',
            '{"Pid":"not-an-integer"}',
            '{"Pid":0,"StartTimeUtcTicks":0}'
        )) {
            Mock Get-Content { $badState }
            Invoke-SelfHostedWorkspaceStop
        }

        Assert-MockCalled Remove-Item -Times 3 -Exactly -ParameterFilter {
            $Path -like "*frontend.pid.json"
        }
        Assert-MockCalled Stop-WorkspaceFrontendProcess -Times 0
        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 3 -Exactly
    }

    It "always stops Compose when frontend cleanup throws" {
        Mock Test-Path { $true }
        Mock Get-Content {
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        }
        Mock Remove-Item {}
        Mock Stop-WorkspaceFrontendProcess {
            throw "sensitive frontend cleanup detail"
        }
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        $captured = ""
        try {
            Invoke-SelfHostedWorkspaceStop
        } catch {
            $captured = $_.Exception.Message
        }

        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
        Assert-MockCalled Remove-Item -Times 1 -Exactly -Scope It
        $captured | Should Match "Frontend cleanup failed"
        $captured | Should Not Match "sensitive frontend cleanup detail"
    }

    It "still stops Compose when frontend state inspection throws" {
        Mock Test-Path { $true }
        Mock Get-Content {
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        }
        Mock Get-Process { throw "sensitive process inspection detail" }
        Mock Remove-Item {}
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        { Invoke-SelfHostedWorkspaceStop } | Should Throw "Frontend cleanup failed."

        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
    }

    It "still stops Compose when descendant enumeration throws" {
        Mock Test-Path { $true }
        Mock Get-Content {
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        }
        Mock Get-WorkspaceDescendantProcessIds {
            throw "sensitive descendant enumeration detail"
        }
        Mock Remove-Item {}
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        { Invoke-SelfHostedWorkspaceStop } | Should Throw "Frontend cleanup failed."

        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
    }

    It "still stops Compose when descendant identity validation throws" {
        Mock Test-Path { $true }
        Mock Get-Content {
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        }
        Mock Get-WorkspaceDescendantProcessIds {
            [pscustomobject]@{
                ProcessId = 42
                ParentProcessId = 41
                CreationDate = [datetime]::new(
                    2026, 1, 1, 0, 0, 1, [DateTimeKind]::Utc
                )
            }
        }
        Mock Test-WorkspaceProcessIdentity {
            throw "sensitive identity validation detail"
        }
        Mock Remove-Item {}
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        { Invoke-SelfHostedWorkspaceStop } | Should Throw "Frontend cleanup failed."

        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
    }

    It "still stops Compose when frontend termination throws" {
        Mock Test-Path { $true }
        Mock Get-Content {
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        }
        Mock Get-WorkspaceDescendantProcessIds { @() }
        Mock Stop-Process { throw "sensitive frontend termination detail" }
        Mock Remove-Item {}
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        { Invoke-SelfHostedWorkspaceStop } | Should Throw "Frontend cleanup failed."

        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
    }

    It "reports both cleanup failures only after attempting Compose" {
        Mock Test-Path { $true }
        Mock Get-Content {
            '{"Pid":41,"StartTimeUtcTicks":639028224000000000}'
        }
        Mock Remove-Item {}
        Mock Stop-WorkspaceFrontendProcess {
            throw "sensitive frontend cleanup detail"
        }
        Mock Invoke-WorkspaceComposeDown {
            throw "sensitive Compose cleanup detail"
        }
        Mock Write-Host {}

        $captured = ""
        try {
            Invoke-SelfHostedWorkspaceStop
        } catch {
            $captured = $_.Exception.Message
        }

        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
        $captured | Should Match "Frontend cleanup failed"
        $captured | Should Match "Compose cleanup failed"
        $captured | Should Not Match "sensitive"
    }

    It "uses an in-memory frontend process when PID state was not written" {
        $frontend = [pscustomobject]@{
            Id = 41
            StartTime = [datetime]::new(
                2026, 1, 1, 0, 0, 0, [DateTimeKind]::Utc
            )
        }
        Mock Test-Path {
            if ($Path -like "*frontend.pid.json") {
                return $false
            }
            return $true
        }
        Mock Stop-WorkspaceFrontendProcess {}
        Mock Invoke-WorkspaceComposeDown {}
        Mock Write-Host {}

        Invoke-SelfHostedWorkspaceStop -FrontendProcess $frontend

        Assert-MockCalled Stop-WorkspaceFrontendProcess -Times 1 -Exactly -Scope It `
            -ParameterFilter {
                $State.Pid -eq 41 -and
                $State.StartTimeUtcTicks -eq $frontend.StartTime.Ticks
            }
        Assert-MockCalled Invoke-WorkspaceComposeDown -Times 1 -Exactly -Scope It
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
