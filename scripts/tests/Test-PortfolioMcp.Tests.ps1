$ScriptPath = Join-Path $PSScriptRoot "..\test_portfolio_mcp.ps1"
. $ScriptPath

function New-Tool {
    param(
        [string]$Name,
        [string[]]$Providers = @()
    )
    return [pscustomobject]@{
        name = $Name
        inputSchema = [pscustomobject]@{
            properties = [pscustomobject]@{
                provider = if ($Providers.Count) {
                    [pscustomobject]@{ enum = $Providers }
                } else {
                    $null
                }
            }
        }
    }
}

Describe "Portfolio MCP package replay contract" {
    It "declares protocol and package modes" {
        $command = Get-Command $ScriptPath
        $validateSet = $command.Parameters["Mode"].Attributes |
            Where-Object { $_ -is [System.Management.Automation.ValidateSetAttribute] }
        @($validateSet.ValidValues) -join "," |
            Should Be "protocol,package,workspace-no-browser,workspace-read,workspace-mutation,operator-fixture,provider-live"
    }

    It "reports a missing replay interpreter explicitly" {
        {
            Test-PackageReplay -RuntimeProfile "portfolio-read" `
                -Python (Join-Path $TestDrive "missing-python.exe") `
                -Root (Split-Path $PSScriptRoot -Parent)
        } | Should Throw "Package replay Python executable is unavailable."
    }

    It "preserves an unsupported interpreter constraint diagnostic" {
        $fakePython = Join-Path $TestDrive "python-3.14.cmd"
        @'
@echo off
        echo 3.14
        exit /b 0
'@ | Set-Content -LiteralPath $fakePython -Encoding UTF8
        $message = ""
        try {
            Test-PackageReplay -RuntimeProfile "portfolio-read" `
                -Python $fakePython `
                -Root (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
            throw "Unsupported interpreter replay unexpectedly succeeded."
        } catch {
            $message = $_.Exception.Message
        }
        $message | Should Match "Unsupported Python 3\.14"
        $message | Should Match ([regex]::Escape(">=3.10,<3.14"))
    }
}

Describe "Workspace MCP parity safety contract" {
    It "rejects mutation without explicit approval" {
        {
            Test-WorkspaceParity -WorkspaceMode mutation `
                -Root (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                -DashboardId "disposable-dashboard"
        } | Should Throw "Workspace mutation requires -AllowWorkspaceMutation."
    }

    It "rejects mutation without a disposable dashboard" {
        {
            Test-WorkspaceParity -WorkspaceMode mutation `
                -Root (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                -MutationApproved
        } | Should Throw "Workspace mutation requires -DisposableDashboardId."
    }
}

Describe "Controlled provider and operator safety contract" {
    It "rejects operator fixture without maintenance approval" {
        {
            Test-OperatorFixture -Python $PSHOME\pwsh.exe `
                -Root (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
        } | Should Throw "Operator fixture requires -AllowMaintenance."
    }

    It "rejects paid provider calls without explicit approval" {
        {
            Test-ProviderLive `
                -Root (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                -RequestLimit 1 -Symbol "AAPL"
        } | Should Throw "Provider live verification requires -AllowPaidRequests."
    }

    It "caps paid provider requests at two" {
        {
            Test-ProviderLive `
                -Root (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                -PaidApproved -RequestLimit 3 -Symbol "AAPL"
        } | Should Throw "Provider live verification permits at most two requests."
    }
}

Describe "Portfolio MCP session lifecycle" {
    BeforeEach {
        $script:sessionDeleted = $false
        Mock Invoke-WebRequest {
            if ($Method -eq "Delete") {
                $script:sessionDeleted = $true
            }
            return [pscustomobject]@{
                Headers = @{ "Mcp-Session-Id" = "test-session" }
                StatusCode = 200
                Content = ""
            }
        }
        Mock Invoke-McpRequest {
            [pscustomobject]@{ result = [pscustomobject]@{} }
        }
        Mock Get-StructuredResult {
            @([pscustomobject]@{ name = "equity"; total_tools = 1 })
        }
        Mock Get-McpPages {
            if ($ResultProperty -eq "tools") {
                return @(
                    New-Tool -Name "equity_price_historical" `
                        -Providers @("fmp")
                )
            }
            return @(
                [pscustomobject]@{ name = "system_prompt" },
                [pscustomobject]@{ name = "equity_deep_dive" }
            )
        }
        Mock Assert-McpCapabilityContract {}
    }

    It "closes the session after a successful probe" {
        $result = Test-PortfolioMcp -RuntimeProfile "platform-standard" `
            -RequestUri "http://127.0.0.1:8001/mcp" `
            -AuthHeader "" -RequestTimeout 5
        $result.ready | Should Be $true
        $script:sessionDeleted | Should Be $true
    }

    It "activates the cache category before Portfolio discovery" {
        $script:activatedCategories = @()
        Mock Get-StructuredResult {
            @(
                [pscustomobject]@{ name = "equity"; total_tools = 1 },
                [pscustomobject]@{ name = "portfolio_intel"; total_tools = 1 },
                [pscustomobject]@{ name = "techtrade"; total_tools = 1 },
                [pscustomobject]@{ name = "backtest"; total_tools = 1 },
                [pscustomobject]@{ name = "regime"; total_tools = 1 },
                [pscustomobject]@{ name = "cache"; total_tools = 2 }
            )
        }
        Mock Invoke-McpRequest {
            if ($Message.params.name -eq "activate_category") {
                $script:activatedCategories +=
                    $Message.params.arguments.category
            }
            [pscustomobject]@{ result = [pscustomobject]@{} }
        }
        Mock Get-McpPages {
            if ($ResultProperty -eq "tools") {
                if ($script:activatedCategories -notcontains "cache") {
                    throw "tools/list ran before cache activation"
                }
                return @()
            }
            return @()
        }

        Test-PortfolioMcp -RuntimeProfile "portfolio-read" `
            -RequestUri "http://127.0.0.1:8001/mcp" `
            -AuthHeader "Basic synthetic" -RequestTimeout 5 | Out-Null

        ($script:activatedCategories -contains "cache") | Should Be $true
    }

    It "redacts and closes the session after a failed probe" {
        Mock Assert-McpCapabilityContract {
            throw "token secret-value"
        }
        try {
            Test-PortfolioMcp -RuntimeProfile "platform-standard" `
                -RequestUri "http://127.0.0.1:8001/mcp" `
                -AuthHeader "" -RequestTimeout 5
            throw "Probe unexpectedly succeeded."
        } catch {
            $_.Exception.Message | Should Not Match "secret-value"
            $_.Exception.Message | Should Match "\[redacted\]"
        }
        $script:sessionDeleted | Should Be $true
    }

    It "fails readiness when a successful probe cannot close its session" {
        Mock Invoke-WebRequest {
            if ($Method -eq "Delete") {
                throw "cleanup transport failed"
            }
            return [pscustomobject]@{
                Headers = @{ "Mcp-Session-Id" = "test-session" }
                StatusCode = 200
                Content = ""
            }
        }
        {
            Test-PortfolioMcp -RuntimeProfile "platform-standard" `
                -RequestUri "http://127.0.0.1:8001/mcp" `
                -AuthHeader "" -RequestTimeout 5
        } | Should Throw "MCP readiness failed: session cleanup failed."
    }

    It "distinguishes an unavailable transport" {
        Mock Invoke-WebRequest {
            throw [System.Net.Http.HttpRequestException]::new(
                "connection refused"
            )
        }
        {
            Test-PortfolioMcp -RuntimeProfile "platform-standard" `
                -RequestUri "http://127.0.0.1:8001/mcp" `
                -AuthHeader "" -RequestTimeout 5
        } | Should Throw "MCP readiness failed: transport unavailable."
    }
}
Describe "Portfolio MCP readiness contract" {
    BeforeEach {
        $script:PreviousMaintenanceSetting =
            $env:OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS
        Remove-Item Env:OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS `
            -ErrorAction SilentlyContinue
    }
    AfterEach {
        if ($null -eq $script:PreviousMaintenanceSetting) {
            Remove-Item Env:OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS `
                -ErrorAction SilentlyContinue
        } else {
            $env:OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS =
                $script:PreviousMaintenanceSetting
        }
    }
    $contractCategories = @(
        [pscustomobject]@{ name = "equity" },
        [pscustomobject]@{ name = "portfolio_intel"; total_tools = 5 },
        [pscustomobject]@{ name = "techtrade"; total_tools = 8 },
        [pscustomobject]@{ name = "backtest"; total_tools = 9 },
        [pscustomobject]@{ name = "regime"; total_tools = 1 },
        [pscustomobject]@{ name = "cache"; total_tools = 2 }
    )
    $contractPrompts = @(
        [pscustomobject]@{ name = "system_prompt" },
        [pscustomobject]@{ name = "equity_deep_dive" },
        [pscustomobject]@{ name = "portfolio_performance_review" },
        [pscustomobject]@{ name = "fmp_cached_portfolio_refresh" }
    )
    $contractTools = @(
        (New-Tool -Name "equity_price_historical" -Providers @("fmp", "yfinance")),
        (New-Tool -Name "portfolio_intel_about"),
        (New-Tool -Name "techtrade_about"),
        (New-Tool -Name "backtest_about"),
        (New-Tool -Name "regime_detect"),
        (New-Tool -Name "cache_health"),
        (New-Tool -Name "cache_coverage")
    )

    It "accepts the standard provider and prompt contract" {
        Assert-McpCapabilityContract -RuntimeProfile "platform-standard" `
            -Categories $contractCategories -Tools $contractTools -Prompts $contractPrompts
    }

    It "accepts Portfolio custom adapters without invoking them" {
        $portfolioTools = @($contractTools) + @(
            (New-Tool -Name "equity_cached" -Providers @("fmp"))
        )
        Assert-McpCapabilityContract -RuntimeProfile "portfolio-read" `
            -Categories $contractCategories -Tools $portfolioTools `
            -Prompts $contractPrompts
    }

    It "requires operator-only capabilities for the ops profile" {
        $opsTools = @($contractTools) + @(
            (New-Tool -Name "equity_cached" -Providers @("fmp")),
            (New-Tool -Name "backtest_bundle_ingest"),
            (New-Tool -Name "techtrade_export"),
            (New-Tool -Name "techtrade_tune")
        )
        Assert-McpCapabilityContract -RuntimeProfile "portfolio-ops" `
            -Categories $contractCategories -Tools $opsTools -Prompts $contractPrompts
    }

    It "requires the guarded cache catalog when maintenance is enabled" {
        $env:OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS = "true"
        $opsTools = @($contractTools) + @(
            (New-Tool -Name "equity_cached" -Providers @("fmp")),
            (New-Tool -Name "backtest_bundle_ingest"),
            (New-Tool -Name "techtrade_export"),
            (New-Tool -Name "techtrade_tune"),
            (New-Tool -Name "cache_jobs_definitions"),
            (New-Tool -Name "cache_jobs_health"),
            (New-Tool -Name "cache_jobs_run"),
            (New-Tool -Name "cache_jobs_trigger_position_history"),
            (New-Tool -Name "cache_jobs_trigger_etf_holdings")
        )
        Assert-McpCapabilityContract -RuntimeProfile "portfolio-ops" `
            -Categories $contractCategories -Tools $opsTools `
            -Prompts $contractPrompts

        $missingRunStatus = @(
            $opsTools | Where-Object name -ne "cache_jobs_run"
        )
        {
            Assert-McpCapabilityContract -RuntimeProfile "portfolio-ops" `
                -Categories $contractCategories -Tools $missingRunStatus `
                -Prompts $contractPrompts
        } | Should Throw "Missing required adapter 'cache_jobs_run'."
    }

    It "rejects cache maintenance tools without explicit opt-in" {
        $unexpected = @($contractTools) + @(
            (New-Tool -Name "equity_cached" -Providers @("fmp")),
            (New-Tool -Name "backtest_bundle_ingest"),
            (New-Tool -Name "techtrade_export"),
            (New-Tool -Name "techtrade_tune"),
            (New-Tool -Name "cache_jobs_run")
        )
        {
            Assert-McpCapabilityContract -RuntimeProfile "portfolio-ops" `
                -Categories $contractCategories -Tools $unexpected `
                -Prompts $contractPrompts
        } | Should Throw "Denied capability 'cache_jobs_run' is exposed."
    }

    It "rejects operator capabilities from the read profile" {
        $overexposed = @($contractTools) + @(
            (New-Tool -Name "equity_cached" -Providers @("fmp")),
            (New-Tool -Name "techtrade_export")
        )
        {
            Assert-McpCapabilityContract -RuntimeProfile "portfolio-read" `
                -Categories $contractCategories -Tools $overexposed -Prompts $contractPrompts
        } | Should Throw "Denied capability 'techtrade_export' is exposed."
    }

    It "distinguishes a missing package category" {
        {
            Assert-McpCapabilityContract -RuntimeProfile "portfolio-read" `
                -Categories @([pscustomobject]@{ name = "news" }) `
                -Tools $contractTools -Prompts $contractPrompts
        } | Should Throw "Missing required category 'equity'."
    }

    It "distinguishes a missing custom adapter route" {
        $missingAdapterTools = @(
            $contractTools | Where-Object name -ne "techtrade_about"
        ) + @(
            New-Tool -Name "equity_cached" -Providers @("fmp")
        )
        {
            Assert-McpCapabilityContract -RuntimeProfile "portfolio-read" `
                -Categories $contractCategories `
                -Tools $missingAdapterTools `
                -Prompts $contractPrompts
        } | Should Throw "Missing required adapter 'techtrade_about'."
    }

    It "distinguishes a missing FMP provider choice" {
        $withoutFmp = @(
            (New-Tool -Name "equity_price_historical" -Providers @("yfinance")),
            (New-Tool -Name "portfolio_intel_about"),
            (New-Tool -Name "techtrade_about"),
            (New-Tool -Name "backtest_about"),
            (New-Tool -Name "regime_detect"),
            (New-Tool -Name "cache_health"),
            (New-Tool -Name "cache_coverage")
        )
        {
            Assert-McpCapabilityContract -RuntimeProfile "portfolio-read" `
                -Categories $contractCategories -Tools $withoutFmp -Prompts $contractPrompts
        } | Should Throw "Missing required provider choice 'fmp'."
    }

    It "redacts credential-shaped diagnostics" {
        $content = "event: message`ndata: " +
            '{"jsonrpc":"2.0","error":{"code":-32001,"message":"token secret-value"}}'
        {
            ConvertFrom-McpEvent -Content $content
        } | Should Throw "MCP request failed with code -32001: token secret-value"
        $protected = Protect-McpDiagnostic `
            -Message "Authorization Bearer abcdefghijklmnopqrstuvwxyz012345"
        $protected | Should Not Match "abcdefghijklmnopqrstuvwxyz012345"
        $protected | Should Match "\[redacted\]"
        Protect-McpDiagnostic -Message "apikey=secret-value" |
            Should Not Match "secret-value"
    }
}
