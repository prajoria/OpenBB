#Requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet("platform-standard", "portfolio-read", "portfolio-ops")]
    [string]$Profile = "platform-standard",

    [string]$Uri = "http://127.0.0.1:8001/mcp",

    [string]$Authorization,

    [ValidateSet(
        "protocol",
        "package",
        "workspace-no-browser",
        "workspace-read",
        "workspace-mutation"
    )]
    [string]$Mode = "protocol",

    [string]$PythonExecutable = $env:OPENBB_PORTFOLIO_PYTHON,

    [string]$RepositoryRoot = (Split-Path $PSScriptRoot -Parent),

    [string[]]$OptionalAnalytics = @(),

    [switch]$AllowWorkspaceMutation,

    [string]$DisposableDashboardId,

    [string]$WorkspaceRoot = (Split-Path $PSScriptRoot -Parent),

    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

function Test-WorkspaceParity {
    param(
        [ValidateSet("no-browser", "read", "mutation")]
        [string]$WorkspaceMode,
        [string]$Root,
        [switch]$MutationApproved,
        [string]$DashboardId
    )

    if ($WorkspaceMode -eq "mutation" -and -not $MutationApproved) {
        throw "Workspace mutation requires -AllowWorkspaceMutation."
    }
    if ($WorkspaceMode -eq "mutation" -and
        [string]::IsNullOrWhiteSpace($DashboardId)) {
        throw "Workspace mutation requires -DisposableDashboardId."
    }
    $helper = Join-Path $Root "scripts\invoke_workspace_mcp_command.ps1"
    $harness = Join-Path $Root "scripts\test_workspace_mcp.py"
    if (-not (Test-Path $helper -PathType Leaf) -or
        -not (Test-Path $harness -PathType Leaf)) {
        throw "Workspace parity harness is unavailable."
    }
    $python = if ($PythonExecutable) {
        $PythonExecutable
    } else {
        (Get-Command python -CommandType Application -ErrorAction Stop).Source
    }
    $arguments = @($harness, "--mode", $WorkspaceMode)
    if ($WorkspaceMode -eq "mutation") {
        $arguments += @(
            "--allow-mutation",
            "--dashboard-id",
            $DashboardId
        )
    }
    & $helper `
        -WorkspaceRoot $Root `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $Root `
        -BackendUrl "http://127.0.0.1:8000"
    if ($LASTEXITCODE -ne 0) {
        throw "Workspace parity child command failed."
    }
}

function Test-PackageReplay {
    param(
        [string]$RuntimeProfile,
        [string]$Python,
        [string]$Root
    )

    if (-not $Python) {
        throw "Package replay requires -PythonExecutable or OPENBB_PORTFOLIO_PYTHON."
    }

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Package replay Python executable is unavailable."
    }
    $manifestPath = Join-Path $Root `
        "openbb_platform\extensions\mcp_server\openbb_mcp_server\assets\runtime_profiles.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Package replay runtime manifest is unavailable."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $profile = $manifest.profiles.$RuntimeProfile
    if ($null -eq $profile) {
        throw "Package replay profile is not declared."
    }
    $versionOutput = & $Python -c `
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or -not $versionOutput) {
        throw "Package replay could not determine the interpreter version."
    }
    $interpreterVersion = [version]([string]$versionOutput).Trim()
    $constraint = [string]$profile.python
    if (
        $interpreterVersion -lt [version]"3.10" -or
        $interpreterVersion -ge [version]"3.14"
    ) {
        throw "Unsupported Python $($interpreterVersion.Major).$($interpreterVersion.Minor); profile requires $constraint."
    }
    $previousProfile = $env:OPENBB_MCP_REPLAY_PROFILE
    $previousRoot = $env:OPENBB_MCP_REPLAY_ROOT
    $previousOptional = $env:OPENBB_MCP_REPLAY_OPTIONAL
    try {
        $env:OPENBB_MCP_REPLAY_PROFILE = $RuntimeProfile
        $env:OPENBB_MCP_REPLAY_ROOT = $Root
        $env:OPENBB_MCP_REPLAY_OPTIONAL = $OptionalAnalytics -join ","
        $assetProbe = @'
import json
import os
import re
import sys
import sysconfig
from importlib import metadata, resources
from pathlib import Path

profile_name = os.environ["OPENBB_MCP_REPLAY_PROFILE"]
root = Path(os.environ["OPENBB_MCP_REPLAY_ROOT"]).resolve()
optional = {
    item for item in os.environ.get("OPENBB_MCP_REPLAY_OPTIONAL", "").split(",")
    if item
}
source_catalog = json.loads(
    (root / "openbb_platform/extensions/mcp_server/openbb_mcp_server/"
     "assets/runtime_profiles.json").read_text(encoding="utf-8")
)
profile = source_catalog["profiles"][profile_name]

constraint = profile["python"]
major, minor = sys.version_info[:2]
for operator, expected_major, expected_minor in re.findall(
    r"(>=|>|<=|<|==)\s*(\d+)\.(\d+)", constraint
):
    current = (major, minor)
    expected = (int(expected_major), int(expected_minor))
    valid = {
        ">=": current >= expected,
        ">": current > expected,
        "<=": current <= expected,
        "<": current < expected,
        "==": current == expected,
    }[operator]
    if not valid:
        raise SystemExit(
            f"Unsupported Python {major}.{minor}; profile requires {constraint}."
        )

installed_catalog = json.loads(
    resources.files("openbb_mcp_server")
    .joinpath("assets/runtime_profiles.json")
    .read_text(encoding="utf-8")
)
if installed_catalog["profiles"][profile_name] != profile:
    raise SystemExit("Installed runtime profile catalog differs from source manifest.")

assets = resources.files("openbb_mcp_server").joinpath("assets")
required = (
    "capability_policy.json",
    "capability_policy_operations.csv",
    "runtime_profiles.json",
    "server_prompts.json",
    "system_prompt.txt",
)
missing = [name for name in required if not assets.joinpath(name).is_file()]
if missing:
    raise SystemExit(f"Missing packaged MCP assets: {missing}")

missing_distributions = []
foreign_distributions = {}
site_roots = {
    Path(path).resolve()
    for key in ("purelib", "platlib")
    if (path := sysconfig.get_path(key))
}
def in_site_packages(path):
    resolved = Path(path).resolve()
    return any(root == resolved or root in resolved.parents for root in site_roots)

for name in (*profile["required_distributions"], *optional):
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        missing_distributions.append(name)
        continue
    metadata_root = Path(distribution.locate_file("")).resolve()
    direct_url = distribution.read_text("direct_url.json")
    editable = False
    if direct_url:
        editable = bool(json.loads(direct_url).get("dir_info", {}).get("editable"))
    if not in_site_packages(metadata_root) or editable:
        foreign_distributions[name] = {
            "editable": editable,
            "metadata_root": str(metadata_root),
        }
if missing_distributions:
    raise SystemExit(f"Missing declared distributions: {missing_distributions}")
if foreign_distributions:
    raise SystemExit(
        "Distributions did not resolve from non-editable site-packages: "
        + json.dumps(foreign_distributions, sort_keys=True)
    )

missing_modules = []
foreign_origins = {}
for name in profile["required_modules"]:
    spec = __import__("importlib.util").util.find_spec(name)
    if spec is None or spec.origin is None:
        missing_modules.append(name)
        continue
    origin = Path(spec.origin).resolve()
    if not in_site_packages(origin):
        foreign_origins[name] = str(origin)
for distribution in optional:
    module = distribution.removeprefix("openbb-").replace("-", "_")
    spec = __import__("importlib.util").util.find_spec(f"openbb_{module}")
    if spec is None or spec.origin is None:
        missing_modules.append(f"openbb_{module}")
    elif not in_site_packages(Path(spec.origin).resolve()):
        foreign_origins[f"openbb_{module}"] = str(Path(spec.origin).resolve())
if missing_modules:
    raise SystemExit(f"Missing declared modules: {missing_modules}")
if foreign_origins:
    raise SystemExit(
        "Package replay resolved checkout source instead of installed wheels: "
        + json.dumps(foreign_origins, sort_keys=True)
    )

entry_points = {
    (ep.group, ep.name): ep.value
    for group in (
        "console_scripts",
        "openbb_core_extension",
        "openbb_provider_extension",
        "openbb_job_extension",
    )
    for ep in metadata.entry_points(group=group)
}
required_entry_points = {
    ("console_scripts", "openbb-mcp"): "openbb_mcp_server.app.app:main",
    ("openbb_provider_extension", "fmp_cached"): "openbb_fmp_cached:fmp_cached_provider",
    ("openbb_core_extension", "fmp_cached"): "openbb_fmp_cached.fmp_cached_router:router",
    ("openbb_core_extension", "portfolio_intel"): "openbb_portfolio_intel.portfolio_intel_router:router",
    ("openbb_core_extension", "techtrade"): "openbb_techtrade.techtrade_router:router",
    ("openbb_core_extension", "backtest"): "openbb_backtest.backtest_router:router",
    ("openbb_core_extension", "regime"): "openbb_regime.regime_router:router",
}
missing_entry_points = sorted(set(required_entry_points) - set(entry_points))
if missing_entry_points:
    raise SystemExit(f"Missing declared entry points: {missing_entry_points}")
wrong_targets = {
    f"{group}:{name}": {
        "expected": target,
        "installed": entry_points[(group, name)],
    }
    for (group, name), target in required_entry_points.items()
    if entry_points[(group, name)] != target
}
if wrong_targets:
    raise SystemExit(
        "Installed entry-point targets differ from declarations: "
        + json.dumps(wrong_targets, sort_keys=True)
    )
for key, target in required_entry_points.items():
    metadata.EntryPoint(
        name=key[1],
        value=target,
        group=key[0],
    ).load()
print(
    json.dumps(
        {
            "entry_points": sorted(f"{group}:{name}" for group, name in required_entry_points),
            "optional_analytics": sorted(optional),
            "profile": profile_name,
            "python": f"{major}.{minor}",
            "ready": True,
        },
        sort_keys=True,
    )
)
'@
        $probeResult = $assetProbe | & $Python - 2>&1
        if ($LASTEXITCODE -ne 0) {
            $diagnostic = Protect-McpDiagnostic -Message (
                $probeResult | Out-String
            )
            throw "Package replay package, provenance, or catalog verification failed: $diagnostic"
        }
        return $probeResult | ConvertFrom-Json
    } finally {
        $env:OPENBB_MCP_REPLAY_PROFILE = $previousProfile
        $env:OPENBB_MCP_REPLAY_ROOT = $previousRoot
        $env:OPENBB_MCP_REPLAY_OPTIONAL = $previousOptional
    }
}

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

    $cacheJobTools = @(
        "cache_jobs_definitions",
        "cache_jobs_health",
        "cache_jobs_run",
        "cache_jobs_trigger_position_history",
        "cache_jobs_trigger_etf_holdings"
    )
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
                "regime",
                "cache"
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
                "cache_health",
                "cache_coverage"
            )
            provider = "fmp"
            denied = @(
                "backtest_bundle_ingest",
                "techtrade_export",
                "techtrade_tune"
            ) + $cacheJobTools
        }
        "portfolio-ops" = @{
            categories = @(
                "equity",
                "portfolio_intel",
                "techtrade",
                "backtest",
                "regime",
                "cache"
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
                "cache_health",
                "cache_coverage",
                "backtest_bundle_ingest",
                "techtrade_export",
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
    $maintenanceEnabled = (
        $env:OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS -eq "true"
    )
    if ($RuntimeProfile -eq "portfolio-ops" -and $maintenanceEnabled) {
        $required.adapters += $cacheJobTools
    } else {
        $required.denied += $cacheJobTools
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
    if ($Mode -eq "workspace-no-browser") {
        Test-WorkspaceParity -WorkspaceMode no-browser -Root $WorkspaceRoot
    } elseif ($Mode -eq "workspace-read") {
        Test-WorkspaceParity -WorkspaceMode read -Root $WorkspaceRoot
    } elseif ($Mode -eq "workspace-mutation") {
        Test-WorkspaceParity -WorkspaceMode mutation -Root $WorkspaceRoot `
            -MutationApproved:$AllowWorkspaceMutation `
            -DashboardId $DisposableDashboardId
    } elseif ($Mode -eq "package") {
        Test-PackageReplay -RuntimeProfile $Profile `
            -Python $PythonExecutable -Root $RepositoryRoot `
            -OptionalAnalytics $OptionalAnalytics
    } else {
        Test-PortfolioMcp -RuntimeProfile $Profile -RequestUri $Uri `
            -AuthHeader $Authorization -RequestTimeout $TimeoutSeconds
    }
}
