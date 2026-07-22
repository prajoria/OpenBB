"""Cached FMP statement family — TTM metrics, scores, growth, DCF, profile-cik.

W1 Statements drain, batch 13 (#1084 #1103 #1104 #1105 #1106 #1132
#1133 #1134 #1135 #1136 #1140 #1141).

12 endpoints, mostly ``symbol=<TICKER>``-keyed statement metrics that
share the `_SearchFetcherBase` mixin. Distinct row shapes so each
fetcher has its own Data class; use `extra=allow` on any endpoint
returning >6 fields to survive FMP schema drift.
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
# Query params — most endpoints reuse _SymbolQueryParams; profile-cik needs cik
# ---------------------------------------------------------------------------


class _CikQueryParams(QueryParams):
    """Query params for CIK-keyed endpoints."""

    cik: str = Field(description="SEC CIK (any leading-zero form).")


# ---------------------------------------------------------------------------
# Data models — one per distinct shape, extra=allow for wide rows
# ---------------------------------------------------------------------------


class FMPCachedTtmMetricsData(Data):
    """Wide TTM/ratio-family row — extra=allow to tolerate FMP schema drift."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


class FMPCachedFinancialScoresData(Data):
    """Row from ``/stable/financial-scores`` — Altman/Piotroski + working capital."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    reported_currency: str | None = Field(
        default=None, description="Reporting currency."
    )
    altman_z_score: float | None = Field(default=None, description="Altman Z-score.")
    piotroski_score: int | None = Field(default=None, description="Piotroski F-score.")


class FMPCachedOwnerEarningsData(Data):
    """Row from ``/stable/owner-earnings`` — fiscal-year-partitioned."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    reported_currency: str | None = Field(default=None, description="Currency.")
    fiscal_year: str | None = Field(default=None, description="Fiscal year.")
    period: str | None = Field(default=None, description="Period label.")
    date: str | None = Field(default=None, description="Report date.")


class FMPCachedEnterpriseValueData(Data):
    """Row from ``/stable/enterprise-values``."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str | None = Field(default=None, description="As-of date.")


class FMPCachedFinancialGrowthData(Data):
    """Row from ``/stable/financial-growth`` — YoY growth per statement line."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str | None = Field(default=None, description="Period end.")
    fiscal_year: str | None = Field(default=None, description="Fiscal year.")
    period: str | None = Field(default=None, description="Period label.")


class FMPCachedFinancialReportsDatesData(Data):
    """Row from ``/stable/financial-reports-dates``."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    fiscal_year: int | None = Field(default=None, description="Fiscal year.")
    period: str | None = Field(default=None, description="Period label.")
    link_json: str | None = Field(default=None, description="JSON report URL.")
    link_xlsx: str | None = Field(default=None, description="XLSX report URL.")


class FMPCachedDcfData(Data):
    """Row from ``/stable/discounted-cash-flow`` (+ levered variant)."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str | None = Field(default=None, description="Valuation date.")
    dcf: float | None = Field(default=None, description="DCF fair value estimate.")


class FMPCachedCustomDcfData(Data):
    """Row from ``/stable/custom-discounted-cash-flow`` (+ levered)."""

    model_config = ConfigDict(extra="allow")

    year: str = Field(description="Projection year (as returned by FMP).")
    symbol: str = Field(description="Ticker symbol.")


class FMPCachedProfileCikData(Data):
    """Row from ``/stable/profile-cik`` — same shape as profile."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


# Shared alias maps
_TTM_ALIASES = {
    "reportedCurrency": "reported_currency",
    "fiscalYear": "fiscal_year",
    "altmanZScore": "altman_z_score",
    "piotroskiScore": "piotroski_score",
    "linkJson": "link_json",
    "linkXlsx": "link_xlsx",
}


# ---------------------------------------------------------------------------
# Fetchers — symbol-keyed, live pass-through
# ---------------------------------------------------------------------------


class FMPCachedKeyMetricsTtmFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedTtmMetricsData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/key-metrics-ttm`` (#1132)."""

    _path = "key-metrics-ttm"
    _data_cls = FMPCachedTtmMetricsData
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
        return await FMPCachedKeyMetricsTtmFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedTtmMetricsData]:
        """Map raw rows to typed TTM data."""
        return FMPCachedKeyMetricsTtmFetcher._transform(data)


class FMPCachedRatiosTtmFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedTtmMetricsData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/ratios-ttm`` (#1133)."""

    _path = "ratios-ttm"
    _data_cls = FMPCachedTtmMetricsData
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
        return await FMPCachedRatiosTtmFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedTtmMetricsData]:
        """Map raw rows to typed TTM ratios data."""
        return FMPCachedRatiosTtmFetcher._transform(data)


class FMPCachedFinancialScoresFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedFinancialScoresData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/financial-scores`` (#1134)."""

    _path = "financial-scores"
    _data_cls = FMPCachedFinancialScoresData
    _alias_map = _TTM_ALIASES
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
        return await FMPCachedFinancialScoresFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedFinancialScoresData]:
        """Map raw rows to typed financial-scores data."""
        return FMPCachedFinancialScoresFetcher._transform(data)


class FMPCachedOwnerEarningsFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedOwnerEarningsData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/owner-earnings`` (#1135)."""

    _path = "owner-earnings"
    _data_cls = FMPCachedOwnerEarningsData
    _alias_map = _TTM_ALIASES
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
        return await FMPCachedOwnerEarningsFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedOwnerEarningsData]:
        """Map raw rows to typed owner-earnings data."""
        return FMPCachedOwnerEarningsFetcher._transform(data)


class FMPCachedEnterpriseValuesFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedEnterpriseValueData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/enterprise-values`` (#1136)."""

    _path = "enterprise-values"
    _data_cls = FMPCachedEnterpriseValueData
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
        return await FMPCachedEnterpriseValuesFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedEnterpriseValueData]:
        """Map raw rows to typed enterprise-values data."""
        return FMPCachedEnterpriseValuesFetcher._transform(data)


class FMPCachedFinancialGrowthFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedFinancialGrowthData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/financial-growth`` (#1140)."""

    _path = "financial-growth"
    _data_cls = FMPCachedFinancialGrowthData
    _alias_map = _TTM_ALIASES
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
        return await FMPCachedFinancialGrowthFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedFinancialGrowthData]:
        """Map raw rows to typed financial-growth data."""
        return FMPCachedFinancialGrowthFetcher._transform(data)


class FMPCachedFinancialReportsDatesFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedFinancialReportsDatesData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/financial-reports-dates`` (#1141)."""

    _path = "financial-reports-dates"
    _data_cls = FMPCachedFinancialReportsDatesData
    _alias_map = _TTM_ALIASES
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
        return await FMPCachedFinancialReportsDatesFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedFinancialReportsDatesData]:
        """Map raw rows to typed financial-reports-dates data."""
        return FMPCachedFinancialReportsDatesFetcher._transform(data)


class FMPCachedDcfFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedDcfData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/discounted-cash-flow`` (#1103)."""

    _path = "discounted-cash-flow"
    _data_cls = FMPCachedDcfData
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
        return await FMPCachedDcfFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedDcfData]:
        """Map raw rows to typed DCF data."""
        return FMPCachedDcfFetcher._transform(data)


class FMPCachedLeveredDcfFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedDcfData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/levered-discounted-cash-flow`` (#1104)."""

    _path = "levered-discounted-cash-flow"
    _data_cls = FMPCachedDcfData
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
        return await FMPCachedLeveredDcfFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedDcfData]:
        """Map raw rows to typed levered-DCF data."""
        return FMPCachedLeveredDcfFetcher._transform(data)


class FMPCachedCustomDcfFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedCustomDcfData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/custom-discounted-cash-flow`` (#1105)."""

    _path = "custom-discounted-cash-flow"
    _data_cls = FMPCachedCustomDcfData
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
        return await FMPCachedCustomDcfFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCustomDcfData]:
        """Map raw rows to typed custom-DCF data."""
        return FMPCachedCustomDcfFetcher._transform(data)


class FMPCachedCustomLeveredDcfFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedCustomDcfData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/custom-levered-discounted-cash-flow`` (#1106)."""

    _path = "custom-levered-discounted-cash-flow"
    _data_cls = FMPCachedCustomDcfData
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
        return await FMPCachedCustomLeveredDcfFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCustomDcfData]:
        """Map raw rows to typed custom-levered-DCF data."""
        return FMPCachedCustomLeveredDcfFetcher._transform(data)


class FMPCachedProfileCikFetcher(
    Fetcher[_CikQueryParams, list[FMPCachedProfileCikData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/profile-cik`` (#1084)."""

    _path = "profile-cik"
    _data_cls = FMPCachedProfileCikData
    _query_field = "cik"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _CikQueryParams:
        """Coerce raw params dict into typed CIK-query object."""
        return _CikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _CikQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedProfileCikFetcher._fetch(query.cik, credentials)

    @staticmethod
    def transform_data(
        query: _CikQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedProfileCikData]:
        """Map raw rows to typed profile-cik data."""
        return FMPCachedProfileCikFetcher._transform(data)
