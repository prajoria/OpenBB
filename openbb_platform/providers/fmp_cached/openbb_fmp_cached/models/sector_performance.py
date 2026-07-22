"""Cached FMP sector / industry performance & PE endpoints — 8 fetchers.

Wave 7 MarketPerformance drain (#1212-#1219).

Two families of 4 endpoints each:

**Date-snapshot family** (param: ``date=YYYY-MM-DD``):
- ``sector-performance-snapshot`` (#1212)
- ``industry-performance-snapshot`` (#1213)
- ``sector-pe-snapshot`` (#1216)
- ``industry-pe-snapshot`` (#1217)

**Historical family** (param: ``sector=Name`` or ``industry=Name``):
- ``historical-sector-performance`` (#1214)
- ``historical-industry-performance`` (#1215)
- ``historical-sector-pe`` (#1218)
- ``historical-industry-pe`` (#1219)

All Free-tier live pass-through, reusing ``_SearchFetcherBase``.
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class _DateQueryParams(QueryParams):
    """Query params for endpoints keyed by ``date=YYYY-MM-DD``."""

    date: str = Field(description="ISO date (YYYY-MM-DD) — must be a market weekday.")


class _SectorQueryParams(QueryParams):
    """Query params for endpoints keyed by ``sector=<Name>``."""

    sector: str = Field(description="Sector name (e.g. 'Technology').")


class _IndustryQueryParams(QueryParams):
    """Query params for endpoints keyed by ``industry=<Name>``."""

    industry: str = Field(description="Industry name (e.g. 'Semiconductors').")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedSectorPerformanceSnapshotData(Data):
    """Row from ``/stable/sector-performance-snapshot``."""

    model_config = ConfigDict(extra="allow")

    date: str = Field(description="Snapshot date.")
    sector: str | None = Field(default=None, description="Sector name.")


class FMPCachedIndustryPerformanceSnapshotData(Data):
    """Row from ``/stable/industry-performance-snapshot``."""

    model_config = ConfigDict(extra="allow")

    date: str = Field(description="Snapshot date.")
    industry: str | None = Field(default=None, description="Industry name.")


class FMPCachedSectorPeSnapshotData(Data):
    """Row from ``/stable/sector-pe-snapshot``."""

    model_config = ConfigDict(extra="allow")

    date: str = Field(description="Snapshot date.")
    sector: str | None = Field(default=None, description="Sector name.")


class FMPCachedIndustryPeSnapshotData(Data):
    """Row from ``/stable/industry-pe-snapshot``."""

    model_config = ConfigDict(extra="allow")

    date: str = Field(description="Snapshot date.")
    industry: str | None = Field(default=None, description="Industry name.")


class FMPCachedHistoricalSectorPerformanceData(Data):
    """Row from ``/stable/historical-sector-performance``."""

    date: str = Field(description="Date.")
    sector: str | None = Field(default=None, description="Sector.")
    exchange: str | None = Field(default=None, description="Exchange.")
    average_change: float | None = Field(
        default=None, description="Sector-avg % change."
    )


class FMPCachedHistoricalIndustryPerformanceData(Data):
    """Row from ``/stable/historical-industry-performance``."""

    date: str = Field(description="Date.")
    industry: str | None = Field(default=None, description="Industry.")
    exchange: str | None = Field(default=None, description="Exchange.")
    average_change: float | None = Field(
        default=None, description="Industry-avg % change."
    )


class FMPCachedHistoricalSectorPeData(Data):
    """Row from ``/stable/historical-sector-pe``."""

    date: str = Field(description="Date.")
    sector: str | None = Field(default=None, description="Sector.")
    exchange: str | None = Field(default=None, description="Exchange.")
    pe: float | None = Field(default=None, description="Sector P/E ratio.")


class FMPCachedHistoricalIndustryPeData(Data):
    """Row from ``/stable/historical-industry-pe``."""

    date: str = Field(description="Date.")
    industry: str | None = Field(default=None, description="Industry.")
    exchange: str | None = Field(default=None, description="Exchange.")
    pe: float | None = Field(default=None, description="Industry P/E ratio.")


_HIST_ALIASES = {"averageChange": "average_change"}


# ---------------------------------------------------------------------------
# Fetchers — 4 date-snapshot + 4 historical
# ---------------------------------------------------------------------------


class FMPCachedSectorPerformanceSnapshotFetcher(
    Fetcher[_DateQueryParams, list[FMPCachedSectorPerformanceSnapshotData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/sector-performance-snapshot`` (#1212)."""

    _path = "sector-performance-snapshot"
    _data_cls = FMPCachedSectorPerformanceSnapshotData
    _query_field = "date"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _DateQueryParams:
        """Coerce raw params dict into the typed date-query object."""
        return _DateQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _DateQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedSectorPerformanceSnapshotFetcher._fetch(
            query.date, credentials
        )

    @staticmethod
    def transform_data(
        query: _DateQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSectorPerformanceSnapshotData]:
        """Map raw rows to typed sector-perf snapshot data."""
        return FMPCachedSectorPerformanceSnapshotFetcher._transform(data)


