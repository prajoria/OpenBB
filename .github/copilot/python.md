---
applyTo: "**/*.py"
---

# Python Coding Standards

> **Single source of truth:** the detailed standards live in
> [`rules/DEVELOPMENT_RULES.md`](../../rules/DEVELOPMENT_RULES.md). This file is a
> short pointer for Copilot so the rules are not maintained in two places.

When writing or modifying Python in this repo, follow these sections of
`rules/DEVELOPMENT_RULES.md`:

| Topic | Section |
|---|---|
| Windows UTF-8 stdout reconfigure, `aiohttp` ban, PowerShell | §2 Windows-Specific Rules |
| Database connection, persistence strategies, `IF NOT EXISTS`, `FMP_CACHE_AUTO_CREATE_DB` | §3 Database Patterns |
| `Tools/` script structure + `sys.path` bootstrap | §4 Script Structure Pattern |
| FMP endpoint, `from`/`to` date params, API-key resolution, rate limiting | §5 FMP API Rules |
| Safe-default parsing, batch error isolation | §6 Parsing Rules / §5 Error Handling |
| `logging` over `print()` | §8 Logging |
| Repo-relative paths, no machine-specific absolutes | §13 Paths in Documentation |

Refer to that document for the authoritative, up-to-date detail.
