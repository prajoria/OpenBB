"""Typed story manifest and stage-graph contracts (#2212, N02)."""

# pylint: disable=redefined-outer-name,wrong-import-position

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openbb_agents.notebook_guide.contracts import (  # noqa: E402
    ApprovalRequest,
    CapabilityCatalog,
    StoryManifest,
    validate_stage_graph,
)

SHA = "a" * 64


@pytest.fixture
def catalog() -> CapabilityCatalog:
    """Return a catalog with one available tool and one planned capability."""
    return CapabilityCatalog.model_validate(
        {
            "schema_version": 1,
            "entries": {
                "platform:equity_profile": {
                    "status": "available",
                    "ref": {
                        "server": "platform",
                        "tool": "equity_profile",
                        "schema_sha256": SHA,
                        "access": "provider_read",
                    },
                },
                "story:analytics": {
                    "status": "planned",
                    "access": "analysis",
                    "owner_issue": 2215,
                    "summary": "Notebook-local analytics behind an owned adapter.",
                },
            },
        }
    )


@pytest.fixture
def manifest_factory():
    """Return a factory that builds a manifest from compact stage data."""

    def factory(
        *,
        dependencies: dict[str, list[str]] | None = None,
        capabilities: dict[str, list[str]] | None = None,
        inputs: dict[str, list[dict]] | None = None,
        outputs: dict[str, list[str]] | None = None,
        cells: dict[str, list[int]] | None = None,
        extra_stage_fields: dict | None = None,
    ) -> StoryManifest:
        dependencies = dependencies or {"a": [], "b": ["a"]}
        stages = []
        for index, (stage_id, depends_on) in enumerate(dependencies.items(), 1):
            stage = {
                "id": stage_id,
                "title": f"Stage {stage_id}",
                "kind": "analysis",
                "cells": (cells or {}).get(stage_id, [index]),
                "depends_on": depends_on,
                "capabilities": (capabilities or {}).get(
                    stage_id, ["platform:equity_profile"]
                ),
                "inputs": (inputs or {}).get(stage_id, []),
                "outputs": (outputs or {}).get(stage_id, [f"{stage_id}_result"]),
                "optional": False,
            }
            stage.update(extra_stage_fields or {})
            stages.append(stage)
        return StoryManifest.model_validate(
            {
                "schema_version": 1,
                "story_id": "portfolio/01",
                "family": "portfolio/01",
                "variant": "portfolio",
                "notebook_path": "notebooks/portfolio/01-synthetic.ipynb",
                "source_sha256": SHA,
                "stages": stages,
                "acceptance_cases": ["portfolio/01:fixture"],
                "limitations": [],
            }
        )

    return factory


def test_valid_manifest_passes(manifest_factory, catalog):
    """A linear two-stage story with resolvable capabilities validates."""
    validate_stage_graph(manifest_factory(), catalog)


def test_stage_cycle_is_rejected(manifest_factory):
    """Stages that depend on each other are not an executable plan."""
    manifest = manifest_factory(dependencies={"a": ["b"], "b": ["a"]})
    with pytest.raises(ValueError, match="cycle"):
        validate_stage_graph(manifest)


def test_unknown_dependency_is_rejected(manifest_factory):
    """A stage cannot wait on a stage the story does not define."""
    manifest = manifest_factory(dependencies={"a": ["ghost"]})
    with pytest.raises(ValueError, match="unknown stage 'ghost'"):
        validate_stage_graph(manifest)


def test_duplicate_stage_ids_are_rejected(manifest_factory):
    """Two stages with one ID would make evidence ambiguous."""
    manifest = manifest_factory()
    duplicated = manifest.model_copy(
        update={"stages": [manifest.stages[0], manifest.stages[0]]}
    )
    with pytest.raises(ValueError, match="duplicate stage 'a'"):
        validate_stage_graph(duplicated)


