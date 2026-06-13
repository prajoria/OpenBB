# techtrade Extension Scaffold (#65) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `openbb-techtrade` extension skeleton so `obb.techtrade.*` resolves and `openbb.build()` stays green — satisfying GitHub issue #65 (Sprint 0 root).

**Architecture:** A pure-compute OpenBB extension (no data provider) that mirrors the on-disk shape of the existing `backtest` and `technical` extensions: a top-level `techtrade_router.py` that lazily includes stub sub-routers, plus `models.py`/`helpers.py`/`py.typed` placeholders and empty `engine/`, `reporting/`, `validation/`, `strategies/` packages. Only the skeleton + entry point + one `about` command ship here; real logic (movers, indicators, confluence, plans) lands in #66+ per the PRD roadmap §18.

**Tech Stack:** Python 3.12, Poetry-style `pyproject.toml`, `openbb-core` extension entry points (`openbb_core_extension`), pydantic v2, pytest. Env: `.venv_win`.

---

## Critical Design Constraint (codegen safety) — READ FIRST

The merged `backtest` extension has a **codegen bug**: its router commands annotate
`-> OBBject[BacktestAbout]` where `BacktestAbout` is a model the static package builder
**renders as a bare name but never imports**. Result: `import openbb` is fine, but the
first access to `obb.backtest.*` raises `NameError: name 'BacktestAbout' is not defined`.

Verified root cause in `openbb_core/app/static/package_builder.py`:
- `build_func_returns` (line ~1650): a bare `OBBject` subclass renders as the string
  `"OBBject"` — **always valid, always importable**.
- An `OBBject[CustomModel]` annotation renders the inner model's bare `__name__` into the
  generated signature **without** emitting a matching import → `NameError`.
- Every working core extension (equity 42 cmds, etf, crypto, …) uses **bare `OBBject`** in
  its generated module and builds green.

**RULE for every command in this scaffold:** annotate the return type as bare `OBBject`
(i.e. `-> OBBject:`), never `OBBject[SomeModel]`. This keeps `obb.techtrade.*` resolvable.
Typed return models are introduced later (#66+) only once we confirm the codegen path for
them (or wrap them so codegen stays green).

**Tracker:** This work is tracked on **GitHub issue #65** (beads has no DB in this
checkout). Reference #65 in the final commit; do not invent a beads ID.

**Branch:** Work directly on `trading_technicals` (user-chosen). No worktree.

---

## File Structure

All paths under `openbb_platform/extensions/techtrade/`:

