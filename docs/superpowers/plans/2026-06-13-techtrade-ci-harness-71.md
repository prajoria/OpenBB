# techtrade #71 — CI Harness (golden-file tests + lint/type + submodule-pin check) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the reusable test/CI harness the rest of the techtrade build relies on: a byte/value-stable golden-file comparison helper + a first golden lock, a submodule-pin drift check, and deterministic test config — all riding the EXISTING platform CI (no redundant workflow YAML).

**Architecture:** Mirror the merged `openbb-backtest` precedent. A small typed `openbb_techtrade/testing.py` provides the reusable golden helper (regen via `TECHTRADE_REGEN_GOLDEN=1`, `_TOL` tolerance, JSON-stable serialization of Decimal/date). A `conftest.py` at the extension root registers the `golden` marker and guarantees source-tree importability (exact mirror of `backtest/conftest.py`). Golden tests live under `tests/golden/`; the pin-drift check lives under `tests/unit/`. Lint (ruff 122) + type (mypy) gates already run via `.github/workflows/general-linting.yml`; the unit suite (incl. pin check + golden) already runs via `test-unit-platform.yml` → `noxfile.py`. So CI fails on lint/type regressions AND submodule-pin drift through existing infra — no new workflow file is added (deliberate, matches backtest).

**Tech Stack:** pytest, pydantic v2 `Data` models, stdlib `json`/`os`/`pathlib`/`decimal`/`datetime`/`subprocess`. Reuses `openbb_techtrade.engine.movers.rank_movers` for the golden lock.

---

## Design decisions (rationale for reviewers)

1. **No new CI workflow YAML.** `general-linting.yml` already runs `ruff check` + `mypy` on changed `openbb_platform/**/*.py` (excluding `package/`, `integration`, `tests`); `test-unit-platform.yml` already runs `pytest .../extensions -m "not integration"`. The pin-drift check and golden tests are plain pytest tests, so they ride the existing unit-test workflow and fail CI on drift. `openbb-backtest` (the merged precedent) added **zero** workflow YAML for its identical golden harness. Adding a techtrade-specific workflow would duplicate infra and diverge from precedent. The acceptance criteria ("Lint + type gates run in CI", "Submodule-pin drift fails CI") are met by existing + new-pytest infra.

2. **Reusable helper lives in the package (`openbb_techtrade/testing.py`), not under `tests/`.** #72–#82 all need golden locks; a package module gives them an unambiguous import (`from openbb_techtrade.testing import assert_matches_golden`) that works under any pytest import mode (cross-`tests/` imports are fragile). Convention precedent: `pandas.testing`, `numpy.testing`. It is dependency-light and fully typed so it passes the existing CI ruff+mypy gates. Each test owns its own `fixtures/` dir (passed in), keeping the helper pure.

3. **`conftest.py` is ruff+mypy gated** (path contains neither `tests` nor `integration`), so it is written clean, mirroring `backtest/conftest.py` exactly.

4. **Pin-drift check is layered + degrades gracefully.** `EXPECTED_PIN` is the recorded constant (`cfda9903…`). The test asserts (a) README documents it (pure file read, always runs); (b) the superproject gitlink from `git ls-tree HEAD` equals it (CI-safe — needs no submodule fetch); (c) if the submodule working tree is populated, its live HEAD equals it. (b)/(c) skip cleanly when git is unavailable (e.g. installed sdist). Bumping the submodule requires updating `EXPECTED_PIN` + README in the same reviewed PR — that IS the §19 pin discipline.

---

## File Structure

