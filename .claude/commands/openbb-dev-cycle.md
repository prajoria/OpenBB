# OpenBB Feature Development Cycle

A disciplined, gated workflow for developing features in the OpenBB platform.
Each phase must complete before the next begins. No shortcuts.

## Overview

This command enforces an 8-phase development lifecycle that chains together
brainstorming, planning, isolation, TDD implementation, quality checks, **QC
review of your own branch via `/openbb-qualitycontrol`**, review-issue creation
+ fix loop, and integration.

**Task tracking is GitHub-Issues-first**, with **bd** as a fallback when
`gh` is not authenticated, and `TaskCreate` as a last-resort ephemeral mode
when neither is available. See §"Task tracking mode" below.

**Key change vs prior version:**
- Primary task tracker is now **GitHub Issues**, not bd. The 2026-07 bd
  bootstrap collision showed that a local-only coordination layer is fragile
  under parallel work. GitHub's server-issued immutable IDs eliminate the
  ghost-ID failure mode by construction. See `docs/BD_MIGRATION_PLAN.md`.
- bd remains in the repo for `bd ready` (fast dep-graph queries), memories,
  and offline coordination — but the dev-cycle command **does not write to
  bd in gh mode**. Bd catches up via `bd github sync --pull-only` when
  someone runs it.
- Phase 6 remains the mandatory self-QC-review loop using
  `/openbb-qualitycontrol` in `branch` mode.

---

## Task tracking mode (auto-detected at each tool call)

Before Phase 1 — and at any tool call that needs to file/claim/close a
tracking issue — probe the environment and select a mode. **The result
does NOT persist across tool calls** (each Bash/PowerShell invocation
is a fresh process). Either (a) resolve the mode inline in each command,
or (b) record the mode in your first response and keep referring to it
explicitly in subsequent tool calls.

**Bash (macOS / Linux / Git Bash on Windows):**

```bash
if gh auth status >/dev/null 2>&1; then
  TASK_MODE=gh
  echo "OK Task mode: gh (GitHub Issues primary)"
elif [ -d .beads ] && command -v bd >/dev/null 2>&1; then
  TASK_MODE=bd
  echo "WARN gh CLI not authenticated; falling back to bd (local coord only)"
  echo "     Reconcile later via: bd github sync --pull-only"
else
  TASK_MODE=ephemeral
  echo "WARN Neither gh nor bd available; using TaskCreate (session-only)"
fi
echo "TASK_MODE=$TASK_MODE"
```

**PowerShell (Windows-primary shell for this repo per CLAUDE.md):**

```powershell
$TASK_MODE = if ((gh auth status 2>$null; $LASTEXITCODE) -eq 0) {
  Write-Host "OK Task mode: gh (GitHub Issues primary)"
  'gh'
} elseif ((Test-Path .beads) -and (Get-Command bd -ErrorAction SilentlyContinue)) {
  Write-Host "WARN gh CLI not authenticated; falling back to bd"
  Write-Host "     Reconcile later via: bd github sync --pull-only"
  'bd'
} else {
  Write-Host "WARN Neither gh nor bd available; using TaskCreate (session-only)"
  'ephemeral'
}
Write-Host "TASK_MODE=$TASK_MODE"
```

The rest of this document uses `<TASK: create ...>`, `<TASK: claim ...>`,
`<TASK: close ...>` etc. as **mode-neutral placeholders**. See
§"Task command translations" at the bottom for the concrete command per
mode.

### How to use `<TASK: ...>` placeholders

These are **not literal shell syntax** — they are template markers. Before
running any tool call containing `<TASK: ...>`, you MUST resolve the
placeholder to the concrete command from the translations table below,
using the currently active mode.

Example: if the doc says `<TASK: create title="foo" type=bug priority=P1>`
and the mode is `gh`, resolve to:

```
gh issue create --repo prajoria/OpenBB --title "foo" --label type:bug --label priority:P1
```

Never paste `<TASK: ...>` verbatim into a shell or tool call — it will fail.

**Rule of thumb:** if you're on a machine that can `gh pr create`, you can
`gh issue create`. gh mode is available in 99% of dev environments.

---

