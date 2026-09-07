[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
    [string] $ServiceName = "OpenBBPortfolio",
    [string] $DataRoot = "$env:ProgramData\OpenBB Portfolio",
    [int] $TimeoutSeconds = 120,
    [string] $EvidencePath,
    [switch] $ExerciseScmRecovery,
    [switch] $ExerciseRecovery,
    [switch] $ExerciseCleanStop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Wait-Until {
    param([Parameter(Mandatory)][scriptblock] $Condition, [string] $Failure)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            return
        }
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw $Failure
}

function Get-ServiceProcess {
    $service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
    if ($null -eq $service) {
        throw "Windows service '$ServiceName' is not installed."
    }
    return $service
}

function Get-DescendantProcesses {
    param([Parameter(Mandatory)][uint32] $ParentId)
    $all = @(Get-CimInstance Win32_Process)
    $pending = [Collections.Generic.Queue[uint32]]::new()
    $pending.Enqueue($ParentId)
    $result = [Collections.Generic.List[object]]::new()
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($child in $all | Where-Object ParentProcessId -eq $current) {
            $result.Add($child)
            $pending.Enqueue([uint32]$child.ProcessId)
        }
    }
    return $result
}

function Get-ComponentProcess {
    param([Parameter(Mandatory)][string] $Marker)
    $service = Get-ServiceProcess
    return Get-DescendantProcesses -ParentId ([uint32]$service.ProcessId) |
        Where-Object { $_.CommandLine -like "*$Marker*" } |
        Select-Object -First 1
}

function Read-WidgetToken {
    $secretPath = Join-Path $DataRoot "secrets.env"
    $line = Get-Content -LiteralPath $secretPath |
        Where-Object { $_ -match '^PI_WIDGET_BACKEND_TOKEN=' } |
        Select-Object -First 1
    if (-not $line) {
        throw "Widget token is missing from the service environment file."
    }
    return $line.Substring($line.IndexOf("=") + 1)
}

function Assert-HttpEndpoint {
    param([Parameter(Mandatory)][string] $Uri, [hashtable] $Headers = @{})
    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers $Headers -TimeoutSec 15
    } catch {
        throw "Health request failed for $Uri`: $($_.Exception.Message)"
    }
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "$Uri returned HTTP $($response.StatusCode)."
    }
}

$startedAt = [DateTimeOffset]::UtcNow
$service = Get-ServiceProcess
if ($service.State -ne "Running") {
    throw "Windows service '$ServiceName' is not running."
}
if ($service.StartMode -ne "Auto") {
    throw "Windows service '$ServiceName' is not configured for automatic startup."
}
if ($service.StartName -ne "NT SERVICE\$ServiceName") {
    throw "Windows service '$ServiceName' is not using its virtual service account."
}

$configPath = Join-Path $DataRoot "service.json"
Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json | Out-Null
$hostProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($service.ProcessId)"
$hostExecutable = $hostProcess.ExecutablePath
if (-not $hostExecutable) {
    throw "Could not resolve the service host executable."
}
& $hostExecutable doctor --json --config $configPath | ConvertFrom-Json | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Service-host doctor reported an unhealthy component."
}

$token = Read-WidgetToken
$headers = @{ Authorization = "Bearer $token" }
Assert-HttpEndpoint "http://127.0.0.1:6120/viewer"
Assert-HttpEndpoint "http://127.0.0.1:6120/widgets.json"
Assert-HttpEndpoint "http://127.0.0.1:6902/api/v1/coverage/commands"
Assert-HttpEndpoint "http://127.0.0.1:6902/api/v1/jobs/health" $headers

$scmRecoveryVerified = $false
if ($ExerciseScmRecovery -and
    $PSCmdlet.ShouldProcess($ServiceName, "Exhaust child restart budget and verify SCM recovery")) {
    $hostProcessId = (Get-ServiceProcess).ProcessId
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        $worker = Get-ComponentProcess "openbb_core.app.jobs.worker"
        if ($null -eq $worker) {
            throw "Could not locate the jobs-worker child process."
        }
        Stop-Process -Id $worker.ProcessId -Force
        if ($attempt -lt 4) {
            Wait-Until {
                $replacement = Get-ComponentProcess "openbb_core.app.jobs.worker"
                $null -ne $replacement -and $replacement.ProcessId -ne $worker.ProcessId
            } "The jobs worker did not restart after failure $attempt."
        }
    }
    Wait-Until {
        $replacementService = Get-ServiceProcess
        $replacementService.State -eq "Running" -and
            $replacementService.ProcessId -ne $hostProcessId
    } "SCM did not replace the service host after restart-budget exhaustion."
    $scmRecoveryVerified = $true
}

$recoveredComponents = @()
if ($ExerciseRecovery) {
    foreach ($component in @(
        @{ Name = "jobs-worker"; Marker = "openbb_core.app.jobs.worker" },
        @{ Name = "portfolio-api"; Marker = "openbb_platform_api.main" },
        @{ Name = "portfolio-intel-ux"; Marker = "openbb_portfolio_intel.widget_backend.main" }
    )) {
        $before = Get-ComponentProcess $component.Marker
        if ($null -eq $before) {
            throw "Could not locate the $($component.Name) child process."
        }
        if ($PSCmdlet.ShouldProcess(
            "$($component.Name) PID $($before.ProcessId)",
            "Terminate child and verify isolated restart")) {
            Stop-Process -Id $before.ProcessId -Force
            Wait-Until {
                $after = Get-ComponentProcess $component.Marker
                $null -ne $after -and $after.ProcessId -ne $before.ProcessId
            } "The $($component.Name) child did not restart."
            $recoveredComponents += $component.Name
        }
    }
}

$cleanStopVerified = $false
if ($ExerciseCleanStop -and $PSCmdlet.ShouldProcess($ServiceName, "Verify descendant-free stop")) {
    $beforeStop = Get-ServiceProcess
    $descendantIds = @(Get-DescendantProcesses ([uint32]$beforeStop.ProcessId) |
        ForEach-Object ProcessId)
    Stop-Service -Name $ServiceName
    Wait-Until {
        @($descendantIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count -eq 0
    } "Child processes remained after service stop."
    $cleanStopVerified = $true
    Start-Service -Name $ServiceName
    Wait-Until { (Get-Service -Name $ServiceName).Status -eq "Running" } "Service did not restart."
}

$evidence = [ordered]@{
    schemaVersion = 1
    service = $ServiceName
    startedAtUtc = $startedAt
    completedAtUtc = [DateTimeOffset]::UtcNow
    healthy = $true
    endpoints = @(
        "portfolio-intel-viewer",
        "portfolio-intel-widgets",
        "portfolio-api-coverage",
        "jobs-heartbeat")
    recoveredComponents = $recoveredComponents
    scmRecoveryVerified = $scmRecoveryVerified
    cleanStopVerified = $cleanStopVerified
}
if ($EvidencePath) {
    $parent = Split-Path -Parent ([IO.Path]::GetFullPath($EvidencePath))
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $evidence | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $EvidencePath -Encoding utf8NoBOM
}
$evidence | ConvertTo-Json -Depth 4
