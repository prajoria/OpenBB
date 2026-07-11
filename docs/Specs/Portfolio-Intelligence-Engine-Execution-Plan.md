# Execution Plan: Portfolio Intelligence Engine (`openbb-portfolio-intel`)

**Parent PRD:** [`Portfolio-Intelligence-Engine-PRD.md`](./Portfolio-Intelligence-Engine-PRD.md)
**Plan status:** Draft v1 — ready for staffing review
**Author:** Portfolio & Quant working group
**Reviewed by:** Engineering Manager / Execution Lead / Architect — review pass 2026-07-11 (verdict & conditions in §0A)
**Date:** 2026-07-11
**Assumed team size:** 4 engineers (3 backend, 1 full-stack) with fractional PM / QA support
**Assumed calendar:** 16 working weeks (P0 → P3), buffer excluded
**Optimization target:** maximize parallelism while keeping the critical path clean
**Branch model:** `portfolio` is the **long-lived integration branch** for this entire program. Every engineer's worktree branches from `portfolio` and merges back into `portfolio`. **`develop` is not touched** until the full product (P0 → P3, all four milestones green) is complete and signed off. See §2A for the full branching contract.

---

## 0. TL;DR

Four engineers, four swim lanes, sixteen weeks. **Lane A** (data) unblocks everyone
and must front-load. **Lane B** (extension router + analytics) is the intellectual
backbone. **Lane C** (portfolio_app integration + paper trading) is the largest single
scope. **Lane D** (widgets, UX, QA harness) is the delivery vehicle. Nothing after
Week 3 is single-threaded; the critical path runs through Lane B's factor/attribution
math and Lane C's fill engine.

| Milestone | Wk | Exit gate |
|---|---|---|
| **M0 — Kickoff & scaffolds land** | 1 | Repos branched off `portfolio`, extension skeleton merges CI green on `portfolio`, ticket graph drawn, worktree contract signed |
| **M1 — Data layer complete (P0)** | 3 | 32 new `fmp_cached` models pass round-trip + gap-detection tests — all merged to `portfolio` |
| **M2 — Phase 1 dashboard renders** | 8 | X-Ray + Events + Risk + Smart-Money widgets render live in Workspace against `portfolio` tip |
| **M3 — What-If + Attribution + Paper Engine (P2)** | 13 | Paper order round-trips end-to-end; Brinson matches reference values — all on `portfolio` |
| **M4 — Alerts + Sentiment + Backtest hand-off (P3) + `develop` merge** | 16 | One-click "backtest this portfolio" works; alert panel live; **single `portfolio` → `develop` integration PR merged** — first and only `develop` touch of this program |

---

## 0A. Engineering Review — Feedback & Conditions

> *Review pass by the Engineering Manager / Execution Lead / Architect, 2026-07-11.*
> *Verdict: **strong plan — approve to staffing review with conditions.** The lane
> decomposition, stub-first contracts, RACI, and per-lane Definition of Done are
> exemplary and above the bar for a program of this size. The items below must be
> resolved before the Week-0 sign-off.*

**Must-fix before kickoff (blocking):**

1. **Resourcing reconciliation vs. PRD.** PRD §20 assumes **1 senior + 1 mid
   (≈ 32 eng-weeks)**; this plan assumes **4 engineers × 16 wk (≈ 64 eng-weeks)** plus
   fractional PM/QA — a **~2× delta** leadership will challenge on sight. Pick one
   narrative and make the PRD and plan agree: either (a) this plan is the true cost and
   the PRD estimate was optimistic once Paper Trading (§16) entered scope — my read — or
   (b) de-scope this plan to the PRD's staffing. State it explicitly; do not let the two
   documents disagree in front of leadership.
2. **Shared-branch rebase hazard (§2A.4).** Rebasing the **long-lived, pushed**
   `portfolio` branch weekly rewrites history that all 8 live worktrees are based on.
   That is a git foot-gun, not a routine op. Decide at kickoff: **merge** `develop` →
   `portfolio` weekly (merge commits on an integration branch are harmless and M4 can
   still present a clean merge), or formalize a rebase-and-force-push-and-resync
   protocol with a fixed window. As written, §2A.4 and §2A.9 are in tension.
3. **Resolve Q8 *and* secure the Backtest team's committed date** before staffing P2.
   The fill-engine start (Wk 9) depends on both; the register rates the backtest
   dependency "Low" but the critical path runs straight through it.

**Should-fix (high-value):**

4. **P0 has zero buffer and sits on the critical path.** E1 ships 32 models + the
   derived-cache table in ~15 working days (~2 models/day, no slack). Any FMP surprise
   in Weeks 1–3 slips *everything* downstream. Add a half-week P0 buffer, or staff E3
   onto data work in Week 2 explicitly (currently only hinted).
5. **E3 bus factor is the #1 execution risk and the mitigation is thin.**
   "Cross-train E2 during P1 pairing" competes with E2 being 100% loaded in P1. Make
   the fill engine a **documented two-person deliverable** (E3 primary, E2 named backup
   with real check-ins), or split it into `orders/TIF` and `fills/corp-actions`
   sub-lanes so knowledge is not single-homed.
6. **QA at 0.25→0.5 FTE under-resources the highest-severity area.** Paper-trading
   isolation and the fill-model golden dataset are Sev-1 gates (PRD §21). Fund QA to
   **≥ 0.5 FTE for the entirety of P2**, not "→0.5".
7. **All-or-nothing value delivery.** Users see nothing until Week 16. Consider an
   **interim, feature-flagged release of the Phase-1 dashboard at M2 (Wk 8)**. This is
   in direct tension with the §2A "single `develop` merge" principle — surface that
   trade-off to leadership rather than defaulting to it.

**Consistency nits (fixed/flagged in place):**

8. M1 exit gate said "Extension skeleton **on main**" — contradicts the entire §2A
   contract. Corrected inline to `portfolio`.
