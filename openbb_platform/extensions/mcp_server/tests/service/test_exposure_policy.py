"""Reviewed capability exposure policy tests."""

import csv
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from openbb_mcp_server.models.capability import (
    CapabilityRecord,
    OperationKey,
    VerificationState,
)
from openbb_mcp_server.service.capability_inventory import ProviderModelMetadata
from openbb_mcp_server.service.exposure_policy import ExposurePolicy

FIXTURES = Path(__file__).parents[1] / "fixtures" / "capability_audit"


@pytest.fixture
def policy() -> ExposurePolicy:
    """Load the committed reviewed policy."""
    return ExposurePolicy.load()


def audited_operations() -> list[dict[str, str]]:
    """Load the immutable 317-row operation denominator."""
    with (FIXTURES / "mcp-api-inventory.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        return list(csv.DictReader(stream))


def capability(path: str, method: str = "GET") -> CapabilityRecord:
    """Build one synthetic route capability for admission tests."""
    return CapabilityRecord(
        id=f"platform:test:{method.lower()}:{path.strip('/').replace('/', '-')}",
        surface="platform",
        owner_lane="D-Widgets+QA",
        source_refs=("tests/synthetic.py",),
        implementation_id="python:synthetic",
        operation=OperationKey(method=method, path=path),
        tool_name="synthetic_tool",
        disposition="direct",
        access_class="provider_read",
        persistence="unverified",
        requirements=(),
        verification=VerificationState(schema=True),
    )


def test_all_317_audited_operations_classify_exactly_once(policy):
    """The reviewed gross operation denominator has zero unknown rows."""
    rows = audited_operations()
    decisions = [
        policy.classify_operation(row["scope"], row["method"], row["path"])
        for row in rows
    ]
    assert len(decisions) == len(rows) == 317
    assert all(decision.rule_id for decision in decisions)
    assert not any(
        decision.rule_id.startswith("deny-unreviewed") for decision in decisions
    )
    assert Counter(decision.disposition for decision in decisions) == {
        "direct": 214,
        "workspace_indirect": 62,
        "metadata_only": 6,
        "restricted": 35,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/backtest/run",
        "/api/v1/derivatives/options/surface",
        "/api/v1/portfolio_intel/risk/metrics",
    ],
)
def test_post_compute_and_text_operations_are_provider_reads(policy, path):
    """Transport POST is not treated as a financial side effect."""
    decision = policy.classify_operation("portfolio-venv-core-in-process", "POST", path)
    assert decision.access_class == "provider_read"
    assert decision.disposition == "direct"


@pytest.mark.parametrize(
    "path",
    ["/tt/execute/approve-plan", "/tt/execute/cancel"],
)
def test_execution_actions_are_denied_in_every_profile(policy, path):
    """Execution-like actions require a later sandbox and approval contract."""
    decision = policy.classify_operation("live-intelligence-custom", "POST", path)
    assert decision.access_class == "financial_mutation"
    assert decision.disposition == "restricted"
    assert decision.admitted_profiles == ()
    assert decision.reason


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/uscongress/bill_text", "POST"),
        ("/api/v1/uscongress/amendment_text", "POST"),
        ("/api/v1/uscongress/bill_text_urls", "GET"),
        ("/api/v1/uscongress/bill_info", "GET"),
        ("/api/v1/uscongress/amendment_text_urls", "GET"),
        ("/api/v1/uscongress/amendment_info", "GET"),
        ("/api/v1/commodity/weather_bulletins_download", "POST"),
        ("/api/v1/regulators/sec/htm_file", "GET"),
    ],
)
def test_unhardened_url_fetches_are_denied(policy, path, method):
    """Caller-controlled URL fetches stay unavailable until SSRF hardening."""
    decision = policy.classify_operation("portfolio-venv-core-in-process", method, path)
    assert decision.disposition == "restricted"
    assert decision.admitted_profiles == ()
    assert "SSRF" in (decision.reason or "")


def test_bundle_ingest_requires_ops_filesystem_access(policy):
    """Persisted backtest bundles are not exposed as standard provider reads."""
    record = capability("/api/v1/backtest/bundle/ingest", "POST")
    assert not policy.evaluate_exposure(record, "platform-standard")
    assert not policy.evaluate_exposure(record, "portfolio-read")
    assert policy.evaluate_exposure(record, "portfolio-ops")


