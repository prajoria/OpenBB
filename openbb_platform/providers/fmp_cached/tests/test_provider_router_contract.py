"""Typed route assembly tests for the FMP Cached provider."""

import inspect
from unittest.mock import AsyncMock, patch

import pytest
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.fmp_cached_router import router, stock_list
from openbb_fmp_cached.models.symbol_lists import FMPCachedStockListFetcher
from openbb_fmp_cached.routers import reference_router


def test_router_exposes_stock_list_with_real_provider_model():
    """The route binds the registered StockList fetcher and typed schemas."""
    assert fmp_cached_provider.fetcher_dict["StockList"] is FMPCachedStockListFetcher
    route = next(
        item
        for item in router.api_router.routes
        if getattr(item, "path", "").endswith("/stock_list")
    )
    assert route.path == "/stock_list"
    assert "GET" in route.methods


def test_stock_list_has_only_dispatcher_injection_parameters():
    """Callers cannot select arbitrary models or pass unreviewed arguments."""
    assert tuple(inspect.signature(stock_list).parameters) == (
        "cc",
        "provider_choices",
        "standard_params",
        "extra_params",
    )


@pytest.mark.asyncio
async def test_stock_list_uses_provider_dispatcher_with_synthetic_rows():
    """The genuine fetch pipeline transforms synthetic transport rows."""
    synthetic = [{"symbol": "AAA", "companyName": "Alpha"}]
    with patch.object(
        FMPCachedStockListFetcher,
        "_shared_extract",
        new=AsyncMock(return_value=synthetic),
    ) as extract:
        result = await FMPCachedStockListFetcher.fetch_data({}, {})

    extract.assert_awaited_once()
    assert result[0].model_dump() == {
        "symbol": "AAA",
        "company_name": "Alpha",
    }


@pytest.mark.asyncio
async def test_stock_list_delegates_to_query_and_obbject():
    """The command delegates model/provider binding to the core dispatcher."""
    query = object()
    response = object()
    with (
        patch.object(reference_router, "Query", return_value=query) as query_cls,
        patch.object(
            reference_router.OBBject,
            "from_query",
            new=AsyncMock(return_value=response),
        ) as from_query,
    ):
        result = await stock_list(None, None, None, None)  # type: ignore[arg-type]

    assert result is response
    query_cls.assert_called_once_with(
        cc=None,
        provider_choices=None,
        standard_params=None,
        extra_params=None,
    )
    from_query.assert_awaited_once_with(query)
