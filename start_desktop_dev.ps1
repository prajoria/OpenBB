#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Launch the OpenBB Desktop (Tauri) app in dev mode.

.DESCRIPTION
    Sets up MSVC (link.exe), Rust (cargo), and OpenSSL environment variables,
    then runs `npm run tauri dev` from the desktop/ directory.

.PARAMETER BuildOnly
    If set, runs `npm run tauri build` instead of dev mode.

.EXAMPLE
    .\start_desktop_dev.ps1
    .\start_desktop_dev.ps1 -BuildOnly
#>

param(
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
$OpenBBRoot = "I:\masterswork\git\OpenBB"

# ── 1. Refresh PATH ──────────────────────────────────────────────────────────
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

# ── 2. Verify Rust ───────────────────────────────────────────────────────────
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
    Write-Error "Rust is not installed. Run: winget install Rustlang.Rustup"
    exit 1
}
Write-Host "Rust: $(rustc --version)" -ForegroundColor DarkCyan

# ── 3. Load MSVC Dev Environment (provides link.exe) ─────────────────────────
$vsDevShell = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\Launch-VsDevShell.ps1"
if (-not (Test-Path $vsDevShell)) {
    Write-Error "VS Build Tools not found at $vsDevShell. Install via: winget install Microsoft.VisualStudio.2022.BuildTools"
    exit 1
}
& $vsDevShell -Arch amd64 -SkipAutomaticLocation

# Re-add user PATH (VS Dev Shell overwrites it, losing cargo)
$env:Path += ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# ── 4. OpenSSL ────────────────────────────────────────────────────────────────
$opensslDir = "C:\Program Files\OpenSSL-Win64"
if (-not (Test-Path $opensslDir)) {
    Write-Error "OpenSSL not found at $opensslDir. Install via: winget install ShiningLight.OpenSSL.Dev"
    exit 1
}
$env:OPENSSL_DIR         = $opensslDir
$env:OPENSSL_LIB_DIR     = "$opensslDir\lib\VC\x64\MD"
$env:OPENSSL_INCLUDE_DIR = "$opensslDir\include"
Write-Host "OpenSSL: $opensslDir" -ForegroundColor DarkCyan

# ── 5. Verify critical tools ─────────────────────────────────────────────────
foreach ($tool in @("cargo", "link")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "'$tool' not found on PATH after environment setup."
        exit 1
    }
}
Write-Host "MSVC linker: $(where.exe link | Select-Object -First 1)" -ForegroundColor DarkCyan

# ── 6. Free port 1470 if occupied ────────────────────────────────────────────
$portInUse = Get-NetTCPConnection -LocalPort 1470 -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "Freeing port 1470..." -ForegroundColor Yellow
    $portInUse | Select-Object OwningProcess -Unique | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

# ── 7. Launch ─────────────────────────────────────────────────────────────────
Set-Location "$OpenBBRoot\desktop"

if ($BuildOnly) {
    Write-Host "`nBuilding OpenBB Desktop (production)..." -ForegroundColor Cyan
    npm run tauri build
} else {
    Write-Host "`nStarting OpenBB Desktop (dev mode on :1470)..." -ForegroundColor Cyan
    npm run tauri dev
}
