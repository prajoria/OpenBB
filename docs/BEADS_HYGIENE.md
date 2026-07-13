# Beads + GitHub Issues Hygiene Protocol

**Status:** ACTIVE (shipped in Phase C of `docs/BD_MIGRATION_PLAN.md`)
**Owner:** Prashant Rajoria + Claude Code
**Last updated:** 2026-07-13

This is the day-to-day protocol for coordinating parallel work on
this repo. It supersedes bd-only rules in `CLAUDE.md`, `AGENTS.md`,
and `.github/copilot-instructions.md` for any conflict.

**Bottom line:** GitHub Issues are the source of truth. Bd is a
local coordination cache with fast dep-graph queries. Every commit
cites its tracking issue so a lost DB never loses the audit trail.

---

## The 6 rules

### 1. Every unit of work has a GitHub Issue

No exceptions. No side channels. `gh issue create` OR `bd create`
(bd auto-syncs to GH if configured, otherwise sync manually with
`bd github push <id>`).

- **GH-side** — the durable, immutable, server-issued ID (`#NN`)
- **Bd-side** — the local coordination cache (`OpenBBTechnical-<id>`)
  paired to GH via `external_ref: gh-<N>`

A commit without a tracking-issue reference is a red flag — either
file the issue or don't do the work.

### 2. Claim before you read code

Coordination is atomic against GitHub's assignee field:

```bash
gh issue edit <#N> --add-assignee @me --add-label "status:in-progress"
```

Run this *first*, before opening the editor. If you can't (someone
else has it), that's a 2-second cost, not a 40-minute one.

Bd-side equivalent (auto-syncs to GH if configured):

```bash
bd update <id> --claim   # sets assignee=you, status=in_progress
```

### 3. One issue → one branch → one PR → one merge

Branch name embeds the issue ID so `git branch` shows what's in
flight:

```bash
git checkout -b feat/<slug>-<issue-ref> origin/develop
# gh mode:  feat/aroon-family-gh-491
# bd mode:  feat/aroon-family-bd-b6k5
```

Commit body cites the issue so `git log --grep` rebuilds the trail
even if the DB is lost:

```
feat(techtrade): Aroon Up/Down/Osc vote

Closes #491                  # gh mode — GitHub auto-closes on merge
                             # (or) Refs bd-b6k5 — bd doesn't parse
                             #   commit bodies; manual `bd close` needed
```

PR title cites the issue; PR body has `Closes #<N>` in the summary.
Blast radius stays inside one PR.

### 4. Dependencies via GitHub task lists

GitHub renders `- [ ] #<N>` in an issue body as a native task list
with live status. The parent issue's body becomes the dep graph:

```markdown
## Children
- [ ] #492 M0 kickoff
- [ ] #493 P0 data-layer gap fill
- [ ] #494 P1 X-Ray + Events
```

Reading `bd ready` gives the same info via `gh issue list --search
"no:assignee -label:blocked"` for gh-mode users.

### 5. Free-write coordination; GitHub is the audit trail

Any authenticated actor can file, claim, close. Accountability
lives in GitHub's own history — no separate approval gate.

If someone claims and disappears, another dev unassigns after N
days of inactivity (label with `status:stale`, weekly sweep).

### 6. Cross-session memory lives in `docs/MEMORIES.md`

Not `bd remember`. Diff-reviewable, in-repo, survives bootstrap
collisions. See `docs/MEMORIES.md` for format + seeded entries.

Bd `remember` still works but is no longer the canonical store.

---

## Session lifecycle

### Session start

```bash
# 1. Refresh the local coord cache from remote
git fetch origin develop
bd dolt pull                    # if bd is present locally

# 2. Optional: pull recent GH changes into bd (only if bd github sync is configured)
export GITHUB_TOKEN=$(gh auth token)
bd github sync --pull-only --dry-run
bd github sync --pull-only

# 3. Find claimable work
gh issue list --repo prajoria/OpenBB \
  --state open \
  --search "no:assignee -label:status:blocked" \
  --limit 20
# OR (equivalent if bd is present):
bd ready
```

