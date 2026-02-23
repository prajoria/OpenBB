<#
.SYNOPSIS
    Setup script for the Portfolio App.
    Creates .venv_openbb, installs OpenBB from PyPI, and installs
    portfolio app dependencies.

.USAGE
    .\portfolio_app\setup.ps1
#>

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

# If running from project root
if (-not (Test-Path "$projectRoot\portfolio_app")) {
    $projectRoot = $PWD.Path
}

$venvDir = Join-Path $projectRoot ".venv_openbb"
$requirementsFile = Join-Path $projectRoot "portfolio_app\requirements.txt"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Portfolio App — Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Create venv ──────────────────────────────────────────────────── #
if (-not (Test-Path $venvDir)) {
    Write-Host "[1/4] Creating virtual environment: $venvDir" -ForegroundColor Yellow
    python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create venv" }
    Write-Host "      Created." -ForegroundColor Green
} else {
    Write-Host "[1/4] Virtual environment already exists: $venvDir" -ForegroundColor Green
}

# ── Step 2: Upgrade pip ──────────────────────────────────────────────────── #
$pip = Join-Path $venvDir "Scripts\pip.exe"
$python = Join-Path $venvDir "Scripts\python.exe"

Write-Host "[2/4] Upgrading pip ..." -ForegroundColor Yellow
& $python -m pip install --upgrade pip --quiet
Write-Host "      Done." -ForegroundColor Green

# ── Step 3: Install OpenBB + dependencies ────────────────────────────────── #
Write-Host "[3/4] Installing OpenBB Platform + portfolio app dependencies ..." -ForegroundColor Yellow
Write-Host "      This may take a few minutes ..." -ForegroundColor DarkGray
& $pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Host "      Done." -ForegroundColor Green

# ── Step 4: Verify installation ──────────────────────────────────────────── #
Write-Host "[4/4] Verifying installation ..." -ForegroundColor Yellow
& $python -c "import openbb; print(f'  OpenBB version: {openbb.__version__}')"
& $python -c "import fastapi; print(f'  FastAPI version: {fastapi.__version__}')"
& $python -c "import uvicorn; print(f'  uvicorn OK')"
& $python -c "import pymysql; print(f'  pymysql OK')"
& $python -c "import httpx; print(f'  httpx OK')"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  To run the services:" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  Terminal 1 (OpenBB API on :6900):" -ForegroundColor White
Write-Host "    .venv_openbb\Scripts\openbb-api --host 127.0.0.1 --port 6900" -ForegroundColor DarkGray
Write-Host "" -ForegroundColor Green
Write-Host "  Terminal 2 (Portfolio App on :6901):" -ForegroundColor White
Write-Host "    .venv_openbb\Scripts\python portfolio_app\run_portfolio.py" -ForegroundColor DarkGray
Write-Host "" -ForegroundColor Green
Write-Host "  Then connect OpenBB Workspace to http://127.0.0.1:6901" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