| File | Responsibility |
|---|---|
| `openbb_techtrade/__init__.py` | Package marker + `__version__`. |
| `openbb_techtrade/py.typed` | PEP 561 typing marker (empty). |
| `openbb_techtrade/techtrade_router.py` | Top-level `Router`; lazily includes sub-routers; defines the `about` command (bare `OBBject`). |
| `openbb_techtrade/helpers.py` | Placeholder for df<->Data plumbing (empty stub for now). |
| `openbb_techtrade/models.py` | Placeholder module docstring only (real models = #66). |
| `openbb_techtrade/engine/__init__.py` | Empty package marker (screener/indicators/confluence/rules/execution land later). |
| `openbb_techtrade/reporting/__init__.py` | Empty package marker (excel_export later). |
| `openbb_techtrade/validation/__init__.py` | Empty package marker (backtest_bridge later). |
| `openbb_techtrade/strategies/__init__.py` | Empty package marker (presets later). |
| `pyproject.toml` | Package metadata + `openbb_core_extension` entry point + extras stubs. |
| `README.md` | One-paragraph extension description. |
| `tests/__init__.py` | Test package marker. |
| `tests/unit/__init__.py` | Unit test package marker. |
| `tests/unit/test_scaffolding.py` | Asserts package + router import, version, and command presence. |

Modified outside the extension:
- `openbb_platform/dev_install.py` — add the editable path entry so dev installs wire techtrade.

> **Out of scope for #65** (do NOT create here — they belong to later issues):
> `engine/*.py` logic, `reporting/excel_export.py`, `tuning/`, `agent/`, `external/`
> (pandas-ta-classic submodule = #67), real `models.py` content = #66.

---

## Task 1: Package skeleton + version + scaffolding test (RED first)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/py.typed`
- Create: `openbb_platform/extensions/techtrade/tests/__init__.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/__init__.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py`

- [ ] **Step 1: Write the failing test**

Create `openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py`:

```python
"""Unit tests for techtrade scaffolding: package + router imports, command surface."""

from __future__ import annotations


def test_package_imports():
    import openbb_techtrade

    assert openbb_techtrade.__version__


def test_core_modules_import():
    # Leaf modules must import without heavy/optional dependencies.
    import openbb_techtrade.helpers  # noqa: F401
    import openbb_techtrade.models  # noqa: F401


def test_subpackages_import():
    import openbb_techtrade.engine  # noqa: F401
    import openbb_techtrade.reporting  # noqa: F401
    import openbb_techtrade.strategies  # noqa: F401
    import openbb_techtrade.validation  # noqa: F401


def test_router_exposes_about():
    from openbb_techtrade.techtrade_router import router

    # Verified Router API in this checkout: commands are FastAPI routes on
    # `router.api_router.routes`, each with a `.path` like "/about".
    paths = {getattr(route, "path", None) for route in router.api_router.routes}
    assert "/about" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'openbb_techtrade'`

- [ ] **Step 3: Create the package marker**

Create `openbb_platform/extensions/techtrade/openbb_techtrade/__init__.py`:

```python
"""OpenBB techtrade extension — segment-aware technical-indicator trading engine."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Create the typing marker and package markers**

Create empty `openbb_platform/extensions/techtrade/openbb_techtrade/py.typed` (0 bytes).

Create `openbb_platform/extensions/techtrade/tests/__init__.py` with a single line:

```python
"""techtrade extension test suite."""
```

Create `openbb_platform/extensions/techtrade/tests/unit/__init__.py` with a single line:

```python
"""techtrade unit tests."""
```

- [ ] **Step 5: Re-run the test (still expected to fail, but further along)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py -q`
Expected: FAIL — now on `import openbb_techtrade.helpers` / `.models` / `.engine` (next task creates them). `test_package_imports` should PASS.

---

## Task 2: Leaf modules + empty subpackages

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/helpers.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/models.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/reporting/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/validation/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/strategies/__init__.py`

- [ ] **Step 1: Create `helpers.py` placeholder**

```python
"""Helper utilities for the techtrade engine.

df<->Data plumbing, alignment, and returns helpers land here as the engine
sub-modules are implemented (see PRD §9.1). Intentionally empty in the scaffold.
"""

from __future__ import annotations
```

- [ ] **Step 2: Create `models.py` placeholder**

```python
"""Core Pydantic Data models for techtrade (see PRD §9.3).

The full model set (SegmentConfig, MoverList, IndicatorPanel, IndicatorVote,
MoverSignal, EntryExitRule, Order, Fill, TradePlan, Recommendation, ExportConfig)
is implemented in issue #66. This module is an intentional placeholder so the
package import graph is complete in the scaffold.
"""

from __future__ import annotations
```

- [ ] **Step 3: Create the four empty subpackage markers**

`engine/__init__.py`:

```python
"""techtrade engine: screener, indicators, confluence, rules, execution (PRD §9.1)."""
```

`reporting/__init__.py`:

```python
"""techtrade reporting: multi-sheet Excel recommendation export (PRD §14.3)."""
```

`validation/__init__.py`:

```python
"""techtrade validation: bridge to openbb-backtest robustness checks (PRD §15)."""
```

`strategies/__init__.py`:

```python
"""techtrade strategies: curated confluence presets (PRD §12.3)."""
```

- [ ] **Step 4: Run the module-import tests**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py::test_core_modules_import openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py::test_subpackages_import -q`
Expected: PASS (2 passed). `test_router_exposes_about` still fails (no router yet).

---

## Task 3: Top-level router + sub-router stubs + `about` command

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py`

The router lazily includes sub-routers (mirrors backtest's `_include_subrouters` resilience
pattern) and defines a single `about` command. **The `about` command returns bare `OBBject`**
per the Critical Design Constraint — NOT `OBBject[SomeModel]`.

- [ ] **Step 1: Create `techtrade_router.py`**

```python
"""Top-level techtrade router.

Assembles the public ``obb.techtrade.*`` surface. Sub-routers (segments/movers,
signals, plan/scan/orders, simulate, export, validate) are attached lazily inside
:func:`_include_subrouters` as each is implemented per the PRD roadmap (§18); a
missing optional sub-router is skipped so the extension imports cleanly during
incremental development.

The ``about`` command returns a bare ``OBBject`` (no parametrized model) so the
static package builder renders a valid, importable return annotation — see
``docs/superpowers/plans/2026-06-13-techtrade-scaffold.md`` (Critical Design
Constraint) and ``package_builder.build_func_returns``.

See PRD §9.1 (layout) and §9.2 (command surface).
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="", description="Segment-aware technical-indicator trading engine.")


def _include_subrouters() -> None:
    """Lazily attach sub-routers as their components are implemented.

    Each entry is attempted once its module exists; missing optional sub-routers
    are skipped so the extension imports cleanly during incremental development
    (PRD roadmap §18: P1 screener, P3 signals, P4 plan/orders, P5 export, ...).
    """
    for module_path, attr in (
        ("openbb_techtrade.engine.screener_router", "router"),
        ("openbb_techtrade.engine.signals_router", "router"),
        ("openbb_techtrade.engine.plan_router", "router"),
        ("openbb_techtrade.reporting.export_router", "router"),
        ("openbb_techtrade.validation.validate_router", "router"),
    ):
        try:
            module = import_module(module_path)
        except ImportError:
            continue
        router.include_router(getattr(module, attr))


_include_subrouters()


@router.command(methods=["GET"])
def about() -> OBBject:
    """Return techtrade extension metadata.

    Returns
    -------
    OBBject
        An OBBject whose ``results`` is a dict of extension name + version.
    """
    try:
        ext_version = version("openbb-techtrade")
    except PackageNotFoundError:
        ext_version = "0.0.0"
    return OBBject(
        results={"extension_name": "techtrade", "extension_version": ext_version}
    )
```

- [ ] **Step 2: Run the full scaffolding test file**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scaffolding.py -q`
Expected: PASS (4 passed). The `test_router_exposes_about` assertion uses the
verified Router API (`router.api_router.routes` → each route's `.path` == `/about`);
no adjustment should be needed.

- [ ] **Step 3: Commit progress**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade openbb_platform/extensions/techtrade/tests
git commit -m "feat(techtrade): scaffold package, router, and about command (#65)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: pyproject.toml + README + entry point

**Files:**
- Create: `openbb_platform/extensions/techtrade/pyproject.toml`
- Create: `openbb_platform/extensions/techtrade/README.md`

- [ ] **Step 1: Create `pyproject.toml`**

Mirrors the backtest extension's structure; declares the `openbb_core_extension`
entry point and the PRD §9.1 extras stubs. `openpyxl` is a real dep (Excel export,
P5) but harmless to declare now; keep the heavy/optional libs as extras.

```toml
[tool.poetry]
name = "openbb-techtrade"
version = "0.1.0"
description = "Segment-aware technical-indicator trading engine extension for OpenBB"
authors = ["Prashant Rajoria"]
license = "AGPL-3.0-only"
readme = "README.md"
packages = [{ include = "openbb_techtrade" }]

[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-core = "^1.6.10"
pandas = "*"
numpy = "*"

[tool.poetry.extras]
# tuneta -> MIT, optional per-segment indicator tuning (PRD §12.4, issue #83)
# talib  -> BSD, optional C-acceleration backend for pandas-ta-classic
# agent  -> optional reasoning / MCP tool surface (PRD §16, issues #84/#85)

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.poetry.plugins."openbb_core_extension"]
techtrade = "openbb_techtrade.techtrade_router:router"
```

> Note: `openbb-core = "^1.6.10"` matches THIS checkout's core (verified during the
> backtest clean-env work). Do not copy backtest's `^1.5.8` — that was the sibling's
> version and is stale here.

- [ ] **Step 2: Create `README.md`**

```markdown
# openbb-techtrade

Segment-aware technical-indicator trading engine for the OpenBB Platform.

Maps GICS sectors to universes, ranks top movers, computes a `pandas-ta-classic`
indicator panel, fuses indicators via weighted confluence voting into an explainable
signal, builds risk-based trade plans with paper-filled recommendations, exports a
multi-sheet Excel workbook, and (optionally) validates robustness via `openbb-backtest`.

Status: **scaffold** (issue #65). See `docs/Specs/TechnicalTrading-Engine-PRD.md` for the
full functional spec and `docs/superpowers/plans/` for the delivery roadmap.

Public surface (incremental): `obb.techtrade.segments / movers / signals / plan / scan /
orders / simulate / export / validate / tune`.
```

- [ ] **Step 3: Verify the entry point parses**

Run: `.venv_win\Scripts\python.exe -c "import tomllib; d=tomllib.load(open('openbb_platform/extensions/techtrade/pyproject.toml','rb')); print(d['tool']['poetry']['plugins']['openbb_core_extension'])"`
Expected: `{'techtrade': 'openbb_techtrade.techtrade_router:router'}`

---

## Task 5: Wire editable install + register the extension

**Files:**
- Modify: `openbb_platform/dev_install.py` (add techtrade to `LOCAL_DEPS`)

- [ ] **Step 1: Add techtrade to `dev_install.py` LOCAL_DEPS**

In `openbb_platform/dev_install.py`, find the core-extension block (the lines adding
`openbb-equity`, `openbb-etf`, etc. around line 48-54). Add immediately after the
`openbb-etf` line:

```python
openbb-techtrade = { path = "./extensions/techtrade", develop = true }
```

(Insert it inside the `LOCAL_DEPS` triple-quoted TOML string, matching the existing
indentation and `develop = true` style.)

- [ ] **Step 2: Editable-install just the new extension into `.venv_win`**

The full `dev_install.py` is slow; install techtrade directly for the fast loop:

Run: `.venv_win\Scripts\python.exe -m pip install -e openbb_platform/extensions/techtrade`
Expected: `Successfully installed openbb-techtrade-0.1.0`

- [ ] **Step 3: Confirm the extension is importable as an installed package**

Run: `.venv_win\Scripts\python.exe -c "import openbb_techtrade; print('techtrade', openbb_techtrade.__version__)"`
Expected: `techtrade 0.1.0`

---

## Task 6: Green build + `obb.techtrade` resolves (Acceptance Gate)

This is issue #65's acceptance criteria: build succeeds AND the namespace resolves.

- [ ] **Step 1: Rebuild the static package**

Run: `.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"`
Expected: exit 0; "Extensions to add:" line includes `techtrade@0.1.0`.

- [ ] **Step 2: Confirm `import openbb` is still clean**

Run: `.venv_win\Scripts\python.exe -c "from openbb import obb; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Confirm `obb.techtrade` namespace resolves and `about` runs**

Run: `.venv_win\Scripts\python.exe -c "from openbb import obb; print('has techtrade:', hasattr(obb, 'techtrade')); print(obb.techtrade.about().results)"`
Expected: `has techtrade: True` then `{'extension_name': 'techtrade', 'extension_version': '0.1.0'}`
**This is the line that proves we avoided the backtest `NameError` trap.**

- [ ] **Step 4: Inspect the generated module is codegen-clean**

Run: `.venv_win\Scripts\python.exe -c "import re,io; s=open('openbb_platform/core/openbb/package/techtrade.py').read(); import sys; sys.exit(0 if '-> OBBject:' in s and 'OBBject[' not in s else 1); "` ; then `echo "codegen clean exit=$?"`
Expected: `codegen clean exit=0` (return type is bare `OBBject`, no unimported model param).

---

## Task 7: Lint + type checks + final commit

- [ ] **Step 1: Ruff (line-length 122 per root `ruff.toml`)**

Run: `.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/techtrade`
Expected: `All checks passed!` (if ruff not installed: `.venv_win\Scripts\python.exe -m pip install ruff` first — it was already present in the clean env).
Fix any reported issues, re-run until clean.

- [ ] **Step 2: Run the full techtrade unit suite once more**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit -q`
Expected: `4 passed`.

- [ ] **Step 3: Confirm no regression in backtest unit suite (shared env sanity)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/backtest/tests/unit -q`
Expected: `431 passed` (unchanged from the clean-env baseline).

- [ ] **Step 4: Review the generated package file is NOT staged**

Run: `git status --porcelain openbb_platform/core/openbb/package/`
The generated `techtrade.py` / `reference.json` churn must NOT be committed (they are
build artifacts). If they appear, `git restore` them before committing.

- [ ] **Step 5: Final commit (only source + dev_install + plan + pyproject + README)**

```bash
git add openbb_platform/extensions/techtrade openbb_platform/dev_install.py docs/superpowers/plans/2026-06-13-techtrade-scaffold.md
git restore --staged openbb_platform/core/openbb/package/ 2>/dev/null || true
git commit -m "feat(techtrade): scaffold extension, entry point, green build (#65)

Create the openbb-techtrade extension skeleton per PRD §9.1: package, top-level
router with lazy sub-router includes, an about command returning bare OBBject
(codegen-safe — avoids the backtest OBBject[Model] NameError trap), placeholder
models/helpers, empty engine/reporting/validation/strategies subpackages,
pyproject entry point + extras stubs, and dev_install wiring.

Acceptance (#65): openbb.build() green; obb.techtrade resolves; about() runs;
ruff clean; 4 scaffolding tests pass; backtest suite unaffected (431 passed).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 6: Report status (do NOT push without user confirmation)**

Summarize: files created, test output shown, build/namespace evidence, and that #65's
acceptance criteria are met. Ask the user before `git push` and before closing issue #65.

---

## Self-Review Notes

**Spec coverage (#65 acceptance criteria):**
- "`python -c "import openbb; openbb.build()"` succeeds" → Task 6 Step 1. ✓
- "`obb.techtrade` namespace resolves (stubs OK)" → Task 6 Step 3. ✓
- "Ruff (line-length 122) + mypy clean" → Task 7 Step 1 (ruff). mypy: the scaffold is
  near-trivial typed code; if a mypy config exists for extensions, run
  `.venv_win\Scripts\python.exe -m mypy openbb_platform/extensions/techtrade/openbb_techtrade`
  and fix. (No project-wide mypy gate was found wired for extensions; ruff is the
  enforced gate. Treat mypy as best-effort and note any unconfigured state.)
- "package per §9.1 (router, models.py, helpers.py, py.typed, engine/, reporting/,
  validation/, strategies/)" → Tasks 1–3. ✓ (`tuning/` and `agent/` are PRD-optional
  and explicitly deferred to #83/#84/#85; `external/` submodule = #67.)
- "techtrade_router.py top-level Router with stub sub-routers" → Task 3. ✓
- "pyproject.toml with entry point + extras stubs" → Task 4. ✓
- "Editable dev install wires the extension" → Task 5. ✓

**Type consistency:** `router` is the exported symbol in every sub-router path listed in
`_include_subrouters`; `about` returns bare `OBBject`; `__version__ = "0.1.0"` matches
`pyproject` version and the `about()` fallback path.

**Placeholder scan:** No "TODO/implement later" left as *executable* gaps — the empty
modules are intentional, documented scaffolding (their emptiness IS the deliverable for
#65), and every code step shows complete content.

**Deferred (filed against later issues, not this plan):**
- Real `models.py` content → #66.
- `external/pandas-ta-classic` submodule → #67.
- Sub-router logic (screener/signals/plan/export/validate) → #70/#75/#77/#81/#82.
