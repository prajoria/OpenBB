$runner = Join-Path $PSScriptRoot "run_openbb_jobs.ps1"
& $runner -JobName "portfolio.position_history" -ParamsJson '{"years":5}' `
    -LogName "fetch_position_history"
exit $LASTEXITCODE
