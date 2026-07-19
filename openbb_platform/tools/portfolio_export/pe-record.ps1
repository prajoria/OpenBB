<#
.SYNOPSIS
    Wraps `pe record` so you can invoke it from anywhere without typing the
    full venv path.

.PARAMETER Name
    Recording name. Scaffold file will be created at
    $env:PORTFOLIO_EXPORT_RECORDINGS_DIR\<Name>.py (default:
    ~/portfolio_export_recordings/<Name>.py; this repo's .env overrides
    to H:\masterswork\browser_recordings\).

.PARAMETER Url
    Initial URL to open. Defaults to https://digital.fidelity.com/.

.EXAMPLE
    .\pe-record.ps1 fidelity_export
    .\pe-record.ps1 chase_export -Url https://secure01a.chase.com/
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Name,

    [string]$Url = "https://digital.fidelity.com/"
)

$ErrorActionPreference = "Stop"

# portfolio-export\pe-record.ps1  ->  OpenBB\
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

& $pe record $Name --url $Url
exit $LASTEXITCODE
