"""Profile contracts for the 32 baseline analytical operations."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from openbb_backtest.backtest_router import router as backtest_router
from openbb_mcp_server.service.exposure_policy import ExposurePolicy
from openbb_portfolio_intel.portfolio_intel_router import (
    router as portfolio_intel_router,
)
from openbb_regime.regime_router import router as regime_router
from openbb_techtrade.techtrade_router import router as techtrade_router

_ASSETS = Path(__file__).parents[2] / "openbb_mcp_server" / "assets"
_FAMILIES = {
    "backtest": "/api/v1/backtest",
    "techtrade": "/api/v1/techtrade",
    "portfolio_intel": "/api/v1/portfolio_intel",
    "regime": "/api/v1/regime",
}
_SOURCE_IDENTITY_HASH = (
    "fe03bd4271e9b1a35fb2e5712d96006492c20e606e793ea37a0373b2c93a8afa"
)


def _rows() -> dict[str, list[dict[str, str]]]:
    with (_ASSETS / "capability_policy_operations.csv").open(
        encoding="utf-8",
        newline="",
    ) as stream:
        catalog = list(csv.DictReader(stream))
    return {
        family: [row for row in catalog if row["path"].startswith(prefix)]
        for family, prefix in _FAMILIES.items()
    }


def test_exact_32_route_denominator_is_locked():
    """Baseline extension counts cannot shrink or silently absorb aliases."""
    rows = _rows()
    assert {family: len(items) for family, items in rows.items()} == {
        "backtest": 10,
        "techtrade": 11,
        "portfolio_intel": 10,
        "regime": 1,
    }
    identities = {
        (row["method"], row["path"]) for items in rows.values() for row in items
    }
    assert len(identities) == 32


def test_analytical_effects_are_profile_classified():
    """Writes, private state, metadata, and provider reads remain distinct."""
    policy = ExposurePolicy.load()
    rows = [row for items in _rows().values() for row in items]
    decisions = {
        row["path"]: policy.classify_operation(
            row["scope"],
            row["method"],
            row["path"],
        )
        for row in rows
    }
    assert Counter(item.disposition for item in decisions.values()) == {
        "direct": 29,
        "metadata_only": 3,
    }
    operator_writes = {
        "/api/v1/backtest/bundle/ingest",
        "/api/v1/techtrade/export",
        "/api/v1/techtrade/tune",
    }
    for path in operator_writes:
        decision = decisions[path]
        assert decision.access_class == "filesystem_write"
        assert decision.admitted_profiles == ("portfolio-ops",)
    paper = decisions["/api/v1/portfolio_intel/paper/alerts"]
    assert paper.access_class == "private_portfolio_read"
    assert "platform-standard" not in paper.admitted_profiles
    metadata = {
        "/api/v1/backtest/about",
        "/api/v1/techtrade/about",
        "/api/v1/portfolio_intel/about",
    }
    for row in rows:
        decision = decisions[row["path"]]
        if row["path"] in operator_writes:
            expected = ("direct", "filesystem_write", ("portfolio-ops",))
        elif row["path"] == "/api/v1/portfolio_intel/paper/alerts":
            expected = (
                "direct",
                "private_portfolio_read",
                ("portfolio-read", "portfolio-ops"),
            )
        elif row["path"] in metadata:
            expected = (
                "metadata_only",
                "public_metadata",
                ("platform-standard", "portfolio-read", "portfolio-ops"),
            )
        else:
            expected = (
                "direct",
                "provider_read",
                ("platform-standard", "portfolio-read", "portfolio-ops"),
            )
        assert (
            decision.disposition,
            decision.access_class,
            decision.admitted_profiles,
        ) == expected


def test_read_profiles_do_not_inherit_operator_operations():
    """Approved analytical reads stay callable without admitting write effects."""
    policy = ExposurePolicy.load()
    for path in (
        "/api/v1/backtest/bundle/ingest",
        "/api/v1/techtrade/export",
        "/api/v1/techtrade/tune",
    ):
        assert not policy.is_operation_admitted(
            "POST",
            path,
            "portfolio-read",
        )
        assert policy.is_operation_admitted("POST", path, "portfolio-ops")


def test_analytical_catalog_tools_have_unique_source_identities():
    """Approved tools retain original operation IDs without adapter aliases."""
    rows = [row for items in _rows().values() for row in items]
    tools = [row["mcp_tool"] for row in rows if row["mcp_tool"]]
    assert len(tools) == len(set(tools)) == 32


def test_source_router_surfaces_match_reviewed_denominators():
    """Original routers retain all approved operations and expose no silent aliases."""
    excluded_regime = {
        (method, route.path)
        for route in regime_router.api_router.routes
        if route.path != "/detect"
        for method in route.methods
    }
    assert excluded_regime == {("GET", "/about")}
    source = []
    for prefix, router in (
        ("/api/v1/backtest", backtest_router),
        ("/api/v1/techtrade", techtrade_router),
        ("/api/v1/portfolio_intel", portfolio_intel_router),
        ("/api/v1/regime", regime_router),
    ):
        for route in router.api_router.routes:
            if (
                prefix.endswith("/regime")
                and (next(iter(route.methods)), route.path) in excluded_regime
            ):
                continue
            source.extend(
                (method, f"{prefix}{route.path}", route.operation_id)
                for method in route.methods
            )
    catalog = {
        (row["method"], row["path"]) for items in _rows().values() for row in items
    }
    assert {(method, path) for method, path, _ in source} == catalog
    payload = json.dumps(sorted(source), separators=(",", ":"))
    assert hashlib.sha256(payload.encode()).hexdigest() == _SOURCE_IDENTITY_HASH
    assert not ExposurePolicy.load().is_operation_admitted(
        "GET",
        "/api/v1/regime/about",
        "portfolio-ops",
    )


def test_runtime_profiles_require_checkout_local_analytical_modules():
    """Required analytics fail explicitly; optional numerical engines stay opt-in."""
    document = json.loads(
        (_ASSETS / "runtime_profiles.json").read_text(encoding="utf-8")
    )
    required = {
        "openbb_backtest": "openbb_platform/extensions/backtest",
        "openbb_techtrade": "openbb_platform/extensions/techtrade",
        "openbb_portfolio_intel": "openbb_platform/extensions/portfolio_intel",
        "openbb_regime": "openbb_platform/extensions/regime",
    }
    for profile_name in ("portfolio-read", "portfolio-ops"):
        profile = document["profiles"][profile_name]
        for module, source in required.items():
            assert module in profile["required_modules"]
            assert profile["module_sources"][module] == source
        assert profile["optional_analytics"] == ["openbb-financialtoolkit"]
        assert profile["optional_module_sources"]["openbb-financialtoolkit"] == {
            "openbb_financialtoolkit": "openbb_platform/extensions/financialtoolkit"
        }