def test_operator_only_entries_cannot_leak_into_portfolio_read(policy):
    """Filesystem and job-control access is admitted only to ops."""
    export = capability("/api/v1/techtrade/export", "POST")
    trigger = capability("/tt/scan/trigger", "POST")
    assert policy.evaluate_exposure(export, "portfolio-ops")
    assert not policy.evaluate_exposure(export, "portfolio-read")
    assert policy.evaluate_exposure(trigger, "portfolio-ops")
    assert not policy.evaluate_exposure(trigger, "portfolio-read")


def test_private_reads_require_portfolio_profile(policy):
    """Private book/lookthrough data does not enter the standard profile."""
    record = capability("/pi/context/book")
    assert not policy.evaluate_exposure(record, "platform-standard")
    assert policy.evaluate_exposure(record, "portfolio-read")
    assert policy.evaluate_exposure(record, "portfolio-ops")


def test_custom_portfolio_routes_remain_restricted_until_adapter(policy):
    """Composed custom routes retain privilege class and reviewed restriction."""
    decision = policy.classify_operation(
        "live-portfolio-custom", "GET", "/portfolio/positions"
    )
    assert decision.disposition == "restricted"
    assert decision.access_class == "private_portfolio_read"
    assert decision.reason


def test_unknown_operation_and_capability_are_denied(policy):
    """Unknown routes never inherit a broad profile default."""
    with pytest.raises(KeyError):
        policy.classify_operation("unknown", "GET", "/unknown")
    assert not policy.evaluate_exposure(capability("/unknown"), "portfolio-ops")
    core_unknown = capability("/api/v1/new_category/future")
    intelligence_unknown = capability("/tt/future/action")
    with pytest.raises(KeyError):
        policy.classify_operation(
            "portfolio-venv-core-in-process",
            "DELETE",
            "/api/v1/equity/order",
        )
    with pytest.raises(KeyError):
        policy.classify_operation(
            "live-intelligence-custom",
            "POST",
            "/tt/scan/arbitrary-financial-mutation",
        )
    assert not policy.evaluate_exposure(core_unknown, "platform-standard")
    assert not policy.evaluate_exposure(intelligence_unknown, "platform-standard")


def test_route_level_restriction_is_an_unconditional_deny(policy):
    """Policy classification cannot override expose=false/module exclusion."""
    restricted = capability("/api/v1/equity/price/historical").model_copy(
        update={
            "disposition": "restricted",
            "exclusion_reason": "Route declares expose=false.",
        }
    )
    assert not policy.evaluate_exposure(restricted, "platform-standard")
    assert not policy.evaluate_exposure(restricted, "portfolio-ops")


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/tt/execute/paper-status", "GET"),
        ("/tt/execute/paper-status/markdown", "GET"),
        ("/pi/risk/dashboard", "GET"),
        ("/pi/alerts", "GET"),
        ("/api/v1/portfolio_intel/paper/alerts", "POST"),
    ],
)
def test_account_scoped_reads_do_not_leak_into_standard(policy, path, method):
    """Paper-account data requires a Portfolio read-capable profile."""
    record = capability(path, method)
    assert not policy.evaluate_exposure(record, "platform-standard")
    assert policy.evaluate_exposure(record, "portfolio-read")


def test_side_effect_policy_does_not_depend_on_transport_method(policy):
    """Reviewed exact operation identity, not POST itself, supplies privilege."""
    decision = policy.classify_operation(
        "live-intelligence-custom", "POST", "/tt/execute/write-batch"
    )
    assert decision.access_class == "filesystem_write"
    assert decision.admitted_profiles == ("portfolio-ops",)
    with pytest.raises(KeyError):
        policy.classify_operation(
            "live-intelligence-custom", "GET", "/tt/execute/write-batch"
        )


