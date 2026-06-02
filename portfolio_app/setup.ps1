<#
.SYNOPSIS
    Setup script for the Portfolio App.
    Uses .venv_win (the project-level from-source virtual environment)
    and installs portfolio app dependencies into it.

    NOTE: .venv_openbb is a separate environment for running the
    OpenBB Platform from PyPI (pre-built packages). This app runs
    from the OpenBB source tree and uses .venv_win.

.USAGE
    .\portfolio_app\setup.ps1
#>

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$projectRoot\portfolio_app")) {
    $projectRoot = $PWD.Path
}

$venvDir = Join-Path $projectRoot ".venv_win"
$requirementsFile = Join-Path $projectRoot "portfolio_app\requirements.txt"
$openbbPlatformDir = Join-Path $projectRoot "openbb_platform"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Portfolio App - Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $venvDir)) {
    Write-Host "[1/4] Creating virtual environment: $venvDir" -ForegroundColor Yellow
    python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create venv" }
    Write-Host "      Created." -ForegroundColor Green
} else {
    Write-Host "[1/4] Virtual environment already exists: $venvDir" -ForegroundColor Green
}

$pip = Join-Path $venvDir "Scripts\pip.exe"
$python = Join-Path $venvDir "Scripts\python.exe"

Write-Host "[2/4] Upgrading pip ..." -ForegroundColor Yellow
& $python -m pip install --upgrade pip --quiet
Write-Host "      Done." -ForegroundColor Green

Write-Host "[3/4] Installing OpenBB Platform + portfolio app dependencies ..." -ForegroundColor Yellow
Write-Host "      This may take a few minutes ..." -ForegroundColor DarkGray
if (-not (Test-Path $openbbPlatformDir)) { throw "openbb_platform directory not found at $openbbPlatformDir" }

Write-Host "      Installing OpenBB installer prerequisites (tomlkit, poetry)" -ForegroundColor DarkGray
& $pip install tomlkit poetry
if ($LASTEXITCODE -ne 0) { throw "Failed to install OpenBB installer prerequisites" }

Write-Host "      Installing OpenBB from source: $openbbPlatformDir" -ForegroundColor DarkGray
Push-Location $openbbPlatformDir
& $python "dev_install.py" -e
$devInstallExitCode = $LASTEXITCODE
Pop-Location
if ($devInstallExitCode -ne 0) { throw "OpenBB source install failed" }

Write-Host "      Installing portfolio app requirements: $requirementsFile" -ForegroundColor DarkGray
& $pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Host "      Done." -ForegroundColor Green

Write-Host "[4/4] Verifying installation ..." -ForegroundColor Yellow
& $python -c "import openbb; print('  OpenBB import OK'); print('  OpenBB version:', getattr(openbb, '__version__', 'source-install'))"
& $python -c "import fastapi; print(f'  FastAPI version: {fastapi.__version__}')"
& $python -c "import uvicorn; print('  uvicorn OK')"
& $python -c "import pymysql; print('  pymysql OK')"
& $python -c "import httpx; print('  httpx OK')"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  To run the services:" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  Terminal 1 (OpenBB API on :6902):" -ForegroundColor White
Write-Host "    .venv_win\Scripts\openbb-api --host 127.0.0.1 --port 6902" -ForegroundColor DarkGray
Write-Host "" -ForegroundColor Green
Write-Host "  Terminal 2 (Portfolio App on :6903):" -ForegroundColor White
Write-Host "    .venv_win\Scripts\python portfolio_app\run_portfolio.py" -ForegroundColor DarkGray
Write-Host "" -ForegroundColor Green
Write-Host "  Then connect OpenBB Workspace to http://127.0.0.1:6902" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
