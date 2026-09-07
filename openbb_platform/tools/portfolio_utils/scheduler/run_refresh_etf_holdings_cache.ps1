$runner = Join-Path $PSScriptRoot "run_openbb_jobs.ps1"
& $runner -JobName "portfolio.etf_holdings" -LogName "refresh_etf_holdings_cache"
exit $LASTEXITCODE
