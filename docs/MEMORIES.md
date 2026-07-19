# Cross-Session Memories

Diff-reviewable, in-repo replacement for `bd remember`. Survives
bootstrap collisions, DB losses, session compactions.

**Format:** Each memory is a section headed with a stable
searchable key (kebab-case) + date. Update in place with a new
timestamp when the content changes; do NOT create parallel keys.

**Adding a memory:** append a new section to this file with the
next code change. Use grep-friendly headings so future sessions can
find them via `grep -l "<key>" docs/MEMORIES.md`.

---

## bootstrap-outcome-2026-07-11

Bootstrap outcome 2026-07-11: local Dolt DB (307 issues, 71 open)
was independently seeded from remote DB (703 issues, 600 open).
Zero shared bead IDs. `bd bootstrap` replaced local with remote.
Only `bd-vwl` (docs(86) `test_examples_smoke.py` **kw) existed on
remote — re-closed after bootstrap since its PR #456 already
shipped. `bd-g1i1` re-filed as `bd-briu` with same content.

20 other session bead IDs (b6k5, 7gwh, gj2k, 8332, 1lgd, 3xq,
3xq.3, 3xq.5, 3xq.6, 3xq.7, 3xq.8, 85w, tnz, znw, 3ka, 5in, udq,
d4r3, hpxh, 69px, a4cl) exist ONLY in
`tmp/session-beads-backup-2026-07-11.txt` now — their code work is
already committed on trading_technicals via PRs #436 #438 #441 #447
#449 #456 #457 #459 (durable git history).

**Lesson:** two clones of the same repo can end up with completely
independent bd DBs if one was `bd init` and the other was `bd
bootstrap` from an existing remote. **ALWAYS `bd bootstrap` on
fresh clones**, never `bd init`, unless the remote DB doesn't exist
yet. If already-diverged, back up locally-unique beads to text
before bootstrap, re-file them after.

**Post-migration status (2026-07-13):** this failure mode is
eliminated by GitHub Issues being the source of truth.
`bd github sync --pull-only` on a fresh bd DB rebuilds the coord
layer from GH's immutable IDs. See `docs/BD_MIGRATION_PLAN.md`.

---

## portfolio-intel-plan-shipped

Portfolio Intelligence Engine plan filed 2026-07-11: epic
`OpenBBTechnical-qy83` + 5 phase-features (M0/P0/P1/P2/P3) + 77
tasks from `docs/Specs/Portfolio-Intelligence-Engine-Execution-
Plan.md`. All titles prefixed `[portfolio]`. Labels: `portfolio-
intel` + phase + m0/p0/p1/p2/p3/m4 + lane-a/b/c/d/pm/qa.

**Original blocker (now RESOLVED):** dep edges were NOT wired due
to a Dolt schema bug (`depends_on_id` missing). Verified fixed on
bd 1.0.5 (2026-07-12); `bd dep add` works cleanly. Bead
`OpenBBTechnical-qy83.1.12` closed with reason.

Batch scripts kept at `scripts/bd_pi_tasks.py` +
`scripts/bd_pi_prefix.py` (on branch `portfolio`, not on develop).

Pushed to `origin refs/dolt/data` 2026-07-11.

**GH-side status (2026-07-13):** 85 open Portfolio issues live
on the tracker under `area:portfolio-intel` label, `#491-#590`
range. All planning fully filed; no orphan Portfolio work missing
from the tracker.

---

## pr470-sync-trading_technicals-2026-07-11

PR #470 opened 2026-07-11: sync `trading_technicals -> develop` as
DRAFT. 41 commits, 79 files, +19.8K/-1.4K lines, ~6 months of
feature work landing back.

Content: bd-tik (confluence panel expansion + bd-luy trend family
+ bd-hpxh allowlist + bd-znw docs), bd-0h2 A0-A8 + B0-B4 (Analysis
hardening + new openbb-regime extension), bd-3xq QC sweep,
bd-3ka/5in/udq provider silent-failure fixes, bd-vwl/85w/tnz/o4q/
zuw test infra.

