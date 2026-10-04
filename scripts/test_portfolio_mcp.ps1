#Requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet("platform-standard", "portfolio-read", "portfolio-ops")]
    [string]$Profile = "platform-standard",

    [string]$Uri = "http://127.0.0.1:8001/mcp",

    [string]$Authorization,

    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

function ConvertFrom-McpEvent {
    param([string]$Content)

    $line = $Content -split "`n" |
        Where-Object { $_.StartsWith("data: ") } |
        Select-Object -First 1
    try {
        $message = if ($line) {
            $line.Substring(6) | ConvertFrom-Json
        } else {
            $Content | ConvertFrom-Json
        }
    } catch {
        throw "MCP transport returned an invalid response."
    }
    if ($message.error) {
        $code = [string]$message.error.code
        $detail = [string]$message.error.message
        throw "MCP request failed with code $code`: $detail"
    }
    if ($message.result.isError) {
        $detail = [string](
            $message.result.content |
                Where-Object type -eq "text" |
                Select-Object -First 1 -ExpandProperty text
        )
        throw "MCP tool execution was denied or failed: $detail"
    }
    return $message
}

function Protect-McpDiagnostic {
    param([string]$Message)

    return $Message `
        -replace '(?i)(authorization|token|password|credential|api[_-]?key|secret)[^,\r\n]*', `
            '$1=[redacted]' `
        -replace '(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=_-]{16,}', `
            'authorization=[redacted]'
}

function Invoke-McpRequest {
    param(
        [string]$RequestUri,
        [hashtable]$Headers,
        [hashtable]$Message,
        [int]$RequestTimeout
    )

    $response = Invoke-WebRequest -Uri $RequestUri -Method Post `
        -Headers $Headers -ContentType "application/json" `
        -Body ($Message | ConvertTo-Json -Depth 12 -Compress) `
        -TimeoutSec $RequestTimeout
    return ConvertFrom-McpEvent -Content $response.Content
}

function Get-McpPages {
    param(
        [string]$RequestUri,
        [hashtable]$Headers,
        [string]$Method,
        [string]$ResultProperty,
        [int]$RequestTimeout
    )

    $items = [System.Collections.Generic.List[object]]::new()
    $cursor = $null
    $seenCursors = [System.Collections.Generic.HashSet[string]]::new()
    $pageCount = 0
    do {
        $params = @{}
        if ($cursor) {
            $params.cursor = $cursor
        }
        $message = Invoke-McpRequest -RequestUri $RequestUri `
            -Headers $Headers `
            -Message @{
                jsonrpc = "2.0"
                id = [guid]::NewGuid().ToString()
                method = $Method
                params = $params
            } `
            -RequestTimeout $RequestTimeout
        foreach ($item in @($message.result.$ResultProperty)) {
            $items.Add($item)
        }
        $cursor = $message.result.nextCursor
        $pageCount += 1
        if ($cursor -and -not $seenCursors.Add([string]$cursor)) {
            throw "MCP pagination returned a repeated cursor."
        }
        if ($pageCount -ge 100 -and $cursor) {
            throw "MCP pagination exceeded 100 pages."
        }
    } while ($cursor)
    return $items.ToArray()
}

function Get-StructuredResult {
    param($Message)

    if ($null -ne $Message.result.structuredContent.result) {
        return @($Message.result.structuredContent.result)
    }
    $text = $Message.result.content |
        Where-Object type -eq "text" |
        Select-Object -First 1 -ExpandProperty text
    if (-not $text) {
        throw "MCP tool returned no structured result."
    }
    return @($text | ConvertFrom-Json)
}

