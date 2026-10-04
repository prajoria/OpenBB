"""Typed quote and batch-route contract tests."""

import json
from dataclasses import dataclass, make_dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers import quote_router
from pydantic import BaseModel, create_model

QUOTE_MODELS = {
    "MarketCap": ("market_cap", "symbol"),
    "SharesFloat": ("shares_float", "symbol"),
    "StockPriceChange": ("stock_price_change", "symbol"),
    "StockQuote": ("stock_quote", "symbol"),
    "StockQuoteShort": ("stock_quote_short", "symbol"),
    "MarketCapBatch": ("market_cap_batch", "symbols"),
    "BatchQuote": ("batch_quote", "symbols"),
    "BatchQuoteShort": ("batch_quote_short", "symbols"),
    "BatchAftermarketTrade": ("batch_aftermarket_trade", "symbols"),
    "BatchAftermarketQuote": ("batch_aftermarket_quote", "symbols"),
    "AllExchangeMarketHours": ("all_exchange_market_hours", None),
}


@dataclass
class _ProviderChoices:
    provider: str = "fmp_cached"


def _manifest() -> list[dict]:
    path = (
        Path(__file__).parents[1] / "openbb_fmp_cached" / "assets" / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def _standard_params(**fields) -> BaseModel:
    model = create_model(
        "QuoteStandardParams",
        **{name: (type(value), ...) for name, value in fields.items()},
    )
    return model(**fields)


def _extra_params(**fields):
    model = make_dataclass(
        "QuoteExtraParams",
        [(name, type(value)) for name, value in fields.items()],
    )
    return model(**fields)


def test_eleven_quote_models_have_explicit_routes():
    """All quote-family registrations have stable typed mappings."""
    evidence = {
        row["model"]: row for row in _manifest() if row["model"] in QUOTE_MODELS
    }
    assert set(evidence) == set(QUOTE_MODELS)
    paths = {route.path for route in quote_router.router.api_router.routes}
    for model, (command, argument) in QUOTE_MODELS.items():
        assert evidence[model]["command"] == command
        assert evidence[model]["arguments"] == ([argument] if argument else [])
        assert f"/{command}" in paths


@pytest.mark.parametrize(
    ("model", "argument", "value"),
    [
        ("MarketCap", "symbol", "AAPL"),
        ("SharesFloat", "symbol", "BRK.B"),
        ("StockPriceChange", "symbol", "MSFT"),
        ("StockQuote", "symbol", "NVDA"),
        ("StockQuoteShort", "symbol", "AMD"),
        ("MarketCapBatch", "symbols", "AAPL,MSFT"),
        ("BatchQuote", "symbols", "AAPL,AAPL"),
        ("BatchQuoteShort", "symbols", "AAPL,MSFT"),
        ("BatchAftermarketTrade", "symbols", "AAPL,MSFT"),
        ("BatchAftermarketQuote", "symbols", "AAPL,MSFT"),
    ],
)
def test_quote_inputs_match_real_query_models(model, argument, value):
    """Single, batch and duplicate symbol input retains declared semantics."""
    fetcher = fmp_cached_provider.fetcher_dict[model]
    query = fetcher.transform_query({argument: value})
    assert getattr(query, argument) == value


def test_batch_symbol_normalization_preserves_duplicates_and_order():
    """Batch preparation never silently deduplicates caller input."""
    params = _standard_params(symbols="AAPL,AAPL,MSFT")
    assert quote_router._symbol_values(params.model_dump()) == [
        "AAPL",
        "AAPL",
        "MSFT",
    ]


@pytest.mark.asyncio
async def test_batch_routes_reject_empty_and_unbounded_inputs():
    """Batch dispatch fails before provider I/O for unsafe cardinality."""
    with pytest.raises(OpenBBError, match="At least one symbol"):
        await quote_router._dispatch(  # pylint: disable=protected-access
            None, _ProviderChoices(), _standard_params(), _extra_params(symbols="")
        )
    symbols = ",".join(f"S{index}" for index in range(101))
    with pytest.raises(OpenBBError, match="at most 100 symbols"):
        await quote_router._dispatch(  # pylint: disable=protected-access
            None,
            _ProviderChoices(),
            _standard_params(),
            _extra_params(symbols=symbols),
        )
    chunks = [
        ",".join(f"A{index}" for index in range(60)),
        ",".join(f"B{index}" for index in range(60)),
    ]
    with pytest.raises(OpenBBError, match="at most 100 symbols"):
        await quote_router._dispatch(  # pylint: disable=protected-access
            None,
            _ProviderChoices(),
            _standard_params(),
            _extra_params(symbols=chunks),
        )


@pytest.mark.asyncio
async def test_single_symbol_routes_reject_blank_input():
    """Required single-symbol routes reject whitespace before provider I/O."""
    with pytest.raises(OpenBBError, match="non-empty symbol"):
        await quote_router._dispatch(  # pylint: disable=protected-access
            None,
            _ProviderChoices(),
            _standard_params(),
            _extra_params(symbol="   "),
        )
    with pytest.raises(OpenBBError, match="non-empty symbol"):
        await quote_router._dispatch(  # pylint: disable=protected-access
            None,
            _ProviderChoices(),
            _standard_params(),
            _extra_params(symbol=None),
        )


@pytest.mark.asyncio
async def test_partial_batch_results_are_not_fabricated():
    """Dispatcher returns exactly the provider's partial response."""
    params = _extra_params(symbols=["AAPL", "MSFT"])
    response = quote_router.OBBject(results=[{"symbol": "AAPL", "price": 100.0}])
    with patch.object(
        quote_router.OBBject,
        "from_query",
        new=AsyncMock(return_value=response),
    ) as from_query:
        result = await quote_router._dispatch(  # pylint: disable=protected-access
            None, _ProviderChoices(), _standard_params(), params
        )
    assert len(result.results) == 1
    assert result.results[0]["symbol"] == "AAPL"
    from_query.assert_awaited_once()
    assert params.symbols == "AAPL,MSFT"


def test_existing_equity_quote_contract_is_unchanged():
    """The new family does not replace canonical EquityQuote dispatch."""
    assert "EquityQuote" in fmp_cached_provider.fetcher_dict
    assert "EquityQuote" not in QUOTE_MODELS
    assert all(row["model"] != "EquityQuote" for row in _manifest())
