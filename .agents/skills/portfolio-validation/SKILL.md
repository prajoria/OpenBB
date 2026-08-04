---
name: portfolio-validation
description: Lightweight validation-and-small-fix workflow for the OpenBB portfolio work, operating DIRECTLY on the long-lived `portfolio_validations` branch (no feature branches, no worktrees) and opening sequential PRs from `portfolio_validations` into `portfolio`. A trimmed sibling of `openbb-dev-cycle` — it keeps the essential quality gates (TDD, harness `/verify`, local review, convergence-until-clean) but drops the heavy worktree isolation and the formal per-step GitHub-issue tree, because Deb reviews these changes manually for work validation. Use this instead of `openbb-dev-cycle` when the user is doing validation, testing-in-progress, or small fixes on the `portfolio_validations` branch. Do NOT use for large features (use `openbb-dev-cycle` with a `feat/pi-*` branch instead). Conservative git profile still applies: never commit/push/PR/merge without explicit user authorization.
---

# Portfolio Validation Cycle (v1)

A lightweight, gated workflow for **validation work and small fixes** on the
OpenBB portfolio stack. This is the informal sibling of `openbb-dev-cycle`:
same discipline on *correctness* (tests, real-path verify, review), far less
ceremony on *process* (no worktree isolation, no per-step GH-issue tree).

**Why it exists:** `portfolio_validations` is a long-lived branch used to keep
testing in progress and land small fixes quickly. Deb monitors the diffs
manually for work validation, so the heavyweight GH-issue-tree tracking that
`openbb-dev-cycle` mandates is redundant here. When work grows beyond "small
fix / validation," graduate it to `openbb-dev-cycle` on a proper `feat/pi-*`
branch.

## Branch topology (the one non-negotiable constraint)

```
        other teams ──▶ portfolio  (main feature branch, shared)
                            │  ▲
        absorb (pull) ──────┘  │  PR (sequential, one at a time)
                            ▼  │
                     portfolio_validations  ◀── ALL work happens here directly
```

1. **All changes happen DIRECTLY on `portfolio_validations`.** No feature
   branches, no worktrees, no `feat/pi-*` cut. Edit → test → verify → commit
   on `portfolio_validations` itself.
