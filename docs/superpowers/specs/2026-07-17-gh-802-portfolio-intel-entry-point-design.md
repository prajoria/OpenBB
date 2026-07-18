# Design: fix `openbb-portfolio-intel` entry-point load error (#802)

**GH Issue:** #802
**Author:** Claude (autopilot, per Daisy's blanket approval on 2026-07-16)
**Related:** PR #466 introduced `portfolio_intel_router.py` with the `_include_subrouters()` loop that has the bug.

## Problem

On any working tree with `openbb-portfolio-intel` installed via `pip install -e openbb_platform/extensions/portfolio_intel`, `from openbb import obb` fails with:

```
ModuleNotFoundError: No module named 'openbb_portfolio_intel.routers'
```

Full traceback lands in `openbb_core.app.extension_loader._load_entry_points` → `ep.load()` on the `openbb_core_extension` entry-point → executes `portfolio_intel_router.py` module-body → calls `_include_subrouters()` → loop tries `__import__("openbb_portfolio_intel.routers.xray_router")` and the exception-swallow guard doesn't catch it.

Reproduced live on `portfolio` at commit `863ac93b8` (post-develop-absorb).

## Root cause (pinned)

`_include_subrouters()` in `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/portfolio_intel_router.py` iterates over `_PLANNED_SUBROUTERS`:

```python
_PLANNED_SUBROUTERS = (
    "openbb_portfolio_intel.routers.xray_router",
    "openbb_portfolio_intel.routers.events_router",
    ... (7 total)
)

def _include_subrouters() -> None:
    for module_path in _PLANNED_SUBROUTERS:
        try:
            module = __import__(module_path, fromlist=["router"])
        except ModuleNotFoundError as exc:
            if exc.name == module_path:
                continue    # swallow expected "not yet implemented"
            raise           # re-raise unexpected
```

The `if exc.name == module_path` guard was intended to distinguish "this sub-router hasn't been implemented yet" (safe to swallow) from "this sub-router IS implemented but has a broken transitive import" (must re-raise so CI catches it).

**The bug:** `ModuleNotFoundError.name` is set to the *deepest package Python couldn't find*, not the module `__import__` was asked for. When `openbb_portfolio_intel.routers` (the intermediate package) doesn't exist, `exc.name == "openbb_portfolio_intel.routers"`, which is a prefix of `module_path` but not equal. The guard fails, exception re-raised, extension load crashes.

This is a common gotcha with `ModuleNotFoundError.name` — it reports the missing *node in the import chain*, not the *target*.

## Success criteria

1. `from openbb import obb` succeeds on `portfolio` with `openbb-portfolio-intel` installed.
2. When any of the 7 planned sub-routers IS implemented, its `router` symbol is included on the parent Router (behavior of the loop's `router.include_router(module.router)` — verify this line still exists / add if missing).
3. When a sub-router IS implemented but has an internal bug (e.g. imports a missing dependency), the ModuleNotFoundError still re-raises so CI catches it. The guard's original intent must be preserved.
4. Regression test: unit test that imports `portfolio_intel_router` and calls `_include_subrouters()` with (a) all sub-routers missing (current state — should be silent), (b) one sub-router present (should include), (c) one sub-router present but with broken import (should raise).

## Approach

**Chosen: Option 2 (loosen the guard).** Change the swallow condition to accept both `exc.name == module_path` (leaf missing) AND `module_path.startswith(exc.name + ".")` (any ancestor missing).

**Rationale over Option 1 (create empty `routers/__init__.py`):**
- Option 1 lies to the type system: the `routers` package would exist but contain nothing, and a future `__import__("openbb_portfolio_intel.routers.xray_router")` would still fail (leaf missing), triggering the same guard-check for a different reason. So Option 1 changes the failure symptom but the underlying guard logic is still fragile. Option 2 fixes the logic directly.
- Option 1 requires a new file to land alongside every future actual sub-router file (need `routers/__init__.py` in the package). Option 2 lets sub-routers land under `routers/` naturally when they're written.
- Option 2 is a 1-line semantic change with existing docstring intent preserved.

**Alternative considered — Option 3: switch to `importlib.import_module` + `ImportError.name` check:** essentially the same as Option 2 but with more import surface. Rejected as no clearer.

## Implementation checklist

- [ ] Modify `_include_subrouters()` guard in `portfolio_intel_router.py` — 1-line semantic change + docstring update
- [ ] Add unit tests in `openbb_platform/extensions/portfolio_intel/tests/unit/test_router_scaffold.py`:
  - `test_all_subrouters_missing_is_silent()` — current reality; the guard should accept
  - `test_subrouter_present_is_included()` — mock a sub-router module, verify inclusion
  - `test_subrouter_with_broken_transitive_import_reraises()` — mock a sub-router that tries to import a genuinely missing dep, verify re-raise
- [ ] Live-verify `from openbb import obb` works in the venv
- [ ] Live-verify a smoke import of the extension: `from openbb_portfolio_intel.portfolio_intel_router import router; print(router.description)`

## Testing strategy

TDD: three unit tests that fully specify the behavior of the guard, then implement. Use `unittest.mock` to inject fake sub-router modules via `sys.modules` for tests (b) and (c), because we don't want to check in real sub-router stubs.

Fixture set:
- Fixture A: `sys.modules` clean → all `__import__` calls raise `ModuleNotFoundError(name="openbb_portfolio_intel.routers")` → guard accepts all → loop completes silently
- Fixture B: inject `sys.modules["openbb_portfolio_intel.routers"] = <fake package>` and `sys.modules["openbb_portfolio_intel.routers.xray_router"] = <fake module with .router attribute>` → import succeeds → `router.include_router` called with the fake
- Fixture C: inject `openbb_portfolio_intel.routers` (parent exists) but any leaf → raises `ModuleNotFoundError(name="openbb_portfolio_intel.routers.xray_router")` → guard now accepts because `module_path == exc.name` for the leaf too → still silent (this is *expected* behavior — a leaf-missing is the "not yet implemented" case)
- Fixture D: inject a fake sub-router whose module body raises `ModuleNotFoundError(name="some_missing_dep")` → exc.name is neither the module_path nor an ancestor → guard re-raises → test asserts the raise

## Rollout

1. Branch `feat/pi-ops/portfolio-intel-entry-point-gh-802` cut from `portfolio` HEAD (`863ac93b8`).
2. TDD implementation as above.
3. Local verify `from openbb import obb`.
4. PR into `portfolio` with `Closes #802`. The new #826 grammar-check workflow validates the syntax. Auto-close still won't fire because of the default-branch limitation (see #847) — expect manual close via `gh issue close` after merge, until #847 ships.
