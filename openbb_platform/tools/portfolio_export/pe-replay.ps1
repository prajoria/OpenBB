<#
.SYNOPSIS
    Wraps `pe replay` so you can invoke it from anywhere without typing the
    full venv path.

.PARAMETER Name
    Recording name to replay. Searches
    $env:PORTFOLIO_EXPORT_RECORDINGS_DIR\<Name>.py first, then falls back
    to the bundled recordings/<Name>.py inside portfolio-export/.

.EXAMPLE
    .\pe-replay.ps1 fidelity_export
    .\pe-replay.ps1 example_fidelity_export   # bundled skeleton
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Name
)

$ErrorActionPreference = "Stop"

# portfolio-export\pe-replay.ps1  ->  OpenBB\
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
$pe        = Join-Path $repoRoot ".venv_portfolio\Scripts\pe.exe"

if (-not (Test-Path $pe)) {
    Write-Error @"
Could not find $pe.

Install the tool first:
  & "$repoRoot\.venv_portfolio\Scripts\python.exe" -m pip install -e "$scriptDir"
  & "$repoRoot\.venv_portfolio\Scripts\python.exe" -m playwright install chromium
"@
    exit 1
}

& $pe replay $Name
exit $LASTEXITCODE
