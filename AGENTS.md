# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [SYNC_CONCEPTS.md](https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Common bd Commands

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**

```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**

- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION v:2 profile:gh-primary hash:updated-2026-07-13 -->
## Coordination — GitHub Issues primary, bd fallback

**Authoritative protocol:** `docs/BEADS_HYGIENE.md` (post-migration).

**Two-line summary:**
1. **GitHub Issues are the source of truth.** Every unit of work has
   a GH Issue. Commit body cites its issue (`Closes #NN` for gh mode,
   `Refs bd-<id>` for bd fallback).
2. **Bd is a local coordination cache.** Optional. Configured via
   `bd github sync` — writes propagate to GH via `bd github sync
   --push-only`.

### Quick Reference — gh mode (primary)

```bash
gh issue list --state open --search "no:assignee -label:status:blocked"  # find work
gh issue view <#N>                                                        # view details
gh issue edit <#N> --add-assignee @me --add-label "status:in-progress"    # claim
gh issue close <#N> --reason completed --comment "shipped in <sha>"       # complete
```

### Quick Reference — bd fallback (if `gh auth status` fails or bd is preferred)

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
bd github sync --push-only  # Propagate bd writes to GH
```

### Rules

- Use GitHub Issues for ALL task tracking — do NOT use TodoWrite,
  TaskCreate, or markdown TODO lists. Bd optional as coordination
  cache.
- Every commit body cites its tracking issue (`Closes #NN` or
  `Refs bd-<id>`). Rule #10 in `.claude/commands/openbb-dev-cycle.md`.
- Use `docs/MEMORIES.md` for persistent knowledge — replaces
  `bd remember` as the canonical store (bd `remember` still works
  but doesn't survive DB loss / bootstrap collision).
- On fresh clone: if `.beads/` exists and origin has
  `refs/dolt/data`, run `bd bootstrap` (never `bd init`).

**Architecture in one line:** GitHub Issues are the durable
server-issued immutable ID space; bd is a local cache with
`external_ref = gh-<N>` linkage that catches up via
`bd github sync --pull-only`. Ghost-ID recovery available via
`git log --grep 'bd-<id>'` and `docs/BD_MIGRATION_PLAN.md` Appendix A.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below.
Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** — use `gh issue create` (or
   `bd create` in fallback)
2. **Run quality gates** (if code changed) — tests, linters, builds
3. **Update issue status** — close finished work (`gh issue close`
   or `bd close`), update in-progress items
4. **Propagate bd → GH if bd was used**:

   ```bash
   bd github sync --push-only    # push local bd writes to GH first
   ```

5. **Handle git/sync by active profile**:

   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```

6. **Hand off** — Summarize changes, validation, issue status, and
   any blocked sync/commit/push step

**Critical rules:**

- Explicit user or orchestrator instructions override this block.
- Do not commit, push, `bd dolt push`, or `bd github push` without
  clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact
  command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex; updated 2026-07-13 gh-primary -->
## Coordination — Codex

Use **GitHub Issues** as the source of truth for task tracking (post
2026-07-13 migration). Use Beads (`bd`) as a local coordination cache
when configured. See `docs/BEADS_HYGIENE.md` for the full protocol.

### Quick Reference — gh mode (primary)

```bash
gh issue list --state open --search "no:assignee -label:status:blocked"
gh issue view <#N>
gh issue edit <#N> --add-assignee @me --add-label "status:in-progress"
gh issue close <#N> --reason completed --comment "shipped in <sha>"
```

### Quick Reference — bd fallback (Codex)

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
bd github sync --push-only  # Propagate to GH
```

### Rules (Codex)

- Use GitHub Issues for ALL task tracking; bd as optional local cache.
- Every commit body cites its tracking issue (`Closes #<N>` for gh,
  `Refs bd-<id>` for bd fallback).
- Codex 0.129.0+ can load Beads context automatically through
  native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in `docs/MEMORIES.md`; do not use
  ad hoc memory files. `bd remember` still works but survives only
  as long as the bd DB.

**Architecture in one line:** GitHub Issues are the durable
server-issued immutable ID space; bd is a local cache with
`external_ref = gh-<N>` linkage. See `docs/BD_MIGRATION_PLAN.md`
for migration story + Appendix A ghost-ID inventory.
<!-- END BEADS CODEX SETUP -->
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See <https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md> for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
