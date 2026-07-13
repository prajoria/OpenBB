# Beads → GitHub Issues Migration Plan (Pine work only)

**Target repo:** `prajoria/OpenBB`
**Scope:** All beads matching the pine/pyne/pyne_compiler regex (26 beads).
**Non-scope:** 53 non-pine beads (Analysis pipeline, techtrade, fmp_cached, SEC N-PORT, etc.) — remain in beads.
**Beads DB fate:** left in place; devs simply stop using `bd` for pine work.

## Mapping decisions

| Beads concept | GitHub concept |
|---|---|
| `issue_type=epic` | Milestone (created if missing) + `type:epic` label |
| `issue_type=task` | Issue with `type:task` label |
| `issue_type=bug` | Issue with `bug` label |
| `priority=1` | `p1` label |
| `priority=2` | `p2` label |
| `priority=3` | `p3` label |
| `status=in_progress` | Issue opened + assigned to current owner (if gh handle known) |
| `status=deferred` | Skipped (none in pine set) |
| `depends_on` (blocked-by) | Rendered as `Blocked by #NN` in issue body once target has a gh number |
| `depends_on` (parent-child) | Milestone assignment |
| `bd-<id>` reference | Retained verbatim in body under `## Origin` for traceability |

## Milestone plan

Four pine epics already exist as GitHub issues (#102, #108, #109, #110). Since the answer chose "milestones for epics," I will **create four matching milestones** and assign each phase's tasks to the right one. The epic *issues* stay as they are — the milestone is the new grouping mechanism.

| Milestone (new) | Beads epic | Existing gh issue |
|---|---|---|
| `Pine: Extension Epic (P1)` | `OpenBBTechnical-0e9` | #102 |
| `Pine: Phase 2 — Strategies + cross-TF` | `OpenBBTechnical-0e9.6` | #108 |
| `Pine: Phase 3 — Completeness` | `OpenBBTechnical-0e9.7` | #109 |
| `Pine: Phase 4 — Polish & Launch` | `OpenBBTechnical-0e9.8` | #110 |

Beads whose title doesn't obviously belong to P2/P3/P4 get **no milestone** (e.g. compiler gaps, dev-env issues, hook bugs).

## Label plan

Labels needed (all already exist per `gh label list`):
- `type:epic`, `type:task` (need to add `type:bug`)
- `p1`, `p2`, `p3` — **need to create**
- `pine` — **need to create** (color: `#5319e7`, description: "Pine Script / pyne_compiler / pynecore work")

## The 26 beads to migrate

Legend: **[SKIP]** = already exists as a gh issue, will not re-create.

### Already-migrated epics (skip create, add milestones/labels only)

| Bead | GH | Milestone to add | Labels to add |
|---|---|---|---|
| `0e9`   | #102 | `Pine: Extension Epic (P1)` | `pine`, `type:epic`, `p1` |
| `0e9.6` | #108 | `Pine: Phase 2 — Strategies + cross-TF` | `pine`, `type:epic`, `p1` |
| `0e9.7` | #109 | `Pine: Phase 3 — Completeness` | `pine`, `type:epic`, `p2` |
| `0e9.8` | #110 | `Pine: Phase 4 — Polish & Launch` | `pine`, `type:epic`, `p1` |

### To create (22 new gh issues)

**Phase 2 tasks** → milestone `Pine: Phase 2 — Strategies + cross-TF`:

| Bead | Title | Prio |
|---|---|---|
| `ph0` | #pine-P2.T1b: Tests — 5 conformance_strategy fixture triples | p1 (in_progress) |
| `ypg` | #pine-P2.T4: Tests — 3 request.security curated corpus + 10 misc | p2 |
| `fwp` | #pine-P2.T3: Tests — openbb-backtest integration test (skipif guard) | p2 |
| `rnu` | #pine-P2.T2: Tests — 3 v5 strategy roundtrip fixtures | p2 |
| `nlm` | #pine-P2.W1: Widgets — 3-5 bundled strategy widgets | p2 |
| `06g` | #pine-P2.P3: Platform — /pine/strategies/list new endpoint | p2 |
| `6tc` | #pine-P2.R5b: openbb-backtest bridge — shape adapter | p2 |
| `r1m` | #pine-P2.R5a: openbb-backtest bridge — maybe_export_to_backtest | p2 |
| `c0d` | #pine-P2.R3b: Runtime — SecondarySeriesCache disk storage + TTL | p2 |
| `h59` | #pine-P2.C7: v5 migration shim — strategy.exit positional-vs-keyword | p2 |

**Unphased pine tasks** → no milestone, `pine` label only:

| Bead | Title | Prio |
|---|---|---|
| `78w`  | [E3-adapter] list[OHLCV] → pd.DataFrame conversion at Provider→dispatcher boundary | p1 |
| `iz9i` | [manifest sync] Add strategy.*/request.security to BUILTINS_IMPLEMENTED | p2 |
| `wly`  | Migrate remaining src/pyne_compiler/tests/ imports openbb_pine.* → pyne_compiler.* | p2 |
| `7a8`  | [audit] Retroactively verify CCXTProvider + CapitalComProvider pass conformance suite | p2 |
| `fyi7` | [pyne_compiler gap] Position-history builtins: strategy.opentrades/closedtrades/... | p3 |
| `jxhh` | [pyne_compiler gap] Support plot.style_histogram + additional color constants | p3 |
| `z5zs` | [api] pynecore.core.strategy_stats.calculate_strategy_statistics call | p3 |
| `grww` | [dev-env] Editable install of pyne_compiler points at deleted worktree paths | p3 |
| `1vr`  | bd recall <key> <content> silently overwrites memory | p3 (bug) |
| `gt7`  | Hook: block-protected-branch-push false-positives on --force-with-lease | p3 |
| `qj7`  | Normalize Signature.kwargs vs. h14 trailing-tuple-kwargs | p3 |
| `b29`  | C3: inner-type validation for strategy.* signatures | p3 |

## Issue body template

```
<original beads description, verbatim>

---

## Origin

Migrated from beads `bd-<BEADS-ID>` on 2026-07-12.

- Original priority: p<N>
- Original type: <task|bug|epic>
- Original status: <open|in_progress>

## Dependencies

- Blocked by: #<gh-num> (bd-<id>), #<gh-num> (bd-<id>)
- Parent: #<gh-num> (bd-<id>)

*(Dependency numbers wired in a second pass once all target issues have gh numbers.)*
```

## Execution order

1. **Create labels**: `p1`, `p2`, `p3`, `pine`, `type:bug`.
2. **Create milestones**: the 4 pine milestones above.
3. **Update the 4 existing epic gh issues** (#102, #108, #109, #110): add milestone + labels.
4. **Sample dry-run**: create 3 sample issues (`ph0`, `78w`, `1vr`) — one in_progress+milestoned, one unphased+p1, one bug — for your review. STOP.
5. **After your approval**: create the remaining 19 issues, all with `## Origin` block.
6. **Second pass**: for each newly-created issue, append `## Dependencies` block with resolved gh numbers.
7. **Beads side**: mark each migrated bead `deferred` with a `bd remember` note pointing to the new gh number. (No delete — audit trail preserved as you requested.)

## Rollback plan

If you dislike the result before step 5 completes: `gh issue delete` the 3 samples and revert milestone/label additions on #102/#108/#109/#110. No beads changes yet, so beads DB untouched.
