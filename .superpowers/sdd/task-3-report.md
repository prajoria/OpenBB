# Task 3 Report

## Scope

Implemented **Task 3 of #1963 (EOD snapshot store — idempotency, restamping,
and retention hook)** only, atop the Task 1/2 `SnapshotStore` contract and
`SqliteSnapshotStore` lifecycle already reviewed and merged on this branch
(`feat/pi-eod-snapshot-store-gh-1963`).

Per the brief (`.superpowers/sdd/task-3-brief.md`) and the design spec
(`docs/superpowers/specs/2026-08-09-asof-snapshot-cache-and-alignment-design.md`
§3.3, §4.5), implemented the three remaining Protocol methods on
`SqliteSnapshotStore`:

- `should_skip(dataset, entity_key, input_hash) -> bool` — `True` iff the
  current LIVE row already carries this `input_hash` (idempotent-rerun
  detection).
- `restamp_live(dataset, entity_key, as_of_session, job_run_id) -> bool` —
  advances the LIVE pointer's `as_of_session` to a new session without
  recomputing the payload, by inserting a *new* row (same
  payload/provenance, new session/run IDs) and running it through the
  existing `stage -> validate -> promote` atomic path. Never mutates the
  prior LIVE row in place; the prior row is flipped to `SUPERSEDED` by
  `promote()`'s existing logic and remains in history for audit.
- `prune(policy=None) -> int` — applies `RetentionPolicy(keep_sessions)`.
  Default (`None`, or `keep_sessions=None`) keeps everything and returns
  `0`. A bounded policy deletes only non-LIVE rows outside the newest
  `keep_sessions` distinct `as_of_session` values per
  `(dataset, entity_key)` key; the `state != 'live'` filter is an
  unconditional safety net so a LIVE row is never pruned regardless of
  its session's age.

## Files changed

- `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
- `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

(`RetentionPolicy` and the three Protocol method stubs already existed from
Task 1/2 — only the concrete `SqliteSnapshotStore` bodies were added here.)

## TDD evidence

### RED

Command:

```powershell
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py -q
```

Result: **4 failed, 13 passed** — all four new Task 3 tests failed with
`AttributeError: 'SqliteSnapshotStore' object has no attribute 'should_skip'`
/ `'restamp_live'` / `'prune'`, confirming the methods were absent before
implementation (the 13 pre-existing Task 1/2 tests were unaffected).

### GREEN

Same command after implementing the three methods:

Result: **17 passed in 0.47s** — all four new tests plus all 13 pre-existing
tests green.

### Reverse verification (required by brief Step 5)

Temporarily mutated `restamp_live()` to update the existing LIVE row's
`as_of_session`/`job_run_id` columns **in place** (a single `UPDATE ...
WHERE state = 'live'`) instead of inserting a new row and promoting it —
i.e., reintroduced exactly the in-place-mutation bug the brief warns
against.

Command:

```powershell
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py -q
```

Result: **1 failed, 16 passed** —
`test_matching_input_hash_can_be_restamped_without_recompute` failed at
`assert len(history) == 2` with `AssertionError: assert 1 == 2` (history
only contained the single mutated row instead of the original run + the
restamped run). This confirms the test suite actually discriminates
between the correct auditable-insert behavior and the forbidden in-place
mutation — not a ceremonial assertion (CLAUDE.md R7).

Restored the correct implementation (insert new row via
stage/validate/promote) and reran:

Result: **17 passed in 0.48s** — back to green, diff confirmed to contain
no leftover mutation-test code (`git diff | Select-String "MUTATION"`
returned nothing).

## Implementation notes

- `should_skip` reuses `get_live()` (already canonicalizes internally) —
  no new SQL needed.
- `restamp_live` deliberately reuses the existing `stage()`/`validate()`/
  `promote()` methods rather than hand-rolling a second write path, so it
  inherits the same atomicity, keep-last-good rank guard, and
  validated-before-promote gate as every other promotion — "the same
  atomic path" from the brief is literal code reuse, not just a similar
  shape.
