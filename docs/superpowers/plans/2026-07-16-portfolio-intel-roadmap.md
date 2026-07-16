# Portfolio Intelligence Engine — Roadmap (Nadia's synthesis)

**Author:** Nadia (PM, AI agent)
**Date:** 2026-07-16
**Branch:** `portfolio` on `prajoria/OpenBB`
**Project:** [#4 Portfolio Intelligence Engine](https://github.com/users/prajoria/projects/4)
**Basis:** `docs/superpowers/audits/2026-07-16-project4-baseline-and-dedup.md` (post-audit state: 9 Done / 81 Todo)
**Companion:** `docs/superpowers/plans/2026-07-16-portfolio-intel-planning-approach.md` (umbrella plan) — supersedes any pre-audit cadence sketches there.

**Cadence unit:** sessions (not weeks). One session ≈ one focused work push by one agent on one branch. Total-session budget is Nadia's honest estimation unit for an AI-agent team; wall-clock is Daisy's decision.

**Team:** *Nadia* (PM), *Kai* (backend/data/router), *Priya* (widgets/frontend/UX), *Rohan* (platform/infra/migrations), *Mira* (QA lead, PR gate), *Zev* (external adversarial reviewer, outright veto on merge).

---

## Executive summary

The tracker's existing `[P0]`/`[P1]`/`[P2]`/`[P3]` phase decomposition (issues #493–#496 are the phase-epics) maps cleanly onto four milestones ending in the single `portfolio → develop` promotion PR Daisy has to sign off on. **M0 is essentially shipped** (9 of 15 M0-scope items closed; 6 remain, all planning/decision items rather than code). **M1 = P0 data-layer** — this is the critical path; every downstream widget assumes P0 endpoints exist. **M4 is the promotion gate** the epic body names verbatim: *"All work merges to portfolio; single merge to develop only at M4."*

**Where the work concentrates:** P2 has the most items (21), reflecting the paper-trading engine's real complexity (fills, isolation, ledger, cost-basis, corporate-actions). P1 is 17 items but many are widgets that parallelize cleanly across Priya. P3 is 9 items and is naturally the last vertical slice.

**Provider assumption:** `fmp_cached` first; `fmp` fallback with mandatory `area:fmp-cached-gap` GH issue per the design rule. Nadia's read (per companion plan) — high fallback risk concentrated in **Alerts (P3)** and **Paper Trading (P2)**; low elsewhere.

---

## Milestones

| Milestone | Scope | Acceptance | Owner (drives sign-off) |
|---|---|---|---|
| **M0** (current) | Kickoff, scaffolds, decisions | 6 remaining items closed OR marked out-of-scope by Daisy | Nadia |
| **M1** | P0 = Data-Layer Gap Fill (14 issues #512–#525) + fmp_cached preflight audit | All 14 P0 issues closed; recorded-fixture harness (#508) operational; every non-`fmp_cached` fallback has a paired `area:fmp-cached-gap` issue | Kai |
| **M2** | P1 = X-Ray + Events + Risk + Smart-Money (17 issues #526–#542) | 4 product surfaces render live in `portfolio_app` widgets against a real portfolio; E2E Playwright specs (Priya) green | Priya |
| **M3** | P2 = What-If + Attribution + Paper Trading (21 issues #543–#563) | Paper order round-trip demo (#556); SEV-1 isolation spec (#546) unskipped and green; Brinson attribution reconciles against fixture (#557) | Kai + Rohan (jointly) |
| **M4** | P3 = Alerts + Sentiment + Backtest hand-off (9 issues #564+#570–#577) + M4 promotion checklist (5 issues #565–#569) | Nightly CI green 3 nights (#565); docs complete (#566); rebase clean (#567); **Daisy's loud sign-off** → single `portfolio → develop` PR opens (#568) | Nadia + Zev (Zev signs off on adversarial pass) |

**Hard rule (from CLAUDE.md):** M4's `portfolio → develop` PR does not open until Daisy says "open the promotion PR" (or equivalent unambiguous instruction). Silence is not consent.

## Workstream × owner matrix

Owner constraint: at most one active `feat/pi-*` branch per owner, and no two active branches touching the same subsystem, to keep merges into `portfolio` conflict-free.

### M0 residuals (6 items, ordered)

| # | Title | Owner | Type |
|---|---|---|---|
| #497 | Cut portfolio branch + branch protection | Rohan | ops |
| #498 | DECISION: PRD Q8 (paper fill model source) | **Daisy** (decision item) | — |
| #499 | Book M1/M2/M3/M4 gate reviews | Nadia | pm |
| #500 | Dolt dep-schema missing depends_on_id column | **N/A — obsolete** (bd retired) | close as `wontfix` |
| #505 | Weekly Monday portfolio←develop sync | Nadia | pm |
| #508 | Recorded-fixture harness for FMP | Rohan | infra |

**Recommendation:** close #500 as `not planned` (retired bd system, superseded). Assign the remaining 4 immediately; #498 is a Daisy-blocking decision item and gates M3 (paper trading fill semantics).

### M1 — P0 Data-Layer (14 items — Kai primary, Rohan supporting)

| Cluster | Issues | Owner |
|---|---|---|
| **ETF holdings & metadata** (priority: unblocks Lane B) | #512, #518 | Kai |
| **Economics / Rates / Indicators** | #513 | Kai |
| **Market perf / sectors** | #514 | Kai |
| **Technicals per holding** | #515 | Kai |
| **Cache + warmers** | #516, #517 | Rohan (owns the cache table + warmers infra) |
| **Calendars** | #519 | Kai |
| **Analyst estimates / ratings** | #520 | Kai |
| **Insider / 13F / Senate** (smart-money data) | #521, #522, #523 | Kai |
| **SEC filings** | #524 | Kai |
| **News** | #525 | Kai |

**M1 preflight (before Kai starts):** Rohan runs a 30-min audit of `providers/fmp_cached/` to catalog which of the above endpoints are covered. Every gap becomes a filed `area:fmp-cached-gap` issue *before* Kai starts on that cluster. Kai works on the fallback path and does not block on gap-issue resolution — the `fmp_cached` team owns those (see companion plan's scope boundary).

**Concurrency:** Kai is the primary; Rohan owns cache infra in parallel. Priya + Mira can start on **M2 harness prep** while M1 is in progress (any widget scaffolding that doesn't need real endpoints).

### M2 — P1 Vertical slices (17 items)

Four product surfaces, each a "route + analytics + widgets" vertical:

| Surface | Analytics | Route | Widgets | Owner assignment |
|---|---|---|---|---|
| **X-Ray look-through** | #526, #535 | #541 | #529, #530 | Kai (analytics+route) + Priya (widgets) |
| **Event Calendar** | #537 | #542 | #531 | Kai + Priya |
| **Risk & Concentration** | #539, #540 | #528 | #533 | Kai + Priya |
| **Smart-Money overlay** | #538 | #527 | #532 | Kai + Priya |
| **Analytics: HHI** | #536 | (part of Risk route) | (part of Risk widget) | Kai |
| **Demo cut** | — | — | — (#534) | Nadia coordinates |

**Concurrency plan:** Kai and Priya alternate — Kai lands the route+analytics on a `feat/pi-app/*` branch, Mira gates, Zev reviews, merge; then Priya lands the widget on `feat/pi-widgets/*`. Never both editing the same surface simultaneously. Rohan is on M3 prep (paper-trading migration audit) during M2.

### M3 — P2 Paper Trading + What-If + Attribution (21 items — heaviest phase)

**Sub-workstreams:**

| Sub-workstream | Issues | Owner | Depends on |
|---|---|---|---|
| **Paper Trading infra** | #562 (apply migration), #563 (Fills v0), #544 (Fills v1), #545 (Ledger) | Rohan (migration + ledger) + Kai (fill engine) | #498 decision (Daisy) |
| **Paper isolation (SEV-1)** | #546, #547, #548 | **Mira** owns the unskip; Kai implements | #562 |
| **Paper widgets** | #549, #550, #551 | Priya | Paper infra route lands first |
| **UX for paper mode** | #555 | Priya | — |
| **What-If** | #558 (engine), #552 (widget) | Kai (engine) + Priya (widget) | M2 X-Ray shipped |
| **Attribution** | #559, #560 (analytics), #553 (widget), #557 (fixtures) | Kai + Priya + Mira (fixtures) | — |
| **Backtest hand-off contract** | #561 | Kai | — |
| **Corp-actions reconciler** | #554 | Rohan | — |
| **Index-constituent history** | #543 | Kai | — |
| **Demo cut** | #556 | Nadia | Paper round-trip working |

**Blocker:** #498 (fill-model decision) MUST resolve before Kai can start #563. Nadia's job is to keep pinging Daisy until it's resolved.

**Cross-account isolation is the SEV-1 gate**: Mira owns unskipping the isolation spec (originally landed in PR #473, blocked on #546). This is the strictest quality bar in the entire project.

### M4 — P3 + Promotion (14 items — 9 P3 + 5 M4-checklist)

**P3 features (9):**

| Cluster | Issues | Owner |
|---|---|---|
| **Alerts** | #571 (engine), #574 (paper wiring), #576 (widget) | Kai (engine) + Priya (widget) + Rohan (wiring) |
| **News & Sentiment** | #564 (index tuning), #570 (analytics), #572 (route), #575 (widget) | Kai + Priya |
| **Backtest button** | #573 (wire), #577 (widget) | Kai + Priya |

**M4 promotion checklist (5):**

| # | Title | Owner |
|---|---|---|
| #565 | Nightly CI green on portfolio for 3 consecutive nights | Rohan + Mira |
| #566 | Documentation + release notes + APIEx/PythonEx complete | Nadia + Kai + Priya (each covers their surface) |
| #567 | Rebase portfolio onto develop + cut `pi-rc-1` tag | Rohan |
| #568 | **SINGLE `portfolio → develop` integration PR** (merge-commit) | Nadia opens on Daisy's sign-off; Zev reviews |
| #569 | Launch demo + retro + memory entry in `docs/MEMORIES.md` | Nadia |

**Zev's adversarial pass** happens before #568. Anything Zev flags as HIGH/CRITICAL blocks the PR from opening.

## Dependency graph (critical path)

```
M0 residuals ─── (Daisy #498) ─── ┐
                                  ▼
M1 P0 Data ──── (Kai primary, Rohan on cache) ────┐
                                                   ▼
                          ┌── M2 P1 X-Ray ─────────┐
                          ├── M2 P1 Events ────────┤
                          ├── M2 P1 Risk ──────────┤
                          └── M2 P1 Smart-Money ───┴─── (all four green) ───┐
                                                                             ▼
                                        M3 P2 Paper (Rohan+Kai) ────────────┐
                                        M3 P2 What-If (Kai+Priya) ──────────┤
                                        M3 P2 Attribution (Kai+Priya+Mira) ─┤
                                        M3 P2 SEV-1 isolation (Mira gate) ──┴─── (Mira signs) ─┐
                                                                                                ▼
                                                              M4 P3 Alerts + Sentiment + Backtest ─┐
                                                                                                    ▼
                                                                              M4 promotion checklist ─┐
                                                                                                       ▼
                                                                                            Zev veto pass ─┐
                                                                                                            ▼
                                                                                              [Daisy sign-off]
                                                                                                            ▼
                                                                            SINGLE portfolio → develop PR (#568)
```

## Session-count estimates (Nadia's honest read)

Per-issue session estimate rounded to 0.5s:

| Milestone | Items | Est. sessions | Notes |
|---|---|---|---|
| M0 residuals | 6 | 2–3 | Mostly PM/decision, one obsolete-close |
| **M1 P0** | 14 | 14–20 | 1 session per endpoint cluster; cache infra +2; preflight audit +1 |
| **M2 P1** | 17 | 20–28 | Each vertical slice ≈ 2 sessions (route+analytics, then widget) × 4 surfaces + Risk extras |
| **M3 P2** | 21 | 30–40 | Heaviest phase; paper engine + SEV-1 isolation are session-hungry |
| **M4 P3+promotion** | 14 | 12–18 | P3 features ≈ 2 sessions each; promotion is 3–4 sessions of docs + review |
| **Total** | 72 | **~78–110 sessions** | Wide range; SEV-1 isolation (#546-#548) is the biggest unknown |

**Suggested cadence:** milestone → milestone → milestone → milestone, with a Daisy check-in at each transition. No fixed calendar. If Daisy wants to translate to weeks, assume 1 session/day at 1 active dev-agent, or scale by active-agent count.

## Risks + open questions

1. **#498 (fill model source)** — blocks M3. Needs Daisy's decision. Nadia files a `pm:blocked-on-decision` label on it.
2. **#500 (Dolt bd schema bug)** — obsolete (bd retired). Nadia proposes closing as `not planned`. Awaiting Daisy's ack for the close (not blocking; will do in Stage 4).
3. **P0 fmp_cached coverage unknown** — Rohan's M1 preflight audit reveals the actual gap size. If gap count is huge (e.g. >8 of 14 clusters need fallback), M1 shifts to "fallback-heavy" mode and the `fmp_cached` team's queue becomes the M2 bottleneck. Nadia flags this if it happens.
4. **Corporate-actions reconciler (#554)** interacts with paper trading (#562/#544/#547). Nadia sequences #554 *before* Fills v1 (#544) so nightly reconciliation exists when partial fills land.
5. **Zev's veto** is codified as outright block on merge. If this becomes a bottleneck (Zev vetoes on nits), Nadia proposes a severity-scoped veto in a Stage 4 amendment.
6. **Nadia herself is an AI agent** — the "weekly Monday sync" (#505) is really a session-boundary sync, not a calendar meeting. Nadia will re-file #505's description in Stage 4 to reflect the AI-agent-team reality.

## Immediate next actions (Stage 4 candidates)

1. Close #500 as `not planned` (obsolete bd item).
2. Add `pm:blocked-on-decision` label to #498, pinging Daisy.
3. Re-describe #505 to reflect AI-agent session cadence rather than human weekly meeting.
4. Set Milestone field (`M1`/`M2`/`M3`/`M4`) on every open item in Project #4 per this doc's mapping.
5. File `feat/pi-ops/enforce-gh-closes-syntax` GH issue to prevent the tracker-drift class this audit fixed (CI reject PRs whose `Closes` clause doesn't cite a real `#NN`).
6. Kai + Rohan pair-run the M1 fmp_cached preflight audit → surfaces `area:fmp-cached-gap` issues *before* M1 code work starts.

**All of (1)–(6) need Daisy's ack for either the field-set operation or the new-issue filing.**

---

*This roadmap is a living document. Milestone content is authoritative until Daisy amends; session estimates are Nadia's honest read and will be revised as evidence accumulates.*