9. Header says buffer **excluded**; §9 register says "1 buffer week baked into
   P1/P2/P3." Reconcile the buffer story — recommend stating buffer *included* and
   committing externally to **18 weeks** (matching the PRD review's 18–20 week
   envelope) while holding 16 as the internal stretch target.

---

## 1. Team Composition & Ownership

| Role | Alias | Primary lane | Secondary lane | Sample skills |
|---|---|---|---|---|
| Senior Backend / Data | **E1** | **Lane A — Data** | Lane B code review | Python, SQLAlchemy, MySQL, FMP quirks, gap detection |
| Senior Backend / Quant | **E2** | **Lane B — Analytics** | Lane C code review | Python, numpy/pandas, portfolio math, Brinson, VaR |
| Mid Backend / Trading | **E3** | **Lane C — Portfolio App + Paper** | Lane B pair | Python, FastAPI, order books, state machines |
| Mid Full-Stack / UX | **E4** | **Lane D — Widgets + QA** | Lane A test data | React/TS, OpenBB widgets.json, Playwright, pytest |
| **Fractional** — PM (0.25) | PM | Roadmap, stakeholder demos, gate reviews | — | — |
| **Fractional** — QA (0.25 → 0.5 in P2) | QA | Isolation tests, paper-fill golden data | — | — |

**Team-size sensitivity.** A 3-person cut (drop E4) is viable but adds ~4 weeks and
requires E2 or E3 to pick up widget work. **See §7** for the 3-person collapsed plan.

---

## 2. Swim Lanes (What Each Person Owns)

### Lane A — Data Layer (E1)
Owns everything under `openbb_platform/providers/fmp_cached/`.
- Adds 32 new FMP endpoint bindings per PRD §6/§10.1.
- Owns the derived-analytics cache table (§10.2).
- Owns gap-detection tests, fixture recording, and cache warmers.
- Reviewer of record for any code that reads FMP data.

### Lane B — Extension & Analytics (E2)
Owns `openbb_platform/extensions/portfolio_intel/` (the new extension).
- Router surface + Pydantic models (§9).
- X-Ray look-through algorithm (§11).
- Risk decomposition + Brinson attribution (§14).
- What-If diff engine (§15).
- Backtest hand-off contract (§16.9, in coordination with E3).

### Lane C — Portfolio App + Paper Trading (E3)
Owns `portfolio_app/src/intel.py` and everything in the `paper_*` namespace.
- New `/portfolio/intel/*` FastAPI routes (§8.1).
- Paper-trading tables, fill engine, corporate-action reconciler (§16).
- Cross-account isolation enforcement.
- P&L math shared with real-account service (single source of truth).

### Lane D — Widgets, UX, QA Harness (E4)
Owns `portfolio_app/widgets.json` additions, front-end contracts, and the test scaffolding.
- 14 new widgets (§18) with the PAPER badge/tint contract (§16.6).
- Playwright E2E flows for each widget.
- Recorded-fixture harness for the isolation test and Brinson reference values.
- Owns the demo script driven at every gate review.

---

## 2A. Branching Model & Worktree Contract (Non-Negotiable)

The entire program runs on a **single long-lived baseline branch** with git worktrees
for parallel development. `develop` is **frozen from this program's perspective**
until the M4 launch gate passes.

### 2A.1 Branch hierarchy

```
main (upstream, untouched by this program)
 │
 └─▶ develop (upstream integration branch — untouched until M4 launch)
      │
      └─▶ portfolio  ◀── THIS PROGRAM'S BASELINE (long-lived, ~4 months)
           │
           ├─▶ feat/pi-data/etf-holdings          (E1's worktree, ephemeral)
           ├─▶ feat/pi-data/earnings-calendar     (E1's worktree, ephemeral)
           ├─▶ feat/pi-router/xray                (E2's worktree, ephemeral)
           ├─▶ feat/pi-router/attribution         (E2's worktree, ephemeral)
           ├─▶ feat/pi-app/routes                 (E3's worktree, ephemeral)
           ├─▶ feat/pi-app/paper-fill-engine      (E3's worktree, ephemeral)
           ├─▶ feat/pi-widgets/xray-sector        (E4's worktree, ephemeral)
           └─▶ feat/pi-widgets/blotter            (E4's worktree, ephemeral)
```

### 2A.2 The three rules

1. **`portfolio` is the only integration point for this program.** Every feature
   branch merges into `portfolio`. Nothing in this program merges into `develop` or
   `main` until M4 passes.
2. **Every engineer works exclusively in a worktree off `portfolio`.** No direct
   commits to `portfolio`. No shared feature branches. Each worktree owns exactly
   one deliverable at a time (one `bd` ticket = one worktree = one PR).
3. **The single `develop` merge happens once — after M4 sign-off.** At that point
   `portfolio` is rebased onto the current `develop` tip, tested, and merged as a
   single well-documented integration. The `portfolio` branch is then retained for
   history and eventually deleted.

### 2A.3 Per-engineer worktree lifecycle

```bash
# Start of a new task (per bd ticket)
git worktree add ../wt-pi-<lane>-<slug> -b feat/pi-<lane>/<slug> portfolio
cd ../wt-pi-<lane>-<slug>
bd update <id> --claim              # per user-level CLAUDE.md

# During work
git commit -m "<type>(<scope>): <what> (bd-<id>)"

# When ready to integrate into portfolio
git checkout portfolio
git pull --ff-only                  # get latest portfolio tip
git checkout feat/pi-<lane>/<slug>
git rebase portfolio                # rebase so PR is clean
gh pr create --base portfolio --title "<title> (bd-<id>)"

# After PR merged
git worktree remove ../wt-pi-<lane>-<slug>
git branch -d feat/pi-<lane>/<slug>
bd close <id>
```

**Key discipline:** the PR **base** is *always* `portfolio`, never `develop` and
never `main`. A gh-cli alias or a repo `.github/pull_request_template.md` should
enforce this.

