#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Validate local Workspace development discovery surfaces without logging data.

.DESCRIPTION
    Checks Portfolio widgets, apps, and agents plus Portfolio Intelligence
    widgets and apps. Output is limited to discovery entry counts.

.PARAMETER SkipCertificateCheck
    Explicitly accept the Portfolio backend's self-signed loopback certificate.
#>

[CmdletBinding()]
param(
    [switch]$SkipCertificateCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-WorkspaceDevSmokeCheck {
    [CmdletBinding()]
    param(
        [switch]$SkipCertificateCheck
    )

    $portfolioBase = "https://127.0.0.1:6902"
    $intelBase = "http://127.0.0.1:6120"
    $portfolioRequestArgs = @{}
    if ($SkipCertificateCheck) {
        $portfolioRequestArgs["SkipCertificateCheck"] = $true
    }

    $portfolioWidgets = Invoke-RestMethod `
        -Uri "$portfolioBase/widgets.json" @portfolioRequestArgs
    $portfolioApps = Invoke-RestMethod `
        -Uri "$portfolioBase/apps.json" @portfolioRequestArgs
    $portfolioAgents = Invoke-RestMethod `
        -Uri "$portfolioBase/agents.json" @portfolioRequestArgs
    $intelWidgets = Invoke-RestMethod -Uri "$intelBase/widgets.json"
    $intelApps = Invoke-RestMethod -Uri "$intelBase/apps.json"

    $checks = [ordered]@{
        PortfolioWidgets = @($portfolioWidgets.PSObject.Properties).Count
        PortfolioApps = @($portfolioApps).Count
        PortfolioAgents = @($portfolioAgents.PSObject.Properties).Count
        IntelWidgets = @($intelWidgets.PSObject.Properties).Count
        IntelApps = @($intelApps).Count
    }

    foreach ($entry in $checks.GetEnumerator()) {
        if ($entry.Value -lt 1) {
            throw "$($entry.Key) discovery returned no entries"
        }
        Write-Host "[PASS] $($entry.Key): $($entry.Value)"
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-WorkspaceDevSmokeCheck -SkipCertificateCheck:$SkipCertificateCheck
}
