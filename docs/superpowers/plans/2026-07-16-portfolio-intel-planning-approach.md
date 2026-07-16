# Portfolio Intelligence Engine — Planning Approach (Draft)

**Status:** DRAFT — awaiting user confirmation on Stage 2 wording + audit doc location before execution.
**Date:** 2026-07-16
**Author:** Claude (session on `portfolio` branch)
**Repo:** `prajoria/OpenBB` — https://github.com/prajoria/OpenBB
**Branch:** `portfolio` (integration; `develop → portfolio` one-way absorb; `portfolio → develop` gated on Daisy's loud sign-off at M4)
**Project:** [Portfolio Intelligence Engine (#4)](https://github.com/users/prajoria/projects/4) — private, 90 items, all Issues

---

## Provider policy — design rule for every dev on the team

**`fmp_cached` first, `fmp` is fallback, never yfinance.**

- **Default:** every data call goes through `fmp_cached`. `PRIMARY_PROVIDER = "fmp_cached"` in `stock_analysis.py` stays the source of truth for the constant.
- **Fallback path:** only when `fmp_cached` genuinely does not cover the endpoint you need. Ideally that is zero cases — treat every fallback as a gap that must be closed **by someone else** (see scope boundary below).
- **When a gap is hit** (required workflow, not optional):
  1. Use `fmp` for the immediate call so the roadmap doesn't stall. If a future workstream introduces a genuinely new data domain not covered by either fmp variant, use whatever provider is available (FRED, EOD-HD, etc.) under the same file-a-gap-issue discipline.
  2. File a GH issue in `prajoria/OpenBB`, add it to Project #4, label `area:fmp-cached-gap`. Body must include: missing endpoint, calling context (which milestone / widget / analysis path), what needs to be added to `providers/fmp_cached/`.
  3. Add a `# TODO(gh-<NN>): migrate to fmp_cached once endpoint lands` comment at the fallback call-site so the debt is visible in every future diff, `grep`-able, and reviewer-visible in PRs.
- **Scope boundary — hard rule:** a **separate team** owns `providers/fmp_cached/`. The portfolio team **does not** implement `fmp_cached` extensions. Ever. File the gap issue with enough context that the `fmp_cached` team can act on it, then move on with the fallback. Do not open PRs adding endpoints to `fmp_cached`, even for "trivial" cases — cross-team boundary violations create merge conflicts and duplicated work.
- **Reviewer discipline (Mira gate, Zev veto):** any PR introducing an `fmp` fallback that does *not* have a paired `area:fmp-cached-gap` GH issue is rejected. Codified rule, no reviewer judgment needed. **Also rejected:** any PR from the portfolio team that touches `providers/fmp_cached/` source (crossing the scope boundary).
- **Rationale:** `fmp_cached` gives reproducible tests (integration tests without live API costs on every run), deterministic dev loops (a hit on cache is instant), and cost control (no rate-limit surprises during CI). The fallback exists so a missing endpoint never blocks a milestone — every use is tracked debt handed off to the owning team.

### Which phases lean on which provider?

Working from the epic's product surfaces:

| Product surface | Primary data need | `fmp_cached` coverage (expected) | Likely fallback risk |
|---|---|---|---|
| **X-Ray look-through** (holdings → sector/geo/factor exposure) | Fund holdings, ETF composition, security master | Solid for equities & ETFs; **gap risk on international fund holdings** | Medium |
| **Event Calendar** (earnings, dividends, splits, corporate actions) | Calendar endpoints per ticker | Solid — this is core fmp territory | Low |
| **Smart-Money overlay** (institutional flow, 13F, insider tx) | 13F filings, insider transactions | Solid for US; **gap risk on non-US institutional data** | Medium |
| **Risk & Attribution** (vol, beta, factor exposure, PnL attribution) | Price history, factor time series, benchmark returns | Solid for price history; **factor time series may need synthesis** | Medium-High |
| **What-If** (hypothetical portfolio ops on cached snapshots) | Everything the base portfolio uses (no new data) | Reuses X-Ray + Risk cache | Low |
| **Paper Trading** (order sim, fill sim, position accounting) | Real-time-ish quotes, corporate actions | `fmp_cached` for reference data; **live quote latency may push toward raw `fmp` for fills** | Medium |
| **Alerts** (threshold triggers on price / event / risk metric) | Streaming quotes or polled quotes | **Almost certainly needs raw `fmp` polling — file gap issue for cached streaming** | High |
| **Backtest hand-off** (feed portfolio state to backtester) | Historical prices + splits/dividends adjusted | Solid | Low |

**Nadia's read:** most phases stay in `fmp_cached`. Concentrated fallback risk is in **Alerts** (real-time-ish polling) and **Paper Trading** (fill semantics need fresh quotes). Those two workstreams file `area:fmp-cached-gap` issues *up-front* in their planning phase rather than at code time — so the gap becomes visible before implementation and the `fmp_cached` team can pipeline the work.

**Preflight action** (added to Stage 3 roadmap): before M1 kicks off, Kai + Rohan do a 30-minute audit against `providers/fmp_cached/` to catalog which endpoints exist. Any anticipated M1–M2 endpoint not present becomes a filed `area:fmp-cached-gap` issue *before* the workstream that needs it starts. Prevents surprise fallbacks mid-sprint and gives the `fmp_cached` team early lead time. **We do not wait on those issues** — implementation proceeds on the fallback path.

---

## Locked decisions

1. **Repo of record:** `prajoria/OpenBB`. Every open issue must be attached to Project #4; if any orphans surface, they get added.
2. **Team (all AI agents, random names, roles fixed):**
   - **PM (project manager, milestone ownership, roadmap authoring):** *Nadia*
   - **Dev-A (backend / data / router):** *Kai*
   - **Dev-B (widgets / frontend / UX):** *Priya*
   - **Dev-C (platform / infra / migrations):** *Rohan*
   - **QA lead (in-team, gates every PR before merge into `portfolio`):** *Mira*
   - **PR reviewer (out-of-team, adversarial, critical review of everything):** *Zev*
3. **Milestone cadence:** Nadia proposes it in Stage 3 after the surviving-issue dependency graph is known. No pre-committed 2-week rhythm — cadence follows the shape of the work.
4. **Docs location:** `docs/superpowers/audits/` and `docs/superpowers/plans/`.
5. **Bulk-close permission:** granted for issues explicitly shipped via a merged PR on `portfolio`. Every close still gets a linking-comment audit trail. Anything ambiguous → "needs your call" list.

---

## Stage 1 — Baseline (COMPLETE)

Read-only inventory. Ran end-to-end; artifacts written to `.dev-cycle/`.

### Data captured

| Artifact | Content |
|---|---|
| `.dev-cycle/project4-snapshot-2026-07-16.json` | Full `gh project item-list` dump — 90 items |
| `.dev-cycle/prs-base-portfolio-2026-07-16.json` | All PRs targeting `portfolio` — 8 |
| `.dev-cycle/prs-head-pi-2026-07-16.json` | All PRs from `feat/pi-*` head branches — 6 |
| `.dev-cycle/portfolio-log-2026-07-16.tsv` | Full `git log origin/portfolio` since 2026-01-01 |
| `.dev-cycle/stage1-derived-2026-07-16.json` | Cross-referenced summary (shipped-via-PR map, shipped-via-commit map, orphans, migration-map coverage) |

### Findings

| Metric | Value |
|---|---|
| Project #4 total items | 90 (all Issues, all in `prajoria/OpenBB`) |
| Status = `Todo` | 87 |
| Status = `Done` | 3 (only #501, #502, #503 — M0 repo-bugs) |
| PRs targeting `portfolio` | 8 (7 merged, 1 open — `#762 chore/absorb-develop-into-portfolio`) |
| PRs from `feat/pi-*` branches | 6, all merged |
| Merged PRs with `Closes #NN` referencing a Project #4 issue | **0** |
| bd → gh migration map entries (`scripts/pi_bead_to_gh_map.json`) | 87 → 87 unique GH issues |
| bd-map ↔ Project #4 coverage | Perfect (all 87 mapped issues are on the project) |

### The critical finding — tracker sync broke at the bd retirement

Every shipped `feat/pi-*` PR cites the retired bd-id (`OpenBBTechnical-qy83.1.N`) in its body, **not** the GH issue number. GitHub can't auto-close on unrecognized identifiers, so:

- Work landed on `portfolio` (PRs #466, #467, #468, #471, #473, #474, #487 all merged).
- The GH issues that those PRs actually finished stayed `Todo` on Project #4.
- The `pi_bead_to_gh_map.json` file (already in the tree) is the retroactive bridge.

**Implication for Stage 2:** the task changed from "spawn parallel subagents to classify 90 items" (my original plan) into a **mechanical join over a small map**. Much cheaper.

### Bd-mapping for the 5 shipped `feat/pi-*` PRs

Extracted from PR bodies + `pi_bead_to_gh_map.json`:

| PR | Branch | bd-id in body | Maps to GH issue |
|---|---|---|---|
| #466 | `feat/pi-router/scaffold` | `bd-qy83.1.4` | (to be confirmed by lookup in Stage 2A) |
| #467 | `feat/pi-app/paper-migration` | `bd-qy83.1.5` | (lookup) |
| #468 | `feat/pi-widgets/playwright-harness` | `bd-qy83.1.7` | (lookup) |
| #471 | `feat/pi-ops/pr-template-ci-guard` | `bd-qy83.1.2` | (lookup) |
| #473 | `feat/pi-qa/isolation-spec` | `bd-qy83.1.8` | (lookup) |
| #474 | `feat/pi-env/venv-smoke` | `bd-qy83.1.9` | (lookup) |
| #487 | `fix/cache-schema-order-on-portfolio` | (fix PR — likely maps to one of #501–#503, already Done) | — |

Stage 2A will produce the exact GH issue numbers.

### Epic body reveals the M4 promotion anchor

The epic (#491) body says verbatim:
> *"All work merges to portfolio; single merge to develop only at M4."*

That confirms and formalizes the workflow rule we added to CLAUDE.md. **M4 is the canonical promotion milestone.** Nadia uses this as the anchoring point for milestone planning.

---

## Stage 2 — Dedup / stale-issue hunt (REVISED after Stage 1)

Original plan was fan-out subagent classification of 90 items. Stage 1 showed the real task is a small deterministic join.

### Stage 2A — Mechanical join (~5 min, no subagents)

For each of the 5 merged `feat/pi-*` PRs:

1. Extract the `bd-qy83.1.N` reference from the PR body.
2. Look up the mapped GH issue in `scripts/pi_bead_to_gh_map.json`.
3. Mark that GH issue as *shipped-in-PR-#NNN*.
4. Same for PR #487 (parse commit message).

**Expected output:** ~5–8 issues move from `Todo` → `Done`. (Not the ~30+ I originally estimated.)

### Stage 2B — Non-project refs check (~15 min)

The commit log has `Closes #21/#23/#93/#763/#774/#775/#776/#782/#783/#793/#804/#805/#806/#807` and `Fixes #739`. None of these are in Project #4 (they were absorbed from `develop`). Noted in the audit doc, not our concern here.

Also confirm: bd-map has 87 entries; project has 90 items. The 3 extras are `#501/#502/#503` (Done). **No orphans.** ✓

### Stage 2C — Missing-`Closes` audit (~5 min)

Grep every PR body for bare `#\d{3}` references and cross-check against Project #4 item numbers. Almost certainly zero hits, but confirms tracker-sync claim rigorously.

### Stage 2D — Close-with-comment (~10 min, needs user only for ambiguous rows)

Under the granted bulk-close permission, close each identified shipped-but-open issue with:

```
Shipped via #<PR-number> (branch: feat/pi-.../…) — originally referenced by the
retired bd-id `OpenBBTechnical-qy83.1.N`. Closing as `Done` on Project #4.
```

Also append a single entry to `docs/MEMORIES.md` documenting the retroactive close pass so a future session sees the audit trail.

**Confirmation needed before Stage 2D fires:**
1. Bulk-close comment wording (template above) — ok, or reword?
2. Audit doc location: `docs/superpowers/audits/2026-07-16-project4-baseline-and-dedup.md` — ok?

---

## Stage 3 — Roadmap synthesis (PENDING Stage 2)

Nadia authors `docs/superpowers/plans/2026-07-16-portfolio-intel-roadmap.md`.

Structure:

- **Executive summary** — where we are (M0 essentially complete after Stage 2 closes), where we're going (M4 = the single portfolio→develop promotion gated on Daisy's sign-off).
- **Milestone anchors:** M1 → M2 → M3 → M4, each with acceptance criteria drawn from the epic body's product surfaces:
  - X-Ray look-through
  - Event Calendar
  - Smart-Money overlay
  - Risk & Attribution
  - What-If
  - Paper Trading
  - Alerts
  - Backtest hand-off
- **Workstream ownership:**
  - **Kai** — backend / data / router extensions under `openbb_platform/extensions/portfolio_intel/`
  - **Priya** — widgets / frontend / UX under `portfolio_app/`
  - **Rohan** — platform / infra / migrations, `openbb_platform/providers/`, dev-env, CI
  - **Mira** (QA) — cross-cutting; owns `Analysis/tests/`, `portfolio_app/tests/e2e/`, isolation spec unskip; PR gate before merge into `portfolio`
  - **Zev** (external reviewer) — invoked on every PR after Mira's pass; adversarial verify with veto on merge to `portfolio`
- **Cadence proposal** — derived from the dependency graph of surviving issues, not a fixed calendar.
- **Concurrency map** — literal owner × branch × milestone matrix. Constraint: two owners cannot hold concurrent branches touching the same subsystem, to keep merges into `portfolio` conflict-free.
- **Risks + open questions** for Daisy to resolve before M1 starts.

### Team-flow diagram

```
                 ┌── Kai (backend)     ─┐
Nadia (PM) ──▶   ├── Priya (widgets)   ─┼──▶ Mira (QA gate) ──▶ Zev (external review) ──▶ portfolio
                 └── Rohan (platform)  ─┘
                        │
                        └── each opens PR against `portfolio` (never `develop`)

M4 sign-off from Daisy ──▶ single portfolio → develop promotion PR
```

### Nadia's cadence heuristics (candidate, to refine post-Stage 2)

- **M1** — foundational (router sub-modules + first widget contract end-to-end). Success = one product surface fully vertical.
- **M2** — breadth (remaining 3-4 product surfaces at MVP fidelity). Success = every surface has *something* running.
- **M3** — depth (paper trading, alerts, cross-account isolation unskip, real data). Success = SEV-1 acceptance criteria green.
- **M4** — promotion candidate (perf, docs, adversarial pass by Zev, verify against upstream develop). Success = Daisy signs off → `portfolio → develop` PR opens.

Not sized in weeks. Nadia will estimate once the concrete issue list is known.

---

## Stage 4 — User review + issue tidy-up (~20 min, requires Daisy)

1. Walk Daisy through the audit + roadmap docs.
2. On approval:
   - Bulk-close classified duplicates/stale/shipped issues (Stage 2D).
   - Add any *newly-identified* work as fresh GH issues attached to Project #4 (with bulk-create sign-off since >3 in one action).
   - Ensure every surviving open issue has `Status`, `Milestone` (M1/M2/M3/M4), and `Workstream` label set.
3. Nadia converts the roadmap into concrete issue-level ordering (M1 issue queue for the first sprint).

---

## What this plan will NOT do

- Not close any issue without an explicit shipped-PR link (bulk permission is scoped to "clearly closed by merged PR").
- Not open new PRs. This entire pass is planning + tracker hygiene.
- Not propose a `portfolio → develop` promotion — that stays gated on Daisy's loud sign-off at M4.
- Not spin up `codebase-memory-mcp` graph analysis unless Stage 2 surfaces "issue is half-done in code but marked open" cases (Stage 2.5 escalation).

---

## Anticipated timeline (session-scale, not calendar)

| Stage | Duration | Blocks on |
|---|---|---|
| 1. Baseline | 15 min | — (DONE) |
| 2A. Mechanical join | 5 min | — |
| 2B. Non-project refs | 15 min | — |
| 2C. Missing-Closes audit | 5 min | — |
| 2D. Close-with-comment | 10 min | User confirms wording + audit doc location |
| 3. Roadmap synthesis (Nadia) | 30 min | Stage 2 complete |
| 4. User review + tidy-up | 20 min | User walkthrough |
| **Total to end of Stage 4** | **~100 min** | Two user check-ins (Stage 2D wording, Stage 4 approval) |

---

## Open questions for Daisy (blocking Stage 2D → Stage 3)

1. **Bulk-close comment wording** — template above OK, or reword?
2. **Audit doc location** — `docs/superpowers/audits/2026-07-16-project4-baseline-and-dedup.md` OK?
3. **Zev's veto scope** — does the external reviewer's veto block merge into `portfolio` outright, or block only when severity ≥ HIGH? (Default: block outright unless Daisy overrides on that PR.)
4. **Nadia's cadence estimate** — do you want week-level dates on M1–M4, or session-count estimates (this is an AI-agent team; wall-clock is not the natural unit)?
