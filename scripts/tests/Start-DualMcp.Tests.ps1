$ScriptPath = Join-Path $PSScriptRoot "..\start-dual-mcp.ps1"
$ScriptText = Get-Content -LiteralPath $ScriptPath -Raw
$ManifestPath = Join-Path $PSScriptRoot "..\..\openbb_platform\extensions\mcp_server\openbb_mcp_server\assets\runtime_profiles.json"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json

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
        $ScriptText | Should Match '\$env:OPENBB_MCP_RUNTIME_PROFILE\s*=\s*"platform-standard"'
        $ScriptText | Should Match '\$env:OPENBB_MCP_CAPABILITY_PROFILE\s*=\s*"platform-standard"'
        $ScriptText | Should Match '\$env:OPENBB_MCP_INSTALLATION_KIND\s*=\s*"isolated_uv"'
    }

    It "uses only checkout-local editable Platform packages" {
        $ScriptText | Should Match 'openbb_platform\\core'
        $ScriptText | Should Match 'openbb_platform\\extensions\\platform_api'
        $ScriptText | Should Match 'openbb_platform\\extensions\\mcp_server'
    }
}
