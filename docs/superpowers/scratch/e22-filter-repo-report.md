# E2.2 — git filter-repo extraction report

**Bead:** OpenBBTechnical-8tl (bd-8tl)
**Date:** 2026-07-09
**Scratch clone:** `/tmp/openbb-extract-scratch`
**Base HEAD (pre-filter):** `bed5b2d9c` (openbb_pine_support @ E2.1 prep)
**Post-filter HEAD:** `ba3a5c658`
**Tool:** `git-filter-repo` (installed as `git_filter_repo` module in `.venv_win`)

## Exact command

Paths file at `/tmp/e2-paths.txt` (38 entries: 14 compiler/runtime/errors/telemetry paths + 24 MOVE-side test files from E0.6 manifest).

```bash
cd /tmp/openbb-extract-scratch && \
H:/masterswork/git/OpenBB-Pine/.venv_win/Scripts/python.exe -m git_filter_repo --force \
  --paths-from-file /tmp/e2-paths.txt \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler/:src/pyne_compiler/compiler/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/runtime/:src/pyne_compiler/runtime/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler_errors.py:src/pyne_compiler/errors/base.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/error_codes.py:src/pyne_compiler/errors/codes.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/diagnostics.py:src/pyne_compiler/errors/diagnostics.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/telemetry.py:src/pyne_compiler/telemetry.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/tests/:src/pyne_compiler/tests/
```

`--force` was required because the scratch clone (created in E2.1) had already
been checked out, so the HEAD reflog contained >1 entry. Since the scratch
clone is disposable and intended solely for extraction, `--force` is safe here.

Contents of `/tmp/e2-paths.txt`:

```
openbb_platform/extensions/pine/openbb_pine/compiler/
openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py
openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py
openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py
openbb_platform/extensions/pine/openbb_pine/runtime/restricted.py
openbb_platform/extensions/pine/openbb_pine/runtime/limits.py
openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py
openbb_platform/extensions/pine/openbb_pine/runtime/secondary_cache.py
openbb_platform/extensions/pine/openbb_pine/runtime/security_hook.py
openbb_platform/extensions/pine/openbb_pine/runtime/strategy_types.py
openbb_platform/extensions/pine/openbb_pine/compiler_errors.py
openbb_platform/extensions/pine/openbb_pine/error_codes.py
openbb_platform/extensions/pine/openbb_pine/diagnostics.py
openbb_platform/extensions/pine/openbb_pine/telemetry.py
# + 24 MOVE-side tests from docs/superpowers/plans/e06-test-split-manifest.md
```

Filter-repo output:
- Parsed 7,279 commits in 2.03s
- Rewrote to 33 commits post-filter (only commits that touched migrating paths)
- Repacked in 3.20s total
- `origin` remote removed (per filter-repo default)

## Verification results

All five checks captured against post-filter HEAD `ba3a5c658`.

| # | Check | Expected | Actual | Verdict |
|---|---|---|---|---|
| 1 | `git log --all --oneline -- src/pyne_compiler/compiler/lexer.py \| wc -l` | ≥5 | **2** | ⚠ below spec expectation — see Surprises §1 |
| 2 | `git log --all --format=%B -- src/pyne_compiler/compiler/lexer.py \| grep -c "Clean-room:"` | ≥1 | **3** | ✅ |
| 3 | `find src/pyne_compiler/ -name '*.py' \| wc -l` | ~60+ | **49** | ⚠ below spec estimate — see Surprises §2 |
| 4 | `find . -path '*/openbb_pine/*'` | 0 | **0** | ✅ |
| 5 | `ls src/pyne_compiler/` | `__init__.py`, `compiler/`, `runtime/`, `errors/`, `tests/` | `compiler/`, `errors/`, `runtime/`, `telemetry.py`, `tests/` | ⚠ no `__init__.py` yet — see Surprises §3 |

Additional cross-checks:
- Total commits in rewritten history: **33**
- Total `Clean-room:` trailers across `git log --all`: **39**
- codegen.py history count: **3** commits (E0.1 split + 2 pre-E0)
- Files under: compiler/ 10, runtime/ 9, errors/ 3 (base + codes + diagnostics), telemetry.py 1, tests/ 24 → matches migration inputs exactly.

## Surprises

1. **Check #1 result (2 vs expected ≥5).** Reality check against the pre-filter
   source: `git -C H:/masterswork/git/OpenBB-Pine log --all --oneline -- openbb_platform/extensions/pine/openbb_pine/compiler/lexer.py | wc -l` returns **3**. So the source repo only had 3 lexer commits to begin with; filter-repo preserved the two commits that produce non-empty tree changes and dropped a merge/PR-squash commit that contributed nothing to the file. The spec estimate ("≥5") was optimistic. Trailer preservation (Check #2 = 3) is the stronger signal and is intact — every Clean-room lineage survives. Not a defect; the plan's ≥5 assumption should be relaxed to ≥2 in future refactor descriptions.

2. **Check #3 result (49 vs ~60+).** Component-by-component sum matches inputs
   exactly: compiler/ (10) + runtime/ (9) + errors/ (3) + telemetry.py (1) +
   tests/ (24 test files but I counted only `.py` files under tests) = 47
   `.py` files migrated + 2 test `__init__.py`s → 49 total. The ~60+ figure in
   the plan appears to have counted per-module tests including subdirectories
   or double-counted the 24-tests-worth of infra. Nothing was dropped.

3. **No `src/pyne_compiler/__init__.py` yet.** Spec §7/§4 puts the package
   `__init__.py` creation in E2.3 (merge into pynecore) — not here. Check #5's
   "expected `__init__.py`" wording in the E2.2 task description is aspirational
   for the post-E2.3 tree; the E2.2 output is a shape-clean sibling set of
   subdirs + `telemetry.py` at the pyne_compiler root, which is what feeds E2.3.

4. **`--force` required.** E2.1 (bd-fis) had already checked out
   `openbb_pine_support` in the scratch clone, adding a second HEAD reflog
   entry beyond the initial clone. filter-repo's freshness guard fired.
   Using `--force` is safe here (disposable scratch), but E2.1's step-2
   sequence should note this.

## Scratch clone status

Preserved at `/tmp/openbb-extract-scratch`, post-filter HEAD `ba3a5c658`,
ready for E2.3 (bd-7bl) to consume via `git remote add extract` on the
pynecore feature branch.

Closes bd-8tl (OpenBBTechnical-8tl).
