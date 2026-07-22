"""Unit tests for W2 Quote family fetchers (#1090 #1091 #1093 #1225 #1245 #1246 #1249-#1253)."""

from __future__ import annotations

import pytest


def test_market_cap_maps_camelcase():
    """MarketCap -> market_cap."""
    from openbb_fmp_cached.models.stock_quotes import FMPCachedMarketCapFetcher

    rows = [{"symbol": "AAPL", "date": "2026-07-21", "marketCap": 4813634055440}]
    out = FMPCachedMarketCapFetcher.transform_data(None, rows)
    assert out[0].symbol == "AAPL"
    assert out[0].market_cap == 4813634055440


def test_shares_float_maps_camelcase():
    """freeFloat/floatShares/outstandingShares all remap."""
    from openbb_fmp_cached.models.stock_quotes import FMPCachedSharesFloatFetcher

    rows = [
        {
            "symbol": "AAPL",
            "date": "2026-07-21",
            "freeFloat": 99.83,
            "floatShares": 14662387495,
            "outstandingShares": 14688300000,
        }
    ]
    out = FMPCachedSharesFloatFetcher.transform_data(None, rows)
    assert out[0].free_float == pytest.approx(99.83)
    assert out[0].float_shares == 14662387495
    assert out[0].outstanding_shares == 14688300000


def test_stock_price_change_extra_allow_preserves_period_columns():
    """stock-price-change returns 1D/5D/1M/3M/6M/ytd/1Y/... — extra=allow."""
    from openbb_fmp_cached.models.stock_quotes import FMPCachedStockPriceChangeFetcher

    rows = [{"symbol": "AAPL", "1D": 0.35, "5D": -1.28, "1M": 10.35, "ytd": 20.55}]
    out = FMPCachedStockPriceChangeFetcher.transform_data(None, rows)
    # dynamic period fields exposed via extra=allow
    assert out[0].symbol == "AAPL"
    d = out[0].model_dump()
    assert d["1D"] == pytest.approx(0.35)
    assert d["ytd"] == pytest.approx(20.55)


def test_quote_short_typed_fields():
    """quote-short models 4 core fields; extras dropped."""
    from openbb_fmp_cached.models.stock_quotes import FMPCachedStockQuoteShortFetcher

    rows = [{"symbol": "AAPL", "price": 327.74, "change": 1.15, "volume": 40800631}]
    out = FMPCachedStockQuoteShortFetcher.transform_data(None, rows)
    assert out[0].price == 327.74
    assert out[0].volume == 40800631


def test_batch_aftermarket_trade_maps_trade_size():
    """TradeSize -> trade_size; tolerates None."""
    from openbb_fmp_cached.models.stock_quotes import (
        FMPCachedBatchAftermarketTradeFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "price": 324.5,
            "tradeSize": None,
            "timestamp": 1784678399000,
        },
        {
            "symbol": "MSFT",
            "price": 500.0,
            "tradeSize": 100,
            "timestamp": 1784678400000,
        },
    ]
    out = FMPCachedBatchAftermarketTradeFetcher.transform_data(None, rows)
    assert out[0].trade_size is None
    assert out[1].trade_size == 100


def test_batch_aftermarket_quote_maps_bid_ask():
    """bidSize/bidPrice/askSize/askPrice all remap."""
    from openbb_fmp_cached.models.stock_quotes import (
        FMPCachedBatchAftermarketQuoteFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "bidSize": 1,
            "bidPrice": 324.28,
            "askSize": 30,
            "askPrice": 324.8,
            "volume": 41338917,
            "timestamp": 1784678400000,
        }
    ]
    out = FMPCachedBatchAftermarketQuoteFetcher.transform_data(None, rows)
    assert out[0].bid_size == 1
    assert out[0].ask_price == 324.8


def test_exchange_market_hours_extra_allow():
    """all-exchange-market-hours returns ~7 columns; extra=allow preserves them."""
    from openbb_fmp_cached.models.stock_quotes import (
        FMPCachedAllExchangeMarketHoursFetcher,
    )

    rows = [
        {
            "exchange": "ASX",
            "name": "Australian Securities Exchange",
            "openingHour": "10:00 AM +10:00",
            "closingHour": "04:00 PM +10:00",
        }
    ]
    out = FMPCachedAllExchangeMarketHoursFetcher.transform_data(None, rows)
    assert out[0].exchange == "ASX"
    d = out[0].model_dump()
    assert d["openingHour"] == "10:00 AM +10:00"


def test_query_field_configuration():
    """Symbol vs symbols vs unused correctly wired per endpoint."""
    from openbb_fmp_cached.models.stock_quotes import (
        FMPCachedAllExchangeMarketHoursFetcher,
        FMPCachedBatchAftermarketQuoteFetcher,
        FMPCachedBatchAftermarketTradeFetcher,
        FMPCachedBatchQuoteFetcher,
        FMPCachedBatchQuoteShortFetcher,
        FMPCachedMarketCapBatchFetcher,
        FMPCachedMarketCapFetcher,
        FMPCachedSharesFloatFetcher,
        FMPCachedStockPriceChangeFetcher,
        FMPCachedStockQuoteFetcher,
        FMPCachedStockQuoteShortFetcher,
    )

    single_symbol = [
        FMPCachedMarketCapFetcher,
        FMPCachedSharesFloatFetcher,
        FMPCachedStockPriceChangeFetcher,
        FMPCachedStockQuoteFetcher,
        FMPCachedStockQuoteShortFetcher,
    ]
    batch_symbols = [
        FMPCachedMarketCapBatchFetcher,
        FMPCachedBatchQuoteFetcher,
        FMPCachedBatchQuoteShortFetcher,
        FMPCachedBatchAftermarketTradeFetcher,
        FMPCachedBatchAftermarketQuoteFetcher,
    ]
    for f in single_symbol:
        assert f._query_field == "symbol", f"{f.__name__} wrong param"
    for f in batch_symbols:
        assert f._query_field == "symbols", f"{f.__name__} wrong param"
    # No-param sends 'unused' as a throwaway key that FMP ignores
    assert FMPCachedAllExchangeMarketHoursFetcher._query_field == "unused"


def test_all_eleven_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "MarketCap",
        "MarketCapBatch",
        "SharesFloat",
        "StockPriceChange",
        "StockQuote",
        "StockQuoteShort",
        "BatchQuote",
        "BatchQuoteShort",
        "BatchAftermarketTrade",
        "BatchAftermarketQuote",
        "AllExchangeMarketHours",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_symbols_query_params_require_field():
    """_SymbolsQueryParams requires the symbols field."""
    from openbb_fmp_cached.models.stock_quotes import _SymbolsQueryParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _SymbolsQueryParams()


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.stock_quotes import FMPCachedMarketCapFetcher

    assert FMPCachedMarketCapFetcher.transform_data(None, []) == []
