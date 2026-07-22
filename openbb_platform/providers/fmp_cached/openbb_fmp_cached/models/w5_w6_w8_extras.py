"""Cached FMP W5/W6/W8 free-tier extras — bulk drain of 30 endpoints.

W5 remainder (#1087 #1095 #1096 #1211 #1261 #1269 #1270 #1271 #1272 #1277 #1278 #1285 #1286 #1287 #1288)
W6 remainder (#1069 #1070 #1191 #1192 #1193 #1194 #1195 #1196 #1235 #1239 #1240 #1243 #1244)
W8 CommitmentOfTraders (#1100 #1101)

All 30 are Free-tier live pass-through. Two shapes:

- **17 no-param**: reuse ``_SearchFetcherBase`` with an empty
  throwaway key (same trick as ``AllExchangeMarketHours`` in
  stock_quotes.py). FMP ignores unknown params.
- **13 single-param**: reuse ``_SearchFetcherBase`` with the right
  ``_query_field`` (symbol/name/cik/senateID/symbols/page).

All rows use ``ConfigDict(extra='allow')`` — 30 endpoints, each with
its own 10-30 field shape and FMP schema drift. Modeling each field
would be ~5,000 LOC of Pydantic that adds no correctness (users can
introspect the dict). Uniform loose typing is the pragmatic choice
for a bulk drain.
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument,too-many-lines

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import ConfigDict, Field

from openbb_fmp_cached.models.search_endpoints import _SearchFetcherBase
from openbb_fmp_cached.models.single_param_endpoints import _SymbolQueryParams
from openbb_fmp_cached.models.statement_extras import _CikQueryParams
from openbb_fmp_cached.models.stock_quotes import _NoParams, _SymbolsQueryParams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query params (additions beyond existing symbol/cik/symbols/no-params)
# ---------------------------------------------------------------------------


class _NameQueryParams(QueryParams):
    """Query params for endpoints keyed by ``name=<str>``."""

    name: str = Field(description="Free-form name search string.")


class _PageQueryParams(QueryParams):
    """Query params for endpoints paginated by ``page=<int>``."""

    page: int = Field(default=0, description="Page offset (0-based).")


class _SenateIdQueryParams(QueryParams):
    """Query params for endpoints keyed by ``senateID=<str>``."""

    senateID: str = Field(description="Senate/House member ID (e.g. 'A000360').")


# ---------------------------------------------------------------------------
# Loose Data class — one class shared across all 30 endpoints
# ---------------------------------------------------------------------------


class FMPCachedGenericRowData(Data):
    """Loose row for the W5/W6/W8 extras drain.

    Each endpoint returns 10-30 endpoint-specific fields; ``extra=allow``
    preserves them all without hardcoding per-endpoint schemas. Users
    who need typed access can wrap this class in downstream code.
    """

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Fetchers — 30 endpoints; grouped by category for readability
# ---------------------------------------------------------------------------


# ============ W5 no-param (8) ============


class FMPCachedDelistedCompaniesFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/delisted-companies`` (#1087)."""

    _path = "delisted-companies"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"  # no-param — FMP ignores 'unused='

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedDelistedCompaniesFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedDelistedCompaniesFetcher._transform(data)


class FMPCachedMergersAcquisitionsLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/mergers-acquisitions-latest`` (#1095)."""

    _path = "mergers-acquisitions-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedMergersAcquisitionsLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedMergersAcquisitionsLatestFetcher._transform(data)


class FMPCachedStandardIndustrialClassificationListFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/standard-industrial-classification-list`` (#1270)."""

    _path = "standard-industrial-classification-list"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedStandardIndustrialClassificationListFetcher._fetch(
            "", credentials
        )

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedStandardIndustrialClassificationListFetcher._transform(data)


class FMPCachedAllIndustryClassificationFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/all-industry-classification`` (#1272)."""

    _path = "all-industry-classification"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedAllIndustryClassificationFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedAllIndustryClassificationFetcher._transform(data)


class FMPCachedSenateLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/senate-latest`` (#1277)."""

    _path = "senate-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedSenateLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSenateLatestFetcher._transform(data)


class FMPCachedHouseLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/house-latest`` (#1278)."""

    _path = "house-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedHouseLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedHouseLatestFetcher._transform(data)


class FMPCachedSenateProfileFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/senate-profile`` (#1285). No-param — returns all 500 profiles."""

    _path = "senate-profile"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedSenateProfileFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSenateProfileFetcher._transform(data)


class FMPCachedSenatePositionsFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/senate-positions`` (#1286)."""

    _path = "senate-positions"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedSenatePositionsFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSenatePositionsFetcher._transform(data)


# ============ W5 with param (7) ============


class FMPCachedMergersAcquisitionsSearchFetcher(
    Fetcher[_NameQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/mergers-acquisitions-search`` (#1096)."""

    _path = "mergers-acquisitions-search"
    _data_cls = FMPCachedGenericRowData
    _query_field = "name"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NameQueryParams:
        """Coerce raw params dict into typed name-query object."""
        return _NameQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NameQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by name."""
        return await FMPCachedMergersAcquisitionsSearchFetcher._fetch(
            query.name, credentials
        )

    @staticmethod
    def transform_data(
        query: _NameQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedMergersAcquisitionsSearchFetcher._transform(data)


class FMPCachedAcquisitionOfBeneficialOwnershipFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/acquisition-of-beneficial-ownership`` (#1211)."""

    _path = "acquisition-of-beneficial-ownership"
    _data_cls = FMPCachedGenericRowData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedAcquisitionOfBeneficialOwnershipFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedAcquisitionOfBeneficialOwnershipFetcher._transform(data)


class FMPCachedSecFilings8KFetcher(
    Fetcher[_PageQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/sec-filings-8k`` (#1261)."""

    _path = "sec-filings-8k"
    _data_cls = FMPCachedGenericRowData
    _query_field = "page"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _PageQueryParams:
        """Coerce raw params dict into typed page-query object."""
        return _PageQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _PageQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by page."""
        return await FMPCachedSecFilings8KFetcher._fetch(str(query.page), credentials)

    @staticmethod
    def transform_data(
        query: _PageQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSecFilings8KFetcher._transform(data)


class FMPCachedSecProfileFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/sec-profile`` (#1269)."""

    _path = "sec-profile"
    _data_cls = FMPCachedGenericRowData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedSecProfileFetcher._fetch(query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSecProfileFetcher._transform(data)


class FMPCachedIndustryClassificationSearchFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/industry-classification-search`` (#1271)."""

    _path = "industry-classification-search"
    _data_cls = FMPCachedGenericRowData
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await FMPCachedIndustryClassificationSearchFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedIndustryClassificationSearchFetcher._transform(data)


class FMPCachedSenateNetWorthFetcher(
    Fetcher[_SenateIdQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/senate-net-worth`` (#1287)."""

    _path = "senate-net-worth"
    _data_cls = FMPCachedGenericRowData
    _query_field = "senateID"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SenateIdQueryParams:
        """Coerce raw params dict into typed senateID query object."""
        return _SenateIdQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SenateIdQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by senateID."""
        return await FMPCachedSenateNetWorthFetcher._fetch(query.senateID, credentials)

    @staticmethod
    def transform_data(
        query: _SenateIdQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSenateNetWorthFetcher._transform(data)


class FMPCachedSenateNetWorthAggregatedFetcher(
    Fetcher[_SenateIdQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/senate-net-worth-aggregated`` (#1288)."""

    _path = "senate-net-worth-aggregated"
    _data_cls = FMPCachedGenericRowData
    _query_field = "senateID"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SenateIdQueryParams:
        """Coerce raw params dict into typed senateID query object."""
        return _SenateIdQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SenateIdQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by senateID."""
        return await FMPCachedSenateNetWorthAggregatedFetcher._fetch(
            query.senateID, credentials
        )

    @staticmethod
    def transform_data(
        query: _SenateIdQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedSenateNetWorthAggregatedFetcher._transform(data)


# ============ W6 no-param (7) ============


class FMPCachedIposDisclosureFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/ipos-disclosure`` (#1069)."""

    _path = "ipos-disclosure"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedIposDisclosureFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedIposDisclosureFetcher._transform(data)


class FMPCachedIposProspectusFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/ipos-prospectus`` (#1070)."""

    _path = "ipos-prospectus"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedIposProspectusFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedIposProspectusFetcher._transform(data)


class FMPCachedCrowdfundingOfferingsLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/crowdfunding-offerings-latest`` (#1191)."""

    _path = "crowdfunding-offerings-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedCrowdfundingOfferingsLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedCrowdfundingOfferingsLatestFetcher._transform(data)


class FMPCachedFundraisingLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/fundraising-latest`` (#1194)."""

    _path = "fundraising-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedFundraisingLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedFundraisingLatestFetcher._transform(data)


class FMPCachedFmpArticlesFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/fmp-articles`` (#1235)."""

    _path = "fmp-articles"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedFmpArticlesFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedFmpArticlesFetcher._transform(data)


class FMPCachedNewsCryptoLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/news/crypto-latest`` (#1239)."""

    _path = "news/crypto-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedNewsCryptoLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedNewsCryptoLatestFetcher._transform(data)


class FMPCachedNewsForexLatestFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/news/forex-latest`` (#1240)."""

    _path = "news/forex-latest"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedNewsForexLatestFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedNewsForexLatestFetcher._transform(data)


# ============ W6 with param (6) ============


class FMPCachedCrowdfundingOfferingsSearchFetcher(
    Fetcher[_NameQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/crowdfunding-offerings-search`` (#1192)."""

    _path = "crowdfunding-offerings-search"
    _data_cls = FMPCachedGenericRowData
    _query_field = "name"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NameQueryParams:
        """Coerce raw params dict into typed name-query object."""
        return _NameQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NameQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by name."""
        return await FMPCachedCrowdfundingOfferingsSearchFetcher._fetch(
            query.name, credentials
        )

    @staticmethod
    def transform_data(
        query: _NameQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedCrowdfundingOfferingsSearchFetcher._transform(data)


class FMPCachedCrowdfundingOfferingsFetcher(
    Fetcher[_CikQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/crowdfunding-offerings`` (#1193)."""

    _path = "crowdfunding-offerings"
    _data_cls = FMPCachedGenericRowData
    _query_field = "cik"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _CikQueryParams:
        """Coerce raw params dict into typed CIK-query object."""
        return _CikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _CikQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by CIK."""
        return await FMPCachedCrowdfundingOfferingsFetcher._fetch(
            query.cik, credentials
        )

    @staticmethod
    def transform_data(
        query: _CikQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedCrowdfundingOfferingsFetcher._transform(data)


class FMPCachedFundraisingSearchFetcher(
    Fetcher[_NameQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/fundraising-search`` (#1195)."""

    _path = "fundraising-search"
    _data_cls = FMPCachedGenericRowData
    _query_field = "name"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NameQueryParams:
        """Coerce raw params dict into typed name-query object."""
        return _NameQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NameQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by name."""
        return await FMPCachedFundraisingSearchFetcher._fetch(query.name, credentials)

    @staticmethod
    def transform_data(
        query: _NameQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedFundraisingSearchFetcher._transform(data)


class FMPCachedFundraisingFetcher(
    Fetcher[_CikQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/fundraising`` (#1196)."""

    _path = "fundraising"
    _data_cls = FMPCachedGenericRowData
    _query_field = "cik"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _CikQueryParams:
        """Coerce raw params dict into typed CIK-query object."""
        return _CikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _CikQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by CIK."""
        return await FMPCachedFundraisingFetcher._fetch(query.cik, credentials)

    @staticmethod
    def transform_data(
        query: _CikQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedFundraisingFetcher._transform(data)


class FMPCachedNewsCryptoFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/news/crypto`` (#1243)."""

    _path = "news/crypto"
    _data_cls = FMPCachedGenericRowData
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by symbols list."""
        return await FMPCachedNewsCryptoFetcher._fetch(query.symbols, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedNewsCryptoFetcher._transform(data)


class FMPCachedNewsForexFetcher(
    Fetcher[_SymbolsQueryParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/news/forex`` (#1244)."""

    _path = "news/forex"
    _data_cls = FMPCachedGenericRowData
    _query_field = "symbols"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolsQueryParams:
        """Coerce raw params dict into typed symbols-query object."""
        return _SymbolsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolsQueryParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch by symbols list."""
        return await FMPCachedNewsForexFetcher._fetch(query.symbols, credentials)

    @staticmethod
    def transform_data(
        query: _SymbolsQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedNewsForexFetcher._transform(data)


# ============ W8 CommitmentOfTraders no-param (2) ============


class FMPCachedCommitmentOfTradersReportFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/commitment-of-traders-report`` (#1100)."""

    _path = "commitment-of-traders-report"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedCommitmentOfTradersReportFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedCommitmentOfTradersReportFetcher._transform(data)


class FMPCachedCommitmentOfTradersAnalysisFetcher(
    Fetcher[_NoParams, list[FMPCachedGenericRowData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/commitment-of-traders-analysis`` (#1101)."""

    _path = "commitment-of-traders-analysis"
    _data_cls = FMPCachedGenericRowData
    _query_field = "unused"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _NoParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _NoParams(**params)

    @staticmethod
    async def aextract_data(
        query: _NoParams, credentials: dict[str, str] | None, **kwargs: Any
    ) -> list[dict]:
        """Live pass-through fetch (no params)."""
        return await FMPCachedCommitmentOfTradersAnalysisFetcher._fetch("", credentials)

    @staticmethod
    def transform_data(
        query: _NoParams, data: list, **kwargs: Any
    ) -> list[FMPCachedGenericRowData]:
        """Map raw rows to typed generic data."""
        return FMPCachedCommitmentOfTradersAnalysisFetcher._transform(data)
