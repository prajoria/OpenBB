# Collaboration Rules

> **Purpose:** Good practices for AI-assisted development sessions.
> Add this file as context before starting any collaboration session.

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

When beginning a new AI collaboration session, provide these as context:

1. `Tools/docs/DESIGN.md` — Architecture, schemas, changelog
2. `Tools/docs/CONTEXT_LOCAL.md` — Local paths, credentials, state
3. `rules/COLLABORATION_RULES.md` — This file
4. Current branch: `git branch --show-current`
5. Any specific task or issue to work on

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

---

*Last updated: 2026-02-20*