## Phase 1: Design & Brainstorming

**Gate:** Design spec approved by user

1. **Invoke `superpowers:brainstorming`** to explore the feature request
   - Understand purpose, constraints, success criteria
   - Propose 2-3 approaches with trade-offs and a recommendation
   - Use **Context7** (`resolve-library-id` → `query-docs`) to pull up-to-date
     docs for any library under consideration
   - Use `feature-dev:code-explorer` to understand existing codebase patterns
2. **Present design** section by section, get user approval after each
3. **Write design spec** to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
4. **Commit** the design spec (only if user authorizes — conservative profile)

**Checklist before proceeding:**
- [ ] Design spec written
- [ ] User has explicitly approved the design
- [ ] No open questions or TBDs in the spec

---

## Phase 2: Planning

**Gate:** Implementation plan approved by user

1. **Invoke `superpowers:writing-plans`** to turn the approved design into a
   step-by-step implementation plan
   - Identify all files to create/modify
   - Define dependencies between steps
   - Set review checkpoints (at least one per 3 steps)
2. **File tracking issues** for each deliverable:
   - `<TASK: create title="<step summary>" body="<what and why>" type=task priority=P2>`
   - Wire dependencies:
     - **gh mode:** edit the parent issue body to append `- [ ] #<child>` for each child issue
     - **bd mode:** `bd dep add <child> <parent> --type parent-child`
     - **ephemeral:** use TaskUpdate `--addBlockedBy [<parent>]`
3. **Present plan** to user for approval

**Checklist before proceeding:**
- [ ] Plan file written with numbered steps
- [ ] Tracking issues created for each deliverable
- [ ] Dependencies wired
- [ ] User has approved the plan

---

## Phase 3: Workspace Isolation

**Gate:** Isolated workspace ready

1. **Create a feature branch off the correct base:**
   ```bash
   git fetch origin develop
   git checkout -b <type>/<slug>-<issue-ref> origin/develop
   # <type> ∈ {feat, fix, chore, docs}
   # <issue-ref>: for gh mode use gh-<N> (e.g. feat/aroon-family-gh-491)
   #              for bd mode use bd-<id> (e.g. feat/aroon-family-bd-b6k5)
   ```
   - Branch naming embeds the issue ID so `git branch` at a glance tells you
     what's in flight
   - Never branch off `qualitycontrol` for production fixes (avoid double-merge
     tax) — that branch is for QC-run reference only
2. **Claim first issue:** `<TASK: claim <id>>`

**Checklist before proceeding:**
- [ ] Working in feature branch off `origin/develop`
- [ ] First issue claimed in the tracker

---

## Phase 4: TDD Implementation

**Gate:** All tests passing, all issues closed

This is the core loop. For each plan step:

1. **Claim the issue:** `<TASK: claim <id>>`
2. **Invoke `superpowers:test-driven-development`** — mandatory:
   - **Red:** Write failing tests that define expected behavior
   - **Green:** Write the minimum code to make tests pass
   - **Refactor:** Clean up while keeping tests green
3. **On test failure or unexpected behavior:**
   - **Invoke `superpowers:systematic-debugging`** — diagnose root cause before
     proposing fixes
   - If the bug is separate from the current task, file a new tracking issue:
     `<TASK: create title="Bug: ..." type=bug priority=P1>`
4. **For independent sub-tasks:**
   - Use `superpowers:dispatching-parallel-agents` or
     `superpowers:subagent-driven-development` for concurrency
5. **Close the issue:** `<TASK: close <id> reason="implemented in <sha>">`
6. **Run tests** after each issue closure to confirm no regression:
   ```bash
   .venv_win\Scripts\python.exe -m pytest <touched-tests-path> -v
   ```

**Checklist before proceeding:**
- [ ] All plan steps implemented
- [ ] All unit tests passing (output shown, not just claimed)
- [ ] All tracking issues closed
- [ ] No known bugs left unfiled

---

## Phase 5: Code Quality Gate

**Gate:** Pre-commit clean, diagnostics clean

1. **Invoke `simplify`** — review all changed code for:
   - Reuse opportunities (esp. helpers from `openbb_core/` — see the QC
     remediation plan for what already exists)
   - Unnecessary complexity
   - Consistency with existing patterns
