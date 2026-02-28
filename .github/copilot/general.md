---
applyTo: "**"
---

# General Project Instructions

This is a **personal finance data platform** built on a fork of OpenBB (branch: `openbb_learning`).

## Key Architecture

- **`fmp_cached` provider** — MySQL-backed caching layer for FMP API data (67+ models)
- **`Tools/` scripts** — CLI utilities that parse brokerage exports and persist to MySQL
- **OpenBB platform** — Provides the router, provider interface, data models, and extension system

## Mandatory Pre-Collaboration Step

**Before starting any coding, analysis, or notebook work**, load these rules files
into your context. They contain critical standards, patterns, and domain knowledge:

1. `rules/COLLABORATION_RULES.md` — PII hygiene, git workflow, session checklists
2. `rules/DEVELOPMENT_RULES.md` — Technical coding standards and patterns
3. `rules/FINANCETOOLKIT_RULES.md` — FinanceToolkit library API, architecture, usage patterns

Read these rules files **first** in every new session. Do not proceed with code
changes until you have reviewed them.

## Additional Context Files

For deeper project context, read these as needed:

- `context/PROJECT_CONTEXT.md` — Project overview, architecture, current state
- `context/CODEBASE_MAP.md` — File inventory and navigation guide
- `context/DOMAIN_KNOWLEDGE.md` — Finance & tax domain concepts
- `context/openbb/ARCHITECTURE.md` — OpenBB platform architecture
- `Tools/docs/DESIGN.md` — Schemas, design decisions, changelog

## Technology Stack

- Python 3.12, Windows primary development
- MySQL 8 (localhost:3306) via PyMySQL
- Virtual environment: `.venv_win`
- HTTP: `requests` library (aiohttp is BROKEN on Windows Python 3.12)
- Data frames: pandas, HTML parsing: BeautifulSoup4
- API source: Financial Modeling Prep (FMP)

## Databases

- `openbb_fmp_cache` — Default provider cache (67+ tables)
- `openbb_fmp_cache_test` — Portfolio-specific data (positions, history, holidays)

**Important:** Most Tools/ scripts target `openbb_fmp_cache_test`, not the default.

## PII & Secrets Rules

- **Never commit PII** — account numbers, owner names, file paths with usernames
- **Never commit credentials** — DB passwords, API keys, tokens
- Use placeholder values (`<OWNER>`, `<DB_PASSWORD>`, `<ACCOUNT_NUMBER>`) in docs
- Sensitive local context lives in `Tools/docs/CONTEXT_LOCAL.md` (git-ignored)

## Output Style Rule

- Never use emoji characters in code string literals, code comments, logging messages, notebook print/output strings, or generated source snippets.
- Use plain ASCII text for status or progress messages (for example, `Added source directories` instead of emoji-prefixed text).
