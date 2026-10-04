$ScriptPath = Join-Path $PSScriptRoot "..\start-dual-mcp.ps1"
$ScriptText = Get-Content -LiteralPath $ScriptPath -Raw
$ManifestPath = Join-Path $PSScriptRoot "..\..\openbb_platform\extensions\mcp_server\openbb_mcp_server\assets\runtime_profiles.json"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$LifecycleModule = Join-Path $PSScriptRoot "..\mcp_stack_lifecycle.psm1"

Import-Module $LifecycleModule -Force

Describe "start-dual-mcp reproducibility" {
    It "requires the PowerShell version used by streamable HTTP readiness" {
        $ScriptText | Should Match '#Requires -Version 7\.0'
    }

    It "pins Workspace external dependencies exactly" {
        ([regex]::Matches($ScriptText, '"fastmcp==3\.4\.0"')).Count | Should Be 1
        ([regex]::Matches($ScriptText, '"fastmcp==3\.4\.6"')).Count | Should Be 1
        $Manifest.profiles.'platform-standard'.required_versions.fastmcp |
            Should Be "3.4.0"
        $ScriptText | Should Match '"openbb-ai==2\.1\.0"'
        $ScriptText | Should Match '"pydantic==2\.12\.5"'
        $ScriptText | Should Match '"starlette==1\.6\.0"'
        $ScriptText | Should Match '"uvicorn==0\.52\.3"'
        $ScriptText | Should Not Match '"(fastmcp|openbb-ai|pydantic|starlette|uvicorn)>='
    }

    It "verifies the isolated Platform environment before startup" {
        $ScriptText | Should Match 'verify_mcp_runtime\.py'
        $ScriptText | Should Match '--repository-root'
        $ScriptText | Should Match 'runtime-resolution\.json'
        $ScriptText | Should Match '\$RuntimeResolutionArtifact\s*\)'
        $ScriptText | Should Match '\$env:OPENBB_MCP_RUNTIME_PROFILE\s*=\s*\$Profile'
        $ScriptText | Should Match '\$env:OPENBB_MCP_CAPABILITY_PROFILE\s*=\s*\[string\]\$RuntimeProfile\.policy_profile'
        $ScriptText | Should Match '\$env:OPENBB_MCP_INSTALLATION_KIND\s*=\s*\$Installation'
        $ScriptText | Should Match 'Invoke-WebRequest[\s\S]*-TimeoutSec \$StartupTimeoutSeconds'
        ([regex]::Matches($ScriptText, 'Set-Content -LiteralPath \$StatePath')).Count |
            Should BeGreaterThan 1
        $ScriptText | Should Match '\[System\.Threading\.Mutex\]::new'
        $ScriptText | Should Match '\$StartMutex\.WaitOne\(0\)'
    }

    It "uses only checkout-local editable Platform packages" {
        $ScriptText | Should Match 'openbb_platform\\core'
        $ScriptText | Should Match 'openbb_platform\\extensions\\platform_api'
        $ScriptText | Should Match 'openbb_platform\\extensions\\mcp_server'
    }

    It "selects a validated runtime profile with the compatibility default" {
        $ScriptText | Should Match '\[ValidateSet\("platform-standard", "portfolio-read", "portfolio-ops"\)\]'
        $ScriptText | Should Match '\[string\]\$Profile\s*=\s*"platform-standard"'
        $ScriptText | Should Match '\[string\]\$PortfolioRoot'
        $ScriptText | Should Match '\$RuntimeProfile\.app\.target'
        $ScriptText | Should Match '\$RuntimeProfile\.app\.kind -eq "custom"'
    }
}

