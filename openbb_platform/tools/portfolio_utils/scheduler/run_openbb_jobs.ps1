[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $JobName,
    [string] $ParamsJson = "{}",
    [string] $LogName = $JobName.Replace(".", "_")
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("{0}_{1}.log" -f $LogName, (Get-Date -Format "yyyy-MM-dd"))
$python = @(
    (Join-Path $repoRoot ".venv_portfolio\Scripts\python.exe"),
    (Join-Path $repoRoot ".venv_win\Scripts\python.exe"),
    (Join-Path $repoRoot "venv\Scripts\python.exe")
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $python) {
    throw "No OpenBB Python environment was found."
}

$env:PYTHONIOENCODING = "utf-8"
"[$(Get-Date -Format o)] Triggering $JobName" | Out-File $logFile -Append -Encoding utf8
& $python -m openbb_core.app.jobs.worker trigger $JobName `
    --params-json $ParamsJson --wait *>&1 |
    Out-File $logFile -Append -Encoding utf8
$exitCode = $LASTEXITCODE
"[$(Get-Date -Format o)] Completed with exit code $exitCode" |
    Out-File $logFile -Append -Encoding utf8
exit $exitCode
