Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ServiceName = "OpenBBPortfolio"
$script:ServiceAccount = "NT SERVICE\OpenBBPortfolio"

function Assert-AbsolutePath {
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][string] $Name)
    if (-not [System.IO.Path]::IsPathFullyQualified($Path)) {
        throw "$Name must be an absolute path: $Path"
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)][string] $FilePath,
        [Parameter(Mandatory)][string[]] $ArgumentList
    )
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-WidgetToken {
    $bytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Ensure-SecretFile {
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][string] $Path)

    Assert-AbsolutePath -Path $Path -Name "Secret path"
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return
    }
    if ($PSCmdlet.ShouldProcess($Path, "Generate widget backend token")) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
        $token = New-WidgetToken
        [IO.File]::WriteAllText(
            $Path,
            "PI_WIDGET_BACKEND_TOKEN=$token$([Environment]::NewLine)",
            [Text.UTF8Encoding]::new($false))
    }
}

function Set-ServiceAcl {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][ValidateSet("Read", "Modify")][string] $Access
    )
    if ($PSCmdlet.ShouldProcess($Path, "Grant $Access to $script:ServiceAccount")) {
        $grant = if ($Access -eq "Read") {
            "$script:ServiceAccount:(OI)(CI)(RX)"
        } else {
            "$script:ServiceAccount:(OI)(CI)(M)"
        }
        Invoke-CheckedCommand -FilePath "icacls.exe" -ArgumentList @(
            $Path, "/inheritance:r", "/grant:r",
            "SYSTEM:(OI)(CI)(F)", "BUILTIN\Administrators:(OI)(CI)(F)", $grant, "/T", "/C")
    }
}

function Publish-OpenBBRelease {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string] $SourceRoot,
        [Parameter(Mandatory)][string] $Destination,
        [string] $PythonExecutable = "python.exe",
        [string] $ArtifactDirectory,
        [switch] $SkipPythonInstall
    )

    $SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
    Assert-AbsolutePath -Path $Destination -Name "Destination"
    $project = Join-Path $SourceRoot "services\windows\OpenBB.ServiceHost\OpenBB.ServiceHost.csproj"
    $platform = Join-Path $SourceRoot "openbb_platform"
    if (-not (Test-Path -LiteralPath $project -PathType Leaf)) {
        throw "Service host project was not found: $project"
    }
    if (-not (Test-Path -LiteralPath $platform -PathType Container)) {
        throw "OpenBB platform source was not found: $platform"
    }
    if ($ArtifactDirectory) {
        Assert-AbsolutePath -Path $ArtifactDirectory -Name "ArtifactDirectory"
        if (-not (Test-Path -LiteralPath $ArtifactDirectory -PathType Container)) {
            throw "ArtifactDirectory was not found: $ArtifactDirectory"
        }
    }

    if (-not $PSCmdlet.ShouldProcess($Destination, "Publish OpenBB release")) {
        return
    }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $hostDirectory = Join-Path $Destination "host"
    $appDirectory = Join-Path $Destination "app"
    New-Item -ItemType Directory -Path $hostDirectory, $appDirectory -Force | Out-Null
    if ($ArtifactDirectory) {
        Copy-Item -Path (Join-Path $ArtifactDirectory "*") -Destination $hostDirectory -Recurse -Force
    } else {
        Invoke-CheckedCommand -FilePath "dotnet.exe" -ArgumentList @(
            "publish", $project, "-c", "Release", "-r", "win-x64",
            "--self-contained", "true", "-p:PublishSingleFile=true",
            "-o", $hostDirectory)
    }
    Copy-Item -Path $platform -Destination $appDirectory -Recurse -Force

    if (-not $SkipPythonInstall) {
        $venvDirectory = Join-Path $Destination "python"
        Invoke-CheckedCommand -FilePath $PythonExecutable -ArgumentList @("-m", "venv", $venvDirectory)
        $venvPython = Join-Path $venvDirectory "Scripts\python.exe"
        $packages = @(
            "openbb_platform\core",
            "openbb_platform\extensions\portfolio",
            "openbb_platform\extensions\portfolio_intel",
            "openbb_platform\extensions\techtrade",
            "openbb_platform\providers\fmp_cached"
        ) | ForEach-Object { Join-Path $appDirectory $_ }
        Invoke-CheckedCommand -FilePath $venvPython -ArgumentList @(
            "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--upgrade", "pip")
        Invoke-CheckedCommand -FilePath $venvPython -ArgumentList (
            @("-m", "pip", "install", "--disable-pip-version-check", "--no-input") +
            $packages)
    }
    $hostExecutable = Join-Path $hostDirectory "OpenBB.ServiceHost.exe"
    if (-not (Test-Path -LiteralPath $hostExecutable -PathType Leaf)) {
        throw "Published service executable was not found: $hostExecutable"
    }
    if (-not $SkipPythonInstall -and
        -not (Test-Path -LiteralPath (Join-Path $Destination "python\Scripts\python.exe") -PathType Leaf)) {
        throw "Service-owned Python executable was not created."
    }
}

