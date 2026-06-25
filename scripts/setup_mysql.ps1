#!/usr/bin/env pwsh
# setup_mysql.ps1 — Post-install MySQL setup for fmp_cached provider
# Reads ALL credentials from .env in the repo root.
# Run once after: winget install Oracle.MySQL

param(
    [string]$EnvFile = "$PSScriptRoot\..\\.env",
    [string]$DumpFile = "H:\DBBackup\openbb_fmp_cache_test_20260226_001244.sql"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── 1. Load .env ─────────────────────────────────────────────────────────────
Write-Host "`n[1/7] Loading credentials from .env ..." -ForegroundColor Cyan
if (-not (Test-Path $EnvFile)) { throw ".env not found at $EnvFile" }

$env_vars = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $k, $v = $line -split '=', 2
    $env_vars[$k.Trim()] = $v.Trim()
}

$MYSQL_HOST     = $env_vars["MYSQL_HOST"]     ?? "localhost"
$MYSQL_PORT     = $env_vars["MYSQL_PORT"]     ?? "3306"
$MYSQL_USER     = $env_vars["MYSQL_USER"]     ?? "fmp_user"
$MYSQL_PASSWORD = $env_vars["MYSQL_PASSWORD"] ?? "fmp_password"
$MYSQL_DATABASE = $env_vars["MYSQL_DATABASE"] ?? "openbb_fmp_cache"
$DUMP_DATABASE  = "openbb_fmp_cache_test"   # name baked into the dump

Write-Host "  Host     : $MYSQL_HOST`:$MYSQL_PORT"
Write-Host "  App user : $MYSQL_USER"
Write-Host "  Databases: $DUMP_DATABASE  +  $MYSQL_DATABASE"

# ── 2. Find mysql.exe ─────────────────────────────────────────────────────────
Write-Host "`n[2/7] Locating MySQL executables ..." -ForegroundColor Cyan
$mysqlBase = (Get-ChildItem "C:\Program Files\MySQL" -Directory -ErrorAction SilentlyContinue |
              Sort-Object Name -Descending | Select-Object -First 1).FullName
if (-not $mysqlBase) { throw "MySQL installation not found under C:\Program Files\MySQL" }

$mysql    = Join-Path $mysqlBase "bin\mysql.exe"
$mysqladm = Join-Path $mysqlBase "bin\mysqladmin.exe"
Write-Host "  Found: $mysqlBase"

# ── 3. Find temporary root password from error log ───────────────────────────
Write-Host "`n[3/7] Retrieving temporary root password from error log ..." -ForegroundColor Cyan
$dataDir  = Join-Path $mysqlBase "data"
$errLog   = Get-ChildItem $dataDir -Filter "*.err" -ErrorAction SilentlyContinue |
            Select-Object -First 1
