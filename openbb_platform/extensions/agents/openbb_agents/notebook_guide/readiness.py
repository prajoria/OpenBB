"""Story readiness against server-qualified capabilities (#2214, N04).

``check_readiness`` decides, for one manifest, which stages can run now. It is
a pure function over data: the manifest, the reviewed catalog and, optionally,
a discovery snapshot of live ``server:tool`` schema hashes. It never opens a
connection, so metadata inspection cannot cause a financial, job, browser or
paper call.

Stage states, most severe first:

- ``forbidden``: a capability's access class is outside the profile.
- ``missing``: a capability is unknown, absent from its own server, or its
  input schema no longer matches the reviewed hash. A tool of the same name on
  another server never counts.
- ``browser_unavailable``: a Workspace capability needs a browser bridge.
- ``planned``: a capability is still to be built; remediation names its owner.
- ``available``: every capability is present and current.

A story is ready only when every mandatory stage is available.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from .contracts import (
    CAPABILITY_FREE_KINDS,
    AvailableCapability,
    CapabilityCatalog,
    StoryManifest,
)

StageState = Literal[
    "available", "planned", "browser_unavailable", "missing", "forbidden"
]
_SEVERITY: dict[str, int] = {
    "available": 0,
    "planned": 1,
    "browser_unavailable": 2,
    "missing": 3,
    "forbidden": 4,
}
BROWSER_SERVERS = frozenset({"workspace"})


class StageReadiness(BaseModel):
    """Readiness of one stage, with what would unblock it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_id: str
    state: StageState
    optional: bool
    capabilities: list[str]
    remediation: list[str]


class ReadinessReport(BaseModel):
    """Readiness of one story, stage by stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    ready: bool
    stages: list[StageReadiness]

    def _ids(self, state: str) -> list[str]:
        return [stage.stage_id for stage in self.stages if stage.state == state]

    @property
    def missing_stage_ids(self) -> list[str]:
        """Stages blocked by an unknown, absent or drifted tool."""
        return self._ids("missing")

    @property
    def forbidden_stage_ids(self) -> list[str]:
        """Stages the profile is not allowed to run."""
        return self._ids("forbidden")

    @property
    def planned_stage_ids(self) -> list[str]:
        """Stages waiting on a capability that is still being built."""
        return self._ids("planned")

    @property
    def browser_unavailable_stage_ids(self) -> list[str]:
        """Stages that need a Workspace browser bridge."""
        return self._ids("browser_unavailable")


def _capability_state(
    name: str,
    catalog: CapabilityCatalog,
    allowed_access: set[str] | None,
    live_tools: Mapping[str, str] | None,
    browser_available: bool,
) -> tuple[StageState, str | None]:
    entry = catalog.entries.get(name)
    if entry is None:
        return "missing", f"{name}: not in the capability catalog"
    access = (
        entry.ref.access if isinstance(entry, AvailableCapability) else entry.access
    )
    if allowed_access is not None and access not in allowed_access:
        return "forbidden", f"{name}: '{access}' access is not granted to this profile"
    if not isinstance(entry, AvailableCapability):
        return "planned", f"#{entry.owner_issue}: {entry.summary}"
    qualified = f"{entry.ref.server}:{entry.ref.tool}"
    if live_tools is not None:
        live_hash = live_tools.get(qualified)
        if live_hash is None:
            return "missing", f"{name}: tool not offered by server '{entry.ref.server}'"
        if live_hash != entry.ref.schema_sha256:
            return "missing", f"{name}: input schema changed since review"
    if entry.ref.server in BROWSER_SERVERS and not browser_available:
        return "browser_unavailable", f"{name}: needs an authenticated browser bridge"
    return "available", None


def check_readiness(
    manifest: StoryManifest,
    catalog: CapabilityCatalog,
    *,
    allowed_access: Iterable[str] | None = None,
    live_tools: Mapping[str, str] | None = None,
    browser_available: bool = True,
) -> ReadinessReport:
    """Report which stages of ``manifest`` can run against ``catalog``.

    ``allowed_access`` limits the access classes the profile grants (``None``
    grants all). ``live_tools`` maps ``server:tool`` to the input-schema hash
    a live discovery returned; when omitted, only the reviewed catalog is
    consulted.
    """
    allowed = set(allowed_access) if allowed_access is not None else None
    stages = []
    for stage in manifest.stages:
        if not stage.capabilities and stage.kind in CAPABILITY_FREE_KINDS:
            state: StageState = "available"
            notes: list[str] = []
        else:
            results = [
                _capability_state(name, catalog, allowed, live_tools, browser_available)
                for name in stage.capabilities
            ]
            state = max((result[0] for result in results), key=_SEVERITY.__getitem__)
            notes = sorted(
                {
                    note
                    for result_state, note in results
                    if note and result_state == state
                }
            )
        stages.append(
            StageReadiness(
                stage_id=stage.id,
                state=state,
                optional=stage.optional,
                capabilities=list(stage.capabilities),
                remediation=notes,
            )
        )
    ready = all(stage.state == "available" for stage in stages if not stage.optional)
    return ReadinessReport(story_id=manifest.story_id, ready=ready, stages=stages)


def summarize_readiness(
    manifests: Iterable[StoryManifest],
    catalog: CapabilityCatalog,
    **options,
) -> dict:
    """Gross readiness denominators across a corpus of manifests.

    Counts every stage, including setup and narrative ones, and reports
    planned stages by owning issue rather than an approved-only percentage.
    """
    reports = [check_readiness(manifest, catalog, **options) for manifest in manifests]
    states = Counter(stage.state for report in reports for stage in report.stages)
    planned_by_owner: Counter[str] = Counter()
    for report in reports:
        for stage in report.stages:
            if stage.state == "planned":
                for note in stage.remediation:
                    planned_by_owner[note.split(":", 1)[0]] += 1
    return {
        "stories": len(reports),
        "ready_stories": sum(report.ready for report in reports),
        "stages": sum(len(report.stages) for report in reports),
        "stage_states": {state: states[state] for state in get_args(StageState)},
        "planned_by_owner": dict(sorted(planned_by_owner.items())),
    }