2. **PRs go `portfolio_validations` → `portfolio`, sequentially.** Open one PR,
   let it merge (or get Deb's sign-off), THEN open the next. Do **not** stack
   PRs or open a second while the first is unmerged. `portfolio` is the shared
   feature branch other teams consume — merges to it become available to them.
3. **Absorb FROM `portfolio` regularly.** Other teams merge into `portfolio`,
   so before starting new work (and before opening a PR) pull `portfolio` into
   `portfolio_validations` to stay current:
   ```bash
   git checkout portfolio_validations
   git fetch origin
   git merge origin/portfolio        # one-way absorb: portfolio -> portfolio_validations
   ```
4. **Fork-internal only, never cross-fork.** Every PR targets `portfolio`
   inside `prajoria/OpenBB`. Always pass `--repo prajoria/OpenBB --base portfolio`.
   Never target `OpenBB-finance/OpenBB` or any other fork. (Same hard rule as
   the rest of this repo — see CLAUDE.md.)
5. **Never propose `portfolio_validations` → `develop`.** Promotion toward
   `develop` is `portfolio`'s job and is gated on Daisy's explicit sign-off.

## Phases (6 phases — trimmed from openbb-dev-cycle's 10)

| # | Phase | Gate |
|---|-------|------|
| 1 | Absorb + scope | On `portfolio_validations`, up to date with `origin/portfolio`; change is confirmed "validation / small fix" (else escalate to `openbb-dev-cycle`) |
| 2 | TDD implementation | RED → GREEN → REFACTOR; unit tests green |
| 3 | Simplify + diagnostics | `simplify` applied; IDE diagnostics + black/ruff/pylint/mypy clean on changed `.py` |
| 4 | Harness verify | `/verify` (or a real run) drives the changed code path end-to-end; output captured |
| 5 | Local review + commit/push/PR | code-review (+ security-review if a security surface changed) triaged; then, **with user authorization**, commit → push → open ONE PR into `portfolio` |
| 6 | Converge + finish | Review findings resolved-with-verify or filed as a GH issue; CI green; on merge, append `docs/MEMORIES.md` and (if the PR closed issues) close them manually |

### Phase 1 — Absorb + scope
- `git checkout portfolio_validations`; `git fetch origin`;
  `git merge origin/portfolio` to absorb other teams' work.
- Confirm the ask is genuinely validation/small-fix. **Escalate to
  `openbb-dev-cycle`** (feature branch + GH-issue tree) if it's a real feature,
  a multi-file architectural change, or anything Deb would want tracked as a
  formal deliverable.

### Phase 2 — TDD implementation
- `superpowers:test-driven-development` — RED → GREEN → REFACTOR. Still
  mandatory even for small fixes; a regression test is the cheapest insurance.
- Reverse-verify every load-bearing test (CLAUDE.md R7/R11): mutate production
  → test must FAIL → restore. Prefer AST/`caplog` assertions over
  `inspect.getsource` textual checks.
- On failure: `superpowers:systematic-debugging`.

### Phase 3 — Simplify + diagnostics
- `simplify`; then run diagnostics and the CI-equivalent linters on changed
  Python: black(88)/ruff/pylint/mypy. Inline `# pylint: disable=...` only with
  a stated reason (e.g. `import-outside-toplevel` on an intentional lazy import).

### Phase 4 — Harness verify
- `/verify` — drive the REAL changed code path, not just pytest. Green tests
  exercise assumptions; `/verify` exercises the app. Capture stdout as evidence.
- For a running backend, curl the actual endpoint; for a renderer, feed a real
  payload through the real function. Green pytest alone is not sufficient.

### Phase 5 — Local review + commit/push/PR
- `coderabbit:code-review` and/or the built-in `code-review` agent on the local
  diff; add `security-review` if the change touches a security surface (HTML
  injection, auth, file paths, network). Triage: Apply-with-verify or file a GH
  issue. **Note:** CodeRabbit is not installed on this repo — expect 0 bot
  threads; rely on the built-in review agents.
- **Get explicit user authorization** (conservative git profile), then:
  ```bash
  git add <files>
  git commit -m "<type>(<scope>): <what>"   # cite the issue if one exists: Refs #NN / Closes #NN
  git push
  gh pr create --repo prajoria/OpenBB --base portfolio --head portfolio_validations \
    --title "..." --body "..."
  ```
  Open exactly ONE PR; do not open the next until this one lands.
  PR-body `Closes #NN` grammar: each clause on its own line, nothing trailing
  (the `check-closes-syntax` CI job enforces it).

### Phase 6 — Converge + finish
- Fan-out review on the PR (`code-review`, `security-review`) until: every
  finding is applied-and-verified or filed as a GH issue, and CI is green.
  Push a new commit each iteration or the review tools no-op.
- On merge into `portfolio`: because the repo default branch is `develop`,
  `Closes #NN` does **NOT** auto-close — close referenced issues manually,
  citing the merge commit.
- Append a one-paragraph entry to `docs/MEMORIES.md` describing what shipped.

## What carries over unchanged from openbb-dev-cycle
- Conservative git profile — no commit/push/PR/merge without explicit
  in-session authorization.
- Fork-internal PRs only (`--repo prajoria/OpenBB`); never cross-fork.
- Provider policy: `fmp_cached` preferred, `fmp` fallback (+ `area:fmp-cached-gap`
  issue), never yfinance.
- `.venv_portfolio` interpreter for all Python; never system Python.
- Test commands and the "mocks agree with themselves" anti-pattern rules
  (CLAUDE.md Testing Rules R1–R11).
- GitHub Issues remain the tracker for anything that needs tracking; beads is
  retired; cross-session memory lives in `docs/MEMORIES.md`.

## Key differences vs openbb-dev-cycle (at a glance)
| Aspect | openbb-dev-cycle | portfolio-validation |
|--------|------------------|----------------------|
| Working location | `feat/pi-*` branch cut from `portfolio` (worktree) | `portfolio_validations` directly |
| PR base | `portfolio` | `portfolio` |
| PR cadence | per-feature | sequential, one at a time |
| Absorb from `portfolio` | rebase/merge into feature branch | merge into `portfolio_validations` |
| Issue tracking | formal GH-issue tree per plan step | optional; Deb reviews diffs manually |
| Phases | 10 | 6 |
| Use when | non-trivial feature | validation / testing / small fix |

## Anti-patterns — do not do these
1. Cutting a `feat/pi-*` branch for a small validation fix — work directly on
   `portfolio_validations`.
2. Opening a second PR into `portfolio` before the first merges — PRs are
   sequential here.
3. Skipping the absorb-from-`portfolio` step and drifting behind other teams.
4. Committing/pushing/merging without explicit user authorization.
5. Opening a cross-fork PR, or a `portfolio_validations`/`portfolio` → `develop`
   PR without Daisy's sign-off.
6. Using this skill for a real feature — escalate to `openbb-dev-cycle`.
7. Claiming done without `/verify` evidence and reverse-verified tests.
