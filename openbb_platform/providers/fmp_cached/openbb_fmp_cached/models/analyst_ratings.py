"""Cached FMP analyst / ratings endpoints — 6 symbol-parameterized fetchers.

Wave 7 Analyst drain (#1057 #1058 #1059 #1061 #1062 #1063).

All six take exactly ``symbol=<TICKER>`` and reuse
``_SearchFetcherBase`` with ``_query_field='symbol'``. Live pass-
through (per-symbol cache to be added in a later PR — see
search_endpoints.py rationale).

Endpoints:
- ``ratings-snapshot`` (#1057) — current multi-factor rating
- ``ratings-historical`` (#1058) — daily rating history
- ``price-target-summary`` (#1059) — analyst target rollup
- ``grades`` (#1061) — individual analyst grade changes
- ``grades-historical`` (#1062) — grade counts over time
- ``grades-consensus`` (#1063) — current consensus buy/hold/sell counts
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from pydantic import ConfigDict, Field

from openbb_fmp_cached.models.search_endpoints import _SearchFetcherBase
from openbb_fmp_cached.models.single_param_endpoints import _SymbolQueryParams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models — use extra=allow for endpoints returning >6 fields (avoid
# schema-drift breakage from FMP adding new scoring columns).
# ---------------------------------------------------------------------------


class FMPCachedRatingsSnapshotData(Data):
    """Row from ``/stable/ratings-snapshot`` — multi-factor scoring rollup."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    rating: str | None = Field(default=None, description="Letter grade (A-F).")
    overall_score: int | None = Field(default=None, description="Composite 1-5.")


class FMPCachedRatingsHistoricalData(Data):
    """Row from ``/stable/ratings-historical``."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str = Field(description="Snapshot date YYYY-MM-DD.")
    rating: str | None = Field(default=None, description="Letter grade.")


class FMPCachedPriceTargetSummaryData(Data):
    """Row from ``/stable/price-target-summary`` — rollup counts + averages."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


class FMPCachedGradesData(Data):
    """Row from ``/stable/grades`` — individual analyst grade change."""

    symbol: str = Field(description="Ticker symbol.")
    date: str = Field(description="Change date.")
    grading_company: str | None = Field(default=None, description="Analyst firm.")
    previous_grade: str | None = Field(default=None, description="Prior grade.")
    new_grade: str | None = Field(default=None, description="New grade.")
    action: str | None = Field(default=None, description="Action taken.")


class FMPCachedGradesHistoricalData(Data):
    """Row from ``/stable/grades-historical`` — rollup counts by rating tier."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str = Field(description="Rollup date.")


class FMPCachedGradesConsensusData(Data):
    """Row from ``/stable/grades-consensus`` — current consensus rollup."""

    symbol: str = Field(description="Ticker symbol.")
    strong_buy: int | None = Field(default=None, description="Strong-buy count.")
    buy: int | None = Field(default=None, description="Buy count.")
    hold: int | None = Field(default=None, description="Hold count.")
    sell: int | None = Field(default=None, description="Sell count.")
    strong_sell: int | None = Field(default=None, description="Strong-sell count.")
    consensus: str | None = Field(default=None, description="Overall consensus.")


# ---------------------------------------------------------------------------
# Shared alias maps
# ---------------------------------------------------------------------------


_RATINGS_ALIASES = {"overallScore": "overall_score"}
_GRADES_ALIASES = {
    "gradingCompany": "grading_company",
    "previousGrade": "previous_grade",
    "newGrade": "new_grade",
}
_CONSENSUS_ALIASES = {"strongBuy": "strong_buy", "strongSell": "strong_sell"}


# ---------------------------------------------------------------------------
# Fetchers — all symbol-keyed, live pass-through via _SearchFetcherBase.
# One class per endpoint (not a factory) so Fetcher[..., list[DataCls]] is
# a concrete generic — OpenBB's RegistryMap._validate rejects bare `list`.
# ---------------------------------------------------------------------------


class FMPCachedRatingsSnapshotFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedRatingsSnapshotData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/ratings-snapshot`` (#1057)."""

    _path = "ratings-snapshot"
    _data_cls = FMPCachedRatingsSnapshotData
    _alias_map = _RATINGS_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedRatingsSnapshotFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedRatingsSnapshotData]:
        """Map raw rows to typed ratings-snapshot data."""
        return FMPCachedRatingsSnapshotFetcher._transform(data)


class FMPCachedRatingsHistoricalFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedRatingsHistoricalData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/ratings-historical`` (#1058)."""

    _path = "ratings-historical"
    _data_cls = FMPCachedRatingsHistoricalData
    _alias_map = _RATINGS_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedRatingsHistoricalFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedRatingsHistoricalData]:
        """Map raw rows to typed ratings-historical data."""
        return FMPCachedRatingsHistoricalFetcher._transform(data)


class FMPCachedPriceTargetSummaryFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedPriceTargetSummaryData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/price-target-summary`` (#1059)."""

    _path = "price-target-summary"
    _data_cls = FMPCachedPriceTargetSummaryData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedPriceTargetSummaryFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedPriceTargetSummaryData]:
        """Map raw rows to typed price-target-summary data."""
        return FMPCachedPriceTargetSummaryFetcher._transform(data)


class FMPCachedGradesFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedGradesData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/grades`` (#1061)."""

    _path = "grades"
    _data_cls = FMPCachedGradesData
    _alias_map = _GRADES_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedGradesFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGradesData]:
        """Map raw rows to typed grades data."""
        return FMPCachedGradesFetcher._transform(data)


class FMPCachedGradesHistoricalFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedGradesHistoricalData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/grades-historical`` (#1062)."""

    _path = "grades-historical"
    _data_cls = FMPCachedGradesHistoricalData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedGradesHistoricalFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGradesHistoricalData]:
        """Map raw rows to typed grades-historical data."""
        return FMPCachedGradesHistoricalFetcher._transform(data)


class FMPCachedGradesConsensusFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedGradesConsensusData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/grades-consensus`` (#1063)."""

    _path = "grades-consensus"
    _data_cls = FMPCachedGradesConsensusData
    _alias_map = _CONSENSUS_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into the typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedGradesConsensusFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGradesConsensusData]:
        """Map raw rows to typed grades-consensus data."""
        return FMPCachedGradesConsensusFetcher._transform(data)
