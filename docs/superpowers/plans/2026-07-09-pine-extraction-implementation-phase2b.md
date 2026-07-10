# Pine Extraction to prajoria/pynecore — Implementation Plan (Phase 2B: E2 + E3 + E4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **⚠ Scope note:** This is **Phase 2B** of the extraction plan. Phase 2A (E0 + E1 = 12 sub-beads across 5 waves) is complete as of 2026-07-09 (openbb-fork HEAD `9ecd02391`, pynecore `main` HEAD `bfca0a163`). Phase 2B is: E2 (git filter-repo extraction of compiler + core runtime to pynecore, 4 tasks), E3 (openbb-fork refactor to consume the extracted pynecore, 5 tasks), E4 (unfreeze the 9 open Phase 2 P1 sub-beads that were paused for extraction, 2 tasks). Phase 2A plan lives at `docs/superpowers/plans/2026-07-07-pine-extraction-implementation.md`.

**Goal:** Move the Pine compiler + core runtime from openbb-fork to `prajoria/pynecore` as `src/pyne_compiler/` via `git filter-repo` (preserving full history + Clean-room trailers). Refactor openbb-fork's remaining shell (FMP + BYO providers + REST routers + MCP + CLI) to consume the extracted pynecore via the unified `pynecore.providers.Provider` base class. Unfreeze the 9 open Phase 2 P1 sub-beads and re-scope their DESIGN fields to the new `pyne_compiler.*` module paths.

**Architecture:** E2 uses `git filter-repo --path` (list from E0.6 manifest + spec §7) + `--path-rename` (add `src/` prefix per R1) to extract compiler + core runtime with full history preservation. Merges to pynecore via `--allow-unrelated-histories`. E3 bumps the openbb-fork submodule pointer to post-E2 pynecore, refactors `fmp_provider.py` + `byo_provider.py` to inherit `pynecore.providers.Provider`, rewrites all `openbb_pine.compiler.*` and `openbb_pine.runtime.{executor_core,...}` imports to `pyne_compiler.*` / `pyne_compiler.runtime.*`, then removes the temporary `_data_provider_stub.py`. E4 unfreezes the 9 P1 beads, updates each DESIGN field to reference `pyne_compiler.*` module paths, and updates the freeze bd memory to UNFROZEN.

**Tech Stack:** Python 3.11+ (per pynecore floor), pytest, `git filter-repo` v2.34+, PyneCore runtime, pandas, FastAPI (openbb-fork side only).

## Global Constraints

- Compiler-touching commits MUST include `Clean-room: I have not viewed TradingView or PyneComp source code.` trailer (PRD §2.5 / spec §10)
- Branch-protection hook enforced: no direct pushes to `openbb_pine_support` or `develop`; every change is a feature branch + PR
- Test baseline: **openbb-fork 1389 passed** + **pynecore providers 98 passed** must be preserved (in whichever repo tests land)
- Beads (`bd`) is the ONLY task tracker (per CLAUDE.md); no TodoWrite/TaskCreate
- Environment: `.venv_win\Scripts\python.exe` (never system Python)
- Verify before commit — show test output, never claim green without evidence
- All new work goes to feature branches; PRs target `openbb_pine_support` (openbb-fork) or `main` (pynecore)
- `pyne_compiler` lives at `src/pyne_compiler/` under pynecore's src/ layout (spec R1)
- Extend the existing `pynecore.providers.Provider` base class — do NOT create a new `adapters/` directory (spec R2 — already implemented in Phase 2A)
- Every FMP/BYO refactor in E3 must pass the pynecore behavioral conformance suite (already merged E1.4 bd-cko)
- Preserve full git history via git filter-repo (spec Q5, §7)
- Retain E3 deprecation shims for one release for old `openbb_pine.compiler.*` and `openbb_pine.runtime.executor` paths (spec §13.5)

---

## File map (Phase 2B)

| File / directory | Disposition | Phase | Notes |
|---|---|---|---|
| Scratch clone of openbb-fork at `/tmp/openbb-extract-scratch` | CREATE (E2.1) | E2 | Local-only; `git clone --no-local` from openbb-fork worktree |
| Tag `pre-openbb-extraction-2026-07-09` on pynecore main | CREATE (E2.1) | E2 | Rollback anchor per spec §8 |
| Rewritten history in scratch clone (post-filter-repo) | CREATE (E2.2) | E2 | Full `--path` + `--path-rename` per spec §7 |
| `third_party/pynecore/src/pyne_compiler/` (11,400+ LOC tree) | POPULATED (E2.3) | E2 | Merged in via `git merge --allow-unrelated-histories` |
| `openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py` | DELETE (E2.3 or E3.4) | E2/E3 | Temporary E0.2 stub; superseded by real `pynecore.providers.Provider` |
| `third_party/pynecore/` submodule pointer | BUMP (E3.1) | E3 | From `2919eac` → post-E2 merge SHA |
| `openbb_platform/extensions/pine/openbb_pine/runtime/fmp_provider.py` | MODIFY (E3.2) | E3 | Inherit `pynecore.providers.Provider`; mode-2; overrides `stream()`/`fetch()` |
| `openbb_platform/extensions/pine/openbb_pine/runtime/byo_provider.py` | MODIFY (E3.3) | E3 | Inherit `Provider` mode-1; construction-scoped |
| `openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py` | MODIFY (E3.4) | E3 | Adapter SITE 1: list[OHLCV] → pd.DataFrame at Provider→dispatcher boundary (bead 78w) |
| `openbb_platform/extensions/pine/openbb_pine/routers/compile_router.py` | MODIFY (E3.4) | E3 | `openbb_pine.__version__` → `pyne_compiler.__version__` in cache-key hash + `PineCompileResponse` |
| `openbb_platform/extensions/pine/openbb_pine/compiler/*.py` (all migrated modules) | REWRITE→SHIM (E3.5) | E3 | Each becomes `DeprecationWarning` re-export from `pyne_compiler.*` per §13.5 |
| `openbb_platform/extensions/pine/openbb_pine/runtime/{executor,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue,pynecore_bridge}.py` | REWRITE→SHIM (E3.5) | E3 | Deprecation shims for migrated runtime modules (executor stays as thin shim + shell) |
| `openbb_platform/extensions/pine/openbb_pine/compiler_errors.py` | REWRITE→SHIM (E3.5) | E3 | Re-export from `pyne_compiler.errors` with `DeprecationWarning` |
| 9 P1 sub-bead DESCRIPTION/DESIGN fields (aeh, god, 5k0, liz, 4d0, 250, cht, ph0, 0uh) | UPDATE (E4.1) | E4 | Point at `pyne_compiler.*` paths |
| `bd remember pine-phase2-frozen-for-extraction` | UPDATE (E4.1) | E4 | Rename → UNFROZEN + record post-extraction SHAs |
| `openbb_platform/extensions/pine/openbb_pine/_coverage_manifest.py` | MODIFY (E4.2) | E4 | Point wild-corpus + BUILTINS_IMPLEMENTED at new module paths |
| Beads `qj7`, `7a8` DESCRIPTION fields | UPDATE (E4.2) | E4 | Post-extraction path fixups |

---

## Phase E2 — Extract compiler + core runtime via git filter-repo (4 tasks)

**Where:** Scratch clone of openbb-fork + pynecore feature branch `feat/extract-openbb-pine-compiler`.
**Dependency graph:** E2.1 → E2.2 → E2.3 → E2.4 (fully sequential).

### Task E2.1: Prepare scratch clone + tag pre-extraction pynecore HEAD

**Bead:** `OpenBBTechnical-fis` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Create: `/tmp/openbb-extract-scratch/` (fresh `git clone --no-local` of openbb-fork worktree)
- Create: git tag `pre-openbb-extraction-2026-07-09` on `pynecore` origin/main HEAD (`bfca0a163`)
- Test: `verify_scratch_and_tag.sh` (ad-hoc script asserting scratch clone contains 82 tests + tag reachable from origin)

**Interfaces:**
- Consumes: openbb-fork HEAD `9ecd02391` on `openbb_pine_support`; pynecore origin/main HEAD `bfca0a163`
- Produces: scratch clone with full commit history for `openbb_platform/extensions/pine/openbb_pine/`; immutable rollback tag on pynecore

**Depends on:** Phase 2A merged (openbb-fork HEAD `9ecd02391`, pynecore `bfca0a163`).

- [ ] **Step 1: Cut work branch in pynecore + create rollback tag**

