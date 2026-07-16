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
