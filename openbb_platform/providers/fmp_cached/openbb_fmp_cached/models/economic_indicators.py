"""Cached FMP economic-indicators fetcher.

W3 Economics drain (#1108).

Single endpoint: ``/stable/economic-indicators?name=<indicator>``. FMP
supports named indicators (GDP, CPI, unemployment, treasuryYield, etc.).
Live pass-through via ``_SearchFetcherBase`` with ``_query_field='name'``.
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


class _IndicatorNameQueryParams(QueryParams):
    """Query params for the economic-indicators endpoint."""

    name: str = Field(description="FMP indicator name (e.g. 'GDP', 'CPI').")


class FMPCachedEconomicIndicatorData(Data):
    """Row from ``/stable/economic-indicators``."""

    name: str = Field(description="Indicator name.")
    date: str = Field(description="Observation date.")
    value: float | None = Field(default=None, description="Observation value.")


class FMPCachedEconomicIndicatorsFetcher(
    Fetcher[_IndicatorNameQueryParams, list[FMPCachedEconomicIndicatorData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/economic-indicators`` (#1108)."""

    _path = "economic-indicators"
    _data_cls = FMPCachedEconomicIndicatorData
    _query_field = "name"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _IndicatorNameQueryParams:
        """Coerce raw params dict into typed name-query object."""
        return _IndicatorNameQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _IndicatorNameQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by indicator name."""
        return await FMPCachedEconomicIndicatorsFetcher._fetch(query.name, credentials)

    @staticmethod
    def transform_data(
        query: _IndicatorNameQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedEconomicIndicatorData]:
        """Map raw rows to typed economic-indicator data."""
        return FMPCachedEconomicIndicatorsFetcher._transform(data)
