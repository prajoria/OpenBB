$ErrorActionPreference = "Stop"

# Derive the repo root from this script's location (Tools/scheduler/ -> repo root)
# so the scheduled task is portable across machines/checkouts.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scriptPath = Join-Path $repoRoot "Tools\fetch_position_history.py"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("fetch_position_history_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

$pythonCandidates = @(
  (Join-Path $repoRoot ".venv_win\Scripts\python.exe"),
  (Join-Path $repoRoot "venv\Scripts\python.exe")
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonExe) {
  $pythonExe = "py"
}

$env:FMP_CACHE_AUTO_CREATE_DB = "false"
$env:PYTHONIOENCODING = "utf-8"

"[$(Get-Date -Format o)] Starting fetch_position_history" | Tee-Object -FilePath $logFile -Append
"[$(Get-Date -Format o)] Using Python: $pythonExe" | Tee-Object -FilePath $logFile -Append

if ($pythonExe -eq "py") {
  & py -3 $scriptPath --database openbb_fmp_cache_test --years 5 2>&1 | Tee-Object -FilePath $logFile -Append
  $exitCode = $LASTEXITCODE
} else {
  & $pythonExe $scriptPath --database openbb_fmp_cache_test --years 5 2>&1 | Tee-Object -FilePath $logFile -Append
  $exitCode = $LASTEXITCODE
}

"[$(Get-Date -Format o)] Completed with exit code: $exitCode" | Tee-Object -FilePath $logFile -Append
exit $exitCode
