"""Deterministic Portfolio-base capability and prompt drift comparison."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openbb_mcp_server.models.capability import AccessClass, Disposition
from openbb_mcp_server.service.capability_inventory import InventoryDocument
from openbb_mcp_server.service.exposure_policy import ExposurePolicy

_APPROVED_DISPOSITIONS = {"direct", "workspace_indirect", "metadata_only"}
_DISPOSITION_EXPOSURE = {
    "unimplemented": 0,
    "restricted": 0,
    "metadata_only": 1,
    "workspace_indirect": 2,
    "direct": 3,
}
_ACCESS_SENSITIVITY = {
    "public_metadata": 0,
    "provider_read": 1,
    "private_portfolio_read": 2,
    "filesystem_write": 3,
    "cache_maintenance": 3,
    "job_control": 3,
    "workspace_mutation": 3,
    "financial_mutation": 3,
}
_ASSET_RELATIVE = Path("openbb_platform/extensions/mcp_server/openbb_mcp_server/assets")


class AccessGrant(BaseModel):
    """Effective policy grant and its accountable evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Disposition
    access_class: AccessClass
    admitted_profiles: tuple[str, ...]
    rule_id: str
    family: str
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    test_evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    implementation_evidence: dict[str, str]
    test_evidence: dict[str, str]
    baseline_implementation_evidence: dict[str, str]
    baseline_test_evidence: dict[str, str]
    evidence_complete: bool
    tests_verified: bool


class CoverageSnapshot(BaseModel):
    """Normalized drift-relevant facts from one source inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_name: str
    profile_alias_group: str
    api_prefix: str
    profile_config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    default_tool_categories: tuple[str, ...]
    enable_tool_discovery: bool
    approved_capabilities: tuple[str, ...]
    reviewed_policy_capabilities: tuple[str, ...]
    routed_models: tuple[str, ...]
    approved_tools: tuple[str, ...]
    unknown_capabilities: tuple[str, ...]
    duplicate_names: tuple[str, ...]
    stale_prompt_references: tuple[str, ...]
    access_grants: dict[str, AccessGrant]

    @model_validator(mode="after")
    def require_sorted_unique_sequences(self) -> CoverageSnapshot:
        """Keep comparisons deterministic and duplicate-free."""
        for field_name in (
            "approved_capabilities",
            "reviewed_policy_capabilities",
            "routed_models",
            "approved_tools",
            "unknown_capabilities",
            "duplicate_names",
            "stale_prompt_references",
        ):
            values = getattr(self, field_name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field_name} must be sorted and unique")
        return self


class CoverageDiff(BaseModel):
    """Sanitized blocking and additive drift report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    profile_name: str
    blocking: bool
    blocking_reasons: tuple[str, ...]
    profile_mismatch: tuple[str, ...]
    lost_capabilities: tuple[str, ...]
    lost_models: tuple[str, ...]
    lost_tools: tuple[str, ...]
    unknown_capabilities: tuple[str, ...]
    duplicate_names: tuple[str, ...]
    stale_prompt_references: tuple[str, ...]
    unreviewed_widening: tuple[str, ...]
    unevidenced_additions: tuple[str, ...]
    reviewed_additions: tuple[str, ...]


def _digest(value: object) -> str:
    """Return a stable digest for JSON-compatible reviewed evidence."""
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _policy_assets(repository: Path) -> tuple[ExposurePolicy, Path]:
    assets = repository / _ASSET_RELATIVE
    return ExposurePolicy.load(assets / "capability_policy.json"), assets