```bash
cd /path/to/pynecore-clone
git switch main
git pull --ff-only
# Confirm we are at the expected HEAD
[ "$(git rev-parse HEAD)" = "bfca0a163" ] || { echo "pynecore HEAD drifted"; exit 1; }
git tag -a pre-openbb-extraction-2026-07-09 -m "Rollback anchor before openbb-pine compiler extraction (spec §8)"
git push origin pre-openbb-extraction-2026-07-09
```

Expected: tag pushed to origin; `git ls-remote --tags origin | grep pre-openbb-extraction` returns one line.

- [ ] **Step 2: Prepare scratch clone of openbb-fork**

```bash
mkdir -p /tmp/openbb-extract-scratch
cd /tmp/openbb-extract-scratch
git clone --no-local /path/to/OpenBB-Pine .
# Confirm we captured the E0.7-inclusive HEAD
git switch openbb_pine_support
[ "$(git rev-parse HEAD)" = "9ecd02391" ] || { echo "openbb-fork HEAD drifted"; exit 1; }
# Baseline test count for later comparison
find openbb_platform/extensions/pine/openbb_pine/tests/unit -name 'test_*.py' | wc -l
# Expected: 82
```

- [ ] **Step 3: Verify scratch clone has full pre-E2 history for compiler files**

```bash
git log --oneline --follow openbb_platform/extensions/pine/openbb_pine/compiler/lexer.py | wc -l
# Expected: >= 5 commits (lexer has been touched many times pre-E0)
git log --oneline --follow openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py | wc -l
# Expected: >= 1 commit (E0.3 creation); pre-E0 lineage lives in executor.py
```

- [ ] **Step 4: Install git-filter-repo v2.34+ inside the scratch clone**

```bash
pip install --user "git-filter-repo>=2.34"
git filter-repo --version
# Expected: git filter-repo 2.34.0 or newer
```

- [ ] **Step 5: Commit workspace notes (docs-only) in the parent worktree**

No code commit yet — E2.1 leaves the scratch clone in place. Record the rollback tag creation in `bd remember`:

```bash
bd remember pine-extraction-rollback-tag "pre-openbb-extraction-2026-07-09 tagged on pynecore main at bfca0a163 on 2026-07-09; scratch clone at /tmp/openbb-extract-scratch"
```

Task E2.1 complete when: rollback tag pushed, scratch clone verified at expected SHA, filter-repo installed.

---

### Task E2.2: Run git filter-repo with curated --path and --path-rename lists

**Bead:** `OpenBBTechnical-8tl` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Modify (in scratch clone only): entire git history rewritten by filter-repo
- Create: `.git/filter-repo/analysis/renames.txt` audit log
- Test: `spot_check_history.sh` — asserts `git log --follow` on 5 files including one E0-split file returns preserved trailers

**Interfaces:**
- Consumes: scratch clone from E2.1
- Produces: scratch clone with rewritten history where only `src/pyne_compiler/**` paths exist for migrating content; Clean-room trailers verbatim

**Depends on:** E2.1.

- [ ] **Step 1: Build the curated file lists**

Assemble the E2 `--path` list = (E0.6 manifest 24 MOVE tests) + (compiler dir) + (core runtime files) + (compiler errors + telemetry). Reproduce spec §7 verbatim:

```bash
cd /tmp/openbb-extract-scratch
cat > /tmp/e2-paths.txt <<'EOF'
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
EOF

# Append 24 MOVE-side tests from the E0.6 manifest lines 158-181
sed -n '158,181p' /path/to/OpenBB-Pine/docs/superpowers/plans/e06-test-split-manifest.md >> /tmp/e2-paths.txt

wc -l /tmp/e2-paths.txt
# Expected: 14 + 24 = 38 lines
```

- [ ] **Step 2: Run filter-repo (dry-run first)**

```bash
cd /tmp/openbb-extract-scratch
git filter-repo --analyze
# Reports current path frequencies. Sanity-check: openbb_pine/compiler/lexer.py should appear.

# Real run — --path from file, --path-rename per spec §7 (src/-prefixed per R1)
git filter-repo \
  --paths-from-file /tmp/e2-paths.txt \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler/:src/pyne_compiler/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/runtime/:src/pyne_compiler/runtime/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler_errors.py:src/pyne_compiler/errors/base.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/error_codes.py:src/pyne_compiler/errors/codes.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/diagnostics.py:src/pyne_compiler/errors/diagnostics.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/telemetry.py:src/pyne_compiler/telemetry.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/tests/:src/pyne_compiler/tests/
```

Expected: filter-repo prints "Parsed N commits" then "New history written". Working tree now contains only `src/pyne_compiler/**`.

- [ ] **Step 3: Verify tree shape**

```bash
find . -type d -maxdepth 3 | sort
# Expected: ./src/pyne_compiler/{,compiler/,runtime/,errors/,tests/}

find src/pyne_compiler -name '*.py' | wc -l
# Expected: >= 60 (compiler + runtime-core + errors + telemetry + 24 tests)

# Confirm the E0-split files landed
ls src/pyne_compiler/runtime/executor_core.py \
   src/pyne_compiler/errors/base.py \
   src/pyne_compiler/runtime/pynecore_bridge.py
```

- [ ] **Step 4: Verify Clean-room trailers preserved (spot-check 5 commits, INCLUDE at least one E0-split file per §12/R3)**

```bash
# 3 wholesale-moved files
for f in src/pyne_compiler/compiler/lexer.py src/pyne_compiler/compiler/codegen.py src/pyne_compiler/compiler/type_checker.py; do
  echo "=== $f ==="
  git log --follow --format="%h %s%n%b" -3 -- "$f" | grep -c "^Clean-room:"
done
# Expected: each shows >= 1 Clean-room trailer

# 2 E0-split files (partial-history expected per R3)
for f in src/pyne_compiler/runtime/executor_core.py src/pyne_compiler/errors/base.py; do
  echo "=== $f (partial-history expected — only reaches E0 creation commit) ==="
  git log --follow --format="%h %s%n%b" -- "$f" | head -20
  # Confirm at least one Clean-room trailer in the visible history
  git log --follow --format="%b" -- "$f" | grep -c "^Clean-room:"
done
# Expected: >= 1 trailer for each (E0.1/E0.3 commits both carried the trailer)
```

- [ ] **Step 5: Snapshot the audit log + record the rewritten HEAD**

```bash
cat .git/filter-repo/analysis/renames.txt | head -50
NEW_HEAD=$(git rev-parse HEAD)
echo "Post-filter-repo HEAD: $NEW_HEAD"
bd remember pine-extraction-e2-filter-repo-head "post-filter-repo scratch HEAD $NEW_HEAD (rewritten from openbb-fork 9ecd02391); paths file /tmp/e2-paths.txt; renames per spec §7"
```

Task E2.2 complete when: tree has only `src/pyne_compiler/**`, spot-check confirms trailers preserved (including one E0-split file with truncated-but-non-empty history).

---

### Task E2.3: Merge rewritten history to pynecore main + delete _data_provider_stub.py + open PR

**Bead:** `OpenBBTechnical-7bl` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Create: pynecore branch `feat/extract-openbb-pine-compiler` from `main`
- Modify: pynecore tree gains `src/pyne_compiler/**` via `--allow-unrelated-histories` merge
- Delete: `src/pyne_compiler/runtime/_data_provider_stub.py` if it slipped in (E0.2 stub; superseded by real `Provider`)
- Modify: `pynecore/pyproject.toml` — verify `packages.find` picks up `pyne_compiler` (already handled in E1.5 placeholder)
- Test: `src/pyne_compiler/tests/` full run must be green

**Interfaces:**
- Consumes: scratch clone rewritten history from E2.2; existing pynecore main
- Produces: pynecore PR containing `src/pyne_compiler/` with preserved history + all Clean-room trailers

**Depends on:** E2.2.

- [ ] **Step 1: Cut pynecore feature branch + add scratch as remote**

```bash
cd /path/to/pynecore-clone
git switch main
git pull --ff-only
git switch -c feat/extract-openbb-pine-compiler main

git remote add extract /tmp/openbb-extract-scratch
git fetch extract
# Discover the extracted branch name (usually openbb_pine_support after filter-repo)
git branch -r | grep extract/
```

- [ ] **Step 2: Merge with --allow-unrelated-histories**

```bash
git merge extract/openbb_pine_support --allow-unrelated-histories --no-ff -m "Merge extracted openbb-pine compiler + core runtime into pynecore

Extraction of compiler + core runtime code originally developed in
prajoria/OpenBB (openbb_pine_support branch, commits 2f000abe3..9ecd02391).
Full history preserved via git filter-repo per Pine Extraction Design §7.

All migrated commits retain their original per-bead attribution and
Clean-room trailers.

Files created by Phase E0 (executor_core.py, compiler_errors.py,
pynecore_bridge.py, telemetry.py) carry history from their E0 creation
commit forward only, per §7.1.

Extraction bead: OpenBBTechnical-rbf (Phase 2B)
"
```

