---
applyTo: "**/test*.py,**/tests/**"
---

# Testing Standards

> **Single source of truth:** the canonical testing rules live in
> [`rules/DEVELOPMENT_RULES.md`](../../rules/DEVELOPMENT_RULES.md) §7 (Testing),
> §3 (Target Database), and §2 (PowerShell). This file is a short pointer plus the
> Copilot-only command snippets so the guidance is not duplicated.

When writing or running tests, follow these sections of
`rules/DEVELOPMENT_RULES.md`:

| Topic | Section |
|---|---|
| Dry-run first, verify after write, idempotency check, skipped symbols | §7 Testing |
| Target database (`openbb_fmp_cache_test` vs `openbb_fmp_cache`) | §3 Database Patterns |
| PowerShell command chaining / line continuation | §2 Windows-Specific Rules |

## Test Execution

```powershell
# Activate the project venv first
& ".venv_win\Scripts\Activate.ps1"

# Run fmp_cached tests
pytest openbb_platform/providers/fmp_cached/tests -v --tb=short

# Run with slow tests
pytest openbb_platform/providers/fmp_cached/tests -v --tb=short --runslow
```
