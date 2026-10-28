"""Story readiness against real, server-qualified capabilities (#2214, N04)."""

# pylint: disable=redefined-outer-name,wrong-import-position

import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openbb_agents.notebook_guide.contracts import (  # noqa: E402
    CapabilityCatalog,
    StoryManifest,
)
from openbb_agents.notebook_guide.readiness import (  # noqa: E402
    check_readiness,
    summarize_readiness,
)

STORIES = (
    Path(__file__).resolve().parents[2] / "openbb_agents" / "notebook_guide" / "stories"
)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _catalog(**overrides) -> CapabilityCatalog:
    entries = {
        "platform:equity_profile": {
            "status": "available",
            "ref": {
                "server": "platform",
                "tool": "equity_profile",
                "schema_sha256": SHA_A,
                "access": "provider_read",
            },
        },
        "platform:portfolio_intel_risk_metrics": {
            "status": "available",
            "ref": {
                "server": "platform",
                "tool": "portfolio_intel_risk_metrics",
                "schema_sha256": SHA_A,
                "access": "analysis",
            },
        },
        "workspace:get_workspace_snapshot": {
            "status": "available",
            "ref": {
                "server": "workspace",
                "tool": "get_workspace_snapshot",
                "schema_sha256": SHA_A,
                "access": "metadata",
            },
        },
        "story:paper": {
            "status": "planned",
            "access": "paper",
            "owner_issue": 2219,
            "summary": "Sandboxed paper actions.",
        },
    }
    entries.update(overrides)
    return CapabilityCatalog.model_validate({"schema_version": 1, "entries": entries})


def _stage(
    stage_id,
    capabilities,
    *,
    kind="analysis",
    depends_on=None,
    cells=None,
    optional=False,
):
    return {
        "id": stage_id,
        "title": stage_id,
        "kind": kind,
        "cells": cells,
        "depends_on": depends_on or [],
        "capabilities": capabilities,
        "inputs": [],
        "outputs": [f"{stage_id}-result"],
        "optional": optional,
    }


def _manifest(stages) -> StoryManifest:
    for index, stage in enumerate(stages, 1):
        stage["cells"] = stage["cells"] or [index]
    return StoryManifest.model_validate(
        {
            "schema_version": 1,
            "story_id": "portfolio/03",
            "family": "portfolio/03",
            "variant": "portfolio",
            "notebook_path": "notebooks/portfolio/03-synthetic.ipynb",
            "source_sha256": SHA_A,
            "stages": stages,
            "acceptance_cases": ["portfolio/03:fixture"],
            "limitations": [],
        }
    )


@pytest.fixture
def readiness_case():
    """Return a two-stage story plus catalogs with and without its risk tool."""
    manifest = _manifest(
        [
            _stage("basket_profile", ["platform:equity_profile"], kind="retrieval"),
            _stage(
                "basket_risk",
                ["platform:portfolio_intel_risk_metrics"],
                depends_on=["basket_profile"],
            ),
        ]
    )
    return SimpleNamespace(
        manifest=manifest,
        catalog=_catalog(),
        live={
            "platform:equity_profile": SHA_A,
            "platform:portfolio_intel_risk_metrics": SHA_A,
            # The same tool name on another server must not satisfy the stage.
            "workspace:portfolio_intel_risk_metrics": SHA_A,
        },
    )


def test_story_with_all_live_tools_is_ready(readiness_case):
    """Every stage available on its own server with its pinned schema."""
    report = check_readiness(
        readiness_case.manifest, readiness_case.catalog, live_tools=readiness_case.live
    )
    assert report.ready
    assert report.missing_stage_ids == []


def test_missing_tool_blocks_story(readiness_case):
    """A tool absent from its server blocks the stage despite a same-named tool."""
    live = dict(readiness_case.live)
    del live["platform:portfolio_intel_risk_metrics"]
    report = check_readiness(
        readiness_case.manifest, readiness_case.catalog, live_tools=live
    )
    assert not report.ready
    assert report.missing_stage_ids == ["basket_risk"]
    (stage,) = [s for s in report.stages if s.stage_id == "basket_risk"]
    assert stage.remediation == [
        "platform:portfolio_intel_risk_metrics: tool not offered by server 'platform'"
    ]


def test_schema_drift_is_missing_not_available(readiness_case):
    """A tool whose input schema changed since review is not silently used."""
    live = {**readiness_case.live, "platform:equity_profile": SHA_B}
    report = check_readiness(
        readiness_case.manifest, readiness_case.catalog, live_tools=live
    )
    assert report.missing_stage_ids == ["basket_profile"]
    (stage,) = [s for s in report.stages if s.stage_id == "basket_profile"]
    assert any("schema" in note for note in stage.remediation)


def test_unknown_capability_is_missing():
    """A capability the catalog does not know cannot be assumed to exist."""
    manifest = _manifest([_stage("ghost", ["platform:nonexistent"])])
    report = check_readiness(manifest, _catalog())
    assert report.missing_stage_ids == ["ghost"]


