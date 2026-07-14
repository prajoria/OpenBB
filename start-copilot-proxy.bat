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
rem File logging + rotation: launch is delegated to start-copilot-proxy.ps1
rem (co-located with this .bat). That script owns the :4141 port guard, the
rem size-based log ROTATION (proxy.log -> .1 -> .2 ... so it can never balloon
rem again; a 40+ GB log was seen pre-rotation), the compact errors-only sink,
rem and UTF-8 output encoding so consola's box-drawing banner is not mojibake.
rem Keeping the logic in a .ps1 avoids the brittle quoting of a bat-embedded
rem PowerShell one-liner and makes rotation testable in isolation.
rem
rem Tunables (env vars, all optional):
rem   PROXY_MAX_LOG_MB   active proxy.log rotation threshold   (default 50)
rem   PROXY_MAX_ERR_MB   proxy-errors.log rotation threshold   (default 25)
rem   PROXY_LOG_KEEP     archives kept per log                 (default 5)
rem ---------------------------------------------------------------------------
set "LOG_DIR=%USERPROFILE%\.local\share\copilot-api"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not defined PROXY_MAX_LOG_MB set "PROXY_MAX_LOG_MB=50"
if not defined PROXY_MAX_ERR_MB set "PROXY_MAX_ERR_MB=25"
if not defined PROXY_LOG_KEEP set "PROXY_LOG_KEEP=5"

echo [start-copilot-proxy] Logging to: %LOG_DIR%\proxy.log
echo [start-copilot-proxy] COPILOT_API_FORCE_MODEL=%COPILOT_API_FORCE_MODEL%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-copilot-proxy.ps1" -Port 4141 -ProxyEntry "%PROXY_ENTRY%" -LogDir "%LOG_DIR%" -MaxLogMB %PROXY_MAX_LOG_MB% -MaxErrMB %PROXY_MAX_ERR_MB% -Retention %PROXY_LOG_KEEP% %*
