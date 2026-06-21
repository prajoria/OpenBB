@echo off
setlocal
title Copilot API Proxy (:4141)

rem ---------------------------------------------------------------------------
rem Portable layout: this .bat lives in <root>\git\OpenBBTechnical\ and the
rem portable Node.js install lives in <root>\tools\nodejs\. %~dp0 expands to
rem "<root>\git\OpenBBTechnical\" (with trailing backslash), so ..\..\tools is
rem the portable tools root. The copilot-api proxy is vendored as a git
rem submodule at "%~dp0copilot-api".
rem ---------------------------------------------------------------------------
set "PORTABLE_ROOT=%~dp0..\.."
set "NODE_HOME=%PORTABLE_ROOT%\tools\nodejs"
set "NPM_CONFIG_PREFIX=%PORTABLE_ROOT%\tools\npm-global"
set "NPM_CONFIG_CACHE=%PORTABLE_ROOT%\tools\npm-cache"
set "PATH=%NODE_HOME%;%NPM_CONFIG_PREFIX%;%PATH%"

set "PROXY_DIR=%~dp0copilot-api"
set "PROXY_ENTRY=%PROXY_DIR%\dist\main.js"

rem ---------------------------------------------------------------------------
rem The submodule ships source only (dist/ is gitignored). On a fresh checkout
rem there is no build yet, so build it once via bun before first launch.
rem ---------------------------------------------------------------------------
if not exist "%PROXY_ENTRY%" (
    echo [start-copilot-proxy] No build found - building copilot-api submodule...
    pushd "%PROXY_DIR%"
    call npx --yes bun@latest install
    call npx --yes bun@latest run build
    popd
)
if not exist "%PROXY_ENTRY%" (
    echo [start-copilot-proxy] ERROR: build failed - %PROXY_ENTRY% still missing.
    echo [start-copilot-proxy] Run "git submodule update --init" then build copilot-api.
    exit /b 1
)

rem ---------------------------------------------------------------------------
rem File logging: tee stdout+stderr to a log file so we can inspect upstream
rem model decisions after the fact. The proxy itself has no built-in file
rem logger; we capture consola's verbose output here.
rem ---------------------------------------------------------------------------
set "LOG_DIR=%USERPROFILE%\.local\share\copilot-api"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\proxy.log"

echo [start-copilot-proxy] Logging to: %LOG_FILE%
echo [start-copilot-proxy] COPILOT_API_FORCE_MODEL=%COPILOT_API_FORCE_MODEL%

rem ---------------------------------------------------------------------------
rem Pre-flight: only one instance can bind :4141. Starting a second one makes
rem Node throw an unhandled EADDRINUSE 'error' event and exit 1 ("it crashes").
rem If a proxy is already listening, reuse it and exit cleanly instead of
rem crashing. Stop the existing process first if you want a fresh start.
rem
rem The port check, the node launch and the timestamped Tee logging all run in a
rem single PowerShell session so the guard and the server share one context.
rem --verbose makes consola emit request payloads and "Forcing model X -> Y".
rem ---------------------------------------------------------------------------
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 4141 -State Listen -ErrorAction SilentlyContinue) { Write-Host '[start-copilot-proxy] A proxy is already listening on :4141 - reusing it (not starting a second instance). Stop the existing process first for a fresh start.'; exit 0 }; & node '%PROXY_ENTRY%' start --port 4141 --verbose %* 2>&1 | ForEach-Object { '{0:HH:mm:ss.fff} {1}' -f (Get-Date), $_ } | Tee-Object -FilePath '%LOG_FILE%' -Append"
