# bd → GitHub Issues Migration Plan (v2)

**Status:** DRAFT — awaiting approval
**Date filed:** 2026-07-12
**Owner:** Prashant Rajoria (with Claude Code assistance)
**Supersedes:** v1 of this doc (commit `bf273c57d`, obsolete — v1 hand-rolled a pairing protocol without checking that `bd github sync` exists natively).
**Companion doc (planned, Phase C):** `docs/BEADS_HYGIENE.md`

---

## 1. Why this plan exists

Since the 2026-07-11 bd bootstrap collision, the local coordination
tracker (bd) and the durable audit trail (git commit messages) have
drifted apart. **80 of the 81 unique bd IDs referenced in commits
since 2026-06-01 no longer resolve as their own beads in the current
bd DB.** Only `bd-vwl → OpenBBTechnical-vwl` survives. Code work
shipped and is durable in git history; the coordination trail is
gone.

The failure mode this creates for parallel developers:

- Commit messages and design docs reference bd IDs that no longer
  resolve — a new agent reading `bd-luy Steps 1–4 shipped` in a
  commit runs `bd show bd-luy` and gets "no issue found." Cannot
  tell whether the work is real, half-done, or fabricated.
- `bd ready` cannot show truthful state because the ID space it
  operates on doesn't match the ID space the codebase records.
- Two clones of the repo can end up with completely independent bd
  DBs if one is `bd init` and the other is `bd bootstrap` from an
  existing remote — this is what caused the 2026-07-11 collision.

Root cause: **bd's DB is remote-first but locally-writeable**,
with no immutable ID space and no per-clone reconciliation
discipline. GitHub Issues, by contrast, provides server-issued
immutable IDs that survive bootstrap collisions by construction.

---

## 2. The critical discovery — bd has native GitHub sync

Verified 2026-07-12 via `bd github --help`:

```
Commands for syncing issues between beads and GitHub.

Available Commands:
  pull        Pull specific items from GitHub
  push        Push specific beads to GitHub
  repos       List accessible GitHub repositories
  status      Show GitHub sync status
  sync        Sync issues with GitHub (bidirectional by default)

Configuration:
  github.token / GITHUB_TOKEN
  github.owner / GITHUB_OWNER
  github.repo / GITHUB_REPO
```

**This has never been configured on this repo** (`bd github status`
returns `❌ Not configured`). The scaffolding is in `.beads/config.yaml`
as commented-out placeholders but was never turned on.

**Verified capabilities** (via `--dry-run` probes on 2026-07-12):

| Capability | Verified? | Detail |
|---|---|---|
| Push a single bead to GH | ✅ | `bd github push <bead-id> --dry-run` shows "Would create in GitHub: <title>" |
| Push all beads to GH | ✅ | `bd github sync --dry-run --push-only` reports it would create **852 issues** (all statuses, not just open) |
| Pull a specific GH issue into bd | ✅ | `bd github pull <#NN> --dry-run` shows "Would import" |
| Bidirectional sync | ✅ | Default `bd github sync` mode; conflict resolution via `--prefer-github`/`--prefer-local`/`--prefer-newer` |
| Auth via env var | ✅ | `export GITHUB_TOKEN=$(gh auth token)` works if the `gh` CLI is signed in |
| Selective sync by bead ID | ✅ | `--issues bd-a,bd-b,...` and `--parent <epic>` flags |

**Verified risks:**

- **Blind push would create 852 duplicates.** The bd DB has 852
  issues; GitHub already has 488 (and rising). A naive
  `bd github sync --push-only` would create 852 new GH issues,
  most of them duplicates of things already in GH, plus 111 closed
  beads that shouldn't be re-filed at all. **Pull-first is
  mandatory.**
- **`bd github sync` default is push+pull**, not pull-only. First
  run must explicitly use `--pull-only`.
- **Label and status mapping is not yet verified** — how does bd
  map its ~30 labels to GitHub's 114? Does it create new GitHub
  labels? Preserve existing ones? Needs testing.