def test_planned_capability_is_a_visible_blocker():
    """Planned work blocks readiness and names its owning issue."""
    manifest = _manifest([_stage("fill", ["story:paper"], kind="paper")])
    report = check_readiness(manifest, _catalog())
    assert not report.ready
    assert report.planned_stage_ids == ["fill"]
    assert report.stages[0].remediation == ["#2219: Sandboxed paper actions."]


def test_access_outside_the_profile_is_forbidden():
    """A read-only profile cannot run a paper stage, planned or not."""
    manifest = _manifest([_stage("fill", ["story:paper"], kind="paper")])
    report = check_readiness(
        manifest,
        _catalog(),
        allowed_access={"metadata", "provider_read", "analysis", "artifact"},
    )
    assert report.forbidden_stage_ids == ["fill"]
    assert report.planned_stage_ids == []


def test_most_severe_capability_decides_the_stage_state():
    """A forbidden capability outranks a planned one in the same stage."""
    manifest = _manifest(
        [
            _stage(
                "fill",
                ["story:analytics", "story:paper"],
                kind="paper",
            )
        ]
    )
    catalog = _catalog(
        **{
            "story:analytics": {
                "status": "planned",
                "access": "analysis",
                "owner_issue": 2215,
                "summary": "Owned analytics adapters.",
            }
        }
    )
    report = check_readiness(
        manifest, catalog, allowed_access={"provider_read", "analysis"}
    )
    assert report.forbidden_stage_ids == ["fill"]
    assert report.stages[0].remediation == [
        "story:paper: 'paper' access is not granted to this profile"
    ]


def test_personal_data_stage_is_forbidden_without_private_read():
    """A public profile never reaches the owner's portfolio, even optionally."""
    catalog = CapabilityCatalog.model_validate_json(
        (STORIES / "capability_catalog.json").read_text(encoding="utf-8")
    )
    manifest = StoryManifest.model_validate_json(
        (STORIES / "portfolio__01.json").read_text(encoding="utf-8")
    )
    public = {"metadata", "provider_read", "analysis", "artifact"}
    report = check_readiness(manifest, catalog, allowed_access=public)
    (stage_id,) = report.forbidden_stage_ids
    (stage,) = [s for s in manifest.stages if s.id == stage_id]
    assert stage.optional
    assert "platform:portfolio_portfolio_snapshots" in stage.capabilities


def test_workspace_stage_without_browser_is_reported_separately():
    """Missing browser bridges are distinct from missing tools."""
    manifest = _manifest(
        [_stage("snapshot", ["workspace:get_workspace_snapshot"], kind="retrieval")]
    )
    report = check_readiness(manifest, _catalog(), browser_available=False)
    assert report.browser_unavailable_stage_ids == ["snapshot"]
    assert report.missing_stage_ids == []


def test_optional_stage_does_not_block_readiness(readiness_case):
    """Only mandatory stages decide whether a story can run."""
    manifest = _manifest(
        [
            _stage("basket_profile", ["platform:equity_profile"], kind="retrieval"),
            _stage("extra", ["story:paper"], kind="paper", optional=True),
        ]
    )
    report = check_readiness(manifest, readiness_case.catalog)
    assert report.ready
    assert report.planned_stage_ids == ["extra"]


def test_readiness_makes_no_network_calls(readiness_case, monkeypatch):
    """Inspection is pure: no provider, job, browser or paper call can happen."""

    def deny(*_args, **_kwargs):
        raise AssertionError("readiness opened a socket")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    check_readiness(
        readiness_case.manifest, readiness_case.catalog, live_tools=readiness_case.live
    )


def test_corpus_summary_publishes_gross_denominators():
    """The real catalog reports every stage, not an approved-only subset."""
    catalog = CapabilityCatalog.model_validate_json(
        (STORIES / "capability_catalog.json").read_text(encoding="utf-8")
    )
    manifests = [
        StoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(STORIES.glob("*__*.json"))
    ]
    summary = summarize_readiness(manifests, catalog)
    assert summary["stories"] == 25
    assert summary["stages"] == sum(len(m.stages) for m in manifests)
    states = summary["stage_states"]
    assert sum(states.values()) == summary["stages"]
    assert states["missing"] == 0
    assert states["forbidden"] == 0
    # techtrade/03 became the first fully runnable story in N05d (#2316);
    # N07 (#2217) made four more runnable and N08 (#2218) six more. The rest
    # wait on N09 and N10.
    ready = {m.story_id for m in manifests if check_readiness(m, catalog).ready}
    assert ready == {
        "techtrade/01",
        "techtrade/02",
        "techtrade/03",
        "techtrade/04",
        "techtrade/05",
        "techtrade/06",
        "portfolio/03",
        "portfolio/04",
        "portfolio/06",
        "portfolio/08",
        "portfolio_yfinance/06",
    }
    assert summary["ready_stories"] == len(ready)
    # N05-N08 (#2215-#2218) are drained: their stages are bound to delivered
    # tools or reviewed onto the bridge that owns them.
    assert set(summary["planned_by_owner"]) == {"#2219", "#2220"}
