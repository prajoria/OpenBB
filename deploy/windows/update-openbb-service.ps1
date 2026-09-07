[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string] $SourceRoot,
    [string] $InstallRoot = "$env:ProgramFiles\OpenBB Portfolio",
    [string] $DataRoot = "$env:ProgramData\OpenBB Portfolio",
    [string] $PythonExecutable = "python.exe",
    [string] $ArtifactDirectory,
    [switch] $SkipPythonInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "OpenBBService.Deployment.psm1") -Force -DisableNameChecking

Assert-AbsolutePath $SourceRoot "SourceRoot"
Assert-AbsolutePath $InstallRoot "InstallRoot"
Assert-AbsolutePath $DataRoot "DataRoot"
if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Update must run from an elevated PowerShell session."
}
$current = Join-Path $InstallRoot "current"
if (-not (Test-Path -LiteralPath $current -PathType Container)) {
    throw "No installed release exists at $current."
}
$staging = Join-Path $InstallRoot ("staging-" + [Guid]::NewGuid().ToString("N"))
$backup = Join-Path $InstallRoot ("rollback-" + [DateTime]::UtcNow.ToString("yyyyMMddHHmmss"))
$configPath = Join-Path $DataRoot "service.json"
$configExisted = Test-Path -LiteralPath $configPath -PathType Leaf
$previousConfig = if ($configExisted) {
    [IO.File]::ReadAllBytes($configPath)
} else {
    $null
}

Publish-OpenBBRelease -SourceRoot $SourceRoot -Destination $staging `
    -PythonExecutable $PythonExecutable -ArtifactDirectory $ArtifactDirectory `
    -SkipPythonInstall:$SkipPythonInstall -WhatIf:$WhatIfPreference
if (-not $PSCmdlet.ShouldProcess("OpenBBPortfolio", "Transactionally activate staged release")) {
    return
}

Stop-Service -Name "OpenBBPortfolio" -ErrorAction Stop
try {
    Move-Item -LiteralPath $current -Destination $backup
    Move-Item -LiteralPath $staging -Destination $current
    $configPath = Write-ServiceConfiguration -ReleaseRoot $current -DataRoot $DataRoot
    Start-Service -Name "OpenBBPortfolio"
    Invoke-ServiceDoctor -HostExecutable (Join-Path $current "host\OpenBB.ServiceHost.exe") `
        -ConfigPath $configPath
    Remove-Item -LiteralPath $backup -Recurse -Force
} catch {
    Stop-Service -Name "OpenBBPortfolio" -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $current) {
        Remove-Item -LiteralPath $current -Recurse -Force
    }
    if (Test-Path -LiteralPath $backup) {
        Move-Item -LiteralPath $backup -Destination $current
        if ($configExisted) {
            [IO.File]::WriteAllBytes($configPath, $previousConfig)
        } elseif (Test-Path -LiteralPath $configPath) {
            Remove-Item -LiteralPath $configPath -Force
        }
        Start-Service -Name "OpenBBPortfolio"
    }
    throw
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
