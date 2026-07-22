"""Cached FMP historical & change directories — historical constituents, symbol-change, shares-float-all.

Wave 4 Directory drain, batch 5 (#1048 #1094 #1170 #1171 #1172).

Five no-param FMP endpoints, all Free-tier:

- ``historical-sp500-constituent`` (#1170) — 1,523 S&P membership changes
- ``historical-nasdaq-constituent`` (#1171) — 444 NASDAQ-100 changes
- ``historical-dowjones-constituent`` (#1172) — 86 DJIA changes (small)
- ``symbol-change`` (#1048) — 100 recent ticker changes
- ``shares-float-all`` (#1094) — 1,000 shares-float snapshots (paged)

Same architecture as batches 2-4. The 3 historical-constituent
endpoints share a Data class ``FMPCachedHistoricalConstituentData``.
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from pydantic import Field

from openbb_fmp_cached.models.symbol_lists import (
    _EmptyQueryParams,
    _SymbolListFetcherBase,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedHistoricalConstituentData(Data):
    """One row from an FMP historical index-constituent endpoint."""

    date: str = Field(description="Event date YYYY-MM-DD.")
    date_added: str | None = Field(default=None, description="Human-readable date.")
    added_security: str | None = Field(default=None, description="Added security name.")
    removed_ticker: str | None = Field(default=None, description="Removed ticker.")
    removed_security: str | None = Field(
        default=None, description="Removed security name."
    )
    symbol: str | None = Field(default=None, description="Added ticker.")
    reason: str | None = Field(default=None, description="Change reason.")


class FMPCachedSymbolChangeData(Data):
    """One row from ``/stable/symbol-change``."""

    date: str = Field(description="Event date YYYY-MM-DD.")
    company_name: str | None = Field(default=None, description="Company name.")
    old_symbol: str | None = Field(default=None, description="Prior ticker.")
    new_symbol: str | None = Field(default=None, description="New ticker.")


class FMPCachedSharesFloatAllData(Data):
    """One row from ``/stable/shares-float-all``."""

    symbol: str = Field(description="Ticker symbol.")
    date: str | None = Field(default=None, description="Snapshot datetime.")
    free_float: float | None = Field(default=None, description="Free float (%).")
    float_shares: int | None = Field(default=None, description="Float shares (count).")
    outstanding_shares: int | None = Field(
        default=None, description="Outstanding shares (count)."
    )


# ---------------------------------------------------------------------------
# Fetchers — 3 historical constituents share a Data class
# ---------------------------------------------------------------------------


_HISTORICAL_ALIASES = {
    "dateAdded": "date_added",
    "addedSecurity": "added_security",
    "removedTicker": "removed_ticker",
    "removedSecurity": "removed_security",
}


class FMPCachedHistoricalSp500ConstituentFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedHistoricalConstituentData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/historical-sp500-constituent`` (#1170)."""

    _path = "historical-sp500-constituent"
    _table = "historical_sp500_constituent"
    _data_cls = FMPCachedHistoricalConstituentData
    _alias_map = _HISTORICAL_ALIASES

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
        """Fetch + persist historical S&P 500 constituent changes."""
        return await FMPCachedHistoricalSp500ConstituentFetcher._shared_extract(
            credentials
        )

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalConstituentData]:
        """Map raw JSON rows to typed historical S&P constituent data."""
        return FMPCachedHistoricalSp500ConstituentFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedHistoricalNasdaqConstituentFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedHistoricalConstituentData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/historical-nasdaq-constituent`` (#1171)."""

    _path = "historical-nasdaq-constituent"
    _table = "historical_nasdaq_constituent"
    _data_cls = FMPCachedHistoricalConstituentData
    _alias_map = _HISTORICAL_ALIASES

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
        """Fetch + persist historical NASDAQ-100 constituent changes."""
        return await FMPCachedHistoricalNasdaqConstituentFetcher._shared_extract(
            credentials
        )

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalConstituentData]:
        """Map raw JSON rows to typed historical NASDAQ constituent data."""
        return FMPCachedHistoricalNasdaqConstituentFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedHistoricalDowjonesConstituentFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedHistoricalConstituentData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/historical-dowjones-constituent`` (#1172)."""

    _path = "historical-dowjones-constituent"
    _table = "historical_dowjones_constituent"
    _data_cls = FMPCachedHistoricalConstituentData
    _alias_map = _HISTORICAL_ALIASES

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
        """Fetch + persist historical DJIA constituent changes."""
        return await FMPCachedHistoricalDowjonesConstituentFetcher._shared_extract(
            credentials
        )

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalConstituentData]:
        """Map raw JSON rows to typed historical DJIA constituent data."""
        return FMPCachedHistoricalDowjonesConstituentFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedSymbolChangeFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedSymbolChangeData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/symbol-change`` (#1048)."""

    _path = "symbol-change"
    _table = "symbol_change"
    _data_cls = FMPCachedSymbolChangeData
    _alias_map = {
        "companyName": "company_name",
        "oldSymbol": "old_symbol",
        "newSymbol": "new_symbol",
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
        """Fetch + persist the recent symbol-change list."""
        return await FMPCachedSymbolChangeFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSymbolChangeData]:
        """Map raw JSON rows to typed symbol-change data."""
        return FMPCachedSymbolChangeFetcher._shared_transform(query, data, **kwargs)


class FMPCachedSharesFloatAllFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedSharesFloatAllData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/shares-float-all`` (#1094)."""

    _path = "shares-float-all"
    _table = "shares_float_all"
    _data_cls = FMPCachedSharesFloatAllData
    _alias_map = {
        "freeFloat": "free_float",
        "floatShares": "float_shares",
        "outstandingShares": "outstanding_shares",
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
        """Fetch + persist the shares-float-all snapshot (first page)."""
        return await FMPCachedSharesFloatAllFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSharesFloatAllData]:
        """Map raw JSON rows to typed shares-float data."""
        return FMPCachedSharesFloatAllFetcher._shared_transform(query, data, **kwargs)