$tempPass = ""
if ($errLog) {
    $match = Select-String -Path $errLog.FullName `
             -Pattern "A temporary password is generated for root@localhost: (.+)$"
    if ($match) { $tempPass = $match.Matches[0].Groups[1].Value.Trim() }
}

if (-not $tempPass) {
    # MySQL might already have been initialized; try empty root password
    Write-Host "  No temp password found — checking if root has empty password ..."
    $testEmpty = & $mysql -u root --password="" -e "SELECT 1;" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Root has empty password — proceeding."
    } else {
        Write-Host ""
        Write-Host "  Could not find temp password and empty root login failed." -ForegroundColor Yellow
        Write-Host "  Please enter the MySQL root password (check Windows Event Viewer or"
        Write-Host "  C:\ProgramData\MySQL\MySQL Server 8.4\Data\*.err for the temp password):" -ForegroundColor Yellow
        $securePass = Read-Host -AsSecureString "Root password"
        $tempPass   = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                          [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePass))
    }
} else {
    Write-Host "  Temp password found."
}

# Helper: run a SQL command as root
function Invoke-MySQLRoot([string]$Sql) {
    if ($tempPass) {
        $result = & $mysql -u root "-p$tempPass" --connect-expired-password -e $Sql 2>&1
    } else {
        $result = & $mysql -u root --password="" -e $Sql 2>&1
    }
    if ($LASTEXITCODE -ne 0) { throw "MySQL error: $result" }
    return $result
}

# ── 4. Set permanent root password & remove temp-password flag ────────────────
Write-Host "`n[4/7] Setting root password (required before any DDL) ..." -ForegroundColor Cyan
if ($tempPass) {
    # With temp password the only allowed statement is ALTER USER
    $alterSql = "ALTER USER 'root'@'localhost' IDENTIFIED BY 'root_localdev_2026';"
    if ($tempPass) {
        & $mysql -u root "-p$tempPass" --connect-expired-password -e $alterSql 2>&1 | Out-Null
    }
    $tempPass = "root_localdev_2026"
    Write-Host "  Root password set to: root_localdev_2026"
} else {
    Write-Host "  Root already has a permanent password — skipping."
}

# ── 5. Create app user and databases ─────────────────────────────────────────
Write-Host "`n[5/7] Creating user '$MYSQL_USER' and databases ..." -ForegroundColor Cyan
$setupSql = @"
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'${MYSQL_HOST}' IDENTIFIED BY '${MYSQL_PASSWORD}';
CREATE DATABASE IF NOT EXISTS \`${DUMP_DATABASE}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON \`${DUMP_DATABASE}\`.* TO '${MYSQL_USER}'@'${MYSQL_HOST}';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'${MYSQL_HOST}';
FLUSH PRIVILEGES;
"@
Invoke-MySQLRoot $setupSql
Write-Host "  User and databases created."

# ── 6. Restore dump ───────────────────────────────────────────────────────────
Write-Host "`n[6/7] Restoring dump (233 MB — may take a few minutes) ..." -ForegroundColor Cyan
if (-not (Test-Path $DumpFile)) { throw "Dump file not found: $DumpFile" }

# Pipe the dump as root (it contains its own USE statement)
Get-Content $DumpFile -Raw | & $mysql -u root "-p$tempPass" 2>&1
if ($LASTEXITCODE -ne 0) { throw "Restore failed — check output above" }
Write-Host "  Dump restored into $DUMP_DATABASE"

# Also alias: copy schema to the production database name if different
if ($DUMP_DATABASE -ne $MYSQL_DATABASE) {
    Write-Host "  Creating '$MYSQL_DATABASE' as a synonym (dump DB = '$DUMP_DATABASE') ..."
    # Simplest safe approach: create the DB and grant; the app connects to whichever name
    # is in user_settings.json — we point it at DUMP_DATABASE since that has the data.
    Write-Host "  NOTE: Pointing user_settings.json at '$DUMP_DATABASE' (where the data lives)."
    $MYSQL_DATABASE = $DUMP_DATABASE
}

# ── 7. Write user_settings.json ──────────────────────────────────────────────
Write-Host "`n[7/7] Writing MySQL credentials to user_settings.json ..." -ForegroundColor Cyan
$settingsPath = "$HOME\.openbb_platform\user_settings.json"
$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json

$settings.credentials | Add-Member -Force -NotePropertyMembers @{
    mysql_host     = $MYSQL_HOST
    mysql_port     = [int]$MYSQL_PORT
    mysql_user     = $MYSQL_USER
    mysql_password = $MYSQL_PASSWORD
    mysql_database = $MYSQL_DATABASE
}

$settings | ConvertTo-Json -Depth 5 | Set-Content $settingsPath -Encoding UTF8
Write-Host "  Written to $settingsPath"

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " MySQL setup complete!" -ForegroundColor Green
Write-Host "  Server  : $MYSQL_HOST`:$MYSQL_PORT" -ForegroundColor Green
Write-Host "  Database: $MYSQL_DATABASE" -ForegroundColor Green
Write-Host "  User    : $MYSQL_USER" -ForegroundColor Green
Write-Host "  user_settings.json updated." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next: restart the Jupyter kernel and re-run Cell 3.1." -ForegroundColor Cyan