def _family_evidence(
    policy: ExposurePolicy,
    rule_id: str,
    repository: Path,
    baseline_repository: Path,
) -> tuple[
    str,
    str,
    str,
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    bool,
]:
    """Return owning family, implementation/test digests, and completeness."""
    traceability = policy.document.traceability
    family_name = traceability.rule_owners.get(rule_id, "unowned")
    family = traceability.work_families.get(family_name)
    if family is None:
        fallback = _digest({"rule_id": rule_id})
        return family_name, fallback, fallback, {}, {}, {}, {}, False
    implementation_evidence = {}
    test_evidence = {}
    baseline_implementation_evidence = {}
    baseline_test_evidence = {}
    complete = True
    implementation_files = 0
    test_files = 0
    for source_ref in family.source_evidence:
        source = repository / source_ref
        source_is_test = (
            "/tests/" in f"/{source_ref}"
            or source_ref.startswith("tests/")
            or source_ref.endswith("/tests")
        )
        if not source.exists():
            complete = False
            continue
        files = (
            [source]
            if source.is_file()
            else [
                path
                for path in sorted(source.rglob("*"))
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            ]
        )
        if not files:
            complete = False
        for path in files:
            relative = path.relative_to(repository).as_posix()
            nested_test = "/tests/" in f"/{relative}" or relative.startswith("tests/")
            if nested_test and not source_is_test:
                continue
            is_test = source_is_test
            content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if is_test:
                test_evidence[relative] = content_digest
                test_files += 1
            else:
                implementation_evidence[relative] = content_digest
                implementation_files += 1
            baseline_path = baseline_repository / relative
            if baseline_path.is_file():
                baseline_digest = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
                if is_test:
                    baseline_test_evidence[relative] = baseline_digest
                else:
                    baseline_implementation_evidence[relative] = baseline_digest
    complete = complete and implementation_files > 0 and test_files > 0
    return (
        family_name,
        _digest(implementation_evidence),
        _digest(test_evidence),
        dict(sorted(implementation_evidence.items())),
        dict(sorted(test_evidence.items())),
        dict(sorted(baseline_implementation_evidence.items())),
        dict(sorted(baseline_test_evidence.items())),
        complete,
    )


def _grant(
    policy: ExposurePolicy,
    decision,
    repository: Path,
    *,
    tests_verified: bool,
    baseline_repository: Path,
) -> AccessGrant:
    (
        family,
        evidence_digest,
        test_evidence_digest,
        implementation_evidence,
        test_evidence,
        baseline_implementation_evidence,
        baseline_test_evidence,
        evidence_complete,
    ) = _family_evidence(
        policy,
        decision.rule_id,
        repository,
        baseline_repository,
    )
    return AccessGrant(
        disposition=decision.disposition,
        access_class=decision.access_class,
        admitted_profiles=decision.admitted_profiles,
        rule_id=decision.rule_id,
        family=family,
        evidence_digest=evidence_digest,
        test_evidence_digest=test_evidence_digest,
        implementation_evidence=implementation_evidence,
        test_evidence=test_evidence,
        baseline_implementation_evidence=baseline_implementation_evidence,
        baseline_test_evidence=baseline_test_evidence,
        evidence_complete=evidence_complete,
        tests_verified=tests_verified,
    )


def _prompt_grant(
    repository: Path,
    baseline_repository: Path,
    *,
    tests_verified: bool,
) -> AccessGrant:
    """Return explicit manifest and regression evidence for bundled prompts."""
    implementation_path = (_ASSET_RELATIVE / "server_prompts.json").as_posix()
    test_path = (
        Path("openbb_platform/extensions/mcp_server/tests/app")
        / "test_prompt_dependencies.py"
    ).as_posix()

    def evidence(path: str, root: Path) -> dict[str, str]:
        source = root / path
        return (
            {path: hashlib.sha256(source.read_bytes()).hexdigest()}
            if source.is_file()
            else {}
        )

    implementation_evidence = evidence(implementation_path, repository)
    test_evidence = evidence(test_path, repository)
    baseline_implementation = evidence(
        implementation_path,
        baseline_repository,
    )
    baseline_tests = evidence(test_path, baseline_repository)
    return AccessGrant(
        disposition="metadata_only",
        access_class="public_metadata",
        admitted_profiles=(
            "platform-standard",
            "portfolio-read",
            "portfolio-ops",
        ),
        rule_id="prompt-catalog",
        family="prompt-catalog",
        evidence_digest=_digest(implementation_evidence),
        test_evidence_digest=_digest(test_evidence),
        implementation_evidence=implementation_evidence,
        test_evidence=test_evidence,
        baseline_implementation_evidence=baseline_implementation,
        baseline_test_evidence=baseline_tests,
        evidence_complete=bool(implementation_evidence and test_evidence),
        tests_verified=tests_verified,
    )


def _prompt_references(
    prompts: list[dict],
    known_tools: set[str],
) -> set[str]:
    """Return unresolved structured tool dependencies."""
    stale = set()
    for prompt in prompts:
        name = str(prompt.get("name") or "unnamed_prompt")
        dependencies = prompt.get("dependencies") or {}
        for tool in dependencies.get("required_tools", ()):
            if tool not in known_tools:
                stale.add(f"{name}:{tool}")
        for group in dependencies.get("any_tool_groups", ()):
            if not set(group) & known_tools:
                stale.add(f"{name}:any({','.join(sorted(group))})")
    return stale