### 2A.4 Keeping `portfolio` current with upstream

`main` and `develop` keep moving during the 16 weeks. We do **not** want a big-bang
merge conflict at M4, so:

- **Weekly (Monday, PM-owned):** rebase `portfolio` onto the current `develop` tip.
  If a conflict emerges, E1/E2/E3/E4 pair on resolution the same day; do not carry
  conflicts into the workweek.
- **Any engineer resuming a worktree:** first `git fetch origin && git rebase
  portfolio` inside their worktree before writing new code. This keeps individual
  worktrees < 1 week old relative to `portfolio`, so rebases stay minutes not hours.
- **Never `git merge portfolio` inside a worktree** — always rebase. This keeps the
  eventual M4 → `develop` merge a clean linear replay.

> **[Architect review]** ⚠️ **This step is more dangerous than it reads.** `portfolio`
> is a *shared, pushed* long-lived branch; rebasing it onto `develop` rewrites history
> that all 8 worktrees are based on, forcing every engineer to hard-reset their base in
> lockstep. Recommend we **merge `develop` → `portfolio`** weekly instead — merge
> commits on an integration branch are harmless, and M4 can still present a clean merge
> to `develop`. If we insist on rebase, we need a written force-push-and-resync
> protocol and a fixed window during which no worktree is mid-rebase. Do not leave this
> ambiguous at kickoff (see §0A item 2).

### 2A.5 The M4 → `develop` merge (end-of-program)

Owned by **PM + E2**. Executed only after all M4 exit-gate checks pass.

```bash
# 1. Final rebase of portfolio onto develop
git checkout portfolio && git fetch origin && git rebase origin/develop

# 2. Full CI + full E2E suite must be green on the rebased tip
# 3. Cut a release candidate tag for traceability
git tag pi-rc-1 && git push origin pi-rc-1

# 4. Open the single integration PR
gh pr create --base develop --title "feat(portfolio-intel): Portfolio Intelligence Engine (P0-P3)" \
  --body "See docs/Specs/Portfolio-Intelligence-Engine-PRD.md and Execution-Plan.md. Closes bd-<epic>."

# 5. Merge with a merge commit (NOT squash) so per-ticket history survives in develop
```

### 2A.6 What CI runs, and where

| Branch | CI expectation |
|---|---|
| `feat/pi-*/*` (worktree branches) | Unit tests + lint on the lane's touched paths |
| `portfolio` (post-merge on every PR) | Full unit suite + integration suite + Playwright E2E |
| `portfolio` (nightly) | + fixture-refresh + cache-warm smoke + full paper-order round-trip |
| **PR into `develop` (M4 only)** | Everything above + `develop`'s existing suite + release-cut dry-run |

### 2A.7 Beads coordination on the `portfolio` branch

Per user-level `CLAUDE.md` §Rule 2 (one bead → one branch → one PR), every worktree
maps to exactly one `bd` ticket. Because all worktrees stack on `portfolio` — a
long-lived branch — dependency wiring (`bd link --blocked-by`) becomes essential:

- **Data-layer models must complete before analytics that depend on them.** File the
  `--blocked-by` link the moment a dependency is spotted.
- **Paper-trading tables (E3) must land before paper widgets (E4).** Explicit link.
- **Router models (E2) block widget contracts (E4).** Explicit link.

`bd ready` will then reflect the true parallelism available on `portfolio` at any
moment, preventing two engineers from grabbing conflicting work.

### 2A.8 Handling upstream hotfixes to `main`/`develop`

If a critical hotfix lands on `develop` (security, provider outage, licensing) mid-program:

- Do **not** merge it into worktrees individually.
- PM triggers an **immediate** `portfolio` rebase onto the new `develop` tip.
- Worktree owners rebase their branches onto the new `portfolio` tip the same day.
- The hotfix is therefore visible in every worktree within 24 h without polluting
  `develop` with in-flight PI work.

### 2A.9 Explicit anti-patterns

| Anti-pattern | Why it's banned |
|---|---|
| Merging any `feat/pi-*` branch into `develop` before M4 | Fragments the program's history; forces `develop` to carry half-built features |
| Committing directly to `portfolio` | Skips PR review; breaks CI gating; violates one-bead-one-PR |
| Merging (not rebasing) `portfolio` into a worktree | Creates merge-commit noise that survives to `develop` at M4 |
| Two engineers sharing one worktree branch | Racy pushes; unclear ownership |
| Long-lived worktree branches (> 2 weeks) | Rebase becomes painful; parallel work stalls |
| Cherry-picking a `portfolio` commit onto `develop` "for urgency" | Bypasses the M4 gate — the very thing that guarantees the product ships whole |

> **[Execution Lead review]** The "single `develop` merge at M4" rule optimizes for a
> *cohesive* launch but delays **all** user value to Week 16 and concentrates
> integration risk into one PR. That is a defensible product call — but it is a
> **leadership decision, not an engineering default.** Put the alternative on the
> table: ship the Phase-1 dashboard behind a feature flag to `develop` at M2 (Wk 8) for
> early feedback and incremental integration. See §0A item 7.

---

## 3. Phase-by-Phase Execution

Notation:
- `▓▓▓` = focused week for that engineer
- `░░░` = reserved capacity (review, pairing, spillover)
- `⋯` = idle / rolling to next phase

### P0 — Data-Layer Gap Fill (Weeks 1–3)

**Goal:** every FMP endpoint the rest of the plan needs is cached, tested, and gap-detected before Week 4.

