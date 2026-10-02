Describe "Self-hosted Workspace verifier" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\test_self_hosted_workspace.ps1"
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

    It "is valid PowerShell and is read-only" {
        $ParseErrors.Count | Should Be 0
        $ScriptText |
            Should Not Match '"(?-i:up|down|start|stop|build|run|exec)"'
        $ScriptText | Should Not Match '\b(Set|New|Remove)-Item\b'
        $ScriptText | Should Not Match 'Stop-Process'
        $ScriptText | Should Not Match '\b(Start|Register)-Job\b'
    }

    It "uses the exact Compose project and expected services" {
        $ScriptText | Should Match 'openbb-workspace-2110'
        $ScriptText | Should Match 'docker-compose-local-dev-sqlite\.yml'
        $ScriptText | Should Match 'workspace-compose\.secrets'

        { Assert-WorkspaceExactServices -Actual @(
            "redis", "fastapi", "rq_worker"
        ) } | Should Not Throw
        { Assert-WorkspaceExactServices -Actual @(
            "redis", "fastapi", "rq_worker", "unexpected"
        ) } | Should Throw `
            "Workspace Compose services do not exactly match the expected running set."
    }

    It "requires both listeners to be bound only to IPv4 loopback" {
        Mock Get-NetTCPConnection {
            @(
                [pscustomobject]@{ LocalAddress = "127.0.0.1"; LocalPort = 8000 }
                [pscustomobject]@{ LocalAddress = "127.0.0.1"; LocalPort = 1420 }
            )
        }

        { Assert-WorkspaceLoopbackListeners } | Should Not Throw
        Assert-MockCalled Get-NetTCPConnection -Times 1 -Exactly
    }

    It "rejects wildcard or non-loopback listeners" {
        Mock Get-NetTCPConnection {
            @(
                [pscustomobject]@{ LocalAddress = "0.0.0.0"; LocalPort = 8000 }
                [pscustomobject]@{ LocalAddress = "127.0.0.1"; LocalPort = 1420 }
            )
        }

        { Assert-WorkspaceLoopbackListeners } |
            Should Throw "Workspace listener validation failed."
    }

    It "uses finite health requests and sanitizes failures" {
        Mock Invoke-WebRequest { throw "private response body" }

        $captured = ""
        try {
            Assert-WorkspaceHealth -Name "backend" `
                -Uri "http://127.0.0.1:8000/health" -Attempts 1
        } catch {
            $captured = $_ | Out-String
        }

        $captured | Should Match "backend health check failed"
        $captured | Should Not Match "private response body"
        Assert-MockCalled Invoke-WebRequest -Times 1 -Exactly -ParameterFilter {
            $ConnectionTimeoutSeconds -eq 3 -and
            $OperationTimeoutSeconds -eq 5
        }
    }

    It "executes a successful external command and returns only stdout" {
        $fixture = Join-Path $TestDrive "success.ps1"
        Set-Content -LiteralPath $fixture -Value @'
Write-Output "alpha"
Write-Output "beta"
Write-Error "discarded diagnostic" -ErrorAction Continue
exit 0
'@

        $actual = @(
            Invoke-WorkspaceVerificationCommand -FilePath (Join-Path $PSHOME "pwsh.exe") `
                -ArgumentList @("-NoProfile", "-File", $fixture) `
                -FailureMessage "Logical verification failure." `
                -TimeoutSeconds 5
        )

        $actual | Should Be @("alpha", "beta")
    }

    It "resolves applications safely and cleans up pre-assignment failures" {
        $ScriptText |
            Should Match 'Get-Command.*-CommandType Application'
        $ScriptText | Should Match 'CreateProcess\(\s*filePath,'
        $ScriptText | Should Match 'TerminateProcess'
        $ScriptText |
            Should Match '(?s)catch\s*\{\s*if \(assignedToJob\).*TerminateAndWait'
    }

    It "sanitizes nonzero external command output" {
        $fixture = Join-Path $TestDrive "nonzero.ps1"
        Set-Content -LiteralPath $fixture -Value @'
Write-Output "private stdout"
[Console]::Error.WriteLine("private stderr")
exit 7
'@

        $captured = ""
        try {
            $null = Invoke-WorkspaceVerificationCommand `
                -FilePath (Join-Path $PSHOME "pwsh.exe") `
                -ArgumentList @("-NoProfile", "-File", $fixture) `
                -FailureMessage "Logical verification failure." `
                -TimeoutSeconds 5
        } catch {
            $captured = $_ | Out-String
        }

        $captured | Should Match "Logical verification failure."
        $captured | Should Not Match "private stdout|private stderr|exit 7"
    }

    It "times out and removes the exact external command process tree" {
        $childFixture = Join-Path $TestDrive "timeout-child.ps1"
        $parentFixture = Join-Path $TestDrive "timeout-parent.ps1"
        $childPidPath = Join-Path $TestDrive "timeout-child.pid"
        Set-Content -LiteralPath $childFixture -Value @'
Start-Sleep -Seconds 30
'@
        Set-Content -LiteralPath $parentFixture -Value @'
param([string]$PwshPath, [string]$ChildScript, [string]$ChildPidPath)
$child = Start-Process -FilePath $PwshPath -ArgumentList @(
    "-NoProfile", "-File", $ChildScript
) -PassThru
Set-Content -LiteralPath $ChildPidPath -Value $child.Id
Start-Sleep -Seconds 30
'@

        $captured = ""
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $null = Invoke-WorkspaceVerificationCommand `
                -FilePath (Join-Path $PSHOME "pwsh.exe") `
                -ArgumentList @(
                    "-NoProfile", "-File", $parentFixture,
                    (Join-Path $PSHOME "pwsh.exe"), $childFixture, $childPidPath
                ) `
                -FailureMessage "Logical timeout failure." `
                -TimeoutSeconds 1
        } catch {
            $captured = $_ | Out-String
        } finally {
            $stopwatch.Stop()
        }

        $captured | Should Match "Logical timeout failure."
        $stopwatch.Elapsed.TotalSeconds | Should BeLessThan 8
        Test-Path $childPidPath | Should Be $true
        $childPid = [int](Get-Content $childPidPath -Raw)
        Get-Process -Id $childPid -ErrorAction SilentlyContinue |
            Should BeNullOrEmpty
    }

    It "removes descendants when a failing root exits first" {
        $childFixture = Join-Path $TestDrive "orphan-child.ps1"
        $parentFixture = Join-Path $TestDrive "orphan-parent.ps1"
        $childPidPath = Join-Path $TestDrive "orphan-child.pid"
        Set-Content -LiteralPath $childFixture -Value @'
Start-Sleep -Seconds 30
'@
        Set-Content -LiteralPath $parentFixture -Value @'
param([string]$PwshPath, [string]$ChildScript, [string]$ChildPidPath)
$child = Start-Process -FilePath $PwshPath -ArgumentList @(
    "-NoProfile", "-File", $ChildScript
) -PassThru
Set-Content -LiteralPath $ChildPidPath -Value $child.Id
exit 9
'@

        try {
            {
                Invoke-WorkspaceVerificationCommand `
                    -FilePath (Join-Path $PSHOME "pwsh.exe") `
                    -ArgumentList @(
                        "-NoProfile", "-File", $parentFixture,
                        (Join-Path $PSHOME "pwsh.exe"), $childFixture,
                        $childPidPath
                    ) `
                    -FailureMessage "Logical root failure." `
                    -TimeoutSeconds 5
            } | Should Throw "Logical root failure."

            Test-Path $childPidPath | Should Be $true
            $childPid = [int](Get-Content $childPidPath -Raw)
            Get-Process -Id $childPid -ErrorAction SilentlyContinue |
                Should BeNullOrEmpty
        } finally {
            if (Test-Path $childPidPath) {
                $childPid = [int](Get-Content $childPidPath -Raw)
                Stop-Process -Id $childPid -Force -ErrorAction SilentlyContinue
            }
        }
    }

    It "checks login with managed ignored credentials without exposing them" {
        $ScriptText | Should Match 'workspace-admin-credentials\.secrets'
        $ScriptText | Should Match 'check-ignore'
        $ScriptText | Should Not Match 'Write-(Host|Output).*(Email|Password|Credentials)'

        Mock Invoke-WebRequest { [pscustomobject]@{ StatusCode = 200 } }
        $credential = [pscustomobject]@{
            Email = "managed@example.invalid"
            Password = "private-value"
        }
        { Assert-WorkspaceManagedAdminLogin -Credential $credential } |
            Should Not Throw
        Assert-MockCalled Invoke-WebRequest -Times 1 -Exactly -ParameterFilter {
            $Uri -eq "http://127.0.0.1:8000/pro/login" -and
            $Method -eq "Post" -and
            $Body -match "private-value"
        }
    }

    It "requires exact allowed and rejected CORS preflight behavior" {
        Mock Invoke-WebRequest {
            if ($Headers.Origin -eq "http://127.0.0.1:1420") {
                return [pscustomobject]@{
                    StatusCode = 200
                    Headers = @{
                        "Access-Control-Allow-Origin" =
                            "http://127.0.0.1:1420"
                    }
                }
            }
            return [pscustomobject]@{
                StatusCode = 400
                Headers = @{}
            }
        }

        { Assert-WorkspaceCorsContract } | Should Not Throw
        Assert-MockCalled Invoke-WebRequest -Times 2 -Exactly `
            -ParameterFilter { $Method -eq "Options" }
    }

    It "sanitizes CORS transport failures" {
        Mock Invoke-WebRequest { throw "private CORS response body" }

        $captured = ""
        try {
            Assert-WorkspaceCorsContract
        } catch {
            $captured = $_ | Out-String
        }

        $captured | Should Match "Workspace CORS verification failed."
        $captured | Should Not Match "private CORS response body"
    }

    It "checks clean pinned source ignored secrets and absent npm lock" {
        $ScriptText | Should Match 'ls-tree'
        $ScriptText | Should Match '"status"'
        $ScriptText | Should Match '"--untracked-files=all"'
        $ScriptText | Should Match 'check-ignore'
        $ScriptText | Should Match 'package-lock\.json'
        $ScriptText | Should Match 'bun\.lock'
    }

    It "accepts scalar native output while checking the pinned commit" {
        $commit = "be00e95019a55d57af146919ee46b7e1a4859226"
        Mock Invoke-WorkspaceVerificationCommand {
            if ($ArgumentList -contains "ls-tree") {
                return "160000 commit $commit`tthird_party/workspace"
            }
            if ($ArgumentList -contains "rev-parse") {
                return $commit
            }
            return @()
        }
        Mock Test-Path {
            return $Path -like "*bun.lock"
        }

        { Assert-WorkspaceSourceAndRuntimeState } | Should Not Throw
    }

    It "rejects unexpected untracked files while ignored runtime files stay hidden" {
        $commit = "be00e95019a55d57af146919ee46b7e1a4859226"
        Mock Invoke-WorkspaceVerificationCommand {
            if ($ArgumentList -contains "ls-tree") {
                return "160000 commit $commit`tthird_party/workspace"
            }
            if ($ArgumentList -contains "rev-parse") {
                return $commit
            }
            if ($ArgumentList -contains "status") {
                return "?? unexpected-local-file.txt"
            }
            return @()
        }
        Mock Test-Path {
            return $Path -like "*bun.lock"
        }

        { Assert-WorkspaceSourceAndRuntimeState } |
            Should Throw "Workspace submodule contains tracked or unexpected untracked changes."
    }

    It "never prints response bodies or runtime secret contents" {
        $ScriptText | Should Not Match '\.Content'
        $ScriptText | Should Not Match 'Write-(Host|Output).*(Body|Content|Token|Secret|Password)'
        $ScriptText | Should Match 'Verification failed:'
    }
}
