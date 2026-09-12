# Provider Model Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dynamically generated OpenBB provider response models importable by
their declared module and name so ETF initialization cannot empty TechTrade's live
segment signal path through a false compatibility failure.

**Architecture:** `ProviderInterface` remains the owner of response-model creation.
When it creates each `OBBject_<StandardModel>` class, it explicitly declares and
exports that class from `openbb_core.app.provider_interface`. TechTrade code and its
graceful universe fallback remain unchanged.

**Tech Stack:** Python 3.10+, Pydantic v2 dynamic models, pytest, OpenBB provider
registry, TechTrade.

## Global Constraints

- Fix the generic provider-model contract; do not special-case `EtfCountries`.
- Do not add monkeypatches, broad exception handling, or dependency changes.
- Preserve TechTrade's logged resolver-failure fallback to an unfiltered universe.
- Run tests with the repository portfolio virtual environment.
- Do not commit generated `openbb.package` output or live financial data.

---

### Task 1: Lock and implement the provider response-model import contract

**Files:**
- Modify: `openbb_platform/core/tests/app/test_provider_interface.py`
- Modify: `openbb_platform/core/openbb_core/app/provider_interface.py:699-741`

**Interfaces:**
- Consumes: `ProviderInterface.return_annotations: dict[str, type[OBBject]]`
- Produces: importable module attributes named `OBBject_<StandardModel>`

- [ ] **Step 1: Write the failing regression test**

Add a test that iterates over `provider_interface.return_annotations`, imports each
model's declared module, and checks that `getattr(module, model.__name__) is model`.
Also assert that `EtfCountries`, when present in the installed registry, resolves as
`openbb_core.app.provider_interface.OBBject_EtfCountries`.

- [ ] **Step 2: Run the regression test to verify RED**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest `
  openbb_platform\core\tests\app\test_provider_interface.py `
  -k return_annotations_are_importable -q
```

Expected: failure because `OBBject_EtfCountries` is not an attribute of
`openbb_core.app.provider_interface`.

- [ ] **Step 3: Implement the minimal generic export**

In `_generate_return_annotations`, create the model with `__module__=__name__`,
store it in the annotation map, and bind it into `globals()` under its generated
class name. Do not catch model-construction errors.

- [ ] **Step 4: Run focused core tests to verify GREEN**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest `
  openbb_platform\core\tests\app\test_provider_interface.py `
  openbb_platform\core\tests\app\static\test_package_builder.py `
  openbb_platform\core\tests\app\static\utils\test_linters.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the tested contract**

Commit the core implementation and regression test with `Refs #2079` and the
required Copilot co-author trailer.

### Task 2: Verify TechTrade fallback and the real import/live paths

**Files:**
- Verify: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/movers.py`
- Verify: `openbb_platform/extensions/techtrade/tests/unit/test_movers.py`
- Verify: `openbb_platform/extensions/techtrade/tests/integration/test_signals_integration.py`
- Create locally: `.dev-cycle/verify-phase6.log` (untracked evidence)

**Interfaces:**
- Consumes: importable `OBBject_EtfCountries` and existing
  `_resolve_filter_universe(...) -> list[str] | None`
- Produces: unchanged fallback behavior plus a non-compatibility-failing live signal
  invocation

- [ ] **Step 1: Run targeted TechTrade unit suites**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest `
  openbb_platform\extensions\techtrade\tests\unit\test_universe.py `
  openbb_platform\extensions\techtrade\tests\unit\test_movers.py `
  openbb_platform\extensions\techtrade\tests\unit\test_signals.py -q
```

Expected: all tests pass, including the existing resolver-failure fallback test.

- [ ] **Step 2: Run diagnostics**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m ruff check `
  openbb_platform\core\openbb_core\app\provider_interface.py `
  openbb_platform\core\tests\app\test_provider_interface.py
```

Expected: no diagnostics.

- [ ] **Step 3: Run the fresh-process compatibility harness**

Initialize `ProviderInterface`, import `OBBject_EtfCountries` through normal Python
import semantics, print its qualified name, and write stdout to
`.dev-cycle/verify-phase6.log`.

Expected output includes:

```text
openbb_core.app.provider_interface.OBBject_EtfCountries
```

- [ ] **Step 4: Run the opt-in live signal integration test**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest `
  openbb_platform\extensions\techtrade\tests\integration\test_signals_integration.py -q
```

Expected: pass when credentials and live data are available, otherwise a documented
skip. It must not fail with an `OBBject_EtfCountries` import error.

- [ ] **Step 5: Review, ship, and converge**

Run simplification, diagnostics, code review, and security review. Commit any
review fixes, push the branch, open one PR targeting `portfolio` with a standalone
`Closes #2079` line, resolve all current-head findings and review threads, wait for
required checks, merge, verify #2079 closed, and remove local cycle artifacts.