| Wk | E1 (Data) | E2 (Analytics) | E3 (App / Paper) | E4 (Widgets / QA) |
|---|---|---|---|---|
| 1 | ▓ Scaffold 32 model files; wire 1 as reference (`EtfHoldings`) | ▓ Extension skeleton (`portfolio_intel/router.py`, models, CI) | ▓ New `intel.py` service module; wire empty routes; DB migration for `paper_*` tables | ▓ `widgets.json` schema audit; add 3 placeholder widgets that hit stub endpoints |
| 2 | ▓ Ship 15 more models (Calendars + Analyst + Insider + Senate) | ▓ X-Ray look-through algorithm on stub data + unit tests | ░ Pair with E1 on cache API; prototype paper_orders CRUD | ▓ Playwright harness + widget contract test skeleton |
| 3 | ▓ Ship remaining 16 models (13F, SEC, News, Economic, Sector, TI) + derived-cache table | ▓ Concentration + HHI + exposure rollups; consume E1's real models | ▓ Read-path for `portfolio_basket` → intel router; JSON contract fixtures | ▓ E2E test: `X-Ray` widget renders against seeded cache |

**M1 exit gate (end of Week 3):**
- ✅ All 32 models unit-tested + gap-detection tested
- ✅ `EtfHoldings` fixture used in an E2E test that renders a widget
- ✅ Extension skeleton on `portfolio` *(was "on main" — corrected per §2A; nothing in this program touches `main`/`develop` before M4)*; CI green
- ✅ `paper_*` tables migrated in a scratch DB

**Parallelism note.** E1 is on the critical path in P0. E2/E3 use `EtfHoldings`
delivered end of Week 1 as their reference; they *build against stubs* for anything
not yet cached and swap in real reads as models land through Week 2/3. This is the
single biggest parallelization lever.

---

### P1 — X-Ray + Events + Risk + Smart-Money (Weeks 4–8)

**Goal:** the four Phase-1 widgets render live in a real Workspace against a real portfolio.

| Wk | E1 (Data) | E2 (Analytics) | E3 (App / Paper) | E4 (Widgets / QA) |
|---|---|---|---|---|
| 4 | ░ Cache warmers for common ETFs; fixtures for gate reviews | ▓ Event Calendar merge algorithm (§12) | ▓ `/portfolio/intel/xray` end-to-end wire-up | ▓ X-Ray Sector + Country pie widgets |
| 5 | ░ Smart-Money bulk-load path (filtered 13F for held CUSIPs) | ▓ Smart-Money aggregator (§13) | ▓ `/portfolio/intel/events` + timeline shape | ▓ Event Calendar timeline widget + drill-down |
| 6 | ░ Perf tune: derived-cache TTLs; index review | ▓ Risk metrics (Sharpe/VaR/CVaR/Max DD) shared with `Analysis/` | ▓ `/portfolio/intel/smart_money` roll-up | ▓ Smart-Money ribbon widget + PAPER badge component |
| 7 | ░ Cache-hit ratio instrumentation | ▓ Contribution-to-risk (marginal + component VaR) | ▓ Risk dashboard endpoint; concentration/HHI wire-up | ▓ Risk Dashboard widget (number-grid + rolling-vol chart) |
| 8 | ░ Buffer + Lane-A backfill of any late endpoints | ░ Buffer + docstrings + APIEx/PythonEx | ░ Buffer + pytest coverage push | ▓ **M2 demo build** — full 8-widget dashboard; Playwright green |

**M2 exit gate (end of Week 8):**
- ✅ 4 Phase-1 widgets render in a real Workspace against a real portfolio
- ✅ Warm-cache p95 latency targets met (§19)
- ✅ Unit coverage ≥ 90% on `portfolio_intel/*`
- ✅ Recorded demo cut for leadership

**Parallelism note.** All four engineers are 100% loaded. E1 downshifts to
"reactive" mode — perf tuning + backfill of any FMP endpoint that turns out to be
flakier than expected. That reserve capacity is what buys P1 its schedule confidence.

---

### P2 — What-If + Attribution + Paper Trading (Weeks 9–13)

**Goal:** ship the What-If diff view, Brinson attribution, and the full paper-trading engine end-to-end.

This is the **highest-risk phase**. Paper trading has the most surface area (5 new tables, fill engine, corporate-action reconciler, isolation guarantees). We front-load it and let attribution + what-if run in parallel behind E2.

> **[EM review]** Two staffing concerns concentrate in this phase. **(1) E3 is a single
> point of failure** on the critical path for five straight weeks — name a real backup
> and schedule the pairing, or split the fill engine into `orders/TIF` and
> `fills/corp-actions` sub-lanes so the knowledge is not single-homed. **(2) QA is
> fractional** exactly where correctness matters most: the isolation guarantee and the
> fill-model golden dataset are Sev-1 gates (PRD §21). Fund QA to ≥ 0.5 FTE for all of
> P2. See §0A items 5–6.

| Wk | E1 (Data) | E2 (Analytics) | E3 (App / Paper) | E4 (Widgets / QA) |
|---|---|---|---|---|
| 9 | ▓ Index-constituent history models (SPY/QQQ/IWM/ACWI) for Brinson | ▓ What-If diff engine (§15) — stateless recompute | ▓ Fill engine v0: market + limit; TIF=day/gtc | ▓ Order Ticket widget UX (form + confirm) |
| 10 | ░ Cache constituents; nightly refresh job | ▓ Brinson-Fachler attribution (allocation vs. selection) | ▓ Fill engine v1: stop / stop_limit / trailing_stop + partial fills | ▓ Blotter widget + PAPER badge everywhere |
| 11 | ░ Corporate-action feed hardening (splits, div ex-dates) | ▓ Pair with E4 on What-If diff-view shape | ▓ Corporate-action reconciler (nightly job) + `paper_ledger` | ▓ Paper Performance widget (equity curve + KPI grid) |
| 12 | ░ Fixture set for Brinson reference values | ▓ Attribution waterfall shape + tests vs. reference | ▓ `paper.account.export_backtest` command + isolation tests | ▓ What-If diff card widget (interactive) |
| 13 | ░ Buffer | ░ Buffer + docs | ▓ Hardening: race conditions in fill engine; replay/audit | ▓ **M3 demo build** — paper trade → filled → X-Ray on paper account |