2. **Run VS Code diagnostics:** `mcp__ide__getDiagnostics` for type errors,
   missing imports
3. **Run pre-commit locally** — must pass before commit:
   ```bash
   pre-commit run --files <touched-files>
   ```
   The fork enforces: black, ruff, mypy (`--check-untyped-defs`), pydocstyle
   (openbb_platform + cli only), codespell, pylint, detect-secrets, nbstripout
4. **Invoke `superpowers:verification-before-completion`:**
   - Run full test suite for touched files
   - **Evidence before assertions** — never claim "all tests pass" without
     showing output

**Checklist before proceeding:**
- [ ] `simplify` review completed, issues fixed
- [ ] No diagnostic errors
- [ ] Pre-commit passes on all touched files
- [ ] All tests confirmed passing (output shown)

---

## Phase 6: Commit + Push + QC Self-Review Loop

**Gate:** `/openbb-qualitycontrol` returns clean on the branch (or all findings
triaged with recorded reasons)

This is the QC loop — every fix branch reviews itself with the QC skill
before opening a PR, so we catch our own regressions before human reviewers do.

### 6a. Commit + push the branch

1. **Commit with fork convention** — Conventional Commits with scope:
   ```bash
   git add <specific-files>   # never git add -A
   git commit -m "<type>(<scope>): <summary>

   <optional body>

   Closes #<gh-issue> (or Refs bd-<id> in bd mode)"
   ```
   Common scopes for this fork: `qc`, `beads`, `analysis`, `techtrade`,
   `backtest`, `fmp_cached`, `agents`, `tools`, `sec`, `notebooks`,
   `financialtoolkit`. **Cite the tracking issue in the commit body** so
   history is queryable:
   - gh mode: `Closes #491 (Point-in-time XLK universe builder)`
   - bd mode: `Refs bd-b6k5 (Aroon Up/Down/Osc family)` — bd does not
     parse commit messages; close the bead manually via `bd close bd-b6k5
     --reason="shipped in <sha>"`. Use `Refs`, not `Closes`, since GitHub
     only auto-closes on `Closes #NN` for its own issues.
2. **Push the branch to origin:**
   ```bash
   git push -u origin <branch-name>
   ```

### 6b. Run `/openbb-qualitycontrol` in `branch` mode

Trigger the QC skill against the branch's commits (files-changed since
`origin/develop`):

```
/openbb-qualitycontrol branch
```

The skill will dispatch categorized subagents against every file the branch
modified, apply the confidence filter (≥ 70) and inline refuters (≥ 85), and
either:
- **Return clean** — no findings, or all findings are refuter-dropped.
  Continue to Phase 7.
- **Surface findings** — enter the fix loop (Phase 6c).

Findings raised by the QC skill are filed as tracking issues in whichever
mode is active (`gh` creates GitHub issues; `bd` creates beads).

### 6c. Fix loop (repeat until clean)

For each QC finding on the branch:

1. **Triage the finding:**
   - **Real bug that must be fixed:** proceed to step 2
   - **False positive / rubric-nit / low-value:**
     `<TASK: drop <finding-id> reason="triage: <specific-reason>">`
     and skip to next. **Note the distinct verb** — `drop` is not
     `close`. In gh mode this becomes `gh issue close --reason
     "not planned" --comment "triage: ..."` so the closure metadata
     honestly reflects rejection, not completion. Using `close` for
     a rejected finding would mislabel it as completed work in
     the GH graph.
2. **Fix the finding:**
   - Return to Phase 4 (TDD) for the specific fix — write failing test, fix,
     confirm green
   - Or apply the suggested fix from the issue description if trivial
3. **Re-run Phase 5** quality gate (`simplify` + pre-commit + tests) on the
   incremental change
4. **Commit + push** the fix on the SAME branch:
   ```bash
   git add <fix-files>
   git commit -m "fix(qc): <summary> — addresses #<finding-id>"
   git push
   ```
5. **Close the finding:**
   `<TASK: close <finding-id> reason="fixed in <sha> — <branch>">`