- **Duplicate detection** — how does `bd github pull` decide
  whether an incoming GH issue is a new bead vs already-linked?
  Needs testing.

This v2 plan is designed to answer those unknowns via cautious
staged experiments before any bulk operation.

---

## 3. Target state

- **bd** = local coordination + query layer (`bd ready`, dep graph,
  claim/close, memories).
- **GitHub Issues** = durable, globally-unique ID space and the
  reviewer-facing surface.
- **`bd github sync`** = the one mechanism that keeps them
  reconciled. Run automatically (via hook or CI) so no manual
  `gh issue` calls are needed.
- **Cross-session memory** = migrate `bd remember` entries into
  `docs/MEMORIES.md` (a diff-reviewable in-repo file) for the
  content that must survive bd DB loss.
- **`.beads/config.yaml`** = commit the non-secret parts
  (`github.owner`, `github.repo`) so every clone inherits the
  configuration. Token stays in `GITHUB_TOKEN` env var (never in
  repo).

Parallel-dev contamination model at the target state:

| Failure mode | Mitigation |
|---|---|
| Both grab the same work | `bd update --claim` syncs to GH assignee immediately via post-hook |
| Both edit same file | Branch name embeds issue number; enforced by convention + PR review |
| Both push to a shared coord DB | `bd github sync` conflict resolution + `refs/dolt/data` sync in parallel |
| Ghost IDs from bootstrap | **Eliminated** — if bd DB is lost, `bd github sync --pull-only` rebuilds it from GH's immutable IDs |
| Stale in-progress epics | `bd list --status in_progress` at session close + GH's own task-list rendering on parent issues |

---

## 4. Phase A — verify + configure + pull-first

**Goal:** learn exactly how `bd github sync` behaves against this
repo's specific state (852 beads + 488 GH issues + 114 GH labels)
before any bulk push. All actions except the config commit are
inspectable via `--dry-run` first.

### A1 — Configure bd github

**Verified 2026-07-12:** `bd config set github.owner` and
`bd config set github.repo` write to the **bd Dolt database**,
not to `.beads/config.yaml`. This means the config **does NOT
propagate to other clones via git.** For the config to be shared
across all clones, we must add it manually to
`.beads/config.yaml` and commit that file.

Two-part step:

```bash
# Local session (temporary, this shell only)
export GITHUB_TOKEN=$(gh auth token)

# Persistent, shared across all clones (via commit in A7)
# Manually edit .beads/config.yaml to add:
#   github.owner: "prajoria"
#   github.repo: "OpenBB"
# (These live under the existing "sync.remote:" line, using the same
#  top-level-key-with-colon style — check config.yaml for actual syntax)

# Verify
bd github status   # expect "✓ Configured"
```

The token stays in `GITHUB_TOKEN` env var only — **never in the
committed config file.**

### A2 — Test pull-first on a single known GH issue

```bash
bd github pull 488 --dry-run    # #488 = the retroactive bd-qy83.1.12 mirror I filed earlier
```

**Expect:** "Would import: 488 - [bd] Dolt dep-schema missing depends_on_id column"

Then execute for real:

```bash
bd github pull 488
bd list --status closed | grep -i "dolt"   # should now show a bead pulled from #488
```

**Observe:**
- Does bd create a new bead ID or link to the existing
  `OpenBBTechnical-qy83.1.12`? (Critical — determines duplicate
  behavior.)
- Does bd preserve the GH issue body verbatim? Labels?
  Closed-status?

If the observation shows a duplicate is created (fresh bead ID
rather than linking to `qy83.1.12`), **stop Phase A** and file
that as a bd upstream issue. Migration plan then needs a
manual reconciliation step for pre-existing GH↔bd matches.

### A3 — Pull the full existing GH issue set

Once A2 confirms sane pull behavior:

```bash
bd github sync --pull-only --dry-run   # count how many GH issues would import
bd github sync --pull-only              # execute
```

**Expected outcome:** all 488 existing GH issues become beads in the
bd DB. Some will duplicate existing beads (which is why A2 mattered);
we deal with duplicates in A4.

### A4 — Reconcile duplicates

