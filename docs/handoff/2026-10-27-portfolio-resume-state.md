# Portfolio work: resume state (2026-10-27)

Companion to the [2026-10-26 pause handoff](./2026-10-26-portfolio-pause.md),
which is still the reference for standing rules and the older backlog (§5).
This file supersedes its §3, §4 and §6. Tracking issue: #2308 (Record
2026-10-27 Portfolio session state and resume plan).

## 1. Where things stand

- **The MCP capability-parity program is complete.** #2123 (Portfolio
  capability coverage and trusted MCP delivery) and all its epics are closed.
  The release record is
  [docs/operations/portfolio-mcp-release.md](../operations/portfolio-mcp-release.md):
  promotion decision, metadata readiness, rollback proof, the six program
  metrics and AC-01..AC-12 status.
- **The Notebook MCP Companion program (#2195) has started.** N01 is merged,
  N02 and N04 are in review (see §3). Everything else is open and agent-doable
  except the items in §4.
- **Project #4 open items:** 39 Notebook Companion issues, plus #2308 until
  this file merges. Nothing else on the board is open.

## 2. What shipped on 2026-10-27

| PR | Issue | Outcome |
| --- | --- | --- |
| #2291 | #2235 (Retired Beads Git hooks still run during Portfolio commits) | The migration no longer copies the inert stubs into `.git/hooks` |
| #2293 | #2292 (Auto-close-on-merge drops runs when several PRs merge back to back) | Auto-close runs are grouped per merge SHA, so fast merges no longer cancel each other |
| #2294 | #2290 (Admit SSRF-hardened document URL fetchers to MCP profiles) | 9 hardened routes admitted to the three profiles |
| #2295 | #2094 (Live fixture staleness: 12 portfolio-story fixtures drift) | Live-served Equity Profile fixtures are checked by status only |
| #2297 | #2296 (Check in the MCP-parity and Notebook Companion plan documents) | Both program plans, the design and requirements landed from the local stash |
| #2299 | #2298 (Capability inventory mislabels the ExchangeMarketHours TTL fetcher) | Inventory and `cache_coverage` agree at 123/58 persistent |
| #2301 | #2300 (Bundled MCP prompts require tool names that no profile emits) | Prompts reference only real tools and providers; drift gate judges per prompt |
| #2303 | #2302 (Offline MCP invocation evidence for the 70 legacy FMP mappings) | Offline MCP invocation evidence for all 181 FMP models |
| #2304 | #2194 (T44: Release, update coverage evidence, and prove rollback) | `-Mode metadata` probe, release record, rollback proof |
| #2305 | #2211 (N01: Inventory source-only notebook stories and Portfolio lineage) | `scripts/notebook_story_inventory.py`; hashes match the audit 25/25 |

The four bugs behind #2298, #2300 and #2302 were found only because every
number in the T44 release record was re-verified against code before it was
written down.

## 3. Notebook Companion: in flight and next

| Task | State | Notes |
| --- | --- | --- |
| N02 (#2212: typed story manifests, stage DAGs and state handoffs) | PR #2307 | Contracts, `validate_stage_graph`, 25 generated manifests and a 47-entry capability catalog |
| N04 (#2214: bind story outcomes to real MCP capability readiness) | Branch `feat/notebook-readiness-gh-2214`, pushed | Open its PR against `portfolio` once #2307 merges; rebase first (see §5.1) |
| N03 (#2213: independent synthetic scenarios and parity expectations) | Next | Hand-computed oracles must not compare a wrapper with itself |
| N05–N10 | After N02/N04 | The readiness table in [notebook-mcp-story-coverage.md](../cross_repo_workflow/notebook-mcp-story-coverage.md) lists how many stages each bridge unblocks; N05 (analytics) is by far the largest |

Readiness at this baseline: 287 stages, 194 doing financial work, 44 runnable
on existing MCP tools, 150 waiting on N05–N10 bridges, 0 of 25 stories ready.

Regenerate manifests after any notebook change with
`scripts/build_story_manifests.py` (it needs the `portfolio-ops` server, so run
it with the MCP and provider sources on `PYTHONPATH`), review the diff, and
commit it. The manifest tests fail until you do.

## 4. Still needs a human

| Item | Why |
| --- | --- |
| Local Nemotron runs: N11 live preflight, N18, N19 (#2221, #2228, #2229) | This machine has an RTX 3090 (24 GB) and Docker Desktop with a WSL2 backend (engine stopped). Running vLLM means starting Docker and downloading the image and model weights, tens of GB. Approve that before the agent does it. |
| Stash `MCP planning drafts + rag submodule + deep-dive nb` | Its documents landed in #2297. Still in the stash: the `02-single-name-deep-dive.ipynb` edit (may contain personal outputs) and the `openbb-rag-financial-research-agent` submodule. Keep or drop is your call. |
| Pine Script program (#175 and children) | Outside-counsel sign-off on the clean-room SOP |
| FMP Premium gaps (#1928, #1929, #1930) | Paid tier, or a decision to drop them |
| Live broker / P9 streaming (#87) | Live-money adapter; needs an explicit go-ahead |

## 5. Lessons from this session

1. **Deleting a merged PR's branch closes PRs stacked on it.** `gh pr merge
   --delete-branch` on #2305 closed #2306, which GitHub could not retarget.
   For a stack, merge the bottom PR *without* deleting its branch, retarget
   the next PR to `portfolio`, then delete. After a squash merge, rebase the
   next branch with `git rebase --onto origin/portfolio <old-bottom-tip>`.
2. **CI rebuilds `core/openbb/assets/reference.json`.** `openbb.build()` in the
   coverage workflow rewrites it for the minimal install, so tests that need
   the full Platform command list read
   `mcp_server/tests/fixtures/platform_command_reference.json` instead.
3. **CI runs only the test files a PR changes.** A failing test elsewhere can
   sit unnoticed on `portfolio`. Local failures in an unchanged file still
   deserve a look before blaming the environment.
4. **Local pre-commit.** The sandbox cannot read `~/.cache/pre-commit`, and long
   paths break pip on Windows. Use a short cache path:
   `PRE_COMMIT_HOME=<repo>/.worktrees/.pch pre-commit run --files ...`.
   Pylint's `C0328` CRLF notices are local-only noise.
5. **`.venv_portfolio` has a stale non-editable `openbb_fmp_cached`** in
   `site-packages`. Tests that import it without the source on `PYTHONPATH`
   see old code (this explained the old `test_cache_observability` failures).
   Reinstall it editable (`pip install -e openbb_platform/providers/fmp_cached`)
   when convenient.
6. **detect-secrets flags hex digests.** Generated manifests are excluded by
   path; elsewhere prefer a baseline entry with `is_secret: false`, or avoid
   committing raw commit SHAs.
