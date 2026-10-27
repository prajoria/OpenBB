# Portfolio work: pause handoff (2026-10-26)

> **Updated 2026-10-27:** §3, §4 and §6 are superseded by the
> [2026-10-27 resume state](./2026-10-27-portfolio-resume-state.md). The MCP
> parity program is closed, the stash documents have landed, and rule 4 below
> no longer applies, because auto-close now reads PR bodies (#1975). §1 and §5
> still stand.

Written at the start of a planned multi-month pause, so that work can resume
from this file alone. Tracking issue: #2284 (Pause handoff record for
Portfolio MCP work).

- **Repo:** `prajoria/OpenBB` (fork). **Integration branch:** `portfolio`.
- **Board:** [Project #4: Portfolio Intelligence Engine](https://github.com/users/prajoria/projects/4).
- **`portfolio` tip at pause:** `303a07ada73` (`build(mcp): lock dual-MCP transitive dependency graphs (#2283)`).
- **Process:** every change goes through the `openbb-dev-cycle` skill. That
  means a side branch cut from `portfolio`, TDD with mutation reverse-checks,
  and a fork-internal PR with `--repo prajoria/OpenBB --base portfolio`.
  `CLAUDE.md` holds the binding rules.

## 1. Standing rules to remember on return

1. **No issue stays open unless a human is needed.** Agent-doable issues get
   worked and finished, never closed as "stale" without doing the work. An
   issue that truly needs a human decision, money, hardware or a legal
   sign-off stays open with a comment naming the blocker.
2. **Only `prajoria` works this repo.** Fork-internal PRs only. Never open a
   PR to `OpenBB-finance`. Never open `portfolio` → `develop` without explicit,
   loud sign-off from Daisy.
3. **Subagents must use `gpt-5.6-sol`.** In this session that model was
   unavailable, so all work ran inline with no subagents and every review was
   a self-review. If it is still unavailable on return, the same applies.
4. **Squash merges close issues only from the commit message.** The
   auto-close workflow reads only the commit message (see #1975, below), so
   put `Closes #NN` in the **commit body** as well as the PR body.

## 2. What shipped

### 2.1 MCP capability-parity program (#2123): 67 of 74 issues done

The program turns the Portfolio stack into a trusted, reproducible MCP
surface. It covers runtime profiles, FMP Cached routing, Portfolio business
routes with auth and data boundaries, the Intelligence and FinancialToolkit
bridges, cache-job tools, operator runbooks, drift CI and clean-replay
certification. It landed between 2026-10-04 and 2026-10-05 (about 200 commits
on `portfolio`, closing with PRs #2274–#2281), then #2283 on 2026-10-26.

- Operator guide: `docs/operations/portfolio-mcp.md`. It now includes a
  "Dependency locks" section.
- Launcher: `scripts/start-dual-mcp.ps1`. Lifecycle module:
  `scripts/mcp_stack_lifecycle.psm1`.
- Readiness probe: `scripts/test_portfolio_mcp.ps1 -Profile portfolio-read -Mode metadata`.

### 2.2 This session: #2245 (Lock complete dual-MCP transitive dependency graphs)

Merged as PR #2283 into `portfolio` (`303a07a`). #2245 is closed.

- **Locks:** `scripts/mcp_locks/platform-mcp.txt` (146 pins) and
  `workspace-mcp.txt` (72 pins), compiled from `*.in` by
  `scripts/lock_mcp_envs.py`:

  | Command | Effect |
  |---|---|
  | `python scripts/lock_mcp_envs.py` | sync; keeps existing pins |
  | `python scripts/lock_mcp_envs.py --upgrade` | deliberate refresh |
  | `python scripts/lock_mcp_envs.py --check` | CI drift gate |

- **Launcher flags:** `uv run --with-requirements <lock> --exclude-newer <locked-at>`.
- **Verified uv 0.11.26 behavior.** These are the non-obvious facts the
  design rests on:

  | What | Behavior |
  |---|---|
  | `UV_CONSTRAINT` | **ignored** by `uv run` |
  | Package hashes in a requirements file | **never verified** by `uv run`; a corrupted hash installed cleanly |
  | `UV_REQUIRE_HASHES` / `UV_VERIFY_HASHES` | ignored by `uv run` |
  | `--with-requirements` | enforces exact pins |

  So the locks pin versions only; hash enforcement is #2282.
- **FastMCP split is intentional.** Platform runs 3.4.0 because FastAPI
  conflicts with Starlette ≥ 1.0.1. Workspace runs 3.4.6 (Starlette 1.6.0).
- **CI:** `.github/workflows/dual-mcp-lock.yml` runs the lock check, a Windows
  job with Pester 4.10.1 plus a clean-cache replay, and a weekly upgrade
  report as an artifact. The report never pushes.
- **Design and plan:**
  - `docs/superpowers/specs/2026-10-25-dual-mcp-dependency-lock-design.md`. Section 7 records the hash and pip amendments.
  - `docs/superpowers/plans/2026-10-25-dual-mcp-dependency-lock.md`.

## 3. Local-only state at risk: resolve first on return

These things exist **only on the operator's machine** and are not on GitHub.
Resolve them before any new work.

1. **`stash@{0}` holds uncommitted program planning documents.** Its message
   is "MCP planning drafts + rag submodule + deep-dive nb (pre-refresh
   2026-10-22)". It contains:
   - Both program plans. Many issue bodies cite them as "local document":
     - `docs/superpowers/plans/2026-10-03-portfolio-mcp-capability-parity.md`
     - `docs/superpowers/plans/2026-10-03-notebook-mcp-agent.md`
   - Notebook-agent design and requirements:
     - `docs/designs/notebook-mcp-agent-design.md`
     - `docs/Specs/notebook-mcp-agent/requirements.md`
   - Eleven new `docs/cross_repo_workflow/*` coverage and inventory files, plus edits to its `README.md` and `mcp-coverage-report.md`. #2194 updates these.
   - A `.gitmodules` change, the `third_party/openbb-rag-financial-research-agent` submodule, and an edit to `notebooks/portfolio/02-single-name-deep-dive.ipynb`.

   **Next step:**
   1. Restore the stash on a side branch.
   2. Review every file for PII. The **notebook edit may contain personal
      outputs**: run `scripts/reset_notebooks_for_checkin.py --check` and
      inspect it cell by cell, or drop it.
   3. Land the documents through a reviewed PR.

   This needs a human, both for the PII review and to decide whether to keep
   the RAG submodule.
2. **Untracked items in the main checkout:**
   - `third_party/openbb-rag-financial-research-agent/` (part of the stash decision above).
   - `third_party/workspace/backend-api/backend/uv.lock` (52 bytes, dated 2026-10-05, origin unknown). It can probably be deleted after a look.
3. **Older stashes:** `stash@{1}`–`stash@{9}` are 2026-08 work-in-progress from
   the `feat/pi-vscode-terminal/*` branches (#1831, #1837, #1838). That work
   shipped through other PRs, so these are probably droppable after a skim.
4. **Stale worktrees and branches.** These remote branches are gone, so their
   PRs merged or closed. Remove them with the `clean_gone` skill after
   confirming nothing unpushed remains.

   | Worktree folder | Branch |
   |---|---|
   | `.worktrees/dual-mcp-lock-2245` | `feat/dual-mcp-lock-gh-2245` (merged) |
   | `.worktrees/pi-snapshot-consumers-1968` | `feat/pi-snapshot-consumers-gh-1968` |
   | `.worktrees/workspace-browser-2101` | `test/workspace-connectors-gh-2101` |
   | `.worktrees/workspace-copilot-2103` | `fix/workspace-bootstrap-privacy-gh-2120` |
   | `.worktrees/workspace-mcp-2102` | `test/self-hosted-workspace-mcp-gh-2102` |
   | `.worktrees/workspace-replay-2111` | `feat/workspace-replay-skill-gh-2111` |
   | `worktrees/local-llm-bootstrap-2088` | `feat/local-llm-bootstrap-gh-2088` |

   Other gone branches without a worktree: `chore/browser-harness-fixtures-gh-2092`,
   `docs/local-llm-guide-gh-2088`, `test/self-hosted-workspace-browser-gh-2101`,
   `test/self-hosted-workspace-copilot-gh-2103`.
5. **`.worktrees/mcp-release-2194`** (`release/mcp-parity-gh-2194`) sits at
   `cddfe05` with no commits. It is the empty start of #2194 (T44); either
   rebase it onto `portfolio` or recreate it.

## 4. Open work on Project #4 (50 items at pause)

Each item is marked as needing a **HUMAN** (stays open until a person acts)
or as **AGENT** work (finishable by the agent through the dev cycle).

### 4.1 MCP capability parity: what remains

| Issue | Who | Next step |
|---|---|---|
| #2194 (T44: Release, update coverage evidence, and prove rollback) | **HUMAN** for the decisions, AGENT for the mechanics | All five dependencies (T38, T40–T43) are closed. Needs an operator promotion decision on the canary → operator profile rollout and acceptance or rejection of each program AC. The agent can run the metadata probe at the release SHA and at the rollback baseline, and update the coverage artifacts once the §3.1 stash documents land. |
| #2282 (Enforce dependency-lock artifact hashes at dual-MCP launch) | AGENT | Needs a launcher model change: a persistent env built by `uv pip sync --require-hashes` from a hashed lock, then `python -m` from that env. Keep the #2159 editable provenance. |
| #2242 (Harden caller-controlled document URL fetchers before MCP exposure) | AGENT | P0 security. Add a URL allowlist, block private IPs and redirects, and set size limits on document-fetching fetchers before exposing them as tools. |
| #2135 (F2.1), #2151 (F8.2), #2125 (E2), #2131 (E8), #2123 (PROGRAM) | close when children close | #2135 waits on #2282. #2151, #2131 and #2123 wait on #2194. |

### 4.2 Notebook MCP Companion program (#2195): 40 issues, not started

The program is a Python MCP agent that replays the 25 portfolio notebook
stories with a **local vLLM Nemotron** model. Its plan and design are only in
`stash@{0}` (§3.1), so **land those documents first**.

- **AGENT:** most tasks, N01–N17 and N20–N24, can run against synthetic
  fixtures and a fake model.
- **HUMAN:** N11 (#2221), N19 (#2229) and the N18 (#2228) qualification runs
  need a GPU host with the Nemotron weights served by vLLM.

### 4.3 Other Project #4 items

| Issue | Who | Note |
|---|---|---|
| #2235 (Retired Beads Git hooks still run during Portfolio commits) | AGENT | Reproduced on 2026-10-26: `git commit` printed `Exported 1045 issues to .beads/issues.jsonl`. Remove the bd hook from `.git/hooks`, or from the hook manager config. |
| #2094 (Live fixture staleness: 12 portfolio-story fixtures drift with market data) | AGENT | Freeze the fixtures to recorded snapshots, or assert shape instead of values. |

## 5. Older backlog not on Project #4 (210 open issues)

These come from programs that predate the Portfolio board. Most of the triage
below is by title, so **verify against code before working any of them**.
Some may already be shipped. For example, an older memory records Analysis
A0–A8 and B0–B4 as landed via PR #470 on another branch.

| Group | Issues | Who | Note |
|---|---|---|---|
| Pine Script extension | #102, #106–#110, #116–#154, #175–#193, #578–#600, #729–#735, #915, #965 | **HUMAN** gate | #175 (outside counsel sign-off on the clean-room SOP) blocks the program. That is a legal decision. |
| FMP Premium-tier gaps | #1928, #1929, #1930 | **HUMAN** | Need a paid FMP tier upgrade, or a decision to drop them. |
| Live broker / P9 streaming | #87 | **HUMAN** | Live-money adapter; needs an explicit go-ahead. |
| Analysis hardening and PR #304 QC findings | #271–#320 | AGENT | Verify which already landed, then fix the P0/P1 review bugs (#307, #310, #312, #313, #317) first. |
| fmp-trading intraday program | #356–#363, #382–#403 | AGENT | P3 agent turns need an Anthropic API key at test time (human-provided). |
| Backtest engine | #54, #60–#62 | AGENT | |
| local-ci Dockerized runner | #980–#1014 | AGENT | |
| core journaling | #408, #413 | AGENT | |
| Portfolio-intel / fmp_cached gaps and bugs | #911, #912, #930, #945, #976, #1321, #1330, #1394, #1395, #1922, #1925, #1932, #1975 | AGENT | #1975 is the auto-close gap from §1.4. |
| Misc tech debt / test infra | #18, #20, #63, #88, #91, #94, #96, #99, #195–#211, #259, #263–#270, #580–#583, #596, #597, #756, #759, #854, #1625, #1779 | AGENT | #597 is bd-related; bd is retired, so likely resolvable by closing with that rationale after confirmation. |

## 6. Ordered resume checklist

1. Run the session-start protocol from `CLAUDE.md`:
   - `python scripts/pi_claim.py --list-stale`
   - `gh issue list --assignee @me --state open`
2. Resolve §3: land or drop `stash@{0}`, clean the gone worktrees and
   branches, and drop the old stashes.
3. Quick AGENT wins: #2235 (bd hooks) and #1975 (auto-close parses the PR
   body).
4. Security first: #2242.
5. #2282 (hash-enforced launch), then close #2135 (F2.1).
6. #2194 (T44) with the operator present for the promotion and rollback
   decisions. Then close #2151, #2131 and #2123.
7. Notebook MCP Companion program (#2195), in N01 → N24 order.
8. Triage the §5 backlog against code, then work the AGENT groups and leave
   the HUMAN-gated ones open with blocker comments.