**M3 exit gate (end of Week 13):**
- ✅ Paper account round-trips a limit order (submit → fill → P&L update)
- ✅ Every intelligence widget works against paper via `?account_id=paper_*`
- ✅ Automated isolation test asserts no cross-account leakage
- ✅ Brinson matches reference values (Bloomberg or manually verified) to ±1 bp
- ✅ QA sign-off on the fill-model golden dataset

**Parallelism note.** E3 is on the critical path for the whole quarter here. E2's
attribution work is intentionally *decoupled* from paper trading (they share no
schema) so Lane C can burn full-throttle without cross-lane synchronization.

---

### P3 — News + Sentiment + Alerting + Backtest Hand-off (Weeks 14–16)

**Goal:** close the flywheel — every widget shipped, alerts live, one-click backtest working.

| Wk | E1 (Data) | E2 (Analytics) | E3 (App / Paper) | E4 (Widgets / QA) |
|---|---|---|---|---|
| 14 | ▓ News + press-release + 8-K endpoint tuning | ▓ Sentiment roll-up (weighted analyst) | ▓ `obb.backtest.portfolio` wire-up (contract) | ▓ News widget + Sentiment widget |
| 15 | ░ Alert-relevant query indices | ▓ Alert-rule engine (pinned alerts) | ▓ Alert-rule wiring on `paper_*` events (fills, stops, TIF) | ▓ Alert panel component + subscription plumbing |
| 16 | ░ Buffer + release fixtures | ░ Buffer + release docs | ░ Buffer + release notes | ▓ **M4 launch demo**, full E2E, docs site, release cut |

**M4 exit gate (end of Week 16):**
- ✅ All 14 widgets shipped
- ✅ Alert panel renders and fires on all 6 trigger types
- ✅ "Backtest this portfolio" opens `openbb-backtest` with the correct payload
- ✅ Docs published; release notes cut; internal changelog updated
- ✅ Stakeholder demo delivered
- ✅ **`portfolio` branch fully green on nightly CI for 3 consecutive nights**
- ✅ **Single `portfolio` → `develop` integration PR opened, reviewed, and merged per §2A.5** — this is the *first and only* time this program touches `develop`

---

## 4. Dependency Graph (Critical Path)

```
                      ┌─────────────────────────────────────────────┐
                      │  E1: EtfHoldings model  (end of Wk 1)        │  ◀── unblocks E2 X-Ray
                      └────────────────────┬────────────────────────┘
                                           ▼
                      ┌─────────────────────────────────────────────┐
                      │  E2: X-Ray algorithm  (Wk 2)                │  ◀── unblocks E4 pie widgets
                      └────────────────────┬────────────────────────┘
                                           ▼
                      ┌─────────────────────────────────────────────┐
                      │  E3: /portfolio/intel/xray wire  (Wk 4)     │  ◀── unblocks M2 demo
                      └────────────────────┬────────────────────────┘
                                           ▼
                             ─── P1 ships (Wk 8) ───
                                           ▼
     ┌─────────────────────────────────────┴──────────────────────────────────┐
     ▼                                                                        ▼
┌────────────────────────────┐                            ┌──────────────────────────────┐
│  E2: Attribution + What-If │                            │  E3: Paper fill engine       │  ← CRITICAL PATH
│  (Wk 9–12)                 │                            │  (Wk 9–13)                   │
└──────────┬─────────────────┘                            └──────────────────┬───────────┘
           ▼                                                                 ▼
                     ────────── M3 gate (Wk 13) ──────────
                                           ▼
                     ────── P3 (Wk 14–16) → M4 launch ──────
```

**The critical path** is: `E1 EtfHoldings → E2 X-Ray algo → E3 route → M2 demo → E3 Paper fill engine → M3 gate → M4 launch.` Everything else can slip a week without moving M4.

---

## 5. Parallelism Enablers

Five specific practices keep 4 people productive at the same time without stepping on each other:

1. **Stub-first contracts (Week 1 mandate).** E2 publishes the Pydantic response
   models for every §11–§14 endpoint before writing the algorithms. E3 and E4 build
   against those models immediately, using deterministic stubs. When E2's real
   implementation lands, no downstream code changes.
2. **Per-lane worktree branch strategy.** `feat/pi-data/*` (E1), `feat/pi-router/*`
   (E2), `feat/pi-app/*` (E3), `feat/pi-widgets/*` (E4). Each engineer works in an
   isolated **git worktree** off the `portfolio` baseline (per §2A). Each PR merges
   to `portfolio` — **never** to `develop` — independently once its lane's CI is
   green. No long-lived feature branches (≤ 2 weeks per §2A.9). The single
   `portfolio` → `develop` merge happens once, at M4.
3. **Recorded FMP fixtures.** Every 🆕 model E1 lands ships with a recorded HTTP
   response fixture. E2 and E3 tests never hit live FMP. This eliminates the "cache
   isn't warm yet" blocker.
4. **`paper_*` schema frozen at end of Week 3.** Once E3 has locked the paper table
   shapes, E4 can build the Blotter widget in parallel against a mocked service. The
   fill engine implementation is then a **behind-the-scenes** deliverable, not a
   schema deliverable.
5. **QA works ahead of implementation.** QA writes the isolation-test spec, the
   fill-model golden dataset, and the Brinson reference values *before* code lands.
   Implementation is measured against a pre-existing bar.

---

## 6. RACI Matrix (Deliverables × People)