Expected: merge succeeds; no path collisions (E1.5 placeholder `src/pyne_compiler/__init__.py` is replaced by the extracted one — if a conflict fires, keep the extracted version).

- [ ] **Step 3: Delete the temporary stub if present**

```bash
if [ -f src/pyne_compiler/runtime/_data_provider_stub.py ]; then
  git rm src/pyne_compiler/runtime/_data_provider_stub.py
  git commit -m "chore(extract): remove E0.2 _data_provider_stub — Provider base now real (bd-E2.3)"
fi
# Rewrite dispatcher import if it references the stub
grep -rn "_data_provider_stub" src/pyne_compiler/ && echo "REWRITE NEEDED" || echo "clean"
# If REWRITE NEEDED, replace `from openbb_pine.runtime._data_provider_stub import DataProviderStub`
# with `from pynecore.providers import Provider` and commit.
```

- [ ] **Step 4: Reinstall + run migrated tests**

```bash
pip install -e . --no-deps
pytest src/pyne_compiler/tests/ -v --tb=short
# Expected baseline: 24 MOVE-side test files passing (test count TBD ~= 300-400 individual tests)
# If ModuleNotFoundError: re-check pyproject.toml packages.find (spec R1)
python -c "import pyne_compiler; print(pyne_compiler.__version__)"
python -c "from pyne_compiler.compiler import lexer, parser, codegen; print('ok')"
python -c "from pyne_compiler.runtime import executor_core, security_dispatcher; print('ok')"
python -c "from pyne_compiler.errors import PineSyntaxError; print('ok')"
```

- [ ] **Step 5: Push + open PR**

```bash
git push -u origin feat/extract-openbb-pine-compiler
gh pr create --repo prajoria/pynecore \
  --base main --head feat/extract-openbb-pine-compiler \
  --title "feat(extract): Pine compiler + core runtime — E2 (bd-E2.3)" \
  --body "$(cat <<'EOF'
## Summary
Extracts the Pine v5/v6 compiler + core runtime from prajoria/OpenBB into pynecore as `src/pyne_compiler/`. Preserves full git history + Clean-room trailers via `git filter-repo` per Pine Extraction Design §7.

## Provenance
- Rewritten history captured from openbb-fork HEAD `9ecd02391` (E0.7 grep-gate)
- Merged via `--allow-unrelated-histories`
- 5-commit trailer spot-check completed on wholesale + E0-split files (see E2.4)
- E0-split files (executor_core.py, compiler_errors.py, pynecore_bridge.py, telemetry.py) carry history only from their E0 creation commit forward per §7.1

## Test plan
- [x] `pytest src/pyne_compiler/tests/ -v` green
- [x] `import pyne_compiler` works
- [x] `git log --follow src/pyne_compiler/compiler/lexer.py` shows original 2f000abe3-era history

Design: `docs/superpowers/specs/2026-07-06-pine-extraction-to-pynecore-design.md` §6.E2 / §7 / §12.
Plan: `docs/superpowers/plans/2026-07-09-pine-extraction-implementation-phase2b.md` E2.3.
EOF
)"
```

Task E2.3 complete when: PR opened; tests green in CI; merge SHA recorded.

---

### Task E2.4: Post-merge verification + spot-check trailers on 5 commits including E0-split files

**Bead:** `OpenBBTechnical-sqf` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Create: `docs/superpowers/plans/e2-post-merge-verification.md` (checklist of the 5 spot-checks + assertions)
- Test: `src/pyne_compiler/tests/test_import_stability.py` (new — per spec §9 regression guard)

**Interfaces:**
- Consumes: pynecore PR from E2.3 (merged)
- Produces: signed-off verification record; import-stability regression test

**Depends on:** E2.3 (PR merged).

- [ ] **Step 1: Merge the PR + capture the post-merge SHA**

```bash
cd /path/to/pynecore-clone
git switch main
git pull --ff-only
POST_E2=$(git rev-parse HEAD)
echo "post-E2 pynecore HEAD: $POST_E2"
```

- [ ] **Step 2: Spot-check 5 commits (3 wholesale + 2 E0-split per §12 / R3)**

```bash
# Wholesale-moved files — full history preserved
for f in src/pyne_compiler/compiler/lexer.py \
         src/pyne_compiler/compiler/codegen.py \
         src/pyne_compiler/compiler/type_checker.py; do
  echo "=== $f ==="
  count=$(git log --follow --format="%b" -- "$f" | grep -c "^Clean-room:")
  echo "Clean-room trailer count: $count"
  [ "$count" -ge 1 ] || { echo "FAIL: no trailer on $f"; exit 1; }
done

# E0-split files — partial history acceptable (E0 commit forward only)
for f in src/pyne_compiler/runtime/executor_core.py \
         src/pyne_compiler/runtime/pynecore_bridge.py; do
  echo "=== $f (partial-history expected) ==="
  first_commit=$(git log --follow --format="%h %s" -- "$f" | tail -1)
  echo "Earliest commit: $first_commit"
  count=$(git log --follow --format="%b" -- "$f" | grep -c "^Clean-room:")
  echo "Clean-room trailer count: $count"
  [ "$count" -ge 1 ] || { echo "FAIL: E0-split file $f has no trailer in visible history"; exit 1; }
done
```

Expected: each of 5 files shows >= 1 `Clean-room:` trailer. E0-split files' earliest commit is E0.1 / E0.3 / E0.5.

- [ ] **Step 3: Write regression guard test (per spec §9 "test_import_stability")**

Create `src/pyne_compiler/tests/test_import_stability.py`:

```python
"""E2.4 regression guard: every public compiler entry point importable at
the documented module path. Catches accidental import-path breakage from
future refactors (spec §9)."""


def test_top_level_package_importable() -> None:
    import pyne_compiler
    assert isinstance(pyne_compiler.__version__, str)


def test_compiler_entry_points() -> None:
    from pyne_compiler.compiler import (
        codegen,
        lexer,
        parser,
        type_checker,
        ir,
    )
    # These are the public entry points that openbb-fork's router calls
    from pyne_compiler.compiler.compile_pine import compile_pine  # noqa: F401
    from pyne_compiler.compiler.types import CompiledModule  # noqa: F401


def test_runtime_entry_points() -> None:
    from pyne_compiler.runtime import (
        executor_core,
        security_dispatcher,
        secondary_cache,
        security_hook,
        strategy_types,
        restricted,
        limits,
    )
    # bridge is the sys.path shim
    from pyne_compiler.runtime.pynecore_bridge import _install_pynecore_path_if_needed  # noqa: F401


def test_error_hierarchy_intact() -> None:
    from pyne_compiler.errors import (
        PineError,
        PineSyntaxError,
        PineTypeError,
        PineCodegenError,
        PineRuntimeError,
        PineSecurityError,
    )
    assert issubclass(PineSyntaxError, PineError)
    assert issubclass(PineRuntimeError, PineError)
```

- [ ] **Step 4: Run + confirm green**

```bash
pytest src/pyne_compiler/tests/test_import_stability.py -v
# Expected: 4 passed
pytest src/pyne_compiler/tests/ -q
# Expected: full migrated test suite green (baseline preserved)
```

- [ ] **Step 5: Commit + push + open follow-up PR**

```bash
git switch -c chore/e2-import-stability main
git add src/pyne_compiler/tests/test_import_stability.py
git commit -m "test(pyne_compiler): import-stability regression guard (bd-E2.4)

Per Pine Extraction Design §9, pins the public import surface for the
extracted compiler + runtime so future refactors that break import
paths get caught by CI immediately.

Also records the 5-commit spot-check for Clean-room trailer preservation
in the E2.4 verification checklist (docs/... — separate PR).
"
git push -u origin chore/e2-import-stability
gh pr create --repo prajoria/pynecore --base main --head chore/e2-import-stability \
  --title "test(pyne_compiler): import-stability regression guard — E2.4"
```

Also update the extraction memory:

```bash
bd remember pine-extraction-e2-complete "E2 complete 2026-07-09: post-E2 pynecore HEAD $POST_E2 (was bfca0a163); scratch clone at /tmp/openbb-extract-scratch (safe to delete after E3.1 submodule bump); 5-commit spot-check green (3 wholesale + 2 E0-split); rollback tag pre-openbb-extraction-2026-07-09 still on origin"
```

