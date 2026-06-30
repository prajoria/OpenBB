"""Unit tests for ``Tools/pine/measure_wild_corpus_coverage.py`` (PRD §3.4 + §8.1).

The measurement tool's contract is "given an index of N scripts and a
manifest of implemented identifiers, how many run unedited?" -- this
test pins that contract with a 3-script inline fixture.

Also covers:

* missing index -> ``status == "skipped"``, exit 0 (no CI failure when
  L0.4's index hasn't landed yet);
* blocker tally ordering (descending by ``blocks_count``);
* manifest mutation visibility (the tool must see fresh frozensets each
  call so a Phase 1 PR that adds ``ta.sma`` immediately bumps coverage).
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add Tools/pine to sys.path so we can import the module-under-test by
# name. The script is intentionally not a package -- it lives in
# Tools/pine/ alongside the other ad-hoc Pine helpers (capital T matches
# the existing tracked path; see L0.3 bead notes for rationale).
REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_PINE = REPO_ROOT / "Tools" / "pine"
if str(TOOLS_PINE) not in sys.path:
    sys.path.insert(0, str(TOOLS_PINE))

import measure_wild_corpus_coverage as mwc  # noqa: E402  (sys.path bridge above)

# --- Fixtures -----------------------------------------------------------


@pytest.fixture()
def three_script_index() -> dict[str, Any]:
    """Return a 3-script wild-corpus index in the L0.4 fingerprint shape.

    Script A uses only ta.sma + ta.ema (covered by the "small" manifest).
    Script B uses ta.sma + request.security (the feature blocks it under
    the small manifest).
    Script C uses an exotic builtin (math.foo) + targets Pine v5.
    """
    return {
        "schema_version": 1,
        "scripts": [
            {
                "url": "https://tradingview.com/scripts/a",
                "pine_version": 6,
                "builtins_used": ["ta.sma", "ta.ema"],
                "features_used": ["indicator"],
                "source_visible": True,
            },
            {
                "url": "https://tradingview.com/scripts/b",
                "pine_version": 6,
                "builtins_used": ["ta.sma"],
                "features_used": ["indicator", "request.security"],
                "source_visible": True,
            },
            {
                "url": "https://tradingview.com/scripts/c",
                "pine_version": 5,
                "builtins_used": ["math.foo"],
                "features_used": ["indicator"],
                "source_visible": True,
            },
        ],
    }


@pytest.fixture()
def empty_manifest() -> dict[str, Any]:
    """Phase-0 manifest -- every set empty."""
    return {
        "manifest_status": "loaded",
        "pine_versions": [],
        "builtins": frozenset(),
        "features": [],
        "builtins_count": 0,
    }


@pytest.fixture()
def small_manifest() -> dict[str, Any]:
    """Return a toy P1 manifest that covers ONE of the 3 fixture scripts (Script A)."""
    return {
        "manifest_status": "loaded",
        "pine_versions": [6],
        "builtins": frozenset({"ta.sma", "ta.ema"}),
        "features": ["indicator"],
        "builtins_count": 2,
    }


@pytest.fixture()
def full_manifest() -> dict[str, Any]:
    """Return a manifest big enough to make every fixture script run unedited."""
    return {
        "manifest_status": "loaded",
        "pine_versions": [5, 6],
        "builtins": frozenset({"ta.sma", "ta.ema", "math.foo"}),
        "features": ["indicator", "request.security"],
        "builtins_count": 3,
    }


# --- Coverage math ------------------------------------------------------


def test_returns_valid_json_payload(three_script_index, empty_manifest):
    """Payload round-trips through json with all documented sections present."""
    payload = mwc.compute_coverage(three_script_index, empty_manifest)
    # Round-trip through json so we catch any non-serializable field.
    rt = json.loads(json.dumps(payload))
    assert rt["schema_version"] == mwc.SCHEMA_VERSION
    assert rt["status"] == "ok"
    assert {"corpus", "coverage", "blockers", "implemented_baseline"} <= set(rt)


def test_coverage_100_when_all_scripts_supported(three_script_index, full_manifest):
    """Every script runs unedited -> coverage_pct == 100.0, blockers empty."""
    payload = mwc.compute_coverage(three_script_index, full_manifest)
    assert payload["coverage"]["coverage_pct"] == 100.0
    assert payload["coverage"]["would_run_unedited"] == 3
    assert payload["coverage"]["would_not_run"] == 0
    assert payload["blockers"] == []


def test_coverage_0_when_implemented_set_is_empty(three_script_index, empty_manifest):
    """Phase-0 baseline -- every script blocked, coverage_pct == 0.0."""
    payload = mwc.compute_coverage(three_script_index, empty_manifest)
    assert payload["coverage"]["coverage_pct"] == 0.0
    assert payload["coverage"]["would_run_unedited"] == 0
    assert payload["coverage"]["would_not_run"] == 3


def test_coverage_33_33_when_one_of_three_supported(three_script_index, small_manifest):
    """1-of-3 supported -> coverage rounds to 33.33% (2dp)."""
    payload = mwc.compute_coverage(three_script_index, small_manifest)
    # 1 of 3 runs unedited; rounded to 2dp by the tool.
    assert payload["coverage"]["coverage_pct"] == 33.33
    assert payload["coverage"]["would_run_unedited"] == 1
    assert payload["coverage"]["would_not_run"] == 2


def test_blocker_list_ordered_descending_by_count(three_script_index, empty_manifest):
    """Every script blocked; ta.sma appears in 2 scripts, others in 1."""
    payload = mwc.compute_coverage(three_script_index, empty_manifest)
    blockers = payload["blockers"]
    # ta.sma appears in scripts A and B -> blocks 2; nothing else hits 2.
    top = next(b for b in blockers if b["identifier"] == "ta.sma")
    assert top["blocks_count"] == 2
    assert top["kind"] == "builtin"
    counts = [b["blocks_count"] for b in blockers]
    assert counts == sorted(counts, reverse=True)


def test_blocker_kinds_distinguished(three_script_index, empty_manifest):
    """Blockers tagged kind='builtin' | 'feature' | 'pine_version'."""
    payload = mwc.compute_coverage(three_script_index, empty_manifest)
    kinds = {b["kind"] for b in payload["blockers"]}
    assert "builtin" in kinds
    assert "feature" in kinds  # request.security from script B
    assert "pine_version" in kinds  # script C declares v5


def test_unknown_bucket_for_source_not_visible_scripts(empty_manifest):
    """source_visible=false scripts go in `unknown`, excluded from coverage_pct."""
    index = {
        "schema_version": 1,
        "scripts": [
            {
                "url": "https://tradingview.com/scripts/visible",
                "pine_version": 6,
                "builtins_used": [],
                "features_used": [],
                "source_visible": True,
            },
            {
                "url": "https://tradingview.com/scripts/closed",
                "pine_version": None,
                "builtins_used": [],
                "features_used": [],
                "source_visible": False,
            },
        ],
    }
    payload = mwc.compute_coverage(index, empty_manifest)
    assert payload["corpus"]["source_visible"] == 1
    assert payload["corpus"]["source_not_visible"] == 1
    assert payload["coverage"]["unknown_pct"] == 50.0
    # The visible script's pine_version is not in the empty manifest, so 0/1.
    assert payload["coverage"]["coverage_pct"] == 0.0


# --- Missing-index path -------------------------------------------------


def test_missing_index_emits_skipped_status_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """A missing tests/wild_corpus/index.json must NOT fail CI."""
    nonexistent = tmp_path / "absent.json"
    assert not nonexistent.exists()
    rc = mwc.main(["--index-path", str(nonexistent)])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "skipped"
    assert payload["coverage_pct"] is None
    assert "wild_corpus/index.json absent" in payload["reason"]


def test_missing_index_writes_skipped_pr_comment(tmp_path: Path):
    """`--pr-comment-out` is honored even on the skipped path."""
    nonexistent = tmp_path / "absent.json"
    comment_path = tmp_path / "pr-comment.md"
    rc = mwc.main(
        [
            "--index-path",
            str(nonexistent),
            "--pr-comment-out",
            str(comment_path),
        ]
    )
    assert rc == 0
    assert comment_path.exists()
    body = comment_path.read_text(encoding="utf-8")
    assert "Wild-corpus coverage" in body
    assert "skipped" in body.lower()


# --- Manifest loader sees fresh values ----------------------------------


def test_manifest_loader_returns_empty_when_module_missing(monkeypatch):
    """If openbb_pine._coverage_manifest is not importable, all sets empty."""

    def _raise(_name):  # pragma: no cover - exact path varies
        raise ImportError("forced for test")

    monkeypatch.setattr(importlib, "import_module", _raise)
    manifest = mwc._load_implemented_baseline()
    assert manifest["builtins"] == frozenset()
    assert manifest["features"] == []
    assert manifest["pine_versions"] == []
    assert manifest["manifest_status"].startswith("not_importable")


def test_manifest_loader_picks_up_real_module_if_present():
    """When openbb_pine._coverage_manifest is importable, the loader reads it.

    At Phase 0 the three sets are empty, so we only assert the call did not
    raise and produced the documented shape.
    """
    pytest.importorskip("openbb_pine._coverage_manifest")
    manifest = mwc._load_implemented_baseline()
    assert manifest["manifest_status"] == "loaded"
    assert isinstance(manifest["builtins"], frozenset)
    assert isinstance(manifest["pine_versions"], list)
    assert isinstance(manifest["features"], list)


# --- PR-comment rendering -----------------------------------------------


def test_pr_comment_shows_delta_when_baseline_provided(
    three_script_index, small_manifest, empty_manifest
):
    """PR-comment Δ column renders the absolute pp difference vs baseline."""
    current = mwc.compute_coverage(three_script_index, small_manifest)
    baseline = mwc.compute_coverage(three_script_index, empty_manifest)
    md = mwc.render_pr_comment(current, baseline)
    assert "33.33%" in md
    assert "0.00%" in md
    # +33.33 pp delta (with rounding tolerance for the formatter).
    assert "+33.33 pp" in md


def test_pr_comment_em_dash_when_no_baseline(three_script_index, small_manifest):
    """With no baseline, Δ and 'main' cells render as em-dash."""
    current = mwc.compute_coverage(three_script_index, small_manifest)
    md = mwc.render_pr_comment(current, None)
    assert "Δ" in md
    # Delta column is em-dash when there is nothing to compare against.
    assert "| — |" in md


# --- Regression gating --------------------------------------------------


def test_fail_on_regression_returns_2_when_exceeded(three_script_index, tmp_path: Path):
    """--fail-on-regression triggers exit 2 if coverage drops too far."""
    # Save a "good" baseline at 100%
    baseline_payload = mwc.compute_coverage(
        three_script_index,
        {
            "manifest_status": "loaded",
            "pine_versions": [5, 6],
            "builtins": frozenset({"ta.sma", "ta.ema", "math.foo"}),
            "features": ["indicator", "request.security"],
            "builtins_count": 3,
        },
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline_payload))

    # Write the 3-script index to disk.
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(three_script_index))

    # Now run with an empty manifest -- coverage will be 0%, a 100pp drop.
    # We need to force-empty the implemented baseline regardless of whether
    # openbb_pine._coverage_manifest is installed.
    original = mwc._load_implemented_baseline
    try:
        mwc._load_implemented_baseline = lambda: {
            "manifest_status": "loaded",
            "pine_versions": [],
            "builtins": frozenset(),
            "features": [],
            "builtins_count": 0,
        }
        rc = mwc.main(
            [
                "--index-path",
                str(index_path),
                "--baseline-json",
                str(baseline_path),
                "--fail-on-regression",
                "5.0",
            ]
        )
    finally:
        mwc._load_implemented_baseline = original

    assert rc == 2
