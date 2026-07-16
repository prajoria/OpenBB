<#
.SYNOPSIS
    Launch the copilot-api proxy on :4141 with size-based log rotation.

.DESCRIPTION
    Called by start-copilot-proxy.bat. Keeps the verbose proxy log from
    ballooning (a 47 GB proxy.log was observed in the wild) by rotating the
    active log to numbered archives once it crosses a size threshold and
    pruning archives beyond a retention count.

    Rotation model (logrotate-style):
        proxy.log        <- active file being written
        proxy.log.1      <- most recent archive
        proxy.log.2 ...  <- older archives
        proxy.log.<Keep> <- oldest kept; anything older is deleted

    Because each line is written with Add-Content (open/close per call) and
    node writes to a pipe (not the file), no file handle is held between
    writes, so the active log can be renamed safely mid-stream.

.PARAMETER Port
    TCP port the proxy binds. Default 4141.

.PARAMETER ProxyEntry
    Absolute path to the built proxy entry (copilot-api\dist\main.js).

.PARAMETER LogDir
    Directory for proxy.log / proxy-errors.log and their archives.

.PARAMETER MaxLogMB
    Rotate the active proxy.log once it crosses this many MB. Default 50.
    Passed as a plain integer (a "50MB" string can't bind to an int arg
    over -File, so the MB multiplier is applied inside the script).

.PARAMETER MaxErrMB
    Rotate the errors-only proxy-errors.log at this many MB. Default 25.

.PARAMETER Retention
    Number of rotated archives to keep per log. Default 5.

.PARAMETER CheckEveryLines
    How often (in lines) to test the active log size. Default 200. Lower =
    tighter size bound but more stat() calls.

.PARAMETER ProxyArgs
    Any remaining args are forwarded verbatim to the proxy.
#>
[CmdletBinding()]
param(
    [int]$Port = 4141,
    [Parameter(Mandatory = $true)][string]$ProxyEntry,
    [string]$LogDir = (Join-Path $env:USERPROFILE '.local\share\copilot-api'),
    [int]$MaxLogMB = 50,
    [int]$MaxErrMB = 25,
    [int]$Retention = 5,
    [int]$CheckEveryLines = 200,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ProxyArgs
)

$ErrorActionPreference = 'Stop'
[long]$MaxLogBytes = [long]$MaxLogMB * 1MB
[long]$MaxErrBytes = [long]$MaxErrMB * 1MB

# Node/consola emit UTF-8 (the box-drawing startup banner + emoji). Windows
# PowerShell decodes a child process's redirected output using
# [Console]::OutputEncoding, which defaults to the OEM code page (cp437/850) ->
# mojibake ('-' box char shows as 'GoC'-style garbage). Force UTF-8 for the
# console decode and the pipeline; file writes below use an explicit BOM-less
# UTF-8 encoder so the log stays readable end to end.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $utf8NoBom } catch { }
$OutputEncoding = $utf8NoBom

# --- Pre-flight: only one instance can bind the port ------------------------
# Starting a second proxy makes node throw an unhandled EADDRINUSE 'error'
# event and exit 1 ("it crashes"). If one is already listening, reuse it.
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "[start-copilot-proxy] A proxy is already listening on :$Port - reusing it (not starting a second instance). Stop the existing process first for a fresh start."
    exit 0
}

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$Log = Join-Path $LogDir 'proxy.log'
$ErrLog = Join-Path $LogDir 'proxy-errors.log'

# --- Rotation helper --------------------------------------------------------
# Shift <log>.(Keep-1) -> <log>.Keep ... <log>.1 -> <log>.2, drop the oldest,
# then move the active <log> -> <log>.1. The next Add-Content recreates a fresh
# active <log>. Returns $true when a rotation happened.
function Invoke-LogRotation {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][long]$MaxBytes,
        [Parameter(Mandatory = $true)][int]$Keep
    )
    if (-not (Test-Path $Path)) { return $false }
    if ((Get-Item $Path).Length -lt $MaxBytes) { return $false }

    $oldest = "$Path.$Keep"
    if (Test-Path $oldest) { Remove-Item $oldest -Force -ErrorAction SilentlyContinue }
    for ($i = $Keep - 1; $i -ge 1; $i--) {
        $src = "$Path.$i"
        $dst = "$Path.$($i + 1)"
        if (Test-Path $src) { Move-Item $src $dst -Force -ErrorAction SilentlyContinue }
    }
    Move-Item $Path "$Path.1" -Force -ErrorAction SilentlyContinue
    return $true
}

# On startup, rotate any already-oversized logs (preserves recent history in
# .1 instead of deleting it outright).
Invoke-LogRotation -Path $Log -MaxBytes $MaxLogBytes -Keep $Retention | Out-Null
Invoke-LogRotation -Path $ErrLog -MaxBytes $MaxErrBytes -Keep $Retention | Out-Null

# Lines worth surfacing into the compact errors-only sink.
$errPattern = 'Failed to create chat completions|Error occurred|HTTP error|invalid_tool_call|Invalid JSON format|Bad control character|Bad Request|does not support|ECONNRESET|fetch failed|ETIMEDOUT|socket hang'

Write-Host "[start-copilot-proxy] Logging to:   $Log"
Write-Host "[start-copilot-proxy] Errors-only:  $ErrLog"
Write-Host ("[start-copilot-proxy] Rotation:     {0} MB x {1} archives (errors {2} MB x {1})" -f [math]::Round($MaxLogBytes / 1MB), $Retention, [math]::Round($MaxErrBytes / 1MB))

# --- Launch + stream with inline rotation ----------------------------------
# The proxy (consola) writes normal logs to STDERR. With 2>&1 merging stderr
# into the pipeline, a 'Stop' preference would turn the first stderr line into
# a terminating NativeCommandError and kill the server on startup. Drop back to
# 'Continue' so stderr is captured as ordinary log output.
$ErrorActionPreference = 'Continue'
$script:lineCount = 0
$nl = [Environment]::NewLine
& node $ProxyEntry start --port $Port --verbose @ProxyArgs 2>&1 | ForEach-Object {
    $text = '{0:HH:mm:ss.fff} {1}' -f (Get-Date), $_
    # AppendAllText with a BOM-less UTF-8 encoder preserves box-drawing/emoji
    # bytes exactly (Add-Content in Windows PowerShell 5.1 would re-encode to
    # ANSI and mangle them).
    [System.IO.File]::AppendAllText($Log, $text + $nl, $utf8NoBom)
    if ($text -match $errPattern) {
        [System.IO.File]::AppendAllText($ErrLog, $text + $nl, $utf8NoBom)
    }
    $script:lineCount++
    if (($script:lineCount % $CheckEveryLines) -eq 0) {
        Invoke-LogRotation -Path $Log -MaxBytes $MaxLogBytes -Keep $Retention | Out-Null
        Invoke-LogRotation -Path $ErrLog -MaxBytes $MaxErrBytes -Keep $Retention | Out-Null
    }
}
