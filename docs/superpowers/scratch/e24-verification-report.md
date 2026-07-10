# E2.4 Post-Merge Verification Report (bd-sqf)

**Target:** `prajoria/pynecore` main @ merge commit `c70ef4a5d8f4c3497ea5ce97861bbbb3fda7f226`
(merge commit itself is `41b5756c`, PR #6).
**Verifier worktree:** `H:/masterswork/git/pynecore-e23` (fast-forwarded to `origin/main`).
**Date:** 2026-07-09.

---

## 1. Structural verification

| Check | Command | Result | Pass |
|---|---|---|---|
| pyne_compiler .py count (~50 expected) | `find src/pyne_compiler/ -type f -name '*.py' \| wc -l` | **50** | ✅ |
| top-level layout | `ls src/pyne_compiler/` | `__init__.py compiler/ errors/ runtime/ telemetry.py tests/` (+ `__pycache__` from local build) | ✅ |
| no leftover `openbb_pine/` | `git ls-files \| grep -c openbb_pine` | **0** | ✅ |

## 2. History preservation — spot-check

| File | `git log --oneline --all` commits |
|---|---|
| `src/pyne_compiler/compiler/lexer.py` | 2 |
| `src/pyne_compiler/compiler/parser.py` | 3 |
| `src/pyne_compiler/runtime/pynecore_bridge.py` | 1 |
| `src/pyne_compiler/runtime/executor_core.py` | 1 |
| `src/pyne_compiler/errors/base.py` | 1 |

All files show ≥1 commit → history was rewritten & preserved. Aggregate `git log --oneline --all -- src/pyne_compiler/ | wc -l` = **38** commits, consistent with the "33 migrated commits" advertised in the merge body (post-merge extras: E1.5 placeholder drop + version bump + merge commit itself). ✅

## 3. Clean-room trailer preservation

Grep `"Clean-room: I have not viewed TradingView or PyneComp source code."` in `git log --all --format=%B -- <file>`:

| File | Trailer count |
|---|---|
| `compiler/lexer.py` | 3 |
| `compiler/parser.py` | 4 |
| `runtime/pynecore_bridge.py` | 2 |
| `runtime/executor_core.py` | 2 |
| `errors/base.py` | 2 |

All ≥1 → clean-room attestation chain intact. ✅
(Merge-commit body advertises "39 across 33 migrated commits" globally.)

## 4. Merge commit body

`git show --format=%B --no-patch 41b5756c` returns:

```
Merge extracted openbb-pine compiler + core runtime into pynecore

Extraction of compiler + core runtime code originally developed in
prajoria/OpenBB (openbb_pine_support branch, commits 2f000abe3..0de866e73).
Full history preserved via git filter-repo per Pine Extraction Design §7.

Filter-repo scratch state: /tmp/openbb-extract-scratch @ ba3a5c658
Path-renames applied: openbb_pine/{compiler,runtime,tests,...} → src/pyne_compiler/{...}
Clean-room trailers preserved: 39 across 33 migrated commits.
Rollback anchor: tag pre-openbb-extraction-2026-07-09 at bfca0a163.

Closes bd-7bl (OpenBBTechnical-7bl).
```

Body cites: source-commit range (2f000abe3..0de866e73) — note it does **not** literally say "PR #431"; the closes-line is `bd-7bl`, and PR context is captured via the merge PR (#6, not #431 — #431 was on the OpenBB side). ✅ (task-spec wording lag, not a defect). Scratch path, rollback tag, path renames all present.

## 5. Provider work preservation (E1)

- `find src/pynecore/providers/ -name '*.py' | wc -l` → **11** (csv, sqlite, provider, tests/*, etc.) ✅
- Provider test execution: **SKIPPED — environment gap.** The pynecore worktree has no venv installed, and the OpenBB `.venv_win` does not carry pynecore packages. Per task guardrail: reporting as a gap rather than inventing a workaround.

## 6. Deprecation shims not yet installed

`cat src/pyne_compiler/__init__.py` shows only docstring + `__version__ = "0.1.0"`; no shim to `openbb_pine`. Correct at this point — shim install is E3.5. ✅

## 7. openbb-fork side untouched

`git log --oneline -3 openbb_pine_support` HEAD = **`bed5b2d9c`** (E2.1 pre-extraction M1 digest merge).

**Note:** task spec anticipated `0de866e73` (final source of the extraction), but `openbb_pine_support` has since advanced through the E2.1 prep merge (`bed5b2d9c`, PR #430) and plan doc merge (`19e4d8616`, PR #429). Neither touches `openbb_pine/` source, so the extraction subject material is unchanged. ✅

---

## Summary

| # | Check | Verdict |
|---|---|---|
| 1 | Structural | ✅ |
| 2 | History preservation | ✅ |
| 3 | Clean-room trailers | ✅ |
| 4 | Merge commit body | ✅ |
| 5 | E1 providers present / tests run | ⚠️ files ✅, tests skipped (env gap) |
| 6 | No premature shim | ✅ |
| 7 | openbb-fork untouched (extraction subject) | ✅ |

## Follow-ups

No new beads filed. The only gap is a local-environment matter (running the E1 provider test suite requires a pynecore venv), not a defect in the extraction. If desired, a bead can later track "set up pynecore local dev venv for E-phase verification"; not filed here to avoid noise.

## Verdict

**Extraction verification: PASS.**

Clean-room: I have not viewed TradingView or PyneComp source code.
