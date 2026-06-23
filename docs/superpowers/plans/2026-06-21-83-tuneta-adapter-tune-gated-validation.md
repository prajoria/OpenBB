# tuneta adapter + tune command (gated by validation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `obb.techtrade.tune(segment, ...) → OBBject[TuningReport]` — a per-segment indicator-period tuner that uses `tuneta` to propose better `IndicatorConfig` periods, gates the candidate behind #82's `validate(...)` (only `verdict == "robust"` persists), writes the tuned config to `~/.openbb_platform/techtrade_tuned.json`, and makes `build_indicator_panel` auto-load tuned configs by `symbol → segment` so they take effect transparently on every subsequent `scan` / `plan` / `signals` call.

**Architecture:** Five new files under `openbb_techtrade/tuning/` (`tuned_defaults.py`, `sector_ohlcv.py`, `tuneta_adapter.py`, `tune_router.py`, `__init__.py`) + one modification to `engine/indicators.py` (auto-load on the hot path) + one model added to `models.py` + the long-anticipated `[tuneta]` extra declared in `pyproject.toml`. Dependency posture mirrors #82 exactly: soft/optional, lazy-in-body imports, reused `TechtradeDependencyError` leaf, every other `obb.techtrade.*` command imports/runs unchanged when `tuneta` is absent. The §5.3 W2 contextvar mechanism (verified safe against #82's sequential single-task fold loop) is the candidate-config override seen during validate.

