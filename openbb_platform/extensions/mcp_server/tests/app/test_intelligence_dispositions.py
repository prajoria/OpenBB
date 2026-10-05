"""Complete disposition audit for Intelligence and Trading Desk operations."""

import csv
import os
from collections import Counter
from pathlib import Path

from fastapi.routing import APIRoute
from openbb_mcp_server.service.exposure_policy import ExposurePolicy

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

_ASSETS = Path(__file__).parents[2] / "openbb_mcp_server" / "assets"


def _catalog_rows() -> list[dict[str, str]]:
    with (_ASSETS / "capability_policy_operations.csv").open(
        encoding="utf-8",
        newline="",
    ) as stream:
        return [
            row
            for row in csv.DictReader(stream)
            if row["scope"] == "live-intelligence-custom"
        ]


def _app_operations() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method != "HEAD"
        and (
            route.path in {"/", "/widgets.json", "/apps.json"}
            or route.path.startswith(("/pi/", "/tt/"))
        )
    }


def test_all_69_live_operations_have_exact_catalog_membership():
    """The source app and reviewed catalog have the same unique denominator."""
    rows = _catalog_rows()
    catalog = {(row["method"], row["path"]) for row in rows}
    assert len(rows) == len(catalog) == 69
    assert Counter(
        (
            "metadata"
            if path in {"/", "/widgets.json", "/apps.json"}
            else path.split("/", 2)[1]
        )
        for _, path in catalog
    ) == {"pi": 48, "tt": 18, "metadata": 3}
    assert _app_operations() == catalog


def test_all_69_operations_have_effect_and_access_dispositions():
    """Every operation is classified once by its reviewed effect boundary."""
    policy = ExposurePolicy.load()
    decisions = [
        policy.classify_operation(
            row["scope"],
            row["method"],
            row["path"],
        )
        for row in _catalog_rows()
    ]
    assert Counter(decision.disposition for decision in decisions) == {
        "direct": 62,
        "metadata_only": 4,
        "restricted": 3,
    }
    assert Counter(decision.access_class for decision in decisions) == {
        "provider_read": 34,
        "private_portfolio_read": 27,
        "public_metadata": 4,
        "financial_mutation": 3,
        "job_control": 1,
    }


def test_state_changes_are_explicit_regardless_of_http_method():
    """Mutation classification is effect-based rather than method-derived."""
    policy = ExposurePolicy.load()
    trigger = policy.classify_path("POST", "/tt/scan/trigger")
    assert trigger.disposition == "direct"
    assert trigger.access_class == "job_control"
    assert trigger.admitted_profiles == ("portfolio-ops",)

    for path in (
        "/tt/execute/approve-plan",
        "/tt/execute/write-batch",
        "/tt/execute/cancel",
    ):
        decision = policy.classify_path("POST", path)
        assert decision.disposition == "restricted"
        assert decision.access_class == "financial_mutation"
        assert decision.admitted_profiles == ()


def test_adapter_relationships_have_unique_direct_tool_identities():
    """Every reviewed analytic operation has one stable adapter identity."""
    policy = ExposurePolicy.load()
    rows = _catalog_rows()
    direct_reads = [
        row
        for row in rows
        if policy.classify_operation(
            row["scope"],
            row["method"],
            row["path"],
        ).disposition
        == "direct"
        and row["path"] != "/tt/scan/trigger"
    ]
    names = {
        f"intelligence_{row['path'].strip('/').replace('/', '_').replace('-', '_')}"
        for row in direct_reads
    }
    assert len(direct_reads) == len(names) == 61
    assert {row["mcp_tool"] for row in direct_reads} == names


def test_unknown_future_widget_route_fails_closed_for_every_profile():
    """A new route cannot inherit admission from the broad PI/TT prefixes."""
    policy = ExposurePolicy.load()
    for profile in ("platform-standard", "portfolio-read", "portfolio-ops"):
        assert not policy.is_operation_admitted(
            "GET",
            "/pi/future/unreviewed",
            profile,
        )


def test_intelligence_traceability_records_completed_review():
    """The reviewed relationship is no longer reported as an adapter gap."""
    family = ExposurePolicy.load().document.traceability.work_families[
        "intelligence-widgets"
    ]
    assert family.implementation_state == "implemented_product"
    assert len(family.source_evidence) == 5
