"""Versioned contracts for notebook story manifests and runs (#2212, N02).

A ``StoryManifest`` describes one notebook story as ordered stages. Each stage
names the capabilities it needs from a ``CapabilityCatalog``. A catalog entry
is either *available* (a real MCP tool whose input schema is pinned by hash)
or *planned* (a capability the program still has to build, with the issue that
owns it). That split keeps every required outcome mapped to a tool or to a
visible blocker. State moves between stages and chapters only through named,
typed bindings, never pickle files or filesystem paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.:/-]*$")]
# ``private_read`` covers sanitized reads of the operator's own portfolio
# through the Portfolio adapter; profiles without it can never see them.
Access = Literal[
    "metadata", "provider_read", "private_read", "analysis", "artifact", "paper"
]
StageKind = Literal[
    "setup",
    "narrative",
    "retrieval",
    "analysis",
    "artifact",
    "state",
    "job",
    "paper",
]

# Stages of these kinds only arrange the environment or tell the story; every
# other stage does financial work and must name at least one capability.
CAPABILITY_FREE_KINDS = frozenset({"setup", "narrative"})


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityRef(_Contract):
    """A real MCP tool, pinned to the input schema it was reviewed against."""

    server: Identifier
    tool: Identifier
    schema_sha256: Sha256
    access: Access


class AvailableCapability(_Contract):
    """Catalog entry for a capability an MCP server already exposes."""

    status: Literal["available"]
    ref: CapabilityRef


class PlannedCapability(_Contract):
    """Catalog entry for a capability still to be built, with its owner."""

    status: Literal["planned"]
    access: Access
    owner_issue: int = Field(gt=0)
    summary: str = Field(min_length=1)


CatalogEntry = Annotated[
    AvailableCapability | PlannedCapability, Field(discriminator="status")
]


class CapabilityCatalog(_Contract):
    """Server-qualified capabilities, independent of any live client."""

    schema_version: Literal[1]
    entries: Mapping[Identifier, CatalogEntry]

    def resolve(self, name: str) -> AvailableCapability | PlannedCapability:
        """Return the entry for ``name`` or raise ``KeyError``."""
        return self.entries[name]


class ArtifactRef(_Contract):
    """A bounded artifact produced by a run."""

    run_id: str
    artifact_id: str
    media_type: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)


class StageEvidence(_Contract):
    """What one stage actually did, with citations."""

    stage_id: str
    status: Literal["succeeded", "failed", "unavailable", "approval_required"]
    tool_call_ids: list[str]
    artifacts: list[ArtifactRef]
    limitations: list[str]


class InputBinding(_Contract):
    """A typed input: an upstream stage output or another story's output."""

    name: Identifier
    output: Identifier
    from_stage: Identifier | None = None
    from_story: Identifier | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> InputBinding:
        if (self.from_stage is None) == (self.from_story is None):
            raise ValueError("an input names exactly one of from_stage or from_story")
        return self


class StoryStage(_Contract):
    """One ordered step of a story."""

    id: Identifier
    title: str = Field(min_length=1)
    kind: StageKind
    cells: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)
    depends_on: list[Identifier]
    capabilities: list[Identifier]
    inputs: list[InputBinding]
    outputs: list[Identifier]
    optional: bool


class StoryManifest(_Contract):
    """A reviewed, source-versioned description of one notebook story."""

    schema_version: Literal[1]
    story_id: Identifier
    family: Identifier
    variant: Literal["portfolio", "free-provider", "techtrade"]
    notebook_path: str = Field(pattern=r"^notebooks/[^\\]+\.ipynb$")
    source_sha256: Sha256
    stages: list[StoryStage] = Field(min_length=1)
    acceptance_cases: list[str] = Field(min_length=1)
    limitations: list[str]


class Budget(_Contract):
    """Run limits; defaults follow the program's global constraints."""

    max_tool_calls: int = Field(default=40, ge=1)
    max_argument_repairs: int = Field(default=2, ge=0)
    max_wall_seconds: int = Field(default=900, ge=1)
    max_concurrent_mutations: Literal[1] = 1