Task E2.4 complete when: 5-commit trailer spot-check documented + signed off; regression-guard PR opened; extraction memory recorded.

---

## Phase E3 — Refactor openbb-fork to consume extracted pynecore (5 tasks)

**Where:** openbb-fork on feature branches from `openbb_pine_support`.
**Dependency graph:** E3.1 → (E3.2 ‖ E3.3 ‖ E3.4) → E3.5. (E3.4 rewrites imports; E3.2/E3.3 rewrite providers; they touch different files and can run in parallel with E3.4.)

### Task E3.1: Bump third_party/pynecore submodule pointer to post-E2 HEAD

**Bead:** `OpenBBTechnical-kpg` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Modify: `third_party/pynecore/` submodule pointer (from `2919eac` to post-E2 pynecore main SHA)
- Modify: `.gitmodules` (verify — no branch pin needed; SHA is enough)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py` (existing) must still pass; new smoke test `test_submodule_bumped.py`

**Interfaces:**
- Consumes: post-E2 pynecore main HEAD from E2.4 (memory `pine-extraction-e2-complete`)
- Produces: openbb-fork submodule pin pointing at pynecore version that contains `src/pyne_compiler/`

**Depends on:** E2.4 (PR merged; post-E2 SHA recorded).

- [ ] **Step 1: Cut feature branch**

```bash
cd /path/to/OpenBB-Pine
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e3-1-submodule-bump openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_submodule_bumped.py`:

```python
"""E3.1: third_party/pynecore submodule must point at a commit that
contains src/pyne_compiler/ (i.e. post-E2)."""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
SUBMODULE = REPO_ROOT / "third_party" / "pynecore"


def test_submodule_head_contains_pyne_compiler() -> None:
    """After E3.1 bump, walking into the submodule finds src/pyne_compiler/."""
    assert (SUBMODULE / "src" / "pyne_compiler" / "__init__.py").is_file(), (
        "third_party/pynecore submodule is still on pre-E2 SHA — bump per E3.1"
    )


def test_submodule_pyne_compiler_importable() -> None:
    """The bumped submodule's pyne_compiler is importable via the bridge."""
    # Trigger sys.path install
    from openbb_pine.runtime import pynecore_bridge  # noqa: F401
    import pyne_compiler  # noqa: F401


def test_submodule_pyne_compiler_has_version() -> None:
    import pyne_compiler
    assert isinstance(pyne_compiler.__version__, str)
    assert len(pyne_compiler.__version__) > 0
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_submodule_bumped.py -v
```
Expected: FAIL — `src/pyne_compiler/__init__.py` not present in submodule (`2919eac` is pre-E2).

- [ ] **Step 4: Bump submodule pointer**

```bash
POST_E2=$(bd memories --json pine-extraction-e2-complete | python -c "import sys, json, re; d=json.load(sys.stdin); m=re.search(r'HEAD (\w+)', d['pine-extraction-e2-complete']); print(m.group(1))")
echo "Bumping to $POST_E2"
cd third_party/pynecore
git fetch origin
git checkout "$POST_E2"
cd ../..
git add third_party/pynecore
git status  # confirm only the submodule pointer changed
```

- [ ] **Step 5: Re-run tests + commit + PR**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_submodule_bumped.py -v
# Expected: 3 passed
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py -v
# Expected: pre-existing tests still green

git commit -m "chore(pine): bump third_party/pynecore to post-E2 (bd-E3.1)

Bumps submodule from 2919eac (pre-Wave-3) to $POST_E2 (post-E2 extraction).
Enables openbb-fork to import pyne_compiler.* per Pine Extraction Design §6.E3 step 1.

E3.2 (fmp_provider), E3.3 (byo_provider), and E3.4 (import rewrites)
depend on this bump being on openbb_pine_support first.
"
git push -u origin refactor/e3-1-submodule-bump
gh pr create --base openbb_pine_support --head refactor/e3-1-submodule-bump \
  --title "chore(pine): bump pynecore submodule post-E2 — E3.1 (bd-E3.1)"
```

Task E3.1 complete when: submodule bumped; 3 new tests + existing bridge tests green.

---

### Task E3.2: Refactor fmp_provider.py to inherit pynecore.providers.Provider (mode-2)

**Bead:** `OpenBBTechnical-3ch` (tracks `OpenBBTechnical-rbf`; also handles `OpenBBTechnical-78w` SITE 1)

**Files:**
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/fmp_provider.py` (445 LOC)
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py` (add list[OHLCV]→pd.DataFrame adapter at Provider boundary — bead 78w SITE 1)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider.py` (existing — must remain green + new mode-2 assertions)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider_conformance.py` (new — runs the pynecore behavioral conformance suite against the FMP provider)

**Interfaces:**
- Consumes: `pynecore.providers.Provider` (extended in E1.1), pynecore behavioral conformance suite (E1.4 bd-cko)
- Produces: `FMPOHLCVProvider(Provider)` — mode-2 (construction takes only config: api_key, cache_dir, base_url; symbol/timeframe are method parameters per spec §5.2); overrides `stream()` + `fetch()` for direct REST-query optimization; conformance-suite green

**Depends on:** E3.1 (submodule bumped so `pynecore.providers.Provider` importable in openbb-fork). Parallel with E3.3, E3.4.

- [ ] **Step 1: Cut feature branch**

```bash
git switch -c refactor/e3-2-fmp-provider-inherits-provider openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider_conformance.py`:

```python
"""E3.2: FMPOHLCVProvider inherits pynecore.providers.Provider (mode-2)
and passes the shared behavioral conformance suite (E1.4 bd-cko)."""
from datetime import datetime, timezone

import pytest

pytest.importorskip("pyne_compiler")  # ensure post-E2 submodule
pytest.importorskip("pynecore.providers")

from pynecore.providers import Provider
from openbb_pine.runtime.fmp_provider import FMPOHLCVProvider


def test_fmp_provider_is_provider_subclass() -> None:
    assert issubclass(FMPOHLCVProvider, Provider), (
        "E3.2 refactor incomplete: FMPOHLCVProvider must inherit "
        "pynecore.providers.Provider (see spec §5.2 mode 2)."
    )


def test_fmp_construction_takes_config_only() -> None:
    """Mode-2: no symbol/timeframe in __init__, only config."""
    p = FMPOHLCVProvider(api_key="test-key")
    # Symbol/timeframe are method-scoped, not construction-scoped
    assert not hasattr(p, "_construction_symbol") or p._construction_symbol is None


def test_fmp_stream_signature_matches_provider_base() -> None:
    import inspect
    sig = inspect.signature(FMPOHLCVProvider.stream)
    params = list(sig.parameters)
    # Base contract: self, symbol, timeframe, *, start, end
    assert "symbol" in params
    assert "timeframe" in params
    assert "start" in params
    assert "end" in params


@pytest.mark.integration
def test_fmp_passes_pynecore_conformance_suite(fmp_provider_instance) -> None:
    """Runs the shared behavioral suite from src/pynecore/providers/tests/test_conformance.py."""
    from pynecore.providers.tests.test_conformance import assert_provider_conformance
    assert_provider_conformance(fmp_provider_instance, symbol="AAPL", timeframe="1D")
```

Also assert bead 78w SITE 1 adapter is present:

```python
def test_dispatcher_has_ohlcv_to_dataframe_adapter() -> None:
    """bead 78w SITE 1: dispatcher must convert list[OHLCV] → pd.DataFrame
    at the Provider→dispatcher boundary (pre-existing dispatcher works in
    DataFrame-space per Wave-4 finding phase2b-plan-notes-from-wave3)."""
    from openbb_pine.runtime import security_dispatcher
    # Look for the adapter — either a function or an inline transform.
    src = open(security_dispatcher.__file__).read()
    assert "pd.DataFrame" in src, "adapter missing: dispatcher needs list[OHLCV]→DataFrame"
    assert "OHLCV" in src or "provider.fetch" in src or "provider.stream" in src
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider_conformance.py -v -m "not integration"
```
Expected: FAIL — `FMPOHLCVProvider` doesn't inherit from `Provider` yet.

- [ ] **Step 4: Refactor fmp_provider.py**

1. Change class signature: `class FMPOHLCVProvider(Provider):` (was previously plain class or `DataProviderStub`).
2. Move `symbol` + `timeframe` from `__init__` to method params on `stream()`/`fetch()` (spec §5.2 mode 2).
3. Override `stream()` + `fetch()` — direct REST query, do NOT fall back to base class file-backed default. `stream()` yields `OHLCV`; `fetch()` returns `list[OHLCV]`.
4. Implement all Provider ABC methods (`to_tradingview_timeframe`, `to_exchange_timeframe`, `get_list_of_symbols`, `update_symbol_info`, `get_opening_hours_and_sessions`, `download_ohlcv`) — most delegate to existing FMP internals; `download_ohlcv` no-ops or delegates to `fetch()` for compatibility.
5. In `security_dispatcher.py`: add the list[OHLCV]→pd.DataFrame adapter at the Provider boundary (bead 78w SITE 1):

