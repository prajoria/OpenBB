# Feature Branch Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the repository's permanent integration branches and prove every other local or remote branch is integrated, superseded, intentionally quarantined, or recovered before deleting obsolete refs.

**Architecture:** Treat branch cleanup as isolated delivery lanes with four permanent trunks: `develop`, `portfolio`, `portfolio_validations`, and `openbb_pine_support`. New or recovered Portfolio Intelligence work converges on `portfolio_validations`; Pine work converges on `openbb_pine_support`; promotion from `portfolio_validations` to `portfolio`, or any PR or merge into `develop`, requires Daisy's explicit instruction. Use ancestry, patch equivalence, file-level comparison, tests, and merged-PR evidence in that order; never infer safety from a closed PR, branch age, or naming convention alone.

**Tech Stack:** Git, GitHub CLI, PowerShell, Git Bash, pytest, Node.js, GitHub pull requests.

## Global Constraints

- This document is planning-only. Creating it does not authorize merges, branch deletion, or PR changes.
- Run all GitHub operations against `prajoria/OpenBB`; never create a cross-fork PR.
- Keep Pine work isolated from Portfolio Intelligence. Pine branches target `openbb_pine_support`, not `portfolio_validations`.
- Keep Portfolio Intelligence work isolated from Pine. In this checkout, Portfolio Intelligence branches target `portfolio_validations`, not `portfolio`.
- Never create or merge a PR into `develop` without Daisy explicitly requesting
  that exact operation. A cleanup request authorizes evidence gathering and
  deletion of already-integrated refs, not a new `develop` merge.
- The only Portfolio Validation promotion path is a fork-internal
  `portfolio_validations` -> `portfolio` PR. Create and merge it only after an
  explicit user request for that exact promotion PR; generic merge, push,
  cleanup, or side-branch PR instructions do not authorize it.
- The historical local-CI stack was merged and deleted during Tasks 1-7.
  Never recreate or re-run its `develop` merge steps from this document.
- Do not delete a branch checked out by any worktree.
- A branch is deletion-safe only after one of these proofs:
  1. its tip is an ancestor of the intended target; or
  2. `git cherry` reports no unique patches and the associated PR is merged; or
  3. content-level comparison proves every unique patch is superseded, with the proof recorded on the tracking issue or PR; or
  4. missing changes have gone through the intended target's full PR and validation cycle and that PR is merged.
