# Feature Branch Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove every remaining `feat/*` branch is integrated into its intended program branch before deleting obsolete local and remote refs.

**Architecture:** Treat branch cleanup as three isolated delivery lanes: Pine work converges on `openbb_pine_support`, local-CI work follows its existing stacked PR chain into `develop`, and Portfolio Intelligence work converges on `portfolio_validations`. Use ancestry, patch equivalence, file-level comparison, tests, and merged-PR evidence in that order; never infer safety from a closed PR or branch age alone.

**Tech Stack:** Git, GitHub CLI, PowerShell, Git Bash, pytest, Node.js, GitHub pull requests.

## Global Constraints

- This document is planning-only. Creating it does not authorize merges, branch deletion, or PR changes.
- Run all GitHub operations against `prajoria/OpenBB`; never create a cross-fork PR.
- Keep Pine work isolated from Portfolio Intelligence. Pine branches target `openbb_pine_support`, not `portfolio_validations`.
- Keep Portfolio Intelligence work isolated from Pine. In this checkout, Portfolio Intelligence branches target `portfolio_validations`, not `portfolio`.
- The only Portfolio Validation promotion path is a fork-internal
  `portfolio_validations` -> `portfolio` PR. Create and merge it only after an
  explicit user request for that exact promotion PR; generic merge, push,
  cleanup, or side-branch PR instructions do not authorize it.
- Preserve the live local-CI stack order: `feat/local-ci-skill-gh-989` -> `feat/local-ci-cli-gh-985` -> `test/develop-e2e-docker-stack` -> `develop`.
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

## Inventory Snapshot

Inventory captured on 2026-09-05 after `git fetch --prune origin`.

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

### Task 1: Freeze the cleanup inventory and ownership boundaries

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

### Task 2: Retire the 15 patch-equivalent Pine branches

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

### Task 3: Reconcile the seven merged Pine branches with nonzero patch IDs

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

### Task 4: Resolve the three closed, unmerged Pine PR branches

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

### Task 5: Drain the local-CI stack bottom-up

**Files:**
- Verify: `.agents/skills/` changes from `feat/local-ci-skill-gh-989`
- Verify: local-CI CLI and schema changes from `feat/local-ci-cli-gh-985`
- Verify: `docker/e2e/` on `test/develop-e2e-docker-stack`

**Interfaces:**
- Consumes: Open PR #1015, PR #1009, and PR #948.
- Produces: Merged changes in `develop` and retired intermediate feature refs.

- [ ] **Step 1: Verify PR #1015 targets the CLI branch**

Run:

```powershell
gh pr view 1015 --repo prajoria/OpenBB --json state,baseRefName,headRefName,mergeable,statusCheckRollup
```

Expected: head `feat/local-ci-skill-gh-989`, base `feat/local-ci-cli-gh-985`, state `OPEN`, and required checks passing.

- [ ] **Step 2: Merge PR #1015 and verify ancestry**

After review approval:

```powershell
gh pr merge 1015 --repo prajoria/OpenBB --merge --delete-branch
git fetch --prune origin
git merge-base --is-ancestor origin/feat/local-ci-skill-gh-989 origin/feat/local-ci-cli-gh-985
```

Expected: GitHub deletes the skill branch. If the final ancestry command cannot run because the remote ref was deleted, verify PR #1015 reports `MERGED` and record its merge commit instead.

- [ ] **Step 3: Verify and merge PR #1009 into the main local-CI feature branch**

Run:

```powershell
gh pr view 1009 --repo prajoria/OpenBB --json state,baseRefName,headRefName,mergeable,statusCheckRollup
```

Expected: head `feat/local-ci-cli-gh-985`, base `test/develop-e2e-docker-stack`, and passing required checks.

Then:

```powershell
gh pr merge 1009 --repo prajoria/OpenBB --merge --delete-branch
git fetch --prune origin
```

Expected: PR #1009 is merged and the CLI feature branch is deleted.

- [ ] **Step 4: Promote the completed local-CI feature through PR #948**

Run:

```powershell
gh pr view 948 --repo prajoria/OpenBB --json state,baseRefName,headRefName,mergeable,statusCheckRollup
```

Expected: head `test/develop-e2e-docker-stack`, base `develop`, and all required checks passing.

Merge only after its review and CI gates pass:

```powershell
gh pr merge 948 --repo prajoria/OpenBB --merge --delete-branch
git fetch --prune origin
```

Expected: the full stack is in `develop`; all three stack refs are absent remotely.

---

### Task 6: Complete the active Top-50 intraday branch through validation

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

### Task 7: Perform the final branch-hygiene audit

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

## Self-Review

- Spec coverage: maps every currently observed remote `feat/*` branch plus the one local-only `feat/*` branch to an explicit target and disposition.
- Safety coverage: requires ancestry or patch/content proof, merged PR evidence, SHA recording, worktree checks, and post-deletion audits.
- Program boundaries: Pine, local-CI, and Portfolio Intelligence are handled independently; no Pine work is routed through `portfolio_validations`.
- Placeholder scan: no incomplete implementation placeholders remain; execution-time issue and PR numbers are resolved with exact GitHub CLI queries.
- Execution authorization: absent. This plan does not perform or authorize branch deletion.