```python
# security_dispatcher.py — at the point where a Provider is consulted
def _ohlcv_list_to_dataframe(bars: list[OHLCV]) -> pd.DataFrame:
    """bead 78w SITE 1: Provider returns list[OHLCV]; dispatcher works in
    DataFrame-space (security_hook.iloc[bar_index] + SecondarySeriesCache).
    Adapt at the boundary."""
    if not bars:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return pd.DataFrame([b._asdict() if hasattr(b, "_asdict") else vars(b) for b in bars])
```

- [ ] **Step 5: Run tests + commit + PR**

```bash
.venv_win/Scripts/python.exe -m pytest \
  openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider.py \
  openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider_conformance.py \
  -v -m "not integration"
# Expected: pre-existing + new tests all green

# Optional integration gate (requires FMP key):
.venv_win/Scripts/python.exe -m pytest \
  openbb_platform/extensions/pine/openbb_pine/tests/unit/test_fmp_provider_conformance.py \
  -v -m "integration"

git commit -m "refactor(pine): FMPOHLCVProvider inherits pynecore.providers.Provider (bd-E3.2, closes bd-78w SITE 1)

Per spec §5.2 mode-2:
- Construction takes config only (api_key, cache_dir, base_url)
- symbol/timeframe move to stream()/fetch() method parameters
- stream() + fetch() overridden for direct REST-query optimization

Also closes bd-78w SITE 1: adds list[OHLCV]→pd.DataFrame adapter in
security_dispatcher.py at the Provider→dispatcher boundary (dispatcher
works in DataFrame-space; adapter isolates the shape change).

Pynecore behavioral conformance suite (E1.4 bd-cko) passes.
"
git push -u origin refactor/e3-2-fmp-provider-inherits-provider
gh pr create --base openbb_pine_support --head refactor/e3-2-fmp-provider-inherits-provider \
  --title "refactor(pine): FMP provider inherits Provider — E3.2 (bd-E3.2)"
```

Task E3.2 complete when: conformance suite green (unit + integration); pre-existing FMP tests still green.

---

### Task E3.3: Refactor byo_provider.py to inherit pynecore.providers.Provider (mode-1)

**Bead:** `OpenBBTechnical-tzm` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/byo_provider.py` (191 LOC)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_byo_provider.py` (existing — must remain green)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_byo_provider_conformance.py` (new)

**Interfaces:**
- Consumes: `pynecore.providers.Provider`
- Produces: `BYOProvider(Provider)` — mode-1 (construction-scoped to a single (symbol, timeframe); `stream()` for a different (symbol, timeframe) raises `ValueError` per spec §5.2 mode-1)

**Depends on:** E3.1 (submodule bumped). Parallel with E3.2, E3.4.

- [ ] **Step 1: Cut feature branch**

```bash
git switch -c refactor/e3-3-byo-provider-inherits-provider openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_byo_provider_conformance.py`:

```python
"""E3.3: BYOProvider inherits pynecore.providers.Provider (mode-1,
construction-scoped) and passes the shared behavioral conformance suite."""
import pytest
pytest.importorskip("pynecore.providers")

from pynecore.providers import Provider
from openbb_pine.runtime.byo_provider import BYOProvider


def test_byo_is_provider_subclass() -> None:
    assert issubclass(BYOProvider, Provider), (
        "E3.3 incomplete: BYOProvider must inherit pynecore.providers.Provider"
    )


def test_byo_mode1_rejects_mismatched_symbol(sample_records) -> None:
    """Mode-1: instance is scoped to (symbol, timeframe) at construction.
    stream() for a different (symbol, timeframe) raises ValueError (spec §5.2)."""
    p = BYOProvider(records=sample_records, symbol="AAPL", timeframe="1D")
    with pytest.raises(ValueError, match="symbol|timeframe"):
        list(p.stream(symbol="MSFT", timeframe="1D"))


def test_byo_passes_conformance_suite(sample_byo_provider) -> None:
    from pynecore.providers.tests.test_conformance import assert_provider_conformance
    assert_provider_conformance(sample_byo_provider, symbol="AAPL", timeframe="1D")
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_byo_provider_conformance.py -v
```
Expected: FAIL — `BYOProvider` not yet a `Provider` subclass.

- [ ] **Step 4: Refactor byo_provider.py**

1. `class BYOProvider(Provider):` — inherits.
2. `__init__(self, records, symbol, timeframe, *, cache_dir=None)` — mode-1 (construction-scoped).
3. Override `stream()`: if requested (symbol, timeframe) mismatches `__init__` values → raise `ValueError` per spec §5.2 mode-1 contract.
4. Override `fetch()`: `return list(self.stream(...))`.
5. Implement remaining ABC methods (`to_tradingview_timeframe` etc. — most no-op since BYO is user-supplied records).

- [ ] **Step 5: Run + commit + PR**

```bash
.venv_win/Scripts/python.exe -m pytest \
  openbb_platform/extensions/pine/openbb_pine/tests/unit/test_byo_provider.py \
  openbb_platform/extensions/pine/openbb_pine/tests/unit/test_byo_provider_conformance.py -v
# Expected: pre-existing + new tests green

git commit -m "refactor(pine): BYOProvider inherits pynecore.providers.Provider mode-1 (bd-E3.3)

Per spec §5.2 mode-1:
- Construction-scoped to a single (symbol, timeframe)
- stream() for mismatched (symbol, timeframe) raises ValueError
- Passes pynecore behavioral conformance suite (E1.4 bd-cko)
"
git push -u origin refactor/e3-3-byo-provider-inherits-provider
gh pr create --base openbb_pine_support --head refactor/e3-3-byo-provider-inherits-provider \
  --title "refactor(pine): BYO provider inherits Provider (mode-1) — E3.3 (bd-E3.3)"
```

Task E3.3 complete when: BYO conformance suite + pre-existing tests all green.

---

### Task E3.4: Rewrite openbb_pine.compiler.* + runtime imports → pyne_compiler.* + delete _data_provider_stub.py

**Bead:** `OpenBBTechnical-8sq` (tracks `OpenBBTechnical-rbf`; also closes `OpenBBTechnical-78w` SITE 2)

**Files:**
- Modify: every non-test `openbb_pine/**/*.py` that imports from `openbb_pine.compiler.*`, `openbb_pine.runtime.{executor_core,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue,pynecore_bridge}`, or `openbb_pine.compiler_errors`
- Modify: `openbb_platform/extensions/pine/openbb_pine/routers/compile_router.py` — `openbb_pine.__version__` → `pyne_compiler.__version__` (spec §6.E3 step 7; per subagent GAP #9)
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py` — bead 78w SITE 2: `iter_ohlcv()` → `Provider.stream()`/`fetch()` (executor_core lives in pynecore post-E2, so this edit happens against `pyne_compiler.runtime.executor_core` if not already applied there — verify grep first)
- Delete: `openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py` if still present
- Test: full openbb-fork pine test suite (baseline 1389 passed) must remain green

**Interfaces:**
- Consumes: post-E2 `pyne_compiler.*` public API; post-E3.1 submodule
- Produces: openbb-fork with zero `openbb_pine.compiler.*` / `openbb_pine.runtime.executor_core` production imports outside deprecation shims

**Depends on:** E3.1. Parallel with E3.2, E3.3.

- [ ] **Step 1: Cut feature branch**

```bash
git switch -c refactor/e3-4-import-rewrites openbb_pine_support
```

- [ ] **Step 2: Grep the current import surface (baseline)**

```bash
grep -rn "from openbb_pine\.compiler\|from openbb_pine\.runtime\.executor_core\|from openbb_pine\.runtime\.security_dispatcher\|from openbb_pine\.runtime\.secondary_cache\|from openbb_pine\.runtime\.security_hook\|from openbb_pine\.runtime\.strategy_types\|from openbb_pine\.runtime\.restricted\|from openbb_pine\.runtime\.limits\|from openbb_pine\.runtime\._pynecore_glue\|from openbb_pine\.runtime\.pynecore_bridge\|from openbb_pine\.compiler_errors\|from openbb_pine import __version__" \
  openbb_platform/extensions/pine/openbb_pine/ \
  --include='*.py' \
  | grep -v tests/ | grep -v /compiler/ | grep -v _data_provider_stub \
  > /tmp/e3-4-import-baseline.txt
wc -l /tmp/e3-4-import-baseline.txt
# Snapshot: expected 20-40 non-test import sites
```