Run a manual sweep:

```bash
bd list --status open --json | jq '.[] | select(.title | test("^\\[bd\\]"))' | head
# any beads titled "[bd] ..." are likely GH-pulled versions of existing beads
```

For each duplicate pair (bd-native + gh-pulled), decide which is
authoritative and `bd close` the other with a reason pointing at
the survivor. This is the manual pass the v1 plan tried to avoid;
turns out it's unavoidable when merging two ID spaces.

### A5 — Selective push: the 6 QC-R1 epics + trend-family follow-ups

Only these specific beads get pushed in Phase A; the full 852-bead
push waits until Phase B has cleaned the DB.

```bash
# Verify each dry-run before executing
bd github push OpenBBTechnical-0qu --dry-run
bd github push OpenBBTechnical-4x3 --dry-run
bd github push OpenBBTechnical-8y3 --dry-run
bd github push OpenBBTechnical-97o --dry-run
bd github push OpenBBTechnical-cgh --dry-run
bd github push OpenBBTechnical-k4k --dry-run

# Then execute
bd github push OpenBBTechnical-0qu OpenBBTechnical-4x3 OpenBBTechnical-8y3 OpenBBTechnical-97o OpenBBTechnical-cgh OpenBBTechnical-k4k
```

Then close each on GH with a reason pointing at the child PRs
(per `qc-r1-cluster-jw1o-progress` memory, all children shipped).

### A6 — File the 2 genuinely-open trend-family beads

```bash
# 1. Create the PIT XLK universe builder bead (replaces ghost bd-69px)
bd create --title="Point-in-time XLK universe builder in fmp_cached" \
  --description="See docs/superpowers/specs/2026-07-10-ensemble-lift-validation-design.md §5.6. Blocks R1 IC gate acceptance runs." \
  --type=feature --priority=1

# Note the new bead ID (e.g. OpenBBTechnical-xxx)

# 2. Create the R1 IC gate bead, blocked by the above
bd create --title="R1 IC gate implementation" \
  --description="See docs/superpowers/specs/2026-07-10-ensemble-lift-validation-design.md §5. Paired-spread acceptance test on d_t = r_ext − r_base." \
  --type=feature --priority=2

bd dep add <r1-ic-gate-id> --blocked-by <pit-universe-id>

# 3. Push both to GH
bd github push <pit-universe-id> <r1-ic-gate-id>
```

### A7 — Commit `.beads/config.yaml` with the manual github.owner/repo edit

Once Phase A is stable:

```bash
# Edit .beads/config.yaml manually per A1 (or verify it was already edited)
git add .beads/config.yaml
git diff --cached                       # verify ONLY github.owner + github.repo lines added
git commit -m "chore(beads): enable bd github sync (owner+repo, no secrets)"
```

**Token stays in `GITHUB_TOKEN` env var or a per-machine secret store —
never committed.**

**Reminder:** `bd config set` writes to the bd DB, not this file.
For the config to be shared across all clones, the yaml edit is
the mechanism.

### A8 — Publish

```bash
bd dolt push   # publish bd state changes (with explicit approval)
git push       # publish config commit (with explicit approval)
```

---

## 5. Phase B — GitHub Issues audit + bulk push

**Goal:** bring GH into full alignment with bd. Then set up
ongoing sync.

**Blocked by:** Phase A completion.

### B1 — Read-only triage of all 488 existing GH issues

Produce a table listing every open GH issue with: `#`, title,
current labels, days-since-update, assignee, proposed action ∈
{close, update-labels, add-blocked-by, split, leave}. Estimated 45 min.

Reviewer approves batch actions async; batch execution follows.

### B2 — Label taxonomy consolidation

114 existing GH labels is likely more than needed. Produce a
proposed target set (~30-40 labels), map each existing label to
keep/rename/merge/delete, execute via `gh api`. Estimated 60 min.

### B3 — Bulk push remaining bd beads

After Phase A's pull + reconcile + label consolidation:

```bash
bd github sync --dry-run --push-only | tee /tmp/push-preview.txt
wc -l /tmp/push-preview.txt   # sanity check the count
bd github sync --push-only     # execute
```