class RunPlan(_Contract):
    """A deterministic, approved plan for one story run."""

    plan_id: str
    manifest_version: str
    catalog_version: int
    inputs: dict[str, str | int | float | bool]
    provider_mode: Literal["fixture", "recorded", "live"]
    sandbox: str | None = None
    stage_order: list[Identifier] = Field(min_length=1)
    budget: Budget = Budget()


class RunState(_Contract):
    """Server-side run state under optimistic concurrency."""

    run_id: str
    plan_id: str
    state_version: int = Field(ge=0)
    stage_status: dict[
        Identifier,
        Literal[
            "pending",
            "running",
            "succeeded",
            "failed",
            "unavailable",
            "approval_required",
        ],
    ]
    job_ids: dict[Identifier, str]
    evidence_ids: list[str]
    pending_approval_ids: list[str]


class ApprovalRequest(_Contract):
    """A human approval bound to one call; never a model-supplied boolean."""

    principal: str = Field(min_length=1)
    sandbox: str = Field(min_length=1)
    tool: Identifier
    argument_sha256: Sha256
    manifest_version: str = Field(min_length=1)
    expires_at: datetime
    nonce: str = Field(min_length=32)


def _check_unique_stages(manifest: StoryManifest) -> dict[str, StoryStage]:
    stages: dict[str, StoryStage] = {}
    for stage in manifest.stages:
        if stage.id in stages:
            raise ValueError(f"{manifest.story_id}: duplicate stage '{stage.id}'")
        stages[stage.id] = stage
    return stages


def _upstream(stage_id: str, stages: Mapping[str, StoryStage]) -> set[str]:
    seen: set[str] = set()
    pending = list(stages[stage_id].depends_on)
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(stages[current].depends_on)
    return seen


def _check_acyclic(manifest: StoryManifest, stages: Mapping[str, StoryStage]) -> None:
    state: dict[str, str] = {}

    def visit(stage_id: str) -> None:
        if state.get(stage_id) == "done":
            return
        if state.get(stage_id) == "visiting":
            raise ValueError(f"{manifest.story_id}: stage cycle through '{stage_id}'")
        state[stage_id] = "visiting"
        for dependency in stages[stage_id].depends_on:
            visit(dependency)
        state[stage_id] = "done"

    for stage_id in stages:
        visit(stage_id)


def validate_stage_graph(
    manifest: StoryManifest, catalog: CapabilityCatalog | None = None
) -> None:
    """Reject manifests that are not executable, ordered stage graphs.

    Checks unique stage IDs, known dependencies, acyclicity, that every input
    comes from a declared output of an upstream stage, that each notebook cell
    belongs to one stage, that financial stages name a capability, and (when a
    catalog is given) that every capability resolves.
    """
    stages = _check_unique_stages(manifest)
    for stage in manifest.stages:
        for dependency in stage.depends_on:
            if dependency not in stages:
                raise ValueError(
                    f"{manifest.story_id}: stage '{stage.id}' depends on unknown "
                    f"stage '{dependency}'"
                )
    _check_acyclic(manifest, stages)

    owners: dict[int, str] = {}
    for stage in manifest.stages:
        for cell in stage.cells:
            if cell in owners:
                raise ValueError(
                    f"{manifest.story_id}: cell {cell} belongs to more than one stage"
                )
            owners[cell] = stage.id
        if not stage.capabilities and stage.kind not in CAPABILITY_FREE_KINDS:
            raise ValueError(
                f"{manifest.story_id}: stage '{stage.id}' has no capability"
            )
        upstream = _upstream(stage.id, stages)
        for binding in stage.inputs:
            if binding.from_stage is None:
                continue
            if binding.from_stage not in upstream:
                raise ValueError(
                    f"{manifest.story_id}: '{binding.from_stage}' is not upstream "
                    f"of '{stage.id}'"
                )
            if binding.output not in stages[binding.from_stage].outputs:
                raise ValueError(
                    f"{manifest.story_id}: stage '{binding.from_stage}' does not "
                    f"declare output '{binding.output}'"
                )
        if catalog is not None:
            for name in stage.capabilities:
                if name not in catalog.entries:
                    raise ValueError(
                        f"{manifest.story_id}: stage '{stage.id}' needs unresolved "
                        f"capability '{name}'"
                    )
