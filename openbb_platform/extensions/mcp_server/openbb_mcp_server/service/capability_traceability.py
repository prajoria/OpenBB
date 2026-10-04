"""Dynamic capability-to-work accountability reporting."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from openbb_mcp_server.service.capability_inventory import ProviderModelMetadata
from openbb_mcp_server.service.exposure_policy import (
    ExposurePolicy,
    ImplementationState,
)


class TraceabilityItem(BaseModel):
    """One capability linked to accountable work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    rule_id: str
    family: str
    owner_issues: tuple[str, ...]
    rationale: str
    source_evidence: tuple[str, ...]
    review_triggers: tuple[str, ...]
    implementation_state: ImplementationState


class TraceabilityReport(BaseModel):
    """Complete dynamic traceability output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[TraceabilityItem, ...]
    unowned: tuple[str, ...]


def build_traceability_report(
    policy: ExposurePolicy,
    *,
    operations: Iterable[tuple[str, str, str]] = (),
    provider_models: Iterable[ProviderModelMetadata] = (),
    specialists: Iterable[tuple[str, str]] = (),
) -> TraceabilityReport:
    """Classify discovered capabilities and retain all unowned drift."""
    decisions = []
    unowned = []
    for scope, method, path in operations:
        capability_id = f"operation:{scope}:{method.upper()}:{path}"
        try:
            decisions.append(policy.classify_operation(scope, method, path))
        except (KeyError, ValueError):
            unowned.append(capability_id)
    for row in provider_models:
        decisions.append(policy.classify_provider_model(row))
    for surface, name in specialists:
        if name not in policy.document.traceability.reviewed_specialists.get(
            surface, ()
        ):
            unowned.append(f"specialist:{surface}:{name}")
            continue
        try:
            decisions.append(policy.classify_specialist(surface, name))
        except (KeyError, ValueError):
            unowned.append(f"specialist:{surface}:{name}")

    items = []
    traceability = policy.document.traceability
    for decision in decisions:
        family_name = traceability.rule_owners.get(decision.rule_id)
        if family_name is None:
            unowned.append(decision.capability_id)
            continue
        family = traceability.work_families[family_name]
        implementation_state: ImplementationState = (
            "implemented_product"
            if decision.disposition in {"direct", "metadata_only", "workspace_indirect"}
            else family.implementation_state
        )
        items.append(
            TraceabilityItem(
                capability_id=decision.capability_id,
                rule_id=decision.rule_id,
                family=family_name,
                owner_issues=family.owner_issues,
                rationale=family.rationale,
                source_evidence=family.source_evidence,
                review_triggers=family.review_triggers,
                implementation_state=implementation_state,
            )
        )
    return TraceabilityReport(
        items=tuple(sorted(items, key=lambda item: item.capability_id)),
        unowned=tuple(sorted(set(unowned))),
    )


__all__ = [
    "TraceabilityItem",
    "TraceabilityReport",
    "build_traceability_report",
]
