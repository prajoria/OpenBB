# Collaboration Rules

> **Purpose:** Good practices for AI-assisted development sessions.
> Load this file plus the companion rules files at session startup.
>
> **Companion files (all in `rules/`):**
> - `PROJECT_CONTEXT.md` — Project overview, architecture, current state
> - `CODEBASE_MAP.md` — File inventory and navigation guide
> - `DEVELOPMENT_RULES.md` — Technical coding standards and patterns
> - `DOMAIN_KNOWLEDGE.md` — Finance & tax domain concepts

---

## 1. PII & Secrets Hygiene

- **Never commit PII** — Account numbers, owner names, family member names,
  file paths containing usernames, or any personally identifiable information
  must not appear in committed files.
- **Never commit credentials** — Database passwords, API keys, tokens, or
  connection strings belong in environment variables, `.env` files, or
  config files that are git-ignored.
- **Use a local-only context file** — Store environment-specific paths,
  credentials, and PII in `Tools/docs/CONTEXT_LOCAL.md` (git-ignored).
  Reference it from DESIGN.md with placeholder notation.
- **Sanitize examples** — When documenting CLI usage or SQL queries in
  committed files, use placeholder values like `<OWNER>`, `<DATA_DIR>`,
  `<DB_PASSWORD>`, `<ACCOUNT_NUMBER>`.
- **Review before commit** — Always check staged diffs for accidental
  inclusion of sensitive data before committing.

---

## 2. Documentation Standards

- **DESIGN.md** — Living architecture & context document (committed).
  Must contain only technical design, schemas, decisions, and changelog.
  No PII, no real file paths, no credentials.
- **CONTEXT_LOCAL.md** — Sensitive local context (git-ignored).
  Contains real paths, credentials, account details, owner names.
- **Per-tool docs** (e.g., `load_espp_plan.md`) — User-facing documentation
  for individual scripts.  Use placeholder values in examples.
- **Changelog entries** — Add to DESIGN.md section 10 for every session
  that modifies Tools/ code.

---

## 3. Code Practices

- **Shared infrastructure** — All DB-connected scripts must use
  `get_connection()` with `DatabaseConfig`.  Never hard-code credentials.
- **DEFAULT paths** — Scripts may define `DEFAULT_*_PATH` constants, but
  these should use generic names (not owner-specific).  The `--file` CLI
  argument overrides them.
- **Idempotent operations** — Prefer idempotent persistence strategies:
  - DELETE + INSERT for full-snapshot data (e.g., `Portfolio_Positions`)
  - INSERT ... ON DUPLICATE KEY UPDATE for data with natural keys (e.g., `ESPP_Plan`)
  - INSERT IGNORE for metadata/lookup tables (e.g., `Account_Owner`)
- **Error handling** — Parse functions should return safe defaults (0.0, None)
  for unparseable values rather than raising exceptions.

---

## 4. Git Workflow

- **Branch:** Work on `openbb_learning` branch.
- **Commit messages:** Use imperative mood, brief subject line, optional
  body with bullet points for multi-change commits.
- **.gitignore:** Ensure these patterns are present:
  - `*.sql` — Database dumps
  - `.venv_win/` — Windows virtual environment
  - `Tools/docs/CONTEXT_LOCAL.md` — Sensitive local context
  - `*.env` — Environment variable files
- **Never force-push** without explicit user confirmation.

---

## 5. Session Startup Checklist

When beginning a new AI collaboration session, load these files as context:

1. `rules/PROJECT_CONTEXT.md` — Project overview, architecture, state
2. `rules/CODEBASE_MAP.md` — File inventory and navigation
3. `rules/DEVELOPMENT_RULES.md` — Technical coding standards
4. `rules/COLLABORATION_RULES.md` — This file
5. `rules/DOMAIN_KNOWLEDGE.md` — Finance & tax domain concepts
6. `Tools/docs/DESIGN.md` — Schemas, design decisions, changelog
7. `Tools/docs/CONTEXT_LOCAL.md` — Local paths, credentials (git-ignored)
8. Current branch: `git branch --show-current`
9. Any specific task or issue to work on

### Quick Verification Commands

```powershell
# Activate venv
& ".venv_win\Scripts\Activate.ps1"

# Verify branch
git branch --show-current

# Verify DB connectivity
python -c "import pymysql; c=pymysql.connect(host='localhost',port=3306,user='fmp_user',password='fmp_password',database='openbb_fmp_cache_test'); print('DB OK'); c.close()"
```

---

## 6. Session Shutdown Checklist

Before ending a session:

1. Update `Tools/docs/DESIGN.md` changelog with work done
2. Update `Tools/docs/CONTEXT_LOCAL.md` with any new paths, accounts, or
   verified state changes
3. Review staged changes for PII leaks: `git diff --cached`
4. Commit and push with a descriptive message

---

## 7. Testing

- **Dry-run first** — Always run `--dry-run` before database writes when
  testing parser changes.
- **Verify after write** — Run a count/select query after DB writes to
  confirm expected row counts.
- **Re-import test** — After any persistence logic change, verify that
  running the import twice produces the same final row count (idempotency).
- **Target database** — Portfolio data is in `openbb_fmp_cache_test`,
  NOT the default `openbb_fmp_cache`.  Always verify which DB you're using.

---

## 8. Lessons Learned

| Session | Lesson |
|---------|--------|
| 2026-02-20 | aiohttp is broken on Windows Python 3.12 — always use `requests` for sync HTTP |
| 2026-02-20 | FMP `/full` endpoint ignores `start_date`/`end_date` — must use `from`/`to` |
| 2026-02-20 | Always add client-side date filtering after FMP API calls as a safety net |
| 2026-02-20 | One API call per symbol is simpler and faster than per-gap fetching |
| 2026-02-20 | `sys.stdout.reconfigure(encoding="utf-8")` is mandatory on Windows |
| 2026-02-20 | Set `FMP_CACHE_AUTO_CREATE_DB=false` to avoid 67-table creation overhead |
| 2026-02-20 | Never let a single symbol failure kill the entire batch — wrap in try/except |

---

*Last updated: 2026-02-20*