Expected count: ~700-750 (down from 852 after de-duping in A4
and closing obsolete ones in Phase A steps).

### B4 — First bidirectional sync

```bash
bd github sync --dry-run       # verify nothing surprising
bd github sync                  # execute
```

From this point forward, every bd write + `bd github sync`
propagates to GH.

---

## 6. Phase C — automate + document

**Goal:** make it impossible to forget the sync.

**Blocked by:** Phase B completion.

### C1 — Write `docs/BEADS_HYGIENE.md`

Simple rules, grounded in bd github sync's actual behavior:

1. Every bd write is followed by `bd github sync` (manually or via
   hook — see C2).
2. Every commit references its bead (`bd-<id>`) OR its GH issue
   (`#NN`) in the subject or body.
3. On fresh clone: run `bd bootstrap` (never `bd init`) if a remote
   Dolt exists, then `bd github sync --pull-only` to import any
   drift.
4. On session close: `bd github sync` before `bd dolt push` before
   `git push`.
5. Cross-session memory lives in `docs/MEMORIES.md` (in-repo,
   diff-reviewable), not `bd remember` (in-DB, lost on bootstrap
   collision).
6. On any conflict: `bd github sync --prefer-newer` is the safe
   default. `--prefer-github` if bd was locally corrupted.
   `--prefer-local` if GH was mass-edited externally.

### C2 — Post-hook for auto-sync (optional)

`.beads/hooks/post-update.sh`:

```bash
#!/usr/bin/env bash
# Runs after any bd write; syncs to GH in the background.
bd github sync --push-only --quiet &
```

Wire via `bd config set hooks.post-update .beads/hooks/post-update.sh`.

### C3 — `docs/MEMORIES.md` seed

Migrate existing `bd remember` entries. Current entries (from
`bd config list | grep memory`):

- `bootstrap-outcome-2026-07-11`
- `portfolio-intel-plan-shipped`
- `pr470-sync-trading_technicals-2026-07-11`
- `qc-r1-cluster-jw1o-progress`

Ongoing: after Phase C ships, `bd remember` still works but its
canonical mirror is `docs/MEMORIES.md`. New memories go in both
initially; bd `remember` may deprecate on a later cycle.

### C4 — CLAUDE.md update

Add a `## Coordination` section that:

- Cites `docs/BEADS_HYGIENE.md` as the authoritative protocol.
- Removes the "Beads Workflow Context" block's rules that no
  longer apply (e.g., the ghost-ID recovery advice).
- Preserves the conservative git profile.

---

## 7. Rollback plan

- **A1-A2:** env var + config unset, no state changes.
- **A3 (pull):** `bd list --status open --json > /tmp/pre-pull.json`
  before running; if pull creates unexpected duplicates, restore
  via `bd import /tmp/pre-pull.json` (JSONL round-trip).
- **A5-A6:** individual `bd close --reason=rollback` + `gh issue close`
  on the specific new issues created.
- **A7 config commit:** single revert.
- **Phase B:** batch-execution recorded in the triage table; reverse
  batch script inverts label changes.
- **Phase C:** hooks are opt-in; docs are one revert.

No irreversible operations at any step. Every bulk operation has
a `--dry-run` first.

---

## 8. What v1 got wrong (for the record)

The v1 plan (commit `bf273c57d`) hand-rolled a manual pairing
protocol (custom `bd-mirror` label, `bd-id:<id>` per-bead labels,
manual `gh issue create` after every `bd close`, template body
strings, close-ordering rules). All of that reimplements what
`bd github sync` does natively.

**Root cause of the v1 mistake:** did not verify existing bd
capabilities before designing a solution. Assumed bd was
GH-agnostic based on: (a) no `bd-mirror` labels existed on the
repo, (b) no git history of GH sync setup, (c) the CLAUDE.md
"Beads Workflow Context" block does not mention `bd github`.

**Lesson generalizable:** before proposing tooling built on top of
X, run `X --help` to see what X already does. This is a specific
instance of the "R7: don't write mocks before you've made one live
call" pattern from the Analysis testing rules.

