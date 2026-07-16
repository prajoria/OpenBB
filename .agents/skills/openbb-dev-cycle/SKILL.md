---
name: openbb-dev-cycle
description: Disciplined 10-phase gated feature-development workflow for the OpenBB platform with a convergent multi-tool review loop — chains brainstorming, planning, git-worktree isolation, TDD implementation, code simplification, harness-based end-to-end verify, pre-push local review (coderabbit + pr-review-toolkit), commit + push + PR open, and a Phase-9 convergence loop that iterates code-review + security-review + coderabbit:autofix until every finding is either fixed-with-verify or filed as a GitHub issue. **GitHub Issues is the sole task tracker**; the prior `bd` (beads) system is fully retired on this repo. Cross-session persistent memory lives in `docs/MEMORIES.md`. Use when starting or running a full feature-development cycle in this repo, when the user asks for the "openbb-dev-cycle" or "dev cycle" workflow, or when implementing a non-trivial OpenBB/Analysis feature that must ship through a real PR-review loop.
---

# OpenBB Feature Development Cycle (v3)

A disciplined, gated workflow for developing features in the OpenBB platform. Each phase must complete before the next begins. **No shortcuts.**

## What changed vs v2

v2 used `bd` (beads) as the primary tracker. v3 replaces that with **GitHub Issues** attached to program-level GitHub Projects — the fork's tracking authority now lives in GH. Beads is **fully retired** on this repo (including `bd remember`):

- Phase 2: `bd create` → `gh issue create` (with program label + sub-issue link to the program epic).
- Phase 4: `bd update --claim` / `bd close` → GH Project "Status" field (`In Progress` / `Done`) + `gh issue close`.
- Phase 9: deferred review findings → `gh issue create` (with `deferred-from-review` label) instead of `bd create`.
- Phase 10 cross-session memory: `bd remember` → append to checked-in `docs/MEMORIES.md`. No `bd` calls anywhere.

If a repo has no active GH Project for the program, the skill halts and asks the user to create one (or points at `docs/prompts/create-*-project.md` templates).

## Phase list (10 phases, 10 gates)

| # | Phase | Gate |
|---|-------|------|
| 1 | Design & Brainstorming | Design spec approved by user, committed |
| 2 | Planning + GH Issues | Plan md + GH issue tree wired (each plan step is a sub-issue of the program epic), user-approved |
| 3 | Workspace Isolation | Worktree/branch live, first GH issue moved to `In Progress` on the project |
| 4 | TDD Implementation | Unit tests green, all planned GH issues closed with `Closes #NN` in the merge commit |
| 5 | Simplify + Diagnostics | `simplify` applied, IDE diagnostics clean |
| 6 | **Harness Verify** | `/verify` drives changed code path end-to-end, output captured |
| 7 | **Pre-Push Local Review** | `coderabbit:code-review` + `pr-review-toolkit:review-pr` findings triaged locally |
| 8 | **Initial Commit → Push → PR Open** | `commit-commands:commit-push-pr` returns a PR URL; PR body references program issues via `Closes #NN`; `HEAD_0` recorded |
| 9 | **Convergence Loop** | Every finding resolved-with-verify OR filed as GH issue with justification; **exit predicate holds** |
| 10 | Finish | `superpowers:finishing-a-development-branch` completes; CLAUDE.md revised; cross-session note appended to `docs/MEMORIES.md` |

### Phase 1: Design & Brainstorming

1. Invoke `superpowers:brainstorming` — purpose, constraints, success criteria, 2-3 approaches with trade-offs and a recommendation. Use Context7 (`resolve-library-id` → `query-docs`) for any library under consideration. Use `feature-dev:code-explorer` to survey existing patterns.
2. Present design section by section; get user approval per section.
3. Write to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
4. Commit the spec (respecting the conservative git profile — propose + wait for approval).

**Checklist:** [ ] spec written & committed  [ ] user approved  [ ] no TBDs.

### Phase 2: Planning + GH Issues