def build_coverage_snapshot(
    document: InventoryDocument,
    *,
    repository: Path,
    tests_verified: bool = False,
    evidence_baseline_repository: Path | None = None,
) -> CoverageSnapshot:
    """Normalize one inventory against its checkout-local policy and prompts."""
    baseline_repository = evidence_baseline_repository or repository
    policy, assets = _policy_assets(repository)
    approved = set()
    reviewed_policy = set()
    tools = set()
    unknown = set()
    grants: dict[str, AccessGrant] = {}

    catalog_path = assets / policy.document.operation_catalog.file
    with catalog_path.open(encoding="utf-8", newline="") as stream:
        operation_rows = list(csv.DictReader(stream))
    for row in operation_rows:
        decision = policy.classify_operation(
            row["scope"],
            row["method"],
            row["path"],
        )
        capability_id = decision.capability_id
        grants[capability_id] = _grant(
            policy,
            decision,
            repository,
            tests_verified=tests_verified,
            baseline_repository=baseline_repository,
        )
        if decision.disposition in _APPROVED_DISPOSITIONS:
            reviewed_policy.add(capability_id)

    for surface, names in policy.document.traceability.reviewed_specialists.items():
        for name in names:
            decision = policy.classify_specialist(surface, name)
            if decision.disposition in _APPROVED_DISPOSITIONS:
                reviewed_policy.add(decision.capability_id)

    for record in document.capabilities.records:
        if record.operation is None:
            continue
        try:
            decision = policy.classify_path(
                record.operation.method,
                record.operation.path,
            )
        except (KeyError, ValueError):
            if record.exclusion_reason is None:
                unknown.add(
                    "operation:" f"{record.operation.method}:{record.operation.path}"
                )
            continue
        grants.setdefault(
            decision.capability_id,
            _grant(
                policy,
                decision,
                repository,
                tests_verified=tests_verified,
                baseline_repository=baseline_repository,
            ),
        )
        if decision.disposition in _APPROVED_DISPOSITIONS:
            approved.add(decision.capability_id)
            if record.tool_name:
                tools.add(record.tool_name)

    for record in document.capabilities.records:
        if record.surface not in {"agents", "daytrade"} or not record.tool_name:
            continue
        capability_id = f"specialist:{record.surface}:{record.tool_name}"
        reviewed = policy.document.traceability.reviewed_specialists.get(
            record.surface,
            (),
        )
        if record.tool_name not in reviewed:
            unknown.add(capability_id)
            continue
        decision = policy.classify_specialist(
            record.surface,
            record.tool_name,
        )
        grants[decision.capability_id] = _grant(
            policy,
            decision,
            repository,
            tests_verified=tests_verified,
            baseline_repository=baseline_repository,
        )
        if decision.disposition in _APPROVED_DISPOSITIONS:
            approved.add(decision.capability_id)
            tools.add(record.tool_name)

    prompts_path = assets / "server_prompts.json"
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    prompt_grant = _prompt_grant(
        repository,
        baseline_repository,
        tests_verified=tests_verified,
    )
    for prompt in prompts:
        capability_id = f"prompt:{prompt['name']}"
        approved.add(capability_id)
        grants[capability_id] = prompt_grant

    routed_models = {
        f"{row.provider}:{row.model}"
        for row in document.provider_models
        if row.status == "routed" and row.provider_registered
    }
    stale = _prompt_references(prompts, tools)
    duplicates = {
        f"{collision.kind}:{collision.key}" for collision in document.collisions
    }
    return CoverageSnapshot(
        profile_name=document.profile.selected_name,
        profile_alias_group=document.profile.alias_group,
        api_prefix=document.profile.api_prefix,
        profile_config_fingerprint=document.profile.config_fingerprint,
        default_tool_categories=document.profile.default_tool_categories,
        enable_tool_discovery=document.profile.enable_tool_discovery,
        approved_capabilities=tuple(sorted(approved)),
        reviewed_policy_capabilities=tuple(sorted(reviewed_policy)),
        routed_models=tuple(sorted(routed_models)),
        approved_tools=tuple(sorted(tools)),
        unknown_capabilities=tuple(sorted(unknown)),
        duplicate_names=tuple(sorted(duplicates)),
        stale_prompt_references=tuple(sorted(stale)),
        access_grants=dict(sorted(grants.items())),
    )


def _is_wider(base: AccessGrant, head: AccessGrant) -> bool:
    """Return whether the head grant exposes an existing capability more broadly."""
    return (
        _DISPOSITION_EXPOSURE[head.disposition]
        > _DISPOSITION_EXPOSURE[base.disposition]
        or bool(set(head.admitted_profiles) - set(base.admitted_profiles))
        or _ACCESS_SENSITIVITY[head.access_class]
        > _ACCESS_SENSITIVITY[base.access_class]
    )


