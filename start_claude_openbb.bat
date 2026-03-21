@echo off
REM Start Claude CLI for OpenBB development
REM Usage: start_claude_openbb.bat [focus_area]

set OPENBB_ROOT=i:\masterswork\git\OpenBB
cd /d "%OPENBB_ROOT%"

if "%1"=="api" (
    claude --context "OpenBB Platform API development" --focus "openbb_platform/"
) else if "%1"=="desktop" (
    claude --context "OpenBB Desktop app development" --focus "desktop/"
) else if "%1"=="cli" (
    claude --context "OpenBB CLI development" --focus "cli/"
) else if "%1"=="providers" (
    claude --context "OpenBB Platform providers and extensions" --focus "openbb_platform/providers/,openbb_platform/extensions/"
) else if "%1"=="deploy" (
    claude --context "OpenBB deployment and DevOps" --focus "*.ps1,*.sh,docker*,*.yml,*.yaml"
) else (
    claude --context "Working on OpenBB Platform development"
)