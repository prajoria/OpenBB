@echo off
REM Start Claude CLI for OpenBB development
REM Usage: start_claude_openbb.bat [focus_area]
REM Kept consistent with start_claude_openbb.ps1

REM The launcher lives at the repo root; %~dp0 is this script's directory.
set OPENBB_ROOT=%~dp0
cd /d "%OPENBB_ROOT%"

if "%1"=="api" (
    claude --dangerously-skip-permissions --append-system-prompt "OpenBB Platform API development (focus: openbb_platform/)"
) else if "%1"=="desktop" (
    claude --dangerously-skip-permissions --append-system-prompt "OpenBB Desktop app development (focus: desktop/)"
) else if "%1"=="cli" (
    claude --dangerously-skip-permissions --append-system-prompt "OpenBB CLI development (focus: cli/)"
) else if "%1"=="providers" (
    claude --dangerously-skip-permissions --append-system-prompt "OpenBB Platform providers and extensions (focus: openbb_platform/providers/, openbb_platform/extensions/)"
) else if "%1"=="deploy" (
    claude --dangerously-skip-permissions --append-system-prompt "OpenBB deployment and DevOps (focus: *.ps1, *.sh, docker*, *.yml, *.yaml)"
) else (
    claude --dangerously-skip-permissions --append-system-prompt "Working on OpenBB Platform development"
)