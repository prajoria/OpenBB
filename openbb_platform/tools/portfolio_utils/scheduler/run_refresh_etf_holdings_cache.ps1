# Daily warmer for the fmp_cached etf_holdings cache (#97 / techtrade scan).
#
# Sibling to run_fetch_position_history.ps1.  Scheduled separately because the
# two tools have different failure modes and re-run cadences.
#
# Cadence: daily, ~02:00 local (an hour after fetch_position_history).

$ErrorActionPreference = "Stop"

# Derive repo root from this script's location so the scheduled task is
# portable across machines/checkouts.
# openbb_platform/tools/portfolio_utils/scheduler/ -> repo root
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Prefer .venv_portfolio (portfolio-branch canonical venv), fall back to .venv_win.
$pythonCandidates = @(
    (Join-Path $root ".venv_portfolio\Scripts\python.exe"),
    (Join-Path $root ".venv_win\Scripts\python.exe")
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonExe) { $pythonExe = "py" }

& $pythonExe `
    (Join-Path $root "openbb_platform\tools\portfolio_utils\portfolio_utils\refresh_etf_holdings_cache.py") `
    --database openbb_fmp_cache_test `
    *>&1 | Out-File -Append -Encoding utf8 "$logDir\refresh_etf_holdings_cache.log"
