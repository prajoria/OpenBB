"""Cached FMP quote family — single-symbol + batch quote endpoints.

W2 Quote drain, batch 11 (#1090 #1091 #1093 #1225 #1245 #1246 #1249
#1250 #1251 #1252 #1253).

11 endpoints across two shapes:

**Single-symbol** (``symbol=``, reuses ``_SearchFetcherBase``):
- ``market-capitalization`` (#1090)
- ``shares-float`` (#1093)
- ``stock-price-change`` (#1249) — wide row w/ 1D/5D/1M/... columns
- ``quote`` (#1245)
- ``quote-short`` (#1246)

**Batch symbols** (``symbols=A,B,C``, comma-joined):
- ``market-capitalization-batch`` (#1091)
- ``batch-quote`` (#1250)
- ``batch-quote-short`` (#1251)
- ``batch-aftermarket-trade`` (#1252)
- ``batch-aftermarket-quote`` (#1253)

**No-param**:
- ``all-exchange-market-hours`` (#1225)

All Free-tier live pass-through. Extra=allow on quote rows because
FMP returns ~30 columns per quote and column-set drifts.
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import ConfigDict, Field

from openbb_fmp_cached.models.search_endpoints import _SearchFetcherBase
from openbb_fmp_cached.models.single_param_endpoints import _SymbolQueryParams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class _SymbolsQueryParams(QueryParams):
    """Query params for endpoints keyed by ``symbols=A,B,C`` (comma-joined).

    FMP's batch endpoints all take a single ``symbols`` param with the
    tickers comma-joined. We accept either a plain str or a list; the
    fetcher joins the list before hitting FMP.
    """

    symbols: str = Field(
        description="Comma-joined ticker list (e.g. 'AAPL,MSFT,GOOGL')."
    )


class _NoParams(QueryParams):
    """No-param endpoints (all-exchange-market-hours)."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedMarketCapData(Data):
    """Row from ``/stable/market-capitalization`` (and batch variant)."""

    symbol: str = Field(description="Ticker symbol.")
    date: str | None = Field(default=None, description="Snapshot date.")
    market_cap: float | None = Field(default=None, description="Market cap (USD).")


class FMPCachedSharesFloatData(Data):
    """Row from ``/stable/shares-float`` (single-symbol variant)."""

    symbol: str = Field(description="Ticker symbol.")
    date: str | None = Field(default=None, description="Snapshot timestamp.")
    free_float: float | None = Field(default=None, description="Free float %.")
    float_shares: int | None = Field(default=None, description="Float share count.")
    outstanding_shares: int | None = Field(
        default=None, description="Outstanding share count."
    )


class FMPCachedStockPriceChangeData(Data):
    """Row from ``/stable/stock-price-change`` — 1D/5D/1M/... % changes."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


class FMPCachedQuoteData(Data):
    """Row from full-quote endpoints — ~30 fields, extra=allow."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


class FMPCachedQuoteShortData(Data):
    """Row from short-quote endpoints — 4 core fields."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Last price.")
    change: float | None = Field(default=None, description="Absolute change.")
    volume: int | None = Field(default=None, description="Session volume.")


class FMPCachedAftermarketTradeData(Data):
    """Row from ``/stable/batch-aftermarket-trade``."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Aftermarket trade price.")
    trade_size: int | None = Field(
        default=None, description="Trade size (may be null)."
    )
    timestamp: int | None = Field(default=None, description="Unix ms timestamp.")


class FMPCachedAftermarketQuoteData(Data):
    """Row from ``/stable/batch-aftermarket-quote``."""

    symbol: str = Field(description="Ticker symbol.")
    bid_size: int | None = Field(default=None, description="Bid size.")
    bid_price: float | None = Field(default=None, description="Bid price.")
    ask_size: int | None = Field(default=None, description="Ask size.")
    ask_price: float | None = Field(default=None, description="Ask price.")
    volume: int | None = Field(default=None, description="Session volume.")
    timestamp: int | None = Field(default=None, description="Unix ms timestamp.")


class FMPCachedExchangeMarketHoursData(Data):
    """Row from ``/stable/all-exchange-market-hours``."""

    model_config = ConfigDict(extra="allow")

    exchange: str = Field(description="Exchange short code.")
    name: str | None = Field(default=None, description="Exchange full name.")


_MARKET_CAP_ALIASES = {"marketCap": "market_cap"}
_SHARES_FLOAT_ALIASES = {
    "freeFloat": "free_float",
    "floatShares": "float_shares",
    "outstandingShares": "outstanding_shares",
}
_AFTERMARKET_TRADE_ALIASES = {"tradeSize": "trade_size"}
_AFTERMARKET_QUOTE_ALIASES = {
    "bidSize": "bid_size",
    "bidPrice": "bid_price",
    "askSize": "ask_size",
    "askPrice": "ask_price",
}


# ---------------------------------------------------------------------------
# Single-symbol fetchers
# ---------------------------------------------------------------------------


class FMPCachedMarketCapFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedMarketCapData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/market-capitalization`` (#1090)."""

    _path = "market-capitalization"
    _data_cls = FMPCachedMarketCapData
    _alias_map = _MARKET_CAP_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedMarketCapFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedMarketCapData]:
        """Map raw rows to typed market-cap data."""
        return FMPCachedMarketCapFetcher._transform(data)


class FMPCachedSharesFloatFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedSharesFloatData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/shares-float`` (#1093)."""

    _path = "shares-float"
    _data_cls = FMPCachedSharesFloatData
    _alias_map = _SHARES_FLOAT_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedSharesFloatFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSharesFloatData]:
        """Map raw rows to typed shares-float data."""
        return FMPCachedSharesFloatFetcher._transform(data)


class FMPCachedStockPriceChangeFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedStockPriceChangeData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/stock-price-change`` (#1249)."""

    _path = "stock-price-change"
    _data_cls = FMPCachedStockPriceChangeData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedStockPriceChangeFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedStockPriceChangeData]:
        """Map raw rows to typed price-change data."""
        return FMPCachedStockPriceChangeFetcher._transform(data)


class FMPCachedStockQuoteFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedQuoteData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/quote`` (#1245)."""

    _path = "quote"
    _data_cls = FMPCachedQuoteData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedStockQuoteFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedQuoteData]:
        """Map raw rows to typed quote data."""
        return FMPCachedStockQuoteFetcher._transform(data)


class FMPCachedStockQuoteShortFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedQuoteShortData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/quote-short`` (#1246)."""

    _path = "quote-short"
    _data_cls = FMPCachedQuoteShortData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedStockQuoteShortFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedQuoteShortData]:
        """Map raw rows to typed short-quote data."""
        return FMPCachedStockQuoteShortFetcher._transform(data)


# ---------------------------------------------------------------------------
# Batch (symbols=A,B,C) fetchers
# ---------------------------------------------------------------------------


class FMPCachedMarketCapBatchFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedMarketCapData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/market-capitalization-batch`` (#1091)."""

    _path = "market-capitalization-batch"
    _data_cls = FMPCachedMarketCapData
    _alias_map = _MARKET_CAP_ALIASES
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch (batch)."""
        return await FMPCachedMarketCapBatchFetcher._fetch(query.symbols, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedMarketCapData]:
        """Map raw rows to typed market-cap data."""
        return FMPCachedMarketCapBatchFetcher._transform(data)


class FMPCachedBatchQuoteFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedQuoteData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/batch-quote`` (#1250)."""

    _path = "batch-quote"
    _data_cls = FMPCachedQuoteData
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch (batch)."""
        return await FMPCachedBatchQuoteFetcher._fetch(query.symbols, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedQuoteData]:
        """Map raw rows to typed quote data."""
        return FMPCachedBatchQuoteFetcher._transform(data)


class FMPCachedBatchQuoteShortFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedQuoteShortData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/batch-quote-short`` (#1251)."""

    _path = "batch-quote-short"
    _data_cls = FMPCachedQuoteShortData
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch (batch)."""
        return await FMPCachedBatchQuoteShortFetcher._fetch(query.symbols, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedQuoteShortData]:
        """Map raw rows to typed short-quote data."""
        return FMPCachedBatchQuoteShortFetcher._transform(data)


class FMPCachedBatchAftermarketTradeFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedAftermarketTradeData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/batch-aftermarket-trade`` (#1252)."""

    _path = "batch-aftermarket-trade"
    _data_cls = FMPCachedAftermarketTradeData
    _alias_map = _AFTERMARKET_TRADE_ALIASES
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch (batch aftermarket)."""
        return await FMPCachedBatchAftermarketTradeFetcher._fetch(
            query.symbols, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAftermarketTradeData]:
        """Map raw rows to typed aftermarket-trade data."""
        return FMPCachedBatchAftermarketTradeFetcher._transform(data)


class FMPCachedBatchAftermarketQuoteFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedAftermarketQuoteData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/batch-aftermarket-quote`` (#1253)."""

    _path = "batch-aftermarket-quote"
    _data_cls = FMPCachedAftermarketQuoteData
    _alias_map = _AFTERMARKET_QUOTE_ALIASES
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch (batch aftermarket)."""
        return await FMPCachedBatchAftermarketQuoteFetcher._fetch(
            query.symbols, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAftermarketQuoteData]:
        """Map raw rows to typed aftermarket-quote data."""
        return FMPCachedBatchAftermarketQuoteFetcher._transform(data)


# ---------------------------------------------------------------------------
# No-param
# ---------------------------------------------------------------------------


class FMPCachedAllExchangeMarketHoursFetcher(
    Fetcher[_NoParams, list[FMPCachedExchangeMarketHoursData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/all-exchange-market-hours`` (#1225).

    No-param — reuses _SearchFetcherBase._fetch but passes an empty
    string as the query value. FMP ignores an empty ``query=`` param
    (the empty query on /stable/all-exchange-market-hours behaves as
    "return all rows").
    """

    _path = "all-exchange-market-hours"
    _data_cls = FMPCachedExchangeMarketHoursData
    _query_field = "unused"  # sent as unused="" — FMP ignores unknowns

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into typed no-param object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedAllExchangeMarketHoursFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedExchangeMarketHoursData]:
        """Map raw rows to typed exchange-hours data."""
        return FMPCachedAllExchangeMarketHoursFetcher._transform(data)