function Get-McpRequirements {
    param([string]$RuntimeProfile)

    $requirements = @{
        "platform-standard" = @{
            categories = @("equity")
            prompts = @("system_prompt", "equity_deep_dive")
            adapters = @()
            provider = "fmp"
            denied = @(
                "backtest_bundle_ingest",
                "techtrade_export",
                "techtrade_tune"
            )
        }
        "portfolio-read" = @{
            categories = @(
                "equity",
                "portfolio_intel",
                "techtrade",
                "backtest",
                "regime"
            )
            prompts = @(
                "portfolio_performance_review",
                "fmp_cached_portfolio_refresh"
            )
            adapters = @(
                "portfolio_intel_about",
                "techtrade_about",
                "backtest_about",
                "regime_detect"
            )
            provider = "fmp"
            denied = @(
                "backtest_bundle_ingest",
                "techtrade_export",
                "techtrade_tune"
            )
        }
        "portfolio-ops" = @{
            categories = @(
                "equity",
                "portfolio_intel",
                "techtrade",
                "backtest",
                "regime"
            )
            prompts = @(
                "portfolio_performance_review",
                "fmp_cached_portfolio_refresh"
            )
            adapters = @(
                "portfolio_intel_about",
                "techtrade_about",
                "backtest_about",
                "regime_detect",
                "backtest_bundle_ingest",
                "techtrade_export"
                "techtrade_tune"
            )
            provider = "fmp"
            denied = @()
        }
    }
    $required = $requirements[$RuntimeProfile]
    if ($null -eq $required) {
        throw "Unknown readiness profile."
    }
    return $required
}

function Assert-McpCapabilityContract {
    param(
        [string]$RuntimeProfile,
        [object[]]$Categories,
        [object[]]$Tools,
        [object[]]$Prompts
    )

    $required = Get-McpRequirements -RuntimeProfile $RuntimeProfile
    $categoryNames = @($Categories.name)
    foreach ($category in $required.categories) {
        if ($category -notin $categoryNames) {
            throw "Missing required category '$category'."
        }
        $categoryRecord = $Categories |
            Where-Object name -eq $category |
            Select-Object -First 1
        if ($null -ne $categoryRecord.total_tools -and
            [int]$categoryRecord.total_tools -lt 1) {
            throw "Required category '$category' has no tools."
        }
    }
    $promptNames = @($Prompts.name)
    foreach ($prompt in $required.prompts) {
        if ($prompt -notin $promptNames) {
            throw "Missing required prompt '$prompt'."
        }
    }
    $toolNames = @($Tools.name)
    foreach ($adapter in $required.adapters) {
        if ($adapter -notin $toolNames) {
            throw "Missing required adapter '$adapter'."
        }
    }
    foreach ($deniedTool in $required.denied) {
        if ($deniedTool -in $toolNames) {
            throw "Denied capability '$deniedTool' is exposed."
        }
    }
    $providerSchemas = $Tools |
        ForEach-Object { $_.inputSchema.properties.provider } |
        Where-Object { $null -ne $_ }
    $providerChoices = foreach ($schema in $providerSchemas) {
        @($schema.enum)
        foreach ($branch in @($schema.anyOf) + @($schema.oneOf)) {
            @($branch.enum)
        }
    }
    $providerAvailable = $required.provider -in @($providerChoices)
    if (-not $providerAvailable) {
        throw "Missing required provider choice '$($required.provider)'."
    }
}

