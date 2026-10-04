"""Reviewed deny-by-default capability exposure policy."""

from __future__ import annotations

import csv
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openbb_mcp_server.models.capability import (
    AccessClass,
    CapabilityRecord,
    Disposition,
)
from openbb_mcp_server.service.capability_inventory import (
    ProfileName,
    ProviderModelMetadata,
)


class ExposureDecision(BaseModel):
    """One independently reviewable policy decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    rule_id: str
    disposition: Disposition
    access_class: AccessClass
    admitted_profiles: tuple[ProfileName, ...]
    reason: str | None = None

    @model_validator(mode="after")
    def require_exclusion_reason(self) -> ExposureDecision:
        """Restricted and unimplemented decisions require a reason."""
        if self.disposition in {"restricted", "unimplemented"} and not self.reason:
            raise ValueError("restricted and unimplemented decisions require a reason")
        return self


class OperationRule(BaseModel):
    """Ordered operation match rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    priority: int = Field(ge=0)
    scopes: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    path_prefixes: tuple[str, ...] = ()
    disposition: Disposition
    access_class: AccessClass
    admitted_profiles: tuple[ProfileName, ...]
    reason: str | None = None

    @model_validator(mode="after")
    def require_exclusion_reason(self) -> OperationRule:
        """Restricted and unimplemented rules require a reason."""
        if self.disposition in {"restricted", "unimplemented"} and not self.reason:
            raise ValueError("restricted and unimplemented rules require a reason")
        return self

    def matches(self, scope: str, method: str, path: str) -> bool:
        """Return whether this rule matches an audited operation."""
        if self.scopes and scope not in self.scopes:
            return False
        if self.methods and method.upper() not in self.methods:
            return False
        if self.paths or self.path_prefixes:
            return path in self.paths or any(
                path.startswith(prefix) for prefix in self.path_prefixes
            )
        return True


