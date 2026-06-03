---
applyTo: "**/*.md"
---

# Markdown Documentation Rules

## PII & Secrets

- Never include real account numbers, owner names, or file paths containing usernames
- Never include database passwords, API keys, or connection strings
- Use placeholder values: `<OWNER>`, `<DATA_DIR>`, `<DB_PASSWORD>`, `<ACCOUNT_NUMBER>`

## Changelog

- Add entries to `Tools/docs/DESIGN.md` section 10 for every session that modifies `Tools/` code
- Use date headings and bullet points

## Style

- Use tables for structured information
- Include code blocks with language identifiers
- Keep committed docs free of environment-specific paths