### During work

- Claim before coding (rule 2)
- Cite the issue in every commit body (rule 3)
- File new issues for anything discovered mid-implementation
- Use `docs/MEMORIES.md` for insights worth surviving compaction

### Session end

```bash
# 1. Close done issues (gh mode)
gh issue close <#N> --reason completed --comment "shipped in <sha>"

# 2. Push bd state to GH if bd was used
bd github sync --push-only

# 3. Push bd Dolt state to remote (with explicit approval per CLAUDE.md)
bd dolt push

# 4. Push git commits (with explicit approval per CLAUDE.md)
git push

# 5. Verify tracker + git are up-to-date
gh issue list --assignee @me --state open   # what's still in your queue
git status                                   # should show "up to date with origin"
```

---

## Parallel-dev contamination model

Two devs stepping on each other happens in exactly four ways.
Counters:

| # | Failure | Root cause | Counter |
|---|---|---|---|
| 1 | Both grab the same work | Skipped rule 2 | `gh issue edit --add-assignee @me` is atomic on the server side |
| 2 | Both edit same file | Skipped rule 3 | Branch name embeds issue; PR review catches overlap |
| 3 | Both push to shared coord DB | Skipped rule 6 of `BD_MIGRATION_PLAN.md` §3.3 | GH is source of truth; bd DB divergence recoverable via `bd github sync --pull-only` |
| 4 | Ghost IDs from bootstrap | Bd DB was replaced | **Eliminated** — GH IDs are server-issued and immutable; commit body citations recover the trail |

The 2026-07-11 bootstrap collision that motivated this whole
migration was failure mode #4. GitHub's immutable IDs eliminate
that class by construction.

---

## Migration state (as of 2026-07-13)

Per `docs/BD_MIGRATION_PLAN.md`:

- **Phase A complete** — bd github sync configured; 114 bd beads
  linked to GH issues via `external_ref = gh-<N>`; 2 GH internal
  duplicates deduped; 125 label backfills applied
- **Phase B in progress** — label taxonomy migrated (138 → ~90
  labels); type/priority/area labels now consistent
- **Phase C shipping** — this document, plus updates to CLAUDE.md,
  AGENTS.md, .github/copilot-instructions.md, and
  `docs/MEMORIES.md`

Future sessions can safely assume:
- Any GH issue with `external_ref` on the bd side is bd-mirrored
- Any GH issue without one is GH-only (bd doesn't have a coord
  entry for it) — file a bead if you're actively working on it,
  otherwise leave it GH-only

---

## Quick reference — the 3 modes from `/openbb-dev-cycle`

The `/openbb-dev-cycle` command auto-detects task-tracking mode
at runtime:

| Mode | When | Task mechanism |
|---|---|---|
| **gh** | `gh auth status` succeeds | `gh issue create/close/edit/list` — primary |
| **bd** | No gh auth, but `.beads/` present | `bd create/close/update` — fallback |
| **ephemeral** | Neither | `TaskCreate` — session-only |

See `.claude/commands/openbb-dev-cycle.md` for the full protocol.

---

## Anti-patterns

1. **Skipping rule 2 (claim)** — two devs land in the same code
2. **Skipping rule 3 (commit citation)** — DB loss = trail loss;
   the 2026-07-11 collision is the case study
3. **Editing `.beads/issues.jsonl` by hand** — it's a rebuildable
   export, silently overwritten on next `bd` write
4. **Bulk pushing bd → GH without pull-first** — creates
   duplicates; verified in Phase A on this repo
5. **Assuming `bd github sync` is bidirectional-safe by default**
   — pull-first is mandatory when GH and bd have diverged
6. **Using `bd remember` for insights that must survive
   bootstrap** — use `docs/MEMORIES.md` instead
7. **Filing a bead without a paired GH issue** (if bd github sync
   is configured, this happens automatically via the post-hook)