- [ ] **Step 3: Write the failing grep-gate test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e3_4_import_migration.py`:

```python
"""E3.4: no production code (non-shim, non-test) imports the migrated modules
under openbb_pine.* paths. All go through pyne_compiler.*."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROD = ROOT / "openbb_pine"


def _grep(pattern: str) -> list[str]:
    out = subprocess.run(
        ["grep", "-rn", "--include=*.py", pattern, str(PROD)],
        capture_output=True, text=True,
    )
    return [
        line for line in out.stdout.splitlines()
        # Skip tests, the compiler/ shim tree (E3.5), the runtime shim files (E3.5),
        # and _data_provider_stub which is deleted below.
        if "/tests/" not in line
        and "/compiler/" not in line
        and "_data_provider_stub" not in line
        and "# shim" not in line
    ]


def test_no_production_import_of_openbb_pine_compiler() -> None:
    hits = _grep(r"from openbb_pine\.compiler")
    assert not hits, f"E3.4 incomplete — production imports still on openbb_pine.compiler.*:\n" + "\n".join(hits)


def test_no_production_import_of_migrated_runtime_modules() -> None:
    hits = _grep(r"from openbb_pine\.runtime\.\(executor_core\|security_dispatcher\|secondary_cache\|security_hook\|strategy_types\|restricted\|limits\|_pynecore_glue\|pynecore_bridge\)")
    assert not hits, f"E3.4 incomplete — production imports still on migrated runtime modules:\n" + "\n".join(hits)


def test_no_production_import_of_compiler_errors() -> None:
    hits = _grep(r"from openbb_pine\.compiler_errors")
    assert not hits, f"E3.4 incomplete — production imports still on openbb_pine.compiler_errors:\n" + "\n".join(hits)


def test_compile_router_uses_pyne_compiler_version() -> None:
    """spec §6.E3 step 7 + GAP #9: compile_router.py must read
    pyne_compiler.__version__ (not openbb_pine.__version__) so its cache-key
    hash matches pynecore's on-disk cache key."""
    src = (PROD / "routers" / "compile_router.py").read_text()
    assert "pyne_compiler" in src and "__version__" in src, (
        "compile_router.py must use pyne_compiler.__version__ per spec §6.E3 step 7"
    )
    assert "openbb_pine import __version__" not in src, (
        "compile_router.py still imports openbb_pine.__version__ — will cause cache-key drift"
    )


def test_data_provider_stub_deleted() -> None:
    stub = PROD / "runtime" / "_data_provider_stub.py"
    assert not stub.exists(), "E0.2 stub must be deleted in E3.4 — Provider base class now real"
```

- [ ] **Step 4: Run to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e3_4_import_migration.py -v
```
Expected: 5 tests fail.

- [ ] **Step 5: Do the rewrite (mechanical + one manual case)**

```bash
# Mechanical rewrites (verify each replaces > 0 sites)
find openbb_platform/extensions/pine/openbb_pine -name '*.py' ! -path '*/tests/*' ! -path '*/compiler/*' ! -name '_data_provider_stub.py' -print0 | \
  xargs -0 sed -i \
    -e 's|from openbb_pine\.compiler\.|from pyne_compiler.|g' \
    -e 's|import openbb_pine\.compiler\.|import pyne_compiler.|g' \
    -e 's|from openbb_pine\.runtime\.executor_core|from pyne_compiler.runtime.executor_core|g' \
    -e 's|from openbb_pine\.runtime\.security_dispatcher|from pyne_compiler.runtime.security_dispatcher|g' \
    -e 's|from openbb_pine\.runtime\.secondary_cache|from pyne_compiler.runtime.secondary_cache|g' \
    -e 's|from openbb_pine\.runtime\.security_hook|from pyne_compiler.runtime.security_hook|g' \
    -e 's|from openbb_pine\.runtime\.strategy_types|from pyne_compiler.runtime.strategy_types|g' \
    -e 's|from openbb_pine\.runtime\.restricted|from pyne_compiler.runtime.restricted|g' \
    -e 's|from openbb_pine\.runtime\.limits|from pyne_compiler.runtime.limits|g' \
    -e 's|from openbb_pine\.runtime\._pynecore_glue|from pyne_compiler.runtime._pynecore_glue|g' \
    -e 's|from openbb_pine\.runtime\.pynecore_bridge|from pyne_compiler.runtime.pynecore_bridge|g' \
    -e 's|from openbb_pine\.compiler_errors|from pyne_compiler.errors|g'

# Manual: compile_router.py version import (spec §6.E3 step 7)
sed -i \
  -e 's|from openbb_pine import __version__ as _pine_version|from pyne_compiler import __version__ as _pine_version|g' \
  -e 's|openbb_pine\.__version__|pyne_compiler.__version__|g' \
  openbb_platform/extensions/pine/openbb_pine/routers/compile_router.py

# Delete the E0.2 stub
git rm openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py

# Handle bead 78w SITE 2: executor_core lives in pynecore now; verify iter_ohlcv
# was already migrated to Provider.stream()/fetch() as part of E2 filter-repo.
# If any residual reference remains in the openbb-fork side, rewrite it:
grep -rn "iter_ohlcv" openbb_platform/extensions/pine/openbb_pine/ ! -path '*/tests/*' && \
  echo "REMAINING iter_ohlcv sites — rewrite to Provider.stream()/fetch()" || \
  echo "78w SITE 2 clean (executor_core migrated as part of E2)"
```

- [ ] **Step 6: Run grep-gate + full pine suite**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e3_4_import_migration.py -v
# Expected: 5 passed

.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/ -q -m "not integration"
# Expected: baseline 1389 passed / 10 skipped preserved
```

- [ ] **Step 7: Commit + PR**

```bash
git add -A
git commit -m "refactor(pine): rewrite compiler/runtime imports → pyne_compiler.* + delete _data_provider_stub (bd-E3.4, closes bd-78w SITE 2)

Per spec §6.E3 step 4-7:
- openbb_pine.compiler.* → pyne_compiler.*
- openbb_pine.runtime.{executor_core,security_dispatcher,secondary_cache,
  security_hook,strategy_types,restricted,limits,_pynecore_glue,
  pynecore_bridge} → pyne_compiler.runtime.*
