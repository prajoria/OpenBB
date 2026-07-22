"""Cached FMP reference-directory listings — index constituents + COT + risk premium.

Wave 4 Directory drain, batch 4 (#1102 #1110 #1167 #1168 #1169).

Five more no-param FMP directories, all Free-tier:

- ``sp500-constituent`` (#1167) — 503 S&P 500 members w/ sector + CIK
- ``nasdaq-constituent`` (#1168) — 102 NASDAQ-100 members (same shape)
- ``dowjones-constituent`` (#1169) — 30 Dow Jones members (same shape)
- ``commitment-of-traders-list`` (#1102) — 65 CFTC-reported instruments
- ``market-risk-premium`` (#1110) — 192 country-level ERP measurements

Same pattern as batches 2+3 (symbol_lists.py, market_directories.py):
- One module, N fetchers sharing ``_SymbolListFetcherBase``.
- Native fetchers, no ``openbb_fmp`` wrap.
- Persistent MySQL mirror; TRUNCATE + INSERT on refresh.
- Loud empty (raises, doesn't silently cache).
- ``raise_for_status_redacted`` for apikey scrubbing.

The 3 index constituents share a data shape (symbol/name/sector/
subSector/headQuarter/dateFirstAdded/cik/founded) so they share one
Data class ``FMPCachedIndexConstituentData`` — a fetcher-level
overload picks the right endpoint.
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


class FMPCachedIndexConstituentData(Data):
    """One row from an FMP index-constituent endpoint (S&P/NASDAQ/DJIA)."""

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Company name.")
    sector: str | None = Field(default=None, description="GICS sector.")
    sub_sector: str | None = Field(
        default=None, description="GICS sub-sector / industry."
    )
    head_quarter: str | None = Field(default=None, description="Headquarters location.")
    date_first_added: str | None = Field(
        default=None, description="Date first added to the index."
    )
    cik: str | None = Field(default=None, description="SEC CIK (zero-padded).")
    founded: str | None = Field(default=None, description="Company founding date.")


class FMPCachedCotListData(Data):
    """One row from ``/stable/commitment-of-traders-list``."""

    symbol: str = Field(description="CFTC symbol (e.g. 'NG').")
    name: str | None = Field(default=None, description="Instrument name.")


class FMPCachedMarketRiskPremiumData(Data):
    """One row from ``/stable/market-risk-premium``."""

    country: str = Field(description="Country name.")
    continent: str | None = Field(default=None, description="Continent.")
    country_risk_premium: float | None = Field(
        default=None, description="Country risk premium (%)."
    )
    total_equity_risk_premium: float | None = Field(
        default=None, description="Total equity risk premium (%)."
    )


# ---------------------------------------------------------------------------
# Fetchers — 3 index constituents share a Data class
# ---------------------------------------------------------------------------


_INDEX_CONSTITUENT_ALIASES = {
    "subSector": "sub_sector",
    "headQuarter": "head_quarter",
    "dateFirstAdded": "date_first_added",
}


class FMPCachedSp500ConstituentFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedIndexConstituentData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/sp500-constituent`` (#1167)."""

    _path = "sp500-constituent"
    _table = "sp500_constituent"
    _data_cls = FMPCachedIndexConstituentData
    _alias_map = _INDEX_CONSTITUENT_ALIASES

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
        """Fetch + persist the S&P 500 constituent list."""
        return await FMPCachedSp500ConstituentFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedIndexConstituentData]:
        """Map raw JSON rows to typed S&P 500 constituent data."""
        return FMPCachedSp500ConstituentFetcher._shared_transform(query, data, **kwargs)


class FMPCachedNasdaqConstituentFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedIndexConstituentData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/nasdaq-constituent`` (#1168)."""

    _path = "nasdaq-constituent"
    _table = "nasdaq_constituent"
    _data_cls = FMPCachedIndexConstituentData
    _alias_map = _INDEX_CONSTITUENT_ALIASES

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
        """Fetch + persist the NASDAQ-100 constituent list."""
        return await FMPCachedNasdaqConstituentFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedIndexConstituentData]:
        """Map raw JSON rows to typed NASDAQ-100 constituent data."""
        return FMPCachedNasdaqConstituentFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedDowjonesConstituentFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedIndexConstituentData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/dowjones-constituent`` (#1169)."""

    _path = "dowjones-constituent"
    _table = "dowjones_constituent"
    _data_cls = FMPCachedIndexConstituentData
    _alias_map = _INDEX_CONSTITUENT_ALIASES

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
        """Fetch + persist the Dow Jones constituent list."""
        return await FMPCachedDowjonesConstituentFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedIndexConstituentData]:
        """Map raw JSON rows to typed DJIA constituent data."""
        return FMPCachedDowjonesConstituentFetcher._shared_transform(
            query, data, **kwargs
        )


# ---------------------------------------------------------------------------
# COT + market-risk-premium — distinct shapes
# ---------------------------------------------------------------------------


class FMPCachedCotListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedCotListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/commitment-of-traders-list`` (#1102)."""

    _path = "commitment-of-traders-list"
    _table = "commitment_of_traders_list"
    _data_cls = FMPCachedCotListData

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
        """Fetch + persist the CFTC COT symbol list."""
        return await FMPCachedCotListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCotListData]:
        """Map raw JSON rows to typed COT list data."""
        return FMPCachedCotListFetcher._shared_transform(query, data, **kwargs)


class FMPCachedMarketRiskPremiumFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedMarketRiskPremiumData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/market-risk-premium`` (#1110)."""

    _path = "market-risk-premium"
    _table = "market_risk_premium"
    _data_cls = FMPCachedMarketRiskPremiumData
    _alias_map = {
        "countryRiskPremium": "country_risk_premium",
        "totalEquityRiskPremium": "total_equity_risk_premium",
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
        """Fetch + persist the country-level market risk-premium list."""
        return await FMPCachedMarketRiskPremiumFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedMarketRiskPremiumData]:
        """Map raw JSON rows to typed market-risk-premium data."""
        return FMPCachedMarketRiskPremiumFetcher._shared_transform(
            query, data, **kwargs
        )