function Write-ServiceConfiguration {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string] $ReleaseRoot,
        [Parameter(Mandatory)][string] $DataRoot
    )
    $configPath = Join-Path $DataRoot "service.json"
    $python = Join-Path $ReleaseRoot "python\Scripts\python.exe"
    $workingDirectory = Join-Path $ReleaseRoot "app"
    $environmentFile = Join-Path $DataRoot "secrets.env"
    $restartDelays = @("00:00:02", "00:00:10", "00:00:30")
    $components = @(
        [ordered]@{
            name = "jobs-worker"; executablePath = $python
            arguments = @("-m", "openbb_core.app.jobs.worker", "worker", "--poll-seconds", "5")
            workingDirectory = $workingDirectory; startupOrder = 10; required = $true
            readinessTimeout = "00:01:00"; gracefulShutdownTimeout = "00:10:00"
            restartWindow = "00:05:00"; maxRestarts = 3; restartDelays = $restartDelays
            environment = @{ OPENBB_INSTALLED_SERVICE = "true" }
        },
        [ordered]@{
            name = "portfolio-api"; executablePath = $python
            arguments = @("-m", "openbb_platform_api.main", "--app", "openbb_platform/extensions/portfolio/launch.py", "--host", "127.0.0.1", "--port", "6902")
            workingDirectory = $workingDirectory; bindAddress = "127.0.0.1"; port = 6902
            startupOrder = 20; required = $true; readinessTimeout = "00:01:00"
            gracefulShutdownTimeout = "00:00:30"; restartWindow = "00:05:00"
            maxRestarts = 3; restartDelays = $restartDelays
            environment = @{ OPENBB_INSTALLED_SERVICE = "true" }
        },
        [ordered]@{
            name = "portfolio-intel-ux"; executablePath = $python
            arguments = @("-m", "uvicorn", "openbb_portfolio_intel.widget_backend.main:app", "--host", "127.0.0.1", "--port", "6120")
            workingDirectory = $workingDirectory; bindAddress = "127.0.0.1"; port = 6120
            startupOrder = 30; required = $true; readinessTimeout = "00:01:00"
            gracefulShutdownTimeout = "00:00:30"; restartWindow = "00:05:00"
            maxRestarts = 3; restartDelays = $restartDelays
            environment = @{ OPENBB_INSTALLED_SERVICE = "true" }
        }
    )
    $configuration = [ordered]@{
        serviceHost = [ordered]@{
            schemaVersion = 1
            environmentFile = $environmentFile
            logDirectory = (Join-Path $DataRoot "logs")
            components = $components
        }
    } | ConvertTo-Json -Depth 8

    if ($PSCmdlet.ShouldProcess($configPath, "Write service configuration")) {
        [IO.File]::WriteAllText($configPath, $configuration, [Text.UTF8Encoding]::new($false))
    }
    return $configPath
}

function Set-OpenBBWindowsService {
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][string] $HostExecutable, [Parameter(Mandatory)][string] $ConfigPath)
    $binaryPath = "`"$HostExecutable`" --config `"$ConfigPath`""
    $existing = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
    if ($PSCmdlet.ShouldProcess($script:ServiceName, "Register Windows service")) {
        if ($null -eq $existing) {
            Invoke-CheckedCommand "sc.exe" @(
                "create", $script:ServiceName, "binPath=", $binaryPath,
                "start=", "delayed-auto", "obj=", $script:ServiceAccount)
        } else {
            Invoke-CheckedCommand "sc.exe" @(
                "config", $script:ServiceName, "binPath=", $binaryPath,
                "start=", "delayed-auto", "obj=", $script:ServiceAccount)
        }
        Invoke-CheckedCommand "sc.exe" @(
            "description", $script:ServiceName,
            "Hosts OpenBB Portfolio API, Portfolio Intelligence UX, and durable jobs worker.")
        Invoke-CheckedCommand "sc.exe" @(
            "failure", $script:ServiceName, "reset=", "86400",
            "actions=", "restart/5000/restart/15000/restart/60000")
        Invoke-CheckedCommand "sc.exe" @("failureflag", $script:ServiceName, "1")
    }
}

function Invoke-ServiceDoctor {
    param([Parameter(Mandatory)][string] $HostExecutable, [Parameter(Mandatory)][string] $ConfigPath)
    Invoke-CheckedCommand $HostExecutable @("doctor", "--json", "--config", $ConfigPath)
}

Export-ModuleMember -Function Assert-AbsolutePath, Ensure-SecretFile, Publish-OpenBBRelease,
    Write-ServiceConfiguration, Set-ServiceAcl, Set-OpenBBWindowsService,
    Invoke-ServiceDoctor, Test-IsAdministrator