- A closed-but-unmerged PR is not integration evidence.
- Before deleting any remote branch, record its full tip SHA in the cleanup issue or PR comment.
- Use `git push origin --delete $branch` only after remote verification. Delete local refs afterward with `git branch -d $branch`; do not use `-D` unless the content-level proof is documented.
- Any new commits must cite their GitHub issue and include the required `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer.

---

## Permanent Branch Allowlist

These branches are long-lived integration trunks and are outside every cleanup
candidate set. Never delete, rename, force-push, or repurpose them:

| Branch | Role | Historical evidence | GitHub protection at 2026-09-05 |
| --- | --- | --- | --- |
| `develop` | Fork default and upstream-sync mainline | Default branch; target of 117 PRs | Protected |
| `portfolio` | Portfolio Intelligence production integration | Declared long-lived Project #4 branch; target of 253 PRs | Not protected |
| `portfolio_validations` | Portfolio Intelligence validation and staging | Mandatory target for this checkout's side branches; target of 12 PRs | Not protected |
| `openbb_pine_support` | Separate Pine program integration | Target of 54 PRs and active Pine work | Not protected |

Add GitHub rulesets for the three currently unprotected trunks before or during
cleanup. Branch protection is defense in depth; the documented no-delete rules
remain authoritative even if GitHub settings drift.

The following refs are also excluded from automatic deletion:

- `trading_technicals`: historical program branch and former target of 27 PRs.
  It has one patch not represented on the current permanent trunks. Preserve it
  until Daisy explicitly approves a dedicated retirement audit.
- `__dolt_remote_info__`: Dolt transport metadata, not a normal code branch.
  Never process it with the code-branch cleanup loop.
- `origin/HEAD`: symbolic remote alias, not a branch.

---

## Execution Status

- The original `feat/*` and `feature/*` cleanup in Tasks 1-7 completed on
  2026-09-05. All scoped refs were proved integrated or superseded before
  deletion.
- The full-inventory continuation below was captured after that cleanup and is
  governed by issue #2035 (expand branch-hygiene plan to full remote
  inventory).
- Updating this plan does not authorize any merge, PR, or deletion. Each
  execution lane needs its own tracked issue and review cycle.

---

## Inventory Snapshot

Inventory captured on 2026-09-05 after `git fetch --prune origin`.

> **Historical completed phase:** Tasks 1-7 and this original `feat/*`
> inventory record the already-finished first cleanup. Do not re-run their
> commands. Current work begins at Phase 2 and uses the status tables there.

| Integration branch | Snapshot SHA |
| --- | --- |
| `origin/openbb_pine_support` | `6059fc7d9a0855aedc5a5d3ecd110caebeb60180` |
| `origin/test/develop-e2e-docker-stack` | `f8e7697f408ee856293013b557c4e349435bef92` |
| `origin/develop` | `db7f7fe673a416144055ddcdf459e76bd164afcb` |
| `origin/portfolio_validations` | `eba8be4e526cf2aa40100512c54798a8ffa5f03b` |

### Branch-to-target map

| Feature branch | Intended target | PR state | Current proof | Planned disposition |
| --- | --- | --- | --- | --- |
| `feat/0ru2-bars-csv-support` | `openbb_pine_support` | PR #485 merged | 0 unique patches | Recheck, then delete |
| `feat/0uh-coverage-manifest` | `openbb_pine_support` | PR #472 merged | 0 unique patches | Recheck, then delete |
| `feat/250-strategies-run-byo` | `openbb_pine_support` | PR #463 merged | 0 unique patches | Recheck, then delete |
| `feat/4d0-strategies-run-flip` | `openbb_pine_support` | PR #462 merged | 0 unique patches | Recheck, then delete |
| `feat/579-shim-reduction` | `openbb_pine_support` | PR #455 merged | 0 unique patches | Recheck, then delete |
| `feat/cht-conformance-strategy` | `openbb_pine_support` | PR #465 merged | 0 unique patches | Recheck, then delete |
| `feat/e07-grep-gate` | `openbb_pine_support` | PR #425 merged | 0 unique patches | Recheck, then delete |
| `feat/e21-scratch-clone-and-tag` | `openbb_pine_support` | PR #430 merged | 0 unique patches | Recheck, then delete |
| `feat/e22-filter-repo-run` | `openbb_pine_support` | PR #431 merged | 0 unique patches | Recheck, then delete |
| `feat/e31-submodule-bump` | `openbb_pine_support` | PR #433 merged | 0 unique patches | Recheck, then delete |
| `feat/e32-fmp-provider-refactor` | `openbb_pine_support` | PR #435 merged | 0 unique patches | Recheck, then delete |
| `feat/e33-byo-provider-refactor` | `openbb_pine_support` | PR #434 merged | 0 unique patches | Recheck, then delete |
| `feat/e35-shims-and-m1` | `openbb_pine_support` | PR #439 merged | 0 unique patches | Recheck, then delete |
| `feat/liz-executor-strategy` | `openbb_pine_support` | PR #461 merged | 0 unique patches | Recheck, then delete |
| `feat/ph0-conformance-strategy-fixtures` | `openbb_pine_support` | PR #469 merged | 0 unique patches | Recheck, then delete |
| `feat/e01-split-errors` | `openbb_pine_support` | PR #351 merged | 2 unique patches | Content-level reconciliation |
| `feat/e02-dispatcher-abstract-provider` | `openbb_pine_support` | PR #417 merged | 2 unique patches | Content-level reconciliation |
| `feat/e03-executor-split` | `openbb_pine_support` | PR #420 merged | 2 unique patches | Content-level reconciliation |
| `feat/e04-telemetry-injection` | `openbb_pine_support` | PR #353 merged | 2 unique patches | Content-level reconciliation |
| `feat/e05-pynecore-bridge` | `openbb_pine_support` | PR #350 merged | 2 unique patches | Content-level reconciliation |
| `feat/e06-test-split` | `openbb_pine_support` | PR #423 merged | 2 unique patches | Content-level reconciliation |
| `feat/e34-import-rewrite` | `openbb_pine_support` | PR #437 merged | 2 unique patches | Content-level reconciliation |
| `feat/pine-578/reshape-validation-metadata` | `openbb_pine_support` | PR #1017 closed, unmerged | 7 unique patches | Recover or prove superseded |
| `feat/pine-canonical-bars-and-capture-gh-967` | `openbb_pine_support` | PR #970 closed, unmerged | 7 unique patches | Recover or prove superseded |
| `feat/pine-hybrid-fixture-spec-gh-957` | `openbb_pine_support` | PR #960 closed, unmerged | 7 unique patches | Recover or prove superseded |
| `feat/local-ci-skill-gh-989` | `feat/local-ci-cli-gh-985` | PR #1015 open | 1 unique patch | Merge stack level 1, then delete |
| `feat/local-ci-cli-gh-985` | `test/develop-e2e-docker-stack` | PR #1009 open | 3 unique patches | Merge stack level 2, then delete |
| `feat/top50-intraday-gh-1986` | `portfolio_validations` | No PR; issue #1986 (test top-50 S&P intraday drift theory) open | 8 unique patches; active worktree | Complete dev cycle, merge, remove worktree, then delete |

The local-CI stack's main feature branch is `test/develop-e2e-docker-stack`. PR #948 is open from that branch to `develop`. It is not deletion-safe until PR #948 merges.

---

### Task 1: Freeze the cleanup inventory and ownership boundaries — COMPLETED

**Files:**
- Modify during execution: none
- Reference: `docs/superpowers/plans/2026-09-05-feature-branch-hygiene.md`

**Interfaces:**
- Consumes: Remote refs from `origin` and GitHub PR metadata.
- Produces: A timestamped branch/SHA inventory attached to the cleanup tracking issue.

- [ ] **Step 1: Refresh refs without changing branches**

Run:

```powershell
git fetch --prune origin
git status --short --branch
```

Expected: the current worktree remains on `portfolio_validations`, with no unexpected tracked-file changes.

- [ ] **Step 2: Capture every remote feature branch and tip**

Run:

```powershell
git ls-remote --heads origin 'refs/heads/feat/*'
```

Expected: every branch in the mapping table is present, or the execution report explains who already removed it and verifies that its intended target still contains the work.

- [ ] **Step 3: Confirm worktree ownership before any local deletion**

Run:

```powershell
git worktree list --porcelain
git for-each-ref --format='%(refname:short)' refs/heads/feat/
```

Expected: `feat/top50-intraday-gh-1986` remains protected because it is checked out at `H:\masterswork\git\OpenBB-Top50-Intraday-1986`.

- [ ] **Step 4: Create one cleanup issue per independent program**

Use separate issues so Pine, local-CI, and Portfolio Intelligence ownership cannot be mixed:

```powershell
gh issue create --repo prajoria/OpenBB --title "chore(pine): verify and retire merged feature branches" --body "Verify each Pine feat/* branch against openbb_pine_support using ancestry, patch equivalence, file-level comparison, and tests before deleting refs. Source plan: docs/superpowers/plans/2026-09-05-feature-branch-hygiene.md."
gh issue create --repo prajoria/OpenBB --title "chore(ci): drain local-CI stacked feature branches" --body "Drain PR #1015 into feat/local-ci-cli-gh-985, PR #1009 into test/develop-e2e-docker-stack, and PR #948 into develop. Delete each branch only after its target merge is verified. Source plan: docs/superpowers/plans/2026-09-05-feature-branch-hygiene.md."
```

Expected: two issue URLs. Do not attach the Pine or local-CI cleanup issues to Portfolio Intelligence Project #4 unless the user explicitly changes program ownership.

---

### Task 2: Retire the 15 patch-equivalent Pine branches — COMPLETED

**Files:**
- Modify during execution: none
- Test: Git ancestry and patch-equivalence checks

**Interfaces:**
- Consumes: The 15 Pine rows marked `0 unique patches`.
- Produces: Deleted remote refs with SHA and proof recorded on the Pine cleanup issue.

- [ ] **Step 1: Define the exact candidate set**

Run:

```powershell
$branches = @(
  'feat/0ru2-bars-csv-support',
  'feat/0uh-coverage-manifest',
  'feat/250-strategies-run-byo',
  'feat/4d0-strategies-run-flip',
  'feat/579-shim-reduction',
  'feat/cht-conformance-strategy',
  'feat/e07-grep-gate',
  'feat/e21-scratch-clone-and-tag',
  'feat/e22-filter-repo-run',
  'feat/e31-submodule-bump',
  'feat/e32-fmp-provider-refactor',
  'feat/e33-byo-provider-refactor',
  'feat/e35-shims-and-m1',
  'feat/liz-executor-strategy',
  'feat/ph0-conformance-strategy-fixtures'
)
```

Expected: exactly 15 branch names.

- [ ] **Step 2: Re-prove zero unique patches at execution time**

Run:

```powershell
foreach ($branch in $branches) {
  $unique = @(git cherry origin/openbb_pine_support "origin/$branch" |
    Where-Object { $_ -like '+*' })
  if ($unique.Count -ne 0) {
    throw "$branch has $($unique.Count) unique patch(es); stop deletion"
  }
  "$branch`t$(git rev-parse "origin/$branch")`tpatch-equivalent"
}
```

Expected: 15 `patch-equivalent` records and no exception.

- [ ] **Step 3: Confirm every associated PR is merged**

Run:

```powershell
$prs = 485,472,463,462,455,465,425,430,431,433,435,434,439,461,469
foreach ($pr in $prs) {
  gh pr view $pr --repo prajoria/OpenBB --json number,state,mergedAt,baseRefName `
    --jq '[.number,.state,.mergedAt,.baseRefName] | @tsv'
}
```

Expected: every row reports `MERGED` and base `openbb_pine_support`. Stop if any row differs.

- [ ] **Step 4: Record SHAs and proof on the Pine cleanup issue**

Post the Step 2 output and the PR list as a comment. Do not include credentials, local home-directory paths, or other private data.

- [ ] **Step 5: Delete only the verified remote refs**

Run:

```powershell
foreach ($branch in $branches) {
  git push origin --delete $branch
}
```

Expected: 15 successful remote deletions.

- [ ] **Step 6: Remove matching local refs if they exist**

Run:

```powershell
foreach ($branch in $branches) {
  if (git show-ref --verify --quiet "refs/heads/$branch") {
    git branch -d $branch
  }
}
git fetch --prune origin
```

Expected: no candidate branch remains locally or under `refs/remotes/origin/`.

---

### Task 3: Reconcile the seven merged Pine branches with nonzero patch IDs — COMPLETED

**Files:**
- Potentially modify on a new Pine reconciliation branch: only files proven missing from `openbb_pine_support`
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/`

**Interfaces:**
- Consumes: Seven merged PR branches whose historical patch IDs differ from the target.
- Produces: Per-branch supersession proof or a merged reconciliation PR.

- [ ] **Step 1: Define the forensic-review set**

```powershell
$branches = @(
  'feat/e01-split-errors',
  'feat/e02-dispatcher-abstract-provider',
  'feat/e03-executor-split',
  'feat/e04-telemetry-injection',
  'feat/e05-pynecore-bridge',
  'feat/e06-test-split',
  'feat/e34-import-rewrite'
)
```

- [ ] **Step 2: Produce commit and file-level evidence for each branch**

Run for each branch:

```powershell
$branch = 'feat/e01-split-errors'
git log --left-right --cherry-pick --oneline origin/openbb_pine_support..."origin/$branch"
git diff --name-status origin/openbb_pine_support..."origin/$branch"
git range-diff "$(git merge-base origin/openbb_pine_support "origin/$branch")".."origin/$branch" `
  "$(git merge-base origin/openbb_pine_support "origin/$branch")"..origin/openbb_pine_support
```

Repeat with each value from `$branches`.

Expected: enough evidence to classify each unique patch as either semantically present/superseded or genuinely missing. A merged PR alone is not sufficient because squash merges alter patch ancestry.

- [ ] **Step 3: Stop and recover genuinely missing behavior**

If any behavior is missing, create a Pine-owned reconciliation branch:

```powershell
$pineIssue = gh issue list --repo prajoria/OpenBB --state open `
  --search '"chore(pine): verify and retire merged feature branches" in:title' `
  --json number --jq '.[0].number'
git switch --create "fix/pine-branch-reconciliation-gh-$pineIssue" origin/openbb_pine_support
```

Apply only the missing hunks, not whole obsolete commits. Run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests -m "not integration" -v
git diff --check
```

Expected: Pine tests pass and `git diff --check` emits no output.

- [ ] **Step 4: Merge missing behavior through `openbb_pine_support`**

Commit with the Pine cleanup issue reference, push, and open a fork-internal PR:

```powershell
git push -u origin "fix/pine-branch-reconciliation-gh-$pineIssue"
gh pr create --repo prajoria/OpenBB --base openbb_pine_support `
  --head "fix/pine-branch-reconciliation-gh-$pineIssue" `
  --title "fix(pine): reconcile retained feature-branch changes (#$pineIssue)" `
  --body "Closes #$pineIssue."
```

Expected: a PR targeting `openbb_pine_support`. Wait for required checks and merge it before proceeding.

- [ ] **Step 5: Delete each original branch only after documentation**

For every superseded branch, post a concrete comment:

```powershell
$branch = 'feat/e01-split-errors'
$tip = git rev-parse "origin/$branch"
$target = git rev-parse origin/openbb_pine_support
gh issue comment $pineIssue --repo prajoria/OpenBB --body `
  "Branch $branch at $tip is superseded by openbb_pine_support at $target; file-level comparison and Pine tests confirm no missing behavior."
```

For every reconciled branch, post its actual merged PR:

```powershell
$branch = 'feat/e01-split-errors'
$tip = git rev-parse "origin/$branch"
$reconciliationPr = gh pr list --repo prajoria/OpenBB --state merged `
  --head "fix/pine-branch-reconciliation-gh-$pineIssue" `
  --json number,mergeCommit --jq '.[0]'
gh issue comment $pineIssue --repo prajoria/OpenBB --body `
  "Branch $branch at $tip was reconciled by PR #$($reconciliationPr.number), merged into openbb_pine_support at $($reconciliationPr.mergeCommit.oid)."
```

Then run:

```powershell
foreach ($branch in $branches) {
  git push origin --delete $branch
}
git fetch --prune origin
```

Expected: all seven refs are absent only after their evidence is recorded.

---

### Task 4: Resolve the three closed, unmerged Pine PR branches — COMPLETED

**Files:**
- Potentially modify on a new Pine recovery branch: files selected from the three closed branches
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/`

**Interfaces:**
- Consumes: PR #1017, PR #970, and PR #960 plus their associated branch tips.
- Produces: A merged recovery PR or documented supersession for each branch.

- [ ] **Step 1: Read the closed PR decisions**

Run:

```powershell
gh pr view 1017 --repo prajoria/OpenBB --comments
gh pr view 970 --repo prajoria/OpenBB --comments
gh pr view 960 --repo prajoria/OpenBB --comments
```

Expected: identify whether each PR was closed as obsolete, replaced, or incomplete. Do not reopen or delete anything yet.

- [ ] **Step 2: Compare each branch against the intended target**

Run:

```powershell
$branches = @(
  'feat/pine-578/reshape-validation-metadata',
  'feat/pine-canonical-bars-and-capture-gh-967',
  'feat/pine-hybrid-fixture-spec-gh-957'
)
foreach ($branch in $branches) {
  "===== $branch ====="
  git log --left-right --cherry-pick --oneline origin/openbb_pine_support..."origin/$branch"
  git diff --name-status origin/openbb_pine_support..."origin/$branch"
}
```

Expected: a branch-by-branch list of missing or superseded files. The current snapshot reports seven unique patches for each branch, so none is eligible for automatic deletion.

- [ ] **Step 3: Recover retained work through a fresh Pine PR**

For any still-required work:

```powershell
$pineIssue = gh issue list --repo prajoria/OpenBB --state open `
  --search '"chore(pine): verify and retire merged feature branches" in:title' `
  --json number --jq '.[0].number'
git switch --create "fix/pine-closed-branch-recovery-gh-$pineIssue" origin/openbb_pine_support
```

Apply only retained changes, then run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests -m "not integration" -v
git diff --check
```

Expected: all Pine tests pass and no whitespace errors remain.

Open and merge a PR to `openbb_pine_support` using the same fork-internal process as Task 3.

- [ ] **Step 4: Document superseded work instead of silently dropping it**

For a branch whose work is intentionally obsolete, comment on its closed PR with concrete Git evidence:

```powershell
$branch = 'feat/pine-hybrid-fixture-spec-gh-957'
$pr = 960
$tip = git rev-parse "origin/$branch"
$target = git rev-parse origin/openbb_pine_support
$files = git diff --name-only "origin/$branch"...origin/openbb_pine_support
$body = @"
Cleanup verification: branch $branch at $tip is superseded by openbb_pine_support at $target.
Compared files:
$($files -join "`n")
No retained behavior remains after file-level comparison. The remote branch can be deleted.
"@
gh pr comment $pr --repo prajoria/OpenBB --body $body
```

Expected: each deletion has an auditable rationale.

- [ ] **Step 5: Delete only resolved branches**

```powershell
git push origin --delete feat/pine-578/reshape-validation-metadata
git push origin --delete feat/pine-canonical-bars-and-capture-gh-967
git push origin --delete feat/pine-hybrid-fixture-spec-gh-957
git fetch --prune origin
```

Expected: all three branches are removed only after recovery or supersession proof.

---

### Task 5: Drain the local-CI stack bottom-up — COMPLETED

**Historical result:** PR #1015 merged into `feat/local-ci-cli-gh-985`, PR
#1009 merged into `test/develop-e2e-docker-stack`, and PR #948 merged into
`develop` under the authorization that applied during the completed first
cleanup. The three source refs were deleted. Post-merge review defects were
corrected by PR #2031.

The original executable merge commands are intentionally removed from this
record. This completed task is evidence only and provides no authorization to
create or merge another `develop` PR.

---

### Task 6: Complete the active Top-50 intraday branch through validation — COMPLETED

**Files:**
- Existing worktree: `H:\masterswork\git\OpenBB-Top50-Intraday-1986`
- Modify as required by issue #1986 (test top-50 S&P intraday drift theory):
  - `openbb_platform/extensions/backtest/README.md`
  - `openbb_platform/extensions/backtest/examples/top50_intraday_drift.py`
  - `openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py`
  - `openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py`
- Reference:
  - `docs/superpowers/specs/2026-08-13-top50-intraday-drift-design.md`
  - `docs/superpowers/plans/2026-08-13-top50-intraday-drift.md`

**Interfaces:**
- Consumes: Eight local commits on `feat/top50-intraday-gh-1986` and the existing dedicated worktree.
- Produces: A reviewed PR merged into `portfolio_validations`, followed by safe worktree and branch cleanup.

- [ ] **Step 1: Do not delete the active worktree branch**

Run:

```powershell
git worktree list --porcelain
git -C H:\masterswork\git\OpenBB-Top50-Intraday-1986 status --short --branch
```

Expected: the branch is still checked out and its worktree state is known before any operation.

- [ ] **Step 2: Rebase or merge the current validation baseline in the worktree**

From the Top-50 worktree:

```powershell
git -C H:\masterswork\git\OpenBB-Top50-Intraday-1986 fetch origin
git -C H:\masterswork\git\OpenBB-Top50-Intraday-1986 rebase origin/portfolio_validations
```

Expected: the eight commits replay cleanly or conflicts are resolved without dropping intended behavior.

- [ ] **Step 3: Run the targeted backtest validation**

```powershell
H:\masterswork\git\OpenBB-Top50-Intraday-1986\.venv_portfolio\Scripts\python.exe -m pytest `
  H:\masterswork\git\OpenBB-Top50-Intraday-1986\openbb_platform\extensions\backtest\tests\unit\test_intraday_drift.py -v
git -C H:\masterswork\git\OpenBB-Top50-Intraday-1986 diff --check origin/portfolio_validations...HEAD
```

Expected: all intraday-drift tests pass and `git diff --check` emits no output.

- [ ] **Step 4: Complete the internal development cycle**

Push the branch and open a fork-internal PR:

```powershell
git -C H:\masterswork\git\OpenBB-Top50-Intraday-1986 push -u origin feat/top50-intraday-gh-1986
gh pr create --repo prajoria/OpenBB --base portfolio_validations `
  --head feat/top50-intraday-gh-1986 `
  --title "feat(backtest): test top-50 S&P intraday drift theory (#1986)" `
  --body "Closes #1986."
```

Expected: a PR to `portfolio_validations`, never directly to `portfolio`.

- [ ] **Step 5: Merge, remove the worktree, and delete the local branch**

After review and CI pass:

```powershell
$top50Pr = gh pr list --repo prajoria/OpenBB --state open `
  --head feat/top50-intraday-gh-1986 --json number --jq '.[0].number'
gh pr merge $top50Pr --repo prajoria/OpenBB --merge --delete-branch
git fetch --prune origin
git worktree remove H:\masterswork\git\OpenBB-Top50-Intraday-1986
git branch -d feat/top50-intraday-gh-1986
```

Expected: the PR is merged into `portfolio_validations`, the dedicated worktree is removed, and no local or remote Top-50 feature ref remains.

---

### Task 7: Perform the final branch-hygiene audit — COMPLETED

**Files:**
- Modify during execution: none
- Test: Git refs and GitHub PR inventory

**Interfaces:**
- Consumes: Completed Pine, local-CI, and Portfolio Intelligence cleanup lanes.
- Produces: A final audit comment proving no obsolete `feat/*` branches remain.

- [ ] **Step 1: Refresh and list remaining feature refs**

```powershell
git fetch --prune origin
git ls-remote --heads origin 'refs/heads/feat/*'
git for-each-ref --format='%(refname:short)' refs/heads/feat/
git worktree list --porcelain
```

Expected: no obsolete feature refs. Any remaining branch must have an open PR or active issue and a documented owner.

- [ ] **Step 2: Cross-check GitHub PRs**

```powershell
gh pr list --repo prajoria/OpenBB --state open --limit 500 `
  --json number,title,headRefName,baseRefName,url `
  --jq '.[] | select(.headRefName | startswith("feat/"))'
```

Expected: every remaining open feature PR maps to a live branch and its intended target; no merged or superseded branch remains.

- [ ] **Step 3: Verify protected integration branches still exist**

```powershell
git ls-remote --heads origin `
  refs/heads/openbb_pine_support `
  refs/heads/test/develop-e2e-docker-stack `
  refs/heads/develop `
  refs/heads/portfolio_validations
```

Expected: `openbb_pine_support`, `develop`, and `portfolio_validations` exist. `test/develop-e2e-docker-stack` may be absent only if PR #948 merged and deleted it.

- [ ] **Step 4: Record the final audit**

Build the audit from the actual remaining refs and comment on each cleanup issue:

```powershell
$remaining = @(git ls-remote --heads origin 'refs/heads/feat/*' |
  ForEach-Object { ($_ -split "`t")[1] -replace '^refs/heads/','' })
$remainingText = if ($remaining.Count -eq 0) {
  'none'
} else {
  $remaining -join "`n"
}
$body = @"
Branch hygiene complete.
- Remaining feat refs:
$remainingText
- Protected integration branches: verified.
- Cross-fork PRs created: none.
- Deleted-ref merge and supersession proofs are recorded in earlier comments.
"@
$cleanupIssues = @(
  gh issue list --repo prajoria/OpenBB --state open `
    --search '"chore(pine): verify and retire merged feature branches" in:title' `
    --json number --jq '.[0].number'
  gh issue list --repo prajoria/OpenBB --state open `
    --search '"chore(ci): drain local-CI stacked feature branches" in:title' `
    --json number --jq '.[0].number'
)
foreach ($issue in $cleanupIssues) {
  gh issue comment $issue --repo prajoria/OpenBB --body $body
}
```

Expected: the cleanup is auditable and each program remains isolated on its intended target.

---

## Phase 2: Full Branch Inventory and Cleanup

Inventory captured on 2026-09-05 after `git fetch --prune origin`. The
snapshot contains 32 real remote branches, plus the local `origin/HEAD`
symbolic alias. Four
are permanent trunks, one is preserved pending a dedicated retirement
decision, one is a develop-only quarantine, one is Dolt metadata, and 25 are
remote cleanup candidates. Two additional cleanup candidates exist only as
local refs.

### Complete remote branch classification

`Evidence target` is the branch against which existing integration or
supersession is proved. `Recovery target` is where retained missing work may
land. A row naming `portfolio` as its evidence target does not authorize a new
PR to `portfolio`; missing Portfolio Intelligence work is recovered through
`portfolio_validations` and waits there for a separately authorized promotion.

The `Status` column is the task tracker and must be updated in place during
execution. Allowed active values are `READY-PROOF`, `NEEDS-RECONCILIATION`,
`ACTIVE-PR`, and `BLOCKED-AUTH`. Allowed terminal values are
`KEPT-PERMANENT`, `KEPT-HOLD`, `KEPT-METADATA`, `DELETED-PROVED`, and
`DELETED-RECONCILED`. A cleanup issue cannot close while any row remains in an
active state other than `BLOCKED-AUTH`.

| Branch | Status | Snapshot tip (abbreviated; not deletion proof) | PR evidence | Evidence target | Recovery target | Snapshot result and required disposition |
| --- | --- | --- | --- | --- | --- | --- |
| `develop` | `KEPT-PERMANENT` | `7199c0a60941` | 117 target PRs | Permanent | None | **Never delete:** protected default/mainline branch |
| `portfolio` | `KEPT-PERMANENT` | `8fe0ff748` | 253 target PRs | Permanent | None | **Never delete:** Portfolio Intelligence production integration |
| `portfolio_validations` | `KEPT-PERMANENT` | `e2c03108b` | 12 target PRs | Permanent | None | **Never delete:** validation/staging integration |
| `openbb_pine_support` | `KEPT-PERMANENT` | `6059fc7d9` | 54 target PRs | Permanent | None | **Never delete:** separate Pine integration |
| `trading_technicals` | `KEPT-HOLD` | `195b63422` | PR #101 merged to `develop`; 27 historical target PRs | Hold | None | **Preserve:** one patch differs from all permanent trunks; dedicated retirement approval required |
| `__dolt_remote_info__` | `KEPT-METADATA` | `fbdc924a3` | Not a code PR branch | Metadata | None | **Exclude:** never pass to code-branch deletion commands |
| `sync/upstream-openbb-2026-07-19` | `BLOCKED-AUTH` | `88dcdb226` | PR #895 open to `develop` | `develop` | Blocked | **Quarantine:** ten unique patches; no PR update, merge, close, or deletion without Daisy explicitly directing the `develop` operation |
| `chore/bump-pynecore-alpha-27v7-9cae` | `DELETED-PROVED` | `57d766cf6` | PR #480 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `chore/bump-pynecore-p2-wave1` | `DELETED-RECONCILED` | `dfd7c60e4` | PR #458 closed, unmerged | `openbb_pine_support` | `openbb_pine_support` | Superseded by the later Pine submodule pointer; proof recorded on #2037 before deletion |
| `chore/bump-pynecore-p2-wave1-v2` | `DELETED-PROVED` | `7da8320c9` | PR #460 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `chore/e41-unfreeze-rescope` | `DELETED-PROVED` | `a5de7c9c3` | PR #440 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `docs/bl57-alpha-quickstart-supported` | `DELETED-PROVED` | `3173a4811` | PR #482 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `docs/dyhr-tv-walkthrough` | `DELETED-PROVED` | `caa364ed8` | PR #486 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `docs/e42-manifest-prd-fixups` | `DELETED-PROVED` | `9b8477553` | PR #442 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `docs/pine-claude-md-merge-rule-learnings` | `DELETED-RECONCILED` | `4f8d10830` | PR #921 merged | `openbb_pine_support` | `openbb_pine_support` | Documentation retained through PR #921; source branch deleted after merge |
| `fix/6atb-coverage-tool` | `DELETED-PROVED` | `352c28da2` | PR #475 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `fix/tech-debt-post-develop-sync` | `DELETED-RECONCILED` | `d2f862670` | No PR | `openbb_pine_support` | `openbb_pine_support` | Obsolete alias fix superseded by the current `session_date` and `AliasChoices` implementation; proof recorded on #2037 before deletion |
| `plan/pine-extraction-2b` | `DELETED-PROVED` | `c5abf3c94` | PR #429 merged | `openbb_pine_support` | `openbb_pine_support` | Zero unique patches; record proof, then delete |
| `chore/delete-portfolio-app-gh-1629` | `DELETED-PROVED` | `07b6639af` | PR #1631 merged | `portfolio` | `portfolio_validations` | Zero unique patches; record proof, then delete |
| `chore/move-techtrade-notebooks-gh-1679` | `DELETED-PROVED` | `2f03dcb74` | PR #1690 merged | `portfolio` | `portfolio_validations` | Zero unique patches; record proof, then delete |
| `chore/reconcile-tools-gh-1628` | `DELETED-PROVED` | `be5aa92d3` | PR #1630 merged | `portfolio` | `portfolio_validations` | Zero unique patches; record proof, then delete |
| `fix/pi-portfolio-backend-run-gh-1786` | `DELETED-PROVED` | `49e861c3f` | PR #1787 merged | `portfolio` | `portfolio_validations` | Zero unique patches; delete remote and matching stale local ref |
| `fix/pi-portfolio-intel-obbject-openapi-gh-1788` | `DELETED-PROVED` | `541c27517` | PR #1791 merged | `portfolio` | `portfolio_validations` | Zero unique patches; delete remote and matching stale local ref |
| `fmp_tradingv2` | `DELETED-PROVED` | `eeaaaf383` | Historical integration branch | `portfolio` | `portfolio_validations` | Zero commits and patches unique to `portfolio`; record proof, then delete |
| `journaling-primitive` | `DELETED-PROVED` | `8200698b1` | Historical integration branch | `portfolio` | `portfolio_validations` | Zero commits and patches unique to `portfolio`; record proof, then delete |
| `chore/absorb-develop-into-portfolio` | `DELETED-RECONCILED` | `5f1940a36` | PR #762 closed, unmerged | `portfolio` | `portfolio_validations` | All files present or superseded in pv; paper_trading migration from old portfolio arch; deleted per #2038 Task 11 |
| `chore/openbb-dev-cycle-v2-2026-07-04` | `DELETED-RECONCILED` | `c8fb15cb7` | No PR | `portfolio_validations` | `portfolio_validations` | SKILL.md superseded by newer version in pv; deleted per #2038 Task 11 |
| `copilot/create-vs-code-extension-spec` | `DELETED-RECONCILED` | `a98761388` | PR #1803 closed, unmerged | `portfolio` | `portfolio_validations` | PRD superseded by newer version in pv; deleted per #2038 Task 11 |
| `fix/tech-debt-to-develop` | `DELETED-RECONCILED` | `2af2b5b9e` | PR #742 closed, unmerged | `portfolio_validations` | `portfolio_validations` | fmp_trading Pydantic v2 fixes and pytest.ini superseded in pv; deleted per #2038 Task 11 |
| `fix/techtrade-python-constraint` | `DELETED-RECONCILED` | `d444443c9` | PR #481 closed, unmerged | `portfolio_validations` | `portfolio_validations` | Python constraint fix superseded in pv (dev_install.py, pyproject.toml evolved); deleted per #2038 Task 11 |
| `qualitycontrol` | `DELETED-RECONCILED` | `9427f6030` | No PR | `portfolio_validations` | `portfolio_validations` | QC skill + .beads data use retired bd system; concept never adopted in pv; deleted per #2038 Task 11 |
| `quant_trading` | `DELETED-RECONCILED` | `92ef1def6` | No PR | `portfolio_validations` | `portfolio_validations` | Copilot CLI parity artifacts obsolete (unadopted format); financialtoolkit fix superseded in pv; deleted per #2038 Task 11 |

### Complete local branch classification

The permanent local `develop` and current `portfolio_validations` refs are not
cleanup candidates. The plan-update branch for issue #2035 (expand
branch-hygiene plan to full remote inventory) remains active until its PR
merges into `portfolio_validations`.

| Local branch | Status | Snapshot tip | Remote ref | Required disposition |
| --- | --- | --- | --- | --- |
| `docs/pi-asof-snapshot-spec-gh-1932` | `DELETED-RECONCILED` | `be92a07c1bef` | Gone | PR #1970 merged into `portfolio` 2026-08-10; sole file blob `97414885f44cea8122939ff31fadf068f2667c14` confirmed present in `origin/portfolio_validations`; no worktree; force-deleted via `git branch -D` under documented-content-proof exception (Task 12, #2038, #2039) |
| `fix/local-ci-post-merge-review-gh-2030` | `DELETED-PROVED` | `38349dd3d551` | Gone | PR #2031 merged into `develop`; tip confirmed ancestor of `origin/develop` via `git merge-base --is-ancestor`; upstream set to `origin/develop` after ancestry proof; deleted via `git branch -d` (Task 12, #2039) |
| `fix/pi-portfolio-backend-run-gh-1786` | `DELETED-PROVED` | `49e861c3fac7` | Gone | Delete locally after the corresponding zero-patch remote cleanup |
| `fix/pi-portfolio-intel-obbject-openapi-gh-1788` | `DELETED-PROVED` | `541c275176e2` | Gone | Delete locally after the corresponding zero-patch remote cleanup |

### Target policy for this cleanup

1. New Pine recovery PRs may target only `openbb_pine_support`.
2. New Portfolio Intelligence, TechTrade, tooling, documentation, and quality
   recovery PRs may target only `portfolio_validations`.
3. Existing merged PRs into `portfolio` may be used as deletion evidence, but
   this plan does not authorize another direct PR to `portfolio`.
4. No new PR or merge may target `develop`. Already-merged `develop` history
   may be inspected only to prove a stale branch safe to delete.
5. PR #895 and `sync/upstream-openbb-2026-07-19` remain untouched until Daisy
   explicitly authorizes that exact `develop` operation.

---

### Task 8: Freeze the full inventory and protect permanent trunks

**Files:**
- Modify during execution: none
- Reference: `docs/superpowers/plans/2026-09-05-feature-branch-hygiene.md`

**Interfaces:**
- Consumes: The complete remote and local classification above.
- Produces: An auditable issue comment and confirmed no-delete rules for all
  permanent trunks.

- [ ] **Step 1: Refresh and compare the live branch set**

```powershell
git fetch --prune origin
$remote = @(git for-each-ref refs/remotes/origin `
  --format='%(refname:strip=3)' | Where-Object { $_ -and $_ -ne 'HEAD' })
$local = @(git for-each-ref refs/heads --format='%(refname:short)')
$remote
$local
```

Expected: every live branch is present in one of the tables above, except the
active issue #2035 (expand branch-hygiene plan to full remote inventory)
delivery branch. Stop and add any newly discovered branch before proceeding.

- [ ] **Step 2: Verify the permanent allowlist**

```powershell
$permanent = @(
  'develop',
  'portfolio',
  'portfolio_validations',
  'openbb_pine_support'
)
foreach ($branch in $permanent) {
  git show-ref --verify --quiet "refs/remotes/origin/$branch"
  if ($LASTEXITCODE -ne 0) {
    throw "Permanent branch missing: $branch"
  }
}
```

Expected: all four remote refs exist.

- [ ] **Step 3: Record immutable tips on issue #2035**

```powershell
$body = $permanent | ForEach-Object {
  "$_ : $(git rev-parse "origin/$_")"
}
gh issue comment 2035 --repo prajoria/OpenBB --body `
  "Permanent branch pre-cleanup tips:`n$($body -join "`n")"
```

Expected: issue #2035 contains all four full SHAs before any deletion.

- [ ] **Step 4: Verify GitHub protection coverage**

```powershell
gh api repos/prajoria/OpenBB/branches?per_page=100 --paginate `
  --jq '.[] | select(.name == "develop" or .name == "portfolio" or .name == "portfolio_validations" or .name == "openbb_pine_support") | [.name,.protected] | @tsv'
```

Expected at snapshot time: only `develop` reports `true`. Record the gap on
issue #2035. Ruleset creation is a separate repository-administration action;
absence of a ruleset never makes a permanent branch deletion-safe.

---

### Task 9: Delete branches already proved integrated

**Files:**
- Modify during execution: none
- Test: PR state, `git cherry`, commit reachability, and post-delete ref audit

**Interfaces:**
- Consumes: Merged zero-patch rows from the full inventory.
- Produces: Deleted remote and matching stale local refs with proof on issue
  #2035.

- [ ] **Step 1: Define the exact zero-patch candidate sets**

```powershell
$pineMerged = @(
  'chore/bump-pynecore-alpha-27v7-9cae',
  'chore/bump-pynecore-p2-wave1-v2',
  'chore/e41-unfreeze-rescope',
  'docs/bl57-alpha-quickstart-supported',
  'docs/dyhr-tv-walkthrough',
  'docs/e42-manifest-prd-fixups',
  'fix/6atb-coverage-tool',
  'plan/pine-extraction-2b'
)
$portfolioMerged = @(
  'chore/delete-portfolio-app-gh-1629',
  'chore/move-techtrade-notebooks-gh-1679',
  'chore/reconcile-tools-gh-1628',
  'fix/pi-portfolio-backend-run-gh-1786',
  'fix/pi-portfolio-intel-obbject-openapi-gh-1788',
  'fmp_tradingv2',
  'journaling-primitive'
)
```

Expected: eight Pine and seven Portfolio candidates.

- [ ] **Step 2: Re-prove patch equivalence**

```powershell
foreach ($branch in $pineMerged) {
  $unique = @(git cherry origin/openbb_pine_support "origin/$branch" |
    Where-Object { $_ -like '+*' })
  if ($unique.Count -ne 0) {
    throw "$branch is no longer patch-equivalent to openbb_pine_support"
  }
}
foreach ($branch in $portfolioMerged) {
  $unique = @(git cherry origin/portfolio "origin/$branch" |
    Where-Object { $_ -like '+*' })
  if ($unique.Count -ne 0) {
    throw "$branch is no longer patch-equivalent to portfolio"
  }
}
```

Expected: no exception and no unique patch.

- [ ] **Step 3: Verify merged PR evidence where a PR exists**

```powershell
$prs = 480,460,440,482,486,442,475,429,1631,1690,1630,1787,1791
foreach ($pr in $prs) {
  gh pr view $pr --repo prajoria/OpenBB `
    --json number,state,baseRefName,mergeCommit `
    --jq '[.number,.state,.baseRefName,.mergeCommit.oid] | @tsv'
}
```

Expected: every PR reports `MERGED` and the target shown in the inventory.
`fmp_tradingv2` and `journaling-primitive` use zero-commit reachability proof
instead because they have no single branch-closing PR.

- [ ] **Step 4: Record full tips, then delete only the proved refs**

```powershell
$candidates = @($pineMerged) + @($portfolioMerged)
$proof = foreach ($branch in $candidates) {
  "$branch : $(git rev-parse "origin/$branch")"
}
gh issue comment 2035 --repo prajoria/OpenBB --body `
  "Patch-equivalent deletion set:`n$($proof -join "`n")"
foreach ($branch in $candidates) {
  git push origin --delete $branch
}
git fetch --prune origin
```

Expected: all 15 remote refs are absent. Delete matching local refs with
`git branch -d` only after confirming they are not checked out by a worktree.
In the next plan-status commit, change each deleted remote row and any deleted
matching local row from `READY-PROOF` to `DELETED-PROVED`.

---

### Task 10: Resolve the remaining Pine branches

**Files:**
- Potentially modify on a Pine recovery branch: only retained files from the
  three unresolved Pine branches
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/`

**Interfaces:**
- Consumes: PR #458, PR #921, and `fix/tech-debt-post-develop-sync`.
- Produces: Supersession evidence or a reviewed PR into
  `openbb_pine_support`, followed by branch deletion.

- [ ] **Step 1: Audit the exact unresolved set**

```powershell
$pineReconcile = @(
  'chore/bump-pynecore-p2-wave1',
  'docs/pine-claude-md-merge-rule-learnings',
  'fix/tech-debt-post-develop-sync'
)
foreach ($branch in $pineReconcile) {
  "===== $branch ====="
  git log --left-right --cherry-pick --oneline `
    origin/openbb_pine_support..."origin/$branch"
  git diff --name-status origin/openbb_pine_support..."origin/$branch"
}
gh pr view 458 --repo prajoria/OpenBB --comments
gh pr view 921 --repo prajoria/OpenBB --comments
```

Expected: a file-level disposition for each unique patch. Do not assume that
closed PR #458 is obsolete or that open PR #921 is merge-ready.

- [ ] **Step 2: Recover only retained Pine behavior**

If any behavior is still required, create a tracked Pine issue and a side
branch from `openbb_pine_support`:

```powershell
$url = gh issue create --repo prajoria/OpenBB `
  --title "fix(pine): reconcile residual branch-hygiene changes" `
  --body "Recover only retained changes from the three Pine reconciliation branches listed in issue #2035. Target openbb_pine_support. Do not touch Portfolio Intelligence or develop."
$pineIssue = [int]($url -replace '^.*/','')
git switch --create "fix/pine-residual-hygiene-gh-$pineIssue" `
  origin/openbb_pine_support
```