1. Invoke `superpowers:writing-plans`. Numbered steps; review checkpoints every ~3 steps. Use `feature-dev:code-architect` for architecture depth.
2. **Identify the program**: find the GH Project + program epic issue for this work (e.g. Portfolio Intelligence Engine → Project #4, epic issue #491). If no program exists, halt and ask the user which project to attach to, or point at a `docs/prompts/create-*-project.md` template to spin one up.
3. **File a GH issue for each deliverable**:
   ```bash
   gh issue create --repo <owner>/<repo> \
     --title "[<program-tag>] <step summary>" \
     --body "$(cat <<EOF
   <what and why>

   ---
   **Provenance**
   - Parent epic: #<epic-issue>
   - Plan step: <N> of <total>
   - Design spec: docs/superpowers/specs/<date>-<topic>-design.md
   EOF
   )" \
     --label "<program-label>,type-task,<phase-label>,<lane-label>"
   ```
4. **Wire as sub-issue of the program epic** via the sub-issues REST API. Use the child issue's numeric database ID (NOT the issue number) from `gh api /repos/<owner>/<repo>/issues/<n>`:
   ```bash
   CHILD_DB_ID=$(gh api /repos/<owner>/<repo>/issues/<child-n> --jq .id)
   gh api -X POST /repos/<owner>/<repo>/issues/<epic-n>/sub_issues \
     -H "Accept: application/vnd.github+json" \
     -f sub_issue_id=$CHILD_DB_ID
   ```
5. **Add each issue to the program project** and set custom fields (Phase/Lane/Type/Start/End as applicable):
   ```bash
   gh project item-add <project-number> --owner <owner> --url <issue-url>
   ```
6. Present the plan + issue URLs; wait for user approval.

**Checklist:** [ ] plan md written  [ ] GH issue per deliverable  [ ] each issue linked as sub-issue of program epic  [ ] each issue added to program project with fields set  [ ] user approved.

**Migration note**: this replaces v2's `bd create` + `bd link --blocked-by`. Beads is fully retired on this repo — no `bd` calls anywhere, including `bd remember` (Phase 10 uses `docs/MEMORIES.md` instead).

### Phase 3: Workspace Isolation

1. Invoke `superpowers:using-git-worktrees` (or a feature branch when worktrees don't fit). **Branch name MUST embed the GH issue number**: `feat/pi-<topic>-gh-<NN>`, `fix/pi-<topic>-gh-<NN>`, or `docs/pi-<topic>-gh-<NN>` for portfolio work (the `pi-` scope tag identifies portfolio; the `-gh-<NN>` suffix is required by the repo's coordination protocol). PR target is the program's integration branch (`portfolio` for Portfolio Intelligence Engine) — never `develop` directly.
2. **Mark the first issue as In Progress** on the program project:
   ```bash
   # Find item_id for the issue in the project (from scripts/<program>_project_items.json,
   # or via `gh project item-list <n> --owner <owner> --format json | jq ...`)
   # Then update the "Status" single-select field to "In Progress":
   gh api graphql -f query='
     mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
       updateProjectV2ItemFieldValue(input: {
         projectId: $project, itemId: $item, fieldId: $field,
         value: { singleSelectOptionId: $option }
       }) { projectV2Item { id } }
     }' \
     -f project=<PROJECT_ID> \
     -f item=<ITEM_ID> \
     -f field=<STATUS_FIELD_ID> \
     -f option=<IN_PROGRESS_OPTION_ID>
   ```
   Or simply comment on the issue: `gh issue comment <n> --body "Starting work on branch: \`<branch>\`"` — comment is a lightweight equivalent when the project field-value dance is overkill.

**Checklist:** [ ] isolated CWD  [ ] first GH issue marked In Progress OR commented with branch name.

### Phase 4: TDD Implementation

For each plan step (each corresponds to one GH issue):

1. Move the GH issue's Status to `In Progress` on the program project (see Phase 3 snippet), OR comment `Starting <issue-N>` on the issue.
2. Invoke `superpowers:test-driven-development` — RED → GREEN → REFACTOR. Mandatory, not optional.
3. On failure: `superpowers:systematic-debugging`. **Bug outside current task?**
   ```bash
   gh issue create --repo <owner>/<repo> \
     --title "[<program-tag>] Bug: <one-line summary>" \
     --body "Discovered while working on #<parent-issue>. Reproducer:\n\n\`\`\`\n<reproducer>\n\`\`\`\n\nExpected: ...\nActual: ..." \
     --label "<program-label>,type-bug,priority-p1"
   ```
   Link it as a sub-issue of the parent if scope-related, or leave standalone if orthogonal.
4. Independent sub-tasks? `superpowers:dispatching-parallel-agents` or `superpowers:subagent-driven-development`.
5. When the issue's work is complete: leave the GH issue **open** — it will be auto-closed by the merge commit via `Closes #NN` in the PR body (Phase 8). Do NOT manually close mid-cycle; the merge-commit reference is the durable audit trail.
6. Re-run unit tests: `.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v`.

**Checklist:** [ ] all plan steps done  [ ] all unit tests green  [ ] no unfiled bugs (every discovered bug has a `type-bug` GH issue).

### Phase 5: Simplify + Diagnostics

1. Invoke `simplify` — reuse, complexity, consistency.
2. Run `mcp__ide__getDiagnostics` — clear all type errors, missing imports.
3. Invoke `superpowers:verification-before-completion` — evidence before assertions, always paste output.

**Checklist:** [ ] `simplify` applied  [ ] diagnostics clean  [ ] test output shown.

### Phase 6: Harness Verify

**Green pytest is not enough.** Pytest exercises assumptions via fixtures/mocks. `/verify` drives the real code path.

1. Invoke `/verify` (built-in). It should drive the changed code path end-to-end. For OpenBB Analysis changes, the natural invocation is roughly:
   ```bash
   .venv_win\Scripts\python.exe -c "from stock_analysis import AnalysisConfig, run_full_analysis; r = run_full_analysis(AnalysisConfig(symbol='MSFT')); print(r['p2'])"
   ```
   Adjust the phase key (`p1`..`p7`) and symbol to match the code you actually changed.
2. **Capture stdout** to a scratchpad (`.dev-cycle/verify-phase6.log`). This is evidence for Phase 7 and the convergence loop.
3. If the project doesn't have a natural entry point that exercises your change, author a small `.claude/verify.md` documenting the invocation for future runs.

**Failure mode `/verify` catches that pytest misses:** provider returns `enterprise_value=None` on real data; unit tests fed hand-constructed inputs and were green; first real invocation silently produces nonsense or throws.

**Checklist:** [ ] `/verify` invoked  [ ] real code path exercised (not just tests)  [ ] stdout captured to evidence log.

### Phase 7: Pre-Push Local Review

Run local review tools BEFORE pushing — cheaper to fix pre-push.

1. `coderabbit:code-review` — local CLI, reads staged/committed diff, no PR needed.
2. `pr-review-toolkit:review-pr` — despite the name, reads local `git diff --name-only`; orchestrates up to 6 subagents (comment-analyzer, pr-test-analyzer, silent-failure-hunter, type-design-analyzer, code-reviewer, code-simplifier).
3. Triage findings via Apply / Defer / Modify (see triage section below). Apply-rows must re-run `/verify` on the affected path. Defer-rows file a GH issue (not a bead — see triage section for the exact `gh issue create` call).

**Checklist:** [ ] both tools run  [ ] every finding triaged  [ ] no `action = empty` rows remain.

### Phase 8: Initial Commit → Push → PR Open

Use `commit-commands:commit-push-pr` **once** — it opens the PR. Do NOT call it again in the loop (it will create a duplicate PR).

1. `commit-commands:commit-push-pr` — branches (if on protected base), commits, pushes with `-u`, opens PR against the program's integration branch (per branch-protection policy in `CLAUDE.md`; e.g. `openbb_pine_support`, `portfolio`). **For Portfolio Intelligence Engine, PR target is `portfolio` — never `develop`. The single `portfolio → develop` promotion PR is gated on Daisy's explicit, loud sign-off; do not open that PR unprompted.**
2. **Add `Closes #NN` / `Refs #NN` to the PR body** for every plan-step GH issue this PR resolves. GH will auto-close referenced issues when the PR merges — this is the primary mechanism keeping the issue tracker in sync with what shipped.
3. Record `HEAD_0 = git rev-parse HEAD` — the loop's seed.
4. Note the PR URL — you will need it in Phase 9.

**Checklist:** [ ] PR URL exists  [ ] PR body cites every plan-step issue with `Closes #NN`  [ ] `HEAD_0` recorded  [ ] branch pushed with tracking.

### Phase 9: Convergence Loop (the heart of this skill)

**Entry**: immediately after Phase 8 returns the PR URL.

Each iteration:

1. **Fan-out reviews** in this order (sequential — CodeRabbit needs the bot's comments to land on GitHub before `autofix` can consume them):
   - `code-review` (built-in top-level) — posts inline PR comments; idempotent per HEAD (skips if already reviewed at this HEAD)
   - `security-review` (built-in) — security findings on the PR
   - Wait for CodeRabbit bot to post threads on the PR (the CodeRabbit app must be installed)
   - `coderabbit:autofix` — reads unresolved review threads via GraphQL (`isResolved=false && isOutdated=false`)
2. **Collate findings** into `.dev-cycle/findings-pr<NNN>-iter<N>.md`:
   ```
   | severity | title | location | tool | action | gh_issue | verify_evidence |
   ```
3. **Per-row triage** (Apply / Defer / Modify — see triage section below).
4. **Apply rows**: fix → re-run `/verify` on affected path → paste stdout into `verify_evidence`.
5. **Defer rows**: `gh issue create` with mandatory justification → record `gh_issue` (issue number + URL).
6. When every row has a terminal action, `commit-commands:commit` (plain — NOT `commit-push-pr`) + `git push`.
7. **Re-run the exit predicate.** Increment iteration counter. Re-enter loop OR exit.

**Exit predicate — all four clauses must hold**:
```
∀ f ∈ findings_iter_N.  f.action ∈ {applied_and_verified, deferred_with_gh_issue}
∧ coderabbit:autofix reports 0 unresolved GH review threads on current HEAD
∧ code-review (built-in) returns "skip — already reviewed at HEAD"
∧ security-review reports 0 unaddressed HIGH/CRITICAL findings
    (if security-review does not expose severity, this degrades to "0 findings")
```

The `code-review` skip-per-HEAD behavior is the strongest convergence signal in the ecosystem — a fresh push + fresh `code-review` returning "no review" proves no reviewer above threshold 80 sees a bug on this HEAD. Every loop iteration MUST push a new commit before re-invoking review tools, or they no-op and you learn nothing.

**Escape hatch**: 5 iterations. On overflow, STOP. Print the latest findings table + deltas across iterations. Hand off to the user for direction. This is escalation, **not** exit — the loop remains open; the user decides.

**State between iterations**:
- `.dev-cycle/findings-pr<NNN>-iter<N>.md` — per-iteration snapshot, diffable across iters
- GH issues — only for deferred items, so `gh issue list --label deferred-from-review` reflects real outstanding work
- Applied-and-verified rows live only in the scratchpad; they don't need a GH issue

**CRITICAL RULE — the loop's only exit is the predicate** (adapted from `ralph-loop/1.0.0/commands/ralph-loop.md:18`):

> **If the exit predicate has not been satisfied, you may NOT declare the loop done.** Do not output false completion signals to escape the loop, even if you think you're stuck, the user is impatient, or you should exit for other reasons. The predicate is the only exit. Filing a GH issue is progress; **filing a GH issue is not exit**. Re-run the predicate after every state change.

### Phase 10: Finish

Only after Phase 9 exits cleanly.

1. `superpowers:finishing-a-development-branch` — guided merge/PR/keep/discard decision. It runs its own test-gate; **do not call it inside Phase 9**.
2. **Verify GH issue closure**: `gh issue list --label <program-label> --state closed --search "closed:>=<PR-merge-date>"` — every issue referenced with `Closes #NN` should now be closed. Manually close any that GH missed (rare — happens if the PR body used the wrong syntax).
3. `claude-md-management:revise-claude-md` — capture any new patterns/conventions surfaced by this cycle.
4. **Append a cross-session memory entry to `docs/MEMORIES.md`** — one short paragraph describing what shipped, keyed by a stable topic (e.g. `## portfolio-intel: paper migration shipped (2026-07-16, PR #NNN)`). This is the durable state that a future session needs to know so it doesn't redo the work. Commit `docs/MEMORIES.md` in the same commit as CLAUDE.md revisions.

**Checklist:** [ ] `finishing-a-development-branch` completed  [ ] all program issues closed on GH  [ ] CLAUDE.md updated if warranted  [ ] `docs/MEMORIES.md` appended and committed.

---

## Multi-tool review fan-out (at a glance)

| Stage | Tool | Produces | Feeds |
|-------|------|----------|-------|
| Phase 5 (pre-verify) | `simplify` | Quality-only diff suggestions | Cleaned diff |
| Phase 6 (pre-commit) | `/verify` (built-in) | Behavioral evidence (real run output) | Gates commit if driven path errors |
| Phase 7 (pre-push) | `coderabbit:code-review` | Local CLI findings on staged diff | Ph 7 triage before push |
| Phase 7 (pre-push) | `pr-review-toolkit:review-pr` | Diff-based findings from 6 sub-agents | Same triage bucket |
| Phase 9 (per-iter) | `code-review` (built-in) | Inline PR comments; idempotent per HEAD | Convergence signal + findings table |
| Phase 9 (per-iter) | `security-review` (built-in) | Security findings on PR | Findings table (HIGH/CRIT gates exit) |
| Phase 9 (per-iter) | `coderabbit:autofix` | Reads GH review threads (GraphQL) | Direct exit-predicate input |

**Deferred**: GitHub Copilot PR review. Follow-up issue tracks adding it once the `gh api` invocation is confirmed.

---

## Findings triage: Apply / Defer / Modify

Every row of the findings table must land in exactly one bucket before the iteration can close.

- **Apply** — in-scope, safe, single-commit fix.
  - Required: (a) fix, (b) `/verify` re-run on affected path, (c) evidence pasted into `verify_evidence` column.
  - No GH issue needed — verified-fix closes the row.

- **Defer** — out of scope, needs design, blocked by external dep, or explicitly downgraded by user.
  - Required: file a GH issue with the program label + `deferred-from-review` label + mandatory justification:
    ```bash
    gh issue create --repo <owner>/<repo> \
      --title "[<program-tag>] Deferred from PR #<NNN> review: <finding>" \
      --body "$(cat <<EOF
    **Location**: <path:line>
    **Reviewer**: <tool>
    **Justification for deferring**: <specific reason, NOT "later" or "follow-up">
    **Original finding**:

    <finding text>
    EOF
    )" \
      --label "<program-label>,type-<bug|task>,deferred-from-review,priority-p<1-4>"
    # Then link as sub-issue of the program epic if scope-related.
    ```
  - Record `gh_issue` (number + URL) in the row.

- **Modify** — partial fix now, remainder deferred. Both an Apply-style verify AND a Defer-style GH issue.

**Loop-blocking rule**: a row with `action = empty`, `action = "noted"`, or `action = "will fix later"` is **loop-blocking**. The exit predicate reads the table; nothing else counts. No side-channel resolution.

**Filing a GH issue is progress; filing a GH issue is not exit.** After filing issues for any deferred rows, re-run the exit predicate — an issue-backed row satisfies the first clause, but the other three clauses (autofix threads, code-review no-op, security-review clean) must ALSO hold before the iteration exits.

---

## Rationalization table

The RED baseline for this skill showed one dominant failure mode: **loop-exit under impatience, filed as a "principled" call**. The entries below concentrate there. Modeled on `superpowers/6.1.1/skills/verification-before-completion/SKILL.md:63-74`.

| Scenario | Excuse | Reality |
|----------|--------|---------|
| Loop-exit early | "Just one nit left, ship it" | Nit unresolved = unresolved. Apply or file a GH issue — pick one — then **re-run the predicate**. |
| Loop-exit early | "Don't refactor under deadline pressure — that's a principle" | Filing a GH issue IS the deferral — no refactor needed. But filing the issue does not exit the loop; re-run the predicate. |
| Loop-exit early | "I filed the issue, so we're done" | Filing an issue is progress, not exit. The predicate has 4 clauses; the issue only satisfies clause 1. |
| Loop-exit early | "User said 'ship it', that overrides the predicate" | User didn't see the findings table. Show them the table + predicate state, then let them decide. |
| Loop-exit early | "Coderabbit's low-severity findings don't count" | Exit predicate is *all* findings, not severity-filtered. Low-severity findings can be Deferred with a low-priority GH issue — but they must be filed. |
| Loop-exit early | "Iteration 5, I'll declare done at 4 by lowering the bar" | Escape hatch at iter 5 = escalate to user, not lower the bar. Predicate is fixed. |
| Loop-exit early | "The PR was auto-approved, skip the loop" | Auto-approval is not review; the loop is what turns approval into evidence. |
| Skip harness verify | "Unit tests are green, `/verify` is redundant" | Tests exercise assumptions; `/verify` exercises the real code path. `enterprise_value=None` on real data is invisible to green tests. |
| Skip harness verify | "I already ran `/verify` in iter 2" | Each commit = new HEAD; verify is per-HEAD, not per-loop. |
| Findings not filed | "We can remember these 3 findings for the next commit" | Context loss between iterations is normal; unfiled = lost. The tracker is the memory. |
| Commit before verify | "Tests were green 20 min ago" | Stale evidence isn't evidence; the file state changed since. |
| Commit before verify | "Only whitespace / a type hint changed" | If the change was worth making, its effect is worth verifying. |
| Task tracker | "I'll use `bd create` — it's faster than gh CLI" | v3 says: GH Issues is the tracker of record on this repo. Beads is fully retired — no `bd` calls, including `bd remember`. Cross-session memory goes in `docs/MEMORIES.md`. |
| Task tracker | "The issue tree in GH is verbose, I'll just track in my head" | Untracked = lost between sessions. GH issue + sub-issue link is the durable index. |

---

## Red flags — STOP if you think any of these

Modeled on `superpowers/6.1.1/skills/using-superpowers/SKILL.md:33-48`.

- "Just one nit left."
- "The user seems tired of the loop."
- "I filed the GH issue, we're done."
- "It's technically not a bug."
- "Tests passed, that's enough."
- "I'll fix it real quick without filing an issue."
- "Iteration 5, so I'll declare done at 4 by lowering the bar."
- "I already know what `/verify` would say."
- "The review tool timed out — treat as clean."
- "Coderabbit is being pedantic — ignore."
- "Deferring everything to GH issues means we're done." (needs a justification per row, not blanket)
- "The PR was auto-approved, skip the loop."
- "Only whitespace changed, skip verify."
- "This is different because <plausible-sounding reason>."
- "`bd create` is faster than the gh CLI." (v3: GH Issues is the tracker on this repo — beads is fully retired, including `bd remember`.)

**All of these mean: STOP. Re-check the exit predicate. If it doesn't hold, keep looping.**

---

## Handoff contract (skill → skill wiring)

| Phase | Skill invoked | Produces | Next phase consumes |
|-------|---------------|----------|---------------------|
| 1 | `superpowers:brainstorming` (+ Context7) | Design spec md | Plan input |
| 2 | `superpowers:writing-plans` + `gh issue create` + `gh api sub_issues` | Plan md + GH issue tree under program epic | Issue queue |
| 3 | `superpowers:using-git-worktrees` | Isolated CWD | Implementation location |
| 4 | `superpowers:test-driven-development` (+ `systematic-debugging`) | Green tests, GH issues left open (auto-close via merge commit) | Diff for simplify |
| 5 | `simplify` + `mcp__ide__getDiagnostics` | Cleaned diff | `/verify` target |
| 6 | `/verify` (built-in) | Runtime evidence log | Pre-push review target |
| 7 | `coderabbit:code-review` + `pr-review-toolkit:review-pr` | Local findings table | Applied/deferred (via `gh issue create`) before push |
| 8 | `commit-commands:commit-push-pr` (**once only**) | PR URL with `Closes #NN` per plan-step issue, `HEAD_0` | Loop seed |
| 9 (per iter) | `code-review` + `security-review` + `coderabbit:autofix`; then `commit-commands:commit` + `git push` | Iter-N findings table + new HEAD | Next iter OR predicate exit |
| 10 | `superpowers:finishing-a-development-branch` + `claude-md-management:revise-claude-md` + append `docs/MEMORIES.md` | Merged/closed branch, closed program issues, updated CLAUDE.md, cross-session memory | Done |

---

## OpenBB-specific rules

- **Always use `.venv_win`** — never system Python (stale extension installs).
- **Provider policy — `fmp_cached` preferred, `fmp` is fallback.** Always use `fmp_cached` when the endpoint exists there. Only fall back to raw `fmp` when `fmp_cached` genuinely does not cover the endpoint — and when you do, **file a GH issue** with label `area:fmp-cached-gap` describing the gap. **Do NOT implement the `fmp_cached` extension yourself** — a separate team owns `providers/fmp_cached/`. The portfolio team's job is to file the gap issue and unblock via fallback (or another provider if genuinely needed), never to open PRs adding endpoints to `fmp_cached`. Never yfinance. Rationale: `fmp_cached` gives reproducible tests, deterministic dev loops, and cost control; the fallback exists so a missing endpoint never blocks the roadmap, but every use of the fallback is tracked debt handed off to the `fmp_cached` team.
- **Branch-protection**: PRs target the program's integration branch. Portfolio Intelligence Engine targets `portfolio`; the single `portfolio → develop` promotion PR is gated on Daisy's explicit, loud sign-off (see per-program CLAUDE.md). Regular flow: `develop → portfolio` is one-way absorb only.
- **GH Issues is the tracker** — every plan step, discovered bug, and deferred review finding gets a `gh issue create` (with program label + sub-issue link). `bd create` / `bd close` are NOT used.
- **Cross-session memory** lives in checked-in `docs/MEMORIES.md`. Beads is fully retired on this repo — no `bd` calls, including `bd remember`.
- **Test commands**:
  ```bash
  # Unit (~1s, no API needed)
  .venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

  # Integration (~19 min, needs fmp_cached API key)
  .venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v
  ```
- **Conservative git profile** — never `git commit` or `git push` without explicit authorization in the current session. Propose the commit, wait for approval. Same policy for `gh issue create` in bulk (>3 issues in one action): confirm the count and scope with the user before firing.

---

## Anti-patterns — do not do these

1. **Skipping brainstorming** — "It's simple" is where assumptions cause the most rework.
2. **Writing code before tests** — TDD is gated, not optional.
3. **Using `bd create` / `bd close` for task tracking** — v3 uses GH Issues. Beads is fully retired on this repo, including `bd remember` (Phase 10 uses `docs/MEMORIES.md`).
4. **Using TodoWrite/TaskCreate for permanent work** — GH Issues is the only long-lived tracker.
5. **Claiming done without evidence** — show test / verify output, not assertions.
6. **Blind agreement with review feedback** — verify technically first (see `superpowers:receiving-code-review`).
7. **Committing without running tests + `/verify`** — always verify before commit.
8. **Skipping harness verify because "tests are green"** — tests are not the app.
9. **Calling `commit-push-pr` inside the loop** — creates a duplicate PR. Use plain `commit` + `git push`.
10. **Exiting the loop on user impatience** — the predicate is the only exit.
11. **Filing a GH issue and declaring the loop done** — filing satisfies clause 1 of the predicate only; re-run the predicate.
12. **PR body without `Closes #NN`** — orphans the program issues from the shipping PR; they stay open forever unless manually closed. Every plan-step issue MUST be cited.

---

## Quick reference: which skill when

| Situation | Skill to invoke |
|-----------|-----------------|
| Starting a new feature | This workflow from Phase 1 |
| Writing tests before code | `superpowers:test-driven-development` |
| Test failure or bug | `superpowers:systematic-debugging` |
| Multiple independent tasks | `superpowers:dispatching-parallel-agents` |
| Need library docs | Context7 (`resolve-library-id` → `query-docs`) |
| Cleaning up code | `simplify` |
| About to say "done" | `superpowers:verification-before-completion` |
| Driving the real code path (not just tests) | `/verify` (Phase 6) |
| Local review before push | `coderabbit:code-review` + `pr-review-toolkit:review-pr` (Phase 7) |
| Open the PR (once) | `commit-commands:commit-push-pr` (Phase 8) |
| Iterate reviews on open PR | `code-review` + `security-review` + `coderabbit:autofix` (Phase 9) |
| Filing a task, bug, or deferred finding | `gh issue create` (Phase 2, 4, 7, 9) — NOT `bd create` |
| Cross-session persistent memory | Append to `docs/MEMORIES.md` (Phase 10) |
| Receiving review feedback | `superpowers:receiving-code-review` |
| Feature branch complete | `superpowers:finishing-a-development-branch` (Phase 10 only) |
