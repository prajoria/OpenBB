<#
.SYNOPSIS
    Deploy the OpenBB Platform dev environment into .venv_openbb.

    Installs the full OpenBB Platform from the local source tree
    (core + all providers/extensions + community extras) and the
    custom fmp_cached provider -- all via Poetry with editable/develop
    links so code changes take effect immediately.

    portfolio_app is NOT included -- it runs as a side-service in its
    own venv (.venv_win).

.DESCRIPTION
    Steps (fully non-interactive):
      1. Create .venv_openbb if it does not exist
      2. Install/upgrade pip + poetry inside the venv
      3. poetry install -E all  (core + all providers/extensions from source)
      4. pip install -e providers/fmp_cached  (custom, not in upstream pyproject)
      5. Verify the installation

.EXAMPLE
    .\deploy_dev.ps1
    powershell -ExecutionPolicy Bypass -File deploy_dev.ps1
#>

$ErrorActionPreference = "Continue"
$RepoRoot     = $PSScriptRoot
$VenvDir      = Join-Path $RepoRoot ".venv_openbb"
$PlatformDir  = Join-Path $RepoRoot "openbb_platform"
$FmpCachedDir = Join-Path $PlatformDir "providers\fmp_cached"

$CertsDir     = Join-Path $RepoRoot "certs"

$Python = Join-Path $VenvDir "Scripts\python.exe"
$Pip    = Join-Path $VenvDir "Scripts\pip.exe"

function Write-Step($num, $total, $msg) {
    Write-Host "[$num/$total] $msg" -ForegroundColor Yellow
}
function Write-Ok($msg) {
    Write-Host "        $msg" -ForegroundColor Green
}
function Write-Info($msg) {
    Write-Host "        $msg" -ForegroundColor DarkGray
}

$steps = 6
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  OpenBB Dev Environment -- deploy into .venv_openbb" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Create venv -------------------------------------------------------
if (-not (Test-Path $VenvDir)) {
    Write-Step 1 $steps "Creating virtual environment: $VenvDir"
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create venv" }
    Write-Ok "Created."
} else {
    Write-Step 1 $steps "Virtual environment exists: $VenvDir"
    Write-Ok "Reusing."
}

# -- 2. Install/upgrade pip + poetry --------------------------------------
Write-Step 2 $steps "Installing pip + poetry inside venv"
& $Python -m pip install --upgrade pip --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
Write-Info "pip upgraded"

& $Pip install --quiet poetry tomlkit poetry-core 2>$null
if ($LASTEXITCODE -ne 0) { throw "poetry install failed" }
Write-Ok "poetry installed"

$poetryVer = & $Python -m poetry --version 2>$null
Write-Info $poetryVer

# -- 3. Poetry install -- all OpenBB packages from source ------------------
Write-Step 3 $steps "Running dev_install.py --extras (this may take several minutes)"
Write-Info "Working directory: $PlatformDir"

# Tell Poetry to use our venv, not create its own
$env:POETRY_VIRTUALENVS_CREATE = "false"
$env:VIRTUAL_ENV = $VenvDir
$env:PYTHONUTF8 = "1"

& $Python (Join-Path $PlatformDir "dev_install.py") --extras
if ($LASTEXITCODE -ne 0) { throw "OpenBB platform install failed" }
Write-Ok "All OpenBB packages installed from source."

# -- 4. Install custom fmp_cached provider --------------------------------
Write-Step 4 $steps "Installing openbb-fmp-cached (editable)"
if (Test-Path $FmpCachedDir) {
    & $Pip install --quiet -e $FmpCachedDir
    if ($LASTEXITCODE -ne 0) { throw "fmp_cached install failed" }
    Write-Ok "openbb-fmp-cached installed."
} else {
    Write-Host "        SKIP: $FmpCachedDir not found" -ForegroundColor Red
}

# -- 5. Generate self-signed SSL certificates ------------------------------
$CertFile = Join-Path $CertsDir "cert.pem"
$KeyFile  = Join-Path $CertsDir "key.pem"

if ((Test-Path $CertFile) -and (Test-Path $KeyFile)) {
    Write-Step 5 $steps "SSL certificates already exist in certs/"
    Write-Ok "Reusing."
} else {
    Write-Step 5 $steps "Generating self-signed SSL certificates"
    if (-not (Test-Path $CertsDir)) { New-Item -ItemType Directory -Path $CertsDir -Force | Out-Null }
    & $Python -c @"
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime, ipaddress

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, u'localhost'),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, u'OpenBB Dev'),
])
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
    .add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName(u'localhost'),
            x509.IPAddress(ipaddress.IPv4Address(u'127.0.0.1')),
        ]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)
with open(r'$KeyFile', 'wb') as f:
    f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
with open(r'$CertFile', 'wb') as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
print('Generated cert.pem + key.pem (valid 365 days)')
"@
    if ($LASTEXITCODE -ne 0) { throw "SSL certificate generation failed" }
    Write-Ok "Certificates created in: $CertsDir"
}

# -- 6. Verify -------------------------------------------------------------
Write-Step 6 $steps "Verifying installation"

$allOk = $true

# openbb
$r = & $Python -W ignore -c "import openbb; print('openbb OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb" -ForegroundColor Red; $allOk = $false }

# openbb-core
$r = & $Python -W ignore -c "import openbb_core; print('openbb-core OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-core" -ForegroundColor Red; $allOk = $false }

# openbb-fmp
$r = & $Python -W ignore -c "import openbb_fmp; print('openbb-fmp OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-fmp" -ForegroundColor Red; $allOk = $false }

# openbb-fmp-cached
$r = & $Python -W ignore -c "import openbb_fmp_cached; print('openbb-fmp-cached OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-fmp-cached" -ForegroundColor Red; $allOk = $false }

# platform-api
$r = & $Python -W ignore -c "from openbb import obb; print('openbb obb router OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: obb router" -ForegroundColor Red; $allOk = $false }

Write-Host ""
if ($allOk) {
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  Deploy complete -- .venv_openbb is ready." -ForegroundColor Green
    Write-Host "  Activate:  .\.venv_openbb\Scripts\Activate.ps1" -ForegroundColor Green
    Write-Host "  Start API (HTTP):  python -m uvicorn openbb_core.api.rest_api:app --host 127.0.0.1 --port 6902" -ForegroundColor Green
    Write-Host "  Start API (HTTPS): python -m uvicorn openbb_core.api.rest_api:app --host 127.0.0.1 --port 6902 --ssl-certfile certs/cert.pem --ssl-keyfile certs/key.pem" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
} else {
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host "  Deploy finished with errors -- check output above." -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Red
}
Write-Host ""
