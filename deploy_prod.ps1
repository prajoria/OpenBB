<#
.SYNOPSIS
    Deploy the OpenBB Platform PRODUCTION baseline into .venv_openbb_master.

    Installs the official PyPI release of OpenBB (with all extras) into a
    clean venv, generates SSL certificates, and runs the API on port 6901.

    This gives you a known-good production baseline to compare against your
    dev environment (.venv_openbb on port 6902).

    Port layout:
      6901 -- production baseline  (.venv_openbb_master, PyPI release)
      6902 -- dev environment      (.venv_openbb, local source)
      6903 -- portfolio_app        (.venv_win, side-service)

.EXAMPLE
    .\deploy_prod.ps1
    powershell -ExecutionPolicy Bypass -File deploy_prod.ps1
#>

$ErrorActionPreference = "Continue"
$RepoRoot   = $PSScriptRoot
$VenvDir    = Join-Path $RepoRoot ".venv_openbb_master"
$CertsDir   = Join-Path $RepoRoot "certs"

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

$steps = 5
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  OpenBB PRODUCTION Baseline -- deploy into .venv_openbb_master" -ForegroundColor Cyan
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

# -- 2. Install/upgrade pip -----------------------------------------------
Write-Step 2 $steps "Upgrading pip"
& $Python -m pip install --upgrade pip --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
Write-Ok "pip upgraded"

# -- 3. Install openbb[all] from PyPI ------------------------------------
Write-Step 3 $steps "Installing openbb[all] from PyPI (this may take several minutes)"
& $Pip install "openbb[all]" --quiet 2>$null
if ($LASTEXITCODE -ne 0) { throw "openbb install failed" }

$obbVer = & $Python -W ignore -c "from importlib.metadata import version; print(version('openbb'))" 2>$null
Write-Ok "openbb $obbVer installed from PyPI."

# -- 4. Generate self-signed SSL certificates ------------------------------
$CertFile = Join-Path $CertsDir "cert.pem"
$KeyFile  = Join-Path $CertsDir "key.pem"

if ((Test-Path $CertFile) -and (Test-Path $KeyFile)) {
    Write-Step 4 $steps "SSL certificates already exist in certs/"
    Write-Ok "Reusing."
} else {
    Write-Step 4 $steps "Generating self-signed SSL certificates"
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

# -- 5. Verify installation -----------------------------------------------
Write-Step 5 $steps "Verifying installation"

$allOk = $true

# openbb
$r = & $Python -W ignore -c "import openbb; print('openbb OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb" -ForegroundColor Red; $allOk = $false }

# openbb-core
$r = & $Python -W ignore -c "import openbb_core; print('openbb-core OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-core" -ForegroundColor Red; $allOk = $false }

# openbb-platform-api (provides openbb-api CLI + widgets.json)
$r = & $Python -W ignore -c "import openbb_platform_api; print('openbb-platform-api OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-platform-api" -ForegroundColor Red; $allOk = $false }

# openbb-fmp
$r = & $Python -W ignore -c "import openbb_fmp; print('openbb-fmp OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-fmp" -ForegroundColor Red; $allOk = $false }

# obb router
$r = & $Python -W ignore -c "from openbb import obb; print('openbb obb router OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: obb router" -ForegroundColor Red; $allOk = $false }

# openbb-api CLI
$r = & $Python -W ignore -c "from openbb_platform_api.main import launch_api; print('openbb-api CLI OK')" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Ok $r } else { Write-Host "        FAIL: openbb-api CLI" -ForegroundColor Red; $allOk = $false }

Write-Host ""
if ($allOk) {
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  Production baseline deployed -- .venv_openbb_master is ready." -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  Activate:" -ForegroundColor Green
    Write-Host "    .\.venv_openbb_master\Scripts\Activate.ps1" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  Start API (HTTP, port 6901 -- official production mode):" -ForegroundColor Green
    Write-Host "    openbb-api --port 6901" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  Start API (HTTPS, port 6901 -- for Workspace):" -ForegroundColor Green
    Write-Host "    openbb-api --port 6901 --ssl-certfile certs/cert.pem --ssl-keyfile certs/key.pem" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  Port layout:" -ForegroundColor DarkGray
    Write-Host "    6901 -- production baseline  (this venv)" -ForegroundColor DarkGray
    Write-Host "    6902 -- dev environment      (.venv_openbb)" -ForegroundColor DarkGray
    Write-Host "    6903 -- portfolio_app        (.venv_win)" -ForegroundColor DarkGray
    Write-Host "================================================================" -ForegroundColor Green
} else {
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host "  Deploy finished with errors -- check output above." -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Red
}
Write-Host ""
