# Task 2 Report: Idempotent Windows Workspace Development Setup

## Status

Implemented and committed issue #2098 on `build/workspace-dev-setup-gh-2098`.

- Subject: `build: add Workspace development setup`
- Commit body includes `Closes #2098` and the required Copilot co-author trailer.

## Files changed

### `scripts/setup_workspace_dev.ps1`

- Added strict, terminating-error PowerShell preflight behavior.
- Checks availability of `git`, `python`, and `uv`.
- Creates `.venv_portfolio` only when its interpreter is absent.
- Initializes only the three Workspace development submodules.
- Installs all required local packages as editables plus `cryptography`.
- Installs `portfolio_intel` in a separate `--no-deps` editable pass to avoid pip's conflicting-direct-reference error with its local `techtrade` dependency while retaining editable installs for both.
- Supports `-SkipPackageInstall` without skipping submodule, MySQL, or Workspace Bench validation.
- Requires a MySQL listener on local port 3306.
- Warns when root `.env` is absent but never creates or modifies it.
- Runs `uv sync --extra dev --extra live` in Workspace Bench.
- Supports opt-in Playwright Chromium installation through `-InstallBrowser`.

### `scripts/tests/Setup-WorkspaceDev.Tests.ps1`

Added seven Pester checks covering PowerShell syntax, public switches, explicit submodule paths, the package-install guard, the pip resolver workaround, MySQL and Workspace Bench operations, and the prohibition on creating or populating `.env`.

## Commands and results

### Required ownership checks

```powershell
python scripts/pi_claim.py --list-stale
gh issue list --assignee "@me" --state open --limit 20
gh pr list --author "@me" --state open --base portfolio
python scripts/pi_claim.py 2098 in-progress
python scripts/pi_claim.py 2098 heartbeat
```

Result: issue #2098 was claimed and heartbeats were posted during implementation and validation.

### TDD RED

```powershell
Invoke-Pester .\scripts\tests\Setup-WorkspaceDev.Tests.ps1 -PassThru
```

Result before implementation: 5 failed, 1 passed because the setup script did not exist.

A subsequent full setup attempt exposed a real pip resolver conflict between the top-level editable `techtrade` requirement and `portfolio_intel`'s local path dependency. A regression check was added first and observed failing before implementing the separate `portfolio_intel --no-deps` editable pass.

### Normal setup path

```powershell
.\scripts\setup_workspace_dev.ps1
```

Final result: exit code 0. The three submodules initialized, editable packages installed, MySQL was detected, Workspace Bench synchronized, and the success message was emitted. The only script warning was the expected missing `.env` warning.

### Idempotent skip path

```powershell
.\scripts\setup_workspace_dev.ps1 -SkipPackageInstall
```

Final result: exit code 0. Package installation was skipped while submodule initialization, MySQL validation, and Workspace Bench synchronization still ran. The only script warning was the expected missing `.env` warning.

### Automated tests and import smoke test

```powershell
Invoke-Pester .\scripts\tests\Setup-WorkspaceDev.Tests.ps1 -PassThru
.\.venv_portfolio\Scripts\python.exe -c "import openbb_core, openbb_platform_api, openbb_backtest, openbb_techtrade, openbb_portfolio, openbb_portfolio_intel, openbb_browser_test_harness, playwright; print('workspace imports: OK')"
git diff --check
```

Results:

- Pester: 7 passed, 0 failed.
- Import smoke test: `workspace imports: OK`.
- Whitespace validation: clean.
- The final verification matrix reran the normal path, skip path, Pester suite, import smoke test, and whitespace check in one command and exited 0.

## Self-review

- Confirmed no `.env` file is created or populated.
- Confirmed the hosted Workspace UI is not downloaded, configured, or run.
- Confirmed browser installation remains explicitly opt-in.
- Confirmed `-SkipPackageInstall` still performs every non-pip preflight.
- Confirmed submodule update is limited to the three issue-scoped paths.
- Confirmed all required packages import from `.venv_portfolio`.
- Confirmed the repository diff contains only the setup script and its focused Pester tests.
- Confirmed the commit contains both issue-closing syntax and the co-author trailer.

## Concerns

- `-InstallBrowser` was not executed because issue validation explicitly requested the normal no-browser path and the skip path; running it would download a Chromium binary. The Playwright Python dependency itself was installed and imported successfully.
- Validation requires a Windows host with `Get-NetTCPConnection`, plus locally available `git`, `python`, `uv`, network/package access, and a MySQL listener on port 3306. All were available on this machine.
