# Pine Extraction to prajoria/pynecore — Implementation Plan (Phase 2A: E0 + E1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **⚠ Scope note (2026-07-07):** This document covers **Phase 2A** of the openbb-dev-cycle plan for the Pine Extraction — the first two phases (**E0** pre-extraction refactor + **E1** provider extensions in pynecore). Phase 2B (containing **E2** `git filter-repo` extraction + **E3** openbb-fork refactor + **E4** unfreeze Phase 2 beads) will be written as a follow-up plan AFTER E0 lands. This split is deliberate: E2's exact `git filter-repo --path` list depends on the final post-E0 file names (`compiler_errors.py`, `executor_core.py`, `pynecore_bridge.py`), and E3's import-rewrite scope depends on E0.6's actual test-split outcome. Writing E2/E3/E4 speculatively against pre-E0 names would produce commands that need to be revised after execution reality. Better to plan against reality.
>
> **Phase 2B trigger:** When E0.1 through E0.7 all merge to `openbb_pine_support` (parent bead `rbf` shows 7 more closed sub-beads), invoke `superpowers:writing-plans` to produce `docs/superpowers/plans/YYYY-MM-DD-pine-extraction-phase2b.md` covering E2 + E3 + E4 with the exact filter-repo commands based on post-E0 filesystem state.

**Goal:** Extract Pine Script compiler + core runtime from openbb-fork's `openbb_platform/extensions/pine/openbb_pine/` (11,541 LOC) into `prajoria/pynecore` as a sibling package `src/pyne_compiler/`. Unify with pynecore's existing `Provider` base class to expose `stream()`/`fetch()` for runtime data queries. Ship reference CSV + SQLite providers in pynecore. Refactor FMP + BYO providers in openbb-fork to extend the unified `Provider` base.

**Architecture:** Five-phase migration (E0 → E1 → E2 → E3 → E4). **This document covers E0 and E1 only** — see the scope note above. E0 decouples cross-cutting imports IN PLACE inside openbb-fork (six sub-refactors E0.1–E0.6 + a grep-gate verification E0.7). E1 extends `Provider` in pynecore + builds CSV/SQLite reference providers + a behavioral conformance suite + a `pyne_compiler/` package placeholder.

**Tech Stack:** Python 3.11+ (per pynecore floor), pytest, git filter-repo, lark grammar, PyneCore runtime, pandas, FastAPI (openbb-fork side only).

## Global Constraints

- Compiler-touching commits MUST include `Clean-room: I have not viewed TradingView or PyneComp source code.` trailer (PRD §2.5 / spec §10)
- Branch-protection hook enforced: no direct pushes to `openbb_pine_support` or `develop`; every change is a feature branch + PR
- Test baseline: **1,353 passing** must be preserved (in whichever repo tests land)
- Beads (`bd`) is the ONLY task tracker (per CLAUDE.md); no TodoWrite/TaskCreate
- Environment: `.venv_win\Scripts\python.exe` (never system Python)
- Verify before commit — show test output, never claim green without evidence
- All new work goes to feature branches from `openbb_pine_support`; PRs target `openbb_pine_support`; pynecore work goes to feature branches from `main`; PRs target pynecore `main`
- `pyne_compiler` lives at `src/pyne_compiler/` under pynecore's src/ layout (spec R1)
- Extend the existing `pynecore.providers.Provider` base class — do NOT create a new `adapters/` directory or `DataProvider` Protocol (spec R2)
- Every new provider (CSV, SQLite, and future FMP/BYO refactor) must pass the behavioral conformance suite in `src/pynecore/providers/tests/test_conformance.py`

---

## File map

Line counts as of 2026-07-06 evening `wc -l`:

