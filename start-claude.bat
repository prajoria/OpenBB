@echo off
setlocal
title Claude Code (via Copilot API)
set "ANTHROPIC_BASE_URL=http://127.0.0.1:4141"
set "ANTHROPIC_API_KEY=copilot-proxy"
set "CLAUDE_CODE_USE_POWERSHELL_TOOL=1"

rem ---------------------------------------------------------------------------
rem Portable layout: this .bat lives in <root>\git\OpenBBTechnical\ and the
rem portable Node.js + npm-global (with claude.cmd) live in <root>\tools\.
rem The copilot-api proxy is vendored as a git submodule next to this script
rem (%~dp0copilot-api). Everything resolved relative to %~dp0 so moving <root>
rem to another disk just works.
rem ---------------------------------------------------------------------------
set "PORTABLE_ROOT=%~dp0..\.."
set "NODE_HOME=%PORTABLE_ROOT%\tools\nodejs"
set "NPM_CONFIG_PREFIX=%PORTABLE_ROOT%\tools\npm-global"
set "NPM_CONFIG_CACHE=%PORTABLE_ROOT%\tools\npm-cache"
set "PATH=%NODE_HOME%;%NPM_CONFIG_PREFIX%;%USERPROFILE%\.local\bin;%PATH%"

rem ---------------------------------------------------------------------------
rem Single source of truth: the upstream Copilot model every request gets
rem rewritten to. Must be a public model id from the proxy's /v1/models list
rem (avoid *-internal and "(Internal only)" variants).
rem ---------------------------------------------------------------------------
set "CLAUDE_MODEL=claude-opus-4.7"

rem Exported to the proxy process so non-stream-translation.ts and the
rem chat-completions handler will override every incoming payload's "model"
rem field with this value.
set "COPILOT_API_FORCE_MODEL=%CLAUDE_MODEL%"

rem ---------------------------------------------------------------------------
rem Always restart the proxy so it picks up the current COPILOT_API_FORCE_MODEL
rem from this environment. Kill any process listening on :4141 first.
rem ---------------------------------------------------------------------------
echo [start-claude] Restarting Copilot proxy on :4141 with forced model %CLAUDE_MODEL%...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 4141 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
start "Copilot API Proxy (:4141)" cmd /k "%~dp0start-copilot-proxy.bat"

echo [start-claude] Waiting for proxy to come up...
powershell -NoProfile -Command "for ($i=0; $i -lt 30; $i++) { try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:4141/v1/models' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { Start-Sleep -Milliseconds 500 } }; exit 1"
if errorlevel 1 (
    echo [start-claude] ERROR: Proxy did not start within 15s. Check the proxy window for errors.
    exit /b 1
)

rem ---------------------------------------------------------------------------
rem Guard: refuse to launch if CLAUDE_MODEL is missing from the proxy's
rem advertised list, or is flagged as Internal-only in its display_name.
rem ---------------------------------------------------------------------------
powershell -NoProfile -Command "$m = (Invoke-WebRequest 'http://127.0.0.1:4141/v1/models' -UseBasicParsing).Content | ConvertFrom-Json; $hit = $m.data | Where-Object { $_.id -eq '%CLAUDE_MODEL%' }; if (-not $hit) { Write-Host '[start-claude] ERROR: model %CLAUDE_MODEL% not advertised by proxy.' -Fore Red; exit 2 }; if ($hit.id -match '-internal$' -or $hit.display_name -match 'Internal only') { Write-Host ('[start-claude] ERROR: %CLAUDE_MODEL% is Internal-only (' + $hit.display_name + '). Pick a public model.') -Fore Red; exit 3 }; Write-Host ('[start-claude] Proxy will force all requests -> ' + $hit.display_name) -Fore Green; exit 0"
if errorlevel 1 (
    echo [start-claude] Run Test-CopilotModels.ps1 to see usable models.
    exit /b 1
)

claude config set statusLine true
set "CLAUDE_CODE_PERMISSION_MODE=bypassPermissions"
claude --permission-mode bypassPermissions --model %CLAUDE_MODEL%
