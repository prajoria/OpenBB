---
applyTo: "**/*.py"
---

# Python Coding Standards

## Windows Encoding (MANDATORY)

Always add this near the top of any script that prints to stdout:

```python
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

Without this, non-ASCII characters crash with `UnicodeEncodeError` on Windows (cp1252).

## HTTP Requests

- **Do NOT use aiohttp** — it throws `asyncio.CancelledError` on Windows Python 3.12
- Use the `requests` library for synchronous HTTP instead
- Add 0.3–0.5 second delay between consecutive FMP API calls

## Database Patterns

- Always use shared infrastructure: `from openbb_fmp_cached.utils.database import DatabaseConfig`
- Never hard-code credentials — they come from `~/.openbb_platform/user_settings.json`
- Use `CREATE TABLE IF NOT EXISTS` — scripts must be runnable on fresh and existing databases
- Set `FMP_CACHE_AUTO_CREATE_DB=false` to skip 67-table creation overhead

### Persistence Strategies

- **DELETE + INSERT** — Full-snapshot data with no natural unique key (e.g., `Portfolio_Positions`)
- **INSERT ... ON DUPLICATE KEY UPDATE** — Data with a clear natural key (e.g., `ESPP_Plan`)
- **INSERT IGNORE** — Metadata/lookup tables (e.g., `Account_Owner`)

## Script Structure

All `Tools/` scripts follow this structure:

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

from openbb_fmp_cached.utils.database import DatabaseConfig

LOG = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="...")
    args = parser.parse_args()
    # ...

if __name__ == "__main__":
    main()
```

## FMP API Rules

- Endpoint: `https://financialmodelingprep.com/stable/historical-price-eod/full`
- Date params: use `from` and `to` (NOT `start_date`/`end_date` — FMP ignores those)
- Always add client-side date filtering as a safety net
- API key: `UserService.read_default_user_settings().credentials.fmp_api_key`

## Error Handling

- Parse functions should return safe defaults (`0.0`, `None`) rather than raising
- Never let a single symbol failure kill the entire batch — wrap in try/except
- Use Python `logging` module, not `print()`, for operational output

## Logging

```python
LOG.info("Processing %d symbols", len(symbols))
LOG.warning("Skipping %s: %s", symbol, error)
LOG.error("Failed to connect: %s", error)
```
