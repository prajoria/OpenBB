# OpenBB Feature Development Cycle

A disciplined, gated workflow for developing features in the OpenBB platform.
Each phase must complete before the next begins. No shortcuts.

## Overview

This skill enforces an 8-phase development lifecycle that chains together
brainstorming, planning, isolation, TDD implementation, quality checks, **QC
review of your own branch via `/openbb-qualitycontrol`**, review-issue creation
+ fix loop, and integration. It uses **beads** (`bd`) for task tracking and the
**superpowers** skill suite for process discipline.

**Key change vs prior version:** Phase 6 is now a mandatory self-QC-review loop
using the `openbb-qualitycontrol` skill in `branch` mode. Every fix branch runs
QC against its own commits before opening a PR — so we catch our own regressions
before humans see them.

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
2. **File beads issues** for each deliverable:
   ```bash
   bd create --title="<step summary>" --description="<what and why>" \
     --type=task --priority=2
   ```
   - Wire dependencies: `bd dep add <child> <parent> --type parent-child`
3. **Present plan** to user for approval

**Checklist before proceeding:**
- [ ] Plan file written with numbered steps
- [ ] Beads issues created for each deliverable
- [ ] Dependencies wired between issues
- [ ] User has approved the plan

---

## Phase 3: Workspace Isolation

**Gate:** Isolated workspace ready