Apply only reviewed retained hunks, then run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests -m "not integration" -v
git diff --check
```

Expected: Pine tests pass and the diff contains no unrelated program files.

- [ ] **Step 3: Deliver retained work only to Pine**

```powershell
git push -u origin "fix/pine-residual-hygiene-gh-$pineIssue"
gh pr create --repo prajoria/OpenBB --base openbb_pine_support `
  --head "fix/pine-residual-hygiene-gh-$pineIssue" `
  --title "fix(pine): reconcile residual branch-hygiene changes (#$pineIssue)" `
  --body "Closes #$pineIssue.`n`nRefs #2035 (full branch inventory)."
```

Expected: the PR targets `openbb_pine_support`, passes review and tests, and
merges before any source branch is deleted.

- [ ] **Step 4: Delete only resolved Pine source branches**

Record each full tip and its supersession or recovery evidence on issue #2035,
then delete the three source refs and prune. If PR #921 remains open or any
patch lacks a disposition, keep that source branch.

For each deleted row, set `Status` to `DELETED-RECONCILED`. Keep
`docs/pine-claude-md-merge-rule-learnings` as `ACTIVE-PR` until PR #921 reaches
a reviewed terminal decision.

---

### Task 11: Reconcile Portfolio and tooling branches through validation

**Files:**
- Potentially modify on one or more tracked side branches rooted in
  `portfolio_validations`: only retained files proven missing