function Test-PortfolioMcp {
    param(
        [string]$RuntimeProfile,
        [string]$RequestUri,
        [string]$AuthHeader,
        [int]$RequestTimeout
    )

    $headers = @{ Accept = "application/json, text/event-stream" }
    if ($AuthHeader) {
        $headers.Authorization = $AuthHeader
    }
    $sessionId = $null
    $readinessSucceeded = $false
    try {
        if ($RuntimeProfile -eq "portfolio-ops") {
            $unauthenticated = Invoke-WebRequest -Uri $RequestUri -Method Post `
                -Headers @{ Accept = "application/json, text/event-stream" } `
                -ContentType "application/json" `
                -Body '{"jsonrpc":"2.0","id":"auth-check","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"auth-check","version":"1"}}}' `
                -TimeoutSec $RequestTimeout -SkipHttpErrorCheck
            if ([int]$unauthenticated.StatusCode -notin @(401, 403)) {
                throw "MCP operator profile does not enforce authentication."
            }
        }
        $initialize = Invoke-WebRequest -Uri $RequestUri -Method Post `
            -Headers $headers -ContentType "application/json" `
            -Body (@{
                jsonrpc = "2.0"
                id = 1
                method = "initialize"
                params = @{
                    protocolVersion = "2025-06-18"
                    capabilities = @{}
                    clientInfo = @{
                        name = "openbb-profile-readiness"
                        version = "1.0"
                    }
                }
            } | ConvertTo-Json -Depth 8 -Compress) `
            -TimeoutSec $RequestTimeout
        $sessionId = [string]$initialize.Headers["Mcp-Session-Id"]
        if (-not $sessionId) {
            throw "MCP transport returned no session identifier."
        }
        $headers["Mcp-Session-Id"] = $sessionId
        Invoke-WebRequest -Uri $RequestUri -Method Post -Headers $headers `
            -ContentType "application/json" `
            -Body '{"jsonrpc":"2.0","method":"notifications/initialized"}' `
            -TimeoutSec $RequestTimeout | Out-Null

        $categoryMessage = Invoke-McpRequest -RequestUri $RequestUri `
            -Headers $headers `
            -Message @{
                jsonrpc = "2.0"
                id = 2
                method = "tools/call"
                params = @{
                    name = "available_categories"
                    arguments = @{}
                }
            } `
            -RequestTimeout $RequestTimeout
        $categories = Get-StructuredResult -Message $categoryMessage
        $required = Get-McpRequirements -RuntimeProfile $RuntimeProfile
        foreach ($category in $required.categories) {
            if ($category -in @($categories.name)) {
                Invoke-McpRequest -RequestUri $RequestUri -Headers $headers `
                    -Message @{
                        jsonrpc = "2.0"
                        id = [guid]::NewGuid().ToString()
                        method = "tools/call"
                        params = @{
                            name = "activate_category"
                            arguments = @{ category = $category }
                        }
                    } `
                    -RequestTimeout $RequestTimeout | Out-Null
            }
        }
        $tools = Get-McpPages -RequestUri $RequestUri -Headers $headers `
            -Method "tools/list" -ResultProperty "tools" `
            -RequestTimeout $RequestTimeout
        $prompts = Get-McpPages -RequestUri $RequestUri -Headers $headers `
            -Method "prompts/list" -ResultProperty "prompts" `
            -RequestTimeout $RequestTimeout
        Assert-McpCapabilityContract -RuntimeProfile $RuntimeProfile `
            -Categories $categories -Tools $tools -Prompts $prompts
        $readinessSucceeded = $true
        return [pscustomobject]@{
            profile = $RuntimeProfile
            categories = $categories.Count
            tools = $tools.Count
            prompts = $prompts.Count
            ready = $true
        }
    } catch {
        $message = Protect-McpDiagnostic -Message $_.Exception.Message
        if ($_.Exception.Response.StatusCode -in @(401, 403)) {
            throw "MCP readiness failed: authentication rejected."
        }
        if ($_.Exception -is [System.Net.Http.HttpRequestException] -and
            $null -eq $_.Exception.Response) {
            throw "MCP readiness failed: transport unavailable."
        }
        throw "MCP readiness failed: $message"
    } finally {
        if ($sessionId) {
            try {
                $cleanup = Invoke-WebRequest -Uri $RequestUri -Method Delete `
                    -Headers $headers -TimeoutSec $RequestTimeout `
                    -SkipHttpErrorCheck
                if ([int]$cleanup.StatusCode -ne 405 -and
                    ([int]$cleanup.StatusCode -lt 200 -or
                    [int]$cleanup.StatusCode -ge 300)) {
                    throw "Session cleanup returned HTTP $($cleanup.StatusCode)."
                }
            } catch {
                if ($readinessSucceeded) {
                    throw "MCP readiness failed: session cleanup failed."
                }
                Write-Warning "MCP readiness session cleanup also failed."
            }
        }
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Test-PortfolioMcp -RuntimeProfile $Profile -RequestUri $Uri `
        -AuthHeader $Authorization -RequestTimeout $TimeoutSeconds
}
