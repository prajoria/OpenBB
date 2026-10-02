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

function Invoke-WorkspaceDiscoveryRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$SurfaceName,
        [Parameter(Mandatory)]
        [string]$Endpoint,
        [switch]$SkipCertificateCheck
    )

    try {
        if ($SkipCertificateCheck) {
            Invoke-RestMethod `
                -Uri $Endpoint `
                -ConnectionTimeoutSeconds 10 `
                -OperationTimeoutSeconds 10 `
                -SkipCertificateCheck
        } else {
            Invoke-RestMethod `
                -Uri $Endpoint `
                -ConnectionTimeoutSeconds 10 `
                -OperationTimeoutSeconds 10
        }
    } catch {
        $endpointUri = [uri]$Endpoint
        $safeEndpoint = "{0}{1}" -f @(
            $endpointUri.GetLeftPart([System.UriPartial]::Authority)
            $endpointUri.AbsolutePath
        )
        throw [System.InvalidOperationException]::new(
            "$SurfaceName request failed for $safeEndpoint"
        )
    }
}

function Invoke-WorkspaceDevSmokeCheck {
    [CmdletBinding()]
    param(
        [switch]$SkipCertificateCheck
    )

    $portfolioBase = "https://127.0.0.1:6902"
    $intelBase = "http://127.0.0.1:6120"

    $portfolioWidgets = Invoke-WorkspaceDiscoveryRequest `
        -SurfaceName "PortfolioWidgets" `
        -Endpoint "$portfolioBase/widgets.json" `
        -SkipCertificateCheck:$SkipCertificateCheck
    $portfolioApps = Invoke-WorkspaceDiscoveryRequest `
        -SurfaceName "PortfolioApps" `
        -Endpoint "$portfolioBase/apps.json" `
        -SkipCertificateCheck:$SkipCertificateCheck
    $portfolioAgents = Invoke-WorkspaceDiscoveryRequest `
        -SurfaceName "PortfolioAgents" `
        -Endpoint "$portfolioBase/agents.json" `
        -SkipCertificateCheck:$SkipCertificateCheck
    $intelWidgets = Invoke-WorkspaceDiscoveryRequest `
        -SurfaceName "IntelWidgets" `
        -Endpoint "$intelBase/widgets.json"
    $intelApps = Invoke-WorkspaceDiscoveryRequest `
        -SurfaceName "IntelApps" `
        -Endpoint "$intelBase/apps.json"

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
