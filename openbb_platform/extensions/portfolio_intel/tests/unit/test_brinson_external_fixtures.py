"""Tests for external (textbook + Bloomberg-placeholder) Brinson fixtures (#557).

Complements the synthetic golden fixtures (#935) with reference cases
sourced from cited academic papers. The attribution engine (#559)
must match these to +/-1bp same as the synthetic set.

Fixtures live at ``analytics/brinson/fixtures_external/*.json`` with a
``reference`` block declaring source + citation. Placeholders (empty
``inputs.group``) are skipped — they exist so the loader treats
Bloomberg fixtures as a first-class category once QA drops in data.

Discriminators:

- **Every non-placeholder external fixture runs through the engine
  and must match its stored expected effects to +/-1bp.** Any
  divergence means either the engine drifted or the fixture drifted;
  either way the CI catches it before shipping.
- **Placeholder recognition** — the Bloomberg PLACEHOLDER fixture is
  correctly identified as unfilled and skipped, so its lack of data
  does NOT fail the suite.
- **Loader schema** — every fixture carries the required
  ``reference.source`` + ``reference.citation`` fields; missing
  provenance is a documentation gap even if the numbers work.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openbb_portfolio_intel.analytics.attribution_engine import (
    build_from_dataframe,
)

ONE_BP = 1e-4


def _external_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "openbb_portfolio_intel"
        / "analytics"
        / "brinson"
        / "fixtures_external"
    )


def _all_external() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(_external_dir().glob("*.json"))]


def _real_external() -> list[dict]:
    """External fixtures with populated inputs (placeholders skipped)."""
    return [fx for fx in _all_external() if fx["inputs"].get("group")]


def test_external_fixture_directory_is_non_empty() -> None:
    """Guardrail: any accidental delete of every external fixture is loud."""
    assert len(_all_external()) >= 3, (
        "expected at least 3 external fixtures (2 textbook + 1 Bloomberg "
        "placeholder); found "
        f"{len(_all_external())}"
    )


def test_every_external_fixture_has_reference_provenance() -> None:
    """Missing citation is a QA policy violation, even if numbers work."""
    for fx in _all_external():
        assert "reference" in fx, f"{fx.get('case_id')}: missing 'reference' block"
        assert fx["reference"].get("source"), f"{fx['case_id']}: reference.source empty"
        assert fx["reference"].get(
            "citation"
        ), f"{fx['case_id']}: reference.citation empty"


def test_bloomberg_placeholder_is_recognized_and_skipped() -> None:
    """The PLACEHOLDER must be skipped by the fixture-loader helper."""
    all_ids = {fx["case_id"] for fx in _all_external()}
    real_ids = {fx["case_id"] for fx in _real_external()}
    placeholders = all_ids - real_ids
    assert placeholders, (
        "expected at least one placeholder fixture in fixtures_external/; "
        "if you dropped it, the QA-hand-off point is gone"
    )
    for pid in placeholders:
        assert "PLACEHOLDER" in pid, (
            f"skipped fixture {pid!r} doesn't declare itself as PLACEHOLDER; "
            "confusing"
        )


@pytest.mark.parametrize("fx", _real_external(), ids=lambda fx: fx["case_id"])
def test_engine_matches_external_fixture_within_1bp(fx: dict) -> None:
    """Engine output matches every external reference fixture to +/-1bp."""
    df = pd.DataFrame(fx["inputs"])
    waterfall = build_from_dataframe(df, window="1Y", benchmark_symbol="EXT")
    exp = fx["expected"]
    tol = exp["tolerance_bps"] * ONE_BP
    for name, engine_val, expected_val in (
        (
            "active_return",
            waterfall.portfolio_return - waterfall.benchmark_return,
            exp["active_return"],
        ),
        ("allocation", waterfall.total_allocation, exp["allocation"]),
        ("selection", waterfall.total_selection, exp["selection"]),
        ("interaction", waterfall.total_interaction, exp["interaction"]),
    ):
        assert np.isclose(
            engine_val, expected_val, atol=tol
        ), f"{fx['case_id']}:{name}: engine={engine_val} vs expected={expected_val}"