class SpecialistRule(BaseModel):
    """Default policy for one specialist MCP surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Disposition
    access_class: AccessClass
    reason: str
    admitted_profiles: tuple[ProfileName, ...] = ()


class ProviderRule(SpecialistRule):
    """Policy for routed or unrouted provider/model registrations."""


class OperationCatalog(BaseModel):
    """Pinned exact reviewed operation membership."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PolicyDocument(BaseModel):
    """Versioned policy asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    operation_catalog: OperationCatalog
    reviewed_metadata_ids: tuple[str, ...]
    scope_path_prefixes: dict[str, tuple[str, ...]]
    scope_exact_paths: dict[str, tuple[str, ...]]
    profiles: dict[ProfileName, tuple[AccessClass, ...]]
    rules: tuple[OperationRule, ...]
    providers: dict[Literal["routed", "unrouted"], ProviderRule]
    specialists: dict[Literal["agents", "daytrade"], SpecialistRule]

    @model_validator(mode="after")
    def validate_policy_invariants(self) -> PolicyDocument:
        """Require complete profiles and deny admissions on excluded decisions."""
        expected = {"platform-standard", "portfolio-read", "portfolio-ops"}
        if set(self.profiles) != expected:
            raise ValueError("policy must define all three profiles")
        entries: list[OperationRule | ProviderRule | SpecialistRule] = [
            *self.rules,
            *self.providers.values(),
            *self.specialists.values(),
        ]
        if any(
            entry.disposition in {"restricted", "unimplemented"}
            and entry.admitted_profiles
            for entry in entries
        ):
            raise ValueError(
                "restricted and unimplemented policy entries cannot admit profiles"
            )
        return self


class ExposurePolicy:
    """Classify operations, provider registrations, and specialist surfaces."""

    def __init__(
        self,
        document: PolicyDocument,
        reviewed_operations: frozenset[tuple[str, str, str]],
    ):
        self.document = document
        self.reviewed_operations = reviewed_operations

    @classmethod
    def load(cls, path: Path | None = None) -> ExposurePolicy:
        """Load the committed reviewed policy asset."""
        policy_path = path or (
            Path(__file__).resolve().parents[1] / "assets" / "capability_policy.json"
        )
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
        document = PolicyDocument.model_validate(payload)
        catalog_path = policy_path.parent / document.operation_catalog.file
        normalized = catalog_path.read_bytes().replace(b"\r\n", b"\n")
        digest = hashlib.sha256(normalized).hexdigest()
        if digest != document.operation_catalog.sha256:
            raise ValueError("operation catalog hash does not match policy")
        with catalog_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        reviewed = frozenset(
            (row["scope"], row["method"].upper(), row["path"]) for row in rows
        )
        return cls(document, reviewed)

    def classify_operation(
        self, scope: str, method: str, path: str
    ) -> ExposureDecision:
        """Classify one audited operation or deny an unknown operation."""
        identity = (scope, method.upper(), path)
        if identity not in self.reviewed_operations:
            raise KeyError(f"Unknown operation: {scope} {method} {path}")
        matches = [
            rule for rule in self.document.rules if rule.matches(scope, method, path)
        ]
        if not matches:
            raise KeyError(f"Unknown operation: {scope} {method} {path}")
        priority = max(rule.priority for rule in matches)
        winners = [rule for rule in matches if rule.priority == priority]
        if len(winners) != 1:
            raise ValueError(
                f"Ambiguous policy rules at priority {priority}: "
                + ", ".join(sorted(rule.id for rule in winners))
            )
        rule = winners[0]
        return ExposureDecision(
            capability_id=f"operation:{scope}:{method.upper()}:{path}",
            rule_id=rule.id,
            disposition=rule.disposition,
            access_class=rule.access_class,
            admitted_profiles=rule.admitted_profiles,
            reason=rule.reason,
        )

    def classify_provider_model(self, row: ProviderModelMetadata) -> ExposureDecision:
        """Classify a provider/model registration by actual routing state."""
        routed = row.status == "routed" and row.provider_registered
        rule_name: Literal["routed", "unrouted"] = "routed" if routed else "unrouted"
        rule = self.document.providers[rule_name]
        return ExposureDecision(
            capability_id=f"provider:{row.provider}:{row.model}",
            rule_id=f"provider-{rule_name}",
            disposition=rule.disposition,
            access_class=rule.access_class,
            admitted_profiles=rule.admitted_profiles,
            reason=rule.reason,
        )

    def classify_specialist(
        self, surface: Literal["agents", "daytrade"], name: str
    ) -> ExposureDecision:
        """Classify one specialist MCP declaration."""
        rule = self.document.specialists[surface]
        return ExposureDecision(
            capability_id=f"specialist:{surface}:{name}",
            rule_id=f"specialist-{surface}",
            disposition=rule.disposition,
            access_class=rule.access_class,
            admitted_profiles=rule.admitted_profiles,
            reason=rule.reason,
        )

    def evaluate_exposure(
        self, record: CapabilityRecord, profile_name: ProfileName
    ) -> bool:
        """Return profile admission without replacing endpoint authorization."""
        if (
            record.disposition in {"restricted", "unimplemented"}
            or record.exclusion_reason
        ):
            return False
        if record.operation is None:
            return (
                record.disposition == "metadata_only"
                and record.access_class in self.document.profiles.get(profile_name, ())
                and record.id in self.document.reviewed_metadata_ids
            )
        scope = _scope_for_path(record.operation.path)
        if scope is None:
            return False
        try:
            decision = self.classify_operation(
                scope, record.operation.method, record.operation.path
            )
        except (KeyError, ValueError):
            return False
        return (
            decision.disposition in {"direct", "workspace_indirect", "metadata_only"}
            and profile_name in decision.admitted_profiles
            and decision.access_class in self.document.profiles.get(profile_name, ())
        )


def _scope_for_path(path: str) -> str | None:
    """Infer the audited scope from its stable path namespace."""
    if path.startswith("/api/v1/"):
        return "portfolio-venv-core-in-process"
    if path.startswith(("/pi/", "/tt/")) or path in {
        "/",
        "/widgets.json",
        "/apps.json",
    }:
        return "live-intelligence-custom"
    if path.startswith(("/portfolio/", "/espp/", "/equity/", "/market/", "/stock/")):
        return "live-portfolio-custom"
    return None


def evaluate_exposure(
    record: CapabilityRecord,
    profile_name: ProfileName,
    *,
    policy: ExposurePolicy | None = None,
) -> bool:
    """Evaluate exposure through the committed policy."""
    return (policy or _default_policy()).evaluate_exposure(record, profile_name)


@lru_cache(maxsize=1)
def _default_policy() -> ExposurePolicy:
    """Load and validate the default policy once per process."""
    return ExposurePolicy.load()


__all__ = [
    "ExposureDecision",
    "ExposurePolicy",
    "OperationRule",
    "PolicyDocument",
    "ProfileName",
    "evaluate_exposure",
]