6. **Re-run `/openbb-qualitycontrol branch`** — must be clean before exiting
   loop

### 6d. Verify the loop terminated cleanly

Before exiting Phase 6:
- [ ] `/openbb-qualitycontrol branch` returns 0 open findings on the branch's
      commits
- [ ] Every raised finding is either fixed (issue closed with `<TASK: close>` + "fixed in <sha>") or explicitly dropped (issue closed with `<TASK: drop>` + "triage: <reason>" — in gh mode `--reason "not planned"`, in bd mode `bd close --reason=triage:...`)
- [ ] All fix commits pushed to the feature branch
- [ ] Pre-commit still passes end-to-end on the full branch

**Anti-pattern to avoid:** Opening a PR before the QC-loop is clean. Human
reviewers should not be your primary QC filter — the QC skill catches most
issues cheaper than a human round-trip.

---

## Phase 7: PR + Review

**Gate:** PR opened, reviewer feedback addressed

1. **Checkpoint with user for PR authorization** — per conservative profile,
   never `gh pr create` without explicit user request. Show:
   - Summary of what shipped
   - Test evidence (commands + pass counts)
   - `/openbb-qualitycontrol` clean-verdict output
   - Proposed PR title (fork convention: `<type>(<scope>): <summary>`)
   - Proposed PR body (fork custom template — see below)
2. **PR body template** (fork custom, not upstream):
   ````markdown
   ## Summary
   <1-2 paragraphs. `Closes #<gh-issue>` for gh-mode or
   `Refs bd-<id>` for bd-mode. Links to design + plan docs.>

   ## What this PR ships
   - `path/to/file.py` (+42/-3 LoC) — <one-line change summary>
   - <repeat per file>

   ## Locked decisions honored
   | # | Decision | Implementation |
   |---|---|---|
   | L1 | <decision from design doc> | <where in the PR> |

   ## Test plan

   **Automated:**
   ```
   .venv_win\Scripts\python.exe -m pytest <path> -v
   # <pass count>
   ```

   **Live smoke** (if applicable): <command>

   **Regression:** <what didn't change>

   ## Closed issues
   - #<N>: <title> — CLOSED  (gh mode: auto-closed by `Closes #<N>` in
     commit body; bd mode: closed manually via `bd close bd-<id>`)

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ````
3. **After PR opens:** Address reviewer feedback via
   `superpowers:receiving-code-review` — verify feedback technically before
   implementing. Don't blindly agree.
