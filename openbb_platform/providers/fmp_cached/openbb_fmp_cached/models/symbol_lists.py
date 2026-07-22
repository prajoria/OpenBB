"""Cached FMP symbol-directory listings — stock/etf/actively-trading/financial-statement/CIK lists.

Wave 4 Directory drain, batch 2 (#1045 #1046 #1047 #1049 #1050).

FMP's ``/stable/*-list`` endpoints return large but bounded symbol
directories: ~50k stocks, ~10k ETFs, ~34k actively-trading, ~33k
financial-statement-eligible tickers, and the CIK master list.

Same architectural pattern as ``available_directories.py`` (#1052-#1055):
- One module with N fetchers sharing a base mixin.
- Native fetchers, no ``openbb_fmp`` wrap.
- Persistent MySQL mirror; TRUNCATE + INSERT on refresh.
- Loud empty (raises, doesn't silently cache).
- ``raise_for_status_redacted`` for apikey scrubbing.

Response shape notes:
- ``stock-list``: {symbol, companyName}
- ``etf-list``: {symbol, name}  (note: ``name`` not ``companyName``)
- ``actively-trading-list``: {symbol, name}
- ``financial-statement-symbol-list``: {symbol, companyName, tradingCurrency, reportingCurrency}
- ``cik-list``: {cik, companyName}  (no symbol field; keyed by CIK)
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field

from openbb_fmp_cached.models.available_directories import (
    _fetch_directory,
    _persist_directory,
    _resolve_api_key,
)

logger = logging.getLogger(__name__)


class _EmptyQueryParams(QueryParams):
    """Symbol-list endpoints take no parameters."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedStockListData(Data):
    """One row from ``/stable/stock-list``."""

    symbol: str = Field(description="Ticker symbol.")
    company_name: str | None = Field(default=None, description="Company name.")


class FMPCachedEtfListData(Data):
    """One row from ``/stable/etf-list``."""

    symbol: str = Field(description="ETF ticker symbol.")
    name: str | None = Field(default=None, description="ETF name.")


class FMPCachedActivelyTradingListData(Data):
    """One row from ``/stable/actively-trading-list``."""

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Instrument name.")


class FMPCachedFinancialStatementSymbolData(Data):
    """One row from ``/stable/financial-statement-symbol-list``."""

    symbol: str = Field(description="Ticker symbol.")
    company_name: str | None = Field(default=None, description="Company name.")
    trading_currency: str | None = Field(default=None, description="Trading currency.")
    reporting_currency: str | None = Field(
        default=None, description="Reporting currency."
    )


class FMPCachedCikListData(Data):
    """One row from ``/stable/cik-list``."""

    cik: str = Field(description="SEC CIK (zero-padded string).")
    company_name: str | None = Field(default=None, description="Company name.")


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _SymbolListFetcherBase:
    """Shared logic for the 5 symbol-list fetchers. Not a public ABC."""

    _path: str = ""
    _table: str = ""
    _data_cls: type[Data] = Data
    _alias_map: dict[str, str] = {}

    @classmethod
    async def _shared_extract(cls, credentials: dict[str, str] | None) -> list[dict]:
        api_key = _resolve_api_key(credentials)
        rows = await _fetch_directory(cls._path, api_key)
        if not rows:
            raise RuntimeError(
                f"{cls._path}: FMP returned empty list — likely tier or API issue"
            )
        _persist_directory(cls._table, "data_json", rows)
        return rows

    @classmethod
    def _shared_transform(
        cls, query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[Data]:
        out = []
        for row in data:
            mapped = {cls._alias_map.get(k, k): v for k, v in row.items()}
            out.append(cls._data_cls.model_validate(mapped))
        return out


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


class FMPCachedStockListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedStockListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/stock-list`` (#1045)."""

    _path = "stock-list"
    _table = "stock_list"
    _data_cls = FMPCachedStockListData
    _alias_map = {"companyName": "company_name"}

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full stock symbol list."""
        return await FMPCachedStockListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedStockListData]:
        """Map raw JSON rows to typed stock-list data."""
        return FMPCachedStockListFetcher._shared_transform(query, data, **kwargs)


class FMPCachedEtfListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedEtfListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/etf-list`` (#1049)."""

    _path = "etf-list"
    _table = "etf_list"
    _data_cls = FMPCachedEtfListData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full ETF symbol list."""
        return await FMPCachedEtfListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedEtfListData]:
        """Map raw JSON rows to typed ETF-list data."""
        return FMPCachedEtfListFetcher._shared_transform(query, data, **kwargs)


class FMPCachedActivelyTradingListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedActivelyTradingListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/actively-trading-list`` (#1050)."""

    _path = "actively-trading-list"
    _table = "actively_trading_list"
    _data_cls = FMPCachedActivelyTradingListData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full actively-trading symbol list."""
        return await FMPCachedActivelyTradingListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedActivelyTradingListData]:
        """Map raw JSON rows to typed actively-trading data."""
        return FMPCachedActivelyTradingListFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedFinancialStatementSymbolListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedFinancialStatementSymbolData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/financial-statement-symbol-list`` (#1046)."""

    _path = "financial-statement-symbol-list"
    _table = "financial_statement_symbol_list"
    _data_cls = FMPCachedFinancialStatementSymbolData
    _alias_map = {
        "companyName": "company_name",
        "tradingCurrency": "trading_currency",
        "reportingCurrency": "reporting_currency",
    }

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the financial-statement-symbol list."""
        return await FMPCachedFinancialStatementSymbolListFetcher._shared_extract(
            credentials
        )

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedFinancialStatementSymbolData]:
        """Map raw JSON rows to typed financial-statement-symbol data."""
        return FMPCachedFinancialStatementSymbolListFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedCikListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedCikListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/cik-list`` (#1047)."""

    _path = "cik-list"
    _table = "cik_list"
    _data_cls = FMPCachedCikListData
    _alias_map = {"companyName": "company_name"}

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the CIK master list."""
        return await FMPCachedCikListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCikListData]:
        """Map raw JSON rows to typed CIK-list data."""
        return FMPCachedCikListFetcher._shared_transform(query, data, **kwargs)