| Deliverable | E1 | E2 | E3 | E4 | PM | QA |
|---|---|---|---|---|---|---|
| 32 new `fmp_cached` models | **R/A** | C | C | I | I | C |
| Derived-analytics cache | **R/A** | C | I | I | I | I |
| X-Ray algorithm | C | **R/A** | C | I | I | C |
| Event Calendar merge | I | **R/A** | C | I | I | C |
| Smart-Money aggregator | C | **R/A** | C | I | I | C |
| Risk / VaR / attribution | I | **R/A** | I | I | I | **C** |
| What-If diff engine | I | **R/A** | C | I | I | C |
| Router surface (`obb.portfolio.intel.*`) | I | **R/A** | C | I | I | I |
| `/portfolio/intel/*` routes | I | C | **R/A** | C | I | I |
| Paper account CRUD | I | I | **R/A** | I | I | C |
| Paper fill engine | I | C | **R/A** | I | I | **C** |
| Corporate-action reconciler | C | I | **R/A** | I | I | C |
| Paper isolation guarantees | I | I | **R/A** | C | I | **R** |
| 14 widgets in `widgets.json` | I | C | C | **R/A** | I | C |
| PAPER badge / tint contract | I | I | C | **R/A** | **C** | C |
| Playwright E2E suite | I | I | I | **R/A** | I | **C** |
| Docs / APIEx / PythonEx | C | **R/A** | C | I | I | I |
| Release notes + changelog | I | C | C | C | **R/A** | I |
| Stakeholder demos | I | C | C | **R** | **A** | I |
| Gate reviews (M1–M4) | C | C | C | C | **R/A** | **R** |

*(R = Responsible · A = Accountable · C = Consulted · I = Informed)*

---

## 7. 3-Person Fallback Plan

If E4 is unavailable, the plan compresses to 3 lanes and adds **~4 weeks** (final delivery Wk 20).

| Change | Impact |
|---|---|
| Merge Lane D into Lanes B/C: E2 owns pie/table widgets; E3 owns paper widgets | Adds ~2 wks to P1 and ~2 wks to P2 |
| QA owned rotationally by all three | Isolation-test spec still authored, but Playwright automation drops from launch scope to fast-follow |
| Cut §16.7 replay endpoint from Phase 2 to v2 | Recovers 1 week in P2 |
| Cut News + Sentiment widgets from launch (endpoints still ship) | Recovers 1 week in P3 |

3-person delivery target: **20 weeks** with the same M-gates in the same order.

---

## 8. Rituals & Ceremonies

- **Daily standup** — 15 min async or sync; one line per person: yesterday / today / blocked.
- **Weekly design review (Wed, 45 min)** — one topic at a time, rotating owner.
  Weeks 1–3: schemas; Weeks 4–8: widget shapes; Weeks 9–13: paper fill semantics.
- **Bi-weekly stakeholder demo (Fri)** — 20 min. Owned by E4, MC'd by PM.
- **Gate reviews (M1, M2, M3, M4)** — 60 min, all 4 engineers + PM + QA + a
  representative from the Backtest and Quant PRDs. Must produce written go/no-go.
- **Blameless post-mortem** on any missed gate — within 5 business days.

---

## 9. Risk Register (Execution-Specific)

*(Product risks live in PRD §21. This table tracks risks to the plan itself.)*

| Risk | Severity | Owner | Mitigation |
|---|---|---|---|
| E1 blocks P0 → cascades to P1 delay | **High** | E1 + PM | Priority-order models by downstream demand (EtfHoldings + Calendars first); pair E3 on Week 1 to unblock second endpoint |
| E3 (Lane C, longest lane) leaves mid-P2 | **High** | PM | Cross-train E2 on paper fill engine in P1 pairing; keep `paper_*` schema and fill rules documented weekly |
| Widget contract churn → E4 rework | Med | E2 + E4 | Freeze Pydantic response models at end of Week 1; schema changes require both E2 + E4 sign-off |
| FMP endpoint returns malformed / incomplete data | Med | E1 | Every model has a graceful-degradation path + a `data_quality` flag surfaced to widgets |
| Paper fill engine race conditions | Med | E3 + QA | Single-writer per account_id; property-based tests; explicit lock ordering documented |
| Brinson reference values disagree with our impl | Low-Med | E2 + QA | QA sources 2 independent references (Bloomberg + spreadsheet); tolerances documented |
| Team velocity assumption too aggressive | Med | PM | 1 buffer week baked into P1 (Wk 8), P2 (Wk 13), P3 (Wk 16) — do not backfill with new scope |
| Backtest engine PRD delayed → §16.9 hand-off breaks | Low | E3 + PM | Ship `paper.account.export_backtest` as a JSON dump behind a feature flag; wire to real engine when available |
| Scope creep from stakeholder demos | Med | PM | Every new ask gets a `bd` ticket; nothing enters the plan without gate-review approval |
| `portfolio` diverges from `develop` over 16 weeks → nightmare M4 merge | **High** | PM + E2 | Weekly Monday rebase of `portfolio` onto `develop` per §2A.4; conflicts resolved same-day; long-lived worktrees banned |
| Someone accidentally targets a PR at `develop` instead of `portfolio` | Med | PM | Branch protection on `develop` requires PM approval; PR template defaults to `portfolio`; CI check rejects `feat/pi-*` PRs targeting `develop` |
| M4 integration PR too large to review | Med | PM + E2 | Per-ticket merge commits preserved (§2A.5 step 5); reviewer walks PR by folder; RC tag pinned for rollback |

> **[EM review]** Two risks are under-weighted in this table. **(a)** The **team-size
> delta vs. PRD §20** (4 eng vs. 1 senior + 1 mid) is a *staffing-approval* risk, not
> just a plan risk — add it as an explicit row owned by PM and surface it to leadership.
> **(b)** Row 10 (weekly `portfolio` rebase) is rated High correctly, but its
> *mitigation is itself the hazard* — rebasing a shared, pushed branch. Prefer
> merge-based upstream sync per the architect note in §2A.4. Also missing: a
> **CI-cost / FMP-rate-limit** risk for the nightly cache-warm + full paper round-trip
> against live FMP — quantify the token budget before it bites.

---

## 10. Definition of Done (Per Lane)