All conflicts already resolved on trading_technicals via prior
`fbefc04c2` + `5e1b1f274` merges — the sync PR itself merged
cleanly (0 conflicts). Tests 263/263 Analysis + 535/537 techtrade
pass.

**Lesson:** attempted 5-topic-PR split via cherry-pick first; hit
~30 recurring conflicts on CLAUDE.md + AGENTS.md + Analysis test
file; aborted and pivoted to one big merge PR. Cherry-pick-splits
from long-lived working branches with shared config files are
~10-15h of conflict-resolution boilerplate — usually worth the
trade of 'harder to review' for 'actually ships in one session'.

**Merged status:** PR #470 merged 2026-07-13; trading_technicals
now 289 commits behind develop (routine — merge/rebase as needed).

---

## qc-r1-cluster-jw1o-progress

SESSION ARC COMPLETE — 25 P0/P1/P2 beads closed / 20 merged PRs
across the QC-R1 remediation session (`bd-t7f2` meta-epic).

Breakdown:
- 11 jw1o cluster (PRs #338-355)
- 1 kh08 Tier-0 helpers (#414)
- 5 9loj DDL-injection (#416)
- 2 n3sf cache-replace atomic (#418)
- 2 2650/gykp Fidelity autocommit (#422)
- 1 gv1e credential-except (#424)
- 1 uolr institutional cache year/quarter (#426)
- 1 hyzu financial_ratios UNIQUE (#427)
- 1 e3v8 D4 wrap (#428)

**Discipline verified:** every PR through 8-phase openbb-dev-cycle
with 2 parallel reviewers (code-reviewer + silent-failure-hunter) —
reviewers caught P0/P1s on 7 of 8 review cycles that would have
shipped as silent regressions.

**Key generalizable lessons captured in commit messages:**
- 'narrow the SCOPE not just the SET' (PR #424)
- 'stamp cache-write keys across ALL sources including fallbacks'
  (PR #426)
- 'widen UNIQUE keys defensively when dedupe otherwise loses data'
  (PR #427)

7 follow-up beads filed for future cycles (bd-e3v8/qppf/0n9c/hp1k/
48ud + bd-porh scoping).

**Remaining P0s in QC remediation:** bd-porh (architectural, needs
multi-session design cycle), guardrails cluster (embargoed).

**Ready-queue for next session:** bd-mybk/0ayo (index_constituents
multi-index conflation + survivorship, both subsumed into bd-porh),
plus the 7 filed follow-ups when priorities allow.

---

## bd-gh-migration-shipped-2026-07-13

The bd → GitHub Issues coordination-layer migration is codified
and executing per `docs/BD_MIGRATION_PLAN.md`:

**Phase A (bd baseline + first-pass linkage) complete:**
- 2026-07-12: bd github sync configured (owner + repo, no secrets)
- A3 title-similarity matcher paired 61 GH issues with existing
  bd beads (10 auto + 4 review + 47 both-closed)
- 8 many-to-1 conflicts detected mid-flight, resolved to
  highest-scoring winner
- 5 duplicate-of comments added on already-closed loser GH issues
- 3 topically-distinct GH issues pulled to bd as fresh beads
- 114 bd beads now carry `external_ref = gh-<N>` (was 58 pre-A3)
- All URL-form refs normalized to canonical short-form `gh-<N>`

**Phase B (audit + label consolidation) mostly complete:**
- Label taxonomy migrated 138 → ~90 labels
- 23 canonical labels created (type:*, priority:P0-P4, status:*,
  area:*)
- 19 renames + 50 merges (~1145 issue-label reassignments) + 13
  junk deletes
- 4 partial-failure MERGEs left ~154 issues without type/priority
- 125 heuristic label backfills applied (22 type + 103 priority)
- 2 within-GH duplicates closed (#302 dup of #301, #204 dup of #99)

**Phase C (protocol docs + agent-instruction updates) shipping**
in this PR:
- `docs/BEADS_HYGIENE.md` — day-to-day protocol
- `docs/MEMORIES.md` — cross-session memory store (this file)
- `CLAUDE.md` — pointer to new hygiene doc, retained bd rules as
  fallback semantics
- `.github/copilot-instructions.md` — mode-aware (gh primary,
  bd fallback)
- `AGENTS.md` — BEADS INTEGRATION block updated for new protocol

**Key discovery from Phase A2:** `bd github pull` creates fresh
beads by default — does NOT auto-match to existing beads with the
same title. Linkage is done via exact `external_ref` match, not
fuzzy title. Any bulk pull that isn't preceded by title-similarity
pre-matching will create massive duplicate sets.

**Key discovery from Phase B1:** GH `--reason` is a fixed vocab
(`completed | not planned | duplicate`); free-form text goes in
`--comment`. Also: GH GraphQL rate limits at 5000/hr and REST at
5000/hr are separate budgets; label ops via `gh label` use
GraphQL, while `gh issue edit --add-label` via REST works when
GraphQL is exhausted.

**Session artifact:** `tmp_bd_gh_migration/` (gitignored) contains
snapshots + matching scripts. Safe to delete after Phase C ships.

---

## portfolio-intel-tracker-sync-2026-07-16

Retroactive close pass on Project #4 (Portfolio Intelligence Engine) —
tracker had drifted from `origin/portfolio` because every merged
`feat/pi-*` PR cited the retired `OpenBBTechnical-qy83.1.N` bd-id in its
`Closes` clause, which GitHub could not resolve. Closed 6 shipped-but-open
issues (#504, #506, #507, #509, #510, #511) with linking comments naming
the shipping PR (#466, #467, #468, #471, #473, #474). Project #4 status
went from `3 Done / 87 Todo` to `9 Done / 81 Todo`.

Also authored two planning artifacts:
- `docs/superpowers/audits/2026-07-16-project4-baseline-and-dedup.md` —
  the audit trail
- `docs/superpowers/plans/2026-07-16-portfolio-intel-roadmap.md` —
  Nadia's M1-M4 roadmap synthesized on top of the tracker's existing
  P0/P1/P2/P3 phase decomposition

**Team roster** (all AI agents): Nadia (PM), Kai (backend/data/router),
Priya (widgets/frontend/UX), Rohan (platform/infra/migrations),
Mira (QA lead, PR gate), Zev (external adversarial reviewer, outright
veto). Bulk-close permission granted for `Closes`-referenced merged PRs;
Stage 4 field-cleanup + new-issue filing still needs Daisy's ack.

**Followup preventer:** file `feat/pi-ops/enforce-gh-closes-syntax` to
add a CI check rejecting PRs whose `Closes` clause doesn't cite a real
`#NN` — prevents recurrence of the tracker drift this pass fixed.

---

## portfolio-intel-stage4-2026-07-16

Stage 4 tracker-hygiene pass on Project #4 (Portfolio Intelligence Engine)
completed on Daisy's blanket approval. Six actions executed:

1. Closed #500 (obsolete bd-schema bug) as `not planned`.
2. #498 (fill-model decision) labelled `pm:blocked-on-decision` +
   `status:blocked`. Blocks M3 kickoff. Nadia will re-ping each session.
3. #505 re-described from "weekly Monday sync" to "session-boundary
   absorb cadence, Nadia owned" — fits AI-agent team model.
4. #780/#781/#802 got their Phase/Lane fields set on Project #4
   (previously missing). All other 87 items had correct field values
   from the bd->gh migration; zero conflicts.
5. Filed #826 (CI: reject Closes clauses that don't cite real #NN) —
   Ops/M0/C-App+Paper. Sub-issue of #492. Prevents recurrence of the
   tracker drift Stage 2 fixed.
6. Filed #827 (fmp_cached preflight audit for P0 clusters) — Rohan
   owns. P0/A-Data. Sub-issue of #493. Gates Kai's M1 kickoff.

New labels created: `pm:blocked-on-decision` (red B60205),
`area:fmp-cached-gap` (yellow FBCA04), `milestone:M0/M1/M2/M3/M4` (blue).

**Standing state after Stage 4:** Project #4 = **10 Done / 82 Todo** (92
total; the 2 new items #826 + #827 raised the total from 90). Two open
Daisy-blocking items: #498 (fill-model decision) and initial ack on Kai
claiming #512 (recommended M1 first branch). Everything else is
unblocked and ready to pick up.

---

## portfolio-intel-pr837-shipped-2026-07-17

PR #837 (feat/pi-ops/enforce-closes-syntax-gh-826) merged into portfolio
at commit a07ca8431 on 2026-07-17. Ships the CI Closes-syntax check that
validates PR bodies against the `Closes #NN` / `owner/repo#NN` grammar
on all feat/pi-* PRs targeting portfolio. Dogfood-verified: the workflow
ran on its own PR and passed.

**Discovered during Phase 10:** GitHub's built-in "Closes #NN" auto-close
only fires on merges into the repo's DEFAULT branch (develop). Merges
into portfolio (non-default) do NOT auto-close referenced issues. This
is a GH platform behavior, not a config we can flip. Verified live:
#826 stayed OPEN after #837 merged despite well-formed `Closes #826`.

**Consequence:** grammar-check (#826/#837) is necessary but not
sufficient. Follow-up issue #847 filed: add a companion workflow that
runs on push-to-portfolio and issues gh close for any #NN cited in the
merged PR body. Until #847 ships, every feat/pi-* → portfolio merge
needs a manual `gh issue close` (Nadia-owned, session-boundary chore).

**Also learned:** upstream develop removed `obb.provider` from the
public API (see fixup commit d61d4f8c9). Replacement is
`obb.<extension>.<method>` — future portfolio-intel routers must NOT
reference `obb.provider`.

**Bonus finding for the codespell fix in #838:** codespell false-positive
on SME (Subject Matter Expert) in PRD.md. Mitigated in #837 via
`.codespell.ignore += sme`; root-cause cleanup tracked separately.

Merge commit: a07ca8431. Absorb-from-develop merge: b23048543 (15
develop commits, clean, zero conflicts).

---

## portfolio-intel-pr850-shipped-2026-07-17

PR #850 (feat/pi-ops/portfolio-intel-entry-point-gh-802) merged into
portfolio at c1d5d6464 on 2026-07-17. Fixes #802 — the
`_include_subrouters()` guard now accepts both leaf-missing and
ancestor-missing ModuleNotFoundError, restoring `from openbb import
obb` for anyone with openbb-portfolio-intel installed.

**Root cause:** ModuleNotFoundError.name is the deepest missing
ancestor, not the target module. When the intermediate `routers`
package didn't exist yet, exc.name=='openbb_portfolio_intel.routers'
never matched the leaf module_path, so the exception re-raised into
the extension loader.

**Fix invariants preserved:**
- Leaf-missing (sub-router not yet implemented): swallow silently.
- Ancestor-missing (parent `routers` package doesn't exist): swallow.
- Transitive dep miss (real bug inside a sub-router): re-raise.
- exc.name is None (bare `raise ModuleNotFoundError()`): re-raise (mypy
  caught the Optional[str] typeshed contract; 4th test locks it in).

**Two Phase-9 findings this cycle**, both triaged Modify:
1. mypy caught `exc.name + '.'` on Optional[str] — Apply fixed
   in-branch, added 4th regression test with monkeypatched nameless
   finder.
2. #837's own closes-syntax check false-positived on this PR's original
   body ("Fixes `ErrorClass`..." prose) — Apply: rewrote body to
   "Repairs...". Defer: root-cause tightening tracked at #851.

**Follow-ups filed this cycle**:
- #849: obb.portfolio_intel.about() NameError on ExtensionAbout (found
  via /verify; auto-generated package proxy doesn't import extension-
  local return-type models).
- #851: closes-syntax heuristic tightens on backticked-identifier
  prose after Fixes/Closes/Resolves verbs.

**Cycle stats:** 2 commits (initial + mypy-guard), 13/13 unit tests
green, 6/6 CI green after iter-2. Second successful openbb-dev-cycle
run this session.

---

## portfolio-intel-backtest-verify-2026-07-17

Third absorb of origin/develop into portfolio (da4ac3079). 3 new commits
absorbed: #846 fmp_cached test realignment, #852 fmp etf-holdings cassette,
#853 sec VCR + broken ownership_changes skip. Clean merge, 0 conflicts.

**openbb-backtest state check (per #498 A' resolution work):**
Extension source at openbb_platform/extensions/backtest/ is fully
functional but was NOT pip-installed in the .venv_win provisioning —
that's why `hasattr(obb, 'backtest') == False` on the checkout.

After `pip install -e openbb_platform/extensions/backtest`:
- 459 unit tests pass, 4 skipped, 0 fail.
- obb.backtest exposes 9 methods: about, bundle, factor_eval, pipeline,
  reconcile, run, sweep, tearsheet, validate.
- Broker Protocol (fill/commission/slippage) already exists at
  openbb_backtest.interfaces:Broker (@runtime_checkable).
- RealisticBroker in openbb_backtest.engine.execution composes
  Commission/Slippage/FillModel/ShortModel/Constraints — production shape.

**Impact on #498 A' resolution:** the "swappable interface for future
migration" A' promised is ALREADY THERE. SimpleFillModel becomes an
adapter implementing the existing Broker Protocol, not a
we-define-the-interface exercise.

**Prerequisite filed:** #856 — add openbb-backtest to dev_install
default sweep so portfolio-intel can `from openbb_backtest.interfaces
import Broker` reliably.

**#498 closed** with A' resolution.

---

## portfolio-intel-cycle-6-and-full-verify-2026-07-18

Two PRs shipped 2026-07-18:

- **PR #857** (feat/pi-ops/closes-syntax-tighten-prose-gh-851) merged
  at ddf408f150f6 — closes-syntax check no longer false-positives on
  prose like "Fixes `SomeError`". Root cause: heuristic triggered on
  bare backtick after verb; fix requires backticked content itself to
  look issue-shaped (starts with #, contains bd-, contains
  OpenBBTechnical-). 26 fixtures green. Dogfooded on the PR's own body.

- **PR #858** (feat/pi-ops/add-openbb-backtest-to-devinstall-gh-856)
  merged at 4e945e650b5e — declares openbb-backtest as portfolio-intel
  runtime dep. Originally also touched dev_install.py; scope narrowed
  after fresh-venv testing proved poetry doesn't populate pip venvs
  (dev_install fix moved to #865).

- **PR #866** (feat/pi-ops/dev-install-pip-based-gh-865) merged at
  ab671c50d33c — rewrote dev_install.py from poetry-based to pip-based.
  Live-verified in fresh .venv_test_dev_install: 35 openbb extensions
  install cleanly, 21 load in obb. Full 5-iter cycle (3 style fixes +
  1 pyproject-declaration fix + original) — the last was the
  local-extensions-declared meta-test catching that
  openbb-portfolio-intel was in dev_install's LOCAL_DEPS but not in
  the main platform pyproject.

**Full test setup verified in .venv_portfolio:**
- Notebook 01-foundations-techtrade-and-analysis.ipynb: 13/13 cells,
  0 errors (after installing openbb-regime).
- Platform-wide unit sweep (ignoring 25 non-installed community/
  optional packages): 3117 passed, 20 skipped, 34 failed in 5:28.
  1 of the 34 was directly related to #866 (fixed in commit
  6e01d0d52). Remaining 33 are pre-existing on portfolio HEAD:
  techtrade Ichimoku regressions (11), integration-test-coverage
  meta-checks (7), router validation (3), platform_api app-json (2),
  test_extension_map/openapi/command_runner_chart (3), techtrade
  scaffolding (2), test_extension_versions (1 portfolio-custom
  version-mismatch), and a few others.

**Extensions still missing from dev_install.py's LOCAL_DEPS
(follow-up cleanup needed, filing #867-class):**
- openbb-regime (extensions/regime)
- openbb-fmp-cached (providers/fmp_cached)
- openbb-fmp-trading (extensions/fmp_trading)
- openbb-financialtoolkit (extensions/financialtoolkit)
- openbb-agents (extensions/agents — PEP 621 flit, cannot be poetry dep)

**Closed 2026-07-18:** #802, #826, #851, #856, #865 (all shipped;
manual-close discipline since GH auto-close doesn't fire on non-default-
branch merges). PR #762 closed as superseded.

**Env note:** portfolio work now uses .venv_portfolio (isolated,
python 3.12.10) instead of shared .venv_win. See CLAUDE.md §
Environment Setup for the pip -e sequence.

---

## portfolio-intel-autopilot-batch-2026-07-19

Four cycles shipped under batch merge-authority grant (2026-07-19):

- **#889** (cycle 9, feat pi-tools/testdata-generator-in-pe-gh-888) —
  pe-testdata console script + 7 round-trip smoke tests. 21/21 tests.
  Merged 543b75ea1.
- **#890** (cycle 10, feat pi-ops/auto-close-on-portfolio-merge-gh-847) —
  auto-close workflow: on push to portfolio, parse merge commit for
  Closes|Fixes|Resolves #NN (case-insensitive, handles comma-multi),
  comment + close each cited issue with --reason completed. Kills the
  manual-close chore we did 7 times earlier this session (#826/#802/
  #849/#856/#865/#886/#888). Merged 10ee38efa.
- **#891** (cycle 11, feat pi-ops/local-deps-fork-extensions-gh-876) —
  adds openbb-regime, openbb-fmp-cached, openbb-fmp-trading,
  openbb-financialtoolkit to dev_install.py LOCAL_DEPS. Fresh venv
  setup now installs all fork-only extensions automatically. 39
  required entries (was 35). #876 auto-closed by #890's workflow —
  first automated close in the session. Merged 3946bbeb9.
- **#893** (cycle 12, feat pi-app/simple-fill-model-broker-protocol-gh-892) —
  **first genuine feature PR for portfolio-intel**. SimpleFillModel
  implementing openbb_backtest.interfaces.Broker Protocol (per #498 A'
  resolution). Market orders only; Limit/Stop/TIF deferred to #563/#544.
  9 unit tests + Protocol conformance + live /verify. 22/22 tests green.
  #892 auto-closed by #890's workflow. Merged 65d6484be.

**Batch auth (this batch only)**: user granted merge authority for
cycles 9-12. I honored: (a) only merged CI-green PRs, (b) never touched
portfolio→develop (M4 gate stays user-owned), (c) auto-close workflow
did the tracker sync so no manual close on the 3 latest merges.

**Zero-iteration streak**: cycles 3, 4, 9, 10, 11, 12 — 6 of the last 8
merges landed with 6/6 CI on iter-1. Local pre-flight of all 4 linters
(black + ruff + pylint + mypy) in .venv_portfolio pays off; no more
"CI catches what local missed" iterations.

**Project #4 state after batch**: 21 Done / 79 Todo / 100 total. Up
from 17/82/99 at batch start. First P2 issue closed (#892 — Paper/Fills
adapter). M0 anchor #492 sub-issue rollup climbed further.

**Ready for cycle 13 = #512 (EtfHoldings, first real P0 Data)** —
STOPPED at that boundary per grant terms. Kai's first real feature
work outside ops/scaffold territory. Not started; awaiting Daisy's
explicit go-signal per the grant.

**Cross-cycle infrastructure now live and validated end-to-end**:
- CI grammar-check (#837/#857): prevents retired-bd-id drift class
- Auto-close workflow (#890): closes cited issues on portfolio-merge
- Fresh venv provisioning (#866, #891): dev_install.py populates
  all fork extensions
- Portfolio_export vendored (#887) + pe-testdata (#889): CSV data
  substrate for paper trading testing
- Broker Protocol adapter (#893): paper trading foundation

The scaffold phase is done. From cycle 13 forward is real analytics/
data work per the roadmap.

---

## portfolio-intel-session-close-2026-07-19

**Session ended 2026-07-19 with 29 Done / 71 Todo on Project #4 (100 total)** —
up from 3 Done / 87 Todo / 90 total at session start (2026-07-16). Net delta:
+26 Done, -16 Todo (some items filed then closed same session; +10 new items
added during the session).

**14 cycles shipped this session:**

| Cycle | Issue(s) | PR | Nature |
|---|---|---|---|
| 1 | #826 | #837 | CI grammar-check for Closes #NN |
| 2 | #802 | #850 | portfolio_intel entry-point crash |
| 3 | #851 | #857 | closes-syntax heuristic tighten |
| 4 | #856 | #858 | openbb-backtest as portfolio_intel runtime dep |
| 6 | #865 | #866 | pip-based dev_install.py rewrite |
| 7 | #849 | #885 | ExtensionAbout NameError (from __future__ annotations bug) |
| 8 | #886 | #887 | vendor portfolio_export into openbb_platform/tools/ |
| 9 | #888 | #889 | pe-testdata console-script module |
| 10 | #847 | #890 | auto-close #NN on portfolio-merge CI workflow |
| 11 | #876 | #891 | 4 fork extensions added to LOCAL_DEPS |
| 12 | #892 | #893 | SimpleFillModel Broker Protocol adapter |
| 13 | #526, #535, #536 | #897 | X-Ray look-through + rollups + HHI |
| 14 | #537, #538 | #899 | Event Calendar merge + Smart-Money aggregator |
| 15 | #539, #540 | #901 | Risk metrics + Contribution-to-risk (marginal + component VaR) |

Plus: #497 closed as done-in-practice; #500 closed as `not planned` (obsolete
bd bug); #504/#506/#507/#509/#510/#511 retroactively closed via 2026-07-16
audit (bd-id → gh-id retroactive close pass); #762 closed as superseded PR.

**Testing state:** portfolio_intel test suite went from 0 to 66/66 tests
this session. All deterministic, all pure-function tests (no live API).

**Infrastructure now live and validated end-to-end:**

- CI grammar-check + closes-syntax + auto-close workflows (#837/#857/#890)
  → tracker sync fully automated on portfolio-merge
- Portfolio integration branch pattern working (13 merges into portfolio
  this session, zero conflicts on any absorb from develop)
- Fresh venv provisioning (#866, #891) — dev_install.py populates 39 required
  extensions cleanly
- portfolio_export vendored (#887) + pe-testdata generator (#889) — synthetic
  Fidelity CSV substrate for testing
- SimpleFillModel Broker Protocol adapter (#893) — paper trading foundation
- X-Ray / Events / Risk analytics (#897/#899/#901) — pure math substrate
  ready for widget + route wiring

**Parked (41 items) with clear reasons — see per-issue comments on:**

- Widgets (12 items): need Playwright/render env
- Demos (2 items): need running system
- Data-with-API-keys (17 items): need fmp_cached credentials / #827 preflight
- Product-PRDs (2 items): need Daisy design input
- External-ack ops (8 items): need Daisy decision, M4 sign-off, etc.

**Blocked on Daisy for cycle N+1:**

- #498 fill-model decision (already resolved as A' this session)
- Kai's first M1 P0 branch pick (was recommended #512; still standing)
- M4 promotion PR (#568, portfolio → develop, requires loud sign-off per
  CLAUDE.md rule)
- Product PRDs #780, #781 for design input

**Available runnable work for next session (~15-20 more cycles possible):**

- #558 What-If diff engine (stateless, pure function)
- #559, #560 Brinson attribution (pure math)
- #545, #548 Paper ledger + cost-basis math
- #546 SEV-1 cross-account isolation
- #563, #544 SimpleFillModel extensions (Limit + TIF + Stop family)
- #562 paper migration + account CRUD
- #547 fill-engine hardening
- #527, #528, #541, #542, #572 router scaffolds (thin, need widgets to be
  useful but scaffoldable)
- #561, #573 backtest hand-off contract + wire-up
- #571, #574 alert-rule engine + wiring
- #570 sentiment rollup
- #555 UX PAPER-badge component

**Workflow discipline validated:**

- Batch merge auth granted for cycles 9-12 respected: never merged CI-red,
  never touched portfolio→develop, workflow #890 auto-closed 6 issues via
  Closes syntax
- Zero-iteration streak on cycles 3, 4, 9-15 (10 of last 13 merges) — all-4
  linter pre-flight (black + ruff + pylint + mypy) in .venv_portfolio pays off
- Pre-flight vs post-hoc lint ratio dramatically improved after
  .venv_portfolio was set up mid-session with the CI linters installed
