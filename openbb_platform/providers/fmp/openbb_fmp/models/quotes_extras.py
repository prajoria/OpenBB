"""FMP quotes-extras endpoints — 9 fetchers.

Port of 9 quotes-domain endpoints to the plain ``fmp`` provider under
Tier-A parity (#1506-#1514).

Endpoints (multi-symbol — takes ``symbols=A,B,C``):
- ``batch-quote``                   (#1506)
- ``batch-quote-short``             (#1507)
- ``batch-aftermarket-quote``       (#1508)
- ``batch-aftermarket-trade``       (#1509)
- ``market-capitalization-batch``   (#1514)

Endpoints (single-symbol — takes ``symbol=X``):
- ``quote``                         (#1510)
- ``quote-short``                   (#1511)
- ``stock-price-change``            (#1512)
- ``market-capitalization``         (#1513)

Design note: unlike the ``fmp_cached`` copies these do NOT cache.
Every call hits FMP live.
"""

# pylint: disable=unused-argument

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_core.provider.utils.helpers import amake_request
from pydantic import ConfigDict, Field

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class FMPQuoteSymbolQueryParams(QueryParams):
    """Single-symbol query parameters shared by 4 single-symbol quotes endpoints."""

    symbol: str = Field(description="Ticker symbol.")


class FMPQuoteSymbolsQueryParams(QueryParams):
    """Multi-symbol query parameters shared by 5 batch quotes endpoints.

    Accepts a comma-separated list of tickers OR a Python ``list[str]``;
    the latter is joined with commas before being passed to FMP.
    """

    symbols: str | list[str] = Field(
        description="Comma-separated tickers or list of tickers.",
    )


def _symbols_to_csv(value: str | list[str]) -> str:
    """Coerce list or scalar to a comma-separated string for FMP."""
    if isinstance(value, list):
        return ",".join(str(v).strip() for v in value if v)
    return str(value)


# ---------------------------------------------------------------------------
# Data models. All use ``extra=allow`` so schema drift on FMP's side
# doesn't break the fetcher for the fields we DO map.
# ---------------------------------------------------------------------------