Every merge to `portfolio` must clear these bars. No exceptions.

**Lane A (Data)**
- [ ] Pydantic model + SQLAlchemy table + gap-detection query
- [ ] Recorded HTTP fixture for the endpoint
- [ ] Round-trip unit test (fetch → cache → re-read → equality)
- [ ] Gap-detection test (partial cache → fills gap on read)
- [ ] `data_quality` metadata surfaced

**Lane B (Analytics)**
- [ ] Pure-function core (no I/O in math modules)
- [ ] Unit tests at 90% coverage + at least one property-based test
- [ ] APIEx + PythonEx examples in docstring
- [ ] Reference-value test (X-Ray sums to 100%, Brinson sums to active return, etc.)
- [ ] Router command registered + integration test

**Lane C (Portfolio App + Paper)**
- [ ] FastAPI route + OpenAPI schema
- [ ] Data access uses `portfolio_basket` or `paper_*` only (SQL grep test enforces this)
- [ ] Isolation test: no query returns a cross-account row
- [ ] For paper: replay test — reconstructing account state from `paper_ledger` matches live state
- [ ] Latency budget met (§19)

**Lane D (Widgets + QA)**
- [ ] `widgets.json` entry validated against schema
- [ ] Playwright test renders the widget with mocked data
- [ ] Playwright test renders the widget with live cache
- [ ] PAPER badge appears when and only when `account_id` starts with `paper_`
- [ ] Widget survives a full workspace reload

---

## 11. Kickoff Checklist (Week 0)

Owner: **PM**. Must be complete before Week 1 stands up.

- [ ] `portfolio` branch cut from `develop`; agreed as long-lived integration branch per §2A
- [ ] Branch protection on `portfolio`: PRs required, CI required, no force-push, no direct commits
- [ ] Branch protection on `develop`: PRs from `portfolio` require **PM + one senior engineer** review (blocks accidental early merge)
- [ ] `.github/pull_request_template.md` sets default base to `portfolio` for `feat/pi-*` branches
- [ ] Weekly `portfolio`-onto-`develop` rebase cadence on shared calendar (Monday, PM-owned per §2A.4)
- [ ] `bd` epic `pi-e1` filed; child issues for M1–M4 filed and linked with `--blocked-by` per §2A.7
- [ ] Extension skeleton `openbb_platform/extensions/portfolio_intel/` scaffolded (PR ready for E2, base=`portfolio`)
- [ ] `paper_*` migration file drafted and reviewed by E1 + E3
- [ ] Recorded-fixture directory `tests/fixtures/fmp/` created; fixture-record CLI documented
- [ ] Playwright harness added to `portfolio_app/tests/e2e/`
- [ ] Isolation-test spec (§16.6) authored by QA and merged as a *pending* test
- [ ] Stakeholder demo cadence scheduled on shared calendar (bi-weekly Fri)
- [ ] Gate-review meetings booked (end of Wk 3, Wk 8, Wk 13, Wk 16)
- [ ] Decision made on **Q8** (paper fill model: built-in or shared with `openbb-backtest`); PRD updated accordingly
- [ ] Every engineer has cloned the repo and successfully created their first worktree per §2A.3
- [ ] Every engineer has confirmed the shared dev-env file **`H:\masterswork\git\.env`** is readable and loadable from their worktree (see Appendix A). No engineer starts Lane A/B/C work without a green `python -c "from dotenv import load_dotenv; load_dotenv(r'H:/masterswork/git/.env'); import os; assert os.environ['FMP_API_KEY']"` from their worktree root.

> **[Execution Lead review]** Two of these deserve to be **hard blockers**, not mere
> checkboxes: **Q8** (fill-model decision) *and* a **written committed date from the
> Backtest team** for the shared execution primitive — P2 staffing (Wk 9) must not lock
> until both exist. One thing is **missing**: a **Definition of Ready** for tickets
> entering a lane. The plan has an excellent Definition of Done (§10) but no entry bar,
> which is where stub contracts, fixtures, and `--blocked-by` links should be verified
> *before* work starts.

---

## 12. What This Plan Explicitly Does *Not* Cover

- **Data seeding** of the derived-analytics cache for existing users at launch — a
  cache-warm background job is in scope; a bulk migration script is not.
- **Multi-tenant deployment** (SaaS mode). Everything assumes single-user desktop /
  self-hosted, matching the current `portfolio_app` posture.
- **Alerting infrastructure beyond in-widget panels** — push notifications and email
  digests are v2 per PRD §17.
- **Broker connectivity for real trading.** Explicitly excluded per PRD §3.2 NG1.
- **Localization / i18n.** Widgets ship in English only for launch.

---

## 13. Appendix B — Weekly One-Liner Cheat Sheet

*(For standups and status emails — one bullet per week per engineer.)*

| Wk | E1 | E2 | E3 | E4 |
|---|---|---|---|---|
| 1 | Reference model shipped | Router skeleton green | Empty routes + paper migration | Widget scaffolds live |
| 2 | 15 calendars/analyst/insider models | X-Ray algo passing on stub | Paper CRUD prototype | E2E harness green |
| 3 | 16 remaining models + derived cache | Concentration/HHI/exposures | intel router wired | X-Ray Sector widget renders live |
| 4 | Cache warmers | Event Calendar merge | X-Ray endpoint live | X-Ray Country widget |
| 5 | Smart-Money bulk load | Smart-Money aggregator | Events endpoint live | Timeline widget |
| 6 | Perf tuning | Risk metrics | Smart-Money endpoint live | Ribbon + PAPER badge |
| 7 | Cache-hit instrumentation | Component VaR / contribution | Risk endpoint + concentration | Risk Dashboard widget |
| 8 | Buffer | Buffer + docs | Buffer | **M2 demo** |
| 9 | Constituent history | What-If diff | Fill engine v0 | Order Ticket widget |
| 10 | Nightly constituent refresh | Brinson attribution | Fill engine v1 (stops, trails) | Blotter widget |
| 11 | Corp-action hardening | Pair on diff-view | Corp-action reconciler | Paper Performance widget |
| 12 | Brinson fixtures | Attribution waterfall | export_backtest + isolation | What-If diff card |
| 13 | Buffer | Buffer | Race hardening + replay | **M3 demo** |
| 14 | News/8-K tuning | Sentiment rollup | backtest.portfolio wire | News + Sentiment widgets |
| 15 | Alert query indices | Alert-rule engine | Paper-event alerts | Alert panel |
| 16 | Release fixtures | Release docs | Release notes | **M4 launch demo + `portfolio` → `develop` merge (§2A.5)** |

