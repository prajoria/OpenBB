[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string] $SourceRoot,
    [string] $InstallRoot = "$env:ProgramFiles\OpenBB Portfolio",
    [string] $DataRoot = "$env:ProgramData\OpenBB Portfolio",
    [string] $PythonExecutable = "python.exe",
    [string] $ArtifactDirectory,
    [switch] $SkipPythonInstall,
    [switch] $SkipServiceRegistration,
    [switch] $SkipStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "OpenBBService.Deployment.psm1") -Force -DisableNameChecking

Assert-AbsolutePath $SourceRoot "SourceRoot"
Assert-AbsolutePath $InstallRoot "InstallRoot"
Assert-AbsolutePath $DataRoot "DataRoot"
if (-not $WhatIfPreference -and -not $SkipServiceRegistration -and -not (Test-IsAdministrator)) {
    throw "Installation must run from an elevated PowerShell session."
}

$releaseRoot = Join-Path $InstallRoot "current"
if (-not (Test-Path -LiteralPath $releaseRoot -PathType Container)) {
    Publish-OpenBBRelease -SourceRoot $SourceRoot -Destination $releaseRoot `
        -PythonExecutable $PythonExecutable -ArtifactDirectory $ArtifactDirectory `
        -SkipPythonInstall:$SkipPythonInstall -WhatIf:$WhatIfPreference
}
if ($PSCmdlet.ShouldProcess($DataRoot, "Create persistent service data directories")) {
    New-Item -ItemType Directory -Path $DataRoot, (Join-Path $DataRoot "logs") -Force | Out-Null
}
$secretPath = Join-Path $DataRoot "secrets.env"
Ensure-SecretFile -Path $secretPath -WhatIf:$WhatIfPreference
$configPath = Write-ServiceConfiguration -ReleaseRoot $releaseRoot -DataRoot $DataRoot `
    -WhatIf:$WhatIfPreference

if (-not $SkipServiceRegistration) {
    $hostExecutable = Join-Path $releaseRoot "host\OpenBB.ServiceHost.exe"
    Set-OpenBBWindowsService -HostExecutable $hostExecutable -ConfigPath $configPath `
        -WhatIf:$WhatIfPreference
    Set-ServiceAcl -Path $InstallRoot -Access Read -WhatIf:$WhatIfPreference
    Set-ServiceAcl -Path $DataRoot -Access Modify -WhatIf:$WhatIfPreference
    if (-not $SkipStart -and $PSCmdlet.ShouldProcess("OpenBBPortfolio", "Start and verify service")) {
        Start-Service -Name "OpenBBPortfolio"
        Invoke-ServiceDoctor -HostExecutable $hostExecutable -ConfigPath $configPath
    }
}
