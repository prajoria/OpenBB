---
applyTo: "**/test*.py,**/tests/**"
---

# Testing Standards

## General Rules

- **Dry-run first** — Always run `--dry-run` before database writes when testing changes
- **Verify after write** — Run a COUNT/SELECT query after DB writes to confirm expected row counts
- **Idempotency check** — After any persistence logic change, verify that running the import twice produces the same final row count

## Target Database

Portfolio data lives in `openbb_fmp_cache_test`. The default `openbb_fmp_cache` is for general provider caching. Always verify which database you're connecting to.

## Skipped Symbols

These symbols are skipped in `fetch_position_history.py`:
`Cash`, `NSAV`, `MVVYF`, `EADSF`, `NXDR`, `NHX202764`, `NHX203309`
(cash positions, OTC/delisted stocks, CUSIPs without FMP data).

## Test Execution

```powershell
# Activate venv first
& ".venv_win\Scripts\Activate.ps1"

# Run fmp_cached tests
pytest openbb_platform/providers/fmp_cached/tests -v --tb=short

# Run with slow tests
pytest openbb_platform/providers/fmp_cached/tests -v --tb=short --runslow
```

## PowerShell Rules (for test commands)

- Use `;` to chain commands (NEVER `&&`)
- Use backtick for line continuation (not `\`)
