# Daily warmer for the fmp_cached etf_holdings cache (#97 / techtrade scan).
#
# Sibling to run_fetch_position_history.ps1.  Scheduled separately because the
# two tools have different failure modes and re-run cadences.
#
# Cadence: daily, ~02:00 local (an hour after fetch_position_history).

$ErrorActionPreference = "Stop"
$root = "H:\masterswork\git\OpenBBTechnical"
$logDir = "$root\Tools\scheduler\logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

& "$root\.venv_win\Scripts\python.exe" `
    "$root\Tools\refresh_etf_holdings_cache.py" `
    --database openbb_fmp_cache_test `
    *>&1 | Out-File -Append -Encoding utf8 "$logDir\refresh_etf_holdings_cache.log"