- openbb_pine.compiler_errors → pyne_compiler.errors
- compile_router.py: openbb_pine.__version__ → pyne_compiler.__version__
  (cache-key hash must match pynecore's on-disk cache key — spec §6.E3
  step 7 / GAP #9)
- Delete E0.2 _data_provider_stub.py (superseded by real Provider base)
- Verify bd-78w SITE 2 clean (iter_ohlcv migrated with executor_core in E2)

Baseline 1389 passed / 10 skipped preserved.
"
git push -u origin refactor/e3-4-import-rewrites
gh pr create --base openbb_pine_support --head refactor/e3-4-import-rewrites \
  --title "refactor(pine): rewrite compiler/runtime imports + delete stub — E3.4 (bd-E3.4)"
```

Task E3.4 complete when: grep-gate green; full pine suite baseline preserved; `_data_provider_stub.py` deleted.

---

### Task E3.5: Install deprecation shims per spec §13.5 + M1 smoke test + close-out

**Bead:** `OpenBBTechnical-ijq` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Create/Modify: `openbb_platform/extensions/pine/openbb_pine/compiler/__init__.py` + each submodule (codegen.py, type_checker.py, parser.py, lexer.py, ir.py, types.py, compile_pine.py, compile_pine_to_program.py, compile_cache.py, v5_migration.py, emit.py, builtin_signatures.py) as `DeprecationWarning` re-export shims
- Create/Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/{executor,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue,pynecore_bridge}.py` as shims (executor_core is NOT reintroduced — old executor.py stays as thin `DeprecationWarning` re-export → `pyne_compiler.runtime.executor_core`)
- Create/Modify: `openbb_platform/extensions/pine/openbb_pine/compiler_errors.py` as `DeprecationWarning` re-export from `pyne_compiler.errors`
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_deprecation_shims.py` (new — asserts old paths still work + emit `DeprecationWarning`)
- Test: M1 smoke — `from openbb import obb; obb.pine.run(source, symbol="AAPL", provider="fmp")` produces byte-identical output vs. pre-extraction

**Interfaces:**
- Consumes: post-E3.4 openbb-fork with new imports
- Produces: one-release compatibility layer for external users of `openbb_pine.compiler.*` etc.; M1 smoke evidence for spec §12.4

**Depends on:** E3.2, E3.3, E3.4 all merged.

- [ ] **Step 1: Cut feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e3-5-deprecation-shims openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_deprecation_shims.py`:

```python
"""E3.5: old openbb_pine.compiler.* and openbb_pine.runtime.* paths still
work AND emit DeprecationWarning per spec §13.5."""
import warnings
import pytest


def test_openbb_pine_compiler_codegen_shim() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from openbb_pine.compiler import codegen  # noqa: F401
        # At least one DeprecationWarning was raised, pointing at pyne_compiler
        dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert dep, "codegen shim did not emit DeprecationWarning"
        assert "pyne_compiler" in str(dep[0].message)


def test_openbb_pine_compiler_public_names_still_resolvable() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from openbb_pine.compiler.codegen import compile_pine  # noqa: F401
        from openbb_pine.compiler.type_checker import type_check  # noqa: F401
        from openbb_pine.compiler.lexer import Lexer  # noqa: F401


def test_openbb_pine_runtime_executor_shim() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from openbb_pine.runtime import executor  # noqa: F401
        dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert dep
        assert "pyne_compiler" in str(dep[0].message)


def test_openbb_pine_compiler_errors_shim() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from openbb_pine import compiler_errors  # noqa: F401
        # PineSyntaxError still importable
        assert hasattr(compiler_errors, "PineSyntaxError")
        dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert dep
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_deprecation_shims.py -v
```
Expected: FAIL — shims not installed yet (or old modules import from pyne_compiler without emitting warning).

- [ ] **Step 4: Install shims per spec §13.5 template**

For each migrated submodule, replace the file content with the template shim (example `openbb_pine/compiler/codegen.py`):

```python
"""DEPRECATED: openbb_pine.compiler.codegen moved to pyne_compiler.codegen.
This shim will be removed in the next minor release."""
import warnings

from pyne_compiler.codegen import *  # noqa: F401,F403
from pyne_compiler.codegen import compile_pine, emit  # noqa: F401 — explicit for star-safety

warnings.warn(
    "openbb_pine.compiler.codegen is deprecated; import from pyne_compiler.codegen instead. "
    "This shim will be removed in the next minor release.",
    DeprecationWarning,
    stacklevel=2,
)
```

Repeat pattern for:
- `openbb_pine/compiler/{__init__,codegen,type_checker,parser,lexer,ir,types,compile_pine,compile_pine_to_program,compile_cache,v5_migration,emit,builtin_signatures}.py`
- `openbb_pine/runtime/{executor,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue,pynecore_bridge}.py`
- `openbb_pine/compiler_errors.py` (re-exports from `pyne_compiler.errors`)

The `errors.py` post-E0.1 re-export block already covers compiler errors; keep it but change its source from `openbb_pine.compiler_errors` → `pyne_compiler.errors` and add a `DeprecationWarning` at module top.

- [ ] **Step 5: Run shim tests + full suite + M1 smoke**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_deprecation_shims.py -v
# Expected: 4 passed

.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/ -q -m "not integration"
# Expected: baseline 1389 passed / 10 skipped preserved

# M1 smoke — byte-identical vs. pre-extraction
.venv_win/Scripts/python.exe - <<'EOF'
from openbb import obb
src = open("Analysis/samples/rsi_reversal.pine").read()  # or any known sample
out = obb.pine.run(src, symbol="AAPL", provider="fmp")
import hashlib, json
digest = hashlib.sha256(json.dumps(out.model_dump(), sort_keys=True, default=str).encode()).hexdigest()
print("M1 output digest:", digest)
# Cross-check vs. pre-extraction digest (record from pre-E2 run into bd remember)
EOF
```

- [ ] **Step 6: Commit + PR + record**

```bash
git commit -m "refactor(pine): deprecation shims for openbb_pine.compiler.* + runtime.* (bd-E3.5)

Per spec §13.5 — one-release migration window.

Each migrated module in openbb_pine.compiler/ and openbb_pine.runtime/
becomes a re-export shim from pyne_compiler.*, emitting a
DeprecationWarning at import time. Downstream notebooks / Analysis/ /
external users' code continues to work; migration message points at the
new path.

Removal target: next pynesys-pynecore minor version bump.

M1 smoke verified byte-identical output vs. pre-extraction baseline
(digest recorded in bd remember pine-extraction-m1-smoke).
"
git push -u origin refactor/e3-5-deprecation-shims
gh pr create --base openbb_pine_support --head refactor/e3-5-deprecation-shims \
  --title "refactor(pine): deprecation shims + M1 smoke — E3.5 (bd-E3.5)"

bd remember pine-extraction-m1-smoke "M1 smoke on rsi_reversal.pine AAPL/fmp: digest=<sha256> post-E3.5; matches pre-E2 baseline; captured 2026-07-09"
```

Task E3.5 complete when: shim tests + full suite green; M1 smoke byte-identical; PR merged.

---

## Phase E4 — Unfreeze Phase 2 P1 sub-beads + coverage manifest updates (2 tasks)

**Where:** openbb-fork feature branch + `bd` writes.
**Dependency graph:** E4.1 → E4.2. Both depend on all E3 tasks merged.

### Task E4.1: Unfreeze 9 P1 sub-beads + rescope DESIGN to pyne_compiler.* paths + update freeze memory

**Bead:** `OpenBBTechnical-8j9` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Update (bd only): 9 P1 sub-bead DESCRIPTION fields — aeh, god, 5k0, liz, 4d0, 250, cht, ph0, 0uh
- Update (bd only): `bd remember pine-phase2-frozen-for-extraction` → replaced with `pine-phase2-unfrozen-2026-07-09`

**Interfaces:**
- Consumes: post-E3 openbb-fork HEAD; post-E2 pynecore HEAD
- Produces: 9 beads with updated DESIGN pointing at `pyne_compiler.*`; freeze memory replaced with UNFROZEN record

**Depends on:** E3.5 merged.

- [ ] **Step 1: Verify prerequisites**

```bash
# Confirm all E3 tasks merged
gh pr list --repo prajoria/OpenBB --state merged --search "E3.1 E3.2 E3.3 E3.4 E3.5" | wc -l
# Expected: 5 (or however many were split)

# Confirm the frozen bead list from memory matches current bd state
bd memories --json pine-phase2-frozen-for-extraction | python -c "import sys, json, re; d=json.load(sys.stdin); print(re.findall(r'\b[a-z0-9]{3}\b', d['pine-phase2-frozen-for-extraction']))"
# Expected: ['aeh', 'god', '5k0', 'liz', '4d0', '250', 'cht', 'ph0', '0uh']

bd list --label pine --status blocked | grep -oE 'OpenBBTechnical-[a-z0-9]{3}' | sort > /tmp/frozen-current.txt
wc -l /tmp/frozen-current.txt
# Expected: 9
```

- [ ] **Step 2: Rescope + unfreeze each bead**

For each of the 9 IDs, update DESCRIPTION replacing old paths with new (mechanical sed on the DESCRIPTION text) then transition status:

```bash
for id in aeh god 5k0 liz 4d0 250 cht ph0 0uh; do
  # Fetch current description
  bd show "$id" --json > /tmp/bead-$id.json

  # Rescope: mechanical path substitutions
  python - <<EOF
import json, re
d = json.load(open("/tmp/bead-$id.json"))
desc = d.get("description", "")
subs = [
    (r'openbb_pine\.compiler\.', 'pyne_compiler.'),
    (r'openbb_pine/compiler/', 'src/pyne_compiler/'),
    (r'openbb_pine\.runtime\.executor_core', 'pyne_compiler.runtime.executor_core'),
    (r'openbb_pine\.runtime\.security_dispatcher', 'pyne_compiler.runtime.security_dispatcher'),
    (r'openbb_pine\.runtime\.secondary_cache', 'pyne_compiler.runtime.secondary_cache'),
    (r'openbb_pine\.runtime\.security_hook', 'pyne_compiler.runtime.security_hook'),
    (r'openbb_pine\.runtime\.strategy_types', 'pyne_compiler.runtime.strategy_types'),
    (r'openbb_pine\.compiler_errors', 'pyne_compiler.errors'),
]
for pat, rep in subs:
    desc = re.sub(pat, rep, desc)
desc += "\n\n[E4.1 2026-07-09: paths rescoped to pyne_compiler.* per Pine Extraction Design §6.E4.]"
open("/tmp/bead-$id-new.txt", "w").write(desc)
EOF

  bd update "$id" --description "$(cat /tmp/bead-$id-new.txt)"
  bd update "$id" --status open  # transition from blocked → open (ready for pickup)
done
```

- [ ] **Step 3: Replace the freeze memory**

```bash
bd forget pine-phase2-frozen-for-extraction
POST_E2=$(bd memories --json pine-extraction-e2-complete | python -c "import sys,json,re; d=json.load(sys.stdin); print(re.search(r'HEAD (\w+)', d['pine-extraction-e2-complete']).group(1))")
POST_E3=$(git -C /path/to/OpenBB-Pine rev-parse openbb_pine_support)
bd remember pine-phase2-unfrozen-2026-07-09 "Phase 2 P1 sub-beads (aeh, god, 5k0, liz, 4d0, 250, cht, ph0, 0uh) UNFROZEN 2026-07-09 after Pine Extraction (bead rbf) merged. openbb-fork HEAD ${POST_E3}, pynecore HEAD ${POST_E2}. Wave 3+ may now pick these up against pyne_compiler.* module paths. Design: docs/superpowers/specs/2026-07-06-pine-extraction-to-pynecore-design.md; Plan: docs/superpowers/plans/2026-07-09-pine-extraction-implementation-phase2b.md"
```

- [ ] **Step 4: Verify freeze/unfreeze checklist per spec §12 R9**

```bash
# Every previously-frozen bead must be either unblocked OR have an explicit still-blocked reason
for id in aeh god 5k0 liz 4d0 250 cht ph0 0uh; do
  status=$(bd show "$id" | head -1)
  echo "$id: $status"
done
# Expected: all show OPEN (or READY), none show BLOCKED
```

- [ ] **Step 5: Record success**

```bash
bd remember pine-extraction-completed "extracted 2026-07-09; pynecore HEAD ${POST_E2}; openbb-fork HEAD ${POST_E3}; deprecation-shim removal target release <next minor>; freeze memory replaced by pine-phase2-unfrozen-2026-07-09"
# Also unblock bd-qj7 dependency on rbf (spec §12 point 9)
bd update qj7 --status open
```

Task E4.1 complete when: 9 beads open + rescoped; freeze memory replaced; `pine-extraction-completed` recorded; bd-qj7 unblocked.

---

### Task E4.2: Update wild-corpus coverage manifest + PRD amendments + bead qj7/7a8 path fixups

**Bead:** `OpenBBTechnical-or5` (tracks `OpenBBTechnical-rbf`)

**Files:**
- Modify: `openbb_platform/extensions/pine/openbb_pine/_coverage_manifest.py` — BUILTINS_IMPLEMENTED / FEATURES_IMPLEMENTED entries that reference module paths point at `pyne_compiler.*`
- Modify: `docs/PRD.md` §16.6 (or the current PRD file) — reflect post-extraction module topology
- Update (bd only): `OpenBBTechnical-qj7` DESCRIPTION — post-extraction paths
- Update (bd only): `OpenBBTechnical-7a8` DESCRIPTION — CCXT/CapitalCom conformance audit against extracted pyne_compiler
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e4_coverage_manifest_paths.py` (new)

**Interfaces:**
- Consumes: post-E4.1 unfrozen bead state
- Produces: coverage-manifest + PRD aligned with post-extraction topology; `bd prime` retrievable UNFROZEN memory

**Depends on:** E4.1.

- [ ] **Step 1: Cut feature branch**

```bash
git switch -c refactor/e4-2-coverage-manifest openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e4_coverage_manifest_paths.py`:

```python
"""E4.2: coverage manifest references pyne_compiler.* paths post-extraction."""
from pathlib import Path


def test_coverage_manifest_uses_pyne_compiler_paths() -> None:
    from openbb_pine import _coverage_manifest
    src = Path(_coverage_manifest.__file__).read_text()
    # No stale openbb_pine.compiler.* module-path strings remain in the manifest
    assert "openbb_pine.compiler." not in src, (
        "E4.2 incomplete: _coverage_manifest.py still references old compiler paths"
    )


def test_bd_prime_retrievable_unfrozen_memory() -> None:
    """The unfreeze memory must be discoverable via `bd memories pine-phase2-unfrozen`."""
    import subprocess
    out = subprocess.run(["bd", "memories", "pine-phase2-unfrozen"], capture_output=True, text=True)
    assert "unfrozen" in out.stdout.lower() or "UNFROZEN" in out.stdout, (
        "unfreeze memory not discoverable — E4.1 memory rename failed"
    )
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e4_coverage_manifest_paths.py -v
```
Expected: FAIL (if `_coverage_manifest.py` still cites old paths).

- [ ] **Step 4: Rescope coverage manifest + PRD**

```bash
# _coverage_manifest.py: point at pyne_compiler.*
sed -i \
  -e 's|openbb_pine\.compiler\.|pyne_compiler.|g' \
  -e 's|openbb_pine\.runtime\.executor_core|pyne_compiler.runtime.executor_core|g' \
  openbb_platform/extensions/pine/openbb_pine/_coverage_manifest.py

# PRD §16.6 (path may differ — grep to find the section)
grep -rn "openbb_pine\.compiler\|openbb_pine/compiler" docs/PRD*.md openbb_platform/extensions/pine/docs/ 2>/dev/null
# Manually update each hit to reference pyne_compiler.* / src/pyne_compiler/
```

- [ ] **Step 5: Update bd-qj7 + bd-7a8 descriptions**

```bash
for id in qj7 7a8; do
  bd show "$id" --json > /tmp/bead-$id.json
  python - <<EOF
import json, re
d = json.load(open("/tmp/bead-$id.json"))
desc = d.get("description", "")
desc = re.sub(r'openbb_pine\.compiler\.', 'pyne_compiler.', desc)
desc = re.sub(r'openbb_pine/compiler/', 'src/pyne_compiler/', desc)
desc += "\n\n[E4.2 2026-07-09: paths rescoped post-extraction.]"
open(f"/tmp/bead-{'$id'}-new.txt", "w").write(desc)
EOF
  bd update "$id" --description "$(cat /tmp/bead-$id-new.txt)"
done
```

- [ ] **Step 6: Run tests + commit + PR**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e4_coverage_manifest_paths.py -v
# Expected: 2 passed

.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/ -q -m "not integration"
# Expected: baseline 1389 passed / 10 skipped preserved

git add openbb_platform/extensions/pine/openbb_pine/_coverage_manifest.py \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e4_coverage_manifest_paths.py \
        docs/  # if PRD updated
git commit -m "refactor(pine): coverage manifest + PRD post-extraction paths (bd-E4.2)

Per spec §6.E4:
- _coverage_manifest.py BUILTINS_IMPLEMENTED / FEATURES_IMPLEMENTED
  entries point at pyne_compiler.* (was openbb_pine.compiler.*)
- PRD §16.6 amendments to new module topology
- bd-qj7 + bd-7a8 DESCRIPTIONs rescoped
- Verifies bd-prime-retrievable pine-phase2-unfrozen-2026-07-09 memory

Baseline 1389 passed / 10 skipped preserved.
"
git push -u origin refactor/e4-2-coverage-manifest
gh pr create --base openbb_pine_support --head refactor/e4-2-coverage-manifest \
  --title "refactor(pine): coverage manifest + PRD post-extraction — E4.2 (bd-E4.2)"
```

**Phase 2B complete when:** E2.1-E4.2 all merged; 9 previously-frozen beads unblocked + rescoped; `pine-extraction-completed` memory recorded; full pine suite baseline preserved on both sides.

---

## Post-plan review checklist (before dispatching subagents)

- [ ] Spec coverage: §6.E2 (E2.1-E2.4), §6.E3 (E3.1-E3.5 including step 7 version rewrites), §6.E4 (E4.1-E4.2), §7 (filter-repo mechanics + §7.1 partial history), §8 (rollback tag), §13.5 (deprecation shims)
- [ ] All 11 tasks have TDD structure: failing test → verify fail → implement → verify pass → commit + PR
- [ ] filter-repo paths use post-E0 filenames (compiler_errors.py, executor_core.py, pynecore_bridge.py, telemetry.py) — matches ground truth
- [ ] bead 78w handled at both sites (SITE 1 dispatcher in E3.2; SITE 2 executor_core verified clean in E3.4)
- [ ] `compile_router.py` version-string rewrite explicitly called out in E3.4 (per spec §6.E3 step 7 / GAP #9)
- [ ] Deprecation shims cover compiler/, runtime/, and compiler_errors.py (spec §13.5)
- [ ] 5-commit spot-check in E2.4 includes ≥1 E0-split file per §12 / R3
- [ ] Freeze/unfreeze checklist (§12 R9) enforced in E4.1
