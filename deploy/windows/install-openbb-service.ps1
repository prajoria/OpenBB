[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string] $SourceRoot,
    [string] $InstallRoot = "$env:ProgramFiles\OpenBB Portfolio",
    [string] $DataRoot = "$env:ProgramData\OpenBB Portfolio",
    [string] $PythonExecutable = "python.exe",
    [string] $ArtifactDirectory,
    [switch] $SkipPythonInstall,
    [switch] $SkipStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "OpenBBService.Deployment.psm1") -Force -DisableNameChecking

Assert-AbsolutePath $SourceRoot "SourceRoot"
Assert-AbsolutePath $InstallRoot "InstallRoot"
Assert-AbsolutePath $DataRoot "DataRoot"
if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Installation must run from an elevated PowerShell session."
}

$releaseRoot = Join-Path $InstallRoot "current"
$hostExecutable = Join-Path $releaseRoot "host\OpenBB.ServiceHost.exe"
$releaseValid = Test-Path -LiteralPath $hostExecutable -PathType Leaf
if (-not $SkipPythonInstall) {
    $releaseValid = $releaseValid -and (
        Test-Path -LiteralPath (Join-Path $releaseRoot "python\Scripts\python.exe") -PathType Leaf)
}
if (-not $releaseValid) {
    $staging = Join-Path $InstallRoot ("installing-" + [Guid]::NewGuid().ToString("N"))
    try {
        Publish-OpenBBRelease -SourceRoot $SourceRoot -Destination $staging `
            -PythonExecutable $PythonExecutable -ArtifactDirectory $ArtifactDirectory `
            -SkipPythonInstall:$SkipPythonInstall -WhatIf:$WhatIfPreference
        if ($PSCmdlet.ShouldProcess($releaseRoot, "Activate staged release")) {
            if (Test-Path -LiteralPath $releaseRoot) {
                Remove-Item -LiteralPath $releaseRoot -Recurse -Force
            }
            Move-Item -LiteralPath $staging -Destination $releaseRoot
        }
    } finally {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
    }
}
if ($PSCmdlet.ShouldProcess($DataRoot, "Create persistent service data directories")) {
    New-Item -ItemType Directory -Path $DataRoot, (Join-Path $DataRoot "logs") -Force | Out-Null
}
$configPath = Write-ServiceConfiguration -ReleaseRoot $releaseRoot -DataRoot $DataRoot `
    -WhatIf:$WhatIfPreference

Set-OpenBBWindowsService -HostExecutable $hostExecutable -ConfigPath $configPath `
    -WhatIf:$WhatIfPreference
Set-ServiceAcl -Path $InstallRoot -Access Read -WhatIf:$WhatIfPreference
Set-ServiceAcl -Path $DataRoot -Access Modify -WhatIf:$WhatIfPreference
$secretPath = Join-Path $DataRoot "secrets.env"
Ensure-SecretFile -Path $secretPath -WhatIf:$WhatIfPreference
if (-not $SkipStart -and $PSCmdlet.ShouldProcess("OpenBBPortfolio", "Start and verify service")) {
    Start-Service -Name "OpenBBPortfolio"
    Invoke-ServiceDoctor -HostExecutable $hostExecutable -ConfigPath $configPath
}
