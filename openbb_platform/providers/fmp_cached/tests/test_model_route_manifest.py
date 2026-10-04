"""Contract tests for provider-owned FMP Cached routes."""

import json
from importlib import resources
from pathlib import Path

from openbb_fmp import fmp_provider
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.fmp_cached_router import router


def _manifest() -> dict:
    path = (
        Path(__file__).parents[1] / "openbb_fmp_cached" / "assets" / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_has_one_unique_stock_list_route():
    """The first promoted model has one stable canonical identity."""
    document = _manifest()
    assert document["schema_version"] == 1
    assert document["routes"] == [
        {
            "aliases": [],
            "arguments": [],
            "canonical_route": "/fmp_cached/stock_list",
            "command": "stock_list",
            "model": "StockList",
            "providers": ["fmp", "fmp_cached"],
        }
    ]


def test_manifest_route_identities_and_models_are_unique():
    """No future manifest row can shadow an existing route/model."""
    routes = _manifest()["routes"]
    assert len({item["canonical_route"] for item in routes}) == len(routes)
    assert len({item["command"] for item in routes}) == len(routes)
    assert len({item["model"] for item in routes}) == len(routes)


def test_manifest_arguments_are_explicitly_allowlisted():
    """A promoted model cannot acquire an arbitrary dispatch argument."""
    for route in _manifest()["routes"]:
        assert "model" not in route["arguments"]
        assert all(argument.isidentifier() for argument in route["arguments"])


def test_package_declares_provider_owned_core_entry_point():
    """Source metadata follows the established core-extension contract."""
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    section = pyproject.split(
        '[tool.poetry.plugins."openbb_core_extension"]', maxsplit=1
    )[1].split("\n[", maxsplit=1)[0]
    assert section.strip() == (
        'fmp_cached = "openbb_fmp_cached.fmp_cached_router:router"'
    )


def test_manifest_cross_validates_router_and_provider_registry():
    """Manifest evidence agrees with executable route/provider ownership."""
    route = next(
        item
        for item in router.api_router.routes
        if getattr(item, "path", "") == "/stock_list"
    )
    evidence = _manifest()["routes"][0]
    providers = {
        provider.name
        for provider in (fmp_provider, fmp_cached_provider)
        if evidence["model"] in provider.fetcher_dict
    }
    assert evidence["canonical_route"] == f"/fmp_cached{route.path}"
    assert providers == set(evidence["providers"])


def test_manifest_is_in_the_importable_package():
    """Built distributions retain the route evidence asset."""
    asset = resources.files("openbb_fmp_cached").joinpath("assets/model_routes.json")
    assert json.loads(asset.read_text(encoding="utf-8")) == _manifest()