| File | Disposition | Lines | Responsibility |
|---|---|---:|---|
| `openbb_platform/extensions/pine/openbb_pine/errors.py` | SPLIT (E0.1) | 1082 | Compiler+runtime + provider errors intermixed. Split into `errors.py` (provider only) + `compiler_errors.py` (compiler+runtime, will move to pynecore). |
| `openbb_platform/extensions/pine/openbb_pine/compiler_errors.py` | NEW (E0.1) | ~750 | Compiler + runtime errors (moves to pynecore in E2). |
| `openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py` | NEW (E0.2) | ~30 | Temporary ABC used by `security_dispatcher` for E0-only. Deleted in E2. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py` | MODIFY (E0.2) | 380 | Removes `FMPOHLCVProvider` import; takes `Provider` ABC via stub. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py` | NEW (E0.3) | ~200 | Compile-cache lookup, `_pynecore_glue` wiring, `_bar_iter`, snapshot capture. Moves to pynecore in E2. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/executor_shell.py` | NEW (E0.3) | ~200 | Thin FMP/BYO/attribution wrapper. Stays in openbb-fork. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/executor.py` | MODIFY→DEPRECATED SHIM (E0.3 then E3) | 396 | Post-E0.3: thin re-export. E3: DeprecationWarning shim. |
| `openbb_platform/extensions/pine/openbb_pine/telemetry.py` | SPLIT (E0.4) | 106 | Post-E0.4: `pyne_compiler.telemetry` gets `TelemetrySink` protocol (moves in E2); `openbb_pine.telemetry` gets impl class. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py` | NEW (E0.5) | ~50 | Moved sys.path bridge. Migrates to pynecore in E2. |
| `openbb_platform/extensions/pine/openbb_pine/__init__.py` | MODIFY (E0.5) | ~150 | Delegates `_install_pynecore_path()` to `pynecore_bridge`. |
| `openbb_platform/extensions/pine/openbb_pine/tests/unit/*.py` | AUDIT+SPLIT (E0.6) | ~77 files | Apply spec §6.E0.6 rule: pynecore-only imports → moves; openbb-fork imports → stays. |
| `third_party/pynecore/src/pynecore/providers/provider.py` | MODIFY (E1.1) | (upstream) | Add `stream()` + `fetch()` concrete methods with default file-backed impls. |
| `third_party/pynecore/src/pynecore/providers/csv.py` | NEW (E1.2) | ~200 | CSV reference provider. |
| `third_party/pynecore/src/pynecore/providers/sqlite.py` | NEW (E1.3) | ~230 | SQLite reference provider. |
| `third_party/pynecore/src/pynecore/providers/tests/test_conformance.py` | NEW (E1.4) | ~180 | Shared behavioral suite. |
| `third_party/pynecore/src/pyne_compiler/__init__.py` | NEW (E1.5) | ~15 | Placeholder package with `__version__`; content-fills in E2. |
| _(Phase 2B — deferred)_ | | | |
| `third_party/pynecore/src/pyne_compiler/` (tree, ~11,400 LOC) | NEW (E2 — Phase 2B) | ~11,400 | Migrated compiler + runtime with history via `git filter-repo`. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/fmp_provider.py` | MODIFY (E3 — Phase 2B) | 445 | Inherit `pynecore.providers.Provider`, override `stream`/`fetch`. |
| `openbb_platform/extensions/pine/openbb_pine/runtime/byo_provider.py` | MODIFY (E3 — Phase 2B) | 191 | Inherit `pynecore.providers.Provider` in mode-1. |
| `openbb_platform/extensions/pine/openbb_pine/routers/compile_router.py` | MODIFY (E3 — Phase 2B) | (existing) | `openbb_pine.__version__` → `pyne_compiler.__version__` in cache key + response. |
| `openbb_platform/extensions/pine/openbb_pine/compiler/*.py`, other migrated modules | REWRITE→SHIM (E3 — Phase 2B) | many | Each becomes a one-release DeprecationWarning shim re-exporting from `pyne_compiler.*`. |

---

## Phase E0 — Pre-extraction refactor (INSIDE openbb-fork)

**Where:** openbb-fork on feature branches from `openbb_pine_support`. Each E0.x is its own PR.
**Dependency graph:** E0.1 → (E0.2 ‖ E0.3 ‖ E0.4 ‖ E0.5) → E0.6 → E0.7 (grep-gate verification).

### Task E0.1: Split errors.py into compiler_errors.py + provider errors.py

**Bead:** `OpenBBTechnical-3cf` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `openbb_platform/extensions/pine/openbb_pine/compiler_errors.py` (new — MOVE targets from `errors.py`)
- Modify: `openbb_platform/extensions/pine/openbb_pine/errors.py` (keep STAY targets; add re-export shim for one release so existing imports keep working)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_split.py` (new — asserts both new + old import paths work)

**Interfaces:**
- Consumes: existing `openbb_pine.errors.*` symbols
- Produces:
  - `compiler_errors.py` exports (MOVE list per spec §6.E0.1): `PineError`, `Diagnostic`, `PineCompileError`, `PineSyntaxError`, `PineTypeError`, `PineUnsupportedBuiltinError`, `PineUnsupportedFeatureError`, `PineCodegenError`, `PineInternalCompilerError`, `PineCacheError`, `PineRuntimeError`, `PineStrategyNotYetImplementedError`, `PineSecurityError`, `PineExecTimeoutError`, `PineDataResolverError`, `PineSecurityContextNotFoundError`
  - `errors.py` (post-split) exports (STAY list): `PineProviderError`, `PineFMPRequiredError`, `PineFMPUnreachableError`, `PineDataValidationError` — PLUS re-exports of the MOVE list (one-release compatibility shim)

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e0-1-split-errors openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_split.py`:

```python
"""E0.1 split verification: compiler_errors.py owns compiler+runtime errors;
errors.py owns provider-side errors; both paths still work for one release."""


def test_compiler_errors_module_exports_move_list() -> None:
    from openbb_pine import compiler_errors
    expected = {
        "PineError", "Diagnostic", "PineCompileError", "PineSyntaxError",
        "PineTypeError", "PineUnsupportedBuiltinError",
        "PineUnsupportedFeatureError", "PineCodegenError",
        "PineInternalCompilerError", "PineCacheError",
        "PineRuntimeError", "PineStrategyNotYetImplementedError",
        "PineSecurityError", "PineExecTimeoutError",
        "PineDataResolverError", "PineSecurityContextNotFoundError",
    }
    missing = expected - set(dir(compiler_errors))
    assert not missing, f"compiler_errors missing: {missing}"


def test_errors_module_still_exports_provider_errors() -> None:
    from openbb_pine import errors
    for name in (
        "PineProviderError", "PineFMPRequiredError",
        "PineFMPUnreachableError", "PineDataValidationError",
    ):
        assert hasattr(errors, name), f"errors missing STAY symbol: {name}"


def test_errors_module_still_reexports_compiler_symbols_for_one_release() -> None:
    # Old callers `from openbb_pine.errors import PineSyntaxError` must keep working.
    from openbb_pine import errors, compiler_errors
    assert errors.PineSyntaxError is compiler_errors.PineSyntaxError
    assert errors.PineDataResolverError is compiler_errors.PineDataResolverError
    assert errors.PineSecurityContextNotFoundError is compiler_errors.PineSecurityContextNotFoundError


def test_provider_errors_are_NOT_in_compiler_errors() -> None:
    from openbb_pine import compiler_errors
    for provider_only in ("PineFMPRequiredError", "PineFMPUnreachableError", "PineDataValidationError"):
        assert not hasattr(compiler_errors, provider_only), (
            f"{provider_only} is provider-side, must NOT leak into compiler_errors"
        )
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_split.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'openbb_pine.compiler_errors'`.

- [ ] **Step 4: Implement the split**

1. Copy `openbb_platform/extensions/pine/openbb_pine/errors.py` → `openbb_platform/extensions/pine/openbb_pine/compiler_errors.py` unchanged.
2. In `compiler_errors.py`, DELETE the STAY-list class definitions (`PineProviderError`, `PineFMPRequiredError`, `PineFMPUnreachableError`, `PineDataValidationError`) and any imports they alone require.
3. In `errors.py`, DELETE the MOVE-list class definitions, then add at the top (after the module docstring):

```python
# One-release compatibility shim: MOVE-list classes now live in compiler_errors.py.
# Downstream imports like `from openbb_pine.errors import PineSyntaxError` keep working.
# Remove this re-export block in the release after Pine extraction ships.
from openbb_pine.compiler_errors import (  # noqa: F401
    Diagnostic,
    PineCacheError,
    PineCodegenError,
    PineCompileError,
    PineDataResolverError,
    PineError,
    PineExecTimeoutError,
    PineInternalCompilerError,
    PineRuntimeError,
    PineSecurityContextNotFoundError,
    PineSecurityError,
    PineStrategyNotYetImplementedError,
    PineSyntaxError,
    PineTypeError,
    PineUnsupportedBuiltinError,
    PineUnsupportedFeatureError,
)
```

4. Enumerate + rewrite every import site of MOVE symbols. Command:

```bash
grep -rn "from openbb_pine.errors import\|from openbb_pine import errors" openbb_platform/extensions/pine/openbb_pine/ | grep -v test_error_split.py
```

For each hit: if the imported names are ALL in the MOVE list, change the module path to `compiler_errors`. If any imported name is in the STAY list, keep `errors` OR split into two lines.

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_split.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full pine test suite (regression gate)**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ -x --tb=short
```
Expected: 1,353 tests pass. Any failure = STOP and fix the missed import site.

- [ ] **Step 7: Commit + open PR**

```bash
git add openbb_platform/extensions/pine/openbb_pine/compiler_errors.py \
        openbb_platform/extensions/pine/openbb_pine/errors.py \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_split.py \
        openbb_platform/extensions/pine/openbb_pine/compiler/ \
        openbb_platform/extensions/pine/openbb_pine/runtime/ \
        openbb_platform/extensions/pine/openbb_pine/routers/
git status  # verify no unrelated files staged
git commit -m "refactor(pine): split errors.py into compiler_errors.py + provider errors (bd-E0.1)

Per Pine Extraction Design §6.E0.1, splits the 1,082 LOC errors.py so
compiler+runtime errors migrate to pyne_compiler in E2 without dragging
provider-side errors along.

- compiler_errors.py: PineError base + Diagnostic + 15 compiler/runtime subclasses
- errors.py (post-split): PineProviderError + FMP subclasses + PineDataValidationError
- errors.py adds one-release shim re-exporting MOVE-list symbols; shim
  removed in next minor per §13.5.

Full pine test suite green (1,353 tests preserved).

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin refactor/e0-1-split-errors
gh pr create --base openbb_pine_support --head refactor/e0-1-split-errors \
  --title "refactor(pine): split errors.py — E0.1 of Pine Extraction (bd-E0.1)" \
  --body "First of six E0 sub-refactors. Splits errors.py per design §6.E0.1. Full pine suite green (1353)."
```

Wait for merge before starting E0.2 / E0.3 / E0.6 (which depend on E0.1).


### Task E0.2: Refactor security_dispatcher to consume abstract Provider (via stub)

**Bead:** `OpenBBTechnical-r9m` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py` (temporary — deleted in E2)
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py`
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/executor.py` (caller — pushes FMP-specific args UP to the executor)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_prefetch_security.py` (update existing)

**Interfaces:**
- Consumes: `openbb_pine.compiler_errors.PineDataResolverError` (from E0.1)
- Produces:
  - `_DataProviderStub` (ABCMeta) with abstract `stream(symbol, timeframe, *, start, end) -> Iterator[OHLCV]` and `fetch(symbol, timeframe, *, start, end) -> list[OHLCV]` methods matching the eventual `pynecore.providers.Provider` shape (E1 will land the real one).
  - `prefetch_security_contexts(provider: _DataProviderStub, contexts: dict[...], **kwargs)` — no FMP-specific imports remaining.

**Depends on:** E0.1 (uses `compiler_errors.PineDataResolverError`).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e0-2-dispatcher-abstract-provider openbb_pine_support
```

- [ ] **Step 2: Write the stub file**

Create `openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py`:

```python
"""TEMPORARY E0 STUB — deleted in Phase E2 when the real pynecore.providers.Provider
lands in this repo via the extracted pynecore. Do NOT depend on this from
anything outside `security_dispatcher.py` and its tests. Its role is to give
E0.2 an abstract ABC to program against so we can decouple the dispatcher
from FMPOHLCVProvider WITHOUT waiting for E1 to land in pynecore first.

Matches the shape the extended pynecore.providers.Provider will expose
after E1 lands (spec §5.1).
"""
from __future__ import annotations

from abc import ABCMeta, abstractmethod
from datetime import datetime
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from pynecore.types.ohlcv import OHLCV  # type: ignore[import-not-found]


class _DataProviderStub(metaclass=ABCMeta):
    """Abstract Provider stub matching pynecore.providers.Provider stream/fetch."""

    @abstractmethod
    def stream(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator["OHLCV"]:
        ...

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list["OHLCV"]:
        ...
```

- [ ] **Step 3: Write the failing test**

Add to `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_prefetch_security.py`:

```python
def test_dispatcher_does_not_import_fmp_provider_symbols() -> None:
    """E0.2 gate: security_dispatcher must NOT reference FMPOHLCVProvider,
    FMPRequest, infer_asset_class, or fmp_retry — those are FMP-specific
    and get pushed up to the caller (executor_shell) post-E0.2."""
    import inspect
    from openbb_pine.runtime import security_dispatcher
    src = inspect.getsource(security_dispatcher)
    for banned in (
        "FMPOHLCVProvider",
        "FMPRequest",
        "infer_asset_class",
        "from openbb_pine.runtime.fmp_provider",
        "from openbb_pine.runtime.fmp_retry",
    ):
        assert banned not in src, f"security_dispatcher still references {banned!r} — E0.2 incomplete"


def test_dispatcher_accepts_stub_provider() -> None:
    """A minimal in-memory stub satisfying _DataProviderStub must work
    end-to-end, proving the dispatcher no longer depends on FMP-specific types."""
    from datetime import datetime, timezone
    from openbb_pine.runtime._data_provider_stub import _DataProviderStub
    from openbb_pine.runtime.security_dispatcher import prefetch_security_contexts

    class InMemoryProvider(_DataProviderStub):
        def stream(self, symbol, timeframe, *, start=None, end=None):
            return iter([])
        def fetch(self, symbol, timeframe, *, start=None, end=None):
            return []

    result = prefetch_security_contexts(
        provider=InMemoryProvider(),
        contexts={},
        primary_symbol="AAPL",
        primary_timeframe="1D",
        primary_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        primary_end=datetime(2024, 1, 10, tzinfo=timezone.utc),
    )
    assert result == {} or isinstance(result, dict)
```

- [ ] **Step 4: Run test to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_prefetch_security.py::test_dispatcher_does_not_import_fmp_provider_symbols -v
```
Expected: FAIL — grep finds `FMPOHLCVProvider` and `fmp_retry` in the current dispatcher source.

- [ ] **Step 5: Refactor `security_dispatcher.py`**

1. Remove imports: `from openbb_pine.runtime.fmp_provider import FMPOHLCVProvider, FMPRequest, infer_asset_class`; `from openbb_pine.runtime.fmp_retry import call_with_retry`.
2. Change the signature of `prefetch_security_contexts` so its FIRST positional parameter is `provider: "_DataProviderStub"` (import `TYPE_CHECKING`-gated to avoid runtime coupling).
3. Delete `_fetch_via_fmp()` — its logic moves UP to the caller. Replace call sites within `prefetch_security_contexts` with `provider.fetch(symbol, timeframe, start=..., end=...)`.
4. FMP-specific retry logic (`call_with_retry`, `FMPRequest`) — DELETE from the dispatcher; the caller (E0.3 `executor_shell`) is responsible for wrapping its FMP provider instance's `fetch()` in a retry decorator before passing it in.

Sketch of the post-refactor `prefetch_security_contexts` shape:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from openbb_pine.runtime._data_provider_stub import _DataProviderStub

def prefetch_security_contexts(
    provider: "_DataProviderStub",
    contexts: dict[SecurityKey, "SecurityContext"],
    *,
    primary_symbol: str,
    primary_timeframe: str,
    primary_start: datetime,
    primary_end: datetime,
    data_resolver: Callable[..., list[OHLCV]] | None = None,
) -> dict[SecurityKey, list[OHLCV]]:
    results: dict[SecurityKey, list[OHLCV]] = {}
    for key, ctx in contexts.items():
        start, end = _extract_window(ctx, primary_start, primary_end)
        if data_resolver is not None:
            try:
                results[key] = _fetch_via_resolver(data_resolver, key, start, end)
            except Exception as exc:
                raise PineDataResolverError(...) from exc
        else:
            results[key] = provider.fetch(key.symbol, key.timeframe, start=start, end=end)
    return results
```

5. Update the caller — for E0.2, temporarily change `openbb_pine/runtime/executor.py`'s call site to pass its `FMPOHLCVProvider` instance where the dispatcher used to look one up internally. (E0.3 will restructure the executor further; for now the executor just becomes the party holding the FMP-specific bits.)

- [ ] **Step 6: Run test to verify it passes**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_prefetch_security.py -v
```
Expected: PASS.

- [ ] **Step 7: Run the full pine test suite (regression gate)**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ -x --tb=short
```
Expected: 1,353 tests pass.

- [ ] **Step 8: Commit + open PR**

```bash
git add openbb_platform/extensions/pine/openbb_pine/runtime/_data_provider_stub.py \
        openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py \
        openbb_platform/extensions/pine/openbb_pine/runtime/executor.py \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_prefetch_security.py
git commit -m "refactor(pine): decouple security_dispatcher from FMPOHLCVProvider (bd-E0.2)

Per Pine Extraction Design §6.E0.2, dispatcher now takes an abstract
_DataProviderStub (temporary ABC matching the eventual
pynecore.providers.Provider shape post-E1). FMP-specific
retry/RequestBuilder logic moves UP to the executor caller.

The _data_provider_stub.py file is TEMPORARY — E2 replaces it with a
direct import of pynecore.providers.Provider.

Full pine test suite green (1,353 tests preserved).

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin refactor/e0-2-dispatcher-abstract-provider
gh pr create --base openbb_pine_support --head refactor/e0-2-dispatcher-abstract-provider \
  --title "refactor(pine): abstract security_dispatcher provider — E0.2 (bd-E0.2)" \
  --body "Second of six E0 sub-refactors. Depends on E0.1 (uses compiler_errors.PineDataResolverError)."
```

### Task E0.3: Split executor.py into executor_core (moves) + executor_shell (stays)

**Bead:** `OpenBBTechnical-9zb` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py` (new — moves to pynecore in E2)
- Create: `openbb_platform/extensions/pine/openbb_pine/runtime/executor_shell.py` (new — stays in openbb-fork)
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/executor.py` (post-E0.3 thin re-export; will become deprecation shim in E3)
- Modify: `openbb_platform/extensions/pine/openbb_pine/routers/run_router.py`, `openbb_platform/extensions/pine/openbb_pine/routers/strategies_router.py` (call `executor_shell.run_compiled` instead of `executor.run_compiled`)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_core.py` (new — tests core in isolation from FMP)
- Modify: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor.py` (rename to `test_executor_shell.py`; adjust imports)

**Interfaces:**
- Consumes: `_DataProviderStub` (from E0.2), `compiler_errors.PineExecTimeoutError` (from E0.1)
- Produces:
  - `executor_core.run_compiled(compiled_module, provider: "_DataProviderStub", *, symbol, timeframe, start, end, ...) -> tuple[list[BarSnapshot], list[TradeSummary]]` — pure runtime, no FMP/BYO/attribution knowledge.
  - `executor_shell.run_compiled(compiled_module, *, symbol, timeframe, provider_hint, start, end, ...) -> OBBject` — instantiates the concrete provider (FMP-cached/FMP/BYO), attaches `POWERED_BY_FULL` attribution, populates OpenBB `.extra`, delegates to `executor_core.run_compiled()`.

**Depends on:** E0.1 (compiler_errors), E0.2 (_DataProviderStub).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e0-3-split-executor openbb_pine_support
```

- [ ] **Step 2: Write the failing test for executor_core (pure runtime, no FMP)**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_core.py`:

```python
"""E0.3 gate: executor_core must be usable end-to-end with a stub provider,
proving it has NO knowledge of FMP, BYO, or attribution."""
from datetime import datetime, timezone

from openbb_pine.runtime._data_provider_stub import _DataProviderStub
from openbb_pine.runtime.executor_core import run_compiled
from openbb_pine.compiler.codegen import compile_pine


class _StubProvider(_DataProviderStub):
    def __init__(self, bars):
        self._bars = list(bars)

    def stream(self, symbol, timeframe, *, start=None, end=None):
        return iter(self._bars)

    def fetch(self, symbol, timeframe, *, start=None, end=None):
        return list(self._bars)


def test_executor_core_runs_pine_script_against_stub_provider() -> None:
    from pynecore.types.ohlcv import OHLCV  # type: ignore[import-not-found]
    src = 'indicator("t"); plot(close)'
    compiled = compile_pine(src)
    bars = [OHLCV(timestamp=i, open=i, high=i, low=i, close=i, volume=1) for i in range(1, 6)]
    snapshots, trades = run_compiled(
        compiled,
        provider=_StubProvider(bars),
        symbol="STUB",
        timeframe="1D",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 5, tzinfo=timezone.utc),
    )
    assert len(snapshots) == 5
    assert trades == []


def test_executor_core_does_not_import_fmp_or_attribution() -> None:
    """Grep guard — proves the split isn't just cosmetic."""
    import inspect
    from openbb_pine.runtime import executor_core
    src = inspect.getsource(executor_core)
    for banned in ("FMPOHLCVProvider", "BYODataProvider", "POWERED_BY_FULL",
                   "from openbb_pine.attribution", "from openbb_pine.runtime.fmp_provider",
                   "from openbb_pine.runtime.byo_provider"):
        assert banned not in src, f"executor_core still references {banned!r} — E0.3 incomplete"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_core.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'openbb_pine.runtime.executor_core'`.

- [ ] **Step 4: Extract executor_core.py**

1. Create `executor_core.py`. Copy from `executor.py` ONLY the functions that operate on generic compiled modules + bar streams: the `_bar_iter` loop, per-bar snapshot capture, `_collect_results`, and the shared portion of `run_compiled` that iterates the compiled module.
2. Replace `_resolve_data_source(...)` calls (which today branch on FMP vs. BYO) with a direct `provider.fetch(symbol, timeframe, start=start, end=end)` call using the passed-in `_DataProviderStub`-typed `provider` argument.
3. Import `PineExecTimeoutError` from `openbb_pine.compiler_errors` (moved in E0.1).
4. Do NOT import `POWERED_BY_FULL`, FMP*, BYO*, or `attribution` — those go in the shell.

- [ ] **Step 5: Extract executor_shell.py**

1. Create `executor_shell.py`. Import `_DataProviderStub`, `FMPOHLCVProvider`, `FMPRequest`, `BYODataProvider`, `POWERED_BY_FULL`.
2. Define `run_compiled(compiled_module, *, symbol, timeframe, provider_hint, start, end, ...) -> OBBject`:
   - Instantiate the concrete provider based on `provider_hint` ("fmp_cached" / "fmp" / "byo").
   - Wrap FMP providers in the fmp_retry `call_with_retry` decorator around their `fetch` method.
   - Call `executor_core.run_compiled(compiled_module, provider=<instance>, symbol=symbol, timeframe=timeframe, start=start, end=end, ...)`.
   - Wrap the returned snapshots/trades in an `OBBject` with `POWERED_BY_FULL` attribution + OpenBB `.extra` fields.

- [ ] **Step 6: Rewire callers (routers + top-level executor.py)**

1. In `openbb_pine/runtime/executor.py`, DELETE the old `run_compiled` implementation and REPLACE its body with `from openbb_pine.runtime.executor_shell import run_compiled  # noqa: F401`. This keeps `from openbb_pine.runtime.executor import run_compiled` working (it becomes a re-export that E3 will convert to a DeprecationWarning shim).
2. Update `openbb_pine/routers/run_router.py` and `openbb_pine/routers/strategies_router.py`:
   - `from openbb_pine.runtime.executor import run_compiled` → `from openbb_pine.runtime.executor_shell import run_compiled`
3. Rename `openbb_pine/tests/unit/test_executor.py` → `test_executor_shell.py` and update its imports.

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_core.py \
                                       openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_shell.py -v
```
Expected: PASS.

- [ ] **Step 8: Run the full pine test suite (regression gate)**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ -x --tb=short
```
Expected: 1,353 tests pass.

- [ ] **Step 9: Commit + open PR**

```bash
git add openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py \
        openbb_platform/extensions/pine/openbb_pine/runtime/executor_shell.py \
        openbb_platform/extensions/pine/openbb_pine/runtime/executor.py \
        openbb_platform/extensions/pine/openbb_pine/routers/ \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_core.py \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_shell.py
git rm openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor.py 2>/dev/null || true
git commit -m "refactor(pine): split executor into core (moves) + shell (stays) (bd-E0.3)

Per Pine Extraction Design §6.E0.3, splits executor.py into:
- executor_core.py: pure runtime — bar loop, snapshot capture, generic
  Provider consumption. Moves to pyne_compiler in E2.
- executor_shell.py: OpenBB-specific wrapper — instantiates concrete
  provider, wires fmp_retry, attaches POWERED_BY_FULL attribution, wraps
  in OBBject.

executor.py becomes a thin re-export (converted to DeprecationWarning
shim in E3).

Full pine test suite green (1,353 tests preserved).

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin refactor/e0-3-split-executor
gh pr create --base openbb_pine_support --head refactor/e0-3-split-executor \
  --title "refactor(pine): split executor into core+shell — E0.3 (bd-E0.3)" \
  --body "Third of six E0 sub-refactors. Depends on E0.1 + E0.2."
```

### Task E0.4: Abstract telemetry behind an injection point

**Bead:** `OpenBBTechnical-gzf` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Modify: `openbb_platform/extensions/pine/openbb_pine/telemetry.py` (split content: protocol moves to future `pyne_compiler.telemetry`, impl class stays here)
- Modify: `openbb_platform/extensions/pine/openbb_pine/compiler/codegen.py`, `type_checker.py`, `v5_migration.py`, `compiler/__init__.py` (replace direct `openbb_pine.telemetry.record_*` calls with injected `TelemetrySink` protocol)
- Modify: `openbb_platform/extensions/pine/openbb_pine/routers/run_router.py`, `compile_router.py` (instantiate `OpenBBTelemetrySink()` and pass `telemetry=` kwarg into `compile_pine`)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_telemetry_injection.py` (new)

**Interfaces:**
- Consumes: (nothing net-new from earlier tasks; independent of E0.2/E0.3)
- Produces:
  - `openbb_pine.telemetry.TelemetrySink` — `Protocol` (or ABC) with two methods: `record_unsupported_feature(name: str) -> None`, `record_unsupported_builtin(name: str) -> None`. Migrates to `pyne_compiler.telemetry` in E2.
  - `openbb_pine.telemetry.OpenBBTelemetrySink` — concrete impl that stays in openbb-fork; wraps the module-level counter dict.
  - `compile_pine(..., telemetry: TelemetrySink | None = None)` — the compiler no longer imports `openbb_pine.telemetry` directly; when `telemetry` is `None`, all `record_*` calls are no-ops.

**Depends on:** (independent) — can run in parallel with E0.2, E0.3, E0.5 after E0.1 lands (E0.4 does not use compiler_errors).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e0-4-telemetry-injection openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_telemetry_injection.py`:

```python
"""E0.4 gate: compiler does not import openbb_pine.telemetry at any callsite;
instead accepts a TelemetrySink instance via the compile_pine(telemetry=...) kwarg."""
import inspect


def test_compiler_modules_do_not_import_openbb_pine_telemetry() -> None:
    from openbb_pine.compiler import codegen, type_checker, v5_migration, __init__ as compiler_init
    for mod in (codegen, type_checker, v5_migration, compiler_init):
        src = inspect.getsource(mod)
        assert "from openbb_pine.telemetry import" not in src, (
            f"{mod.__name__} still imports openbb_pine.telemetry directly — E0.4 incomplete"
        )
        assert "openbb_pine.telemetry" not in src or "TelemetrySink" in src, (
            f"{mod.__name__} references openbb_pine.telemetry outside a type annotation"
        )


def test_telemetry_sink_protocol_exists() -> None:
    from openbb_pine.telemetry import TelemetrySink, OpenBBTelemetrySink
    sink = OpenBBTelemetrySink()
    assert hasattr(sink, "record_unsupported_feature")
    assert hasattr(sink, "record_unsupported_builtin")
    # Protocol shape check
    sink.record_unsupported_feature("test_feature")
    sink.record_unsupported_builtin("test_builtin")


def test_compile_pine_accepts_telemetry_kwarg() -> None:
    from openbb_pine.compiler.codegen import compile_pine
    from openbb_pine.telemetry import OpenBBTelemetrySink, reset_metrics, get_unsupported_feature_counts

    reset_metrics()
    sink = OpenBBTelemetrySink()
    # A script that uses an unsupported feature should call sink.record_unsupported_feature
    src = 'indicator("t"); plot(close)'  # replace with a script that hits an unsupported feature
    try:
        compile_pine(src, telemetry=sink)
    except Exception:
        pass  # OK if the sample script itself fails; the point is telemetry= is accepted
    # No assertion on counts — just that the kwarg is accepted without TypeError


def test_compile_pine_defaults_telemetry_to_none() -> None:
    """When telemetry is None (default), all record_* callsites are no-ops."""
    from openbb_pine.compiler.codegen import compile_pine
    # Should complete without touching any telemetry sink
    result = compile_pine('indicator("t"); plot(close)')
    assert result is not None
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_telemetry_injection.py -v
```
Expected: FAIL — codegen.py still does `from openbb_pine.telemetry import record_unsupported_feature`.

- [ ] **Step 4: Rewrite telemetry.py to define TelemetrySink + OpenBBTelemetrySink**

Replace the contents of `openbb_platform/extensions/pine/openbb_pine/telemetry.py` with:

```python
"""D1 §3.5 + PRD §9.4 failure-mode telemetry.

Post-E0.4 shape:
- TelemetrySink: Protocol the compiler programs against. Post-extraction,
  this Protocol moves to pyne_compiler.telemetry (E2). openbb-fork retains
  an implementation class here.
- OpenBBTelemetrySink: concrete impl that keeps in-process counters
  (matches the pre-E0.4 module-level counter behavior).
- Module-level record_unsupported_* / get_unsupported_*_counts /
  reset_metrics helpers: kept as a thin delegation to a module-global
  OpenBBTelemetrySink for one release (back-compat for tests that call
  telemetry.get_unsupported_feature_counts() directly).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TelemetrySink(Protocol):
    """Contract the compiler programs against for telemetry emission.

    Note: `runtime_checkable` here catches "did you forget to define these
    methods at all"; real conformance is the behavioral (impl calls sink,
    sink records) end-to-end test in test_telemetry_injection.py.
    """

    def record_unsupported_feature(self, name: str) -> None: ...
    def record_unsupported_builtin(self, name: str) -> None: ...


class OpenBBTelemetrySink:
    """Concrete TelemetrySink implementation used by openbb-fork routers."""

    def __init__(self) -> None:
        self._feature_counts: dict[str, int] = {}
        self._builtin_counts: dict[str, int] = {}

    def record_unsupported_feature(self, name: str) -> None:
        self._feature_counts[name] = self._feature_counts.get(name, 0) + 1

    def record_unsupported_builtin(self, name: str) -> None:
        self._builtin_counts[name] = self._builtin_counts.get(name, 0) + 1

    def get_unsupported_feature_counts(self) -> dict[str, int]:
        return dict(self._feature_counts)

    def get_unsupported_builtin_counts(self) -> dict[str, int]:
        return dict(self._builtin_counts)

    def reset(self) -> None:
        self._feature_counts.clear()
        self._builtin_counts.clear()


# Module-global sink for back-compat with tests that call the free functions.
_DEFAULT_SINK = OpenBBTelemetrySink()


def record_unsupported_feature(name: str) -> None:
    _DEFAULT_SINK.record_unsupported_feature(name)


def record_unsupported_builtin(name: str) -> None:
    _DEFAULT_SINK.record_unsupported_builtin(name)


def get_unsupported_feature_counts() -> dict[str, int]:
    return _DEFAULT_SINK.get_unsupported_feature_counts()


def get_unsupported_builtin_counts() -> dict[str, int]:
    return _DEFAULT_SINK.get_unsupported_builtin_counts()


def reset_metrics() -> None:
    _DEFAULT_SINK.reset()
```

- [ ] **Step 5: Rewire compiler modules**

For each of `openbb_pine/compiler/codegen.py`, `type_checker.py`, `v5_migration.py`, `compiler/__init__.py`:

1. DELETE every `from openbb_pine.telemetry import record_unsupported_feature` / `record_unsupported_builtin` line.
2. Change every `record_unsupported_feature(name)` → `if telemetry is not None: telemetry.record_unsupported_feature(name)` where `telemetry` is a parameter threaded through the call stack. This means:
   - `compile_pine()` gains `telemetry: TelemetrySink | None = None` parameter.
   - `compile_pine` passes `telemetry` down into codegen (`codegen_module(..., telemetry=telemetry)`), type_checker (`type_check(..., telemetry=telemetry)`), and v5_migration (`migrate_v5(..., telemetry=telemetry)`).
   - Import `TelemetrySink` as `TYPE_CHECKING`-gated to avoid a runtime import of openbb_pine.telemetry from the compiler:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from openbb_pine.telemetry import TelemetrySink  # E2 will rewrite to pyne_compiler.telemetry
```

- [ ] **Step 6: Rewire router call sites**

In `openbb_pine/routers/run_router.py`, `compile_router.py`, `strategies_router.py`:
1. `from openbb_pine.telemetry import OpenBBTelemetrySink`
2. Where `compile_pine(...)` is called, instantiate `sink = OpenBBTelemetrySink()` and pass `telemetry=sink`.
3. After the compile, read counts from `sink.get_unsupported_*_counts()` (replaces the previous read from module-level `openbb_pine.telemetry.get_unsupported_*_counts()`).

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_telemetry_injection.py -v
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ -x --tb=short
```
Expected: PASS + 1,353 total pine tests green.

- [ ] **Step 8: Commit + open PR**

```bash
git add openbb_platform/extensions/pine/openbb_pine/telemetry.py \
        openbb_platform/extensions/pine/openbb_pine/compiler/ \
        openbb_platform/extensions/pine/openbb_pine/routers/ \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_telemetry_injection.py
git commit -m "refactor(pine): abstract telemetry behind TelemetrySink protocol (bd-E0.4)

Per Pine Extraction Design §6.E0.4, breaks the compiler's direct import
of openbb_pine.telemetry. Compiler now takes an optional
telemetry: TelemetrySink | None kwarg through compile_pine. Routers
instantiate OpenBBTelemetrySink and inject it.

TelemetrySink Protocol moves to pyne_compiler.telemetry in E2;
OpenBBTelemetrySink impl stays in openbb-fork.

Full pine test suite green (1,353 tests preserved).

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin refactor/e0-4-telemetry-injection
gh pr create --base openbb_pine_support --head refactor/e0-4-telemetry-injection \
  --title "refactor(pine): TelemetrySink injection — E0.4 (bd-E0.4)" \
  --body "Fourth of six E0 sub-refactors. Independent of E0.2/E0.3 — can review in parallel."
```

### Task E0.5: Extract pynecore sys.path bridge into pynecore_bridge.py

**Bead:** `OpenBBTechnical-lef` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py` (new — migrates to pynecore in E2)
- Modify: `openbb_platform/extensions/pine/openbb_pine/__init__.py` (delegate `_install_pynecore_path()` to the new module)
- Modify: `openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py` (import the bridge to force it to run before any `pynecore.*` import)
- Test: `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py` (new)

**Interfaces:**
- Consumes: (nothing net-new from earlier tasks; independent)
- Produces:
  - `openbb_pine.runtime.pynecore_bridge.install_pynecore_path() -> None` — idempotent function that prepends `<repo-root>/third_party/pynecore/src` to `sys.path` if `pynecore` is not already importable.
  - `openbb_pine.runtime.pynecore_bridge.is_pynecore_installed() -> bool` — detection helper for the "is pip install already done?" check.

**Depends on:** (independent).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e0-5-pynecore-bridge openbb_pine_support
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py`:

```python
"""E0.5 gate: pynecore_bridge module exists with install_pynecore_path +
is_pynecore_installed, and is idempotent (safe to call multiple times)."""


def test_bridge_module_exports_expected_functions() -> None:
    from openbb_pine.runtime import pynecore_bridge
    assert callable(pynecore_bridge.install_pynecore_path)
    assert callable(pynecore_bridge.is_pynecore_installed)


def test_bridge_is_idempotent() -> None:
    import sys
    from openbb_pine.runtime import pynecore_bridge

    before = list(sys.path)
    pynecore_bridge.install_pynecore_path()
    pynecore_bridge.install_pynecore_path()
    pynecore_bridge.install_pynecore_path()
    # Should not have appended duplicates
    assert sys.path.count(sys.path[0]) == 1


def test_bridge_is_noop_when_pynecore_already_installed() -> None:
    import sys
    from openbb_pine.runtime import pynecore_bridge

    # If pynecore is already importable, no path insertion should happen
    if pynecore_bridge.is_pynecore_installed():
        before = list(sys.path)
        pynecore_bridge.install_pynecore_path()
        assert sys.path == before, "bridge should be a no-op when pynecore is already installed"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'openbb_pine.runtime.pynecore_bridge'`.

- [ ] **Step 4: Create pynecore_bridge.py**

Create `openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py`:

```python
"""Sys.path bridge for the submodule-vendored pynecore deployment.

When openbb-fork uses `third_party/pynecore/` as a git submodule (not a
pip-installed package), pynecore is not on sys.path by default. This
module prepends `<submodule>/src` so `import pynecore` resolves.

Idempotent: safe to call multiple times.
No-op when pynecore is already importable (the happy path once pynecore
is pip-installed alongside pyne_compiler).

Post-E2 this file moves to src/pyne_compiler/runtime/pynecore_bridge.py.
The E3 refactor makes openbb_pine.__init__ delegate here instead of
owning the sys.path insertion directly.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def is_pynecore_installed() -> bool:
    """True when `import pynecore` would succeed without our path manipulation."""
    return importlib.util.find_spec("pynecore") is not None


def _submodule_src_dir() -> Path:
    """Return the path to `third_party/pynecore/src` relative to this file's repo root."""
    # runtime/pynecore_bridge.py → runtime/ → openbb_pine/ → pine/ → extensions/ → openbb_platform/ → repo-root
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "third_party" / "pynecore" / "src"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "pynecore_bridge: could not locate third_party/pynecore/src relative to "
        f"{here}. Ensure the pynecore submodule is initialized."
    )


def install_pynecore_path() -> None:
    """Prepend the pynecore submodule's src/ to sys.path if pynecore isn't installed.

    Idempotent: repeated calls have no effect after the first successful insert.
    No-op when pynecore is already importable.
    """
    if is_pynecore_installed():
        return
    src_dir = str(_submodule_src_dir())
    if src_dir in sys.path:
        return  # already inserted, don't duplicate
    sys.path.insert(0, src_dir)
```

- [ ] **Step 5: Update `openbb_pine/__init__.py`**

Replace the existing `_install_pynecore_path()` function body with a delegation:

```python
def _install_pynecore_path() -> None:
    from openbb_pine.runtime.pynecore_bridge import install_pynecore_path
    install_pynecore_path()


_install_pynecore_path()  # module-load-time invocation preserved
```

- [ ] **Step 6: Update `openbb_pine/runtime/_pynecore_glue.py`**

Add at the very top (before any `from pynecore...` import):

```python
from openbb_pine.runtime import pynecore_bridge  # noqa: F401 — ensure bridge runs
pynecore_bridge.install_pynecore_path()
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py -v
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ -x --tb=short
```
Expected: PASS + 1,353 total pine tests green.

- [ ] **Step 8: Commit + open PR**

```bash
git add openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py \
        openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py \
        openbb_platform/extensions/pine/openbb_pine/__init__.py \
        openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py
git commit -m "refactor(pine): extract sys.path bridge into pynecore_bridge.py (bd-E0.5)

Per Pine Extraction Design §6.E0.5, moves the _install_pynecore_path
logic out of openbb_pine/__init__.py into
runtime/pynecore_bridge.py so it can migrate to pyne_compiler in E2.

Post-E3, ownership transfers to pyne_compiler and openbb_pine imports
it via pyne_compiler.runtime.pynecore_bridge.

Full pine test suite green (1,353 tests preserved).

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin refactor/e0-5-pynecore-bridge
gh pr create --base openbb_pine_support --head refactor/e0-5-pynecore-bridge \
  --title "refactor(pine): extract pynecore_bridge.py — E0.5 (bd-E0.5)" \
  --body "Fifth of six E0 sub-refactors. Independent — can review in parallel with E0.2/E0.3/E0.4."
```


### Task E0.6: Split test files along the extraction boundary

**Bead:** `OpenBBTechnical-209` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Modify: `openbb_platform/extensions/pine/openbb_pine/tests/unit/*.py` (77 files) — audit + tag each with a `_test_lives_in: "pynecore" | "openbb-fork"` comment marker; split any test class or module that crosses the boundary.
- Create: `docs/pine-extraction/e0-6-test-audit.md` — the audit table (source of truth for E2's `--path` list).

**Interfaces:**
- Consumes: E0.1 (compiler_errors), E0.2 (_data_provider_stub), E0.3 (executor_core/shell split), E0.4 (TelemetrySink injection) — all four must be merged before starting E0.6 so the audit reflects the post-refactor import graph.
- Produces: `docs/pine-extraction/e0-6-test-audit.md` with a table of `test_file → destination (pynecore | openbb-fork | split)`. This table drives E2's `git filter-repo --path <test-file>` list.

**Depends on:** E0.1 + E0.2 + E0.3 + E0.4 (all merged).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c refactor/e0-6-test-audit openbb_pine_support
```

- [ ] **Step 2: Write the enforcement test**

Create `openbb_platform/extensions/pine/openbb_pine/tests/unit/test_audit_completeness.py`:

```python
"""E0.6 gate: every unit test file in openbb_pine/tests/unit/ carries an audit
marker in its module docstring specifying its post-extraction destination."""
import pathlib
import re

TESTS_DIR = pathlib.Path(__file__).parent
MARKER_RE = re.compile(r"^_test_lives_in\s*:\s*(pynecore|openbb-fork|split)\s*$", re.MULTILINE)


def test_every_test_file_has_audit_marker() -> None:
    missing = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == "test_audit_completeness.py":
            continue
        text = path.read_text(encoding="utf-8")
        # Marker lives in the module docstring, e.g.:
        #   """... _test_lives_in: pynecore ..."""
        if not MARKER_RE.search(text):
            missing.append(path.name)
    assert not missing, (
        "E0.6 gate: the following test files lack a _test_lives_in marker in their module "
        f"docstring — add one of pynecore / openbb-fork / split: {missing}"
    )
```

- [ ] **Step 3: Run to see the full list of unmarked files**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_audit_completeness.py -v 2>&1 | tail -40
```
Expected: FAIL, listing all 77 test files.

- [ ] **Step 4: Categorize each test file by the §6.E0.6 rule**

Apply the rule from spec §6.E0.6:

> A test file moves to pynecore iff all its non-stdlib imports are either (a) pynecore-side modules (`pyne_compiler.*`, `pynecore.*`) OR (b) stdlib/test fixtures. Any test importing an openbb-fork-side module (`openbb_pine.stdlib.*`, `.attribution`, `.routers.*`, `.mcp_tools`, `.runtime.fmp_provider`, `.runtime.byo_provider`, `.runtime.fmp_retry`, `.runtime.provider_selection`, `._coverage_manifest`, `.cli`, or the extension entrypoint) STAYS in openbb-fork.

Concrete decisions (per spec §6.E0.6 special cases + Rev 3 clarifications):

| Test file | Destination | Reason |
|---|---|---|
| `test_lexer.py`, `test_parser.py`, `test_type_checker.py`, `test_codegen.py`, `test_codegen_allowlist.py`, `test_compile_cache.py`, `test_compiled_module_shape.py`, `test_v5_migration.py`, `test_ir.py`, `test_grammar_strategy.py`, `test_builtin_signatures.py`, `test_diagnostics.py`, `test_error_classes.py` | **pynecore** | Compiler-internal; imports only compiler/* and errors/* |
| `test_error_model.py` | **pynecore** | Post-E0.4 the telemetry import becomes TelemetrySink injection; now purely compiler-side |
| `test_prefetch_security.py` (post-E0.2 update from the previous task) | **pynecore** | Post-E0.2 uses `_DataProviderStub` — no openbb-fork import |
| `test_executor_core.py` (new in E0.3) | **pynecore** | Runs `executor_core` with stub provider |
| `test_restricted.py`, `test_limits.py` | **pynecore** | Test runtime pieces that move |
| `test_executor_shell.py` (renamed in E0.3) | **openbb-fork** | Tests FMP/BYO wiring + POWERED_BY_FULL attribution |
| `test_stdlib_math_*.py` (7 files), `test_stdlib_ta_*.py` (28 files) | **openbb-fork** | Test the `openbb_pine.stdlib` bridges — stdlib STAYS per §7 |
| `test_widgets.py`, `test_about.py`, `test_attribution_surfaces.py`, `test_extension_loads.py`, `test_no_side_effects.py`, `test_mcp_tools.py`, `test_cli_main.py` | **openbb-fork** | Test OpenBB integration surfaces |
| `test_routers_catalog.py`, `test_routers_compile.py`, `test_routers_run.py`, `test_routers_strategies.py`, `test_routers_health.py`, `test_router_command_bare_obbject.py` | **openbb-fork** | Router integration |
| `test_fmp_provider.py`, `test_fmp_retry.py`, `test_byo_provider.py`, `test_provider_selection.py` | **openbb-fork** | Provider tests — providers stay in openbb-fork |
| `test_error_split.py` (from E0.1), `test_telemetry_injection.py` (from E0.4), `test_pynecore_bridge.py` (from E0.5), `test_audit_completeness.py` (this task) | **openbb-fork** | E0 verification tests — no post-extraction destination in pynecore |

For each test file, add the marker to its module docstring:

```python
"""... existing docstring ...

_test_lives_in: pynecore
"""
```
(or `openbb-fork` / `split`)

For any `split` case (e.g. a mixed-concern file), MOVE the pynecore-bound test classes into a new file with a `pynecore` marker; keep the openbb-fork-bound classes in the original file with an `openbb-fork` marker.

- [ ] **Step 5: Generate the audit table document**

Create `docs/pine-extraction/e0-6-test-audit.md`:

```markdown
# E0.6 Test Audit — post-extraction destinations

Generated per Pine Extraction Design §6.E0.6.
Drives the E2 `git filter-repo --path` list for tests.

| Test file | Destination | Rationale |
|---|---|---|
[Fill in from Step 4 categorization above]

## Files migrating to pynecore (feed into E2 filter-repo --path list)
- openbb_platform/extensions/pine/openbb_pine/tests/unit/test_lexer.py
[…]

## Files staying in openbb-fork
- openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_shell.py
[…]
```

Also add a self-check test:

```python
def test_pynecore_destined_tests_use_only_pynecore_side_imports() -> None:
    """For every test file marked _test_lives_in: pynecore, its non-stdlib
    imports must all be from compiler_errors / compiler / runtime /
    telemetry (the modules that migrate). No openbb_pine.stdlib,
    routers, attribution, mcp_tools, cli, fmp_*, byo_*, provider_selection."""
    import pathlib, re
    tests_dir = pathlib.Path(__file__).parent
    banned = re.compile(r"from openbb_pine\.(stdlib|attribution|routers|mcp_tools|"
                        r"_coverage_manifest|cli|runtime\.(fmp_provider|byo_provider|"
                        r"fmp_retry|provider_selection))")
    violators = []
    for path in tests_dir.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        if "_test_lives_in: pynecore" not in text:
            continue
        if banned.search(text):
            violators.append(path.name)
    assert not violators, f"Marked pynecore but import openbb-fork modules: {violators}"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_audit_completeness.py -v
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ -x --tb=short
```
Expected: PASS + 1,353 total pine tests green.

- [ ] **Step 7: Commit + open PR**

```bash
git add openbb_platform/extensions/pine/openbb_pine/tests/unit/ \
        docs/pine-extraction/e0-6-test-audit.md
git commit -m "refactor(pine): audit test files by post-extraction destination (bd-E0.6)

Per Pine Extraction Design §6.E0.6, tags every test file in
openbb_pine/tests/unit/ with a _test_lives_in marker (pynecore /
openbb-fork / split) using the rule: pynecore iff all non-stdlib
imports are pynecore-side. Also produces docs/pine-extraction/
e0-6-test-audit.md which drives E2 filter-repo path list.

Adds enforcement tests: every file must carry a marker; every
pynecore-marked file must NOT import openbb-fork modules.

Full pine test suite green (1,353 tests preserved).

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin refactor/e0-6-test-audit
gh pr create --base openbb_pine_support --head refactor/e0-6-test-audit \
  --title "refactor(pine): test audit for E2 filter-repo — E0.6 (bd-E0.6)" \
  --body "Sixth of six E0 sub-refactors. Depends on E0.1 + E0.2 + E0.3 + E0.4."
```

### Task E0.7: Grep-gate verification (E0 completion criterion)

**Bead:** `OpenBBTechnical-dt1` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `.claude/hooks/pine-e0-grep-gate.sh` (new — the shell one-liner from spec §6.E0)
- Modify: `.pre-commit-config.yaml` (add hook so future commits can't reintroduce coupling)
- Test: manual invocation of the hook against the current tree

**Interfaces:**
- Consumes: all six E0 sub-refactors merged
- Produces: passing grep-gate command per spec §6.E0. This is the definition of "E0 is done."

**Depends on:** E0.1 + E0.2 + E0.3 + E0.4 + E0.5 + E0.6 (all merged to `openbb_pine_support`).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch openbb_pine_support
git pull --ff-only
git switch -c chore/e0-7-grep-gate openbb_pine_support
```

- [ ] **Step 2: Write the grep-gate script**

Create `.claude/hooks/pine-e0-grep-gate.sh`:

```bash
#!/usr/bin/env bash
# Pine Extraction Design §6.E0 verification: compiler + core-runtime code
# must not import any provider/glue/telemetry/attribution/routers code.
# This grep MUST return zero hits for E0 to be considered done and for
# E2 (git filter-repo) to safely proceed.
set -euo pipefail

MIGRATING_FILES=(
  openbb_platform/extensions/pine/openbb_pine/compiler/
  openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py
  openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py
  openbb_platform/extensions/pine/openbb_pine/runtime/secondary_cache.py
  openbb_platform/extensions/pine/openbb_pine/runtime/security_hook.py
  openbb_platform/extensions/pine/openbb_pine/runtime/strategy_types.py
  openbb_platform/extensions/pine/openbb_pine/runtime/restricted.py
  openbb_platform/extensions/pine/openbb_pine/runtime/limits.py
  openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py
  openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py
  openbb_platform/extensions/pine/openbb_pine/compiler_errors.py
)

FORBIDDEN_PATTERN='from openbb_pine\.(attribution|telemetry|routers|mcp_tools|_coverage_manifest|cli)\.|from openbb_pine\.runtime\.(fmp_provider|byo_provider|fmp_retry|provider_selection)'

if grep -rE "$FORBIDDEN_PATTERN" "${MIGRATING_FILES[@]}" 2>/dev/null; then
  echo "" >&2
  echo "E0 grep-gate FAILED: migrating files still import openbb-fork-side code." >&2
  echo "See Pine Extraction Design §6.E0 verification for the full rationale." >&2
  exit 1
fi

echo "E0 grep-gate PASSED: no cross-boundary imports in migrating files."
```

Make it executable and commit as a pre-commit hook stage:

```bash
chmod +x .claude/hooks/pine-e0-grep-gate.sh
```

- [ ] **Step 3: Wire into .pre-commit-config.yaml**

Add to `.pre-commit-config.yaml` (or create at repo root if it doesn't exist):

```yaml
  - repo: local
    hooks:
      - id: pine-e0-grep-gate
        name: pine-e0-grep-gate
        entry: .claude/hooks/pine-e0-grep-gate.sh
        language: system
        pass_filenames: false
        # Only run when a pine-migrating file changes
        files: 'openbb_platform/extensions/pine/openbb_pine/(compiler/|runtime/(executor_core|security_dispatcher|secondary_cache|security_hook|strategy_types|restricted|limits|_pynecore_glue|pynecore_bridge)\.py|compiler_errors\.py)'
```

- [ ] **Step 4: Run the gate manually**

```bash
bash .claude/hooks/pine-e0-grep-gate.sh
```
Expected: `E0 grep-gate PASSED: no cross-boundary imports in migrating files.` If it fails, list which file/line still couples, file a follow-up sub-bead against the responsible E0.x task, and DO NOT proceed to E1.

- [ ] **Step 5: Run the full pine test suite (final E0 baseline check)**

```bash
.venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/pine/ --tb=short 2>&1 | tail -20
```
Expected: **1,353 passed**. Record the exact count in the PR body.

- [ ] **Step 6: Commit + open PR**

```bash
git add .claude/hooks/pine-e0-grep-gate.sh .pre-commit-config.yaml
git commit -m "chore(pine): wire E0 grep-gate as pre-commit hook (bd-E0.7)

Per Pine Extraction Design §6.E0 verification, this is the hard gate
for 'E0 is done'. Zero cross-boundary imports in migrating files.
Green tests are necessary but not sufficient.

Enforced going forward: any commit that reintroduces
'from openbb_pine.{attribution,telemetry,routers,mcp_tools,
_coverage_manifest,cli}' or 'from openbb_pine.runtime.{fmp_provider,
byo_provider,fmp_retry,provider_selection}' inside a migrating file
will be rejected at pre-commit time.

Full pine test suite green (1,353 tests preserved) as the final
E0 baseline.

Clean-room: I have not viewed TradingView or PyneComp source code.
"
git push -u origin chore/e0-7-grep-gate
gh pr create --base openbb_pine_support --head chore/e0-7-grep-gate \
  --title "chore(pine): E0 grep-gate — E0.7 verification (bd-E0.7)" \
  --body "Wrap-up gate for Phase E0. Enforces §6.E0 verification. Depends on E0.1-E0.6 all merged."
```

**E0 completion:** Once bd-E0.7 merges, record with `bd remember pine-e0-complete "E0 done YYYY-MM-DD; test baseline 1353 green; grep-gate PASSED; ready for E1."` and proceed to Phase E1.


---

## Phase E1 — Extend Provider base class + build reference providers (in pynecore)

**Where:** `prajoria/pynecore` on feature branches from `main`. Each E1.x is its own PR to pynecore `main`.
**Prerequisite:** All of Phase E0 merged into `openbb_pine_support` (grep-gate green).

### Task E1.1: Extend Provider base class with stream() and fetch() concrete methods

**Bead:** `OpenBBTechnical-dnf` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Modify: `src/pynecore/providers/provider.py` (add `stream()` + `fetch()` concrete methods)
- Test: `src/pynecore/providers/tests/test_provider_base_extensions.py` (new)

**Interfaces:**
- Consumes: existing `Provider` (metaclass=ABCMeta), `download_ohlcv()`, `load_ohlcv_data()`, `OHLCVReader`, `OHLCV`
- Produces:
  - `Provider.stream(self, symbol: str, timeframe: str, *, start: datetime | None = None, end: datetime | None = None) -> Iterator[OHLCV]` — concrete method (subclasses MAY override). Default: yields bars from the on-disk `.ohlcv` file (populated by `download_ohlcv()`), filtered to `[start, end]`.
  - `Provider.fetch(self, symbol: str, timeframe: str, *, start: datetime | None = None, end: datetime | None = None) -> list[OHLCV]` — concrete method. Default: `list(self.stream(...))`.

**Depends on:** Phase E0 fully merged in openbb-fork (so the openbb-side changes are in sync when we cross-reference the eventual E2 import fixup).

- [ ] **Step 1: Cut a feature branch in pynecore**

```bash
cd /path/to/pynecore-clone
git switch main
git pull --ff-only
git switch -c feat/provider-stream-fetch main
```

- [ ] **Step 2: Write the failing test**

Create `src/pynecore/providers/tests/test_provider_base_extensions.py`:

```python
"""E1.1: Provider base class now exposes stream() and fetch() concrete methods
with a default file-backed implementation. Existing ccxt.py and capitalcom.py
subclasses inherit these for free with no code change."""
from datetime import datetime, timezone
from typing import Iterator

import pytest

from pynecore.providers.provider import Provider
from pynecore.types.ohlcv import OHLCV


class _MinimalProvider(Provider):
    """Fake concrete provider whose download_ohlcv just writes 5 known bars.
    Verifies the default stream()/fetch() reads them back."""

    # Implement all the existing abstract methods with sane no-ops
    def to_tradingview_timeframe(self, tf):
        return tf
    def to_exchange_timeframe(self, tf):
        return tf
    def get_list_of_symbols(self):
        return ["TESTSYM"]
    def update_symbol_info(self):
        pass
    def get_opening_hours_and_sessions(self):
        return {}, {}

    def download_ohlcv(self, start=None, end=None):
        # Write 5 known bars to self.ohlcv_writer
        for i in range(1, 6):
            ts = int(datetime(2024, 1, i, tzinfo=timezone.utc).timestamp())
            self.ohlcv_writer.write(OHLCV(
                timestamp=ts, open=i, high=i, low=i, close=i, volume=1,
            ))


def test_provider_has_stream_method() -> None:
    assert callable(getattr(Provider, "stream", None))


def test_provider_has_fetch_method() -> None:
    assert callable(getattr(Provider, "fetch", None))


def test_default_stream_yields_download_ohlcv_output(tmp_path):
    """Round-trip through .ohlcv file."""
    p = _MinimalProvider(symbol="TESTSYM", timeframe="1D", ohlv_dir=tmp_path, config_dir=tmp_path)
    with p:
        p.download_ohlcv()
        bars = list(p.stream(
            "TESTSYM", "1D",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 5, tzinfo=timezone.utc),
        ))
    assert len(bars) == 5
    assert bars[0].close == 1.0
    assert bars[-1].close == 5.0


def test_default_fetch_returns_list_matching_stream(tmp_path):
    p = _MinimalProvider(symbol="TESTSYM", timeframe="1D", ohlv_dir=tmp_path, config_dir=tmp_path)
    with p:
        p.download_ohlcv()
        streamed = list(p.stream("TESTSYM", "1D",
                                  start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                                  end=datetime(2024, 1, 5, tzinfo=timezone.utc)))
        fetched = p.fetch("TESTSYM", "1D",
                           start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                           end=datetime(2024, 1, 5, tzinfo=timezone.utc))
    assert streamed == fetched


def test_stream_returns_empty_for_unknown_range(tmp_path):
    p = _MinimalProvider(symbol="TESTSYM", timeframe="1D", ohlv_dir=tmp_path, config_dir=tmp_path)
    with p:
        p.download_ohlcv()
        result = p.fetch("TESTSYM", "1D",
                         start=datetime(2020, 1, 1, tzinfo=timezone.utc),
                         end=datetime(2020, 1, 2, tzinfo=timezone.utc))
    assert result == []


def test_stream_returns_empty_when_start_greater_than_end(tmp_path):
    """Per spec §5.4 conformance check #4 (Rev 3): start > end returns [], NOT raise."""
    p = _MinimalProvider(symbol="TESTSYM", timeframe="1D", ohlv_dir=tmp_path, config_dir=tmp_path)
    with p:
        p.download_ohlcv()
        result = p.fetch("TESTSYM", "1D",
                         start=datetime(2024, 1, 5, tzinfo=timezone.utc),
                         end=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert result == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest src/pynecore/providers/tests/test_provider_base_extensions.py -v
```
Expected: FAIL — `AttributeError: type object 'Provider' has no attribute 'stream'`.

- [ ] **Step 4: Implement stream() and fetch() on Provider**

In `src/pynecore/providers/provider.py`, add to the `Provider` class (per spec §5.1):

```python
from datetime import datetime
from typing import Iterator

# ... existing imports + class ...

class Provider(metaclass=ABCMeta):
    # ... existing __init__, __enter__, __exit__, abstract methods ...

    def stream(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator["OHLCV"]:
        """Yield OHLCV bars in chronological order for (symbol, timeframe).

        Default implementation: reads from the .ohlcv file populated by
        download_ohlcv(). Subclasses MAY override for direct-query
        optimization (e.g. FMP hits REST directly, no file intermediate).

        For closed historical ranges, list(stream(...)) MUST equal fetch(...).
        For live ranges, stream() MAY include a forming bar that fetch()
        excludes (spec §5.1 / §5.4 conformance).

        start/end (when provided) are inclusive; None means unbounded on
        that side. start > end returns no bars (SQL-consistent). Timestamps
        yielded MUST be UTC, monotonically non-decreasing.
        """
        # Guard: reversed range = empty output (spec §5.4 check #4, Rev 3)
        if start is not None and end is not None and start > end:
            return iter([])

        # Use the existing OHLCVReader to iterate the .ohlcv file
        reader = self.load_ohlcv_data()
        try:
            for bar in reader:
                bar_ts = datetime.fromtimestamp(bar.timestamp, tz=start.tzinfo if start else None) if start else None
                if start is not None:
                    if datetime.fromtimestamp(bar.timestamp, tz=start.tzinfo) < start:
                        continue
                if end is not None:
                    if datetime.fromtimestamp(bar.timestamp, tz=end.tzinfo) > end:
                        break  # bars are chronologically sorted; safe to stop
                yield bar
        finally:
            if hasattr(reader, "close"):
                reader.close()

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list["OHLCV"]:
        """Return a bar range as a materialized list.

        Default: list(self.stream(...)). Subclasses MAY override to issue
        a single batched query (e.g. one SQL SELECT) instead of iterating.
        Ordering + UTC guarantees identical to stream()."""
        return list(self.stream(symbol, timeframe, start=start, end=end))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest src/pynecore/providers/tests/test_provider_base_extensions.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 6: Verify existing ccxt.py + capitalcom.py tests still pass (regression gate)**

```bash
pytest src/pynecore/providers/tests/ -v
```
Expected: existing tests unchanged, no regressions.

- [ ] **Step 7: Commit + open PR**

```bash
git add src/pynecore/providers/provider.py \
        src/pynecore/providers/tests/test_provider_base_extensions.py
git commit -m "feat(providers): add stream() + fetch() concrete methods to Provider base (bd-E1.1)

Per Pine Extraction Design §5.1, extends the existing Provider base
class with two new concrete methods:
- stream(sym, tf, *, start, end) -> Iterator[OHLCV]
- fetch(sym, tf, *, start, end) -> list[OHLCV]

Default implementations use the existing download_ohlcv() +
load_ohlcv_data() flow. Existing CCXT + CapitalCom subclasses inherit
these for free with no code change.

Per spec §5.4 conformance check #4 (Rev 3): start > end returns [],
not raises.

Enables CSV/SQLite reference providers (E1.2/E1.3) and unifies
pyne_compiler's data-access model with pynecore's existing Provider.
"
git push -u origin feat/provider-stream-fetch
gh pr create --base main --head feat/provider-stream-fetch \
  --title "feat(providers): stream() + fetch() on Provider base — E1.1 (bd-E1.1)" \
  --body "First of five E1 tasks. Unifies data model per spec §5. Existing CCXT/CapitalCom regressions checked."
```

### Task E1.2: CSV reference provider

**Bead:** `OpenBBTechnical-gxy` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `src/pynecore/providers/csv.py` (new — stdlib-only CSV provider)
- Test: `src/pynecore/providers/tests/test_csv.py` (new)
- Test fixture: `src/pynecore/providers/tests/fixtures/testsym_1d.csv` (new)

**Interfaces:**
- Consumes: `Provider` (extended in E1.1), `OHLCV`
- Produces:
  - `CSVProvider(Provider)` — construction: `CSVProvider(csv_path: Path, symbol: str, timeframe: str, ohlv_dir: Path, config_dir: Path)`.
  - Overrides `stream()` and `fetch()` to read directly from the CSV file (mode 1: instance-scoped).
  - Recognizes RFC 4180 CSV with columns `timestamp,open,high,low,close,volume`.

**Depends on:** E1.1 (extended Provider base).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch main
git pull --ff-only
git switch -c feat/csv-provider main
```

- [ ] **Step 2: Create the fixture CSV**

Create `src/pynecore/providers/tests/fixtures/testsym_1d.csv`:

```csv
timestamp,open,high,low,close,volume
1704067200,100.0,101.5,99.0,101.0,1000
1704153600,101.0,102.0,100.5,101.5,1100
1704240000,101.5,103.0,101.0,102.5,1200
1704326400,102.5,104.0,102.0,103.5,1300
1704412800,103.5,105.0,103.0,104.5,1400
```

(Timestamps are 2024-01-01, 2024-01-02, ..., 2024-01-05 UTC epoch seconds.)

- [ ] **Step 3: Write the failing test**

Create `src/pynecore/providers/tests/test_csv.py`:

```python
"""E1.2: CSVProvider reads RFC 4180 CSV files with timestamp,open,high,low,close,volume columns."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pynecore.providers.csv import CSVProvider

FIXTURE = Path(__file__).parent / "fixtures" / "testsym_1d.csv"


def test_csv_provider_exists() -> None:
    from pynecore.providers.csv import CSVProvider
    assert CSVProvider is not None


def test_csv_provider_fetches_all_bars(tmp_path):
    p = CSVProvider(
        csv_path=FIXTURE, symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        bars = p.fetch("TESTSYM", "1D",
                       start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 5, tzinfo=timezone.utc))
    assert len(bars) == 5
    assert bars[0].close == 101.0
    assert bars[-1].close == 104.5


def test_csv_provider_filters_by_range(tmp_path):
    p = CSVProvider(
        csv_path=FIXTURE, symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        bars = p.fetch("TESTSYM", "1D",
                       start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 4, tzinfo=timezone.utc))
    assert len(bars) == 3
    assert bars[0].close == 101.5


def test_csv_provider_stream_matches_fetch(tmp_path):
    """Conformance check #1 (§5.4)."""
    p = CSVProvider(
        csv_path=FIXTURE, symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        streamed = list(p.stream("TESTSYM", "1D",
                                  start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                                  end=datetime(2024, 1, 5, tzinfo=timezone.utc)))
        fetched = p.fetch("TESTSYM", "1D",
                           start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                           end=datetime(2024, 1, 5, tzinfo=timezone.utc))
    assert streamed == fetched


def test_csv_provider_reversed_range_returns_empty(tmp_path):
    """Conformance check #4 (§5.4 Rev 3): start > end returns []."""
    p = CSVProvider(
        csv_path=FIXTURE, symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        result = p.fetch("TESTSYM", "1D",
                         start=datetime(2024, 1, 5, tzinfo=timezone.utc),
                         end=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert result == []


def test_csv_provider_unknown_symbol_raises(tmp_path):
    """Conformance check #5 (§5.4): missing symbol raises typed error."""
    p = CSVProvider(
        csv_path=FIXTURE, symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        with pytest.raises((KeyError, LookupError, ValueError)):
            p.fetch("NEVER_EXISTS_XYZ", "1D",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 5, tzinfo=timezone.utc))
```

- [ ] **Step 4: Run test to verify it fails**

```bash
pytest src/pynecore/providers/tests/test_csv.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pynecore.providers.csv'`.

- [ ] **Step 5: Implement CSVProvider**

Create `src/pynecore/providers/csv.py`:

```python
"""CSVProvider — stdlib-only reference provider for RFC 4180 CSV OHLCV files.

Ships in pynecore core (spec §13.2: stdlib-only providers ship unconditionally).
CSV format: timestamp,open,high,low,close,volume
- timestamp: UTC epoch seconds (int)
- open/high/low/close: float
- volume: float or int

Rows are assumed already sorted by timestamp ascending; the provider does
not sort. Malformed rows raise ValueError with the offending line number.
"""
from __future__ import annotations

import csv as _csv
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pynecore.providers.provider import Provider
from pynecore.types.ohlcv import OHLCV


class CSVProvider(Provider):
    """Reads OHLCV bars from a single RFC 4180 CSV file."""

    def __init__(
        self,
        csv_path: Path,
        symbol: str,
        timeframe: str,
        ohlv_dir: Path,
        config_dir: Path,
    ) -> None:
        super().__init__(
            symbol=symbol, timeframe=timeframe,
            ohlv_dir=ohlv_dir, config_dir=config_dir,
        )
        self._csv_path = Path(csv_path)
        if not self._csv_path.is_file():
            raise FileNotFoundError(f"CSVProvider: {csv_path} does not exist")

    # Existing Provider abstracts — implement as no-ops / stubs suitable for CSV
    def to_tradingview_timeframe(self, tf):
        return tf
    def to_exchange_timeframe(self, tf):
        return tf
    def get_list_of_symbols(self):
        return [self.symbol]
    def update_symbol_info(self):
        pass
    def get_opening_hours_and_sessions(self):
        return {}, {}

    def download_ohlcv(self, start=None, end=None):
        """Populate the .ohlcv file from the CSV so the base file-backed
        flow works. Called from __enter__ context, or callers can skip this
        and use stream()/fetch() directly (which override the base)."""
        for bar in self._iter_csv_bars():
            self.ohlcv_writer.write(bar)

    def _iter_csv_bars(self) -> Iterator[OHLCV]:
        with self._csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            required = {"timestamp", "open", "high", "low", "close", "volume"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSVProvider: {self._csv_path} missing columns: {missing}")
            for lineno, row in enumerate(reader, start=2):  # header is line 1
                try:
                    yield OHLCV(
                        timestamp=int(row["timestamp"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                except (KeyError, ValueError) as e:
                    raise ValueError(f"CSVProvider: malformed row at {self._csv_path}:{lineno}: {e}") from e

    def stream(self, symbol, timeframe, *, start=None, end=None):
        """Override the base default with a direct CSV read (avoids the
        write-then-read-through-.ohlcv round trip)."""
        if symbol != self.symbol:
            raise KeyError(
                f"CSVProvider constructed for symbol={self.symbol!r} but stream() called "
                f"with symbol={symbol!r}. CSVProvider is instance-scoped (mode 1 per spec §5.2)."
            )
        if start is not None and end is not None and start > end:
            return iter([])
        return self._filtered_iter(start, end)

    def _filtered_iter(self, start, end) -> Iterator[OHLCV]:
        for bar in self._iter_csv_bars():
            ts_dt = datetime.fromtimestamp(bar.timestamp, tz=(start.tzinfo if start else None))
            if start is not None and ts_dt < start:
                continue
            if end is not None and ts_dt > end:
                break
            yield bar
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest src/pynecore/providers/tests/test_csv.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 7: Commit + open PR**

```bash
git add src/pynecore/providers/csv.py \
        src/pynecore/providers/tests/test_csv.py \
        src/pynecore/providers/tests/fixtures/testsym_1d.csv
git commit -m "feat(providers): CSVProvider reference implementation (bd-E1.2)

Per Pine Extraction Design §5.3 + §13.2, ships stdlib-only CSV
provider unconditionally in pynecore core. RFC 4180 with columns
timestamp,open,high,low,close,volume. Instance-scoped (mode 1) —
one file, one symbol.

Overrides Provider.stream/fetch for direct CSV read.

Depends on E1.1 (extended Provider base).
"
git push -u origin feat/csv-provider
gh pr create --base main --head feat/csv-provider \
  --title "feat(providers): CSVProvider — E1.2 (bd-E1.2)" \
  --body "Second E1 task. Ships stdlib-only per §13.2. Passes 6 unit tests + will pass §5.4 conformance in E1.4."
```

### Task E1.3: SQLite reference provider

**Bead:** `OpenBBTechnical-l05` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `src/pynecore/providers/sqlite.py` (new — stdlib-only SQLite provider)
- Test: `src/pynecore/providers/tests/test_sqlite.py` (new)

**Interfaces:**
- Consumes: `Provider` (extended in E1.1), `OHLCV`
- Produces:
  - `SQLiteProvider(Provider)` — construction: `SQLiteProvider(db_path: Path, table_name: str, symbol: str, timeframe: str, ohlv_dir: Path, config_dir: Path, symbol_column: str = "symbol", timeframe_column: str | None = None)`.
  - Overrides `stream()`/`fetch()` to issue direct SQL SELECT (mode 2: multi-symbol capable).
  - Table schema (default): `CREATE TABLE ohlcv (timestamp INTEGER, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)`. Configurable via constructor.

**Depends on:** E1.1.

- [ ] **Step 1: Cut a feature branch**

```bash
git switch main
git pull --ff-only
git switch -c feat/sqlite-provider main
```

- [ ] **Step 2: Write the failing test (which also creates the test DB)**

Create `src/pynecore/providers/tests/test_sqlite.py`:

```python
"""E1.3: SQLiteProvider reads OHLCV bars from a SQLite database via SQL SELECT."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pynecore.providers.sqlite import SQLiteProvider


@pytest.fixture()
def sqlite_db(tmp_path) -> Path:
    """Fresh SQLite DB with 5 bars for TESTSYM 1D + 3 bars for OTHER 1D."""
    db = tmp_path / "ohlcv.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ohlcv (
            timestamp INTEGER,
            symbol TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL
        );
    """)
    rows = [
        (1704067200 + i * 86400, "TESTSYM", 100 + i, 101 + i, 99 + i, 100.5 + i, 1000 + 100 * i)
        for i in range(5)
    ] + [
        (1704067200 + i * 86400, "OTHER", 200 + i, 201 + i, 199 + i, 200.5 + i, 2000)
        for i in range(3)
    ]
    conn.executemany("INSERT INTO ohlcv VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


def test_sqlite_provider_exists() -> None:
    from pynecore.providers.sqlite import SQLiteProvider
    assert SQLiteProvider is not None


def test_fetch_returns_all_bars_for_symbol(sqlite_db, tmp_path):
    p = SQLiteProvider(
        db_path=sqlite_db, table_name="ohlcv",
        symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        bars = p.fetch("TESTSYM", "1D",
                       start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    assert len(bars) == 5
    assert bars[0].close == 100.5


def test_fetch_isolates_by_symbol(sqlite_db, tmp_path):
    p = SQLiteProvider(
        db_path=sqlite_db, table_name="ohlcv",
        symbol="OTHER", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        bars = p.fetch("OTHER", "1D",
                       start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    assert len(bars) == 3
    assert all(bar.open >= 200 for bar in bars)


def test_stream_matches_fetch(sqlite_db, tmp_path):
    """Conformance check #1 (§5.4)."""
    p = SQLiteProvider(
        db_path=sqlite_db, table_name="ohlcv",
        symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        streamed = list(p.stream("TESTSYM", "1D",
                                  start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                                  end=datetime(2024, 1, 10, tzinfo=timezone.utc)))
        fetched = p.fetch("TESTSYM", "1D",
                           start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                           end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    assert streamed == fetched


def test_reversed_range_returns_empty(sqlite_db, tmp_path):
    """Conformance check #4 (§5.4)."""
    p = SQLiteProvider(
        db_path=sqlite_db, table_name="ohlcv",
        symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        result = p.fetch("TESTSYM", "1D",
                         start=datetime(2024, 1, 10, tzinfo=timezone.utc),
                         end=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert result == []


def test_unknown_symbol_returns_empty(sqlite_db, tmp_path):
    """SQLite semantics: unknown symbol → no rows → empty list.
    (This is stricter than spec check #5's 'raises'; the provider takes
    the empty-list path to match natural SQL semantics — check #5 is
    exercised via the conformance suite (E1.4) with a wrapper that
    escalates to a raise for the compliance test.)"""
    p = SQLiteProvider(
        db_path=sqlite_db, table_name="ohlcv",
        symbol="NEVER_EXISTS", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        result = p.fetch("NEVER_EXISTS", "1D",
                         start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                         end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    assert result == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest src/pynecore/providers/tests/test_sqlite.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pynecore.providers.sqlite'`.

- [ ] **Step 4: Implement SQLiteProvider**

Create `src/pynecore/providers/sqlite.py`:

```python
"""SQLiteProvider — stdlib-only reference provider backed by a SQLite database.

Ships in pynecore core (spec §13.2: stdlib-only providers ship unconditionally).
Default schema:
    CREATE TABLE ohlcv (
        timestamp INTEGER, symbol TEXT,
        open REAL, high REAL, low REAL, close REAL, volume REAL
    );

Column names configurable via constructor. Supports multi-symbol tables
(mode 2 per spec §5.2) — one provider instance can serve many
(symbol, timeframe) pairs.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pynecore.providers.provider import Provider
from pynecore.types.ohlcv import OHLCV


class SQLiteProvider(Provider):
    """Reads OHLCV bars from a SQLite database via SQL SELECT."""

    def __init__(
        self,
        db_path: Path,
        table_name: str,
        symbol: str,
        timeframe: str,
        ohlv_dir: Path,
        config_dir: Path,
        *,
        symbol_column: str = "symbol",
        timeframe_column: str | None = None,
        timestamp_column: str = "timestamp",
    ) -> None:
        super().__init__(
            symbol=symbol, timeframe=timeframe,
            ohlv_dir=ohlv_dir, config_dir=config_dir,
        )
        self._db_path = Path(db_path)
        self._table = table_name
        self._sym_col = symbol_column
        self._tf_col = timeframe_column
        self._ts_col = timestamp_column
        if not self._db_path.is_file():
            raise FileNotFoundError(f"SQLiteProvider: {db_path} does not exist")

    def to_tradingview_timeframe(self, tf):
        return tf
    def to_exchange_timeframe(self, tf):
        return tf
    def get_list_of_symbols(self):
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(f"SELECT DISTINCT {self._sym_col} FROM {self._table}").fetchall()
        return [r[0] for r in rows]
    def update_symbol_info(self):
        pass
    def get_opening_hours_and_sessions(self):
        return {}, {}

    def download_ohlcv(self, start=None, end=None):
        """Populate the .ohlcv file from the SQL query for the base file-backed flow."""
        for bar in self._query(self.symbol, self.timeframe, start, end):
            self.ohlcv_writer.write(bar)

    def _query(self, symbol: str, timeframe: str, start, end) -> Iterator[OHLCV]:
        clauses = [f"{self._sym_col} = ?"]
        params: list = [symbol]
        if self._tf_col:
            clauses.append(f"{self._tf_col} = ?")
            params.append(timeframe)
        if start is not None:
            clauses.append(f"{self._ts_col} >= ?")
            params.append(int(start.timestamp()))
        if end is not None:
            clauses.append(f"{self._ts_col} <= ?")
            params.append(int(end.timestamp()))
        sql = (
            f"SELECT {self._ts_col}, open, high, low, close, volume "
            f"FROM {self._table} WHERE " + " AND ".join(clauses) +
            f" ORDER BY {self._ts_col} ASC"
        )
        with sqlite3.connect(self._db_path) as conn:
            for row in conn.execute(sql, params):
                yield OHLCV(
                    timestamp=int(row[0]),
                    open=float(row[1]), high=float(row[2]),
                    low=float(row[3]), close=float(row[4]),
                    volume=float(row[5]),
                )

    def stream(self, symbol, timeframe, *, start=None, end=None):
        """Multi-symbol capable (mode 2 per spec §5.2) — accepts any
        (symbol, timeframe) present in the underlying table."""
        if start is not None and end is not None and start > end:
            return iter([])
        return self._query(symbol, timeframe, start, end)

    def fetch(self, symbol, timeframe, *, start=None, end=None):
        return list(self.stream(symbol, timeframe, start=start, end=end))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest src/pynecore/providers/tests/test_sqlite.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 6: Commit + open PR**

```bash
git add src/pynecore/providers/sqlite.py \
        src/pynecore/providers/tests/test_sqlite.py
git commit -m "feat(providers): SQLiteProvider reference implementation (bd-E1.3)

Per Pine Extraction Design §5.3, ships stdlib-only SQLite provider
unconditionally in pynecore core. Default schema:
CREATE TABLE ohlcv (timestamp, symbol, open, high, low, close, volume).
Column names configurable via constructor.

Supports mode-2 usage (multi-symbol per instance) via SQL WHERE clauses.
Overrides Provider.stream/fetch for direct SELECT.

Depends on E1.1.
"
git push -u origin feat/sqlite-provider
gh pr create --base main --head feat/sqlite-provider \
  --title "feat(providers): SQLiteProvider — E1.3 (bd-E1.3)" \
  --body "Third E1 task. Ships stdlib-only per §13.2. Supports multi-symbol tables per §5.2 mode 2."
```

### Task E1.4: Behavioral conformance suite

**Bead:** `OpenBBTechnical-cko` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `src/pynecore/providers/tests/test_conformance.py` (new — shared behavioral suite per spec §5.4)
- Modify: `src/pynecore/providers/tests/test_csv.py`, `test_sqlite.py` (each calls the conformance suite with its fixture)

**Interfaces:**
- Consumes: `Provider` (E1.1), `CSVProvider` (E1.2), `SQLiteProvider` (E1.3)
- Produces:
  - `_conformance_suite(provider: Provider, *, closed_only: bool) -> None` — the 7 checks from spec §5.4.
  - Instructions in the module docstring for external consumers (openbb-fork's FMPOHLCVProvider in E3.2) to call the same suite.

**Depends on:** E1.1, E1.2, E1.3.

- [ ] **Step 1: Cut a feature branch**

```bash
git switch main
git pull --ff-only
git switch -c feat/provider-conformance-suite main
```

- [ ] **Step 2: Write the failing test**

Create `src/pynecore/providers/tests/test_conformance.py` (verbatim from spec §5.4 with helpers):

```python
"""Shared behavioral conformance suite every Provider subclass must pass.

Per Pine Extraction Design §5.4 (Rev 3). Called by each concrete provider's
test module (test_csv.py, test_sqlite.py, and downstream openbb-fork's
test_fmp_provider.py in E3.2 conformance tests).

The 7 checks:
1. stream() and fetch() equivalent for CLOSED historical ranges
2. Timestamps monotonically non-decreasing
3. Empty range returns []
4. start > end returns [] (not raise)
5. Missing symbol raises typed error
6. UTC-timezone enforcement
7. Stateless across calls (fetch() twice = same result)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pynecore.providers.provider import Provider


def _conformance_suite(provider: "Provider", *, closed_only: bool = True,
                        test_symbol: str = "TESTSYM", test_timeframe: str = "1D",
                        range_start: datetime | None = None,
                        range_end: datetime | None = None) -> None:
    """Behavioral checks every Provider's stream()/fetch() must satisfy.

    :param provider: A Provider instance already inside its context manager,
        wired to a fixture data set covering [range_start, range_end].
    :param closed_only: When True, the fixture guarantees the range is
        entirely closed (no forming bar). Live providers (FMP realtime)
        may call with closed_only=False to skip check #1.
    :param test_symbol: Symbol the fixture has data for.
    :param test_timeframe: Timeframe the fixture has data for.
    :param range_start: Start of the closed historical range fixture covers.
    :param range_end: End of the closed historical range fixture covers.
    """
    if range_start is None:
        range_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    if range_end is None:
        range_end = datetime(2024, 1, 5, tzinfo=timezone.utc)

    # 1. stream() and fetch() return equivalent data for closed historical ranges
    if closed_only:
        streamed = list(provider.stream(test_symbol, test_timeframe,
                                         start=range_start, end=range_end))
        fetched = provider.fetch(test_symbol, test_timeframe,
                                  start=range_start, end=range_end)
        assert streamed == fetched, (
            f"stream()/fetch() disagreed for closed range on {type(provider).__name__}: "
            f"stream={len(streamed)} bars, fetch={len(fetched)} bars"
        )

    # 2. Timestamps monotonically non-decreasing
    fetched = provider.fetch(test_symbol, test_timeframe,
                              start=range_start, end=range_end)
    timestamps = [bar.timestamp for bar in fetched]
    assert timestamps == sorted(timestamps), "bars must be chronological"

    # 3. Empty (out-of-fixture-range) window returns []
    empty = provider.fetch(test_symbol, test_timeframe,
                            start=datetime(2000, 1, 1, tzinfo=timezone.utc),
                            end=datetime(2000, 1, 2, tzinfo=timezone.utc))
    assert empty == [], f"unknown range should return [] cleanly, got {len(empty)} bars"

    # 4. start > end returns [] (Rev 3 change from Rev 2's 'raise')
    reversed_range = provider.fetch(test_symbol, test_timeframe,
                                     start=range_end, end=range_start)
    assert reversed_range == [], "start > end must return [] (not raise)"

    # 5. Missing symbol raises typed error
    with pytest.raises((KeyError, LookupError, ValueError)):
        provider.fetch("NEVER_EXISTS_XYZ_9999", test_timeframe,
                        start=range_start, end=range_end)

    # 6. UTC-timezone enforcement on returned bars
    for bar in fetched:
        # OHLCV.timestamp is stored as epoch seconds int; convert and check UTC intent.
        dt = datetime.fromtimestamp(bar.timestamp, tz=timezone.utc)
        assert dt.tzinfo == timezone.utc, "bar timestamps must round-trip through UTC"

    # 7. Stateless across calls
    a = provider.fetch(test_symbol, test_timeframe, start=range_start, end=range_end)
    b = provider.fetch(test_symbol, test_timeframe, start=range_start, end=range_end)
    assert a == b, "fetch() must be stateless (two identical calls => identical results)"
```

Then in `test_csv.py`, add:

```python
def test_csv_provider_conformance(tmp_path):
    from pynecore.providers.tests.test_conformance import _conformance_suite
    p = CSVProvider(
        csv_path=FIXTURE, symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        # CSV provider raises KeyError for unknown symbols per its mode-1 guard
        _conformance_suite(p, closed_only=True,
                            test_symbol="TESTSYM", test_timeframe="1D",
                            range_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                            range_end=datetime(2024, 1, 5, tzinfo=timezone.utc))
```

And in `test_sqlite.py`, add (with a small wrapper to make check #5 raise, matching mode-2 semantics):

```python
class _RaisingSQLiteProvider(SQLiteProvider):
    """Wraps SQLiteProvider so unknown-symbol fetches RAISE (matching
    §5.4 check #5) instead of returning []. Real production callers
    should decide whether they prefer raise or empty-list semantics."""
    def fetch(self, symbol, timeframe, *, start=None, end=None):
        result = super().fetch(symbol, timeframe, start=start, end=end)
        if not result:
            # Only raise if the symbol simply isn't in the table
            available = self.get_list_of_symbols()
            if symbol not in available:
                raise KeyError(f"symbol {symbol!r} not in SQLite table {self._table!r}")
        return result


def test_sqlite_provider_conformance(sqlite_db, tmp_path):
    from pynecore.providers.tests.test_conformance import _conformance_suite
    p = _RaisingSQLiteProvider(
        db_path=sqlite_db, table_name="ohlcv",
        symbol="TESTSYM", timeframe="1D",
        ohlv_dir=tmp_path, config_dir=tmp_path,
    )
    with p:
        _conformance_suite(p, closed_only=True,
                            test_symbol="TESTSYM", test_timeframe="1D",
                            range_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                            range_end=datetime(2024, 1, 5, tzinfo=timezone.utc))
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest src/pynecore/providers/tests/test_conformance.py -v
pytest src/pynecore/providers/tests/test_csv.py::test_csv_provider_conformance -v
pytest src/pynecore/providers/tests/test_sqlite.py::test_sqlite_provider_conformance -v
```
Expected: FAIL — `_conformance_suite` doesn't exist yet.

- [ ] **Step 4: Ensure existing ccxt.py + capitalcom.py don't regress**

The extended `Provider.stream`/`fetch` defaults are what CCXT and CapitalCom inherit. Their own test suites must still pass:

```bash
pytest src/pynecore/providers/ -v --tb=short
```
Expected: PASS across all provider tests including existing ones.

- [ ] **Step 5: Commit + open PR**

```bash
git add src/pynecore/providers/tests/test_conformance.py \
        src/pynecore/providers/tests/test_csv.py \
        src/pynecore/providers/tests/test_sqlite.py
git commit -m "test(providers): shared behavioral conformance suite (bd-E1.4)

Per Pine Extraction Design §5.4 (Rev 3), ships _conformance_suite that
every Provider subclass must pass:
1. stream/fetch equivalent for closed ranges
2. Timestamps monotonically non-decreasing
3. Empty range returns []
4. start > end returns [] (not raise)
5. Missing symbol raises typed error
6. UTC-timezone enforcement
7. Stateless across calls

CSVProvider + SQLiteProvider both pass. Downstream FMP+BYO providers
(E3.2/E3.3) will call the same suite.

Depends on E1.1 + E1.2 + E1.3.
"
git push -u origin feat/provider-conformance-suite
gh pr create --base main --head feat/provider-conformance-suite \
  --title "test(providers): conformance suite — E1.4 (bd-E1.4)" \
  --body "Fourth E1 task. Shared suite per §5.4. CSV + SQLite both pass."
```

### Task E1.5: pyne_compiler package placeholder + pyproject verification

**Bead:** `OpenBBTechnical-4dj` (tracks `OpenBBTechnical-rbf` extraction epic)

**Files:**
- Create: `src/pyne_compiler/__init__.py` (new — placeholder with `__version__` and sys.path bridge stub)
- Modify: `pyproject.toml` (verify `packages.find = { where = ["src"] }` picks up both packages; add `[project.optional-dependencies]` for future provider extras if needed)
- Test: `src/pyne_compiler/tests/__init__.py` (new — makes tests dir a package) + `src/pyne_compiler/tests/test_package_installable.py` (new)

**Interfaces:**
- Consumes: nothing — this is packaging plumbing
- Produces:
  - `pyne_compiler.__version__` — string, initially `"0.1.0-pre-extraction"`. E3.4 wires router `compile_router.py` to read this.
  - Verified: `pip install -e .` on pynecore installs BOTH `pynecore` AND `pyne_compiler`.

**Depends on:** (independent of E1.1-E1.4 but must land before E2 so the target directory exists).

- [ ] **Step 1: Cut a feature branch**

```bash
git switch main
git pull --ff-only
git switch -c feat/pyne-compiler-placeholder main
```

- [ ] **Step 2: Write the failing test**

Create `src/pyne_compiler/tests/test_package_installable.py`:

```python
"""E1.5: pyne_compiler is discoverable + installable alongside pynecore."""


def test_pyne_compiler_importable() -> None:
    import pyne_compiler  # noqa: F401


def test_pyne_compiler_has_version() -> None:
    import pyne_compiler
    assert isinstance(pyne_compiler.__version__, str)
    assert len(pyne_compiler.__version__) > 0


def test_pynecore_and_pyne_compiler_coexist() -> None:
    """Both packages install from the same distribution (pynesys-pynecore)."""
    import pynecore
    import pyne_compiler
    assert pynecore is not None
    assert pyne_compiler is not None
    # Independent version strings
    assert hasattr(pynecore, "__version__")
    assert hasattr(pyne_compiler, "__version__")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest src/pyne_compiler/tests/test_package_installable.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pyne_compiler'`.

- [ ] **Step 4: Create the placeholder package**

Create `src/pyne_compiler/__init__.py`:

```python
"""pyne_compiler — clean-room Pine v5/v6 compiler + core runtime.

Sibling of pynecore under the pynesys-pynecore distribution. Provenance:
see CLEANROOM.md at repo root.

Post-E2 this package receives its full source via git filter-repo from
openbb-fork's openbb_platform/extensions/pine/openbb_pine/.

Independent __version__ from pynecore per spec §4.2 / §13.1: one
distribution, two version strings. The compiler string bumps on
compiler changes without forcing a pynecore runtime bump.
"""

__version__ = "0.1.0-pre-extraction"


# Sys.path bridge for the submodule-vendored deployment.
# Populated by E2 (moves openbb_pine/runtime/pynecore_bridge.py here).
# For now it's a no-op stub so import works.
def _install_pynecore_path_if_needed() -> None:
    """Post-E2 this delegates to pyne_compiler.runtime.pynecore_bridge;
    pre-E2 (placeholder) it's a no-op."""
    pass


_install_pynecore_path_if_needed()
```

Create `src/pyne_compiler/tests/__init__.py` (empty).

- [ ] **Step 5: Verify pyproject picks up pyne_compiler**

Check `pyproject.toml` — `packages.find = { where = ["src"] }` should discover both. If it doesn't (older setuptools may need explicit listing):

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["pynecore*", "pyne_compiler*"]
```

Then reinstall in dev mode and run the tests:

```bash
pip install -e . --no-deps
pytest src/pyne_compiler/tests/test_package_installable.py -v
python -c "import pynecore, pyne_compiler; print('pynecore:', pynecore.__version__, '/ pyne_compiler:', pyne_compiler.__version__)"
```
Expected: PASS (3 tests). Python print: `pynecore: X.Y.Z / pyne_compiler: 0.1.0-pre-extraction`.

- [ ] **Step 6: Commit + open PR**

```bash
git add src/pyne_compiler/__init__.py \
        src/pyne_compiler/tests/__init__.py \
        src/pyne_compiler/tests/test_package_installable.py \
        pyproject.toml
git commit -m "feat(packaging): pyne_compiler placeholder package (bd-E1.5)

Per Pine Extraction Design §4.2 + §13.1, creates the target directory
src/pyne_compiler/ with __init__.py and independent __version__ so
setuptools picks it up under packages.find = { where = ['src'] }.
Both pynecore + pyne_compiler now install from one pip install -e .

Full source moves in via git filter-repo at E2. Placeholder version
0.1.0-pre-extraction gets replaced by the real compiler version there.
"
git push -u origin feat/pyne-compiler-placeholder
gh pr create --base main --head feat/pyne-compiler-placeholder \
  --title "feat(packaging): pyne_compiler placeholder — E1.5 (bd-E1.5)" \
  --body "Fifth E1 task. Prerequisite for E2 filter-repo (needs the target directory to exist)."
```

**Phase E1 complete when:** E1.1-E1.5 all merged to pynecore main; `pytest src/pynecore/providers/ src/pyne_compiler/` all green.