The retroactive fix I did earlier (`bd close bd-qy83.1.12` +
manual `gh issue create #488` + custom labels) is preserved but
labeled as v1-style. When `bd github sync --pull-only` runs on #488
in A2, we'll see how bd handles a GH issue that was created by
hand outside the sync flow — an accidental test case for the
migration.

---

## Appendix A — Ghost ID inventory (unchanged from v1)

**Source:** `git log --all --oneline --grep='bd-[a-z0-9]\{3\}'
--since='2026-06-01'`, deduplicated. **Total:** 81 unique bd IDs.
**Resolved in bd DB today:** 1 (`bd-vwl`). **Ghost:** 80.

Complete list:

```
bd-0bp1     bd-2k86     bd-8sq      bd-c4h      bd-kpg      bd-t7p2
bd-0h2.10   bd-3cf      bd-8tl      bd-dt1      bd-lef      bd-tnz
bd-0h2.11   bd-3ch      bd-90e      bd-e3v8     bd-luy      bd-tzm
bd-0h2.12   bd-3ka      bd-9bh      bd-fis      bd-lw3      bd-udq
bd-0h2.14   bd-3qo      bd-9loj     bd-gv1e     bd-lyzk     bd-uolr
bd-0h2.16   bd-3xq      bd-9nd.10   bd-gzf      bd-n3sf     bd-z7f
bd-0h2.9    bd-4d0      bd-9nd.11   bd-hpxh     bd-o4q      bd-znw
bd-0ru2     bd-5in      bd-9nd.12   bd-hyzu     bd-or5      bd-zuw
bd-0uh      bd-6atb     bd-9nd.8    bd-ijq      bd-ph0
bd-209      bd-78w      bd-9nd.9    bd-isvv     bd-qu2h
bd-250      bd-7ct      bd-9zb      bd-jt4r     bd-r9m
bd-2650     bd-85w      bd-bl57     bd-kbtx     bd-ri3
bd-29n      bd-8j9      bd-c2fr     bd-kh08     bd-sqf
```

Additional ghost IDs referenced elsewhere (from the ensemble-lift
spec + prior status summaries):

```
bd-b6k5     bd-7gwh     bd-gj2k     bd-8332     bd-1lgd
bd-j7mw     bd-d4r3     bd-a4cl     bd-69px     bd-w1g7
bd-hpxh     bd-tik      bd-40v      bd-z43      bd-alj
```

Note: with `bd github sync` in place, these ghost IDs remain
ghost — the coordination trail for the shipped work is gone
regardless of the tool we use to coordinate future work. The
value of documenting them here is (a) the historical record and
(b) the recovery signal (if a future migration ever needs to
reconstruct the pre-2026-07-11 bd state, the git history plus
this list is the reconstruction basis).

The v1 plan's Phase A step "file an aggregate `[bd-archive]` GH
issue" is preserved as an option for A5/A6 if you want the ghost
list mirrored to GH. Not strictly necessary once bd github sync
runs on the live DB.

---

## Approval checklist

Reviewer signs off on:

- [ ] Phase A steps A1-A2 (config + single-issue pull test) —
  safe to run mid-session, no bulk operations
- [ ] Phase A step A3 (full pull) requires explicit go-ahead after
  A2 observations
- [ ] Phase A step A4 (reconcile duplicates) is a manual pass —
  approve the approach (bd close the loser, note the survivor)
- [ ] Phase A step A5-A6 (selective push of 6 QC epics + 2 new
  trend-family beads) requires explicit go-ahead per batch
- [ ] Phase A step A7 (`.beads/config.yaml` commit) — verify only
  non-secret keys added (owner+repo, no token)
- [ ] Phase B and Phase C scope as described
- [ ] Rollback plan (§7) suffices for each step

**Bottom line:** v2 is much less code than v1, because `bd github
sync` does most of the mechanics. The work is the *care*: pull
before push, dry-run before bulk, reconcile duplicates manually,
consolidate labels once. Then it self-maintains.