def _mapped_content_changed(
    head: AccessGrant,
) -> bool:
    """Require changed contents at continuous implementation and test paths."""
    implementation_changed = any(
        path in head.baseline_implementation_evidence
        and digest != head.baseline_implementation_evidence[path]
        for path, digest in head.implementation_evidence.items()
    )
    tests_changed = any(
        path in head.baseline_test_evidence
        and digest != head.baseline_test_evidence[path]
        for path, digest in head.test_evidence.items()
    )
    return implementation_changed and tests_changed


def compare_snapshots(
    base: CoverageSnapshot,
    head: CoverageSnapshot,
) -> CoverageDiff:
    """Compare normalized base/head snapshots without freezing additive counts."""
    profile_mismatch = []
    for field_name in (
        "profile_name",
        "profile_alias_group",
        "api_prefix",
        "profile_config_fingerprint",
        "default_tool_categories",
        "enable_tool_discovery",
    ):
        base_value = getattr(base, field_name)
        head_value = getattr(head, field_name)
        if base_value != head_value:
            profile_mismatch.append(f"{field_name}:{base_value}!={head_value}")

    base_capabilities = set(base.approved_capabilities)
    head_capabilities = set(head.approved_capabilities)
    base_policy_capabilities = set(base.reviewed_policy_capabilities)
    head_policy_capabilities = set(head.reviewed_policy_capabilities)
    additions = (head_capabilities - base_capabilities) | (
        head_policy_capabilities - base_policy_capabilities
    )
    policy_bootstrap_additions = {
        capability_id
        for capability_id in additions
        if capability_id in base_policy_capabilities
        and capability_id in head_policy_capabilities
    }
    unevidenced_additions = {
        capability_id
        for capability_id in additions - policy_bootstrap_additions
        if capability_id not in head.access_grants
        or (
            not head.access_grants[capability_id].evidence_complete
            or not head.access_grants[capability_id].tests_verified
            or not _mapped_content_changed(head.access_grants[capability_id])
        )
    }
    unreviewed_widening = set()
    for capability_id in set(base.access_grants) & set(head.access_grants):
        base_grant = base.access_grants[capability_id]
        head_grant = head.access_grants[capability_id]
        if _is_wider(base_grant, head_grant) and (
            not head_grant.evidence_complete
            or not head_grant.tests_verified
            or not _mapped_content_changed(head_grant)
        ):
            unreviewed_widening.add(capability_id)

    newly_stale = set(head.stale_prompt_references) - set(base.stale_prompt_references)
    sections = {
        "profile_mismatch": set(profile_mismatch),
        "lost_capabilities": (base_capabilities - head_capabilities)
        | (base_policy_capabilities - head_policy_capabilities),
        "lost_models": set(base.routed_models) - set(head.routed_models),
        "lost_tools": set(base.approved_tools) - set(head.approved_tools),
        "unknown_capabilities": set(head.unknown_capabilities)
        - set(base.unknown_capabilities),
        "duplicate_names": set(head.duplicate_names),
        "stale_prompt_references": newly_stale,
        "unreviewed_widening": unreviewed_widening,
        "unevidenced_additions": unevidenced_additions,
    }
    blocking_reasons = tuple(name for name, values in sections.items() if values)
    return CoverageDiff(
        profile_name=head.profile_name,
        blocking=bool(blocking_reasons),
        blocking_reasons=blocking_reasons,
        **{name: tuple(sorted(values)) for name, values in sections.items()},
        reviewed_additions=tuple(
            sorted(additions - unevidenced_additions | policy_bootstrap_additions)
        ),
    )


def compare_repository_coverage(
    base: InventoryDocument,
    head: InventoryDocument,
    *,
    base_repository: Path,
    head_repository: Path,
    head_tests_verified: bool = False,
) -> CoverageDiff:
    """Build checkout-local snapshots and compare them."""
    return compare_snapshots(
        build_coverage_snapshot(base, repository=base_repository),
        build_coverage_snapshot(
            head,
            repository=head_repository,
            tests_verified=head_tests_verified,
            evidence_baseline_repository=base_repository,
        ),
    )


__all__ = [
    "AccessGrant",
    "CoverageDiff",
    "CoverageSnapshot",
    "build_coverage_snapshot",
    "compare_repository_coverage",
    "compare_snapshots",
]