Describe "dual MCP lifecycle ownership" {
    It "quotes a checkout path containing spaces without changing it" {
        $result = @(ConvertTo-NativeArguments -Arguments @("C:\OpenBB Portfolio\app.py"))
        $result | Should Be '"C:\OpenBB Portfolio\app.py"'
        $trailing = @(ConvertTo-NativeArguments -Arguments @("C:\OpenBB Portfolio\"))
        $trailing | Should Be '"C:\OpenBB Portfolio\\"'
    }

    It "matches exact PID start time and executable identity" {
        $process = Get-Process -Id $PID
        $identity = @{
            pid = $process.Id
            started_at = $process.StartTime.ToUniversalTime().ToString("o")
            executable = $process.Path
        }
        Test-ProcessIdentity -Identity $identity | Should Be $true
        $identity.started_at = $process.StartTime.AddSeconds(-1).ToUniversalTime().ToString("o")
        Test-ProcessIdentity -Identity $identity | Should Be $false
    }

    It "rejects a listener outside the launcher process tree" {
        Mock Get-NetTCPConnection {
            [pscustomobject]@{ OwningProcess = 99999 }
        } -ModuleName mcp_stack_lifecycle
        Mock Get-DescendantProcessIds { @() } -ModuleName mcp_stack_lifecycle

        {
            Wait-ForOwnedListener -Name "Platform" `
                -LauncherIdentity @{ pid = 123; started_at = "2026-01-01T00:00:00Z" } `
                -Port 18001 -ErrorLog "missing.log" -TimeoutSeconds 5
        } | Should Throw "Platform port 18001 was claimed by an unrelated process."
    }

    It "cleans every process started before partial startup failure" {
        Mock Stop-ProcessTree {} -ModuleName mcp_stack_lifecycle
        Stop-PartialStack `
            -PlatformIdentity @{ pid = 11 } `
            -PlatformLauncherIdentity @{ pid = 10 } `
            -WorkspaceIdentity $null `
            -WorkspaceLauncherIdentity @{ pid = 20 }

        Assert-MockCalled Stop-ProcessTree 1 {
            $Identity.pid -eq 11
        } -ModuleName mcp_stack_lifecycle
        Assert-MockCalled Stop-ProcessTree 1 {
            $Identity.pid -eq 10
        } -ModuleName mcp_stack_lifecycle
        Assert-MockCalled Stop-ProcessTree 1 {
            $Identity.pid -eq 20
        } -ModuleName mcp_stack_lifecycle
    }

    It "removes stale state without stopping unrelated processes" {
        $statePath = Join-Path $TestDrive "processes.json"
        Set-Content -LiteralPath $statePath -Value "{}"
        Mock Test-ProcessIdentity { $false } -ModuleName mcp_stack_lifecycle
        Mock Stop-Process {} -ModuleName mcp_stack_lifecycle

        Clear-StaleProcessState -State @{
            platform = @{ pid = 10 }
            workspace = @{ pid = 20 }
        } -StatePath $statePath

        Test-Path -LiteralPath $statePath | Should Be $false
        Assert-MockCalled Stop-Process 0 -ModuleName mcp_stack_lifecycle
    }

    It "treats malformed process identity as stale" {
        Test-ProcessIdentity -Identity @{
            pid = $PID
            started_at = "not-a-date"
            executable = "python.exe"
        } | Should Be $false
    }

    It "leaves live state intact and refuses restart" {
        $statePath = Join-Path $TestDrive "live-processes.json"
        Set-Content -LiteralPath $statePath -Value "{}"
        Mock Test-ProcessIdentity { $true } -ModuleName mcp_stack_lifecycle

        {
            Clear-StaleProcessState -State @{
                platform = @{ pid = 10 }
                workspace = @{ pid = 20 }
            } -StatePath $statePath
        } | Should Throw "A recorded MCP stack is still running. Use -Action Status or -Action Stop first."
        Test-Path -LiteralPath $statePath | Should Be $true
    }

    It "refuses restart while a launcher-only partial state is live" {
        $statePath = Join-Path $TestDrive "partial-processes.json"
        Set-Content -LiteralPath $statePath -Value "{}"
        Mock Test-ProcessIdentity {
            $Identity.pid -eq 30
        } -ModuleName mcp_stack_lifecycle

        {
            Clear-StaleProcessState -State @{
                platform_launcher = @{ pid = 30 }
            } -StatePath $statePath
        } | Should Throw "A recorded MCP stack is still running. Use -Action Status or -Action Stop first."
        Test-Path -LiteralPath $statePath | Should Be $true
    }

    It "fails when an explicit Portfolio interpreter is missing" {
        $missing = Join-Path $TestDrive "missing python.exe"
        {
            Resolve-PortfolioEnvironment -OpenBBRoot $TestDrive `
                -PortfolioPython $missing -PortfolioRoot $TestDrive
        } | Should Throw "PortfolioPython '$missing' does not exist."
    }

    It "requires strong authentication for operator profiles" {
        {
            Get-ServerAuthHeader -SerializedCredentials "" -Required
        } | Should Throw "portfolio-ops requires OPENBB_MCP_SERVER_AUTH with a high-entropy password."
        {
            Get-ServerAuthHeader -SerializedCredentials '["operator","short"]' -Required
        } | Should Throw "OPENBB_MCP_SERVER_AUTH must contain a username and password of at least 32 characters."
        $header = Get-ServerAuthHeader `
            -SerializedCredentials '["operator","01234567890123456789012345678901"]' `
            -Required
        $header | Should Match '^Bearer '
        $compatible = Get-ServerAuthHeader `
            -SerializedCredentials '["reader","short"]'
        $compatible | Should Match '^Bearer '
    }

    It "treats corrupt state as stale and recoverable" {
        $statePath = Join-Path $TestDrive "corrupt.json"
        Set-Content -LiteralPath $statePath -Value "{not-json"
        Read-ProcessState -StatePath $statePath | Should Be $null
        Test-Path -LiteralPath $statePath | Should Be $false
    }
}
