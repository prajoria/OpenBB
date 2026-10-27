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
- **The Notebook MCP Companion program (#2195) is past its analytics bridge.**
  N01-N06 are merged, and N05 (#2215) and its feature NF2.1 (#2203) are
  closed. Next are the N07-N10 bridges under NF2.2 (#2204), then N11 onward
  (see §3). Everything is agent-doable except the items in §4.
- **Project #4 open items:** 30 Notebook Companion issues, plus #2323 until
  this update merges. Nothing else on the board is open.

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

### Later on 2026-10-27: N02-N06

| PR | Issue | Outcome |
| --- | --- | --- |
| #2307, #2310, #2311, #2312 | #2212, #2214, #2213, #2216 (N02, N04, N03, N06) | Manifests, readiness, scenarios and the story run registry |
| #2317 | #2313 (N05a basket look-through, sector roll-up and concentration) | Four `story_*` tools over `basket_lookthrough`, which the notebook helper now also uses |
| #2318 | #2314 (N05b seven-phase single-name analysis) | `story_single_name_analysis` over `Analysis/stock_analysis`, loaded only from a trusted location |
| #2319 | #2315 (N05c Brinson attribution, what-if diff, candidate trades) | Three tools; the what-if diff never guesses a missing price |
| #2320 | #2316 (N05d TechTrade story analytics) | Six tools over `openbb_techtrade.engine.story_analytics`; TechTrade chapter 3 is the first ready story |
| #2322 | #2321 (N05e drain N05 and bind run state to the N06 tools) | Nothing waits on N05 or N06 |

## 3. Notebook Companion: in flight and next

| Task | State | Notes |
| --- | --- | --- |
| N01-N06 (#2211-#2216) | Done | N05's five sub-issues are #2313-#2316 and #2321 |
| N07 (#2217: artifacts) | Next | 18 stage needs: charts, tables, reports, XLSX and exported files |
| N08 (#2218: jobs) | Open | 12 stage needs: backtest, tuning and replay as durable jobs |
| N09 (#2219: paper) | Open | 23 stage needs, the largest: Portfolio and TechTrade paper actions in a sandbox |
| N10 (#2220: provider modes) | Open | 14 stage needs: provider variants, recording, free-tier sector maps |
| N11 onward (#2221-#2234) | Open | N11's live preflight, N18 and N19 need the approval in §4 |

Readiness now: 287 stages; 114 setup or narrative; 173 doing financial work,
108 of them runnable on MCP tools; 65 waiting on N07-N10; 1 of 25 stories
(TechTrade chapter 3) ready. The live table is in
[notebook-mcp-story-coverage.md](../cross_repo_workflow/notebook-mcp-story-coverage.md).

Every N05 tool follows one pattern worth reusing for N07-N10:

- Lift the notebook math into an engine module.
- Test it against hand-computed values and against the notebook's own cells (exec'd with rendering stubbed).
- Expose it from a `story_adapters/` module with bounded, finite inputs.
- Give it one policy rule and work family, and bind its stages in `REVIEWED_BINDINGS`.
- Reverse-verify every load-bearing test by mutation.

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
6. **Pre-commit hooks were not installed in this checkout.** `git commit` ran
   no hooks until `pre-commit install` (with the short `PRE_COMMIT_HOME`), so
   one test-file lint issue was committed. Check `.git/hooks/pre-commit`
   exists before trusting a green commit.
7. **CI's evidence step runs every test file in a family, integration tests
   included, without provider keys.** A live test must skip when no key is
   configured (see `test_single_name.py`), or it fails CI.
8. **`REVIEWED_BINDINGS` is merged from dict literals,** so a stage reviewed
   twice silently keeps the later entry. `test_reviewed_binding_keys_are_unique`
   now catches that.
9. **Overriding `PYTHONPATH` with the core source hides the venv's built
   extensions** (`obb.equity` disappears). For a live call, put only the
   package under test on `PYTHONPATH`.
10. **Notebook-cell parity needs varied inputs.** Hand-picked fixtures left
    threshold mutations alive; 150 seeded random paths through the
    market-weather cell killed them all.
6. **detect-secrets flags hex digests.** Generated manifests are excluded by
   path; elsewhere prefer a baseline entry with `is_secret: false`, or avoid
   committing raw commit SHAs.
