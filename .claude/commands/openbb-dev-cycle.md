# OpenBB Feature Development Cycle

A disciplined, gated workflow for developing features in the OpenBB platform. Each phase must complete before the next begins. No shortcuts.

## Overview

This skill enforces a 7-phase development lifecycle that chains together brainstorming, planning, isolation, TDD implementation, quality checks, review, and integration. It uses **beads** for task tracking and the **superpowers** skill suite for process discipline.

---

## Phase 1: Design & Brainstorming

**Gate:** Design spec approved by user

1. **Invoke `superpowers:brainstorming`** to explore the feature request
   - Understand purpose, constraints, success criteria
   - Propose 2-3 approaches with trade-offs and a recommendation
   - Use **Context7** (`resolve-library-id` → `query-docs`) to pull up-to-date docs for any library under consideration
   - Use `feature-dev:code-explorer` to understand existing codebase patterns that the feature touches
2. **Present design** section by section, get user approval after each
3. **Write design spec** to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
4. **Commit** the design spec

**Checklist before proceeding:**
- [ ] Design spec written and committed
- [ ] User has explicitly approved the design
- [ ] No open questions or TBDs in the spec

---

## Phase 2: Planning

**Gate:** Implementation plan approved by user

1. **Invoke `superpowers:writing-plans`** to turn the approved design into a step-by-step implementation plan
   - Identify all files to create/modify
   - Define dependencies between steps
   - Set review checkpoints (at least one per 3 steps)
   - Use `feature-dev:code-architect` if architecture decisions need deeper analysis
2. **File beads issues** for each deliverable:
   ```bash
   bd create --title="<step summary>" --description="<what and why>" --type=task --priority=2
   ```
   - Wire dependencies: `bd dep add <child> <parent>`
3. **Present plan** to user for approval

**Checklist before proceeding:**
- [ ] Plan file written with numbered steps
- [ ] Beads issues created for each deliverable
- [ ] Dependencies wired between issues
- [ ] User has approved the plan

---

## Phase 3: Workspace Isolation

**Gate:** Isolated workspace ready

1. **Invoke `superpowers:using-git-worktrees`** to create an isolated workspace
   - Or create a feature branch if worktrees aren't appropriate
2. **Claim first issue:** `bd update <id> --claim`

**Checklist before proceeding:**
- [ ] Working in isolated branch or worktree
- [ ] First issue claimed in beads

---

## Phase 4: TDD Implementation

**Gate:** All tests passing, all issues closed

This is the core loop. For each plan step:

1. **Claim the issue:** `bd update <id> --claim`
2. **Invoke `superpowers:test-driven-development`** — this is mandatory, not optional:
   - **Red:** Write failing tests that define the expected behavior
   - **Green:** Write the minimum code to make tests pass
   - **Refactor:** Clean up while keeping tests green
3. **On test failure or unexpected behavior:**
   - **Invoke `superpowers:systematic-debugging`** — diagnose root cause before proposing fixes
   - If the bug is separate from the current task, file a new bead: `bd create --title="Bug: ..." --type=bug --priority=1`
4. **For independent sub-tasks within a step:**
   - Use `superpowers:dispatching-parallel-agents` or `superpowers:subagent-driven-development` to run them concurrently
5. **Close the issue:** `bd close <id>`
6. **Run tests** after each issue closure to confirm nothing regressed:
   ```bash
   .venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v
   ```

**Checklist before proceeding:**
- [ ] All plan steps implemented
- [ ] All unit tests passing
- [ ] All beads issues closed
- [ ] No known bugs left unfiled

---

## Phase 5: Code Quality

**Gate:** Code simplified, diagnostics clean

1. **Invoke `simplify`** — review all changed code for:
   - Reuse opportunities
   - Unnecessary complexity
   - Consistency with existing patterns
2. **Run VS Code diagnostics:** `mcp__ide__getDiagnostics` to check for type errors, missing imports
3. **Invoke `superpowers:verification-before-completion`:**
   - Run full test suite
   - Run linters if configured
   - Confirm output before claiming anything is done
   - **Evidence before assertions** — never claim "all tests pass" without showing output

**Checklist before proceeding:**
- [ ] `simplify` review completed, issues fixed
- [ ] No diagnostic errors
- [ ] All tests confirmed passing with output shown

---

## Phase 6: Code Review

**Gate:** Review feedback addressed

1. **Invoke `superpowers:requesting-code-review`** — self-review against requirements:
   - Does every requirement from the design spec have a corresponding implementation?
   - Are edge cases handled?
   - Is error handling adequate?
2. **Use `feature-dev:code-reviewer`** for automated review focusing on:
   - Bugs and logic errors
   - Security vulnerabilities
   - Adherence to project conventions
3. **When receiving feedback** (from user or reviewer):
   - **Invoke `superpowers:receiving-code-review`** — verify feedback technically before implementing
   - Don't blindly agree — if feedback seems wrong, investigate and explain

**Checklist before proceeding:**
- [ ] Self-review completed
- [ ] All review findings addressed or explicitly deferred (with beads filed)
- [ ] User satisfied with the implementation

---

## Phase 7: Integration & Completion

**Gate:** Changes committed and pushed

1. **Invoke `superpowers:finishing-a-development-branch`** — guided decision:
   - Merge directly?
   - Create PR?
   - Cleanup needed?
2. **Run pre-flight checks:**
   ```bash
   bd preflight          # Lint, stale, orphan checks
   bd stats              # Verify issue counts
   ```
3. **Commit with descriptive message:**
   ```bash
   git add <specific files>
   git commit -m "feat(<scope>): <summary>

   <details>

   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
   ```
4. **Update project knowledge:**
   - **Invoke `claude-md-management:revise-claude-md`** to capture new patterns/conventions
   - `bd remember "<key insight>"` for persistent cross-session knowledge
5. **Sync:**
   ```bash
   git push
   bd dolt push    # if beads remote configured
   ```

**Checklist before declaring done:**
- [ ] All beads issues closed
- [ ] All tests passing (output shown)
- [ ] Changes committed with proper message
- [ ] CLAUDE.md updated if new conventions emerged
- [ ] Pushed to remote

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
| Receiving review feedback | `superpowers:receiving-code-review` |
| Feature branch complete | `superpowers:finishing-a-development-branch` |

## Anti-Patterns — Don't Do These

1. **Skipping brainstorming** — "It's simple" is where assumptions cause the most rework
2. **Writing code before tests** — TDD is gated, not optional
3. **Using TodoWrite/TaskCreate** — beads (`bd`) is the only task tracker
4. **Claiming done without evidence** — show test output, not just assertions
5. **Blind agreement with review feedback** — verify technically first
6. **Committing without running tests** — always verify before commit
7. **Skipping phases** — each gate exists because skipping it has burned us before

## OpenBB-Specific Rules

- **Always use `.venv_win`** — never system Python
- **`fmp_cached` is the only provider** — no `fmp` fallback, no yfinance
- **Test commands:**
  ```bash
  # Unit tests (~1s, no API needed)
  .venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

  # Integration tests (~19 min, needs fmp_cached API key)
  .venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v
  ```
- **Beads for everything** — `bd create`, `bd close`, `bd ready`, never markdown TODOs
