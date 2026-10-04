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
    $contractCategories = @(
        [pscustomobject]@{ name = "equity" },
        [pscustomobject]@{ name = "portfolio_intel"; total_tools = 5 },
        [pscustomobject]@{ name = "techtrade"; total_tools = 8 },
        [pscustomobject]@{ name = "backtest"; total_tools = 9 },
        [pscustomobject]@{ name = "regime"; total_tools = 1 }
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
        (New-Tool -Name "regime_detect")
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
            (New-Tool -Name "regime_detect")
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
