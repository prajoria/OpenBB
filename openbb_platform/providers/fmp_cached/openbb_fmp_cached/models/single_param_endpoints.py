"""Cached FMP single-param fetchers — company-notes, executive-compensation-benchmark, holidays-by-exchange.

Wave 4 finish (#1085 #1099 #1224). Three endpoints each taking exactly
one query parameter. Reuses ``_SearchFetcherBase`` from
``search_endpoints.py`` (which is already generic enough — it just
needs the caller to set ``_query_field`` and a matching ``QueryParams``
class).

Endpoints:
- ``company-notes`` (#1085) — ``symbol=<TICKER>`` — bond/note disclosures
- ``executive-compensation-benchmark`` (#1099) — ``year=<YYYY>`` — industry avg
- ``holidays-by-exchange`` (#1224) — ``exchange=<CODE>`` — market holidays
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field

from openbb_fmp_cached.models.search_endpoints import _SearchFetcherBase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class _SymbolQueryParams(QueryParams):
    """Query params for endpoints keyed by ticker symbol."""

    symbol: str = Field(description="Ticker symbol.")


class _YearQueryParams(QueryParams):
    """Query params for endpoints keyed by year."""

    year: int = Field(description="Reporting year (4-digit).")


class _ExchangeQueryParams(QueryParams):
    """Query params for endpoints keyed by exchange code."""

    exchange: str = Field(description="Exchange short code (e.g. 'NYSE').")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedCompanyNoteData(Data):
    """One row from ``/stable/company-notes``."""

    cik: str | None = Field(default=None, description="SEC CIK (zero-padded).")
    symbol: str = Field(description="Ticker symbol.")
    title: str | None = Field(default=None, description="Note title / description.")
    exchange: str | None = Field(default=None, description="Exchange short code.")


class FMPCachedExecutiveCompensationBenchmarkData(Data):
    """One row from ``/stable/executive-compensation-benchmark``."""

    industry_title: str = Field(description="Industry name (SIC-classified).")
    year: int = Field(description="Reporting year.")
    average_compensation: float | None = Field(
        default=None, description="Industry-average executive compensation."
    )


class FMPCachedHolidayData(Data):
    """One row from ``/stable/holidays-by-exchange``."""

    exchange: str = Field(description="Exchange short code.")
    date: str = Field(description="Holiday date YYYY-MM-DD.")
    name: str | None = Field(default=None, description="Holiday name.")
    is_closed: bool | None = Field(
        default=None, description="True if exchange fully closed."
    )
    adj_open_time: str | None = Field(
        default=None, description="Adjusted open time (or null)."
    )
    adj_close_time: str | None = Field(
        default=None, description="Adjusted close time (or null)."
    )


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


class FMPCachedCompanyNotesFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedCompanyNoteData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/company-notes`` (#1085)."""

    _path = "company-notes"
    _data_cls = FMPCachedCompanyNoteData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for company-notes."""
        return await FMPCachedCompanyNotesFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCompanyNoteData]:
        """Map raw rows to typed company-note data."""
        return FMPCachedCompanyNotesFetcher._transform(data)


class FMPCachedExecutiveCompensationBenchmarkFetcher(
    Fetcher[_YearQueryParams, list[FMPCachedExecutiveCompensationBenchmarkData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/executive-compensation-benchmark`` (#1099)."""

    _path = "executive-compensation-benchmark"
    _data_cls = FMPCachedExecutiveCompensationBenchmarkData
    _alias_map = {
        "industryTitle": "industry_title",
        "averageCompensation": "average_compensation",
    }
    _query_field = "year"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _YearQueryParams:
        """Coerce raw params dict into the typed year-query object."""
        return _YearQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _YearQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for executive-compensation-benchmark."""
        return await FMPCachedExecutiveCompensationBenchmarkFetcher._fetch(
            str(query.year), credentials
        )

    @staticmethod
    def transform_data(
        query: _YearQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedExecutiveCompensationBenchmarkData]:
        """Map raw rows to typed benchmark data."""
        return FMPCachedExecutiveCompensationBenchmarkFetcher._transform(data)


class FMPCachedHolidaysByExchangeFetcher(
    Fetcher[_ExchangeQueryParams, list[FMPCachedHolidayData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/holidays-by-exchange`` (#1224)."""

    _path = "holidays-by-exchange"
    _data_cls = FMPCachedHolidayData
    _alias_map = {
        "isClosed": "is_closed",
        "adjOpenTime": "adj_open_time",
        "adjCloseTime": "adj_close_time",
    }
    _query_field = "exchange"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _ExchangeQueryParams:
        """Coerce raw params dict into the typed exchange-query object."""
        return _ExchangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _ExchangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for holidays-by-exchange."""
        return await FMPCachedHolidaysByExchangeFetcher._fetch(
            query.exchange, credentials
        )

    @staticmethod
    def transform_data(
        query: _ExchangeQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHolidayData]:
        """Map raw rows to typed holiday data."""
        return FMPCachedHolidaysByExchangeFetcher._transform(data)