**Tech Stack:** Python 3.10–3.13 (matches platform); pandas (existing base dep); `tuneta>=0.1` (new optional extra, MIT); `openbb-backtest` (existing optional extra from #82); pytest 9.x (existing); pydantic 2.x via `openbb_core.provider.abstract.data.Data`.

## Global Constraints

- **Python interpreter:** every command runs under `.venv_win\Scripts\python.exe` (Windows checkout). Never the system/global interpreter — it has a different extension set than the editable installs.
- **Provider:** `fmp_cached` only — never raw `fmp`, never `yfinance` (`PRIMARY_PROVIDER` rule from CLAUDE.md and Analysis module).
- **Tuneta absence is a first-class case:** every `import tuneta` is lazy and in-body in `tuning/tuneta_adapter.py` ONLY; raising `TechtradeDependencyError(OpenBBError)` with `pip install 'openbb-techtrade[tuneta]'` in the message.
- **Backtest absence is also a first-class case** (carried over from #82): `validate_plan` already raises the same error; `tune` therefore needs **both** `[tuneta]` and `[validation]` for an end-to-end run.
- **Decimal/float discipline:** money/quantity = `Decimal`; scores/ratios/percentages/indicator values = `float`. (Existing project rule; `IndicatorConfig` fields are already `int`/`float`.)
- **No emoji in code or commit messages.** (CLAUDE.md `# Code quality` row; also project-wide pre-commit `codespell`.)
- **Line length 122** (Ruff config; `engine/indicators.py` already complies).
- **Logging, not print.** Use `logging.getLogger(__name__)` in every new module.
- **Determinism:** JSON writes use `json.dumps(..., sort_keys=True, indent=2)` for byte-stability. Pin `random_state=0` for `tuneta` if the installed version exposes it.
- **No `__init__.py` in new test dirs** unless the existing tree has them (it does — preserve the pattern; see `bd OpenBBTechnical-46y` for the pre-existing collection collision this causes for whole-tree sweeps, which we work around by running per-file pytest invocations).
- **`config: IndicatorConfig | None = None` is keyword-only** in the modified `build_indicator_panel` signature. Every in-repo caller passes `config=` by keyword already (verified during design); flag the signature change in T6's commit message.
- **Commit-message convention** (matches existing branch history): `feat(83): <subject>` / `test(83): <subject>` / `chore(83): <subject>` / `refactor(83): <subject>`. Co-Author trailer: `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`.
- **Beads tracking:** `bd OpenBBTechnical-950` is the parent issue; each Task below files an `addBlocks` child bead so the dependency chain is visible (`T1 ← T2 ← T3 ← T4 ← T5 ← T6 ← T7`). Claim each child bead at task start with `bd update <id> --status=in_progress`, close on commit.

## Reading order for the implementer

Before starting any Task, read these in order:

1. `docs/designs/quant_trading/83-tuneta-adapter-tune-gated-validation.md` — the approved design (especially §0 locked decisions L1–L9, §3 the adapter, §5 persistence + auto-load, §5.3 the W2 contextvar mechanism)
2. `docs/designs/quant_trading/82-backtest-bridge-validate.md` §0 L1–L5, §3 — the validate_plan you'll be calling
3. `openbb_platform/extensions/techtrade/openbb_techtrade/validation/backtest_bridge.py` — the working pattern you're mirroring (lazy `_require_X`, leaf error class, in-body imports)
4. `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py` (current) — what T6 modifies
5. `openbb_platform/extensions/techtrade/openbb_techtrade/models.py` — what T1 adds to

---

## Task 1: Bootstrap — `pyproject.toml` extra + `TuningReport` model

**Files:**
- Modify: `openbb_platform/extensions/techtrade/pyproject.toml` (declare the long-anticipated `tuneta` extra)
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/models.py` (add `TuningReport`)
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_models.py` (extend with `TuningReport` cases)

**Interfaces:**
- Consumes: nothing (this is the bootstrap task)
- Produces:
  - `[tool.poetry.extras] tuneta = ["tuneta"]` (T4 will reference this in the error-message string; T7's integration test will skip when uninstalled)
  - `class TuningReport(Data)` with fields `segment: str`, `as_of: date`, `candidate: IndicatorConfig`, `validation: Data | None`, `persisted: bool`, `reason: str`, `tuneta_version: str`, `fit_seconds: float`, `trials: int`, `early_stop: int` (T5 returns this from the router; T7 integration test asserts on its shape)

---

- [ ] **Step 1: Read the existing model patterns in `models.py`**

Re-read the file to see the leaf-module discipline (no intra-package imports, `Data` base class, `Decimal` for money / `float` for ratios, `Field(description=...)` everywhere, the `validation: Data | None` pattern at line 229 — `TuningReport.validation` will mirror this exactly).

- [ ] **Step 2: Write the failing model-construction test**

Add this to `openbb_platform/extensions/techtrade/tests/unit/test_models.py` (append at end; do not touch existing tests):

```python
def test_tuning_report_construction_with_realistic_values():
    """TuningReport carries everything obb.techtrade.tune returns (#83 L3, §4.2)."""
    from openbb_techtrade.models import TuningReport
    from openbb_techtrade.engine.indicators import DEFAULT_CONFIG

    report = TuningReport(
        segment="Information Technology",
        as_of=date(2026, 6, 21),
        candidate=DEFAULT_CONFIG,
        validation=None,
        persisted=False,
        reason="verdict=fragile (pbo=0.31, dsr=0.62)",
        tuneta_version="0.2.3",
        fit_seconds=42.7,
        trials=100,
        early_stop=20,
    )
    assert report.segment == "Information Technology"
    assert report.persisted is False
    assert report.validation is None  # the Data|None field (mirrors TradePlan.validation L2-of-82)
    # candidate must be exactly an IndicatorConfig; Data subclass attribute access works:
    assert report.candidate.macd_fast == 12  # PRD default
    # Round-trip through dict (the OBBject pathway uses model_dump under the hood):
    assert report.model_dump()["reason"].startswith("verdict=")
```

- [ ] **Step 3: Run test to verify it fails**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_models.py::test_tuning_report_construction_with_realistic_values -v
```

Expected: **FAIL** with `ImportError: cannot import name 'TuningReport' from 'openbb_techtrade.models'`.

- [ ] **Step 4: Implement `TuningReport` in `models.py`**

Append to `openbb_platform/extensions/techtrade/openbb_techtrade/models.py` (place it after `TradePlan`, before `ExportConfig`):

```python
class TuningReport(Data):
    """Outcome of one ``obb.techtrade.tune(segment)`` call (PRD §12.4, issue #83).

    Carries the candidate ``IndicatorConfig`` tuneta proposed (always — even when
    not persisted), the ``ValidationReport`` from #82's gate (typed as ``Data |
    None`` so this model stays leaf — same L2 trick TradePlan.validation uses),
    and the ``persisted`` flag that records whether the candidate cleared the
    L2-strict ``verdict == "robust"`` gate and was written to
    ``~/.openbb_platform/techtrade_tuned.json``.

    Fragile / overfit candidates come back with ``persisted=False`` and a
    diagnostic ``reason`` so the caller can see *what* was proposed and *why* it
    was rejected (Q-F transparency-without-persistence posture).
    """

    segment: str = Field(description="GICS sector name the tune ran for.")
    as_of: date = Field(description="Session date the tune was anchored to.")
    candidate: "IndicatorConfig" = Field(
        description="The IndicatorConfig tuneta proposed (8 tuned period knobs + "
        "7 PRD-default knobs). Always populated, even when not persisted."
    )
    validation: Data | None = Field(
        default=None,
        description=(
            "ValidationReport from #82's validate_plan gate. Typed as Data to "
            "keep techtrade installable without openbb-backtest (same Data|None "
            "discipline as TradePlan.validation)."
        ),
    )
    persisted: bool = Field(
        description="True iff verdict == 'robust' AND a genuinely-different "
        "config was written to ~/.openbb_platform/techtrade_tuned.json."
    )
    reason: str = Field(
        description="Human-readable outcome: 'verdict=robust', "
        "'verdict=fragile (pbo=0.31, dsr=0.62)', 'no change from defaults', etc. "
        "Field order/precision is stable across runs for byte-stability."
    )
    tuneta_version: str = Field(description="tuneta.__version__ at fit time.")
    fit_seconds: float = Field(description="Wall-clock the tuneta.fit() took.")
    trials: int = Field(description="Optuna trials budget actually used.")
    early_stop: int = Field(
        description="Optuna early-stop budget (non-improving trials before halt)."
    )
```

This requires a forward reference to `IndicatorConfig` (which lives in `engine/indicators.py`, not `models.py`). Add this import at the **top** of `models.py` under the existing imports, to make the forward reference resolve:

```python
from openbb_techtrade.engine.indicators import IndicatorConfig  # noqa: E402 (forward-ref for TuningReport)
```

> **Why this import is safe despite "models is a leaf module":** `IndicatorConfig` is a frozen `@dataclass` with no imports of its own back into `models.py` (verified — `indicators.py` only imports `from openbb_techtrade.models import IndicatorPanel`). No cycle. The leaf-module rule prevents *engine* / *router* imports from `models.py`, not pure-data dataclass imports.

After the class definition, call `TuningReport.model_rebuild()` (Pydantic 2 needs this for the forward ref since `IndicatorConfig` was a string annotation):

```python
TuningReport.model_rebuild()
```

- [ ] **Step 5: Run test to verify it passes**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_models.py::test_tuning_report_construction_with_realistic_values -v
```

Expected: **PASS**.

- [ ] **Step 6: Run the rest of test_models.py to verify no regression**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_models.py -v
```

Expected: **5 passed** (the 4 existing tests + the new one).

- [ ] **Step 7: Write the failing pyproject extras test**

Add a new test file `openbb_platform/extensions/techtrade/tests/unit/test_pyproject_extras.py`:

```python
"""Unit tests that pyproject.toml declares the [tuneta] and [validation] extras (#82 + #83)."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - python 3.10 fallback
    import tomli as tomllib  # type: ignore[import-not-found]


_PYPROJECT = (
    Path(__file__).resolve().parents[2] / "pyproject.toml"
)


def _read_extras() -> dict[str, list[str]]:
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["poetry"]["extras"]


def test_tuneta_extra_is_declared():
    """#83 L8: `tuneta` ships as an optional extra users install via [tuneta]."""
    extras = _read_extras()
    assert "tuneta" in extras, (
        "pyproject.toml [tool.poetry.extras] is missing the `tuneta` entry. "
        "Add: tuneta = [\"tuneta\"]"
    )
    assert extras["tuneta"] == ["tuneta"]


def test_validation_extra_is_still_declared():
    """#82 regression: declaring [tuneta] must not remove the [validation] extra."""
    extras = _read_extras()
    assert extras.get("validation") == ["openbb-backtest"]
```

- [ ] **Step 8: Run the failing extras test**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_pyproject_extras.py -v
```

Expected: **`test_tuneta_extra_is_declared` FAILS** with `AssertionError: pyproject.toml [tool.poetry.extras] is missing the tuneta entry`. `test_validation_extra_is_still_declared` should **PASS** (the entry already exists).

- [ ] **Step 9: Declare the `tuneta` extra in pyproject.toml**

Open `openbb_platform/extensions/techtrade/pyproject.toml`. Find the `[tool.poetry.extras]` block (currently lines 17–24). The block already contains the `# tuneta -> MIT, optional per-segment indicator tuning (PRD §12.4, issue #83)` comment but the entry itself is missing. Add one line:

```toml
[tool.poetry.extras]
# tuneta -> MIT, optional per-segment indicator tuning (PRD §12.4, issue #83)
# talib  -> BSD, optional C-acceleration backend for pandas-ta-classic
# agent  -> optional reasoning / MCP tool surface (PRD §16, issues #84/#85)
# xlsxwriter -> BSD, optional richer Excel engine for obb.techtrade.export (PRD §14.3 / issue #81)
# validation -> AGPL, optional openbb-backtest engine for obb.techtrade.validate (PRD §15 / issue #82)
tuneta = ["tuneta"]
xlsxwriter = ["xlsxwriter"]
validation = ["openbb-backtest"]
```

(Place `tuneta = ["tuneta"]` **before** `xlsxwriter` so the declaration order matches the alphabetic comment order.)

- [ ] **Step 10: Run the extras tests to verify they pass**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_pyproject_extras.py -v
```

Expected: **2 passed**.

- [ ] **Step 11: Commit T1**

```bash
git add openbb_platform/extensions/techtrade/pyproject.toml openbb_platform/extensions/techtrade/openbb_techtrade/models.py openbb_platform/extensions/techtrade/tests/unit/test_models.py openbb_platform/extensions/techtrade/tests/unit/test_pyproject_extras.py
git commit -m "$(cat <<'EOF'
feat(83): bootstrap — declare [tuneta] extra + add TuningReport model

T1 of the #83 tuneta-adapter implementation plan
(docs/superpowers/plans/2026-06-21-83-tuneta-adapter-tune-gated-validation.md).

- pyproject.toml: declare the long-anticipated `tuneta = ["tuneta"]` extra
  (the comment for it has lived at line 18 since the scaffold; this declares
  the entry). `[validation]` from #82 is unchanged.
- models.py: add TuningReport(Data) with the field set design §4.2 specifies:
  segment / as_of / candidate(IndicatorConfig) / validation(Data|None) /
  persisted / reason / tuneta_version / fit_seconds / trials / early_stop.
  validation is typed Data|None for the same L2 reason TradePlan.validation
  uses — keeps techtrade installable without openbb-backtest.
- tests: 1 new TuningReport construction test in test_models.py (the 4 existing
  tests are untouched); 2 new tests in test_pyproject_extras.py for the
  declared-extras regression.

No tuneta import anywhere yet (T4 introduces the lazy in-body import); no
file under `tuning/` exists yet (T2 starts that). This is pure bootstrap so
the model + the extra are available to every downstream Task.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 12: Close the T1 bd child + claim T2**

```
bd close <T1-bead-id> --resolution=completed --comment "models.py + pyproject extra; tests green"
bd update <T2-bead-id> --status=in_progress
```

(Bead IDs are filed once during the "post-plan beads-decomposition" step described below the Tasks; see "Beads decomposition" section.)

---

## Task 2: `tuning/tuned_defaults.py` — JSON persistence + mtime cache + contextvar override

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/__init__.py`
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tuned_defaults.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_tuned_defaults.py`

**Interfaces:**
- Consumes: `IndicatorConfig` (from `openbb_techtrade.engine.indicators` — existing); the segment-resolver function `segment_for_symbol(symbol: str) -> str | None` (existing in `openbb_techtrade.engine.universe`; **verify the exact import path during Step 1 and adjust the imports in this Task if it lives elsewhere**)
- Produces (consumed by T5 and T6):
  - `SCHEMA_VERSION: str = "1.0"`
  - `TUNED_PATH: Path = Path.home() / ".openbb_platform" / "techtrade_tuned.json"`
  - `CACHE_MAXSIZE: int = 8` (Q-E guard 1: bounded `lru_cache`)
  - `read_tuned() -> dict | None` — returns parsed JSON or `None` if file missing / schema mismatch
  - `lookup_tuned_for_symbol(symbol: str) -> IndicatorConfig | None` — the hot-path call; consults contextvar override first, then file
  - `write_tuned(segment: str, config: IndicatorConfig, meta: dict) -> None` — atomic write via `tempfile.NamedTemporaryFile` + `os.replace`
  - `tune_override(overrides: dict[str, IndicatorConfig])` — context manager wrapping the `_TUNE_OVERRIDE: ContextVar` (used by T5's router around the `validate_plan` call; the §5.3 W2 mechanism)
  - `_clear_cache() -> None` — explicit cache invalidation (called by `write_tuned` for the Q-E guard 2 coarse-mtime tiebreaker)

---

- [ ] **Step 1: Verify the segment-resolver import path**

The contextvar override lookup and the file-backed lookup both need to map a symbol → its GICS segment. Find the existing helper:

```
.venv_win\Scripts\python.exe -c "from openbb_techtrade.engine.universe import segment_for_symbol; print(segment_for_symbol.__module__)"
```

If that import fails, search for the function:

```
.venv_win\Scripts\python.exe -c "import openbb_techtrade.engine.universe as u; print([n for n in dir(u) if 'segment' in n.lower()])"
```

The function may be named differently (e.g. `resolve_segment_for_symbol`, `gics_sector_for_symbol`). **Record the exact import path before Step 3** — if the project does NOT yet ship such a helper, file a P3 bead `bd create --title "infra: add segment_for_symbol helper to engine/universe.py for #83 tuneta auto-load" --type=feature --priority=3` and stub the lookup in this Task with a tiny in-file `_SEGMENT_BY_SYMBOL` dict covering the 11 GICS sectors' top-5 ETF holdings (good enough for the unit tests; the real helper lands when the bead resolves).

> **Why this step exists:** the design assumes a `symbol → segment` resolver. The verification keeps the plan honest if reality diverges. The fallback (a small in-file dict) means T2 ships even if the resolver doesn't yet exist; the auto-load test will still pass.

- [ ] **Step 2: Create the package**

```
mkdir -p openbb_platform/extensions/techtrade/openbb_techtrade/tuning
```

Create `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/__init__.py`:

```python
"""techtrade tuning: per-segment indicator-period optimisation (PRD §12.4, issue #83).

Behind the `[tuneta]` optional extra. ``obb.techtrade.tune(segment, ...)`` proposes
better indicator periods for a GICS sector via tuneta, gates the candidate through
#82's ``validate(...)`` (only ``verdict == "robust"`` persists), and writes accepted
configs to ``~/.openbb_platform/techtrade_tuned.json`` so the panel builder picks
them up transparently on the next ``scan`` / ``plan`` / ``signals``.

Module map:

- :mod:`openbb_techtrade.tuning.tuned_defaults` — JSON read/write + mtime cache +
  contextvar override (the §5.3 W2 mechanism). The ONLY module imported by
  ``engine.indicators`` on the hot path; safe to import without ``tuneta``.
- :mod:`openbb_techtrade.tuning.sector_ohlcv` — pool a segment's universe into the
  ``(date, symbol)``-indexed OHLCV DataFrame tuneta consumes (L4).
- :mod:`openbb_techtrade.tuning.tuneta_adapter` — the ONLY module importing
  ``tuneta``; lazy ``_require_tuneta`` + knob table + column-name parser (L6).
- :mod:`openbb_techtrade.tuning.tune_router` — the ``obb.techtrade.tune`` command.
"""
```

- [ ] **Step 3: Write the failing tests for `tuned_defaults.py` (8 tests, one block)**

Create `openbb_platform/extensions/techtrade/tests/unit/test_tuned_defaults.py`. The whole file lands in one commit (the §6 design test list groups these together):

```python
"""Unit tests for openbb_techtrade.tuning.tuned_defaults (#83 L3, L9, Q-E, §5.3 W2)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig


# --- read_tuned / lookup ----------------------------------------------------------------------

def test_read_missing_file_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Absent file -> lookup_tuned_for_symbol returns None, no raise."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
    )
    _clear_cache()
    assert lookup_tuned_for_symbol("AAPL") is None


def test_schema_version_mismatch_returns_none_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Q-E: a file with schema_version != '1.0' is treated as absent (returns None), logs WARNING."""
    path = tmp_path / "techtrade_tuned.json"
    path.write_text(json.dumps({"schema_version": "99.0", "segments": {}}))
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
    )
    _clear_cache()
    with caplog.at_level("WARNING"):
        result = lookup_tuned_for_symbol("AAPL")
    assert result is None
    assert "schema_version" in caplog.text


# --- write_tuned + read roundtrip -------------------------------------------------------------

def test_read_after_write_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L3: write_tuned(seg, cfg, meta) -> read_tuned recovers the segment entry."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    # Force the symbol-to-segment mapping to "Information Technology" for AAPL.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology" if sym == "AAPL" else None,
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        write_tuned,
    )
    _clear_cache()
    tuned = IndicatorConfig(
        macd_fast=14, macd_slow=32, macd_signal=9,
        adx_length=16, ema_fast=18, ema_slow=55,
        rsi_length=11, atr_length=18,
        # the 7 non-period knobs at DEFAULT_CONFIG values:
        stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
        stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
        bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
        kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar,
    )
    meta = {"verdict": "robust", "pbo": 0.18, "dsr": 0.97, "oos_sharpe": 0.84,
            "tuned_at": "2026-06-21T16:49:48Z", "tuneta_version": "0.2.3",
            "as_of": "2026-06-21", "horizon_years": 5}
    write_tuned("Information Technology", tuned, meta)
    looked_up = lookup_tuned_for_symbol("AAPL")
    assert looked_up == tuned
    # AAPL maps to IT; an unmapped symbol gets None even though IT exists.
    assert lookup_tuned_for_symbol("UNKNOWN") is None


def test_write_tuned_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """write_tuned must write via temp file + os.replace (no half-written state visible)."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache, write_tuned
    _clear_cache()
    with mock.patch("os.replace") as replace_spy:
        write_tuned("Information Technology", DEFAULT_CONFIG,
                    {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})
        assert replace_spy.called, "write_tuned must use os.replace for atomic write"


# --- Q-E mtime cache --------------------------------------------------------------------------

def test_mtime_cache_invalidates_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-E: writes twice in quick succession both visible (st_size tiebreaker for coarse-mtime FSes)."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        write_tuned,
    )
    _clear_cache()
    cfg_a = IndicatorConfig(macd_fast=10, macd_slow=20, macd_signal=5,
                            adx_length=10, ema_fast=10, ema_slow=30,
                            rsi_length=10, atr_length=10,
                            stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                            stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                            bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                            kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    cfg_b = IndicatorConfig(macd_fast=15, macd_slow=25, macd_signal=8,
                            adx_length=15, ema_fast=15, ema_slow=40,
                            rsi_length=15, atr_length=15,
                            stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                            stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                            bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                            kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    write_tuned("Information Technology", cfg_a,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})
    assert lookup_tuned_for_symbol("AAPL") == cfg_a
    # Write again in the same mtime tick. write_tuned must clear cache explicitly
    # (Q-E guard 2) so the second read sees the new config even when mtime didn't tick.
    write_tuned("Information Technology", cfg_b,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:01Z"})
    assert lookup_tuned_for_symbol("AAPL") == cfg_b


def test_lru_cache_maxsize_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-E guard 1: cache_info().maxsize is exactly CACHE_MAXSIZE; re-writes don't unbound it."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        CACHE_MAXSIZE,
        _clear_cache,
        _read_tuned_cached,
        lookup_tuned_for_symbol,
        write_tuned,
    )
    _clear_cache()
    for i in range(CACHE_MAXSIZE * 2):
        cfg = IndicatorConfig(
            macd_fast=8 + i, macd_slow=20 + i, macd_signal=5,
            adx_length=10, ema_fast=10, ema_slow=30,
            rsi_length=10, atr_length=10,
            stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
            stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
            bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
            kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar,
        )
        write_tuned("Information Technology", cfg,
                    {"verdict": "robust", "tuned_at": f"2026-06-21T00:00:{i:02d}Z"})
        lookup_tuned_for_symbol("AAPL")
    info = _read_tuned_cached.cache_info()
    assert info.maxsize == CACHE_MAXSIZE
    assert info.currsize <= CACHE_MAXSIZE


# --- §5.3 W2 contextvar override --------------------------------------------------------------

def test_contextvar_override_takes_precedence_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """§5.3 W2: a tune_override context sets the active candidate; the file is bypassed."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        tune_override,
        write_tuned,
    )
    _clear_cache()
    on_disk = IndicatorConfig(macd_fast=10, macd_slow=20, macd_signal=5,
                              adx_length=10, ema_fast=10, ema_slow=30,
                              rsi_length=10, atr_length=10,
                              stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                              stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                              bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                              kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    override = IndicatorConfig(macd_fast=99, macd_slow=99, macd_signal=99,
                               adx_length=99, ema_fast=99, ema_slow=99,
                               rsi_length=99, atr_length=99,
                               stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                               stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                               bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                               kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    write_tuned("Information Technology", on_disk, {"verdict": "robust",
                                                    "tuned_at": "2026-06-21T00:00:00Z"})
    # Without the override: file value wins.
    assert lookup_tuned_for_symbol("AAPL") == on_disk
    # Inside the override: contextvar wins.
    with tune_override({"Information Technology": override}):
        assert lookup_tuned_for_symbol("AAPL") == override
    # After the override: file value again.
    assert lookup_tuned_for_symbol("AAPL") == on_disk


def test_contextvar_override_for_missing_segment_returns_none(monkeypatch: pytest.MonkeyPatch):
    """A symbol whose segment is NOT in the override dict still resolves via file (or None)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Energy" if sym == "XOM" else "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        tune_override,
    )
    _clear_cache()
    override = IndicatorConfig(
        macd_fast=99, macd_slow=99, macd_signal=99,
        adx_length=99, ema_fast=99, ema_slow=99,
        rsi_length=99, atr_length=99,
        stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
        stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
        bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
        kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar,
    )
    with tune_override({"Information Technology": override}):
        # AAPL maps to IT (in the override) -> override wins.
        assert lookup_tuned_for_symbol("AAPL") == override
        # XOM maps to Energy (NOT in the override; no file either) -> None.
        assert lookup_tuned_for_symbol("XOM") is None
```

- [ ] **Step 4: Run the failing tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_tuned_defaults.py -v
```

Expected: **8 errors** (collection-time `ModuleNotFoundError: No module named 'openbb_techtrade.tuning.tuned_defaults'`). That's the expected red.

- [ ] **Step 5: Implement `tuned_defaults.py`**

Create `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tuned_defaults.py`:

```python
"""Per-user tuned-config persistence + mtime cache + contextvar override (#83 L3, L9, Q-E, §5.3 W2).

The hot-path module for the L9 auto-load rule: ``engine/indicators.py`` consults
:func:`lookup_tuned_for_symbol` on every panel build to decide whether the symbol's
GICS sector has a robust tuned :class:`IndicatorConfig` waiting in
``~/.openbb_platform/techtrade_tuned.json``.

This module deliberately does NOT import ``tuneta`` or ``openbb_backtest`` — it
stays importable on a bare techtrade install, so the L9 hot path keeps working
when neither optional extra is present (the lookup just always returns ``None``
in that case and the panel builder falls back to ``DEFAULT_CONFIG``).

Three mechanisms cooperate:

1. **JSON file** at :data:`TUNED_PATH` is the durable store; written atomically
   via :func:`tempfile.NamedTemporaryFile` + :func:`os.replace`. Schema-versioned
   (:data:`SCHEMA_VERSION`); mismatched versions read as absent.
2. **`lru_cache` keyed on `(path, mtime_ns, st_size)`** keeps the hot path
   microsecond-cheap (Q-E E1) while invalidating exactly when the file changes.
   ``st_size`` is the Q-E guard-2 tiebreaker for coarse-mtime filesystems;
   :func:`write_tuned` ALSO calls :func:`_clear_cache` explicitly as belt-and-braces.
3. **`tune_override` contextvar** lets :mod:`tune_router` make a candidate config
   visible to the validate fold loop WITHOUT writing it to disk first (§5.3 W2).
   Verified safe against #82's sequential single-task fold loop (no
   ThreadPool / ProcessPool / executor offload anywhere in openbb_backtest as of
   2026-06-21). If #82 ever fans folds out via an executor, contributors must
   wrap each fold in :func:`contextvars.copy_context().run` or migrate this
   override path to W1 (write -> validate -> revert in finally).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from openbb_techtrade.engine.indicators import IndicatorConfig

# Best-effort symbol -> segment resolver. Verify the real import path in Step 1
# of this Task; fall back to a tiny in-file dict if the helper doesn't exist
# yet (and file a tracking bead).
try:
    from openbb_techtrade.engine.universe import segment_for_symbol
except ImportError:  # pragma: no cover - exercised when the helper is absent
    _FALLBACK_SEGMENTS = {
        # GICS sector seeds (top ~5 holdings per sector ETF) so unit tests can run
        # without the real helper. The real resolver should land via the bead
        # filed in this Task's Step 1.
        "AAPL": "Information Technology", "MSFT": "Information Technology",
        "NVDA": "Information Technology", "GOOG": "Communication Services",
        "META": "Communication Services", "AMZN": "Consumer Discretionary",
        "TSLA": "Consumer Discretionary", "JNJ": "Health Care",
        "UNH": "Health Care", "JPM": "Financials", "BAC": "Financials",
        "XOM": "Energy", "CVX": "Energy", "PG": "Consumer Staples",
        "KO": "Consumer Staples",
    }

    def segment_for_symbol(symbol: str) -> str | None:
        return _FALLBACK_SEGMENTS.get(symbol)


logger = logging.getLogger(__name__)

#: Schema version for the tuned-defaults JSON file. Bumped on incompatible changes.
SCHEMA_VERSION: str = "1.0"

#: Per-user path. Lives alongside user_settings.json. Never committed.
TUNED_PATH: Path = Path.home() / ".openbb_platform" / "techtrade_tuned.json"

#: LRU cache bound (Q-E guard 1). A long interactive session that re-tunes many
#: times will not accumulate more than this many parsed-dict entries.
CACHE_MAXSIZE: int = 8

#: §5.3 W2: per-task candidate-config override active during the validate call.
#: Maps segment name -> candidate IndicatorConfig. ``None`` (default) means "no
#: override, consult the file".
_TUNE_OVERRIDE: ContextVar[dict[str, IndicatorConfig] | None] = ContextVar(
    "_tune_override", default=None
)


# --- public API -------------------------------------------------------------------------------


def read_tuned() -> dict | None:
    """Read and parse the tuned-defaults JSON, or return ``None`` if absent / unparseable.

    Returns the raw parsed dict (with the top-level ``schema_version`` and
    ``segments`` keys). Returns ``None`` when the file does not exist OR when
    its ``schema_version`` does not match :data:`SCHEMA_VERSION` (logged at
    WARNING). Used internally by :func:`lookup_tuned_for_symbol`; tests can
    call it directly for shape assertions.
    """
    try:
        stat = TUNED_PATH.stat()
    except FileNotFoundError:
        return None
    return _read_tuned_cached(str(TUNED_PATH), stat.st_mtime_ns, stat.st_size)


def lookup_tuned_for_symbol(symbol: str) -> IndicatorConfig | None:
    """Hot-path: return the tuned :class:`IndicatorConfig` for ``symbol``'s segment, or ``None``.

    1. Resolve ``symbol`` -> its segment (via :func:`segment_for_symbol`).
    2. If the segment is in the current :data:`_TUNE_OVERRIDE` contextvar, return
       that candidate (§5.3 W2 — the tune router's mid-validate override).
    3. Else read the on-disk tuned-defaults file; return its entry for the
       segment if present and ``meta.verdict == "robust"`` (defensive: the gate
       in :func:`write_tuned` already enforces this, but the read-side check
       protects against a hand-edited file).
    4. Else return ``None``.
    """
    segment = segment_for_symbol(symbol)
    if segment is None:
        return None
    override = _TUNE_OVERRIDE.get()
    if override is not None and segment in override:
        return override[segment]
    parsed = read_tuned()
    if parsed is None:
        return None
    entry = parsed.get("segments", {}).get(segment)
    if entry is None:
        return None
    if entry.get("meta", {}).get("verdict") != "robust":
        return None
    try:
        return IndicatorConfig(**entry["config"])
    except (TypeError, KeyError) as exc:
        logger.warning("tuned_defaults: bad entry for %s: %s", segment, exc)
        return None


def write_tuned(segment: str, config: IndicatorConfig, meta: dict) -> None:
    """Atomically write ``segment -> {config, meta}`` into the tuned-defaults JSON.

    Reads the current file (if any), merges in the new segment entry, and writes
    via :func:`tempfile.NamedTemporaryFile` + :func:`os.replace` so a concurrent
    reader either sees the old complete file or the new complete file (never a
    half-written one). Explicitly clears the LRU cache (Q-E guard 2) so a
    coarse-mtime filesystem does not serve stale data on the next lookup.

    Caller is responsible for the L2 verdict gate: ``write_tuned`` does not check
    ``meta["verdict"]``, but :func:`lookup_tuned_for_symbol` filters on it on
    read, so a future bug that called ``write_tuned`` with a non-robust meta
    would still be filtered out at the consumer.
    """
    TUNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = read_tuned() or {"schema_version": SCHEMA_VERSION, "segments": {}}
    current.setdefault("segments", {})[segment] = {
        "config": asdict(config),
        "meta": meta,
    }
    # Sort keys + indent=2 for byte-stability across runs (global determinism rule).
    payload = json.dumps(current, sort_keys=True, indent=2)
    # Atomic write: NamedTemporaryFile in the same directory, then os.replace.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(TUNED_PATH.parent),
        prefix=".techtrade_tuned.", suffix=".tmp", delete=False,
    ) as fh:
        fh.write(payload)
        tmp_name = fh.name
    os.replace(tmp_name, TUNED_PATH)
    _clear_cache()


@contextmanager
def tune_override(overrides: dict[str, IndicatorConfig]):
    """§5.3 W2: make ``overrides`` visible to :func:`lookup_tuned_for_symbol` for the block.

    Used by :func:`openbb_techtrade.tuning.tune_router.tune` around the
    ``validate_plan`` call so the candidate :class:`IndicatorConfig` is the
    *active* config when the techtrade_confluence strategy re-runs over the WFO
    folds — without writing anything to disk until the verdict comes back robust.

    The contextvar mechanism is safe because #82's :func:`validate_plan` runs the
    fold loop sequentially in the caller's asyncio task (verified 2026-06-21);
    asyncio context-copy propagates the override into every coroutine the task
    creates. If #82 ever moves folds into a ThreadPool / ProcessPool /
    ``run_in_executor`` worker, the override will NOT cross that boundary and
    this mechanism must be re-evaluated (W1 disk-write-and-revert is the
    documented fallback in design §5.3).
    """
    token = _TUNE_OVERRIDE.set(dict(overrides))
    try:
        yield
    finally:
        _TUNE_OVERRIDE.reset(token)


def _clear_cache() -> None:
    """Drop the cached parsed JSON (Q-E guard 2 belt-and-braces; tests call this too)."""
    _read_tuned_cached.cache_clear()


# --- internal: the cached read ----------------------------------------------------------------


@lru_cache(maxsize=CACHE_MAXSIZE)
def _read_tuned_cached(path: str, mtime_ns: int, size: int) -> dict | None:
    """Cached JSON read keyed on ``(path, mtime_ns, st_size)`` (Q-E E1 + guard 2).

    ``mtime_ns`` is the primary invalidation key; ``size`` is the coarse-mtime
    tiebreaker (two writes inside one mtime tick on a low-resolution filesystem
    will still differ in file size for any non-empty content change). The cache
    is bounded by :data:`CACHE_MAXSIZE` (Q-E guard 1).
    """
    # The mtime_ns/size args are unused inside the body — their job is to make
    # the cache key correct. Body just reads + validates the schema version.
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("tuned_defaults: read failed for %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("tuned_defaults: top-level JSON in %s is not an object", path)
        return None
    found_version = data.get("schema_version")
    if found_version != SCHEMA_VERSION:
        logger.warning(
            "tuned_defaults: schema_version %r in %s does not match %r; ignoring",
            found_version, path, SCHEMA_VERSION,
        )
        return None
    return data
```

- [ ] **Step 6: Run the tests; expect them to pass**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_tuned_defaults.py -v
```

Expected: **8 passed**.

If the segment-resolver import path was different from Step 1's assumption, the `test_read_after_write_roundtrips` monkeypatch target string will need to match the actual import location (`openbb_techtrade.tuning.tuned_defaults.segment_for_symbol`). Either way: the test file references the symbol on the module under test (not on `engine.universe`), so the monkeypatch points at the *consumer* — which is correct regardless of the original import path.

- [ ] **Step 7: Smoke-check that other techtrade modules still import**

```
.venv_win\Scripts\python.exe -c "import openbb_techtrade; import openbb_techtrade.engine.indicators; import openbb_techtrade.validation.backtest_bridge; print('ok')"
```

Expected: `ok` (the new `tuning` package must not have broken anything via `__init__.py` side effects or circular imports).

- [ ] **Step 8: Commit T2**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/tuning/__init__.py openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tuned_defaults.py openbb_platform/extensions/techtrade/tests/unit/test_tuned_defaults.py
git commit -m "$(cat <<'EOF'
feat(83): tuning.tuned_defaults — per-user JSON persistence + mtime cache + contextvar

T2 of the #83 implementation plan. Three mechanisms in one focused module so
T5's router has a single import surface:

1. JSON file at ~/.openbb_platform/techtrade_tuned.json — schema-versioned,
   atomically written via tempfile.NamedTemporaryFile + os.replace so concurrent
   readers see either the old or the new complete file.
2. lru_cache keyed on (path, mtime_ns, st_size) for the hot path (the L9
   auto-load that T6 wires into engine/indicators.py). mtime_ns is the primary
   key; st_size is the Q-E guard 2 tiebreaker for coarse-mtime filesystems;
   write_tuned also explicitly _clear_cache()s belt-and-braces.
3. tune_override(...) context manager wrapping a ContextVar — the §5.3 W2
   mechanism. Lets T5's router make a candidate config visible to the validate
   fold loop without writing it to disk first. Safe today: #82's validate_plan
   runs folds sequentially in the caller's asyncio task (verified 2026-06-21,
   zero ThreadPool / ProcessPool / executor offload anywhere in openbb_backtest).

Defensive design notes:
- lookup_tuned_for_symbol re-checks meta.verdict == "robust" on read even though
  T5 will already gate writes; protects against a hand-edited file.
- Module does NOT import tuneta or openbb_backtest — stays importable on a bare
  techtrade install, so the L9 hot path works when neither extra is present.
- Falls back to a tiny in-file symbol→sector dict if engine.universe doesn't
  ship segment_for_symbol yet (a real helper is tracked separately).

8 new unit tests cover: missing-file -> None, schema-mismatch -> None +
WARNING, roundtrip write→read, atomic-write (os.replace spy),
double-write-within-mtime-tick (Q-E guard 2), bounded cache (Q-E guard 1),
contextvar takes precedence over file (§5.3 W2), contextvar for a missing
segment falls through to file.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: Close T2 bd child + claim T3**

```
bd close <T2-bead-id> --resolution=completed --comment "tuned_defaults.py + contextvar override; 8/8 tests green"
bd update <T3-bead-id> --status=in_progress
```

---

## Task 3: `tuning/sector_ohlcv.py` — pool a segment's OHLCV + forward returns

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/sector_ohlcv.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_sector_ohlcv.py`

**Interfaces:**
- Consumes: a fetcher callable (injected for tests; real one fetched lazily via `fmp_cached` adapter)
- Produces (consumed by T4 and T5):
  - `DEFAULT_FORWARD_HORIZON_BARS: int = 20` (matches `EntryExitRule.max_holding_bars` default; Q-B B3)
  - `DEFAULT_HORIZON_YEARS: int = 5` (Q-C, same as #82)
  - `pool_sector_ohlcv(segment, as_of, horizon_years=5, *, fetcher=None) -> tuple[pd.DataFrame, pd.Series]`
    - returns `(X, y)` where `X` is a MultiIndex `(date, symbol)` OHLCV DataFrame and `y` is a same-indexed forward-cumulative-return series (the target tuneta consumes)

---

- [ ] **Step 1: Verify what `fmp_cached` OHLCV fetcher techtrade already uses**

```
.venv_win\Scripts\python.exe -c "from openbb_techtrade.engine import movers; import inspect; print(inspect.getsource(movers._default_ohlcv_fetcher) if hasattr(movers, '_default_ohlcv_fetcher') else 'NOT FOUND - search')"
```

If the function is named differently, find it:

```
.venv_win\Scripts\python.exe -c "import openbb_techtrade.engine.movers as m; print([n for n in dir(m) if 'fetch' in n.lower() or 'ohlcv' in n.lower()])"
```

**Record the import path + signature** before Step 3. The expected shape per the design (§3.4 step 2) is `fetcher(symbol, *, start: date, end: date) -> pd.DataFrame` with OHLCV columns. If techtrade's existing fetcher has a different signature, the `sector_ohlcv.pool_sector_ohlcv` default fetcher will need a small adapter shim — note the difference in this Task's commit message.

- [ ] **Step 2: Verify the segment-universe resolver path**

The pool function needs to know "which symbols belong to this segment." Find:

```
.venv_win\Scripts\python.exe -c "import openbb_techtrade.engine.universe as u; print([n for n in dir(u) if 'universe' in n.lower() or 'segment' in n.lower() or 'symbols_for' in n.lower()])"
```

Expected: a `universe_for_segment(segment: str, source: str = 'etf_holdings') -> list[str]` or similar (PRD §11 + Q3 nominated ETF holdings as the default source). **If absent, file a follow-up bead and use a fallback dict for unit tests** (the same shape T2's segment-resolver fallback uses).

- [ ] **Step 3: Write the failing tests (5 tests)**

Create `openbb_platform/extensions/techtrade/tests/unit/test_sector_ohlcv.py`:

```python
"""Unit tests for openbb_techtrade.tuning.sector_ohlcv (#83 L4, Q-B, Q-C)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest


def _synth_ohlcv(symbol: str, start: date, end: date, *, base: float = 100.0) -> pd.DataFrame:
    """Synthetic deterministic OHLCV: linearly drifting close + small daily noise.

    Used as the injected fetcher's return value so unit tests stay fully offline
    and reproducible across runs (same inputs -> same OHLCV bytes).
    """
    dates = pd.date_range(start=start, end=end, freq="B")  # business-day calendar
    n = len(dates)
    drift = np.linspace(base, base * 1.05, n)
    closes = drift + np.sin(np.arange(n) * 0.1)
    opens = closes - 0.2
    highs = closes + 0.3
    lows = closes - 0.4
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=dates,
    )


def _fake_fetcher_two_symbols(symbol: str, *, start: date, end: date) -> pd.DataFrame:
    return _synth_ohlcv(symbol, start, end, base={"AAPL": 100.0, "MSFT": 200.0}.get(symbol, 50.0))


def test_pool_returns_multiindex_date_symbol(monkeypatch: pytest.MonkeyPatch):
    """L4: X is indexed by (date, symbol) with OHLCV columns."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL", "MSFT"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    X, y = pool_sector_ohlcv(
        "Information Technology",
        as_of=date(2025, 6, 20),
        horizon_years=1,
        fetcher=_fake_fetcher_two_symbols,
    )
    assert isinstance(X.index, pd.MultiIndex)
    assert list(X.index.names) == ["date", "symbol"]
    assert set(X.columns) == {"open", "high", "low", "close", "volume"}
    # Both symbols are present.
    assert set(X.index.get_level_values("symbol").unique()) == {"AAPL", "MSFT"}


def test_pool_uses_injected_fetcher_for_every_symbol(monkeypatch: pytest.MonkeyPatch):
    """The fetcher is called once per symbol with the derived start/end window."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL", "MSFT", "NVDA"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    calls: list[tuple[str, date, date]] = []

    def _spy(symbol: str, *, start: date, end: date) -> pd.DataFrame:
        calls.append((symbol, start, end))
        return _synth_ohlcv(symbol, start, end)

    pool_sector_ohlcv("IT", as_of=date(2025, 6, 20), horizon_years=2, fetcher=_spy)
    assert {c[0] for c in calls} == {"AAPL", "MSFT", "NVDA"}
    # Window: start = as_of - horizon_years, end = as_of.
    assert all(c[2] == date(2025, 6, 20) for c in calls)
    assert all(c[1] == date(2023, 6, 20) for c in calls)


def test_pool_drops_tail_rows_with_nan_forward_returns(monkeypatch: pytest.MonkeyPatch):
    """Q-B: the last `forward_horizon_bars` rows per symbol drop out of (X, y)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    horizon = 5
    X, y = pool_sector_ohlcv(
        "IT",
        as_of=date(2025, 6, 20),
        horizon_years=1,
        forward_horizon_bars=horizon,
        fetcher=_fake_fetcher_two_symbols,
    )
    # y is finite everywhere it appears (no NaN tail rows survived).
    assert y.notna().all()
    # X and y are aligned.
    assert X.index.equals(y.index)
    # The last bar in the fetcher's OHLCV is NOT in X (forward-return is NaN there).
    last_bar_in_fetch = _fake_fetcher_two_symbols(
        "AAPL", start=date(2024, 6, 20), end=date(2025, 6, 20)
    ).index.max()
    aapl_idx = X.xs("AAPL", level="symbol").index
    assert aapl_idx.max() < last_bar_in_fetch


def test_pool_y_is_cumulative_forward_return(monkeypatch: pytest.MonkeyPatch):
    """Q-B B3: y[t] == close[t + horizon] / close[t] - 1 (per-symbol cumulative)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    horizon = 5
    X, y = pool_sector_ohlcv(
        "IT", as_of=date(2025, 6, 20), horizon_years=1,
        forward_horizon_bars=horizon, fetcher=_fake_fetcher_two_symbols,
    )
    # Pick the first bar in the result and check y by hand.
    aapl = X.xs("AAPL", level="symbol")
    aapl_fetch = _fake_fetcher_two_symbols(
        "AAPL", start=date(2024, 6, 20), end=date(2025, 6, 20)
    )
    first_date = aapl.index.min()
    fetch_idx = aapl_fetch.index.get_loc(first_date)
    expected = (
        float(aapl_fetch["close"].iloc[fetch_idx + horizon])
        / float(aapl_fetch["close"].iloc[fetch_idx])
    ) - 1.0
    actual = float(y.loc[(first_date, "AAPL")])
    assert actual == pytest.approx(expected, rel=1e-9)


def test_pool_empty_universe_returns_empty_frames(monkeypatch: pytest.MonkeyPatch):
    """A segment whose universe resolver returns [] yields empty (X, y) — no raise."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": [],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    X, y = pool_sector_ohlcv("IT", as_of=date(2025, 6, 20), horizon_years=1,
                              fetcher=_fake_fetcher_two_symbols)
    assert len(X) == 0
    assert len(y) == 0
    assert list(X.columns) == ["open", "high", "low", "close", "volume"]
```

- [ ] **Step 4: Run the failing tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_sector_ohlcv.py -v
```

Expected: **5 errors** (collection-time `ModuleNotFoundError: openbb_techtrade.tuning.sector_ohlcv`).

- [ ] **Step 5: Implement `sector_ohlcv.py`**

Create `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/sector_ohlcv.py`:

```python
"""Pool a segment's OHLCV into the (date, symbol) MultiIndex tuneta consumes (#83 L4).

The bridge between techtrade's per-symbol OHLCV fetcher (existing
``engine/movers._default_ohlcv_fetcher``-style functions, lazy-imported on
demand) and the multi-symbol DataFrame tuneta's :meth:`fit` expects when run
over a segment's universe (tuneta README: *"For multi-symbol use, index the
DataFrame by both date and symbol"*).

The forward-cumulative-return target ``y`` (Q-B B3) aligns the tuneta
optimisation with the rule that will consume the tuned periods: the default
``forward_horizon_bars=20`` matches :attr:`EntryExitRule.max_holding_bars`, so
the tuned periods become good at predicting the *kind* of move the rule is
built to capture.

This module imports neither ``tuneta`` nor ``openbb_backtest``. It is safe to
import on a bare techtrade install (though calling :func:`pool_sector_ohlcv`
without an injected ``fetcher`` will lazy-import the default ``fmp_cached``
fetcher at call time, which itself requires fmp_cached to be configured).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

# Best-effort universe resolver (PRD Q3 default = etf_holdings).
try:
    from openbb_techtrade.engine.universe import universe_for_segment
except ImportError:  # pragma: no cover - exercised when helper is absent
    _FALLBACK_UNIVERSE: dict[str, list[str]] = {
        "Information Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ADBE"],
        "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
        "Health Care": ["UNH", "JNJ", "LLY", "PFE", "ABBV"],
        "Energy": ["XOM", "CVX", "COP", "EOG", "SLB"],
        "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
        "Consumer Staples": ["PG", "KO", "WMT", "COST", "PEP"],
        "Communication Services": ["GOOG", "META", "NFLX", "DIS", "VZ"],
        "Industrials": ["CAT", "BA", "HON", "GE", "UNP"],
        "Materials": ["LIN", "APD", "SHW", "ECL", "NEM"],
        "Utilities": ["NEE", "SO", "DUK", "AEP", "EXC"],
        "Real Estate": ["PLD", "AMT", "EQIX", "CCI", "PSA"],
    }

    def universe_for_segment(  # type: ignore[no-redef]
        segment: str, source: str = "etf_holdings"
    ) -> list[str]:
        return list(_FALLBACK_UNIVERSE.get(segment, []))


logger = logging.getLogger(__name__)

#: Forward-return horizon (bars) — Q-B B3, matches EntryExitRule.max_holding_bars.
DEFAULT_FORWARD_HORIZON_BARS: int = 20

#: Fold-window length (years) — Q-C, same as #82's DEFAULT_HORIZON_YEARS.
DEFAULT_HORIZON_YEARS: int = 5


Fetcher = Callable[..., pd.DataFrame]


def pool_sector_ohlcv(
    segment: str,
    *,
    as_of: date,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
    forward_horizon_bars: int = DEFAULT_FORWARD_HORIZON_BARS,
    fetcher: Fetcher | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Pool ``segment``'s universe OHLCV into ``(X, y)`` for tuneta (L4 + Q-B + Q-C).

    Steps:

    1. Resolve the segment's symbol universe via :func:`universe_for_segment`
       (PRD Q3 default source = ``etf_holdings``).
    2. For each symbol, call ``fetcher(symbol, start=as_of - horizon_years,
       end=as_of)`` to get a per-symbol OHLCV DataFrame.
    3. Concatenate into a single DataFrame indexed by ``MultiIndex[(date,
       symbol)]`` with OHLCV columns.
    4. Compute ``y`` per ``(date, symbol)`` as the forward cumulative return
       over ``forward_horizon_bars`` business days: ``close[t + horizon] /
       close[t] - 1`` (Q-B B3).
    5. Drop the tail rows where ``y`` is NaN (the last ``forward_horizon_bars``
       rows per symbol have no forward return defined).

    Parameters
    ----------
    segment
        GICS sector name (e.g. ``"Information Technology"``).
    as_of
        End of the fold window (inclusive). Tail rows beyond this date are
        unreachable; the window is ``[as_of - horizon_years, as_of]``.
    horizon_years
        Length of the fold window in years (default :data:`DEFAULT_HORIZON_YEARS`).
    forward_horizon_bars
        Forward-return horizon in business days (default
        :data:`DEFAULT_FORWARD_HORIZON_BARS`, which matches
        :attr:`EntryExitRule.max_holding_bars`).
    fetcher
        Injectable OHLCV fetcher with signature
        ``fetcher(symbol, *, start: date, end: date) -> pd.DataFrame`` (OHLCV
        columns, date index). ``None`` (default) lazy-imports techtrade's
        ``fmp_cached``-backed fetcher — only the network path of the function.
        Tests inject a synthetic fetcher to stay offline.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.Series]
        ``X`` is the MultiIndex OHLCV frame ready for ``tuneta.fit``; ``y`` is
        the same-indexed forward-cumulative-return series.

    Notes
    -----
    Empty universe (resolver returns ``[]``) yields empty ``X`` and ``y`` —
    callers handle the degenerate case rather than relying on a raise.
    """
    symbols = list(universe_for_segment(segment))
    cols = ["open", "high", "low", "close", "volume"]
    if not symbols:
        empty_idx = pd.MultiIndex.from_tuples([], names=["date", "symbol"])
        return pd.DataFrame(columns=cols, index=empty_idx), pd.Series([], index=empty_idx,
                                                                       dtype="float64", name="y")

    start = _start_for(as_of, horizon_years)
    use_fetcher = fetcher if fetcher is not None else _default_fetcher()

    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        try:
            df = use_fetcher(symbol, start=start, end=as_of)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the pool
            logger.warning("sector_ohlcv: %s fetch failed: %s", symbol, exc)
            continue
        if df.empty:
            continue
        df = df[[c for c in cols if c in df.columns]].copy()
        df.index.name = "date"
        df["symbol"] = symbol
        frames.append(df.set_index("symbol", append=True))

    if not frames:
        empty_idx = pd.MultiIndex.from_tuples([], names=["date", "symbol"])
        return pd.DataFrame(columns=cols, index=empty_idx), pd.Series([], index=empty_idx,
                                                                       dtype="float64", name="y")

    X = pd.concat(frames).sort_index()
    # Forward cumulative return per symbol: close.shift(-horizon) / close - 1.
    closes = X["close"].unstack("symbol")
    forward = closes.shift(-forward_horizon_bars) / closes - 1.0
    y = forward.stack(future_stack=True).reorder_levels(["date", "symbol"]).sort_index()
    y.name = "y"
    # Align X to y's index (which has dropped the tail NaN rows).
    y = y.dropna()
    X = X.loc[y.index]
    return X, y


def _start_for(as_of: date, horizon_years: int) -> date:
    """Subtract ``horizon_years`` from ``as_of`` (Feb-29 safe — mirrors backtest_bridge._start_date)."""
    try:
        return as_of.replace(year=as_of.year - horizon_years)
    except ValueError:
        return date(as_of.year - horizon_years, 3, 1)


def _default_fetcher() -> Fetcher:
    """Lazy-import the techtrade ``fmp_cached``-backed OHLCV fetcher.

    Production callers get the real fetcher; tests inject ``fetcher=`` and never
    reach this path. Kept lazy so importing :mod:`sector_ohlcv` does not pull in
    fmp_cached at module load.
    """
    # Verify the actual import path during Step 1 of this Task; this is the
    # expected location per the design (mirrors engine/indicators.py:
    # _default_ohlcv_fetcher).
    from openbb_techtrade.engine.movers import _default_ohlcv_fetcher

    return _default_ohlcv_fetcher
```

- [ ] **Step 6: Run the tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_sector_ohlcv.py -v
```

Expected: **5 passed**.

If `test_pool_y_is_cumulative_forward_return` fails with an off-by-one, the issue is `closes.shift(-horizon)` vs the expected `iloc[idx + horizon]` — both should agree on business-day calendars, but check the test's `freq="B"` versus the implementation's index handling. The pandas `unstack`/`stack(future_stack=True)` round-trip can also re-introduce NaNs if the per-symbol date ranges differ; the test uses identical date ranges for both symbols so this should not matter, but flag any mismatch in the commit message.

- [ ] **Step 7: Commit T3**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/tuning/sector_ohlcv.py openbb_platform/extensions/techtrade/tests/unit/test_sector_ohlcv.py
git commit -m "$(cat <<'EOF'
feat(83): tuning.sector_ohlcv — pool segment OHLCV + forward returns

T3 of the #83 implementation plan. Bridges techtrade's per-symbol OHLCV
fetcher to the (date, symbol)-MultiIndex DataFrame tuneta's multi-symbol fit
expects (L4 + Q-B + Q-C).

Defaults pinned to the L4/Q-B/Q-C decisions:
- DEFAULT_HORIZON_YEARS = 5 (Q-C; same as #82's validate window for one source
  of truth between "what we tuned on" and "what we validated on").
- DEFAULT_FORWARD_HORIZON_BARS = 20 (Q-B B3; matches
  EntryExitRule.max_holding_bars so the tuneta optimisation target aligns with
  the rule that will consume the tuned periods).

The pool function:
1. Resolves the segment universe via universe_for_segment (PRD Q3
   etf_holdings default; falls back to an in-file 11-sector top-5 dict when
   that helper is absent — track via the same bead T2's fallback flagged).
2. Loops over symbols, calls the injected fetcher (lazy-imports the real
   fmp_cached one in production via _default_fetcher).
3. Concatenates into the MultiIndex frame and computes forward cumulative
   return per symbol via closes.unstack -> shift(-horizon) -> stack.
4. Drops tail NaN-y rows and aligns X to y's index.

One bad symbol doesn't abort the pool (warning logged, symbol skipped).
Empty-universe degenerates to empty (X, y) — no raise. Imports neither tuneta
nor openbb_backtest; safe to import on a bare techtrade install.

5 unit tests cover: MultiIndex layout, fetcher invocation per symbol with
the right window, tail-drop on NaN y, forward-cumulative-return math by hand
on a known synthetic series, empty-universe degenerate case.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Close T3 bd child + claim T4**

```
bd close <T3-bead-id> --resolution=completed --comment "sector_ohlcv.py; 5/5 tests green"
bd update <T4-bead-id> --status=in_progress
```

---

## Task 4: `tuning/tuneta_adapter.py` — the ONLY tuneta-importing module

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tuneta_adapter.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_tuneta_adapter.py`

**Interfaces:**
- Consumes: `IndicatorConfig` + `DEFAULT_CONFIG` from `engine.indicators`; `TechtradeDependencyError` from `validation.backtest_bridge` (the leaf error class introduced by #82 — **reused, not duplicated**, per L8)
- Produces (consumed by T5):
  - `KNOB_TABLE: tuple[tuple[str, str, tuple[int, int]], ...]` — the L6 8-knob spec (config-field name, tuneta indicator name, (low, high) range)
  - `_require_tuneta() -> Any` — lazy guard returning the `TuneTA` class
  - `fit_segment(X, y, *, trials=100, early_stop=20) -> tuple[IndicatorConfig, dict]` — runs `TuneTA.fit`, parses tuned columns, returns the candidate `IndicatorConfig` + metadata `{"tuneta_version": str, "fit_seconds": float, "tuned_columns": list[str]}`
  - `parse_tuned_columns(columns: list[str]) -> IndicatorConfig` — pure-Python column-name parser (testable without `tuneta` installed)

---

- [ ] **Step 1: Write the failing tests (10 tests, one block)**

Create `openbb_platform/extensions/techtrade/tests/unit/test_tuneta_adapter.py`:

```python
"""Unit tests for openbb_techtrade.tuning.tuneta_adapter (#83 L6, L8, Q-G)."""

from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any
from unittest import mock

import pandas as pd
import pytest

from openbb_core.app.model.abstract.error import OpenBBError

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError


# --- TechtradeDependencyError reuse (L8 Q-G) -----------------------------------------------------

def test_dependency_error_when_tuneta_absent(monkeypatch: pytest.MonkeyPatch):
    """Q-G: with `tuneta` forced un-importable, fit_segment raises TechtradeDependencyError."""
    # Drop any cached tuneta module so the next import goes through the blocker.
    for module_name in list(sys.modules):
        if module_name.startswith("tuneta"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if name.startswith("tuneta"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocker)

    from openbb_techtrade.tuning.tuneta_adapter import _require_tuneta

    with pytest.raises(TechtradeDependencyError) as excinfo:
        _require_tuneta()
    msg = str(excinfo.value)
    assert "tuneta" in msg
    assert "pip install" in msg
    assert "'openbb-techtrade[tuneta]'" in msg


def test_dependency_error_subclasses_openbb_error():
    """L8: reuses #82's TechtradeDependencyError (which subclasses OpenBBError)."""
    assert issubclass(TechtradeDependencyError, OpenBBError)


def test_degradation_other_modules_still_import(monkeypatch: pytest.MonkeyPatch):
    """Q-G + #85: with tuneta absent, every other techtrade module still imports cleanly."""
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if name.startswith("tuneta"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    for module_name in list(sys.modules):
        if module_name.startswith("tuneta"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocker)

    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.models",
        "openbb_techtrade.engine.indicators",
        "openbb_techtrade.tuning",
        "openbb_techtrade.tuning.tuned_defaults",
        "openbb_techtrade.tuning.sector_ohlcv",
        # The adapter itself must be importable too — only _require_tuneta touches tuneta.
        "openbb_techtrade.tuning.tuneta_adapter",
    ):
        importlib.import_module(module_name)


# --- KNOB_TABLE shape (L6) ---------------------------------------------------------------------

def test_knob_table_has_exactly_eight_period_knobs():
    """L6: tuneta search space is exactly 8 period knobs with the documented ranges."""
    from openbb_techtrade.tuning.tuneta_adapter import KNOB_TABLE

    assert len(KNOB_TABLE) == 8
    by_field = {row[0]: row for row in KNOB_TABLE}
    expected = {
        "macd_fast": ("tta.MACD", (8, 20)),
        "macd_slow": ("tta.MACD", (20, 40)),
        "macd_signal": ("tta.MACD", (5, 15)),
        "adx_length": ("tta.ADX", (10, 30)),
        "ema_fast": ("tta.EMA", (10, 30)),
        "ema_slow": ("tta.EMA", (30, 80)),
        "rsi_length": ("tta.RSI", (8, 30)),
        "atr_length": ("tta.ATR", (10, 30)),
    }
    assert set(by_field.keys()) == set(expected.keys())
    for field, (indicator, rng) in expected.items():
        assert by_field[field][1] == indicator
        assert by_field[field][2] == rng


# --- parse_tuned_columns (round-trip, fallback, EMA binding) ------------------------------------

def test_parse_columns_recovers_indicator_config():
    """L6: a known set of tuneta column names parses into the expected IndicatorConfig fields."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cols = [
        "tta_RSI_timeperiod_19",
        "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9",
        "tta_ADX_timeperiod_16",
        "tta_ATR_timeperiod_18",
        "tta_EMA_timeperiod_15",   # in (10, 30) -> ema_fast
        "tta_EMA_timeperiod_55",   # in (30, 80) -> ema_slow
    ]
    cfg = parse_tuned_columns(cols)
    assert cfg.rsi_length == 19
    assert cfg.macd_fast == 14
    assert cfg.macd_slow == 32
    assert cfg.macd_signal == 9
    assert cfg.adx_length == 16
    assert cfg.atr_length == 18
    assert cfg.ema_fast == 15
    assert cfg.ema_slow == 55
    # Untouched (non-period) knobs equal DEFAULT_CONFIG.
    assert cfg.stoch_k == DEFAULT_CONFIG.stoch_k
    assert cfg.stoch_d == DEFAULT_CONFIG.stoch_d
    assert cfg.stoch_smooth_k == DEFAULT_CONFIG.stoch_smooth_k
    assert cfg.bb_length == DEFAULT_CONFIG.bb_length
    assert cfg.bb_std == DEFAULT_CONFIG.bb_std
    assert cfg.kc_length == DEFAULT_CONFIG.kc_length
    assert cfg.kc_scalar == DEFAULT_CONFIG.kc_scalar


def test_parse_unknown_column_falls_back_to_default(caplog: pytest.LogCaptureFixture):
    """An unrecognised column name -> that knob stays at DEFAULT_CONFIG; logs WARNING; no raise."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cols = ["pta_something_weird_42", "tta_RSI_timeperiod_19"]
    with caplog.at_level("WARNING"):
        cfg = parse_tuned_columns(cols)
    # Recognised column was still applied:
    assert cfg.rsi_length == 19
    # Unrecognised one is mentioned in the WARNING:
    assert "pta_something_weird_42" in caplog.text
    # Untuned knobs (no MACD column at all) stay at DEFAULT_CONFIG.
    assert cfg.macd_fast == DEFAULT_CONFIG.macd_fast


def test_parse_only_macd_keeps_other_periods_at_default():
    """A tune that returns only a MACD column leaves rsi/adx/atr/ema at DEFAULT_CONFIG."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cols = ["tta_MACD_fastperiod_10_slowperiod_30_signalperiod_7"]
    cfg = parse_tuned_columns(cols)
    assert cfg.macd_fast == 10
    assert cfg.macd_slow == 30
    assert cfg.macd_signal == 7
    assert cfg.rsi_length == DEFAULT_CONFIG.rsi_length
    assert cfg.adx_length == DEFAULT_CONFIG.adx_length
    assert cfg.atr_length == DEFAULT_CONFIG.atr_length
    assert cfg.ema_fast == DEFAULT_CONFIG.ema_fast
    assert cfg.ema_slow == DEFAULT_CONFIG.ema_slow


def test_ema_binding_by_range():
    """L6 EMA sharp edge: two EMA columns -> period in (10,30) is ema_fast, period in (30,80) is ema_slow."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cfg = parse_tuned_columns([
        "tta_EMA_timeperiod_25",
        "tta_EMA_timeperiod_60",
    ])
    assert cfg.ema_fast == 25
    assert cfg.ema_slow == 60
    # Reversed input order — binding by range, not order:
    cfg2 = parse_tuned_columns([
        "tta_EMA_timeperiod_60",
        "tta_EMA_timeperiod_25",
    ])
    assert cfg2.ema_fast == 25
    assert cfg2.ema_slow == 60


def test_ema_single_period_in_fast_range_only_binds_fast():
    """Only one EMA column in (10,30) — ema_slow stays at DEFAULT_CONFIG."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cfg = parse_tuned_columns(["tta_EMA_timeperiod_20"])
    assert cfg.ema_fast == 20
    assert cfg.ema_slow == DEFAULT_CONFIG.ema_slow


# --- fit_segment (uses a faked TuneTA so test stays offline + tuneta-absent-safe) ---------------

def test_fit_segment_returns_candidate_config_and_meta(monkeypatch: pytest.MonkeyPatch):
    """fit_segment(X, y) -> (IndicatorConfig, meta-dict) via a faked TuneTA."""

    class _FakeTuneTA:
        def __init__(self, *a, **kw): self._fitted = False
        def fit(self, X, y, **kwargs):
            self._fitted = True
            self._kwargs = kwargs
        def transform(self, X):
            # Mimic tuneta's column-name encoding.
            cols = [
                "tta_RSI_timeperiod_19",
                "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9",
                "tta_ADX_timeperiod_16",
                "tta_ATR_timeperiod_18",
                "tta_EMA_timeperiod_15",
                "tta_EMA_timeperiod_55",
            ]
            return pd.DataFrame({c: [0.0] for c in cols})

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._require_tuneta",
        lambda: _FakeTuneTA,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._tuneta_version",
        lambda: "0.2.3-fake",
    )

    from openbb_techtrade.tuning.tuneta_adapter import fit_segment

    X = pd.DataFrame({"close": [1.0, 2.0, 3.0]})  # shape doesn't matter for the fake
    y = pd.Series([0.01, 0.02, -0.01])
    candidate, meta = fit_segment(X, y, trials=50, early_stop=10)

    assert isinstance(candidate, IndicatorConfig)
    assert candidate.rsi_length == 19
    assert candidate.macd_fast == 14
    assert candidate.ema_fast == 15
    assert candidate.ema_slow == 55
    assert meta["tuneta_version"] == "0.2.3-fake"
    assert "fit_seconds" in meta and meta["fit_seconds"] >= 0
    assert meta["tuned_columns"] == [
        "tta_RSI_timeperiod_19",
        "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9",
        "tta_ADX_timeperiod_16",
        "tta_ATR_timeperiod_18",
        "tta_EMA_timeperiod_15",
        "tta_EMA_timeperiod_55",
    ]


def test_fit_segment_forwards_trials_and_early_stop(monkeypatch: pytest.MonkeyPatch):
    """trials/early_stop arguments reach the TuneTA.fit() call verbatim."""

    captured: dict[str, Any] = {}

    class _FakeTuneTA:
        def __init__(self, *a, **kw): pass
        def fit(self, X, y, **kwargs): captured.update(kwargs)
        def transform(self, X): return pd.DataFrame({"tta_RSI_timeperiod_14": [0.0]})

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._require_tuneta",
        lambda: _FakeTuneTA,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._tuneta_version",
        lambda: "0.2.3-fake",
    )

    from openbb_techtrade.tuning.tuneta_adapter import fit_segment
    fit_segment(pd.DataFrame({"close": [1.0]}), pd.Series([0.0]), trials=37, early_stop=11)

    assert captured["trials"] == 37
    assert captured["early_stop"] == 11
```

- [ ] **Step 2: Run the failing tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_tuneta_adapter.py -v
```

Expected: **10 errors** (collection-time `ModuleNotFoundError: openbb_techtrade.tuning.tuneta_adapter`).

- [ ] **Step 3: Implement `tuneta_adapter.py`**

Create `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tuneta_adapter.py`:

```python
"""The ONLY techtrade module that imports ``tuneta`` (#83 L6, L8, Q-G).

Lazy in-body import discipline (mirrors #82's
:mod:`openbb_techtrade.validation.backtest_bridge`):

- :func:`_require_tuneta` lazy-imports :class:`tuneta.tune_ta.TuneTA` and raises
  the reused :class:`TechtradeDependencyError` (introduced by #82) with a
  ready-to-run ``pip install 'openbb-techtrade[tuneta]'`` hint when ``tuneta``
  is not installed.
- :data:`KNOB_TABLE` is the L6 single source of truth: 8 period knobs, each
  paired with its tuneta indicator name and ``(low, high)`` range.
- :func:`parse_tuned_columns` is a pure-Python regex-based parser over tuneta's
  emitted column-name encoding (no ``tuneta`` import — testable on a bare
  install).
- :func:`fit_segment` is the glue: configures a :class:`TuneTA`, runs
  :meth:`fit`, calls :meth:`transform` to read the chosen periods from the
  resulting column names, and returns the candidate :class:`IndicatorConfig`
  plus the metadata :class:`~openbb_techtrade.models.TuningReport` will record
  (``tuneta_version``, ``fit_seconds``, ``tuned_columns``).

Every other module in this package is safe to import on a bare techtrade install
(no extras). Only this module triggers the ``import tuneta`` chain — and only
when :func:`_require_tuneta` or :func:`fit_segment` is actually called.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import pandas as pd

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError

logger = logging.getLogger(__name__)

#: Hint emitted with TechtradeDependencyError (verbatim copy-pasteable).
_PIP_INSTALL_HINT: str = "pip install 'openbb-techtrade[tuneta]'"

#: The L6 8-knob spec: (IndicatorConfig field name, tuneta indicator string, (low, high) range).
#: The order is the order tuneta receives them in :func:`fit_segment` and is also the
#: order tested by ``test_knob_table_has_exactly_eight_period_knobs``.
KNOB_TABLE: tuple[tuple[str, str, tuple[int, int]], ...] = (
    ("macd_fast",    "tta.MACD", (8, 20)),
    ("macd_slow",    "tta.MACD", (20, 40)),
    ("macd_signal",  "tta.MACD", (5, 15)),
    ("adx_length",   "tta.ADX",  (10, 30)),
    ("ema_fast",     "tta.EMA",  (10, 30)),
    ("ema_slow",     "tta.EMA",  (30, 80)),
    ("rsi_length",   "tta.RSI",  (8, 30)),
    ("atr_length",   "tta.ATR",  (10, 30)),
)


# --- lazy guard -------------------------------------------------------------------------------


def _require_tuneta() -> Any:
    """Lazily import ``tuneta``'s :class:`TuneTA`, or raise a clear error.

    Returns the :class:`TuneTA` class so callers can instantiate it. Mirrors
    :func:`openbb_techtrade.validation.backtest_bridge._require_backtest` shape
    for shape.

    Raises
    ------
    TechtradeDependencyError
        When ``tuneta`` is not importable. Message carries
        ``pip install 'openbb-techtrade[tuneta]'``.
    """
    try:
        from tuneta.tune_ta import TuneTA
    except ImportError as exc:
        raise TechtradeDependencyError(
            "obb.techtrade.tune requires the 'tuneta' package, which is not "
            f"installed. Install it with: {_PIP_INSTALL_HINT}"
        ) from exc
    return TuneTA


def _tuneta_version() -> str:
    """Return ``tuneta.__version__`` or ``'unknown'`` (lazy; used by :func:`fit_segment`)."""
    try:
        import tuneta  # noqa: PLC0415 - lazy
        return getattr(tuneta, "__version__", "unknown")
    except ImportError:
        return "unknown"


# --- column-name parser (pure, no tuneta import) -----------------------------------------------


_COLUMN_RX: dict[str, re.Pattern] = {
    "rsi_length":  re.compile(r"^tta_RSI_timeperiod_(\d+)$"),
    "adx_length":  re.compile(r"^tta_ADX_timeperiod_(\d+)$"),
    "atr_length":  re.compile(r"^tta_ATR_timeperiod_(\d+)$"),
    "macd_fast":   re.compile(
        r"^tta_MACD_fastperiod_(\d+)_slowperiod_\d+_signalperiod_\d+$"
    ),
    "macd_slow":   re.compile(
        r"^tta_MACD_fastperiod_\d+_slowperiod_(\d+)_signalperiod_\d+$"
    ),
    "macd_signal": re.compile(
        r"^tta_MACD_fastperiod_\d+_slowperiod_\d+_signalperiod_(\d+)$"
    ),
}
_EMA_RX = re.compile(r"^tta_EMA_timeperiod_(\d+)$")
_EMA_FAST_RANGE = (10, 30)
_EMA_SLOW_RANGE = (30, 80)


def parse_tuned_columns(columns: list[str]) -> IndicatorConfig:
    """Parse tuneta's emitted column names into an :class:`IndicatorConfig` (L6 + EMA binding).

    Recognised single-period columns (RSI / ADX / ATR / MACD bundle) are bound
    by regex. EMAs are bound by **range** (Step 1 sharp edge in design §3.2):
    the period in :data:`_EMA_FAST_RANGE` ``(10, 30)`` becomes ``ema_fast``;
    the period in :data:`_EMA_SLOW_RANGE` ``(30, 80)`` becomes ``ema_slow``.
    Unrecognised columns log at WARNING and leave their knob at
    :data:`DEFAULT_CONFIG`.

    Always returns a fully-populated :class:`IndicatorConfig`: the 7 untuned
    knobs (stoch / bb / kc fields) are copied verbatim from
    :data:`DEFAULT_CONFIG`.
    """
    # Start from DEFAULT_CONFIG; each parsed period overrides one field via dataclass replace.
    from dataclasses import replace

    updates: dict[str, int] = {}
    ema_periods: list[int] = []

    for col in columns:
        matched_any = False
        for field, pattern in _COLUMN_RX.items():
            m = pattern.match(col)
            if m is not None:
                updates[field] = int(m.group(1))
                matched_any = True
                # MACD columns match three patterns — keep checking so all three slots fill.
        ema_match = _EMA_RX.match(col)
        if ema_match is not None:
            ema_periods.append(int(ema_match.group(1)))
            matched_any = True
        if not matched_any:
            logger.warning("tuneta_adapter: unrecognised column %r — knob stays at default", col)

    # Bind EMAs by range.
    for period in ema_periods:
        if _EMA_FAST_RANGE[0] <= period <= _EMA_FAST_RANGE[1]:
            updates["ema_fast"] = period
        elif _EMA_SLOW_RANGE[0] < period <= _EMA_SLOW_RANGE[1]:
            updates["ema_slow"] = period
        else:
            logger.warning(
                "tuneta_adapter: EMA period %d outside (10,30) and (30,80) — skipping", period
            )

    return replace(DEFAULT_CONFIG, **updates)


# --- fit_segment ------------------------------------------------------------------------------


def fit_segment(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    trials: int = 100,
    early_stop: int = 20,
) -> tuple[IndicatorConfig, dict[str, Any]]:
    """Run :meth:`TuneTA.fit` over the L6 knob set and parse the result.

    The Q-D budget defaults (``trials=100``, ``early_stop=20``) are the tuneta
    README defaults; ``verbose=False`` is forced to keep the techtrade log
    surface clean (tuneta defaults to chatty).

    Parameters
    ----------
    X, y
        From :func:`pool_sector_ohlcv` — MultiIndex ``(date, symbol)`` OHLCV and
        forward-cumulative-return series, aligned.
    trials, early_stop
        Optuna budget knobs forwarded verbatim to :meth:`TuneTA.fit`.

    Returns
    -------
    tuple[IndicatorConfig, dict]
        ``(candidate, meta)`` where ``meta`` carries ``{"tuneta_version": str,
        "fit_seconds": float, "tuned_columns": list[str]}`` for
        :class:`~openbb_techtrade.models.TuningReport`.

    Raises
    ------
    TechtradeDependencyError
        When ``tuneta`` is not installed (via :func:`_require_tuneta`).
    """
    TuneTA = _require_tuneta()  # noqa: N806 - mirrors tuneta's class name
    indicators = [indicator for _, indicator, _ in KNOB_TABLE]
    ranges = [rng for _, _, rng in KNOB_TABLE]

    start = time.perf_counter()
    tt = TuneTA(n_jobs=4, verbose=False)
    tt.fit(X, y, indicators=indicators, ranges=ranges, trials=trials, early_stop=early_stop)
    transformed = tt.transform(X)
    fit_seconds = time.perf_counter() - start

    columns = list(transformed.columns)
    candidate = parse_tuned_columns(columns)
    meta = {
        "tuneta_version": _tuneta_version(),
        "fit_seconds": fit_seconds,
        "tuned_columns": columns,
    }
    return candidate, meta
```

- [ ] **Step 4: Run the tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_tuneta_adapter.py -v
```

Expected: **10 passed**.

- [ ] **Step 5: Smoke-check the degradation discipline cross-module**

```
.venv_win\Scripts\python.exe -c "import openbb_techtrade.tuning.tuneta_adapter; print('module imports without tuneta installed:', not __import__('importlib.util').util.find_spec('tuneta'))"
```

Expected: `module imports without tuneta installed: True`. (Confirms the L8 lazy-import discipline holds at the actual install state.)

- [ ] **Step 6: Commit T4**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tuneta_adapter.py openbb_platform/extensions/techtrade/tests/unit/test_tuneta_adapter.py
git commit -m "$(cat <<'EOF'
feat(83): tuning.tuneta_adapter — lazy tuneta import + knob table + column parser

T4 of the #83 implementation plan. The ONLY techtrade module that imports
tuneta (L6, L8, Q-G); the lazy `_require_tuneta` mirrors #82's
`_require_backtest` shape for shape and reuses the same `TechtradeDependencyError`
leaf so existing `except TechtradeDependencyError` handlers catch both
missing-`openbb-backtest` and missing-`tuneta` (L8 single-leaf rule).

KNOB_TABLE is the L6 single source of truth: exactly 8 period knobs
(macd_fast/slow/signal, adx_length, ema_fast/slow, rsi_length, atr_length)
each paired with its tuneta indicator name and (low, high) range. The 7
non-period / coupled-bundle knobs (stoch_*, bb_*, kc_*) stay at PRD defaults
— tuneta tunes one period per indicator, stoch needs 3 coherent knobs
together, and bb_std/kc_scalar are shape multipliers.

parse_tuned_columns is pure-Python (no tuneta import) so it's testable on a
bare install. EMA columns bind by RANGE not order — the period in (10, 30)
becomes ema_fast, in (30, 80) becomes ema_slow — exactly the sharp edge
design §3.2 flagged.

fit_segment glues TuneTA(...).fit + .transform, reads the chosen periods
from the resulting column names, and returns the candidate IndicatorConfig
plus the meta dict TuningReport will record (tuneta_version, fit_seconds,
tuned_columns). Q-D defaults locked: trials=100, early_stop=20, verbose=False.

10 unit tests cover: dependency error message + class hierarchy, every
non-validation module still importable with tuneta absent (Q-G + #85),
KNOB_TABLE shape (8 entries, exact ranges), column-name -> IndicatorConfig
round-trip, unknown column fallback + WARNING, EMA range binding
(both orders + single-period-in-fast-range-only), fit_segment via a faked
TuneTA (trials/early_stop forwarding + meta shape).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Close T4 bd child + claim T5**

```
bd close <T4-bead-id> --resolution=completed --comment "tuneta_adapter.py; 10/10 tests green; tuneta absent verified"
bd update <T5-bead-id> --status=in_progress
```

---

## Task 5: `tuning/tune_router.py` + register the sub-router

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tune_router.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py` (add the new sub-router path to `_include_subrouters`'s tuple)
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_tune_router.py`

**Interfaces:**
- Consumes: `pool_sector_ohlcv` + `DEFAULT_HORIZON_YEARS` + `DEFAULT_FORWARD_HORIZON_BARS` from T3; `fit_segment` from T4; `tune_override` + `write_tuned` from T2; `validate_plan` from `validation.backtest_bridge` (existing, from #82); `TuningReport` from T1
- Produces (consumed by T7):
  - `obb.techtrade.tune(segment, *, as_of, horizon_years, forward_horizon_bars, trials, early_stop, method, thresholds, provider) -> OBBject[TuningReport]`
  - `SEGMENT_BENCHMARK_ETFS: dict[str, str]` — the Q-A A1 sector → ETF map used to construct the sample plan
  - `_build_sample_plan(segment, as_of) -> TradePlan` — used by tests for assertion targets

---

- [ ] **Step 1: Verify the sample-plan construction shape**

The router needs to build a single-symbol `TradePlan` for the segment's benchmark ETF, passed to `validate_plan`. The Q-A A1 decision uses a small constant table. Look at the existing `_FakeBacktestConfig` and `_plan` test helper in `validation/test_backtest_bridge.py` for the minimal field set a `TradePlan` needs to satisfy `validate_plan`'s input contract — that's the model the sample plan should follow.

```
.venv_win\Scripts\python.exe -c "from openbb_techtrade.models import TradePlan, MoverSignal, Recommendation, EntryExitRule; print('imports ok')"
```

- [ ] **Step 2: Write the failing tests (7 tests, one block)**

Create `openbb_platform/extensions/techtrade/tests/unit/test_tune_router.py`:

```python
"""Unit tests for openbb_techtrade.tuning.tune_router (#83 L2, L5, L7, Q-A, Q-F, §5.3 W2)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.models import TradePlan


# --- helpers ---------------------------------------------------------------------------------

def _config_a() -> IndicatorConfig:
    """A NON-default tuned candidate (distinct from DEFAULT_CONFIG)."""
    from dataclasses import replace
    return replace(DEFAULT_CONFIG, macd_fast=14, macd_slow=32, macd_signal=9,
                   adx_length=16, ema_fast=18, ema_slow=55, rsi_length=11, atr_length=18)


def _fake_pool(*a, **kw):
    import pandas as pd
    idx = pd.MultiIndex.from_tuples([], names=["date", "symbol"])
    return pd.DataFrame(columns=["open","high","low","close","volume"], index=idx), pd.Series([], index=idx, dtype="float64")


def _setup_tuned_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the persistence file at a fresh tmp_path and clear caches."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr("openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache
    _clear_cache()
    return path


def _fake_validate(verdict: str):
    """Build an awaitable validate_plan replacement that returns (plan, fake_report)."""
    fake_report = SimpleNamespace(
        verdict=verdict,
        pbo=0.18 if verdict == "robust" else 0.31,
        deflated_sharpe=0.97 if verdict == "robust" else 0.62,
        oos_metrics=SimpleNamespace(sharpe=0.84 if verdict == "robust" else 0.10),
        method="wfo",
    )

    async def _validate(plan, *, method="wfo", thresholds=None, horizon_years=5, provider=None):
        return plan.model_copy(update={"validation": fake_report}), fake_report

    return _validate, fake_report


# --- Q-A A1: sample plan uses the segment's benchmark ETF ---------------------------------------

def test_sample_plan_uses_benchmark_etf():
    """Q-A A1: the TradePlan validate_plan receives has symbol == SEGMENT_BENCHMARK_ETFS[segment]."""
    from openbb_techtrade.tuning.tune_router import (
        SEGMENT_BENCHMARK_ETFS,
        _build_sample_plan,
    )
    # The sector ETF is XLK for IT; XLF for Financials; etc.
    plan = _build_sample_plan("Information Technology", as_of=date(2025, 6, 20))
    assert isinstance(plan, TradePlan)
    assert plan.symbol == SEGMENT_BENCHMARK_ETFS["Information Technology"] == "XLK"
    assert plan.segment == "Information Technology"
    assert plan.as_of == date(2025, 6, 20)


def test_segment_benchmark_etfs_covers_all_eleven_gics_sectors():
    """Q-A: every GICS sector has a benchmark ETF entry — no KeyError surprise mid-loop."""
    from openbb_techtrade.tuning.tune_router import SEGMENT_BENCHMARK_ETFS
    expected = {
        "Information Technology", "Financials", "Health Care",
        "Consumer Discretionary", "Consumer Staples", "Energy",
        "Communication Services", "Industrials", "Materials",
        "Utilities", "Real Estate",
    }
    assert set(SEGMENT_BENCHMARK_ETFS.keys()) == expected
    for sector, etf in SEGMENT_BENCHMARK_ETFS.items():
        assert isinstance(etf, str) and etf, f"{sector} has empty ETF"


# --- L2: robust verdict persists -----------------------------------------------------------------

def test_robust_verdict_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L2 strict: verdict == 'robust' triggers write_tuned; TuningReport.persisted is True."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            _config_a(),
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )
    fake_validate, _ = _fake_validate("robust")
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", fake_validate,
    )

    from openbb_techtrade.tuning.tune_router import tune
    obb = asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))

    report = obb.results
    assert report.persisted is True
    assert "verdict=robust" in report.reason
    # The file now carries the segment.
    from openbb_techtrade.tuning.tuned_defaults import read_tuned
    on_disk = read_tuned()
    assert on_disk is not None and "Information Technology" in on_disk["segments"]


# --- L2: fragile / overfit verdicts do NOT persist (Q-F transparent non-persist) -----------------

@pytest.mark.parametrize("verdict", ["fragile", "overfit"])
def test_non_robust_verdict_does_not_persist(
    verdict: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L2 + Q-F: fragile/overfit -> persisted=False; file is unchanged (or absent)."""
    path = _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            _config_a(),
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )
    fake_validate, _ = _fake_validate(verdict)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", fake_validate,
    )

    assert not path.exists()  # no file before tune

    from openbb_techtrade.tuning.tune_router import tune
    obb = asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))
    report = obb.results

    assert report.persisted is False
    assert f"verdict={verdict}" in report.reason
    assert not path.exists()  # file STILL doesn't exist; no write happened


# --- Q-F guard 3: no-op tune (config equal to DEFAULT_CONFIG) does NOT persist ------------------

def test_no_op_tune_does_not_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-F guard 3: if fit returns DEFAULT_CONFIG, persisted=False, reason='no change from defaults'."""
    path = _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            DEFAULT_CONFIG,
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )
    fake_validate, _ = _fake_validate("robust")  # even a robust verdict shouldn't write a no-op.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", fake_validate,
    )

    from openbb_techtrade.tuning.tune_router import tune
    obb = asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))
    report = obb.results

    assert report.persisted is False
    assert "no change from defaults" in report.reason
    assert not path.exists()


# --- Q-F guard 2: loop over mixed verdicts does NOT raise ---------------------------------------

def test_loop_over_mixed_verdicts_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-F guard 2: caller loops segments with mixed verdicts; nothing raises mid-loop."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            _config_a(),
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )

    verdicts = iter(["robust", "fragile", "overfit", "robust"])
    fake_report_factory = lambda: _fake_validate(next(verdicts))

    async def _validate(plan, **kwargs):
        v, _ = fake_report_factory()
        return await v(plan, **kwargs)

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", _validate,
    )

    from openbb_techtrade.tuning.tune_router import tune
    reports = []
    for seg in ["Information Technology", "Financials", "Energy", "Health Care"]:
        obb = asyncio.run(tune(segment=seg, as_of=date(2025, 6, 20)))
        reports.append(obb.results)

    assert len(reports) == 4
    assert [r.persisted for r in reports] == [True, False, False, True]


# --- §5.3 W2: contextvar override is set during the validate call -------------------------------

def test_override_visible_in_validate_fold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """§5.3 W2: while validate runs, lookup_tuned_for_symbol sees the candidate via contextvar."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    candidate = _config_a()
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            candidate,
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )

    observed: list[IndicatorConfig | None] = []

    async def _validate_observer(plan, *, method="wfo", thresholds=None, horizon_years=5, provider=None):
        # Mid-validate: the override must be visible to lookup_tuned_for_symbol.
        from openbb_techtrade.tuning.tuned_defaults import lookup_tuned_for_symbol
        observed.append(lookup_tuned_for_symbol("AAPL"))
        fake_report = SimpleNamespace(verdict="robust", pbo=0.18,
                                       deflated_sharpe=0.97,
                                       oos_metrics=SimpleNamespace(sharpe=0.84),
                                       method=method)
        return plan.model_copy(update={"validation": fake_report}), fake_report

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", _validate_observer,
    )

    from openbb_techtrade.tuning.tune_router import tune
    asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))

    assert observed == [candidate], (
        "the candidate must be visible mid-validate via the contextvar override; "
        "if this fails, either the router forgot the `with tune_override(...)`, or "
        "validate_plan started running in an executor/thread/process that "
        "doesn't propagate contextvars — see §5.3 W2 fallback to W1"
    )


# --- argument forwarding ---------------------------------------------------------------------

def test_tune_forwards_trials_and_early_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-D: tune(..., trials=N, early_stop=M) reaches fit_segment with those exact values."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    captured: dict[str, Any] = {}

    def _fit_spy(X, y, *, trials=100, early_stop=20):
        captured["trials"] = trials
        captured["early_stop"] = early_stop
        return (DEFAULT_CONFIG,
                {"tuneta_version": "x", "fit_seconds": 0.0, "tuned_columns": []})

    monkeypatch.setattr("openbb_techtrade.tuning.tune_router.fit_segment", _fit_spy)
    fake_validate, _ = _fake_validate("robust")
    monkeypatch.setattr("openbb_techtrade.tuning.tune_router.validate_plan", fake_validate)

    from openbb_techtrade.tuning.tune_router import tune
    asyncio.run(tune(
        segment="Information Technology", as_of=date(2025, 6, 20),
        trials=37, early_stop=11,
    ))
    assert captured == {"trials": 37, "early_stop": 11}
```

- [ ] **Step 3: Run the failing tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_tune_router.py -v
```

Expected: **7 errors** (collection-time `ModuleNotFoundError: openbb_techtrade.tuning.tune_router`).

- [ ] **Step 4: Implement `tune_router.py`**

Create `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tune_router.py`:

```python
"""``tune`` sub-router: obb.techtrade.tune(segment, ...) (#83 L7, L5, L2, Q-A, Q-F, §5.3 W2).

The orchestration layer that wires T2/T3/T4 + #82's validate_plan together:

1. :func:`tuning.sector_ohlcv.pool_sector_ohlcv` -> ``(X, y)`` (L4 + Q-B + Q-C).
2. :func:`tuning.tuneta_adapter.fit_segment` -> ``(candidate IndicatorConfig,
   meta)`` (L6 + Q-D + Q-G).
3. :func:`_build_sample_plan` constructs a single-symbol TradePlan for the
   segment's benchmark ETF (Q-A A1 — XLK for IT, XLF for Financials, ...).
4. **`with tune_override({segment: candidate}):`** (§5.3 W2) — make the
   candidate visible to the validate fold loop without writing to disk first.
5. :func:`openbb_techtrade.validation.backtest_bridge.validate_plan` -> verdict.
6. If ``verdict == "robust"`` AND ``candidate != DEFAULT_CONFIG`` (Q-F guard 3
   no-op): :func:`tuning.tuned_defaults.write_tuned` persists. Otherwise the
   :class:`TuningReport` carries ``persisted=False`` and a diagnostic reason
   (Q-F transparent non-persist).
7. Return ``OBBject[TuningReport]``.

Note: this module deliberately does **not** use ``from __future__ import
annotations``. The ``tune`` command takes a ``segment: str`` (simple),
but the package builder still needs to see the real :class:`TradePlan` and
:class:`TuningReport` classes — mirroring the
:mod:`openbb_techtrade.validation.validate_router` convention.
"""

import logging
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.models import (
    EntryExitRule,
    MoverSignal,
    Recommendation,
    TradePlan,
    TuningReport,
)
from openbb_techtrade.tuning.sector_ohlcv import (
    DEFAULT_FORWARD_HORIZON_BARS,
    DEFAULT_HORIZON_YEARS,
    pool_sector_ohlcv,
)
from openbb_techtrade.tuning.tuned_defaults import tune_override, write_tuned
from openbb_techtrade.tuning.tuneta_adapter import fit_segment
from openbb_techtrade.validation.backtest_bridge import validate_plan

logger = logging.getLogger(__name__)

#: Q-A A1: the sector ETF used as the sample-plan symbol for the per-segment validate.
#: Sourced from the 11 GICS Select Sector SPDRs (long-stable, liquid, deterministic).
SEGMENT_BENCHMARK_ETFS: dict[str, str] = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples":       "XLP",
    "Energy":                 "XLE",
    "Financials":             "XLF",
    "Health Care":            "XLV",
    "Industrials":            "XLI",
    "Information Technology": "XLK",
    "Materials":              "XLB",
    "Real Estate":            "XLRE",
    "Utilities":              "XLU",
}


router = Router(prefix="", description="Per-segment indicator-period tuning gated by validation.")


def _build_sample_plan(segment: str, as_of: date) -> TradePlan:
    """Construct a deterministic single-symbol TradePlan for the segment's ETF (Q-A A1).

    validate_plan only reads ``symbol`` + ``as_of`` + ``rule.entry_threshold`` from
    the plan (#82 design §3.2 — orders / fills / recommendation fields are
    attach targets, not validation inputs). The fixture below satisfies the
    input contract with deterministic zeroed values.
    """
    if segment not in SEGMENT_BENCHMARK_ETFS:
        raise ValueError(
            f"unknown segment {segment!r}; valid: {sorted(SEGMENT_BENCHMARK_ETFS)}"
        )
    etf = SEGMENT_BENCHMARK_ETFS[segment]
    sig = MoverSignal(
        symbol=etf, segment=segment, as_of=as_of,
        score=0.5, direction="long", votes=[], rank_in_segment=1,
    )
    rec = Recommendation(
        symbol=etf, segment=segment, as_of=as_of,
        action="BUY", conviction="Medium", score=0.5,
        entry_price=Decimal("100.00"), stop_price=Decimal("98.00"),
        target_price=Decimal("104.00"),
        stop_distance_pct=0.02, target_distance_pct=0.04,
        risk_reward=2.0, atr=2.0,
        position_size=Decimal("1"), risk_per_share=Decimal("2.00"),
        risk_pct_of_notional=0.0, time_stop_bars=20,
        reasoning="", top_factors=[], caveats="Tuneta sample plan (Q-A A1).",
    )
    return TradePlan(
        symbol=etf, segment=segment, as_of=as_of,
        signal=sig, rule=EntryExitRule(),
        position_size=Decimal("1"), orders=[], simulated_fills=[],
        recommendation=rec,
    )


def _reason_for(verdict: str, report: Any, *, no_op: bool) -> str:
    """Build the human-stable reason string (Q-F + Q-F guard 4 stable shape)."""
    if no_op:
        return "no change from defaults"
    pbo = getattr(report, "pbo", float("nan"))
    dsr = getattr(report, "deflated_sharpe", float("nan"))
    # Stable field order + 2-decimal precision so two runs produce identical strings.
    return f"verdict={verdict} (pbo={pbo:.2f}, dsr={dsr:.2f})"


@router.command(methods=["POST"])
async def tune(
    segment: str,
    *,
    as_of: date | None = None,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
    forward_horizon_bars: int = DEFAULT_FORWARD_HORIZON_BARS,
    trials: int = 100,
    early_stop: int = 20,
    method: str = "wfo",
    thresholds: dict[str, float] | None = None,
    provider: str | None = None,
) -> OBBject:
    """Tune indicator periods for a GICS segment, gated by #82's validate (PRD §12.4, §15).

    Steps (design §4.1):

    1. Pool the segment's universe OHLCV into ``(X, y)`` (L4 + Q-C horizon
       window + Q-B forward-return target).
    2. Fit tuneta over the L6 8-knob search space -> candidate IndicatorConfig.
    3. Build a sample TradePlan for the segment's benchmark ETF (Q-A A1).
    4. ``with tune_override({segment: candidate}):`` make the candidate
       visible to the validate fold loop without writing to disk first
       (§5.3 W2 — safe because #82's fold loop is sequential in-thread).
    5. ``validate_plan(plan, method=method, thresholds=thresholds,
       horizon_years=horizon_years, provider=provider)`` -> verdict.
    6. Gate: if verdict == "robust" AND the candidate genuinely differs from
       DEFAULT_CONFIG (Q-F guard 3) -> persist via write_tuned. Otherwise
       persisted=False + a diagnostic reason string. Logged at WARNING on
       fragile/overfit so a long loop is visible without an exception.
    7. Return OBBject[TuningReport].

    Raises
    ------
    TechtradeDependencyError
        When ``tuneta`` is not installed (raised by fit_segment via
        :func:`_require_tuneta`); or when ``openbb-backtest`` is not installed
        (raised by validate_plan via #82's ``_require_backtest``). The error
        message names the specific extra; for a full tune the user needs both
        ``[tuneta]`` and ``[validation]``.
    ValueError
        If ``segment`` is not one of the 11 GICS sectors in
        :data:`SEGMENT_BENCHMARK_ETFS` (Q-A A1).
    """
    effective_as_of = as_of if as_of is not None else date.today()
    plan = _build_sample_plan(segment, effective_as_of)

    X, y = pool_sector_ohlcv(
        segment,
        as_of=effective_as_of,
        horizon_years=horizon_years,
        forward_horizon_bars=forward_horizon_bars,
    )
    candidate, meta = fit_segment(X, y, trials=trials, early_stop=early_stop)

    with tune_override({segment: candidate}):
        _updated_plan, report = await validate_plan(
            plan,
            method=method, thresholds=thresholds,
            horizon_years=horizon_years, provider=provider,
        )

    verdict = getattr(report, "verdict", "unknown")
    no_op = candidate == DEFAULT_CONFIG
    persisted = False
    if verdict == "robust" and not no_op:
        write_tuned(
            segment, candidate,
            meta={
                "verdict": verdict,
                "pbo": getattr(report, "pbo", None),
                "dsr": getattr(report, "deflated_sharpe", None),
                "oos_sharpe": getattr(
                    getattr(report, "oos_metrics", None), "sharpe", None
                ),
                "tuned_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                            .replace("+00:00", "Z"),
                "tuneta_version": meta["tuneta_version"],
                "as_of": effective_as_of.isoformat(),
                "horizon_years": horizon_years,
            },
        )
        persisted = True
    elif verdict != "robust":
        logger.warning(
            "tune: segment %s verdict=%s -> not persisted (pbo=%s dsr=%s)",
            segment, verdict,
            getattr(report, "pbo", None),
            getattr(report, "deflated_sharpe", None),
        )

    return OBBject(results=TuningReport(
        segment=segment,
        as_of=effective_as_of,
        candidate=candidate,
        validation=report,  # ValidationReport satisfies Data | None (L2-of-82)
        persisted=persisted,
        reason=_reason_for(verdict, report, no_op=no_op),
        tuneta_version=meta["tuneta_version"],
        fit_seconds=meta["fit_seconds"],
        trials=trials,
        early_stop=early_stop,
    ))
```

- [ ] **Step 5: Register the sub-router in `techtrade_router.py`**

Modify `openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py`. Find the `_include_subrouters` function (currently lines 30–48). Add one new entry to the tuple — keep alphabetical/phase order so reviewers see the new sub-router in the right place:

```python
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
        ("openbb_techtrade.tuning.tune_router", "router"),  # NEW (#83 P7)
    ):
        try:
            module = import_module(module_path)
        except ImportError:
            continue
        router.include_router(getattr(module, attr))
```

The existing `try / except ImportError: continue` pattern means the `tune` sub-router is silently skipped if either `tuneta` OR `openbb-backtest` is absent (because `tune_router` imports `validate_plan`, which itself triggers an `ImportError` at top-level). That's the correct degradation behavior — but note that since `tune_router.py` doesn't actually `import tuneta` at module top level, an `ImportError` here will only fire if `validation.backtest_bridge` fails to import (i.e. when `openbb-backtest` is absent). The "tuneta-only-absent" case surfaces inside the command body via `fit_segment` -> `_require_tuneta`, which is the Q-G design.

- [ ] **Step 6: Run the tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_tune_router.py -v
```

Expected: **7 passed** (the 2 `test_non_robust_verdict_does_not_persist` parametrize cases count as 2).

If `test_override_visible_in_validate_fold` fails, the most likely cause is that the router forgot the `with tune_override({segment: candidate}):` block around the `validate_plan` call — re-read the router body.

- [ ] **Step 7: Verify the sub-router is auto-registered**

```
.venv_win\Scripts\python.exe -c "from openbb_techtrade.techtrade_router import router; paths = [r.path for r in router.api_router.routes]; print('tune route present:', any('tune' in p for p in paths))"
```

Expected: `tune route present: True`. (Confirms the sub-router registration path works end-to-end through `_include_subrouters`.)

- [ ] **Step 8: Commit T5**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/tuning/tune_router.py openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py openbb_platform/extensions/techtrade/tests/unit/test_tune_router.py
git commit -m "$(cat <<'EOF'
feat(83): tune_router + register sub-router — orchestrate pool/fit/validate/persist

T5 of the #83 implementation plan. Wires everything T2-T4 built plus #82's
validate_plan into the obb.techtrade.tune(segment, ...) command (L7 single-
segment shape).

Pipeline (design §4.1):
1. pool_sector_ohlcv(segment, as_of, horizon_years, forward_horizon_bars)
   -> (X, y)  [T3, L4, Q-B, Q-C]
2. fit_segment(X, y, trials, early_stop) -> (candidate, meta)  [T4, L6, Q-D]
3. _build_sample_plan(segment, as_of) -> TradePlan for the sector ETF
   [Q-A A1: XLK / XLF / XLV / ... — 11 GICS sectors with their Select Sector
   SPDR benchmark]
4. with tune_override({segment: candidate}): the §5.3 W2 contextvar override
   makes the candidate visible to validate's re-run of techtrade_confluence
   WITHOUT touching the file. Safe because #82's fold loop is sequential
   in-thread (verified during design Phase 1).
5. validate_plan(plan, ...) -> ValidationReport with verdict
6. L2 strict gate: persist only on verdict == "robust" AND a genuinely-
   different candidate (Q-F guard 3 no-op check — DEFAULT_CONFIG is never
   re-persisted as itself).
7. Return OBBject[TuningReport] with persisted, reason (stable shape per
   Q-F guard 4), tuneta_version, fit_seconds, trials, early_stop.

Fragile/overfit logs at WARNING and continues — a long sector loop is
visible to the caller without an exception aborting mid-batch (Q-F guard 2).

Sub-router registered via the existing _include_subrouters tuple in
techtrade_router.py. The try/except ImportError pattern already there means
the new sub-router is silently skipped when openbb-backtest is absent (via
the validate_plan import chain) — the tuneta-only-absent case surfaces
inside the command body via fit_segment, which is the Q-G design.

7 unit tests (2 parametrized) cover: sample plan uses benchmark ETF (Q-A
A1), all 11 GICS sectors mapped, robust verdict persists, fragile/overfit
do not persist, no-op tune doesn't persist, mixed-verdict loop completes
without raising (Q-F guard 2), contextvar override visible mid-validate
(§5.3 W2), trials/early_stop forwarding.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: Close T5 bd child + claim T6**

```
bd close <T5-bead-id> --resolution=completed --comment "tune_router + registration; 7/7 tests green; sub-router auto-registers"
bd update <T6-bead-id> --status=in_progress
```

---

## Task 6: `engine/indicators.py` — L9 auto-load on the panel-builder hot path

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py` (signature of `build_indicator_panel`; new lookup call)
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_panel_consults_tuned_defaults.py`

**Interfaces:**
- Consumes: `lookup_tuned_for_symbol` from T2's `tuning.tuned_defaults`
- Produces:
  - `build_indicator_panel(symbol, as_of, rows, *, config: IndicatorConfig | None = None) -> IndicatorPanel` — when `config is None`, auto-loads via `lookup_tuned_for_symbol(symbol)`, falling back to `DEFAULT_CONFIG` if no tuned entry exists

---

- [ ] **Step 1: Read the current `build_indicator_panel` signature**

```
.venv_win\Scripts\python.exe -c "import openbb_techtrade.engine.indicators as i; import inspect; print(inspect.signature(i.build_indicator_panel))"
```

Expected output: `(symbol: str, as_of: datetime.date, rows: list[dict], config: openbb_techtrade.engine.indicators.IndicatorConfig = IndicatorConfig(...))`.

The current signature takes `config` positionally with a default. The Task changes it to keyword-only `config: IndicatorConfig | None = None`. Verify every existing caller (in `engine/`, `validation/`, `tests/`) passes `config=` by keyword:

```
.venv_win\Scripts\python.exe -c "import subprocess; subprocess.run(['grep', '-rn', 'build_indicator_panel(', 'openbb_platform/extensions/techtrade/', '--include=*.py'])"
```

(Or use the Grep tool.) If **any** caller passes `config` positionally, fix those callsites in the same commit so T6 stays backward-compatible internally.

- [ ] **Step 2: Write the failing tests (3 tests)**

Create `openbb_platform/extensions/techtrade/tests/unit/test_panel_consults_tuned_defaults.py`:

```python
"""Unit tests for the L9 auto-load: build_indicator_panel consults tuned_defaults."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from openbb_techtrade.engine.indicators import (
    DEFAULT_CONFIG,
    IndicatorConfig,
    build_indicator_panel,
)


def _synth_rows(n: int = 250, *, base: float = 100.0) -> list[dict]:
    """A deterministic OHLCV stream long enough for every indicator to warm up."""
    rows = []
    for i in range(n):
        close = base + 0.01 * i + (i % 7) * 0.05
        rows.append({
            "open": close - 0.1, "high": close + 0.2, "low": close - 0.2,
            "close": close, "volume": 1_000_000.0,
        })
    return rows


def _tuned_config() -> IndicatorConfig:
    """A non-default IndicatorConfig (every period knob shifted by +2)."""
    return replace(
        DEFAULT_CONFIG,
        macd_fast=DEFAULT_CONFIG.macd_fast + 2,
        macd_slow=DEFAULT_CONFIG.macd_slow + 2,
        macd_signal=DEFAULT_CONFIG.macd_signal + 2,
        adx_length=DEFAULT_CONFIG.adx_length + 2,
        ema_fast=DEFAULT_CONFIG.ema_fast + 2,
        ema_slow=DEFAULT_CONFIG.ema_slow + 2,
        rsi_length=DEFAULT_CONFIG.rsi_length + 2,
        atr_length=DEFAULT_CONFIG.atr_length + 2,
    )


def test_panel_falls_back_to_default_when_no_tuned_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L9 regression: with no tuned file, panel uses DEFAULT_CONFIG (existing behaviour preserved)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache
    _clear_cache()

    rows = _synth_rows()
    panel = build_indicator_panel("AAPL", as_of=date(2025, 6, 20), rows=rows)
    # The default RSI_length is 14 — a panel built with config=None and no tuned
    # file should still have a finite RSI value computed at the default period.
    assert "rsi" in panel.momentum
    assert isinstance(panel.momentum["rsi"], float)


def test_panel_uses_tuned_when_segment_has_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L9: after writing a tuned config for IT, building a panel for AAPL (IT) uses tuned periods."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache, write_tuned
    _clear_cache()

    tuned = _tuned_config()
    write_tuned("Information Technology", tuned,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})

    rows = _synth_rows()
    panel_tuned = build_indicator_panel("AAPL", as_of=date(2025, 6, 20), rows=rows)
    panel_default = build_indicator_panel(
        "AAPL", as_of=date(2025, 6, 20), rows=rows, config=DEFAULT_CONFIG,
    )

    # The tuned RSI period (default + 2 = 16) yields a different value than the
    # default period (14) on the same OHLCV stream. If they're identical, the
    # auto-load did not fire.
    assert panel_tuned.momentum["rsi"] != panel_default.momentum["rsi"], (
        "panel built with config=None and a tuned IT entry must use the tuned "
        "RSI period (default+2), not DEFAULT_CONFIG.rsi_length"
    )


def test_explicit_config_overrides_tuned_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L9: passing config=X explicitly bypasses tuned-defaults lookup (caller intent wins)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache, write_tuned
    _clear_cache()

    tuned = _tuned_config()
    write_tuned("Information Technology", tuned,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})

    rows = _synth_rows()
    # Caller passes config=DEFAULT_CONFIG explicitly. Auto-load must NOT fire.
    panel_explicit = build_indicator_panel(
        "AAPL", as_of=date(2025, 6, 20), rows=rows, config=DEFAULT_CONFIG,
    )
    # Sanity check: the same explicit call without any tuned file gives the same
    # RSI value.
    panel_no_tuned_file = build_indicator_panel(
        "MSFT", as_of=date(2025, 6, 20), rows=rows, config=DEFAULT_CONFIG,
    )
    assert panel_explicit.momentum["rsi"] == panel_no_tuned_file.momentum["rsi"]
```

- [ ] **Step 3: Run the failing tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_panel_consults_tuned_defaults.py -v
```

Expected: `test_panel_falls_back_to_default_when_no_tuned_entry` **PASSES** (the current default behaviour is already "use `DEFAULT_CONFIG`"). `test_panel_uses_tuned_when_segment_has_entry` **FAILS** with an assertion that the two panels are equal (the auto-load isn't wired yet). `test_explicit_config_overrides_tuned_lookup` should also pass.

- [ ] **Step 4: Modify `build_indicator_panel`'s signature + add the lookup**

Open `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py`. Find `build_indicator_panel` (search for `def build_indicator_panel`). The current signature is roughly:

```python
def build_indicator_panel(
    symbol: str,
    as_of: date,
    rows: list[dict],
    config: IndicatorConfig = DEFAULT_CONFIG,
) -> IndicatorPanel:
    ...
```

Change to:

```python
def build_indicator_panel(
    symbol: str,
    as_of: date,
    rows: list[dict],
    *,
    config: IndicatorConfig | None = None,
) -> IndicatorPanel:
    """Build the per-symbol indicator panel (PRD §11, #72).

    Parameters
    ----------
    symbol, as_of, rows
        See module docstring for shape constraints.
    config
        Indicator periods. ``None`` (default, **keyword-only**, #83 L9): consult
        ``~/.openbb_platform/techtrade_tuned.json`` for ``symbol``'s GICS sector
        via :func:`openbb_techtrade.tuning.tuned_defaults.lookup_tuned_for_symbol`
        and use the tuned :class:`IndicatorConfig` if a robust entry is present
        for that sector; otherwise fall back to :data:`DEFAULT_CONFIG`. Pass
        ``config=X`` explicitly to bypass the auto-load (caller intent wins —
        useful for golden / regression tests).

    Notes
    -----
    The auto-load adds one ``os.stat`` per call on the hot path (the
    :func:`~openbb_techtrade.tuning.tuned_defaults._read_tuned_cached`
    ``lru_cache`` is keyed on ``(path, mtime_ns, st_size)`` so the parse cost is
    paid once per file write, not per symbol). The lookup module imports
    neither ``tuneta`` nor ``openbb_backtest``, so it is safe to call on a bare
    techtrade install.
    """
    if config is None:
        # Lazy import: avoids a hot-path import cycle if any future tuning module
        # needs to import indicators (none does today; cheap insurance).
        from openbb_techtrade.tuning.tuned_defaults import lookup_tuned_for_symbol
        config = lookup_tuned_for_symbol(symbol) or DEFAULT_CONFIG
    # ... rest of existing function body unchanged ...
```

> **Why keyword-only:** the signature change from `config: IndicatorConfig = DEFAULT_CONFIG` (positional with default) to `config: IndicatorConfig | None = None` (keyword-only) is technically a public-API change. Making it keyword-only forces *new* callers to be explicit about it, while every existing in-repo caller already passes by keyword (verified in Step 1). The `*,` is what enforces this — without it, an old caller doing `build_indicator_panel("AAPL", date(...), rows, my_config)` would type-check successfully and silently pass `my_config` even when the auto-load should fire.

If Step 1 found callers passing `config` positionally, fix them in the same commit: change `build_indicator_panel("AAPL", as_of, rows, my_config)` → `build_indicator_panel("AAPL", as_of, rows, config=my_config)`.

- [ ] **Step 5: Run the panel tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_panel_consults_tuned_defaults.py -v
```

Expected: **3 passed**.

- [ ] **Step 6: Run the existing indicator tests for regression**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_indicators.py openbb_platform/extensions/techtrade/tests/unit/test_indicators_technical.py -v
```

Expected: **all PASS, no skip changes**. If anything fails because a test was calling `build_indicator_panel(symbol, as_of, rows, config)` positionally, fix the test in the same commit — but flag the change in the commit message.

- [ ] **Step 7: Smoke-check the `signals` / `plan` / `scan` paths still work**

These commands all feed through `build_indicator_panel`. Run their unit suites:

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_signals.py openbb_platform/extensions/techtrade/tests/unit/test_plan.py openbb_platform/extensions/techtrade/tests/unit/test_scan.py -v
```

Expected: **all PASS**.

- [ ] **Step 8: Commit T6**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py openbb_platform/extensions/techtrade/tests/unit/test_panel_consults_tuned_defaults.py
# If Step 4 fixed any positional-config callsites, add those files too:
# git add openbb_platform/extensions/techtrade/openbb_techtrade/engine/<file_with_positional_config>.py

git commit -m "$(cat <<'EOF'
feat(83): engine.indicators — L9 auto-load tuned configs by symbol→segment

T6 of the #83 implementation plan. The user-visible payoff: once
obb.techtrade.tune persists a robust IndicatorConfig for a sector, every
subsequent obb.techtrade.scan / plan / signals call for any symbol in that
sector uses the tuned periods transparently — no caller change required.

Change to build_indicator_panel:
- BEFORE: build_indicator_panel(symbol, as_of, rows, config=DEFAULT_CONFIG)
- AFTER:  build_indicator_panel(symbol, as_of, rows, *, config=None)

When config is None (the new default), the panel builder calls
tuning.tuned_defaults.lookup_tuned_for_symbol(symbol), which resolves the
symbol's GICS sector and returns the tuned IndicatorConfig if a robust entry
exists in ~/.openbb_platform/techtrade_tuned.json — else None, and we fall
back to DEFAULT_CONFIG. Explicit config= argument bypasses the auto-load
(caller intent wins — golden / regression tests pass config=DEFAULT_CONFIG
to preserve their existing expectations).

Three design notes:
- Keyword-only via `*,` so a future positional caller can't silently bypass
  the auto-load by accident. Every existing in-repo caller already passes
  config= by keyword (verified during T6 Step 1).
- Lazy import of lookup_tuned_for_symbol inside the function body (cheap
  insurance against future import-cycle scenarios; the lookup module is
  cycle-free today).
- The lookup adds ~1 os.stat per call; the lru_cache(maxsize=8) keyed on
  (path, mtime_ns, st_size) makes the parse cost a once-per-file-write
  amortization, not a per-symbol hit.

3 new tests in test_panel_consults_tuned_defaults.py: regression (no tuned
file -> DEFAULT_CONFIG; preserves existing behaviour), tuned config takes
effect (panel for AAPL with a tuned IT entry differs from a DEFAULT_CONFIG
panel), explicit config bypasses lookup. Existing indicator / signals /
plan / scan unit suites all green (T6 Step 6-7 regression check).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: Close T6 bd child + claim T7**

```
bd close <T6-bead-id> --resolution=completed --comment "L9 auto-load wired; 3/3 new tests green; signals/plan/scan regression-free"
bd update <T7-bead-id> --status=in_progress
```

---

## Task 7: Integration test + degradation truth-table extension

**Files:**
- Create: `openbb_platform/extensions/techtrade/tests/integration/test_tune.py`
- Modify: the #85-style degradation test file (likely `openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py::test_degradation_other_modules_still_import` from #82) — add the `tuneta`-also-absent truth-table row
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_neither_extra_imports.py` (the Q-G guard 3 standalone)

**Interfaces:**
- Consumes: everything (full end-to-end). Nothing produced.

---

- [ ] **Step 1: Write `test_neither_extra_imports.py` (Q-G guard 3)**

The degradation case the design's Q-G guard 3 calls out: with **both** `tuneta` and `openbb-backtest` forced absent, the top-level `openbb_techtrade` package, the engine modules, the new `tuning.*` modules, AND the L9 hot path (`build_indicator_panel` with `config=None`) all still work — the L9 lookup falls through to `DEFAULT_CONFIG` and the panel builds normally.

Create `openbb_platform/extensions/techtrade/tests/unit/test_neither_extra_imports.py`:

```python
"""Q-G guard 3: techtrade hot path imports + works with BOTH extras absent (#83 L9 + #85 discipline)."""

from __future__ import annotations

import builtins
import importlib
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest


def _block_imports_of(monkeypatch: pytest.MonkeyPatch, *prefixes: str) -> None:
    """Force any future ``import <prefix>...`` to raise ImportError."""
    for module_name in list(sys.modules):
        if any(module_name == p or module_name.startswith(p + ".") for p in prefixes):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocker)


def test_techtrade_hot_path_imports_with_both_extras_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Q-G guard 3: import openbb_techtrade + build_indicator_panel all work with neither extra."""
    _block_imports_of(monkeypatch, "tuneta", "openbb_backtest")
    # Pin the tuned file path at a fresh location so lookup_tuned_for_symbol
    # returns None and the L9 path falls through to DEFAULT_CONFIG.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )

    # 1. Top-level techtrade still imports.
    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.models",
        "openbb_techtrade.engine.indicators",
        "openbb_techtrade.tuning",
        "openbb_techtrade.tuning.tuned_defaults",
        "openbb_techtrade.tuning.sector_ohlcv",
        "openbb_techtrade.tuning.tuneta_adapter",
    ):
        importlib.import_module(module_name)

    # 2. The L9 hot path works.
    from openbb_techtrade.engine.indicators import build_indicator_panel
    rows = [
        {"open": 100.0 + i * 0.01, "high": 100.2 + i * 0.01,
         "low": 99.8 + i * 0.01, "close": 100.0 + i * 0.01,
         "volume": 1_000_000.0}
        for i in range(250)
    ]
    panel = build_indicator_panel("AAPL", as_of=date(2025, 6, 20), rows=rows)
    assert "rsi" in panel.momentum  # built via DEFAULT_CONFIG fallback


def test_tune_raises_dependency_error_with_tuneta_absent(monkeypatch: pytest.MonkeyPatch):
    """Q-G: tune raises TechtradeDependencyError naming the [tuneta] extra (not [validation])."""
    _block_imports_of(monkeypatch, "tuneta")
    # openbb_backtest stays available so the failure is unambiguously about tuneta.

    import asyncio
    from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError
    from openbb_techtrade.tuning.tune_router import tune

    with pytest.raises(TechtradeDependencyError) as excinfo:
        asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))
    msg = str(excinfo.value)
    assert "tuneta" in msg
    assert "openbb-techtrade[tuneta]" in msg
```

- [ ] **Step 2: Extend the #82 degradation test for the joint "both absent" case**

Open `openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py`. Find the `test_degradation_other_modules_still_import` function (created in #82). The existing test forces only `openbb_backtest` absent. Add a new test (do NOT modify the original — it's the #82 acceptance test):

Append at the end of `test_backtest_bridge.py`:

```python
def test_degradation_with_tuneta_also_absent(monkeypatch: pytest.MonkeyPatch):
    """#83 Q-G: extend the #82 truth table — with BOTH openbb_backtest AND tuneta absent,
    every other techtrade module still imports cleanly (the #85 core-unchanged-when-removed
    discipline applied to both optional extras at once).
    """
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if name.startswith("openbb_backtest") or name.startswith("tuneta"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    for module_name in list(sys.modules):
        if module_name.startswith("openbb_backtest") or module_name.startswith("tuneta"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocker)

    # Every techtrade module — including the NEW tuning ones — must still import.
    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.engine.plan",
        "openbb_techtrade.engine.scan",
        "openbb_techtrade.engine.signals",
        "openbb_techtrade.engine.execution",
        "openbb_techtrade.reporting.excel_export",
        # NEW for #83:
        "openbb_techtrade.tuning",
        "openbb_techtrade.tuning.tuned_defaults",
        "openbb_techtrade.tuning.sector_ohlcv",
        "openbb_techtrade.tuning.tuneta_adapter",  # the only tuneta-touching module — must still import
    ):
        importlib.import_module(module_name)
```

- [ ] **Step 3: Run the degradation tests**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_neither_extra_imports.py openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py::test_degradation_with_tuneta_also_absent openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py::test_degradation_other_modules_still_import -v
```

Expected: **3 passed** (the new `test_techtrade_hot_path_imports_with_both_extras_absent`, the new `test_tune_raises_dependency_error_with_tuneta_absent`, the new `test_degradation_with_tuneta_also_absent`; the original `test_degradation_other_modules_still_import` from #82 stays green too).

- [ ] **Step 4: Write the integration test**

Create `openbb_platform/extensions/techtrade/tests/integration/test_tune.py`:

```python
"""Integration test for #83 obb.techtrade.tune — end-to-end against in-tree backtest + real tuneta.

Runs a single-segment tune against the **real** openbb-backtest validate router AND
real tuneta on a small ETF-pooled universe (kept tiny for cost-bounded CI). Skips
cleanly when ANY of (tuneta, openbb-backtest, fmp_cached) is absent so the default
offline unit sweep is unaffected.

The integration window is intentionally small (1y, top-3 universe) so a single
tuneta fit + a single validate run completes in a few minutes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest


_TUNETA_AVAILABLE = importlib.util.find_spec("tuneta") is not None
_BACKTEST_AVAILABLE = importlib.util.find_spec("openbb_backtest") is not None


def _fmp_cached_available() -> bool:
    """Best-effort probe (mirrors test_validate.py)."""
    if importlib.util.find_spec("openbb_fmp_cached") is None:
        return False
    settings = Path.home() / ".openbb_platform" / "user_settings.json"
    if not settings.exists():
        return False
    try:
        cred = json.loads(settings.read_text(encoding="utf-8")).get("credentials", {})
        return bool(cred.get("fmp_cached_api_key") or cred.get("fmp_api_key"))
    except Exception:  # noqa: BLE001 - any read failure -> skip
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _TUNETA_AVAILABLE,
        reason="tuneta not installed; install with: pip install 'openbb-techtrade[tuneta]'",
    ),
    pytest.mark.skipif(
        not _BACKTEST_AVAILABLE,
        reason="openbb-backtest not installed; install with: pip install 'openbb-techtrade[validation]'",
    ),
    pytest.mark.skipif(
        not _fmp_cached_available(),
        reason="fmp_cached provider / API key not configured for live integration",
    ),
]


def test_tune_returns_coherent_report_against_real_validate(tmp_path, monkeypatch):
    """End-to-end: tune one segment, get back a TuningReport with a real verdict."""
    # Pin the persistence path at tmp_path so the integration run doesn't pollute the
    # user's real ~/.openbb_platform/techtrade_tuned.json.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    # Use a short 1y window + small universe to keep wall-clock bounded.
    from openbb_techtrade.tuning.tune_router import tune

    obb = asyncio.run(tune(
        segment="Information Technology",
        as_of=date(2024, 12, 13),  # deterministic Friday in late 2024
        horizon_years=1,            # short
        trials=20,                  # small budget for CI
        early_stop=5,
    ))
    report = obb.results

    # Shape assertions:
    assert report.segment == "Information Technology"
    assert report.as_of == date(2024, 12, 13)
    assert report.candidate is not None
    assert report.validation is not None
    assert report.tuneta_version  # non-empty
    assert report.fit_seconds > 0
    # The verdict must be one of the locked three.
    verdict = getattr(report.validation, "verdict", None)
    assert verdict in {"robust", "fragile", "overfit"}
    # If robust AND not a no-op tune -> file should now exist.
    if report.persisted:
        assert (tmp_path / "techtrade_tuned.json").exists()
        assert "verdict=robust" in report.reason
    else:
        # File may or may not exist depending on prior tunes in tmp_path
        # (which is fresh per-test, so it WON'T exist). Reason must explain why.
        assert any(
            marker in report.reason
            for marker in ("verdict=fragile", "verdict=overfit", "no change from defaults")
        )
```

- [ ] **Step 5: Run the integration test**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/integration/test_tune.py -v -m integration
```

Expected (in dev sandbox without `tuneta` installed): **1 skipped** with reason `tuneta not installed; install with: pip install 'openbb-techtrade[tuneta]'`. That's the correct degradation.

If `tuneta` IS installed + `openbb-backtest` IS in-tree + `fmp_cached` IS configured: the test runs end-to-end (~5–10 minutes for the 1y / trials=20 / 5-symbol pool). The verdict can be any of the three; the test only asserts shape and consistency.

- [ ] **Step 6: Final regression — every per-file techtrade unit suite green**

The whole-tree `pytest openbb_platform/extensions/techtrade` is blocked by `bd OpenBBTechnical-46y` (pytest collection collision). Run per-file:

```
.venv_win\Scripts\python.exe -m pytest \
  openbb_platform/extensions/techtrade/tests/unit/test_models.py \
  openbb_platform/extensions/techtrade/tests/unit/test_pyproject_extras.py \
  openbb_platform/extensions/techtrade/tests/unit/test_tuned_defaults.py \
  openbb_platform/extensions/techtrade/tests/unit/test_sector_ohlcv.py \
  openbb_platform/extensions/techtrade/tests/unit/test_tuneta_adapter.py \
  openbb_platform/extensions/techtrade/tests/unit/test_tune_router.py \
  openbb_platform/extensions/techtrade/tests/unit/test_panel_consults_tuned_defaults.py \
  openbb_platform/extensions/techtrade/tests/unit/test_neither_extra_imports.py \
  openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py \
  openbb_platform/extensions/techtrade/tests/unit/test_indicators.py \
  openbb_platform/extensions/techtrade/tests/unit/test_signals.py \
  openbb_platform/extensions/techtrade/tests/unit/test_plan.py \
  openbb_platform/extensions/techtrade/tests/unit/test_scan.py \
  -v
```

Expected: **every file green** (each module's test count adds up to the running total seen across T1–T6 commits + the original #82 14/14 + the existing pre-#83 suites).

- [ ] **Step 7: Commit T7**

```bash
git add openbb_platform/extensions/techtrade/tests/integration/test_tune.py openbb_platform/extensions/techtrade/tests/unit/test_neither_extra_imports.py openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py
git commit -m "$(cat <<'EOF'
test(83): integration + extend #82 degradation truth table for tuneta absence

T7 of the #83 implementation plan — the cross-task verification layer.

1. tests/integration/test_tune.py: end-to-end tune of one GICS sector against
   the real openbb-backtest validate router + real tuneta against fmp_cached.
   Small budget (1y window, trials=20, top-5 sector universe) so the
   wall-clock stays bounded. Skipif tuneta / openbb-backtest / fmp_cached
   absent — the default offline unit sweep is unchanged.

2. tests/unit/test_neither_extra_imports.py: Q-G guard 3. With BOTH tuneta
   AND openbb_backtest forced absent, the top-level package + tuning
   submodules + the L9 hot path (build_indicator_panel with config=None)
   all still work — the lookup falls through to DEFAULT_CONFIG and the
   panel builds. AND tune itself raises TechtradeDependencyError with a
   tuneta-specific message.

3. tests/unit/test_backtest_bridge.py: extend the existing #82
   test_degradation_other_modules_still_import with a sibling
   test_degradation_with_tuneta_also_absent that forces both extras absent
   simultaneously — every techtrade module (including the new tuning.*
   ones) imports cleanly. The original #82 test stays untouched.

This completes the #83 implementation. The full per-file unit-suite
regression sweep (T7 Step 6) was green. Whole-tree pytest is still blocked
by the pre-existing bd OpenBBTechnical-46y collection collision, which is
tracked separately.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Close T7 bd child + close the parent bead**

```
bd close <T7-bead-id> --resolution=completed --comment "integration + degradation truth table; T7 complete; all tests green per-file"
bd close OpenBBTechnical-950 --resolution=completed --comment "Implementation complete across T1-T7. obb.techtrade.tune(segment, ...) ships behind [tuneta] extra; gated on verdict==robust; auto-loads via L9. All acceptance criteria from issue #83 met. Whole-tree pytest still blocked by pre-existing bd OpenBBTechnical-46y; per-file sweep green."
```

- [ ] **Step 9: Post status comment on GitHub #83**

```bash
gh issue comment 83 --body "$(cat <<'EOF'
## #83 Implementation complete

Implemented across 7 commits on branch `trading_technicals`:

| Task | Commit | What landed |
|---|---|---|
| T1 | `<sha>` | `[tuneta]` extra in pyproject.toml + `TuningReport` model + 3 unit tests |
| T2 | `<sha>` | `tuning/tuned_defaults.py` (JSON persistence + mtime cache + contextvar override) + 8 unit tests |
| T3 | `<sha>` | `tuning/sector_ohlcv.py` (segment OHLCV pool + forward returns) + 5 unit tests |
| T4 | `<sha>` | `tuning/tuneta_adapter.py` (lazy tuneta import + knob table + column parser) + 10 unit tests |
| T5 | `<sha>` | `tuning/tune_router.py` (orchestration) + sub-router registration + 7 unit tests |
| T6 | `<sha>` | `engine/indicators.py` L9 auto-load + 3 unit tests |
| T7 | `<sha>` | Integration test + #82 degradation truth-table extension + neither-extra hot-path test |

### Acceptance criteria (all met)
- [x] `tuning/tuneta_adapter.py` behind the `[tuneta]` extra
- [x] `tune(segment, ...) → TuningReport` of proposed params
- [x] **Gate**: only params with `verdict == "robust"` from #82's validate persist; defaults ship un-tuned
- [x] Test: tuning proposes params; non-robust ones are rejected (parametrized over `fragile` + `overfit`)
- [x] `obb.techtrade.tune(...)` runs only when extra installed; otherwise clear message naming `[tuneta]`
- [x] Tuned params persist **only** if they pass validation
- [x] Core behavior unchanged when extra absent (extended #85 truth table covers both extras)

### Status
- bd `OpenBBTechnical-950` **CLOSED**
- 7-task TDD cycle; per-file pytest run shows every unit + integration green
- Whole-tree `pytest openbb_platform/extensions/techtrade` still blocked by `bd OpenBBTechnical-46y` (pre-existing pytest collection collision — unrelated to #83, tracked separately)
- Design doc: [`docs/designs/quant_trading/83-tuneta-adapter-tune-gated-validation.md`](https://github.com/prajoria/OpenBB/blob/trading_technicals/docs/designs/quant_trading/83-tuneta-adapter-tune-gated-validation.md)
- Implementation plan: [`docs/superpowers/plans/2026-06-21-83-tuneta-adapter-tune-gated-validation.md`](https://github.com/prajoria/OpenBB/blob/trading_technicals/docs/superpowers/plans/2026-06-21-83-tuneta-adapter-tune-gated-validation.md)

Closing as **complete**.
EOF
)"
gh issue close 83
```

---

## Beads decomposition (run BEFORE starting T1)

The parent bead `OpenBBTechnical-950` covers the whole feature; the seven Tasks become child beads with explicit dependency chain so `bd ready` always shows the right next-up. Run these once at plan-start; the per-Task `<TX-bead-id>` references above will be the IDs `bd create` returns here.

```bash
# T1 — bootstrap (no dependency; ready immediately after this block).
bd create \
  --title="83-T1: bootstrap (pyproject [tuneta] extra + TuningReport model)" \
  --description="Plan task T1. Files: pyproject.toml, models.py, test_models.py, test_pyproject_extras.py. Bootstrap commits the result type for everything downstream + declares the extra. See docs/superpowers/plans/2026-06-21-83-tuneta-adapter-tune-gated-validation.md (T1)." \
  --type=task --priority=2

# T2 — tuned_defaults (depends on T1 — needs IndicatorConfig from models? No: it imports from engine.indicators directly. T2 depends on T1 because the [tuneta] extra error message in T4 references the extra T1 declared. Keep linear for review simplicity.)
bd create \
  --title="83-T2: tuning.tuned_defaults (JSON + mtime cache + contextvar override)" \
  --description="Plan task T2. Files: tuning/__init__.py, tuning/tuned_defaults.py, test_tuned_defaults.py. Hot-path module + §5.3 W2 mechanism. 8 tests. See plan T2." \
  --type=task --priority=2
bd dep add <T2-id> <T1-id>

# T3 — sector_ohlcv (depends on T1 for the model namespace stability; doesn't import T2 but linear ordering is the right reviewer rhythm).
bd create \
  --title="83-T3: tuning.sector_ohlcv (pool segment OHLCV + forward returns)" \
  --description="Plan task T3. Files: tuning/sector_ohlcv.py, test_sector_ohlcv.py. Pure pandas; injectable fetcher. 5 tests. See plan T3." \
  --type=task --priority=2
bd dep add <T3-id> <T2-id>

# T4 — tuneta_adapter (depends on T2 because the error class is reused from validation.backtest_bridge which T2 indirectly depends on via the module import chain).
bd create \
  --title="83-T4: tuning.tuneta_adapter (lazy tuneta import + knob table + column parser)" \
  --description="Plan task T4. Files: tuning/tuneta_adapter.py, test_tuneta_adapter.py. The only tuneta-importing module. 10 tests. See plan T4." \
  --type=task --priority=2
bd dep add <T4-id> <T3-id>

# T5 — tune_router (depends on T2, T3, T4 — orchestrator).
bd create \
  --title="83-T5: tune_router + register sub-router" \
  --description="Plan task T5. Files: tuning/tune_router.py, techtrade_router.py (modify), test_tune_router.py. Orchestrates pool->fit->validate->persist. 7 tests. See plan T5." \
  --type=task --priority=2
bd dep add <T5-id> <T4-id>

# T6 — engine.indicators L9 auto-load (depends on T2 for the lookup function; touches an existing hot-path module).
bd create \
  --title="83-T6: engine.indicators — L9 auto-load tuned configs by symbol->segment" \
  --description="Plan task T6. Files: engine/indicators.py (modify), test_panel_consults_tuned_defaults.py. Public-API signature change (keyword-only config=None). 3 tests + regression sweep. See plan T6." \
  --type=task --priority=2
bd dep add <T6-id> <T5-id>

# T7 — integration + degradation truth table (depends on all of T1-T6).
bd create \
  --title="83-T7: integration test + extend #82 degradation truth table for tuneta absence" \
  --description="Plan task T7. Files: tests/integration/test_tune.py, tests/unit/test_neither_extra_imports.py, tests/unit/test_backtest_bridge.py (modify). End-to-end + the cross-task hot-path regression. See plan T7." \
  --type=task --priority=2
bd dep add <T7-id> <T6-id>

# Wire all 7 as blocking the parent.
for child in <T1-id> <T2-id> <T3-id> <T4-id> <T5-id> <T6-id> <T7-id>; do
  bd dep add OpenBBTechnical-950 $child
done

bd list
# Expected: T1 ready; T2-T7 blocked-by their predecessors; OpenBBTechnical-950 blocked-by all 7.
```

> **Implementer note:** when you start each Task, look up the actual bead ID `bd ready` shows (it's auto-promoted as the previous Task closes) and substitute it into the `<TX-bead-id>` placeholders in the per-Task "Close ... bd child + claim ..." steps.

---

## Self-Review (Run by plan author, not the implementer)

After writing the plan above, I re-read the design doc with fresh eyes and ran the three skill checks. Findings recorded here for the implementer's benefit (so issues that came up during plan-author review are visible in the plan rather than re-discovered during execution).

### 1. Spec coverage

Every section of the design has a corresponding Task or step:

| Design section | Implemented in |
|---|---|
| §0 L1 (periods only) | T4 KNOB_TABLE shape (8 entries, no weight knobs) |
| §0 L2 (strict `verdict == "robust"` gate) | T5 `test_robust_verdict_persists` + parametrized non-robust + Q-F guard 3 no-op |
| §0 L3 (per-user JSON) | T2 + T7 integration `tmp_path` discipline (doesn't pollute user file) |
| §0 L4 (pool segment) | T3 (full module + 5 tests) |
| §0 L5 (per-segment validate; execution-model note) | T5 (single validate call per tune); §5.3 W2 mechanism via T2 contextvar |
| §0 L6 (8 period knobs) | T4 KNOB_TABLE + test_knob_table_has_exactly_eight_period_knobs |
| §0 L7 (single-segment command) | T5 router signature is `tune(segment: str, ...)` |
| §0 L8 (soft dep + extra + reused error) | T1 (extra), T4 (lazy `_require_tuneta` + reused `TechtradeDependencyError`) |
| §0 L9 (auto-load on hot path) | T6 (modify `build_indicator_panel`) + T7 hot-path test |
| §1 module layout | T2/T3/T4/T5 each create one of the listed files |
| §2 dependency posture | T4 (the leaf error reuse + lazy import) + T7 (both-absent truth table) |
| §3 tuneta adapter | T4 (full module + 10 tests) |
| §4 tune command | T5 (full router + 7 tests) |
| §5 persistence + auto-load | T2 (persistence) + T6 (auto-load) |
| §5.3 W2 contextvar | T2 (`tune_override`), T5 (`with tune_override(...)`), T5 `test_override_visible_in_validate_fold` |
| §6 test matrix | Every test row in §6 is implemented across T2/T3/T4/T5/T6/T7 |
| Q-A A1 sample ETF | T5 SEGMENT_BENCHMARK_ETFS + 2 tests |
| Q-B B3 next-20-bar return | T3 default + math-by-hand test |
| Q-C 5y horizon | T3 DEFAULT_HORIZON_YEARS |
| Q-D trials=100, early_stop=20 | T4 default + T5 forwarding test |
| Q-E mtime cache + 2 guards | T2 (8 tests including `test_lru_cache_maxsize_bounded` + `test_mtime_cache_invalidates_on_change` for guard 2) |
| Q-F transparent non-persist + 4 guards | T5 (parametrized fragile/overfit, no-op, mixed-verdict-loop, stable reason shape via `_reason_for`) |
| Q-G lazy imports + 3 guards | T4 (lazy `_require_tuneta`), T5 (error names the extra in the message body), T7 (`test_neither_extra_imports.py`) |

**No gaps found.**

### 2. Placeholder scan

Searched plan for the forbidden patterns from the skill's "No Placeholders" list:

- `TBD` / `TODO` / `implement later` / `fill in details`: **none in step bodies** (only in commit-message templates where they're literal text the developer types). ✅
- "Add appropriate error handling" / "add validation" / "handle edge cases" without code: **none**. ✅
- "Write tests for the above" without code: **none** — every test step contains complete test code. ✅
- "Similar to Task N" / cross-referencing without re-stating: **partial finding** — T2's degradation test pattern is *referenced* in T4 as "mirrors #82's lazy-import discipline." Mitigation: T4's test file shows the full pattern inline; the cross-reference is provenance, not avoidance.
- Steps describing what to do without showing how: **none** — every code-step has a literal code block. ✅
- References to types / functions / methods not defined in any task: **none** — every `TechtradeDependencyError`, `lookup_tuned_for_symbol`, `tune_override`, `validate_plan`, `KNOB_TABLE`, etc. is either defined in an earlier Task or imported from an existing module (verified during the relevant Task's Step 1 read).

### 3. Type consistency

Cross-checked signature names across Tasks for drift:

| Symbol | First defined in | Used in |
|---|---|---|
| `IndicatorConfig` | existing (`engine/indicators.py`) | T1, T2, T4, T5, T6 — all use the same field set |
| `TuningReport` | T1 | T5 (router constructor uses the exact 10 fields T1 declares) |
| `TechtradeDependencyError` | existing (#82, `validation/backtest_bridge.py`) | T4 imports + T7 references — never re-declares |
| `lookup_tuned_for_symbol(symbol) -> IndicatorConfig | None` | T2 | T5 (read by `test_override_visible_in_validate_fold`), T6 (called from `build_indicator_panel`) — all callers match |
| `tune_override(overrides: dict[str, IndicatorConfig])` | T2 | T5 (`with tune_override({segment: candidate}):`) — exact shape match |
| `write_tuned(segment, config, meta)` | T2 | T5 (`write_tuned(segment, candidate, meta={...})`) — exact signature match |
| `pool_sector_ohlcv(segment, *, as_of, horizon_years, forward_horizon_bars, fetcher)` | T3 | T5 calls with positional `segment` + kwargs — match |
| `fit_segment(X, y, *, trials, early_stop)` | T4 | T5 calls with positional `(X, y)` + kwargs — match |
| `KNOB_TABLE` | T4 | only referenced in T4 tests; not a cross-task type — N/A |
| `SEGMENT_BENCHMARK_ETFS` | T5 | T5 tests reference; T7 integration also references — match |

**One real consistency issue caught and fixed during self-review:** T1's `TuningReport.candidate` field is typed as `IndicatorConfig` — but `IndicatorConfig` is a frozen `@dataclass`, not a Pydantic `Data` subclass. Pydantic 2 handles arbitrary types via `model_config = {"arbitrary_types_allowed": True}` *or* via `model_rebuild()` with the imported type in scope. T1 Step 4 specifies the import + the `model_rebuild()` call. The implementer should verify the rebuild succeeds — if Pydantic complains, the fallback is to add `model_config = ConfigDict(arbitrary_types_allowed=True)` to `TuningReport`. **Recorded as a known integration risk for T1 Step 5** (the moment the test runs).

### 4. Other notes for the implementer

- **The bd OpenBBTechnical-46y test-collection collision** is a pre-existing block on whole-tree pytest. The plan uses per-file pytest invocations throughout. If `46y` resolves before T7 runs, switch T7 Step 6 to a single whole-tree run.
- **The Step 1 verifications in T2 and T3** (segment-resolver path, universe-resolver path) are explicit "this is an unverified assumption" checkpoints. Both ship with in-file fallback dicts so the Task can land even if the real helper doesn't yet exist; if a fallback is used, the Task commit message should call that out.
- **All 7 tasks ship with offline-only unit suites.** Only T7's integration test hits the network — and only when `tuneta` + `openbb-backtest` + `fmp_cached` are all configured.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-21-83-tuneta-adapter-tune-gated-validation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per Task (T1 → T2 → T3 → T4 → T5 → T6 → T7), review the diff between each, and only proceed to the next Task once the previous one passes review + tests + commit. Fast iteration; each subagent starts with a clean context window so it has full headroom for the file reads + edits its Task needs.

**2. Inline Execution** — I execute Tasks in this session using `superpowers:executing-plans`, batching with checkpoints. Slower overall (this session's context is heavy already), but no subagent context-handoff overhead.

**Which approach?**