- `restamp_live` returns `False` (logs a WARNING) if there is no current
  LIVE row to restamp, or if the copied-payload candidate fails
  validation — it never partially mutates state on a refusal.
- `prune()` groups by `(dataset, entity_key)`, ranks each key's distinct
  `as_of_session` values, and deletes only `state != 'live'` rows outside
  the newest `keep_sessions` sessions, inside the store's existing `_tx()`
  transaction wrapper. The dynamic `NOT IN (...)`/`1 = 1` SQL fragment is
  built only from fixed literals / `?` placeholders (no external string
  reaches the SQL text) — flagged by `ruff` S608 and suppressed with a
  `# noqa: S608` justification comment, matching the existing pattern in
  `execution/mysql_paper_engine.py` and
  `providers/fmp_cached/openbb_fmp_cached/utils/database.py`.
- Extended the test file's `_stage()` helper with an `input_hash=` kwarg
  (previously unexposed) and added `_live_store()` / `_store_with_three_sessions()`
  fixtures used by the new tests.
- Added `test_should_skip_is_false_with_no_live_row_or_mismatched_hash` and
  `test_restamp_live_refuses_when_no_live_row_exists` as extra coverage for
  the negative/edge paths named in the brief's interfaces but not spelled
  out in its two example tests.
- Updated the module and test-file docstrings that previously said
  `should_skip`/`restamp_live`/`prune` "land in Task 3" — they now
  describe Task 3 as done, matching the rest of the file's pattern of a
  running scope note per task.

## Validation

- `.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py -q` → **17 passed**
- `.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade -m "not integration" -q` → **795 passed, 3 skipped, 56 deselected** (full extension suite, no regressions)
- `.venv_portfolio\Scripts\python.exe -m black --check <2 files>` → clean (after one auto-format of a line the initial draft left too long)
- `.venv_portfolio\Scripts\python.exe -m ruff check <2 files>` → clean (after adding the S608 justification comment and rewording two docstrings to imperative mood, D401)
- `.venv_portfolio\Scripts\python.exe -m pylint <2 files>` → no new findings; only pre-existing noise: `C0328` (CRLf-vs-LF, documented CLAUDE.md local-only artifact) and a pre-existing `C0123` on line 121 of the test file that predates this task (confirmed via `git show HEAD:...` + pylint on the original file — same finding, unrelated to Task 3, left untouched per instructions not to fix unrelated Minor notes)
- `.venv_portfolio\Scripts\python.exe -m mypy openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py` → `Success: no issues found in 1 source file`
- `.venv_portfolio\Scripts\python.exe -m codespell_lib <2 files>` → clean

## Invariants preserved

- **stage → validate → atomic promote**: `restamp_live` is built entirely
  from calls to the existing `stage()`/`validate()`/`promote()` — no
  parallel write path was introduced.
- **Explicit LIVE pointer**: `should_skip`/`restamp_live` both read/write
  through `state = 'live'`, never `MAX(as_of_session)`.
- **No in-place restamp mutation**: verified both positively (the real
  implementation inserts a new row) and negatively (reverse-verification
  mutation test above proved the suite fails if a future edit reintroduces
  in-place mutation).
- **LIVE rows never pruned**: `prune()`'s `DELETE` always filters
  `state != 'live'` regardless of session-window membership; test asserts
  `get_live()` still returns a row (the newest session's payload) after a
  bounded prune.

## Self-review

- Reviewed the full diff of both changed files; confirmed no changes
  outside `should_skip`/`restamp_live`/`prune` and their required test
  coverage/imports/docstring-scope updates.
- Confirmed `.superpowers/sdd/task-2-report.md`, which showed as already
  modified in `git status` before this session started, was left
  untouched and is **not** included in this task's commit.
- Did not address the pre-existing `C0123` pylint note on the test file
  (predates Task 3; out of scope per instructions).

## Commit

- Message: `feat(techtrade): add snapshot restamp and retention`
- Trailer: `Refs #1963`
- Trailer: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
- Files staged: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`, `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

## Concerns

- None outstanding for this task's scope. The MySQL backend equivalent of
  these three methods (Task 4) is not implemented here and is tracked
  separately per the brief's file list.