class FMPBatchQuoteData(Data):
    """Row from ``/stable/batch-quote`` (#1506)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPBatchQuoteShortData(Data):
    """Row from ``/stable/batch-quote-short`` (#1507)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPBatchAftermarketQuoteData(Data):
    """Row from ``/stable/batch-aftermarket-quote`` (#1508)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPBatchAftermarketTradeData(Data):
    """Row from ``/stable/batch-aftermarket-trade`` (#1509)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPStockQuoteData(Data):
    """Row from ``/stable/quote`` (#1510)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPStockQuoteShortData(Data):
    """Row from ``/stable/quote-short`` (#1511)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPStockPriceChangeData(Data):
    """Row from ``/stable/stock-price-change`` (#1512)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPMarketCapData(Data):
    """Row from ``/stable/market-capitalization`` (#1513)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPMarketCapBatchData(Data):
    """Row from ``/stable/market-capitalization-batch`` (#1514)."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


# ---------------------------------------------------------------------------
# Shared fetch helper — same pattern as analyst_ratings.py.
# ---------------------------------------------------------------------------


async def _fmp_stable_get(
    path: str, params: dict[str, Any], credentials: dict[str, str] | None
) -> list[dict]:
    """GET ``/stable/<path>?<params>&apikey=<K>`` and return the JSON list.

    Routes apikey through ``params`` (not URL) so it stays out of
    tracebacks and proxy logs. Raises ``EmptyDataError`` when FMP
    returns a non-list payload.
    """
    api_key = (credentials or {}).get("fmp_api_key", "")
    url = f"{_FMP_STABLE_BASE}/{path}"
    full_params = {**params, "apikey": api_key}
    payload = await amake_request(url, params=full_params)
    if not isinstance(payload, list):
        raise EmptyDataError(
            f"{path}: unexpected response shape from FMP "
            f"(got {type(payload).__name__}; expected list)."
        )
    return payload


# ---------------------------------------------------------------------------
# Single-symbol fetchers (4)
# ---------------------------------------------------------------------------


class FMPStockQuoteFetcher(Fetcher[FMPQuoteSymbolQueryParams, list[FMPStockQuoteData]]):
    """Fetcher for ``/stable/quote`` (#1510)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("quote", {"symbol": query.symbol}, credentials)

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPStockQuoteData]:
        """Map raw rows to typed model instances."""
        return [FMPStockQuoteData.model_validate(r) for r in data]


class FMPStockQuoteShortFetcher(
    Fetcher[FMPQuoteSymbolQueryParams, list[FMPStockQuoteShortData]]
):
    """Fetcher for ``/stable/quote-short`` (#1511)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get(
            "quote-short", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPStockQuoteShortData]:
        """Map raw rows to typed model instances."""
        return [FMPStockQuoteShortData.model_validate(r) for r in data]


class FMPStockPriceChangeFetcher(
    Fetcher[FMPQuoteSymbolQueryParams, list[FMPStockPriceChangeData]]
):
    """Fetcher for ``/stable/stock-price-change`` (#1512)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get(
            "stock-price-change", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPStockPriceChangeData]:
        """Map raw rows to typed model instances."""
        return [FMPStockPriceChangeData.model_validate(r) for r in data]


class FMPMarketCapFetcher(Fetcher[FMPQuoteSymbolQueryParams, list[FMPMarketCapData]]):
    """Fetcher for ``/stable/market-capitalization`` (#1513)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get(
            "market-capitalization", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPMarketCapData]:
        """Map raw rows to typed model instances."""
        return [FMPMarketCapData.model_validate(r) for r in data]


# ---------------------------------------------------------------------------
# Multi-symbol fetchers (5)
# ---------------------------------------------------------------------------


class FMPBatchQuoteFetcher(
    Fetcher[FMPQuoteSymbolsQueryParams, list[FMPBatchQuoteData]]
):
    """Fetcher for ``/stable/batch-quote`` (#1506)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolsQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol list."""
        return await _fmp_stable_get(
            "batch-quote", {"symbols": _symbols_to_csv(query.symbols)}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPBatchQuoteData]:
        """Map raw rows to typed model instances."""
        return [FMPBatchQuoteData.model_validate(r) for r in data]


class FMPBatchQuoteShortFetcher(
    Fetcher[FMPQuoteSymbolsQueryParams, list[FMPBatchQuoteShortData]]
):
    """Fetcher for ``/stable/batch-quote-short`` (#1507)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolsQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol list."""
        return await _fmp_stable_get(
            "batch-quote-short",
            {"symbols": _symbols_to_csv(query.symbols)},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPBatchQuoteShortData]:
        """Map raw rows to typed model instances."""
        return [FMPBatchQuoteShortData.model_validate(r) for r in data]


class FMPBatchAftermarketQuoteFetcher(
    Fetcher[FMPQuoteSymbolsQueryParams, list[FMPBatchAftermarketQuoteData]]
):
    """Fetcher for ``/stable/batch-aftermarket-quote`` (#1508)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolsQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol list."""
        return await _fmp_stable_get(
            "batch-aftermarket-quote",
            {"symbols": _symbols_to_csv(query.symbols)},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPBatchAftermarketQuoteData]:
        """Map raw rows to typed model instances."""
        return [FMPBatchAftermarketQuoteData.model_validate(r) for r in data]


class FMPBatchAftermarketTradeFetcher(
    Fetcher[FMPQuoteSymbolsQueryParams, list[FMPBatchAftermarketTradeData]]
):
    """Fetcher for ``/stable/batch-aftermarket-trade`` (#1509)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolsQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol list."""
        return await _fmp_stable_get(
            "batch-aftermarket-trade",
            {"symbols": _symbols_to_csv(query.symbols)},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPBatchAftermarketTradeData]:
        """Map raw rows to typed model instances."""
        return [FMPBatchAftermarketTradeData.model_validate(r) for r in data]


class FMPMarketCapBatchFetcher(
    Fetcher[FMPQuoteSymbolsQueryParams, list[FMPMarketCapBatchData]]
):
    """Fetcher for ``/stable/market-capitalization-batch`` (#1514)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQuoteSymbolsQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPQuoteSymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQuoteSymbolsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol list."""
        return await _fmp_stable_get(
            "market-capitalization-batch",
            {"symbols": _symbols_to_csv(query.symbols)},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPQuoteSymbolsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPMarketCapBatchData]:
        """Map raw rows to typed model instances."""
        return [FMPMarketCapBatchData.model_validate(r) for r in data]