---

*End of Execution Plan.*

---

## Appendix A — Developer Environment (Shared `.env`)

**Location:** `H:\masterswork\git\.env` — one level above this repo checkout, shared
across every OpenBB fork in `H:\masterswork\git\` (including this program's worktrees).

**Why it lives outside the repo.** It is gitignored by design: it carries live API
keys and DB credentials that must never enter git history. Because it lives in the
**parent** directory of every checkout, every worktree (`H:\masterswork\git\OpenBB\`,
`H:\masterswork\git\OpenBB-Portfolio\OpenBB\`, and any `.claude/worktrees/*` under
them) sees the same file automatically when loaded with an explicit path.

### A.1 What the file provides

The shared `.env` supplies the settings every dev agent in Lanes A/B/C/D needs to run
the fork end-to-end without hand-configuring each worktree. Grouped by concern:

| Group | Variables |
|---|---|
| **FMP provider** | `FMP_API_KEY`, `FMP_BASE_URL`, `FMP_CACHE_TEST_MODE` |
| **MySQL cache + portfolio DB** | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_TEST_DATABASE` |
| **Azure / OpenAI (for optional LLM/agent surfaces)** | `AZURE_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_ENDPOINT` |
| **Runtime tunables** | `DEBUG`, `LOG_LEVEL`, `DEFAULT_TIMEOUT`, `RATE_LIMIT_DELAY` |
| **Path plumbing** | `PYTHONPATH`, `QUANT_REPO_PATH` |

*(Actual values are read from the file at runtime — never quoted or logged in code,
CI output, or documentation.)*

### A.2 How each Lane consumes it

**Lane A (E1 — Data).** `fmp_cached` uses `FMP_API_KEY` for gap-fill fetches and the
`MYSQL_*` variables for cache reads/writes. Recorded-fixture generation reads from the
live FMP endpoint once, then all subsequent tests run offline. `FMP_CACHE_TEST_MODE=1`
short-circuits network calls in unit tests.

**Lane B (E2 — Analytics).** No direct FMP access. Reads the cache only. Needs the
`MYSQL_*` block to run integration tests against a warm cache.

**Lane C (E3 — Portfolio App + Paper).** Needs the full `MYSQL_*` block (writes to
`paper_*` tables), and inherits `FMP_API_KEY` transitively through the provider for
live-price quotes into the fill engine.

**Lane D (E4 — Widgets + QA).** Playwright E2E tests need the full block so the
`portfolio_app` under test can boot with real cache access. CI runs may substitute a
sealed test `.env` with `FMP_CACHE_TEST_MODE=1` to keep tests hermetic.

### A.3 Loading pattern (canonical)

Every dev agent — Claude subagent or human — uses the same loader so the behavior is
identical across worktrees. Add this at the top of any script or notebook that needs
credentials, and to `portfolio_app/src/db.py` if not already present:

```python
from dotenv import load_dotenv
import os
from pathlib import Path

# Explicit path — never rely on cwd discovery for the shared .env
_ENV_PATH = Path(r"H:/masterswork/git/.env")
load_dotenv(_ENV_PATH, override=False)   # override=False so per-worktree overrides win

# OpenBB reads user_settings.json automatically — no manual credential setting needed
```

`override=False` means an engineer can drop a local `.env` inside their worktree to
override any single variable (e.g. point at a scratch MySQL) without editing the
shared file. The shared file remains the source of truth.

### A.4 Per-worktree override pattern

When a worktree needs a different value (scratch DB, alternate FMP tier, DEBUG=true):

```
H:\masterswork\git\OpenBB-Portfolio\OpenBB\
├── .env               ← per-worktree override (gitignored)
└── ...
```

Loader order in code:
1. Load shared `H:\masterswork\git\.env` with `override=False`.
2. Load local `./.env` with `override=True`.

This gives every dev agent a predictable environment stack: **shared defaults +
local overrides**, no accidental cross-contamination.

### A.5 Security posture

- The shared `.env` **must remain outside every git repo** in
  `H:\masterswork\git\`. Confirm with `git check-ignore` before every commit that
  touches env plumbing.
- No `.env`, `user_settings.json`, or key material of any kind may ever be committed
  to `portfolio`, `develop`, or any `feat/pi-*` branch. Both branch-protection rules
  in §11 already require this; secret-scanning (detect-secrets pre-commit hook, per
  project CLAUDE.md) is the last line of defense.
- Rotation: if any key in the shared `.env` is rotated (FMP tier upgrade, Azure key
  cycle), PM broadcasts to the team and every worktree owner runs the loader
  smoke-test from §11 within 24 h.

### A.6 Dev-agent (LLM subagent) contract

Any Claude/subagent dispatched under this program:

1. Assumes `H:\masterswork\git\.env` exists and is readable.
2. Uses the §A.3 loader pattern verbatim — never hardcodes a path, never inlines a
   key, never `echo`s a key to the terminal.
3. When it needs a variable, reads it via `os.environ[...]`, never via
   command-substitution that could leak into a log.
4. If the loader fails (missing file, missing key), the agent stops and surfaces
   the failure to the parent turn — it does **not** attempt to synthesize a
   fallback key or a placeholder.

