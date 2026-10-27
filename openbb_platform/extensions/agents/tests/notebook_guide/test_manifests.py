"""The 25 reviewed story manifests and their capability catalog (#2212, N02)."""

# pylint: disable=redefined-outer-name,wrong-import-position

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openbb_agents.notebook_guide.contracts import (  # noqa: E402
    AvailableCapability,
    CapabilityCatalog,
    PlannedCapability,
    StoryManifest,
    validate_stage_graph,
)

from scripts.build_story_manifests import PLANNED, build_manifest  # noqa: E402
from scripts.notebook_story_inventory import inventory_notebooks  # noqa: E402

STORIES = (
    REPO_ROOT
    / "openbb_platform"
    / "extensions"
    / "agents"
    / "openbb_agents"
    / "notebook_guide"
    / "stories"
)
# Every planned capability must be owned by a Notebook Companion task issue.
PROGRAM_TASK_ISSUES = set(range(2211, 2235))


def _manifests() -> dict[str, StoryManifest]:
    manifests = {}
    for path in sorted(STORIES.glob("*__*.json")):
        manifest = StoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
        manifests[manifest.story_id] = manifest
    return manifests


@pytest.fixture(scope="module")
def manifests() -> dict[str, StoryManifest]:
    """Return all committed manifests, keyed by story ID."""
    return _manifests()


