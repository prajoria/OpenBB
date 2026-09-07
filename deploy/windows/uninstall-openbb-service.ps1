[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
    [string] $InstallRoot = "$env:ProgramFiles\OpenBB Portfolio",
    [string] $DataRoot = "$env:ProgramData\OpenBB Portfolio",
    [switch] $PurgeData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "OpenBBService.Deployment.psm1") -Force -DisableNameChecking

Assert-AbsolutePath $InstallRoot "InstallRoot"
Assert-AbsolutePath $DataRoot "DataRoot"
if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Uninstall must run from an elevated PowerShell session."
}

if (Get-Service -Name "OpenBBPortfolio" -ErrorAction SilentlyContinue) {
    if ($PSCmdlet.ShouldProcess("OpenBBPortfolio", "Stop and delete Windows service")) {
        Stop-Service -Name "OpenBBPortfolio" -ErrorAction SilentlyContinue
        & sc.exe delete "OpenBBPortfolio" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "sc.exe delete failed with exit code $LASTEXITCODE."
        }
    }
}
if (Test-Path -LiteralPath $InstallRoot) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force -WhatIf:$WhatIfPreference
}
if ($PurgeData -and (Test-Path -LiteralPath $DataRoot)) {
    Remove-Item -LiteralPath $DataRoot -Recurse -Force -WhatIf:$WhatIfPreference
}
