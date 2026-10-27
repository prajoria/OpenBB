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