class FMPCachedIndustryPerformanceSnapshotFetcher(
    Fetcher[_DateQueryParams, list[FMPCachedIndustryPerformanceSnapshotData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/industry-performance-snapshot`` (#1213)."""

    _path = "industry-performance-snapshot"
    _data_cls = FMPCachedIndustryPerformanceSnapshotData
    _query_field = "date"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _DateQueryParams:
        """Coerce raw params dict into the typed date-query object."""
        return _DateQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _DateQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedIndustryPerformanceSnapshotFetcher._fetch(
            query.date, credentials
        )

    @staticmethod
    def transform_data(
        query: _DateQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedIndustryPerformanceSnapshotData]:
        """Map raw rows to typed industry-perf snapshot data."""
        return FMPCachedIndustryPerformanceSnapshotFetcher._transform(data)


class FMPCachedSectorPeSnapshotFetcher(
    Fetcher[_DateQueryParams, list[FMPCachedSectorPeSnapshotData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/sector-pe-snapshot`` (#1216)."""

    _path = "sector-pe-snapshot"
    _data_cls = FMPCachedSectorPeSnapshotData
    _query_field = "date"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _DateQueryParams:
        """Coerce raw params dict into the typed date-query object."""
        return _DateQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _DateQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedSectorPeSnapshotFetcher._fetch(query.date, credentials)

    @staticmethod
    def transform_data(
        query: _DateQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSectorPeSnapshotData]:
        """Map raw rows to typed sector-PE snapshot data."""
        return FMPCachedSectorPeSnapshotFetcher._transform(data)


class FMPCachedIndustryPeSnapshotFetcher(
    Fetcher[_DateQueryParams, list[FMPCachedIndustryPeSnapshotData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/industry-pe-snapshot`` (#1217)."""

    _path = "industry-pe-snapshot"
    _data_cls = FMPCachedIndustryPeSnapshotData
    _query_field = "date"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _DateQueryParams:
        """Coerce raw params dict into the typed date-query object."""
        return _DateQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _DateQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedIndustryPeSnapshotFetcher._fetch(query.date, credentials)

    @staticmethod
    def transform_data(
        query: _DateQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedIndustryPeSnapshotData]:
        """Map raw rows to typed industry-PE snapshot data."""
        return FMPCachedIndustryPeSnapshotFetcher._transform(data)


class FMPCachedHistoricalSectorPerformanceFetcher(
    Fetcher[_SectorQueryParams, list[FMPCachedHistoricalSectorPerformanceData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/historical-sector-performance`` (#1214)."""

    _path = "historical-sector-performance"
    _data_cls = FMPCachedHistoricalSectorPerformanceData
    _alias_map = _HIST_ALIASES
    _query_field = "sector"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SectorQueryParams:
        """Coerce raw params dict into the typed sector-query object."""
        return _SectorQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SectorQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedHistoricalSectorPerformanceFetcher._fetch(
            query.sector, credentials
        )

    @staticmethod
    def transform_data(
        query: _SectorQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalSectorPerformanceData]:
        """Map raw rows to typed historical sector-perf data."""
        return FMPCachedHistoricalSectorPerformanceFetcher._transform(data)


class FMPCachedHistoricalIndustryPerformanceFetcher(
    Fetcher[_IndustryQueryParams, list[FMPCachedHistoricalIndustryPerformanceData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/historical-industry-performance`` (#1215)."""

    _path = "historical-industry-performance"
    _data_cls = FMPCachedHistoricalIndustryPerformanceData
    _alias_map = _HIST_ALIASES
    _query_field = "industry"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _IndustryQueryParams:
        """Coerce raw params dict into the typed industry-query object."""
        return _IndustryQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _IndustryQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedHistoricalIndustryPerformanceFetcher._fetch(
            query.industry, credentials
        )

    @staticmethod
    def transform_data(
        query: _IndustryQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalIndustryPerformanceData]:
        """Map raw rows to typed historical industry-perf data."""
        return FMPCachedHistoricalIndustryPerformanceFetcher._transform(data)


class FMPCachedHistoricalSectorPeFetcher(
    Fetcher[_SectorQueryParams, list[FMPCachedHistoricalSectorPeData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/historical-sector-pe`` (#1218)."""

    _path = "historical-sector-pe"
    _data_cls = FMPCachedHistoricalSectorPeData
    _query_field = "sector"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SectorQueryParams:
        """Coerce raw params dict into the typed sector-query object."""
        return _SectorQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SectorQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedHistoricalSectorPeFetcher._fetch(
            query.sector, credentials
        )

    @staticmethod
    def transform_data(
        query: _SectorQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalSectorPeData]:
        """Map raw rows to typed historical sector-PE data."""
        return FMPCachedHistoricalSectorPeFetcher._transform(data)


class FMPCachedHistoricalIndustryPeFetcher(
    Fetcher[_IndustryQueryParams, list[FMPCachedHistoricalIndustryPeData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/historical-industry-pe`` (#1219)."""

    _path = "historical-industry-pe"
    _data_cls = FMPCachedHistoricalIndustryPeData
    _query_field = "industry"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _IndustryQueryParams:
        """Coerce raw params dict into the typed industry-query object."""
        return _IndustryQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _IndustryQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedHistoricalIndustryPeFetcher._fetch(
            query.industry, credentials
        )

    @staticmethod
    def transform_data(
        query: _IndustryQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedHistoricalIndustryPeData]:
        """Map raw rows to typed historical industry-PE data."""
        return FMPCachedHistoricalIndustryPeFetcher._transform(data)
