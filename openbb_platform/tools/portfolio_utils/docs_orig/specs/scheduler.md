# scheduler/run_fetch_position_history.ps1 — Spec

| | |
|---|---|
| **Category** | Infra (scheduled task wrapper) |
| **Path** | `Tools/scheduler/run_fetch_position_history.ps1` |
| **Writes** | log files under `<repo>/logs/` |

## Purpose

PowerShell wrapper that runs `Tools/fetch_position_history.py` on a schedule
(e.g. Windows Task Scheduler), with portable path resolution and logging.

## Behavior

- Derives `$repoRoot` from `$PSScriptRoot` (`Tools/scheduler/` -> repo root) so
  the task is portable across machines/checkouts.
- Picks the Python interpreter in this order:
  `<repo>/.venv_win/Scripts/python.exe` -> `<repo>/venv/Scripts/python.exe` ->
  `py` launcher fallback.
- Sets `FMP_CACHE_AUTO_CREATE_DB=false` and `PYTHONIOENCODING=utf-8`.
- Runs `fetch_position_history.py --database openbb_fmp_cache_test --years 5`.
- Tees all output to `<repo>/logs/fetch_position_history_<yyyy-MM-dd>.log` and
  exits with the child process exit code.

## Usage

```powershell
# Manual
powershell -ExecutionPolicy Bypass -File Tools\scheduler\run_fetch_position_history.ps1

# Or register as a Windows Scheduled Task pointing at this script.
```

## Notes

- `$ErrorActionPreference = "Stop"` — fail fast.
- Creates the `logs/` directory if missing.
- The hard-coded `--database openbb_fmp_cache_test --years 5` is the scheduled
  default; edit the script to change the cadence target.
