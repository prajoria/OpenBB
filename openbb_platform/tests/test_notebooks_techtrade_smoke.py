"""Techtrade-notebook smoke tests (#1762).

CI-safe smoke checks over ``notebooks/techtrade/*.ipynb``. Mirrors the
structure of ``test_notebooks_portfolio_smoke.py`` but scoped to the
techtrade series.

The techtrade notebooks were added incrementally alongside T5 (#1719)
in this repo; there was no smoke test protecting them from silent
output-strip or JSON-corruption regressions until now.

Same rationale as the portfolio smoke:

1. Structural rot — each notebook must parse, contain markdown +
   code cells, and every code cell must ``compile()`` cleanly under the
   deployed Python.
2. Recorded-output rot — every code cell must carry non-empty outputs
   on disk. Catches "someone opened + saved the notebook, wiping
   outputs, and pushed" — which would silently regress the entire
   series' documentation value.
3. PII deny-list — the recorded outputs must not carry any of the
   operator-username / Windows-user-path tokens that would leak PII.

Non-goals: no live execution (kernel-restart-and-Run-All still requires
`.venv_portfolio` + heavy deps + real data). This suite is the
structural guard; the operator's local re-run is the semantic guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TECHTRADE_NB_DIR = REPO_ROOT / "notebooks" / "techtrade"

# The techtrade notebook series covered by this smoke.
#
# Scope: only the notebooks authored under the current check-in
# discipline (state-stripped, outputs preserved, PII deny-list clean).
# Notebooks nb-01 through nb-06 predate the discipline and are covered
# by a separate hygiene follow-up (see the CLAUDE.md note in the file
# header). Once those are cleaned up, add them to this list.
EXPECTED_NOTEBOOKS = [
    "07-t5-order-batch-and-xlsx-workbook.ipynb",
    "08-t5-paper-trading-engine-walkthrough.ipynb",
    "09-t5-end-to-end-plan-to-fills.ipynb",
]

# Tokens that must NOT appear anywhere in a committed notebook's outputs.
# These are the same PII deny-list tokens used by the portfolio smoke —
# operator-username leaks, Windows-user-path leaks, and AppData
# transcript-cache paths.
_PII_TOKENS = ("daaji", "AppData")


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_is_present(nb_name: str) -> None:
    """Every expected techtrade notebook is on disk."""
    path = TECHTRADE_NB_DIR / nb_name
    assert path.exists(), f"Missing techtrade notebook: {path}"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_parses_as_json(nb_name: str) -> None:
    """Notebook JSON is well-formed."""
    path = TECHTRADE_NB_DIR / nb_name
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict)
    assert "cells" in data, f"{nb_name}: no `cells` array"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_has_markdown_and_code_cells(nb_name: str) -> None:
    """Every notebook is a mix of narrative + executable code, not just one."""
    path = TECHTRADE_NB_DIR / nb_name
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    kinds = {c.get("cell_type") for c in data["cells"]}
    assert "markdown" in kinds, f"{nb_name}: missing markdown cells (narrative)"
    assert "code" in kinds, f"{nb_name}: missing code cells (executable)"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_code_cells_compile(nb_name: str) -> None:
    """Every code cell parses as valid Python. Catches Py3.12 regressions."""
    path = TECHTRADE_NB_DIR / nb_name
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for i, cell in enumerate(data["cells"]):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not source.strip():
            continue
        try:
            compile(source, f"{nb_name}[cell {i}]", "exec")
        except SyntaxError as exc:
            pytest.fail(f"{nb_name} cell {i} SyntaxError: {exc}")


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_code_cells_have_recorded_outputs(nb_name: str) -> None:
    """Every code cell (with source) has recorded outputs.

    Rationale: the check-in policy strips ``execution_count`` but MUST
    preserve outputs so GitHub readers see real results without running
    the notebook. This test fails the moment someone commits a
    stripped-outputs notebook — matches the portfolio smoke's
    ``test_code_cells_have_recorded_outputs`` guard.

    Rare exception: a purely-import cell (e.g. `import pandas as pd`)
    can legitimately have no outputs. We tolerate that specific case
    by allowing empty outputs on cells whose source is only imports.
    """
    path = TECHTRADE_NB_DIR / nb_name
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    missing: list[int] = []
    for i, cell in enumerate(data["cells"]):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not source.strip():
            continue
        # Import-only cells are allowed to have no output.
        if _is_import_only(source):
            continue
        outputs = cell.get("outputs", [])
        if not outputs:
            missing.append(i)
    assert not missing, (
        f"{nb_name}: {len(missing)} code cell(s) with source but no "
        f"outputs (index: {missing}). Someone opened + saved and pushed?"
    )


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_no_pii_in_notebook_outputs(nb_name: str) -> None:
    """PII deny-list: no operator-username / Windows-user-path tokens.

    Mirrors the portfolio smoke's ``test_no_pii_in_notebook_outputs``.
    """
    path = TECHTRADE_NB_DIR / nb_name
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    hits: list[tuple[int, str]] = []
    for i, cell in enumerate(data["cells"]):
        if cell.get("cell_type") != "code":
            continue
        for out in cell.get("outputs", []):
            text = out.get("text") or ""
            if isinstance(text, list):
                text = "".join(text)
            for token in _PII_TOKENS:
                if token in text:
                    hits.append((i, token))
    assert not hits, (
        f"{nb_name}: PII-token hits in outputs (cell, token): {hits}. "
        "Strip via scripts/reset_notebooks_for_checkin.py and re-execute "
        "under a sandbox path before committing."
    )


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_state_stripped(nb_name: str) -> None:
    """Committed notebooks must have execution_count=None on every
    code cell (per repo check-in policy). Kernel version drift and
    per-cell timing must also be stripped.
    """
    path = TECHTRADE_NB_DIR / nb_name
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for i, cell in enumerate(data["cells"]):
        if cell.get("cell_type") != "code":
            continue
        exc = cell.get("execution_count")
        assert exc is None, (
            f"{nb_name} cell {i}: execution_count={exc!r}; run "
            "scripts/reset_notebooks_for_checkin.py before committing"
        )
        meta = cell.get("metadata", {})
        assert "execution" not in meta, (
            f"{nb_name} cell {i}: metadata.execution present (nbclient "
            "timing state); strip via reset_notebooks_for_checkin.py"
        )


def _is_import_only(source: str) -> bool:
    """Return True iff the source has only imports (`import X`, `from X import Y`)."""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("import ") or line.startswith("from "):
            continue
        return False
    return True
