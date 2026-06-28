# Vendored Skills

This directory holds **project-scoped skills** discovered by VS Code Copilot and
Claude Code (each subfolder has a `SKILL.md` with YAML frontmatter).

## Why these live in the repo

Most folders here are **mirrored from user scope** (`~/.agents/skills/`) so the
skill set travels with the repository — clone it on a new machine and the skills
are immediately available without re-installing plugins or syncing `~/.agents`.

| Folder(s) | Origin |
|-----------|--------|
| `beads/` | Project-specific (Beads task-tracker workflow) |
| `openbb-dev-cycle/` | Project-specific (converted from `.claude/commands/openbb-dev-cycle.md`) |
| everything else | Vendored snapshot of `~/.agents/skills/` (Claude plugin + community skills) |

Plugin **commands** are vendored separately under `.claude/commands/`.

## Refreshing the snapshot

These are static copies. To re-sync after updating skills in user scope, re-copy
the changed folders from `~/.agents/skills/` (skip the two project-specific ones
above). The vendored skills are safe to delete individually if unwanted.
