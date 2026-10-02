Describe "Workspace development smoke checker" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\test_workspace_dev.ps1"
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
        $script:requests = @()
        Mock Invoke-RestMethod {
            param($Uri)
            $script:requests += [pscustomobject]@{
                Uri = $Uri
                SkipCertificateCheck = $SkipCertificateCheck.IsPresent
            }

            switch ($Uri) {
                "https://127.0.0.1:6902/widgets.json" {
                    return [pscustomobject]@{ portfolio_summary = @{} }
                }
                "https://127.0.0.1:6902/apps.json" {
                    return ,([pscustomobject]@{ name = "Portfolio Overview" })
                }
                "https://127.0.0.1:6902/agents.json" {
                    return [pscustomobject]@{ portfolio_copilot_proxy = @{} }
                }
                "http://127.0.0.1:6120/widgets.json" {
                    return [pscustomobject]@{ intelligence_summary = @{} }
                }
                "http://127.0.0.1:6120/apps.json" {
                    return ,([pscustomobject]@{ name = "Portfolio Intelligence" })
                }
                default { throw "Unexpected URI: $Uri" }
            }
        }
        Mock Write-Host {}
    }

    It "is valid PowerShell" {
        $ParseErrors.Count | Should Be 0
    }

    It "checks all five discovery surfaces and prints counts only" {
        Invoke-WorkspaceDevSmokeCheck

        $script:requests.Count | Should Be 5
        Assert-MockCalled Write-Host -Times 5 -Exactly -ParameterFilter {
            $Object -match '^\[PASS\] (PortfolioWidgets|PortfolioApps|PortfolioAgents|IntelWidgets|IntelApps): 1$'
        }
        Assert-MockCalled Write-Host -Times 0 -ParameterFilter {
            $Object -match "Portfolio Overview|portfolio_summary|Portfolio Intelligence|intelligence_summary"
        }
    }

    It "requires explicit TLS bypass for Portfolio requests" {
        Invoke-WorkspaceDevSmokeCheck -SkipCertificateCheck

        @(
            $script:requests |
                Where-Object { $_.Uri -like "https://127.0.0.1:6902/*" }
        ).Count | Should Be 3
        @(
            $script:requests |
                Where-Object {
                    $_.Uri -like "https://127.0.0.1:6902/*" -and
                    $_.SkipCertificateCheck
                }
        ).Count | Should Be 3
        @(
            $script:requests |
                Where-Object {
                    $_.Uri -like "http://127.0.0.1:6120/*" -and
                    $_.SkipCertificateCheck
                }
        ).Count | Should Be 0
    }

    It "does not bypass TLS unless explicitly requested" {
        Invoke-WorkspaceDevSmokeCheck

        @(
            $script:requests | Where-Object { $_.SkipCertificateCheck }
        ).Count | Should Be 0
    }

    It "uses a finite timeout for every discovery request" {
        Invoke-WorkspaceDevSmokeCheck

        Assert-MockCalled Invoke-RestMethod -Times 5 -Exactly -Scope It `
            -ParameterFilter { $ConnectionTimeoutSeconds -eq 10 }
    }

    It "sanitizes endpoint failures on every output stream" {
        $sensitiveBody = "account=123456789&token=top-secret"
        $script:capturedError = ""
        Mock Invoke-RestMethod {
            $exception = [System.Exception]::new("HTTP request failed")
            $errorRecord = [System.Management.Automation.ErrorRecord]::new(
                $exception,
                "SensitiveServerResponse",
                [System.Management.Automation.ErrorCategory]::InvalidOperation,
                $null
            )
            $errorRecord.ErrorDetails =
                [System.Management.Automation.ErrorDetails]::new($sensitiveBody)
            throw $errorRecord
        }

        $successOutput = & {
            try {
                Invoke-WorkspaceDevSmokeCheck
            } catch {
                $script:capturedError = $_ | Out-String
            }
        } *>&1 | Out-String

        $successOutput | Should Not Match ([regex]::Escape($sensitiveBody))
        $script:capturedError | Should Not Match ([regex]::Escape($sensitiveBody))
        $script:capturedError |
            Should Match "PortfolioWidgets request failed for https://127.0.0.1:6902/widgets.json"
    }

    $emptySurfaces = @(
        @{
            Name = "Portfolio widgets"
            Endpoint = "https://127.0.0.1:6902/widgets.json"
            Expected = "PortfolioWidgets discovery returned no entries"
        },
        @{
            Name = "Portfolio apps"
            Endpoint = "https://127.0.0.1:6902/apps.json"
            Expected = "PortfolioApps discovery returned no entries"
        },
        @{
            Name = "Portfolio agents"
            Endpoint = "https://127.0.0.1:6902/agents.json"
            Expected = "PortfolioAgents discovery returned no entries"
        },
        @{
            Name = "Portfolio Intelligence widgets"
            Endpoint = "http://127.0.0.1:6120/widgets.json"
            Expected = "IntelWidgets discovery returned no entries"
        },
        @{
            Name = "Portfolio Intelligence apps"
            Endpoint = "http://127.0.0.1:6120/apps.json"
            Expected = "IntelApps discovery returned no entries"
        }
    )

    It "fails when <Name> discovery is empty" -TestCases $emptySurfaces {
        param($Endpoint, $Expected)

        $targetEndpoint = $Endpoint
        Mock Invoke-RestMethod { @() } -ParameterFilter {
            $Uri -eq $targetEndpoint
        }

        { Invoke-WorkspaceDevSmokeCheck } | Should Throw $Expected
    }
}