- Test: targeted checks selected from each retained file's owning subsystem

**Interfaces:**
- Consumes: Eight remote nonzero-patch branches and one local-only nonzero-patch
  branch.
- Produces: Documented supersession or reviewed PRs into
  `portfolio_validations`; never directly into `portfolio` or `develop`.

- [ ] **Step 1: Define the exact reconciliation set**

```powershell
$validationReconcile = @(
  'chore/absorb-develop-into-portfolio',
  'chore/openbb-dev-cycle-v2-2026-07-04',
  'copilot/create-vs-code-extension-spec',
  'fix/tech-debt-to-develop',
  'fix/techtrade-python-constraint',
  'qualitycontrol',
  'quant_trading'
)
$localOnlyReconcile = @(
  'docs/pi-asof-snapshot-spec-gh-1932'
)
```

Expected: seven remote and one local-only source branch.

- [ ] **Step 2: Produce file-level evidence**

```powershell
foreach ($branch in $validationReconcile) {
  "===== $branch ====="
  git log --left-right --cherry-pick --oneline `
    origin/portfolio_validations..."origin/$branch"
  git diff --name-status origin/portfolio_validations..."origin/$branch"
}
foreach ($branch in $localOnlyReconcile) {
  "===== $branch ====="
  git log --left-right --cherry-pick --oneline `
    origin/portfolio_validations..."$branch"
  git diff --name-status origin/portfolio_validations..."$branch"
}
```

Expected: every changed file is classified as present, superseded, obsolete,
or retained. Historical PR state alone is not enough.

- [ ] **Step 3: Split retained work by coherent ownership**

For each coherent retained change, create a GitHub issue, add it to Project #4,
claim it, and create a side branch from `portfolio_validations`. Do not combine
unrelated QC tooling, dependency constraints, design documents, and application
code merely because they came from one stale branch.

Use this exact branch policy:

```powershell
$branchType = 'fix'
$topic = 'portfolio-validation-reconciliation'
git switch portfolio_validations
git pull --ff-only origin portfolio_validations
git switch --create "$branchType/$topic-gh-$issue"
```

`$issue` is the number returned from the issue created for that coherent
retained change; no branch may be created without that issue.

- [ ] **Step 4: Run the full internal development cycle**

Each recovery branch must complete `/openbb-dev-cycle`, targeted tests,
independent review, and a fork-internal PR:

```powershell
$branch = "$branchType/$topic-gh-$issue"
$issueTitle = gh issue view $issue --repo prajoria/OpenBB `
  --json title --jq '.title'
gh pr create --repo prajoria/OpenBB --base portfolio_validations `
  --head $branch `
  --title "$issueTitle (#$issue)" `
  --body "Closes #$issue.`n`nRefs #2035 (full branch inventory)."
```

Expected: every recovery PR targets `portfolio_validations`. This task never
creates a direct `portfolio` PR and never creates or merges a `develop` PR.

- [ ] **Step 5: Delete reconciled source refs**

After all retained work from a source branch is merged into
`portfolio_validations`, or the issue records concrete supersession evidence:

1. Record the source branch's full tip SHA on issue #2035.
2. Delete the remote source ref.
3. Prune remotes.
4. Delete a matching local ref with `git branch -d` only when no worktree owns
   it.

Expected: all eight reconciliation source branches are gone without bypassing
the validation stage.

Update every deleted source row to `DELETED-RECONCILED` in the same status
reporting cycle that records its evidence.

---

### Task 12: Remove stale local-only branches

**Files:**
- Modify during execution: none
- Test: local reachability, merged PR evidence, and worktree ownership

**Interfaces:**
- Consumes: Local-only branches after Tasks 9 and 11.
- Produces: A clean local branch list containing only active work and permanent
  trunks.

- [ ] **Step 1: Verify no worktree owns a candidate**

```powershell
git worktree list --porcelain
```

Expected: none of the local candidates is listed as a checked-out branch.

- [ ] **Step 2: Delete the already-merged local-CI correction branch**

```powershell
gh pr view 2031 --repo prajoria/OpenBB `
  --json state,baseRefName,headRefName,mergeCommit
git branch -d fix/local-ci-post-merge-review-gh-2030
```

Expected: PR #2031 reports `MERGED` into `develop`; `git branch -d` succeeds.
This is deletion of an already-integrated local ref, not authorization for a
new `develop` PR or merge.

- [ ] **Step 3: Delete Portfolio local refs only after their remote rows clear**

```powershell
$localPortfolio = @(
  'fix/pi-portfolio-backend-run-gh-1786',
  'fix/pi-portfolio-intel-obbject-openapi-gh-1788'
)
foreach ($branch in $localPortfolio) {
  git branch -d $branch
}
git worktree prune
```

Expected: both refs delete without force. Task 11 owns reconciliation and
deletion of `docs/pi-asof-snapshot-spec-gh-1932`. If `-d` refuses, stop and
re-open the corresponding reconciliation proof; do not use `-D`.

Update each successfully deleted local row to `DELETED-PROVED` or
`DELETED-RECONCILED`, matching the proof path used.

---

### Task 13: Quarantine develop-only work

**Files:**
- Modify during execution: none
- Test: GitHub PR and branch state only

**Interfaces:**
- Consumes: PR #895 and `sync/upstream-openbb-2026-07-19`.
- Produces: An explicit no-action record, not a merge or deletion.

- [ ] **Step 1: Verify the quarantined pair**

```powershell
gh pr view 895 --repo prajoria/OpenBB `
  --json number,state,baseRefName,headRefName,mergeable,statusCheckRollup
git rev-parse origin/sync/upstream-openbb-2026-07-19
```

Expected: PR #895 still targets `develop`. Record its state and full branch tip
on issue #2035.

- [ ] **Step 2: Make no state-changing GitHub or Git operation**

Do not update, close, merge, rebase, retarget, or delete PR #895 or its branch.
The only exit from quarantine is a later instruction from Daisy explicitly
naming the intended `develop` operation.

---

### Task 14: Run the full post-cleanup audit

**Files:**
- Modify during execution: none
- Test: complete local/remote ref and open-PR inventory

**Interfaces:**
- Consumes: Completed Tasks 8-13.
- Produces: Final evidence that only permanent, explicitly held, quarantined,
  or actively tracked branches remain.

- [ ] **Step 1: List every remaining ref**

```powershell
git fetch --prune origin
git for-each-ref refs/remotes/origin --sort=refname `
  --format='%(refname:strip=3)|%(objectname)'
git for-each-ref refs/heads --sort=refname `
  --format='%(refname:short)|%(objectname)|%(upstream:short)'
git worktree list --porcelain
```

Expected remote code branches after completed cleanup:

```text
develop
openbb_pine_support
portfolio
portfolio_validations
sync/upstream-openbb-2026-07-19
trading_technicals
```

`__dolt_remote_info__` may also remain as metadata. Any additional branch must
have an open issue, an open PR to an allowed non-`develop` target, and a named
owner; otherwise the cleanup is incomplete.

- [ ] **Step 2: Audit every open PR**

```powershell
gh pr list --repo prajoria/OpenBB --state open --limit 1000 `
  --json number,title,headRefName,baseRefName,url
```

Expected:

- no stale PR from a deleted branch;
- no newly created PR targeting `develop`;
- no `portfolio_validations` to `portfolio` promotion unless Daisy separately
  requested that exact PR;
- every remaining Pine PR targets `openbb_pine_support`;
- every remaining Portfolio recovery PR targets `portfolio_validations`.

- [ ] **Step 3: Verify permanent refs and forbidden deletions**

```powershell
$permanent = 'develop','portfolio','portfolio_validations','openbb_pine_support'
foreach ($branch in $permanent) {
  git show-ref --verify --quiet "refs/remotes/origin/$branch"
  if ($LASTEXITCODE -ne 0) {
    throw "Permanent branch missing after cleanup: $branch"
  }
}
```

Expected: all four permanent branches exist at the end of every cleanup cycle.

- [ ] **Step 4: Record and close the cleanup issue**

Post the final branch list, deleted branch names and full pre-delete SHAs,
supersession or recovery evidence, merged recovery PRs, held refs, and
quarantined refs on issue #2035. Close issue #2035 only after the audit matches
the expected state and every status-table row is terminal or
`BLOCKED-AUTH`.

---

## Self-Review

- Spec coverage: maps every remote code branch observed on 2026-09-05 and every
  stale local branch to a permanent trunk, explicit hold, quarantine, or
  cleanup disposition.
- Permanent-branch coverage: `develop`, `portfolio`, `portfolio_validations`,
  and `openbb_pine_support` are an explicit no-delete allowlist;
  `trading_technicals` requires a separate retirement decision.
- Safety coverage: requires ancestry or patch/content proof, merged PR
  evidence, SHA recording, worktree checks, and post-deletion audits.
- Program boundaries: Pine recovery targets `openbb_pine_support`; Portfolio
  recovery targets `portfolio_validations`; existing `portfolio` merges are
  evidence only.
- Develop gate: no task creates or merges a PR to `develop`; PR #895 and its
  branch are explicitly quarantined.
- Placeholder scan: execution-time issue identifiers are captured from the
  exact `gh issue create` result before use.
- Execution authorization: absent. This plan does not perform or authorize branch deletion.
