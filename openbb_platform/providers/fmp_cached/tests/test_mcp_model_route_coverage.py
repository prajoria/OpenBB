"""End-to-end contract gate for all 181 FMP Cached registrations."""

import hashlib
import importlib
import json
from dataclasses import make_dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from openbb_core.app.router import RouterLoader
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.fmp_cached_router import router as fmp_cached_router
from openbb_fmp_cached.routers import (
    analyst_router,
    corporate_router,
    government_news_router,
    intraday_router,
    market_performance_router,
    quote_router,
    reference_history_router,
    reference_router,
    search_router,
    statements_router,
)

_ASSETS = Path(__file__).parents[1] / "openbb_fmp_cached" / "assets"
_LEGACY_HASH = "b0f6d7fb9edd2c53b8a9c2a9c617a01d7b39a87d8111fbf94f61273a0005f46f"


def _manifest() -> list[dict]:
    return json.loads((_ASSETS / "model_routes.json").read_text(encoding="utf-8"))[
        "routes"
    ]


def _route_models(router) -> set[str]:
    return {
        route.openapi_extra["model"]
        for route in router.api_router.routes
        if route.openapi_extra and route.openapi_extra.get("model")
    }


def test_all_181_provider_models_have_typed_routes():
    """Legacy plus provider-owned routes cover the complete denominator."""
    registered = set(fmp_cached_provider.fetcher_dict)
    manifest = {row["model"] for row in _manifest()}
    assembled = RouterLoader.from_extensions()
    legacy = {
        route.openapi_extra["model"]
        for route in assembled.api_router.routes
        if route.openapi_extra
        and route.openapi_extra.get("model") in registered
        and not route.path.startswith("/fmp_cached/")
    }
    assert len(registered) == 181
    assert len(legacy) == 70
    assert len(manifest) == 112
    assert legacy & manifest == {"RiskPremium"}
    assert legacy | manifest == registered


def test_legacy_70_route_identities_are_unchanged():
    """The original route path/model/operation IDs remain byte-stable."""
    registered = set(fmp_cached_provider.fetcher_dict)
    routes = []
    for route in RouterLoader.from_extensions().api_router.routes:
        evidence = route.openapi_extra or {}
        if evidence.get("model") in registered and not route.path.startswith(
            "/fmp_cached/"
        ):
            routes.append(
                {
                    "path": route.path,
                    "model": evidence["model"],
                    "operation_id": route.operation_id,
                    "methods": sorted(route.methods),
                }
            )
    payload = json.dumps(
        sorted(routes, key=lambda item: item["path"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(payload.encode()).hexdigest() == _LEGACY_HASH


def test_eight_gap_batches_are_disjoint_and_equal_original_111():
    """T12-T19 partition the audited 111-key gap without overlap."""
    batches = [
        _route_models(reference_router.router) - {"StockList"},
        _route_models(search_router.router)
        | _route_models(reference_history_router.router),
        _route_models(quote_router.router),
        _route_models(intraday_router.router),
        _route_models(analyst_router.router)
        | _route_models(market_performance_router.router),
        _route_models(statements_router.router),
        _route_models(corporate_router.router),
        _route_models(government_news_router.router),
    ]
    for index, batch in enumerate(batches):
        for other in batches[index + 1 :]:
            assert batch.isdisjoint(other)
    union = set().union(*batches)
    manifest = {row["model"] for row in _manifest()}
    assert len(union) == 111
    assert union == manifest - {"StockList"}


def test_all_provider_owned_routes_match_manifest_and_openapi():
    """Every approved operation has exact provider/argument/tool evidence."""
    app = FastAPI()
    app.include_router(
        fmp_cached_router.api_router,
        prefix="/api/v1/fmp_cached",
    )
    openapi = app.openapi()["paths"]
    for row in _manifest():
        path = row["canonical_route"].replace(
            "/fmp_cached",
            "/api/v1/fmp_cached",
            1,
        )
        operation = openapi[path]["get"]
        assert operation["operationId"] == f"fmp_cached_{row['command']}"
        schema = operation.get("parameters", [])
        wire_arguments = {item["name"] for item in schema if item["name"] != "provider"}
        body = operation.get("requestBody", {})
        if body:
            body_schema = body["content"]["application/json"]["schema"]
            for name in body_schema.get("properties", {}):
                wire_arguments.add(name)
        assert wire_arguments == set(row["arguments"])


@pytest.mark.asyncio
@pytest.mark.parametrize("row", _manifest(), ids=lambda row: row["model"])
async def test_every_provider_owned_command_is_callable_with_synthetic_data(row):
    """Each command reaches typed Query/OBBject dispatch without network I/O."""
    route = next(
        route
        for route in fmp_cached_router.api_router.routes
        if route.path == row["canonical_route"].removeprefix("/fmp_cached")
    )
    module = importlib.import_module(route.endpoint.__module__)
    provider_choices = make_dataclass(
        "ProviderChoices",
        [("provider", str)],
    )(provider="fmp_cached")
    standard_params = make_dataclass("StandardParams", [])()
    values = {
        "symbol": "AAPL",
        "symbols": "AAPL,MSFT",
        "cik": "0000320193",
        "query": "Alpha",
        "cusip": "037833100",
        "isin": "US0378331005",
        "name": "Alpha",
        "date": "2025-01-02",
        "sector": "Technology",
        "industry": "Software",
        "year": 2025,
        "period": "FY",
        "exchange": "NASDAQ",
        "indicator": "SMA",
        "period_length": 14,
        "timeframe": "5min",
        "interval": "5min",
        "start_date": "2025-01-02",
        "end_date": "2025-01-03",
        "extended_hours": False,
        "page": 0,
        "limit": 10,
        "senate_id": "A000360",
        "from": "2025-01-01",
        "to": "2025-01-31",
        "sicCode": "3571",
    }
    python_names = {
        "from": "from_date",
        "to": "to_date",
        "sicCode": "sic_code",
    }
    fields = [
        (python_names.get(name, name), type(values[name])) for name in row["arguments"]
    ]
    extra_params = make_dataclass("ExtraParams", fields)(
        **{python_names.get(name, name): values[name] for name in row["arguments"]}
    )
    response = module.OBBject(
        results=[{"model": row["model"]}],
        provider="fmp_cached",
    )
    with (
        patch.object(module, "Query", return_value=object()),
        patch.object(
            module.OBBject,
            "from_query",
            new=AsyncMock(return_value=response),
        ),
    ):
        result = await route.endpoint(
            None,
            provider_choices,
            standard_params,
            extra_params,
        )
    assert result.results == [{"model": row["model"]}]


def test_58_fallback_descriptors_are_explicitly_non_persistent():
    """Credential-only wrappers are never reported as durable cache stores."""
    document = json.loads(
        (_ASSETS / "persistence_descriptors.json").read_text(encoding="utf-8")
    )
    runtime = {
        name
        for name, fetcher in fmp_cached_provider.fetcher_dict.items()
        if fetcher.__module__ == "openbb_fmp_cached.models.base_cached"
        and fetcher.__name__.startswith("Fallback")
    }
    assert len(runtime) == 58
    assert runtime == set(document["non_persistent_fallbacks"])
    assert document["descriptor"]["persistent"] is False
    assert document["descriptor"]["strategy"] == "credential_translation_only"
