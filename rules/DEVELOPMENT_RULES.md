# Development Rules

> **Purpose:** Technical coding standards, patterns, and gotchas specific
> to this project.  Follow these when writing or modifying code.

---

## 1. Python Environment

- **Venv:** `.venv_win` — Windows-specific, project-local.
- **Activation:** `& ".venv_win\Scripts\Activate.ps1"` in PowerShell.
- **Python version:** 3.12.
- **Never use** `python -m venv` or `pip install` without activating first.
- **Never create** a sub-shell (`powershell -c "..."`) — use the persistent
  terminal session.

---

## 2. Windows-Specific Rules

### Encoding
Always add this near the top of any script that prints to stdout:
```python
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```
Without this, non-ASCII characters crash with `UnicodeEncodeError` on
Windows (cp1252 default encoding).

### Async / aiohttp
**Do NOT use aiohttp** for HTTP requests.  It throws
`asyncio.CancelledError` in `protocol.read()` on Windows Python 3.12.
Use the `requests` library for synchronous HTTP instead.

### PowerShell
- Use `;` to chain commands (NEVER `&&`).
- Use backtick `` ` `` for line continuation (not `\`).
- Prefer PowerShell cmdlets (`Get-ChildItem`, `Test-Path`) over Unix aliases.
- Use `$PWD` or `Get-Location` for current directory.

---

## 3. Database Patterns

### Connection
Always use the shared infrastructure:
```python
from openbb_fmp_cached.utils.database import DatabaseConfig
# ... then get_connection(database="openbb_fmp_cache_test")
```
Never hard-code credentials.  Credentials come from
`~/.openbb_platform/user_settings.json`.

### Persistence Strategies
Choose the right strategy based on data characteristics:

| Strategy | When to Use | Example |
|----------|-------------|---------|
| DELETE + INSERT | Full-snapshot data with no natural unique key | `Portfolio_Positions` |
| INSERT ... ON DUPLICATE KEY UPDATE | Data with a clear natural key | `ESPP_Plan`, `market_holidays` |
| INSERT IGNORE | Metadata/lookup tables | `Account_Owner` |

### Table Creation
Always use `CREATE TABLE IF NOT EXISTS`.  Scripts must be runnable
against both fresh and existing databases.

### Auto-Create Overhead
Set `FMP_CACHE_AUTO_CREATE_DB=false` in environment to skip the 67-table
creation check that runs on every `init_database()` call.  This is
critical for scripts that run many iterations.

### Target Database
Portfolio data lives in `openbb_fmp_cache_test`.  The default
`openbb_fmp_cache` is for general provider caching.  Always verify
which database you're connecting to.

---

## 4. Script Structure Pattern

All Tools/ scripts follow this structure:

```python
#!/usr/bin/env python3
"""Docstring with purpose and usage."""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import logging
from pathlib import Path

# --- sys.path bootstrap ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
for sub in [
    "openbb_platform/providers/fmp_cached",
    "openbb_platform/providers/fmp",
    "openbb_platform/core",
    "openbb_platform/platform",
]:
    p = str(PROJECT_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
# Add all extensions
for ext_dir in (PROJECT_ROOT / "openbb_platform" / "extensions").iterdir():
    if ext_dir.is_dir():
        p = str(ext_dir)
        if p not in sys.path:
            sys.path.insert(0, p)

# --- imports from project ---
from openbb_fmp_cached.utils.database import DatabaseConfig

# --- constants ---
LOG = logging.getLogger(__name__)

# --- functions ---
def main():
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("--database", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # ...

if __name__ == "__main__":
    main()
```

---

## 5. FMP API Rules

### Endpoint
Use the stable endpoint: `https://financialmodelingprep.com/stable/historical-price-eod/full`

### Date Parameters
- Use `from` and `to` (NOT `start_date` / `end_date`).
- FMP's `/full` endpoint **ignores** `start_date`/`end_date` params.
- Always add client-side date filtering as a safety net.

### API Key Resolution
```python
from openbb_core.app.service.user_service import UserService
creds = UserService.read_default_user_settings().credentials
api_key = getattr(creds, "fmp_api_key", None)
```

### Rate Limiting
Add a 0.3–0.5 second delay between consecutive API calls to avoid
hitting FMP rate limits.

### Error Handling
- Catch `requests.exceptions.RequestException` for network errors.
- Handle empty JSON responses (holidays, delisted symbols) gracefully.
- Never let a single symbol failure kill the entire batch.

---

## 6. Parsing Rules

### Currency Values
Handle all Fidelity formats: `$10,423.20`, `+$5,104.47`, `-$183.70`,
`($605.38)`, `--`.  Parentheses mean negative.

### Safe Defaults
Parse functions should return safe defaults (`0.0`, `None`) for
unparseable values rather than raising exceptions.

### HTML Parsing
- Fidelity uses ag-grid with **pinned-left** and **center** containers.
- Pinned-left is the authority for tickers and detail drawers.
- Center container does NOT contain drawer tables.
- Col-id attributes (`curVal`, `qty`, `cstBasShr`, etc.) may change
  across Fidelity DOM updates — treat as brittle.

---

## 7. Testing

### Dry-Run First
Always run `--dry-run` before database writes when testing changes.

### Verify After Write
Run a COUNT/SELECT query after DB writes to confirm expected row counts.

### Idempotency Check
After any persistence logic change, verify that running the import twice
produces the same final row count.

### Skip Symbols
Certain symbols are skipped in `fetch_position_history.py`:
`Cash`, `NSAV`, `MVVYF`, `EADSF`, `NXDR`, `NHX202764`, `NHX203309`
(cash positions, OTC/delisted stocks, CUSIDs without FMP data).

---

## 8. Logging

Use Python's `logging` module, not `print()`, for operational output:
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
LOG = logging.getLogger(__name__)
```

Log progress at INFO level for batch operations (per-symbol, row counts).
Log detailed diagnostics at DEBUG level.

---

## 9. Git Practices

- **Branch:** `openbb_learning` (never commit to `main`).
- **Commit messages:** Imperative mood, brief subject.
- **Review diffs** for PII before committing (see COLLABORATION_RULES.md).
- **Never force-push** without explicit user confirmation.
- `.gitignore` must include: `*.sql`, `.venv_win/`,
  `Tools/docs/CONTEXT_LOCAL.md`, `*.env`.

---

## 10. Code Style

- Follow existing code patterns in the file you're modifying.
- Use type hints for function signatures.
- Use dataclasses for structured data (see `ESPPPurchase`, `ShareLot`).
- Prefer f-strings over `.format()` or `%`.
- Keep functions focused — extract helpers for readability.
- Document non-obvious decisions with inline comments.

---

*Last updated: 2026-02-20*
