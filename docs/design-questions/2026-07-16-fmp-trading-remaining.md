# Open design questions — fmp_trading test suite (2026-07-16)

**Context:** During the develop test-failure sweep (umbrella #816),
7 PRs (#828–#833) retired 30 of 41 fmp_trading test failures. The
remaining 12 hit design-decision territory — each requires an owner
call before code changes can land safely.

**How to use this doc:** each section names a decision, describes what
it blocks, lists options with trade-offs, notes my recommendation, and
provides an answer template. Reply in-line under `## Decision:` and
open a PR (or comment on the referenced issue) to unblock the work.

Source of failures: https://github.com/prajoria/OpenBB/issues/821 —
see the comment
[#4996870803](https://github.com/prajoria/OpenBB/issues/821#issuecomment-4996870803)
for the numeric summary.

---

## Q1 — `StubbedDataProvider.is_signal_bar_close` strict-mode semantics

**Blocks:** 3 tests

- `test_data_provider.py::TestStubbedProviderReadsRecordedEvents::test_signal_at_ts_returns_true`
- `test_data_provider.py::TestNoSharedMutableState::test_two_provider_instances_have_independent_events`
- `test_data_provider.py::TestNoSharedMutableState::test_concurrent_run_tick_with_stubbed_providers_no_interference`

### Symptom

Two documented invariants contradict:

1. Docstring on `is_signal_bar_close` says: *"Show closest known ts
   to help the operator diagnose the drift"* — implies **strict-always:
   raise `ReplayTsMismatch` for any unknown ts.**
2. Test `test_signal_at_ts_returns_true` asserts (after setting up
   one SignalEvent at ts N): *`assert not provider.is_signal_bar_close(other_ts, "intraday_momentum")`* —
   implies **tolerant-when-recorded-events-exist: silently return
   False for unknown ts as long as the provider has SOME recorded
   events.**

My earlier fix in #832 handled the empty-events case (silent False
if no events at all) but did NOT resolve this contradiction — after
that fix, strict mode still raises when recorded events exist and
tick_ts isn't among them.

### Options

| # | Option | Trade-off |
|---|---|---|
| A | **Tolerant-always**: strict mode never raises, always returns False for unknown ts | Simplest, aligns with `test_signal_at_ts_returns_true`. Loses the diagnostic value of the current `ReplayTsMismatch`. |
| B | **Strict-always** (current): raise for any unknown ts | Loud diagnostic on drift. Breaks the `test_signal_at_ts_returns_true` "no spurious bar closes" assertion — needs test rewrite. |
| C | **Opt-in strict**: `StubbedDataProvider(events=..., strict=True)` defaults to False; strict-only when explicitly requested | Most flexible. Two-state API adds surface area. Existing tests would default to tolerant. |
| D | **Whitelist tolerance**: strict mode raises UNLESS tick_ts falls within `[min_recorded, max_recorded]` window | Middle ground: catches "typo'd date" (way out of range) but tolerates "different tick within recorded session". Adds implementation complexity. |

### My recommendation

**Option C — opt-in strict.** The design intent of `StubbedDataProvider`
is replay determinism, and tolerant behavior lets the caller drive
the loop with any ts without needing to pre-check. Callers who want
loud drift-detection can opt in with `strict=True`. Matches the
Python `dict.get(k, default)` pattern.

### Decision

<!-- Fill in one of A / B / C / D. Add a one-line rationale. -->

**Answer:**

---

## Q2 — `ReplayValidator._compare_tick_events` session-scoped vs tick-scoped events

**Blocks:** 5 tests

- `test_replay_determinism.py::TestReplayDeterminism::*` (4 tests)
- `test_replay_determinism.py::TestReplayMutationDetection::test_replay_with_raise_off_sets_diverged_at_tick`
- Related: `test_replay_no_divergence.py::test_reference_journal_control_flow_deterministic` (fixed one comparison shape in #831, but still hits this)

### Symptom

`ReplayValidator._compare_tick_events` compares emitted events to
recorded events tick-by-tick using the `event_type` string field
(after PR #831 correctness fix). But recorded fixtures include
**session-scoped events** (`session_start`, `session_end`) that fire
once per session, not per tick. The comparator's per-tick loop
receives:

- **Emitted** at tick 0: `["tick"]` (just the tick event)
- **Recorded** at tick 0: `["session_start", "tick"]` (both)

Result: `expected=["session_start", "tick"], actual=["tick"]` —
divergence on tick 0 of every replay.

### Options

| # | Option | Trade-off |
|---|---|---|
| A | **Skip session-scoped events** in comparator: filter both sides on `event_type in {"tick", "signal", "order", "fill", "veto"}` before comparing | Simplest. Assumes session-scoped events are always deterministic (no need to replay-check). If a `session_start` payload ever drifts, we'd miss it. |
| B | **Track session-scoped events separately**: compare once at session-start / session-end, not per tick | More thorough. Adds a two-phase comparator + fixture-loading step. Bigger diff. |
| C | **Regenerate golden fixtures** without session-scoped events, then rely on option A to filter defensively | Fast unblock. Fixtures then lie about the real event stream. |

### My recommendation

**Option A.** Session-scoped events are structural (session_id shape,
timestamps) not behavioral — they're deterministic by construction.
Skip them in the tick-by-tick comparator. If they need their own
regression check, add a separate `_compare_session_lifecycle_events`
that runs once at replay start/end. That's a follow-up, not a blocker.

### Decision

<!-- Fill in one of A / B / C. -->

**Answer:**

---

## Q3 — Golden fixture drift on `test_no_look_ahead`

**Blocks:** 1 test

- `test_no_look_ahead.py::TestNoLookAheadAtFiveMinGranularity::test_signal_at_bar_close_fills_at_next_bar_open`

### Symptom

Golden fixture (a pre-recorded expected output) no longer matches
what the code produces. This can happen for two reasons:

1. **Code drifted from spec** — a code change silently changed
   behavior. Fixture is right; code needs a fix.
2. **Spec drifted from code** — the code was intentionally
   updated (e.g. a signal formula change) but the golden fixture
   wasn't regenerated. Code is right; fixture needs a `TECHTRADE_REGEN_GOLDEN=1` run.

Without domain review of the specific test, I can't distinguish
between the two.

### Options

| # | Option | Trade-off |
|---|---|---|
| A | **Regenerate the golden fixture** (`TECHTRADE_REGEN_GOLDEN=1`) after reviewing the diff between old and new output | Fast unblock. Silently accepts current output as correct — must be paired with a manual diff-review commit. |
| B | **Fix the code** to produce the golden output | Preserves the original intent. Requires understanding what changed. |
| C | **Mark the test `xfail(strict=False)`** with a follow-up issue | Defers decision. Keeps CI green. Signal from this test is lost until re-enabled. |

### My recommendation

**Option A + reviewer discipline**: regenerate the fixture, then in
the commit body diff the new vs old golden with git-diff and confirm
each numeric change is either "intentional per spec change X" or
"floating-point noise". If any diff is unexplained, revert and go to
Option B.

### Decision

<!-- Fill in one of A / B / C. -->

**Answer:**

---

## Q4 — Agent-extra CI handling for architecture tests

**Blocks:** 2 tests

- `test_import_guard.py::test_agent_submodules_fail_cleanly_when_extra_hidden`
- `test_core_unchanged_when_removed.py::test_core_unchanged_when_agent_extra_removed`

### Symptom

Both tests spawn a `pip install .` subprocess (without the `[agent]`
extra) to verify the agent module surface fails cleanly when the
extra isn't installed. On CI the pip install fails because the
`[agent]` extra transitively needs `litellm` which needs Rust
toolchain — even the base install path pulls the same dep tree.

Locally, the tests also fail unless the developer has Rust +
pre-installed everything.

### Options

| # | Option | Trade-off |
|---|---|---|
| A | **Marker skip**: `@pytest.mark.requires_agents` on both, add noxfile deselect | Matches the fix pattern used for issue #818. Fast, restores CI green. Loses the architecture check. |
| B | **Install rust + litellm in CI** | Preserves the check. Adds ~2 minutes to CI runtime + Docker image bloat. |
| C | **Refactor the test** to use `importlib.util.find_spec` instead of `pip install` — check "is X installable via metadata" without actually running the install | Preserves intent + doesn't need Rust. Loses the "does pip actually succeed" check (which is what the test claims to verify). |

### My recommendation

**Option A** — for consistency with #818 (which handles other
agent-touching tests the same way). Filed as a follow-up: revisit
architecture tests when there's a proper "install-in-container" CI
job that's willing to pay the Rust cost.

### Decision

<!-- Fill in one of A / B / C. -->

**Answer:**

---

## Sign-off

Once all 4 decisions are in this doc, a follow-up PR can land the
implementation for each in one batch. Expected retirement: **all 12
remaining fmp_trading tests → 0 failed**, closing #821 entirely.

- Author: Claude (session 2026-07-16)
- Session context: umbrella #816, session summary #790
- PRs already merged: #828 #829 #830 #831 #832 #833