def test_provider_models_preserve_routed_and_unimplemented_denominators(policy):
    """Provider routing state controls exposure without removing gaps."""
    common = {
        "provider": "fmp_cached",
        "fetcher_class": "SyntheticFetcher",
        "fetcher_module": "openbb_fmp_cached.models.synthetic",
        "implementation_id": "python:synthetic",
        "persistence": "dedicated",
        "credential_fields": ("fmp_cached_api_key",),
    }
    routed = ProviderModelMetadata(
        **common,
        model="Routed",
        commands=("/equity/quote",),
        tool_names=("equity_quote",),
        provider_registered=True,
        status="routed",
    )
    unrouted = ProviderModelMetadata(
        **common,
        model="Unrouted",
        commands=(),
        tool_names=(),
        provider_registered=True,
        status="unrouted",
    )
    routed_decision = policy.classify_provider_model(routed)
    gap_decision = policy.classify_provider_model(unrouted)
    assert routed_decision.disposition == "direct"
    assert routed_decision.admitted_profiles
    assert gap_decision.disposition == "unimplemented"
    assert gap_decision.admitted_profiles == ()
    assert gap_decision.reason


def test_all_181_provider_rows_classify_with_audited_partition(policy):
    """The immutable FMP provider denominator is fully policy-classified."""
    with (FIXTURES / "mcp-fmp-model-coverage.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    decisions = []
    for row in rows:
        routed = int(row["registered_command_count"]) > 0
        provider_row = ProviderModelMetadata(
            provider="fmp_cached",
            model=row["model"],
            fetcher_class=row["fetcher_class"],
            fetcher_module=row["implementation"],
            implementation_id=f"fixture:{row['model']}",
            persistence=(
                "fallback_none"
                if row["implementation"] == "fallback-no-persistence"
                else "dedicated"
            ),
            commands=tuple(row["commands"].split("|")) if row["commands"] else (),
            tool_names=tuple(row["mcp_tools"].split("|")) if row["mcp_tools"] else (),
            credential_fields=("fmp_cached_api_key",),
            provider_registered=True,
            status="routed" if routed else "unrouted",
        )
        decisions.append(policy.classify_provider_model(provider_row))
    assert len(decisions) == 181
    assert Counter(decision.disposition for decision in decisions) == {
        "direct": 70,
        "unimplemented": 111,
    }


def test_only_exact_reviewed_metadata_ids_are_admitted(policy):
    """Metadata admission is exact rather than prefix-based."""
    record = CapabilityRecord(
        id="platform:profile:portfolio-read",
        surface="platform",
        owner_lane="D-Widgets+QA",
        source_refs=("tests/synthetic.py",),
        implementation_id="prompt:synthetic",
        disposition="metadata_only",
        access_class="public_metadata",
        persistence="not_applicable",
        requirements=(),
        verification=VerificationState(schema=True),
    )
    assert policy.evaluate_exposure(record, "platform-standard")
    unknown = record.model_copy(update={"id": "platform:prompt:unreviewed"})
    assert not policy.evaluate_exposure(unknown, "platform-standard")


def test_specialist_catalog_declarations_are_not_overstated(policy):
    """Agents remain restricted and handler-less Daytrade stays unimplemented."""
    snapshot = json.loads(
        (FIXTURES / "mcp-catalog-snapshot.json").read_text(encoding="utf-8")
    )
    agents = [
        policy.classify_specialist("agents", name)
        for name in snapshot["agents"]["source_registry_tools"]
    ]
    daytrade = [
        policy.classify_specialist("daytrade", name)
        for name in snapshot["daytrade"]["declared_tools"]
    ]
    assert len(agents) == 2
    assert len(daytrade) == 6
    assert {decision.disposition for decision in agents} == {"restricted"}
    assert {decision.disposition for decision in daytrade} == {"unimplemented"}
    assert all(decision.reason for decision in [*agents, *daytrade])


def test_restricted_rule_without_reason_is_invalid(tmp_path):
    """Policy assets cannot silently restrict or omit capabilities."""
    source = (
        Path(__file__).parents[2]
        / "openbb_mcp_server"
        / "assets"
        / "capability_policy.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    invalid = deepcopy(payload)
    invalid["rules"][0].pop("reason")
    path = tmp_path / "invalid-policy.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    (tmp_path / payload["operation_catalog"]["file"]).write_bytes(
        (source.parent / payload["operation_catalog"]["file"]).read_bytes()
    )
    with pytest.raises(ValidationError, match="require a reason"):
        ExposurePolicy.load(path)