4. **Update project knowledge if new patterns emerged:**
   - **gh mode:** append a timestamped entry to `docs/MEMORIES.md`
     (create the file if it doesn't exist yet). Commit it in the same PR
     as the code change, or in a small follow-up docs PR.
   - **bd mode:** `bd remember "<key insight>"` for cross-session knowledge
   - `claude-md-management:revise-claude-md` if a new convention needs to land

**Checklist before declaring done:**
- [ ] PR merged to `develop`
- [ ] All tracking issues closed with reason citing merge SHA
- [ ] Tracking issue for the branch also closed
- [ ] Insights captured (in `docs/MEMORIES.md` for gh mode, or `bd remember`
      for bd mode)

---

## Phase 8: Cleanup

1. **Delete the local + remote branch** after merge:
   ```bash
   git checkout develop && git pull
   git branch -d <branch-name>
   git push origin --delete <branch-name>
   ```
2. **Verify next-branch readiness:**
   - **gh mode:**
     `gh issue list --label QC-FIX --assignee @me --state open`
     — confirm the next expected issue is visible
   - **bd mode:** `bd ready | grep QC-FIX`
3. **Session close:** report merged SHA + closed issue IDs + what's next

---

## Task command translations

The `<TASK: ...>` placeholders above translate to the following per mode.

### Create a tracking issue

| Mode | Command |
|---|---|
| gh | `gh issue create --repo prajoria/OpenBB --title "<title>" --body "<body>" --label type:<T> --label priority:<P>[ --label area:<A>]` |
| bd | `bd create --title="<title>" --description="<body>" --type=<T> --priority=<P>` |
| ephemeral | `TaskCreate(subject="<title>", description="<body>")` |

**Note on `gh issue create --label`:** repeat the flag per label rather
than using the comma form (`--label "a,b,c"`). Both are accepted by gh,
but repeated flags avoid quoting gotchas and validate each label
independently.

**Labels used in gh mode:**
- `type:` — one of `feature`, `bug`, `task`, `epic`, `doc`
- `priority:` — one of `P0`, `P1`, `P2`, `P3`, `P4`
- `area:` — optional, matches commit scope (`techtrade`, `analysis`,
  `fmp_cached`, `regime`, `backtest`, `tools`, `agents`, `notebooks`, etc.)

**Auto-create missing labels** — run once per session before the first
`gh issue create` call:

**Bash:**

```bash
# Idempotent — gh label create fails if exists; safe to ignore via || true
for spec in \
  "type:feature|a2eeef" "type:bug|d73a4a" "type:task|0e8a16" \
  "type:epic|5319e7" "type:doc|0075ca" \
  "priority:P0|b60205" "priority:P1|d93f0b" "priority:P2|fbca04" \
  "priority:P3|c2e0c6" "priority:P4|cccccc" \
  "status:in-progress|0e8a16" "status:in-review|fbca04" \
  "status:blocked|b60205"
do
  name="${spec%%|*}"; color="${spec##*|}"
  gh label create "$name" --color "$color" >/dev/null 2>&1 || true
done
```

**PowerShell:**

```powershell
$labels = @(
  @{n='type:feature'; c='a2eeef'}, @{n='type:bug'; c='d73a4a'},
  @{n='type:task';    c='0e8a16'}, @{n='type:epic'; c='5319e7'},
  @{n='type:doc';     c='0075ca'},
  @{n='priority:P0';  c='b60205'}, @{n='priority:P1'; c='d93f0b'},
  @{n='priority:P2';  c='fbca04'}, @{n='priority:P3'; c='c2e0c6'},
  @{n='priority:P4';  c='cccccc'},
  @{n='status:in-progress'; c='0e8a16'},
  @{n='status:in-review';   c='fbca04'},
  @{n='status:blocked';     c='b60205'}
)
foreach ($l in $labels) {
  try { gh label create $l.n --color $l.c 2>$null | Out-Null } catch {}
}
```

### Claim an issue

| Mode | Command |
|---|---|
| gh | `gh issue edit <#N> --add-assignee @me --add-label "status:in-progress"` |
| bd | `bd update <id> --status=in_progress --claim` |
| ephemeral | `TaskUpdate(taskId=<id>, status=in_progress)` |

### Close an issue

| Mode | Command |
|---|---|
| gh | `gh issue close <#N> --reason completed --comment "<reason>"` |
| bd | `bd close <id> --reason="<reason>"` |
| ephemeral | `TaskUpdate(taskId=<id>, status=completed)` |

Use `close` when the work in the issue was actually completed
(shipped, merged, fixed).

### Drop (reject) an issue

Use `drop` — not `close` — when rejecting a false-positive
finding, rubric-nit, or low-value item without doing work. The
different verb maps to the different GitHub close-reason so the
tracker graph honestly reflects rejection vs. completion.

| Mode | Command |
|---|---|
| gh | `gh issue close <#N> --reason "not planned" --comment "triage: <reason>"` |
| bd | `bd close <id> --reason="triage: <reason>"` |
| ephemeral | `TaskUpdate(taskId=<id>, status=completed)` — no rejected state in TaskCreate; add "REJECTED: <reason>" prefix to your final summary |

**Note on gh `--reason`:** the reason field is a **fixed vocabulary**
(`completed` \| `not planned` \| `duplicate`). Free-form text goes in
`--comment`, not `--reason`. Use `close` for completed work and
`drop` for rejected findings — the semantic distinction is important
for the GH audit trail.

### List ready work

| Mode | Command |
|---|---|
| gh | `gh issue list --assignee @me --state open --label "status:in-progress" --json number,title,labels` (or `--search "no:assignee"` for unclaimed) |
| bd | `bd ready` |
| ephemeral | `TaskList` |

### Add a memory / cross-session insight

| Mode | Where |
|---|---|
| gh | Append to `docs/MEMORIES.md`. Format: `## <key> (<date>)\n\n<body>\n`. Commit with the next code change. |
| bd | `bd remember "<key insight>"` |
| ephemeral | **Emit a `MEMORY: <text>` line in your final session summary** so the user can manually transcribe to `docs/MEMORIES.md` next time gh mode is available. Do NOT drop the insight silently — cross-session knowledge is what caused the 2026-07 bootstrap collision's recovery pain. |

---

## Quick Reference: Which Skill When

| Situation | Skill to Invoke |
|-----------|----------------|
| Starting a new feature | This workflow from Phase 1 |
| Writing tests before code | `superpowers:test-driven-development` |
| Test failure or bug | `superpowers:systematic-debugging` |
| Multiple independent tasks | `superpowers:dispatching-parallel-agents` |
| Need library docs | Context7 (`resolve-library-id` → `query-docs`) |
| Cleaning up code | `simplify` |
| About to say "done" | `superpowers:verification-before-completion` |
| **Self-QC a fix branch** | **`/openbb-qualitycontrol branch`** |
| Receiving review feedback | `superpowers:receiving-code-review` |
| Feature branch complete | `superpowers:finishing-a-development-branch` |

## Anti-Patterns — Don't Do These

1. **Skipping brainstorming** — "It's simple" is where assumptions cause the
   most rework
2. **Writing code before tests** — TDD is gated, not optional
3. **Mixing task-tracking modes mid-cycle** — if you started in gh mode,
   finish in gh mode. Switching to bd mid-cycle creates two disconnected
   trails. If gh drops out mid-session, either resume in bd (and note the
   drop in the next commit body for later reconciliation) or wait for
   auth to recover.
4. **Claiming done without evidence** — show test output, not just assertions
5. **Blind agreement with review feedback** — verify technically first
6. **Committing without running pre-commit** — always run locally before push
7. **Skipping phases** — each gate exists because skipping it has burned us
   before
8. **Opening PR before Phase 6 QC-loop clean** — human reviewers are not your
   primary QC filter
9. **Branching off `qualitycontrol`** — always base off `origin/develop`; the
   `qualitycontrol` branch is for QC-run reference only
10. **Committing without citing the tracking issue** — every commit body must
    reference its issue (gh `Closes #NN` — auto-closes on merge; or bd
    `Refs bd-XX` + manual `bd close` since bd doesn't parse commits) so
    `git log --grep` can rebuild the trail if the tracker DB is lost
    (this is exactly what the 2026-07 bd bootstrap collision proved)

## OpenBB-Specific Rules

- **Always use `.venv_win`** — never system Python
- **`fmp_cached` is the only provider for `Analysis/`** — no `fmp` fallback, no
  `yfinance`
- **Reuse before inventing** — check for existing helpers first:
  - `openbb_core/provider/utils/helpers.py::make_request` / `amake_request` /
    `get_querystring`
  - `openbb_fmp_cached/utils/database.py::execute_query` / `execute_many`
  - `openbb_agents/guardrails.py::redact_pii` (single PII redactor — fix in
    place, don't create a second)
  - `openbb_fred/utils/rate_limiter.py::fred_get` (will become thin wrapper on
    the new `openbb_core/provider/utils/http_retry.py::retrying_get`)
  - See the QC-remediation plan file referenced in the tracking issue for the
    full "reuse cheatsheet"
- **Test commands:**
  ```bash
  # Unit tests (~1s, no API needed)
  .venv_win\Scripts\python.exe -m pytest <path> -m "not integration" -v

  # Integration tests (~19 min, needs fmp_cached API key)
  .venv_win\Scripts\python.exe -m pytest <path> -m "integration" -v
  ```
- **GitHub Issues for everything permanent** in gh mode; bd only as fallback.
  See `docs/BD_MIGRATION_PLAN.md` for the migration story and
  `docs/BEADS_HYGIENE.md` (once Phase C lands) for day-to-day rules.
- **Commit every tracking-issue ID in the commit body.** `git log --grep
  '#NN'` is the durable audit trail — it survives DB losses, bootstrap
  collisions, and tracker migrations.