1. **Create a feature branch off the correct base:**
   ```bash
   git fetch origin develop
   git checkout -b <type>/<slug> origin/develop
   # <type> ∈ {feat, fix, chore, docs}
   ```
   - Branch naming matches fork convention (`type/slug`, optional issue #)
   - Never branch off `qualitycontrol` for production fixes (avoid double-merge
     tax) — that branch is for QC-run reference only
2. **Claim first issue:** `bd update <id> --status=in_progress --claim`

**Checklist before proceeding:**
- [ ] Working in feature branch off `origin/develop`
- [ ] First issue claimed in beads

---

## Phase 4: TDD Implementation

**Gate:** All tests passing, all issues closed

This is the core loop. For each plan step:

1. **Claim the issue:** `bd update <id> --status=in_progress --claim`
2. **Invoke `superpowers:test-driven-development`** — mandatory:
   - **Red:** Write failing tests that define expected behavior
   - **Green:** Write the minimum code to make tests pass
   - **Refactor:** Clean up while keeping tests green
3. **On test failure or unexpected behavior:**
   - **Invoke `superpowers:systematic-debugging`** — diagnose root cause before
     proposing fixes
   - If the bug is separate from the current task, file a new bead:
     `bd create --title="Bug: ..." --type=bug --priority=1`
4. **For independent sub-tasks:**
   - Use `superpowers:dispatching-parallel-agents` or
     `superpowers:subagent-driven-development` for concurrency
5. **Close the issue:** `bd close <id>`
6. **Run tests** after each issue closure to confirm no regression:
   ```bash
   .venv_win\Scripts\python.exe -m pytest <touched-tests-path> -v
   ```

**Checklist before proceeding:**
- [ ] All plan steps implemented
- [ ] All unit tests passing (output shown, not just claimed)
- [ ] All beads issues closed
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

This is the **new loop** — every fix branch reviews itself with the QC skill
before opening a PR, so we catch our own regressions before human reviewers do.

### 6a. Commit + push the branch

1. **Commit with fork convention** — Conventional Commits with scope:
   ```bash
   git add <specific-files>   # never git add -A
   git commit -m "<type>(<scope>): <summary>

   <optional body>"
   ```
   Common scopes for this fork: `qc`, `beads`, `analysis`, `techtrade`,
   `backtest`, `fmp_cached`, `agents`, `tools`, `sec`, `notebooks`,
   `financialtoolkit`. Cite bead IDs with the `#NN (short description)` form.
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

### 6c. Fix loop (repeat until clean)

For each QC finding on the branch:

1. **Triage the finding:**
   - **Real bug that must be fixed:** proceed to step 2
   - **False positive / rubric-nit / low-value:** `bd close <finding-id>
     --reason "triage: <specific-reason>"` and skip to next
2. **Fix the finding:**
   - Return to Phase 4 (TDD) for the specific fix — write failing test, fix,
     confirm green
   - Or apply the suggested fix from the bead description if trivial
3. **Re-run Phase 5** quality gate (`simplify` + pre-commit + tests) on the
   incremental change
4. **Commit + push** the fix on the SAME branch:
   ```bash
   git add <fix-files>
   git commit -m "fix(qc): <summary> — addresses OpenBBTechnical-<id>"
   git push
   ```
5. **Close the finding bead:**
   ```bash
   bd close <finding-id> --reason "fixed in <sha> — <branch>"
   ```
6. **Re-run `/openbb-qualitycontrol branch`** — must be clean before exiting
   loop

### 6d. Verify the loop terminated cleanly

Before exiting Phase 6:
- [ ] `/openbb-qualitycontrol branch` returns 0 open findings on the branch's
      commits
- [ ] Every raised finding is either fixed (bead closed with "fixed in <sha>")
      or explicitly dropped (bead closed with "triage: <reason>")
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
2. **PR body template (fork custom, not upstream):**
   ```markdown
   ## Summary
   <1-2 paragraphs. `Closes OpenBBTechnical-<id> (short description)`.
   Links to design + plan docs.>

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

   ## Beads
   - `OpenBBTechnical-<id>`: <title> — CLOSED
   - <repeat per closed finding>

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ```
3. **After PR opens:** Address reviewer feedback via
   `superpowers:receiving-code-review` — verify feedback technically before
   implementing. Don't blindly agree.
4. **Update project knowledge if new patterns emerged:**
   - `bd remember "<key insight>"` for cross-session knowledge
   - `claude-md-management:revise-claude-md` if a new convention needs to land

**Checklist before declaring done:**
- [ ] PR merged to `develop`
- [ ] All beads issues closed with `--reason` citing merge SHA
- [ ] Tracking bead for the branch also closed
- [ ] `bd remember` used for any generalizable insights

---

## Phase 8: Cleanup

1. **Delete the local + remote branch** after merge:
   ```bash
   git checkout develop && git pull
   git branch -d <branch-name>
   git push origin --delete <branch-name>
   ```
2. **Verify beads state:**
   ```bash
   bd ready | grep QC-FIX      # confirm next branch is unblocked
   ```
3. **Session close:** report merged SHA + closed bead IDs + what's next

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
3. **Using TodoWrite/TaskCreate for permanent work** — beads (`bd`) is the only
   long-lived tracker; TaskCreate is fine for session-local workflow
4. **Claiming done without evidence** — show test output, not just assertions
5. **Blind agreement with review feedback** — verify technically first
6. **Committing without running pre-commit** — always run locally before push
7. **Skipping phases** — each gate exists because skipping it has burned us
   before
8. **Opening PR before Phase 6 QC-loop clean** — human reviewers are not your
   primary QC filter
9. **Branching off `qualitycontrol`** — always base off `origin/develop`; the
   `qualitycontrol` branch is for QC-run reference only

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
  - See `C:\Users\daaji\.claude\plans\dreamy-giggling-chipmunk.md` for the full
    "reuse cheatsheet"
- **Test commands:**
  ```bash
  # Unit tests (~1s, no API needed)
  .venv_win\Scripts\python.exe -m pytest <path> -m "not integration" -v

  # Integration tests (~19 min, needs fmp_cached API key)
  .venv_win\Scripts\python.exe -m pytest <path> -m "integration" -v
  ```
- **Beads for everything permanent** — `bd create`, `bd close`, `bd ready`,
  never markdown TODOs. Commit `.beads/issues.jsonl` at session close per
  Conservative profile.
