"""Portfolio-based MCP capability and prompt drift contracts."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from openbb_mcp_server.service.capability_inventory import (
    InventoryDocument,
)
from openbb_mcp_server.service.coverage_diff import (
    AccessGrant,
    CoverageSnapshot,
    _family_evidence,
    compare_repository_coverage,
    compare_snapshots,
)
from openbb_mcp_server.service.exposure_policy import ExposurePolicy


def _snapshot(**changes) -> CoverageSnapshot:
    values = {
        "profile_name": "portfolio-read",
        "profile_alias_group": "portfolio",
        "api_prefix": "/api/v1",
        "profile_config_fingerprint": "f" * 64,
        "default_tool_categories": ("equity", "portfolio"),
        "enable_tool_discovery": True,
        "approved_capabilities": ("operation:GET:/api/v1/equity/price/quote",),
        "reviewed_policy_capabilities": ("operation:GET:/api/v1/equity/price/quote",),
        "routed_models": ("fmp_cached:EquityQuote",),
        "approved_tools": ("equity_price_quote",),
        "unknown_capabilities": (),
        "duplicate_names": (),
        "stale_prompt_references": (),
        "access_grants": {
            "operation:GET:/api/v1/equity/price/quote": AccessGrant(
                disposition="direct",
                access_class="provider_read",
                admitted_profiles=("platform-standard", "portfolio-read"),
                rule_id="core-provider-and-compute",
                family="fmp-routing-waves",
                evidence_digest="a" * 64,
                test_evidence_digest="a" * 64,
                implementation_evidence={"src/router.py": "a" * 64},
                test_evidence={"tests/test_router.py": "a" * 64},
                baseline_implementation_evidence={"src/router.py": "a" * 64},
                baseline_test_evidence={"tests/test_router.py": "a" * 64},
                evidence_complete=True,
                tests_verified=True,
            )
        },
    }
    values.update(changes)
    return CoverageSnapshot.model_validate(values)


def test_missing_approved_route_model_and_tool_are_blocking():
    """Approved base identities cannot disappear behind changed denominators."""
    report = compare_snapshots(
        _snapshot(),
        _snapshot(
            approved_capabilities=(),
            routed_models=(),
            approved_tools=(),
            access_grants={},
        ),
    )

    assert report.blocking
    assert report.lost_capabilities == ("operation:GET:/api/v1/equity/price/quote",)
    assert report.lost_models == ("fmp_cached:EquityQuote",)
    assert report.lost_tools == ("equity_price_quote",)


def test_unknown_duplicate_and_stale_prompt_reference_are_blocking():
    """Unowned additions and invalid prompt dependencies fail together."""
    report = compare_snapshots(
        _snapshot(),
        _snapshot(
            unknown_capabilities=("operation:GET:/api/v1/new/route",),
            duplicate_names=("tool_name:equity_price_quote",),
            stale_prompt_references=("deep_dive:missing_tool",),
        ),
    )

    assert report.blocking
    assert report.unknown_capabilities == ("operation:GET:/api/v1/new/route",)
    assert report.duplicate_names == ("tool_name:equity_price_quote",)
    assert report.stale_prompt_references == ("deep_dive:missing_tool",)


def test_prompt_addition_without_manifest_and_test_evidence_is_blocking():
    """Prompt names cannot bypass the evidence gate."""
    prompt_id = "prompt:new_prompt"
    base = _snapshot()
    report = compare_snapshots(
        base,
        _snapshot(
            approved_capabilities=tuple(
                sorted((*base.approved_capabilities, prompt_id))
            )
        ),
    )

    assert report.blocking
    assert report.unevidenced_additions == (prompt_id,)


def test_reviewed_addition_with_evidence_is_not_count_frozen():
    """Exact policy-owned additions pass without rewriting old denominators."""
    addition = "operation:GET:/api/v1/equity/price/new"
    grants = {
        **_snapshot().access_grants,
        addition: AccessGrant(
            disposition="direct",
            access_class="provider_read",
            admitted_profiles=("portfolio-read",),
            rule_id="core-provider-and-compute",
            family="fmp-routing-waves",
            evidence_digest="b" * 64,
            test_evidence_digest="b" * 64,
            implementation_evidence={"src/router.py": "b" * 64},
            test_evidence={"tests/test_router.py": "b" * 64},
            baseline_implementation_evidence={"src/router.py": "a" * 64},
            baseline_test_evidence={"tests/test_router.py": "a" * 64},
            evidence_complete=True,
            tests_verified=True,
        ),
    }
    report = compare_snapshots(
        _snapshot(),
        _snapshot(
            approved_capabilities=tuple(
                sorted(
                    (
                        "operation:GET:/api/v1/equity/price/quote",
                        addition,
                    )
                )
            ),
            approved_tools=tuple(sorted(("equity_price_quote", "equity_price_new"))),
            access_grants=grants,
        ),
    )

    assert not report.blocking
    assert report.reviewed_additions == (addition,)
    assert report.unevidenced_additions == ()


def test_previously_reviewed_policy_identity_can_bootstrap_enumeration():
    """Improved source discovery may reveal an already-reviewed capability."""
    capability_id = "operation:GET:/api/v1/equity/price/quote"
    base = _snapshot(
        approved_capabilities=(),
        approved_tools=(),
    )
    head = _snapshot()

    report = compare_snapshots(base, head)

    assert not report.blocking
    assert report.reviewed_additions == (capability_id,)


def test_addition_in_existing_family_requires_updated_evidence():
    """A catalog entry alone is not evidence for a new implementation."""
    addition = "operation:GET:/api/v1/equity/price/new"
    grants = {
        **_snapshot().access_grants,
        addition: AccessGrant(
            disposition="direct",
            access_class="provider_read",
            admitted_profiles=("portfolio-read",),
            rule_id="core-provider-and-compute",
            family="fmp-routing-waves",
            evidence_digest="a" * 64,
            test_evidence_digest="a" * 64,
            implementation_evidence={"src/router.py": "a" * 64},
            test_evidence={"tests/test_router.py": "a" * 64},
            baseline_implementation_evidence={"src/router.py": "a" * 64},
            baseline_test_evidence={"tests/test_router.py": "a" * 64},
            evidence_complete=True,
            tests_verified=True,
        ),
    }
    report = compare_snapshots(
        _snapshot(),
        _snapshot(
            approved_capabilities=tuple(
                sorted(
                    (
                        "operation:GET:/api/v1/equity/price/quote",
                        addition,
                    )
                )
            ),
            access_grants=grants,
        ),
    )

    assert report.blocking
    assert report.unevidenced_additions == (addition,)


@pytest.mark.parametrize(
    "evidence_update",
    [
        {
            "evidence_digest": "b" * 64,
            "implementation_evidence": {"src/router.py": "b" * 64},
        },
        {
            "test_evidence_digest": "b" * 64,
            "test_evidence": {"tests/test_router.py": "b" * 64},
        },
        {
            "evidence_digest": "b" * 64,
            "test_evidence_digest": "b" * 64,
            "implementation_evidence": {"src/unrelated.py": "b" * 64},
            "test_evidence": {"tests/test_unrelated.py": "b" * 64},
            "baseline_implementation_evidence": {},
            "baseline_test_evidence": {},
        },
    ],
)
def test_one_sided_or_remapped_evidence_cannot_approve_addition(
    evidence_update,
):
    """Both corresponding implementation and test contents must change."""
    addition = "operation:GET:/api/v1/equity/price/new"
    base = _snapshot()
    grant = base.access_grants["operation:GET:/api/v1/equity/price/quote"].model_copy(
        update={
            "admitted_profiles": ("portfolio-read",),
            **evidence_update,
        }
    )
    report = compare_snapshots(
        base,
        _snapshot(
            approved_capabilities=tuple(
                sorted((*base.approved_capabilities, addition))
            ),
            access_grants={
                **base.access_grants,
                addition: grant,
            },
        ),
    )

    assert report.blocking
    assert report.unevidenced_additions == (addition,)


def test_widened_access_requires_changed_complete_evidence():
    """A policy edit alone cannot silently broaden an existing operation."""
    widened = AccessGrant(
        disposition="direct",
        access_class="provider_read",
        admitted_profiles=(
            "platform-standard",
            "portfolio-read",
            "portfolio-ops",
        ),
        rule_id="core-provider-and-compute",
        family="fmp-routing-waves",
        evidence_digest="a" * 64,
        test_evidence_digest="a" * 64,
        implementation_evidence={"src/router.py": "a" * 64},
        test_evidence={"tests/test_router.py": "a" * 64},
        baseline_implementation_evidence={"src/router.py": "a" * 64},
        baseline_test_evidence={"tests/test_router.py": "a" * 64},
        evidence_complete=True,
        tests_verified=True,
    )
    unsupported = compare_snapshots(
        _snapshot(),
        _snapshot(access_grants={"operation:GET:/api/v1/equity/price/quote": widened}),
    )
    assert unsupported.blocking
    assert unsupported.unreviewed_widening == (
        "operation:GET:/api/v1/equity/price/quote",
    )

    reviewed = compare_snapshots(
        _snapshot(),
        _snapshot(
            access_grants={
                "operation:GET:/api/v1/equity/price/quote": widened.model_copy(
                    update={
                        "evidence_digest": "c" * 64,
                        "test_evidence_digest": "c" * 64,
                        "implementation_evidence": {"src/router.py": "c" * 64},
                        "test_evidence": {"tests/test_router.py": "c" * 64},
                    }
                )
            }
        ),
    )
    assert not reviewed.blocking
    assert reviewed.unreviewed_widening == ()


@pytest.mark.parametrize(
    ("base_changes", "head_changes"),
    [
        (
            {"disposition": "workspace_indirect"},
            {"disposition": "direct"},
        ),
        (
            {"access_class": "provider_read"},
            {"access_class": "financial_mutation"},
        ),
        (
            {"access_class": "provider_read"},
            {"access_class": "private_portfolio_read"},
        ),
    ],
)
def test_directness_and_mutation_transitions_are_widening(
    base_changes,
    head_changes,
):
    """Direct exposure and mutation classes require changed evidence."""
    capability_id = "operation:GET:/api/v1/equity/price/quote"
    original = _snapshot().access_grants[capability_id]
    base = _snapshot(
        access_grants={capability_id: original.model_copy(update=base_changes)}
    )
    head = _snapshot(
        access_grants={capability_id: original.model_copy(update=head_changes)}
    )

    report = compare_snapshots(base, head)

    assert report.blocking
    assert report.unreviewed_widening == (capability_id,)


def test_replacing_one_admitted_profile_is_widening():
    """A newly admitted profile cannot hide behind a simultaneous removal."""
    capability_id = "operation:GET:/api/v1/equity/price/quote"
    base = _snapshot()
    original = base.access_grants[capability_id]
    head = _snapshot(
        access_grants={
            capability_id: original.model_copy(
                update={
                    "admitted_profiles": (
                        "platform-standard",
                        "portfolio-ops",
                    )
                }
            )
        }
    )

    report = compare_snapshots(base, head)

    assert report.blocking
    assert report.unreviewed_widening == (capability_id,)


def test_policy_prose_cannot_change_source_evidence_digest():
    """Self-authored rationale edits are not implementation evidence."""
    repo_root = Path(__file__).resolve().parents[5]
    policy = ExposurePolicy.load()
    family_name = "fmp-routing-waves"
    family = policy.document.traceability.work_families[family_name]
    changed_family = family.model_copy(
        update={"rationale": "Different policy prose without source changes."}
    )
    changed_families = {
        **policy.document.traceability.work_families,
        family_name: changed_family,
    }
    changed_traceability = policy.document.traceability.model_copy(
        update={"work_families": changed_families}
    )
    changed_policy = ExposurePolicy(
        policy.document.model_copy(update={"traceability": changed_traceability}),
        policy.reviewed_operations,
    )

    original = _family_evidence(
        policy,
        "core-provider-and-compute",
        repo_root,
        repo_root,
    )
    changed = _family_evidence(
        changed_policy,
        "core-provider-and-compute",
        repo_root,
        repo_root,
    )

    assert original == changed


def test_profile_configuration_must_remain_compatible():
    """Base/head inventories cannot compare unrelated profile aliases."""
    report = compare_snapshots(
        _snapshot(),
        _snapshot(profile_config_fingerprint="e" * 64),
    )

    assert report.blocking
    assert report.profile_mismatch == (
        f"profile_config_fingerprint:{'f' * 64}!={'e' * 64}",
    )


def test_current_repository_inventory_and_prompts_have_no_self_drift(
    tmp_path,
):
    """The real Portfolio inventory, policy, and prompt manifest reconcile."""
    repo_root = Path(__file__).resolve().parents[5]
    output_dir = tmp_path / "portfolio-read"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(repo_root / "scripts" / "audit_mcp_capabilities.py"),
            "--profile",
            "portfolio-read",
            "--output-dir",
            str(output_dir),
            "--metadata-only",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    document = InventoryDocument.model_validate_json(
        (output_dir / "inventory.json").read_text(encoding="utf-8")
    )

    report = compare_repository_coverage(
        document,
        document,
        base_repository=repo_root,
        head_repository=repo_root,
    )

    assert not report.blocking, json.dumps(report.model_dump(mode="json"), indent=2)
    assert report.lost_capabilities == ()
    assert report.stale_prompt_references == ()

    policy = ExposurePolicy.load()
    candidate = None
    for record in document.capabilities.records:
        if not record.operation or not record.tool_name:
            continue
        try:
            decision = policy.classify_path(
                record.operation.method,
                record.operation.path,
            )
        except (KeyError, ValueError):
            continue
        if decision.disposition in {
            "direct",
            "workspace_indirect",
            "metadata_only",
        }:
            candidate = (record.operation, decision.capability_id)
            break
    assert candidate is not None
    operation, capability_id = candidate
    retained_records = tuple(
        record
        for record in document.capabilities.records
        if not (
            record.operation
            and record.operation.method == operation.method
            and record.operation.path == operation.path
        )
    )
    missing_route = document.model_copy(
        update={
            "capabilities": document.capabilities.model_copy(
                update={"records": retained_records}
            )
        }
    )
    missing_report = compare_repository_coverage(
        document,
        missing_route,
        base_repository=repo_root,
        head_repository=repo_root,
    )
    assert missing_report.blocking
    assert capability_id in missing_report.lost_capabilities


def test_ops_inventory_source_enumerates_jobs_and_specialists(tmp_path):
    """Operator and separate stdio surfaces cannot exist only in policy prose."""
    repo_root = Path(__file__).resolve().parents[5]
    output_dir = tmp_path / "portfolio-ops"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(repo_root / "scripts" / "audit_mcp_capabilities.py"),
            "--profile",
            "portfolio-ops",
            "--output-dir",
            str(output_dir),
            "--metadata-only",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    document = InventoryDocument.model_validate_json(
        (output_dir / "inventory.json").read_text(encoding="utf-8")
    )
    route_paths = {
        record.operation.path
        for record in document.capabilities.records
        if record.operation
    }
    specialist_tools = {
        surface: {
            item.tool_name
            for item in document.capabilities.records
            if item.surface == surface and item.tool_name
        }
        for surface in ("agents", "daytrade")
    }

    assert {
        "/api/v1/cache/jobs/definitions",
        "/api/v1/cache/jobs/health",
        "/api/v1/cache/jobs/runs/{run_id}",
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        "/api/v1/cache/jobs/portfolio.etf_holdings/trigger",
    } <= route_paths
    assert specialist_tools == {
        "agents": {"get_positions", "get_sector_exposure"},
        "daytrade": {
            "quote_batch",
            "market_movers",
            "company_news",
            "session_status",
            "journal_summary",
            "fills_for_session",
        },
    }