@pytest.fixture(scope="module")
def catalog() -> CapabilityCatalog:
    """Return the committed capability catalog."""
    return CapabilityCatalog.model_validate_json(
        (STORIES / "capability_catalog.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def sources():
    """Return the current source-only inventory, keyed by story ID."""
    return {
        source.story_id: source
        for source in inventory_notebooks(REPO_ROOT / "notebooks")
    }


def test_every_story_has_exactly_one_manifest(manifests, sources):
    """25/25 notebooks have a manifest, including the optional eighth chapter."""
    assert set(manifests) == set(sources)
    assert len(manifests) == 25
    assert {"portfolio/08", "portfolio_yfinance/08"} <= set(manifests)


def test_manifests_validate_against_the_catalog(manifests, catalog):
    """Every stage graph is acyclic and every capability resolves."""
    for manifest in manifests.values():
        validate_stage_graph(manifest, catalog)


def test_manifests_pin_current_source_hashes(manifests, sources):
    """A changed notebook fails until its manifest is regenerated and reviewed."""
    stale = {
        story_id
        for story_id, manifest in manifests.items()
        if manifest.source_sha256 != sources[story_id].source_sha256
    }
    assert not stale


def test_committed_manifests_match_the_generator(manifests, sources):
    """Hand edits and unreviewed regenerations both show up as differences."""
    previous: dict[str, str] = {}
    for story_id in sorted(sources):
        folder = story_id.split("/")[0]
        expected = build_manifest(sources[story_id], previous.get(folder))
        previous[folder] = story_id
        assert (
            manifests[story_id].model_dump(mode="json", exclude_none=True) == expected
        ), story_id


def test_every_cell_belongs_to_exactly_one_stage(manifests, sources):
    """No code or Markdown cell is silently dropped from a story."""
    for story_id, manifest in manifests.items():
        owned = [cell for stage in manifest.stages for cell in stage.cells]
        expected = [cell.position for cell in sources[story_id].cells]
        assert sorted(owned) == expected, story_id


def test_every_obb_call_is_a_stage_capability(manifests, sources):
    """Each Platform call a stage makes is named by that stage."""
    for story_id, manifest in manifests.items():
        calls = {cell.position: cell.calls for cell in sources[story_id].cells}
        for stage in manifest.stages:
            needed = {
                "platform:" + call[4:].replace(".", "_")
                for cell in stage.cells
                for call in calls[cell]
                if call.startswith("obb.")
            }
            assert needed <= set(stage.capabilities), (story_id, stage.id)


def test_catalog_pins_tools_and_owns_every_gap(catalog):
    """Platform tools carry schema hashes; every planned gap has an owner task."""
    for name, entry in catalog.entries.items():
        if name.startswith("platform:"):
            assert isinstance(entry, AvailableCapability), name
            assert entry.ref.tool == name.split(":", 1)[1]
        else:
            assert isinstance(entry, PlannedCapability), name
            assert entry.owner_issue in PROGRAM_TASK_ISSUES, name
            assert PLANNED[name][1] == entry.owner_issue


def test_personal_data_stages_are_optional_and_private(manifests, catalog):
    """Only sanitized private reads, and never a mandatory step (#2214)."""
    private = {
        name
        for name, entry in catalog.entries.items()
        if isinstance(entry, AvailableCapability) and entry.ref.access == "private_read"
    }
    assert private == {"platform:portfolio_portfolio_snapshots"}
    stages = [
        stage
        for manifest in manifests.values()
        for stage in manifest.stages
        if private & set(stage.capabilities)
    ]
    assert stages and all(stage.optional for stage in stages)


def test_no_unclassified_binding_reviews_remain(manifests):
    """N04 resolves every binding the generator could not decide."""
    assert not any(
        "story:binding_review" in stage.capabilities
        for manifest in manifests.values()
        for stage in manifest.stages
    )


def test_portfolio_families_keep_both_provider_variants(manifests):
    """Every Portfolio family is told with both the Portfolio and free providers."""
    families: dict[str, set[str]] = {}
    for manifest in manifests.values():
        if manifest.family.startswith("portfolio/"):
            families.setdefault(manifest.family, set()).add(manifest.variant)
    assert len(families) == 8
    assert all(
        variants == {"portfolio", "free-provider"} for variants in families.values()
    )


def test_cross_chapter_state_comes_from_earlier_chapters(manifests):
    """Stories read state only from an earlier chapter of the same series."""
    for manifest in manifests.values():
        for stage in manifest.stages:
            for binding in stage.inputs:
                if binding.from_story is None:
                    continue
                assert (
                    binding.from_story.split("/")[0] == manifest.story_id.split("/")[0]
                )
                assert binding.from_story < manifest.story_id
                assert binding.from_story in manifests


def test_manifests_contain_no_saved_outputs_or_absolute_paths():
    """Manifests carry structure, never notebook outputs or local paths."""
    for path in STORIES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "outputs" not in json.loads(text)
        assert ":\\\\" not in text and "/Users/" not in text and "/home/" not in text


def _stage(manifest, prefix):
    matches = [s for s in manifest.stages if s.id.startswith(prefix)]
    assert len(matches) == 1, (manifest.story_id, prefix)
    return matches[0]


@pytest.mark.parametrize(
    ("story_id", "stage", "tool"),
    [
        ("portfolio/03", "3-", "platform:story_basket_effective_positions"),
        ("portfolio/03", "4-", "platform:story_basket_sector_view"),
        ("portfolio/03", "5-", "platform:story_concentration"),
        ("portfolio/03", "7-", "platform:story_concentration"),
        ("portfolio/03", "8-", "platform:story_construction_targets"),
        ("portfolio_yfinance/03", "3-", "platform:story_basket_effective_positions"),
        ("portfolio/08", "6-", "platform:story_basket_sector_view"),
        ("portfolio/08", "10a-", "platform:story_basket_effective_positions"),
        ("portfolio/02", "1-", "platform:story_single_name_analysis"),
        ("portfolio/02", "7-", "platform:story_single_name_analysis"),
        ("portfolio/02", "8-", "platform:story_single_name_analysis"),
        ("portfolio/08", "7-", "platform:story_single_name_analysis"),
        ("portfolio/05", "2-", "platform:story_candidate_trades"),
        ("portfolio/05", "4-", "platform:story_whatif_diff"),
        ("portfolio/05", "5-", "platform:story_brinson_attribution"),
        ("portfolio_yfinance/05", "2-", "platform:story_candidate_trades"),
        ("portfolio_yfinance/05", "4-", "platform:story_brinson_attribution"),
        ("techtrade/01", "3-", "platform:story_market_weather"),
        ("techtrade/02", "6-", "platform:story_actionable_plans"),
        ("techtrade/03", "6-", "platform:story_round_trip_pnl"),
        ("techtrade/05", "7-", "platform:story_indicator_config"),
        ("techtrade/06", "4-", "platform:story_replay_recommendations"),
    ],
)
def test_reviewed_xray_stages_bind_to_story_analytics_tools(
    manifests, catalog, story_id, stage, tool
):
    """N05a (#2313): reviewed x-ray stages run on the server's tools."""
    bound = _stage(manifests[story_id], stage)
    assert tool in bound.capabilities
    assert "story:analytics" not in bound.capabilities
    assert isinstance(catalog.entries[tool], AvailableCapability)


@pytest.mark.parametrize(
    ("story_id", "stage"),
    [("portfolio_yfinance/03", "4-"), ("portfolio_yfinance/08", "6-")],
)
def test_free_tier_sector_maps_wait_on_provider_modes(manifests, story_id, stage):
    """The hand-maintained free-tier sector map is a provider mode (N10)."""
    assert "story:provider_modes" in _stage(manifests[story_id], stage).capabilities


def test_every_reviewed_binding_matches_a_stage():
    """A renamed notebook section cannot silently drop a reviewed binding."""
    # pylint: disable=import-outside-toplevel
    from scripts.build_story_manifests import REVIEWED_BINDINGS, unused_bindings

    sources = inventory_notebooks(REPO_ROOT / "notebooks")
    previous: dict[str, str] = {}
    built = []
    for source in sources:
        folder = source.story_id.split("/")[0]
        built.append(build_manifest(source, previous.get(folder)))
        previous[folder] = source.story_id
    assert REVIEWED_BINDINGS
    assert unused_bindings(built) == []


def test_timing_loops_bind_the_tools_they_time(manifests):
    """The chapter 7 routine binds the pipeline it times, with no residual."""
    bound = _stage(manifests["portfolio/07"], "5-")
    assert "platform:story_single_name_analysis" in bound.capabilities
    assert "story:analytics" not in bound.capabilities


@pytest.mark.parametrize(
    ("story_id", "stage"),
    [("portfolio/04", "5-"), ("portfolio_yfinance/04", "6-")],
)
def test_illustrative_fixture_stages_need_no_capability(manifests, story_id, stage):
    """Worked examples of a signal's shape are narrative, not analytics."""
    bound = _stage(manifests[story_id], stage)
    assert bound.capabilities == []
    assert bound.kind == "narrative"


def test_the_what_if_stage_binds_its_arithmetic(manifests):
    """The what-if diff stage was bound only to quotes; its math is a tool now."""
    bound = _stage(manifests["portfolio/05"], "3-")
    assert {"platform:equity_price_quote", "platform:story_whatif_diff"} <= set(
        bound.capabilities
    )


@pytest.mark.parametrize(
    ("story_id", "stage"),
    [("techtrade/03", "1-"), ("techtrade/04", "9-"), ("techtrade/05", "10-")],
)
def test_techtrade_probes_and_tables_need_no_capability(manifests, story_id, stage):
    """Dependency probes, static tables and code templates run nothing."""
    assert _stage(manifests[story_id], stage).capabilities == []


def test_techtrade_story_analytics_bridge_is_drained(manifests):
    """N05d leaves no TechTrade chapter 1-6 stage waiting on story:analytics."""
    waiting = [
        (story_id, stage.id)
        for story_id, manifest in manifests.items()
        if story_id in {f"techtrade/0{i}" for i in range(1, 7)}
        for stage in manifest.stages
        if "story:analytics" in stage.capabilities
    ]
    assert waiting == []


def test_reviewed_binding_keys_are_unique():
    """A stage reviewed twice would silently keep only the later binding."""
    # pylint: disable=import-outside-toplevel
    import ast

    source = (REPO_ROOT / "scripts" / "build_story_manifests.py").read_text(
        encoding="utf-8"
    )
    keys = [
        (node.elts[0].value, node.elts[1].value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Tuple)
        and len(node.elts) >= 2
        and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str)
            for e in node.elts[:2]
        )
        and "/" in node.elts[0].value
        and node.elts[0].value.split("/")[0]
        in {"portfolio", "portfolio_yfinance", "techtrade"}
    ]
    duplicated = sorted({k for k in keys if keys.count(k) > 1})
    assert not duplicated, duplicated