def test_input_must_come_from_an_upstream_output(manifest_factory):
    """A binding to an output the source stage never declares is rejected."""
    manifest = manifest_factory(
        inputs={"b": [{"name": "basket", "from_stage": "a", "output": "missing"}]}
    )
    with pytest.raises(ValueError, match="does not declare output 'missing'"):
        validate_stage_graph(manifest)


def test_input_from_a_non_upstream_stage_is_rejected(manifest_factory):
    """Data may only flow from stages the consumer waits on."""
    manifest = manifest_factory(
        dependencies={"a": [], "b": [], "c": ["a"]},
        inputs={"c": [{"name": "x", "from_stage": "b", "output": "b_result"}]},
    )
    with pytest.raises(ValueError, match="'b' is not upstream of 'c'"):
        validate_stage_graph(manifest)


def test_input_from_upstream_output_is_accepted(manifest_factory, catalog):
    """A transitive upstream output satisfies a binding."""
    manifest = manifest_factory(
        dependencies={"a": [], "b": ["a"], "c": ["b"]},
        inputs={"c": [{"name": "x", "from_stage": "a", "output": "a_result"}]},
    )
    validate_stage_graph(manifest, catalog)


def test_external_story_input_names_its_source_story(manifest_factory, catalog):
    """Cross-chapter handoffs cite the producing story, never a pickle path."""
    manifest = manifest_factory(
        inputs={
            "a": [{"name": "basket", "from_story": "portfolio/02", "output": "basket"}]
        }
    )
    validate_stage_graph(manifest, catalog)
    with pytest.raises(ValidationError):
        manifest_factory(
            inputs={"a": [{"name": "basket", "path": ".notebook_state/basket.pkl"}]}
        )


def test_unresolved_capability_is_rejected(manifest_factory, catalog):
    """Every capability must be available or planned with an owner."""
    manifest = manifest_factory(capabilities={"a": ["platform:nonexistent"]})
    with pytest.raises(
        ValueError, match="unresolved capability 'platform:nonexistent'"
    ):
        validate_stage_graph(manifest, catalog)


def test_planned_capability_requires_an_owner_issue():
    """A planned gap without an owning issue is not a visible blocker."""
    with pytest.raises(ValidationError):
        CapabilityCatalog.model_validate(
            {
                "schema_version": 1,
                "entries": {"story:x": {"status": "planned", "access": "analysis"}},
            }
        )


def test_unknown_fields_are_rejected(manifest_factory):
    """Contracts forbid unknown fields so typos cannot silently pass."""
    with pytest.raises(ValidationError):
        manifest_factory(extra_stage_fields={"unexpected": True})


def test_cell_references_are_one_based_and_unique(manifest_factory):
    """Cells are one-based notebook positions owned by exactly one stage."""
    with pytest.raises(ValidationError):
        manifest_factory(cells={"a": [0]})
    manifest = manifest_factory(cells={"a": [1, 2], "b": [2, 3]})
    with pytest.raises(ValueError, match="cell 2 belongs to more than one stage"):
        validate_stage_graph(manifest)


def test_financial_stage_without_capability_is_rejected(manifest_factory):
    """Only setup and narrative stages may run without a capability."""
    manifest = manifest_factory(capabilities={"a": []})
    with pytest.raises(ValueError, match="stage 'a' has no capability"):
        validate_stage_graph(manifest)


def test_approval_request_is_bound_to_one_call():
    """Approvals carry a principal, sandbox, argument hash and one-use nonce."""
    request = ApprovalRequest.model_validate(
        {
            "principal": "operator",
            "sandbox": "paper-sandbox-1",
            "tool": "story:paper",
            "argument_sha256": SHA,
            "manifest_version": "portfolio/05@1",
            "expires_at": "2026-10-27T20:00:00Z",
            "nonce": "n" * 32,
        }
    )
    assert request.nonce == "n" * 32
    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate(
            {**request.model_dump(mode="json"), "approved": True}
        )