- Create: `openbb_platform/extensions/techtrade/conftest.py` — sys.path safety + register `golden` marker.
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/testing.py` — reusable golden helper (`to_jsonable`, `assert_matches_golden`, `DEFAULT_TOL`, `REGEN_ENV`).
- Create: `openbb_platform/extensions/techtrade/tests/golden/__init__.py`
- Create: `openbb_platform/extensions/techtrade/tests/golden/fixtures/movers_pct_change.json` — committed golden.
- Create: `openbb_platform/extensions/techtrade/tests/golden/test_movers_golden.py` — locks `rank_movers` output + determinism.
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_testing_helpers.py` — unit tests for the golden helper itself.
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_submodule_pin.py` — pin-drift check.
- Modify: `openbb_platform/extensions/techtrade/README.md` — add a short "Testing & determinism" subsection.

**Out of scope (do NOT touch):** any `.github/workflows/*` (existing gates suffice), `reference.json`, `package/__init__.py`, `agents/tests/test_config.py` (persistent noise — must stay unstaged).

---

## Task 1: Reusable golden helper (`openbb_techtrade/testing.py`)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/testing.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_testing_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the techtrade golden-file test harness (issue #71, PRD §17).

Fully offline. Exercises ``to_jsonable`` type coercion (Decimal -> str, date /
datetime -> isoformat, nested pydantic ``Data`` -> dict) and ``assert_matches_golden``
match / mismatch / float-tolerance / regen-write behavior using a tmp fixture dir.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from openbb_techtrade.models import Mover
from openbb_techtrade.testing import (
    REGEN_ENV,
    assert_matches_golden,
    to_jsonable,
)


def test_to_jsonable_coerces_decimal_to_string():
    assert to_jsonable(Decimal("300")) == "300"
    assert to_jsonable({"volume": Decimal("12.5")}) == {"volume": "12.5"}


def test_to_jsonable_coerces_dates_to_isoformat():
    assert to_jsonable(date(2024, 1, 12)) == "2024-01-12"
    assert to_jsonable(datetime(2024, 1, 12, 9, 30)) == "2024-01-12T09:30:00"


def test_to_jsonable_handles_nested_pydantic_and_lists():
    mover = Mover(symbol="AAA", pct_change=0.05, volume=Decimal("200"), rank=1)
    out = to_jsonable([mover])
    assert out == [{"symbol": "AAA", "pct_change": 0.05, "volume": "200", "rank": 1}]


def test_assert_matches_golden_passes_on_exact_match(tmp_path: Path):
    payload = {"a": 1, "nested": {"b": "x"}}
    (tmp_path / "fx.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    # Does not raise.
    assert_matches_golden("fx", payload, fixture_dir=tmp_path)


def test_assert_matches_golden_allows_float_within_tolerance(tmp_path: Path):
    (tmp_path / "fx.json").write_text(json.dumps({"x": 1.0}) + "\n", encoding="utf-8")
    assert_matches_golden("fx", {"x": 1.0 + 1e-12}, fixture_dir=tmp_path, tol=1e-9)


def test_assert_matches_golden_raises_on_value_mismatch(tmp_path: Path):
    (tmp_path / "fx.json").write_text(json.dumps({"x": 1.0}) + "\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_matches_golden("fx", {"x": 2.0}, fixture_dir=tmp_path)


def test_assert_matches_golden_raises_on_structural_mismatch(tmp_path: Path):
    (tmp_path / "fx.json").write_text(json.dumps({"x": 1}) + "\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_matches_golden("fx", {"x": 1, "y": 2}, fixture_dir=tmp_path)


def test_assert_matches_golden_regen_writes_fixture(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(REGEN_ENV, "1")
    payload = {"symbol": "AAA", "volume": "200"}
    assert_matches_golden("fresh", payload, fixture_dir=tmp_path)
    written = json.loads((tmp_path / "fresh.json").read_text(encoding="utf-8"))
    assert written == payload


def test_assert_matches_golden_missing_fixture_without_regen_raises(tmp_path: Path):
    with pytest.raises((FileNotFoundError, AssertionError)):
        assert_matches_golden("nope", {"x": 1}, fixture_dir=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_testing_helpers.py -q`
Expected: FAIL with `ModuleNotFoundError: openbb_techtrade.testing`.

- [ ] **Step 3: Write `openbb_techtrade/testing.py`**

Requirements (write fully typed + ruff-clean — this module IS CI-gated):
- Module docstring referencing issue #71 / PRD §17.
- `REGEN_ENV = "TECHTRADE_REGEN_GOLDEN"`; `DEFAULT_TOL = 1e-9`.
- `to_jsonable(obj)` recursively converts: pydantic `BaseModel`/`Data` → `model_dump()` then recurse; `Decimal` → `str`; `datetime` → `.isoformat()`; `date` → `.isoformat()`; `dict` → recurse values (keys kept as-is); `list`/`tuple` → list of recursed; `float`/`int`/`str`/`bool`/`None` → as-is; fallback `str(obj)`. (Check `datetime` before `date` — `datetime` is a `date` subclass.)
- `assert_matches_golden(name, payload, *, fixture_dir, tol=DEFAULT_TOL)`:
  - `payload = to_jsonable(payload)`.
  - `path = Path(fixture_dir) / f"{name}.json"`.
  - If `os.environ.get(REGEN_ENV) == "1"`: `mkdir(parents=True, exist_ok=True)`, write `json.dumps(payload, indent=2, sort_keys=True) + "\n"`, return.
  - Read golden = `json.loads(path.read_text())` (let `FileNotFoundError` propagate when absent and not regenerating).
  - Recursively compare golden vs payload via a private `_assert_equal(golden, actual, tol, path_str)`: dict → assert same keys, recurse; list → assert same len, recurse by index; `float` (either side) → `pytest.approx(golden, abs=tol)`; else `==`. Raise `AssertionError` with the JSON path on mismatch.

Use `from openbb_core.provider.abstract.data import Data` and/or `pydantic.BaseModel` for the isinstance check (prefer `BaseModel` to catch all models).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_testing_helpers.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Ruff the new package module**

Run: `.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/techtrade/openbb_techtrade/testing.py`
Expected: `All checks passed!`

---

## Task 2: `conftest.py` + `golden` marker + golden lock of `rank_movers`

**Files:**
- Create: `openbb_platform/extensions/techtrade/conftest.py`
- Create: `openbb_platform/extensions/techtrade/tests/golden/__init__.py`
- Create: `openbb_platform/extensions/techtrade/tests/golden/test_movers_golden.py`
- Create (via regen): `openbb_platform/extensions/techtrade/tests/golden/fixtures/movers_pct_change.json`

- [ ] **Step 1: Write `conftest.py`** (mirror backtest exactly)

```python
"""Pytest config: make ``openbb_techtrade`` importable + register markers (#71).

Until the extension is installed editable, add the package root to ``sys.path`` so
unit tests run against the source tree. Also registers the ``golden`` marker used
by the golden-file regression locks (PRD §17).
"""

import os
import sys

_PKG_ROOT = os.path.dirname(__file__)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)


def pytest_configure(config):
    """Register techtrade-local pytest markers."""
    config.addinivalue_line(
        "markers",
        "golden: regression-locks an output against a committed golden fixture.",
    )
```

- [ ] **Step 2: Write the golden test (`tests/golden/test_movers_golden.py`)**

```python
"""Golden-fixture regression lock for the top-mover ranking engine (#71, #70).

Runs the pure, deterministic ``rank_movers`` over a fixed candidate set and locks
the resulting ``MoverList`` against a committed golden JSON within ``DEFAULT_TOL``.
Carries the ``golden`` marker. Regenerate intentionally after a *reviewed* change
with ``TECHTRADE_REGEN_GOLDEN=1`` — never blindly. This both proves the harness
end to end and guards #70's ranking output.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openbb_techtrade.engine.movers import rank_movers
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)
_CANDIDATES = [
    {"symbol": "AAA", "pct_change": 0.012, "volume": 1_000},
    {"symbol": "BBB", "pct_change": 0.051, "volume": 2_500},
    {"symbol": "CCC", "pct_change": 0.034, "volume": 1_750},
    {"symbol": "DDD", "pct_change": -0.020, "volume": 3_200},
    {"symbol": "EEE", "pct_change": 0.051, "volume": 900},
]


def _snapshot():
    ml = rank_movers("Information Technology", _AS_OF, _CANDIDATES, metric="pct_change")
    return ml.model_dump()


def test_rank_movers_matches_golden():
    assert_matches_golden("movers_pct_change", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_rank_movers_is_deterministic():
    assert _snapshot() == _snapshot()
```

- [ ] **Step 3: Run to confirm it fails (missing fixture)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/golden/test_movers_golden.py -q`
Expected: FAIL — `FileNotFoundError`/`AssertionError` on the missing `movers_pct_change.json`.

- [ ] **Step 4: Generate the golden fixture (reviewed inputs)**

Run (PowerShell-safe single command):
`set TECHTRADE_REGEN_GOLDEN=1 && .venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/golden/test_movers_golden.py::test_rank_movers_matches_golden -q`
(or set env inline via `TECHTRADE_REGEN_GOLDEN=1 ...` in bash).
Then **read** `tests/golden/fixtures/movers_pct_change.json` and hand-verify: order is `BBB, EEE, CCC, AAA, DDD` (descending pct_change; BBB & EEE tie at 0.051 → ascending symbol tiebreak BBB before EEE), `rank` 1..5, `volume` as integer-string Decimals, `as_of` = `"2024-01-12"`, `segment` = `"Information Technology"`.

- [ ] **Step 5: Run again to confirm the lock passes**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/golden/ -q`
Expected: PASS (2 tests). Confirm the `golden` marker raises no unknown-marker warning.

---

## Task 3: Submodule-pin drift check

**Files:**
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_submodule_pin.py`

- [ ] **Step 1: Write the test**

```python
"""Submodule-pin drift guard for the vendored pandas-ta-classic fork (#71, PRD §19).

Fails CI if the ``external/pandas-ta-classic`` pin drifts from the reviewed,
recorded commit. The recorded pin is asserted against (a) the techtrade README,
(b) the superproject gitlink (``git ls-tree HEAD`` — needs no submodule fetch),
and (c) the live submodule HEAD when its working tree is populated. Git-based
checks skip cleanly when git / the work tree is unavailable (e.g. installed sdist),
so the suite stays runnable everywhere while still failing CI on real drift.

Bumping the submodule must update ``EXPECTED_PIN`` here and the README in the same
reviewed PR — that is the §19 pin discipline, enforced by this test.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

EXPECTED_PIN = "cfda99036ba64a4983e5871d42d1865743b7c6a9"
_SUBMODULE_REL = "openbb_platform/extensions/techtrade/external/pandas-ta-classic"
_EXT_ROOT = Path(__file__).resolve().parents[2]  # .../extensions/techtrade
_README = _EXT_ROOT / "README.md"


def _repo_root() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=_EXT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out.stdout.strip())


def test_readme_documents_expected_pin():
    text = _README.read_text(encoding="utf-8")
    shas = set(re.findall(r"\b[0-9a-f]{40}\b", text))
    assert EXPECTED_PIN in shas, f"README must document submodule pin {EXPECTED_PIN}"


def test_superproject_gitlink_matches_expected_pin():
    root = _repo_root()
    if root is None:
        pytest.skip("git unavailable / not a work tree")
    out = subprocess.run(
        ["git", "ls-tree", "HEAD", _SUBMODULE_REL],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    line = out.stdout.strip()
    if not line:
        pytest.skip("submodule gitlink not present in this tree")
    # Format: "160000 commit <sha>\t<path>"
    recorded = line.split()[2]
    assert recorded == EXPECTED_PIN


def test_live_submodule_head_matches_expected_pin():
    sub = _EXT_ROOT / "external" / "pandas-ta-classic"
    if not (sub / ".git").exists():
        pytest.skip("submodule working tree not populated")
    out = subprocess.run(
        ["git", "-C", str(sub), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == EXPECTED_PIN
```

- [ ] **Step 2: Run the test**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_submodule_pin.py -q`
Expected: PASS (3 tests; none skipped in this dev checkout — git present, submodule populated).

- [ ] **Step 3: Negative-control sanity (manual, do NOT commit)**

Temporarily change `EXPECTED_PIN` to `"0"*40`, run the test, confirm all three FAIL (proves drift is actually detected), then revert to `cfda9903…`.

---

## Task 4: README "Testing & determinism" subsection

**Files:**
- Modify: `openbb_platform/extensions/techtrade/README.md`

- [ ] **Step 1: Add a concise subsection** after the existing vendored-submodule section, documenting:
  - Run unit + golden locally: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -m "not integration" -q`.
  - Golden files live under `tests/golden/fixtures/`; regenerate intentionally after a reviewed change with `TECHTRADE_REGEN_GOLDEN=1`.
  - Lint/type gates (ruff 122 + mypy) run in CI via `general-linting.yml`; the unit suite (incl. the submodule-pin drift guard) runs via `test-unit-platform.yml`.
  - Bumping the submodule requires updating the pin in `tests/unit/test_submodule_pin.py` + README together (reviewed PR).

- [ ] **Step 2: Markdown sanity** — keep line lengths reasonable; no emoji; no code fences left unclosed.

---

## Final verification (controller runs before commit)

- [ ] `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -m "not integration" -q` → all green (57 prior + new golden/helper/pin tests).
- [ ] `.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/techtrade/openbb_techtrade openbb_platform/extensions/techtrade/conftest.py` → `All checks passed!`
- [ ] `git status --short` shows ONLY #71 files staged; the three noise files remain unstaged.
- [ ] Single commit: `feat(techtrade): add CI test harness — golden helper + submodule-pin guard (#71)`.
```