def test_no_stage_waits_on_story_analytics_or_story_state(manifests):
    """N05e (#2321): N05 is drained and run state is a delivered tool."""
    waiting = [
        (story_id, stage.id, name)
        for story_id, manifest in manifests.items()
        for stage in manifest.stages
        for name in stage.capabilities
        if name in {"story:analytics", "story:state"}
    ]
    assert waiting == []


def test_state_handoffs_bind_to_the_run_registry(manifests, catalog):
    """Stages that hand state between chapters use the N06 run tools."""
    state_stages = [
        stage
        for manifest in manifests.values()
        for stage in manifest.stages
        if "story_state" in stage.outputs
    ]
    assert state_stages
    for stage in state_stages:
        assert {"platform:story_run_get", "platform:story_run_checkpoint"} <= set(
            stage.capabilities
        ), stage.id
    for tool in ("platform:story_run_get", "platform:story_run_checkpoint"):
        assert isinstance(catalog.entries[tool], AvailableCapability)


@pytest.mark.parametrize(
    ("story_id", "stage", "capability"),
    [
        ("techtrade/08", "7-", "story:paper"),
        ("techtrade/09", "9-", "story:paper"),
        ("techtrade/07", "5-", "story:artifacts"),
        ("portfolio_yfinance/03", "4-", "story:provider_modes"),
        ("portfolio/07", "2-", "story:provider_modes"),
        ("portfolio/03", "1-", "platform:story_run_get"),
    ],
)
def test_remaining_stages_moved_to_their_owning_bridge(
    manifests, story_id, stage, capability
):
    """Paper, artifact, provider-mode and state work waits on its own bridge."""
    assert capability in _stage(manifests[story_id], stage).capabilities


@pytest.mark.parametrize(
    ("story_id", "stage"),
    [
        ("portfolio_yfinance/01", "0-before"),
        ("portfolio/02", "11-"),
        ("portfolio_yfinance/03", "8-"),
        ("techtrade/09", "1-"),
    ],
)
def test_probes_and_illustrations_need_nothing(manifests, story_id, stage):
    """Environment probes and illustrations run no capability."""
    assert _stage(manifests[story_id], stage).capabilities == []
