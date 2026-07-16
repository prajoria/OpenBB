# Project #4 (Portfolio Intelligence Engine) — Baseline + Dedup Audit

**Date:** 2026-07-16
**Session branch:** `portfolio` on `prajoria/OpenBB`
**Author:** Claude (Stage 2 of the planning-approach doc)
**Scope:** Reconcile Project #4's `Todo`/`Done` state against what's actually shipped on `origin/portfolio`, in service of an accurate M1–M4 roadmap.
**Companion:** `docs/superpowers/plans/2026-07-16-portfolio-intel-planning-approach.md` (the umbrella plan) and `docs/superpowers/plans/2026-07-16-portfolio-intel-roadmap.md` (Nadia's roadmap synthesized post-audit).

---

## 1. Baseline snapshot (Stage 1)

| Source | Path | Size |
|---|---|---|
| Project #4 items | `.dev-cycle/project4-snapshot-2026-07-16.json` | 90 items |
| PRs base=portfolio | `.dev-cycle/prs-base-portfolio-2026-07-16.json` | 8 (7 merged, 1 open) |
| PRs head=feat/pi-* | `.dev-cycle/prs-head-pi-2026-07-16.json` | 6 (all merged) |
| Portfolio commit log | `.dev-cycle/portfolio-log-2026-07-16.tsv` | full log since 2026-01-01 |
| Derived summary | `.dev-cycle/stage1-derived-2026-07-16.json` | issue-ref cross-refs |
| bd→gh migration map | `scripts/pi_bead_to_gh_map.json` (untracked) | 87 entries |

**Pre-audit state:** 87 `Todo`, 3 `Done` (only #501, #502, #503 — M0 repo-bugs shipped via PR #487).

**Critical finding:** every merged `feat/pi-*` PR cited the retired `OpenBBTechnical-qy83.1.N` bd-id in its `Closes` clause, which GitHub could not resolve into an `#NN` reference. Result: 6 issues stayed `Todo` even though the work landed on `portfolio`. The bd→gh map (`scripts/pi_bead_to_gh_map.json`) is the retroactive bridge.

## 2. Mechanical join (Stage 2A)

Extracted `OpenBBTechnical-qy83.*` references from each merged `feat/pi-*` PR body, split by intent (`Closes` vs bare mention), and joined against `pi_bead_to_gh_map.json`:

| PR | Branch | `Closes` bd-id → GH | Bare-mention bd-id → GH | GH status pre-audit |
|---|---|---|---|---|
| #466 | `feat/pi-router/scaffold` | `qy83.1.4` → **#506** | `qy83.1.12` → #500 | #506 Todo · #500 Todo |
| #467 | `feat/pi-app/paper-migration` | `qy83.1.5` → **#507** | — | Todo |
| #468 | `feat/pi-widgets/playwright-harness` | `qy83.1.7` → **#509** | — | Todo |
| #471 | `feat/pi-ops/pr-template-ci-guard` | `qy83.1.2` → **#504** | — | Todo |
| #473 | `feat/pi-qa/isolation-spec` | `qy83.1.8` → **#510** | `qy83.4.12` → #546 | #510 Todo · #546 Todo (forward ref) |
| #474 | `feat/pi-env/venv-smoke` | `qy83.1.9` → **#511** | `qy83.1.13/14` → #501/#502 (already Done) | #511 Todo |
| #487 | `fix/cache-schema-order-on-portfolio` | — | referenced #501–#503 (already Done) | — |

**Decision rule:** `Closes` in a merged PR = bulk-close permission applies. Bare mentions (`qy83.1.12` in #466, `qy83.4.12` in #473) are intentional *forward-references* to future work — **left open** for genuine engineering to close.

**Total in-scope for close:** 6 issues (#504, #506, #507, #509, #510, #511).

## 3. Bulk close (Stage 2D)

Each of the 6 issues received the following retroactive-close comment via `gh issue comment` (concrete PR/branch/bd-id substituted per issue), then closed with `gh issue close --reason completed`:

> Shipped via #\<PR> (branch: `<branch>`) — originally referenced by the retired bd-id `OpenBBTechnical-<bd-id>`. Closing as `Done` on Project #4 (Portfolio Intelligence Engine).
>
> Retroactive close performed 2026-07-16 during Project #4 tracker-sync audit: the merged PR cited the retired bd-id in its `Closes` clause, which GitHub could not resolve, so this issue stayed `Todo` even though the work landed on `portfolio`. See `docs/superpowers/audits/2026-07-16-project4-baseline-and-dedup.md` for the full sync pass.

Comment permalinks (chronological):
- #511 → https://github.com/prajoria/OpenBB/issues/511#issuecomment-4990004324
- #510 → https://github.com/prajoria/OpenBB/issues/510#issuecomment-4990004616
- #504 → https://github.com/prajoria/OpenBB/issues/504#issuecomment-4990004894
- #509 → https://github.com/prajoria/OpenBB/issues/509#issuecomment-4990005176
- #507 → https://github.com/prajoria/OpenBB/issues/507#issuecomment-4990005424
- #506 → https://github.com/prajoria/OpenBB/issues/506#issuecomment-4990005698

## 4. Post-audit state

**Project #4 status distribution:** `Done: 9  · Todo: 81` (was `Done: 3 · Todo: 87`).

Refreshed snapshot: `.dev-cycle/project4-snapshot-post-close-2026-07-16.json`.

Milestone/phase breakdown of the 81 remaining `Todo`s:

| Bucket | Count | Notes |
|---|---|---|
| **M0 (Kickoff & scaffolds)** | 6 | #497, #498, #499, #500, #505, #508 — mostly PM/decision-gate items + FMP-fixture harness |
| **P0 (Data-Layer Gap Fill)** | 14 | #512–#525 — endpoint pass on `fmp_cached`/`fmp` fallback |
| **P1 (X-Ray + Events + Risk + Smart-Money)** | 17 | #526–#542 — analytics + routes + widgets |
| **P2 (What-If + Attribution + Paper Trading)** | 21 | #543–#563 — paper trading engine + attribution + widgets |
| **P3 (Alerts + Sentiment + Backtest + merge)** | 9 | #564, #570–#577 — final surface + hand-off |
| **M4 (Promotion candidate)** | 5 | #565–#569 — nightly CI, docs, single `portfolio → develop` merge |
| **PHASE epics** (M0/P0/P1/P2/P3 headers) | 5 | #492–#496 — kept open as tracking anchors, close only when their phase is complete |
| **EPIC** | 1 | #491 — closes at M4 promotion |
| **Other** | 3 | — |

**Milestone→phase mapping (see roadmap doc for authoritative version):**
- **M1 = P0 + M0 leftovers** — foundation ready for feature work
- **M2 = P1** — X-Ray / Events / Risk / Smart-Money vertical slices
- **M3 = P2** — What-If / Attribution / Paper Trading
- **M4 = P3 + M4 checklist** — Alerts / Sentiment / Backtest hand-off + promotion PR

## 5. Non-project references (Stage 2B)

The commit log surfaces `Closes #21/#23/#93/#763/#774/#775/#776/#782/#783/#793/#804/#805/#806/#807` and `Fixes #739`. None of these are in Project #4 — they're absorbed from `develop`. Noted here for completeness; no action required.

Coverage audit: `bd_map` has 87 entries; Project #4 has 90 items. The 3 extras are `#501/#502/#503` (M0 repo-bugs, already `Done`). **No orphans.** Every bd-mapped GH issue is on Project #4.

## 6. Ambiguous cases carried forward

None. Every `Closes`-cited bd-id in a merged PR mapped 1:1 to a Project #4 issue with `Todo` status. Every `Refs`-only mention was recognizable as a forward-reference to future work.

## 7. Debt entries created by this audit

None. Six retroactive-close comments were added; no new issues filed. If the roadmap surfaces need for a `feat/pi-ops/enforce-gh-closes-syntax` GH issue (to prevent recurrence — CI could reject PRs whose `Closes` clause doesn't reference an actual GH `#NN`), that will be filed in Stage 4 with your bulk-file sign-off.
