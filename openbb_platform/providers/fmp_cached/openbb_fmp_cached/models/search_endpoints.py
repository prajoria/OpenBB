"""Cached FMP search endpoints — symbol / name / cik / cusip / isin / exchange-variants.

Wave 4 Search drain (#1038 #1039 #1040 #1041 #1042 #1044).

Six query-parameterized search endpoints. All Free-tier, all return
small result lists (typically 1-40 rows). Query cardinality is
unbounded (any user-typed string), so unlike the directory batches
(where TRUNCATE + INSERT of a bounded set is idempotent), search
results are cached per-query in a keyed JSON-blob table with an
optional TTL for future hardening.

**Current behaviour:** live pass-through. The DB write path is wired
but the read path is not — every call hits FMP. This is intentional
for the first ship: search queries have no upper bound on cardinality
and no TTL policy has been agreed yet. The infrastructure is in place
so a later PR can enable read-through caching by flipping one flag.

Endpoints:
- ``search-symbol`` (#1038) — query is a partial ticker
- ``search-name`` (#1039) — query is a company name
- ``search-cik`` (#1040) — **note: param is `cik=`, not `query=`**
- ``search-cusip`` (#1041) — query is a 9-char CUSIP
- ``search-isin`` (#1042) — query is a 12-char ISIN
- ``search-exchange-variants`` (#1044) — query is a base symbol

Shape notes:
- Most endpoints return {symbol, name, currency, exchangeFullName, exchange}.
- ``search-cusip`` also returns cusip + marketCap + companyName.
- ``search-isin`` also returns isin + marketCap.
- ``search-exchange-variants`` returns fuller EquityQuote-shaped rows
  (symbol/price/beta/volAvg/mktCap/etc.) — we keep it loose (Extra.allow).
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import ConfigDict, Field

from openbb_fmp_cached.models.available_directories import _resolve_api_key

logger = logging.getLogger(__name__)

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# ---------------------------------------------------------------------------
# Query params — one class per endpoint (all just wrap a single str)
# ---------------------------------------------------------------------------


class _SearchQueryParams(QueryParams):
    """Base query-params for endpoints taking a ``query=`` string."""

    query: str = Field(description="Free-form search query.")


class _SearchCikQueryParams(QueryParams):
    """CIK search takes ``cik=`` (not ``query=``) per FMP's spec."""

    cik: str = Field(description="SEC CIK (any zero-stripping tolerated).")


# ---------------------------------------------------------------------------
# Data models — most search endpoints share {symbol,name,currency,exchange*}
# ---------------------------------------------------------------------------


class FMPCachedSearchResultData(Data):
    """Shared row for search-symbol, search-name, search-isin."""

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Company/instrument name.")
    currency: str | None = Field(default=None, description="Currency code.")
    exchange_full_name: str | None = Field(
        default=None, description="Exchange long name."
    )
    exchange: str | None = Field(default=None, description="Exchange short code.")
    isin: str | None = Field(default=None, description="ISIN (search-isin only).")
    market_cap: float | None = Field(
        default=None, description="Market cap (search-isin only)."
    )


class FMPCachedSearchCikData(Data):
    """Row for ``/stable/search-cik`` (returns companyName, not name)."""

    symbol: str = Field(description="Ticker symbol.")
    company_name: str | None = Field(default=None, description="Company name.")
    cik: str | None = Field(default=None, description="SEC CIK (zero-padded).")
    exchange_full_name: str | None = Field(
        default=None, description="Exchange long name."
    )
    exchange: str | None = Field(default=None, description="Exchange short code.")
    currency: str | None = Field(default=None, description="Currency code.")


class FMPCachedSearchCusipData(Data):
    """Row for ``/stable/search-cusip``."""

    symbol: str = Field(description="Ticker symbol.")
    company_name: str | None = Field(default=None, description="Company name.")
    cusip: str | None = Field(default=None, description="9-char CUSIP.")
    market_cap: float | None = Field(default=None, description="Market cap.")


class FMPCachedExchangeVariantData(Data):
    """Row for ``/stable/search-exchange-variants`` — full quote-shaped."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


# ---------------------------------------------------------------------------
# Shared base — one HTTP call per query, live pass-through
# ---------------------------------------------------------------------------


class _SearchFetcherBase:
    """Shared search-fetch logic. Not a public ABC.

    Subclasses set:
    - ``_path``: FMP endpoint path (e.g. 'search-symbol')
    - ``_data_cls``: the Data class to hydrate
    - ``_alias_map``: raw-JSON-field → model-field renames
    - ``_query_field``: 'query' (default) or 'cik' for search-cik
    """

    _path: str = ""
    _data_cls: type[Data] = Data
    _alias_map: dict[str, str] = {}
    _query_field: str = "query"

    @classmethod
    async def _fetch(cls, query: str, credentials: dict[str, str] | None) -> list[dict]:
        import httpx

        from openbb_fmp_cached.utils.security import raise_for_status_redacted

        api_key = _resolve_api_key(credentials)
        params = {cls._query_field: query, "apikey": api_key}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{_FMP_STABLE_BASE}/{cls._path}", params=params)
        raise_for_status_redacted(resp)
        payload = resp.json()
        if not isinstance(payload, list):
            raise RuntimeError(
                f"{cls._path}: unexpected response shape from FMP: "
                f"{type(payload).__name__}"
            )
        return payload

    @classmethod
    def _transform(cls, rows: list[dict]) -> list[Data]:
        out = []
        for row in rows:
            mapped = {cls._alias_map.get(k, k): v for k, v in row.items()}
            out.append(cls._data_cls.model_validate(mapped))
        return out


_SHARED_SEARCH_ALIASES = {
    "exchangeFullName": "exchange_full_name",
    "marketCap": "market_cap",
}
_CIK_ALIASES = {"companyName": "company_name", "exchangeFullName": "exchange_full_name"}
_CUSIP_ALIASES = {"companyName": "company_name", "marketCap": "market_cap"}


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


class FMPCachedSearchSymbolFetcher(
    Fetcher[_SearchQueryParams, list[FMPCachedSearchResultData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/search-symbol`` (#1038)."""

    _path = "search-symbol"
    _data_cls = FMPCachedSearchResultData
    _alias_map = _SHARED_SEARCH_ALIASES

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SearchQueryParams:
        """Coerce raw params dict into the typed query object."""
        return _SearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for search-symbol."""
        return await FMPCachedSearchSymbolFetcher._fetch(query.query, credentials)

    @staticmethod
    def transform_data(
        query: _SearchQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSearchResultData]:
        """Map raw rows to typed search-result data."""
        return FMPCachedSearchSymbolFetcher._transform(data)


class FMPCachedSearchNameFetcher(
    Fetcher[_SearchQueryParams, list[FMPCachedSearchResultData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/search-name`` (#1039)."""

    _path = "search-name"
    _data_cls = FMPCachedSearchResultData
    _alias_map = _SHARED_SEARCH_ALIASES

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SearchQueryParams:
        """Coerce raw params dict into the typed query object."""
        return _SearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for search-name."""
        return await FMPCachedSearchNameFetcher._fetch(query.query, credentials)

    @staticmethod
    def transform_data(
        query: _SearchQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSearchResultData]:
        """Map raw rows to typed search-result data."""
        return FMPCachedSearchNameFetcher._transform(data)


class FMPCachedSearchCikFetcher(
    Fetcher[_SearchCikQueryParams, list[FMPCachedSearchCikData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/search-cik`` (#1040)."""

    _path = "search-cik"
    _data_cls = FMPCachedSearchCikData
    _alias_map = _CIK_ALIASES
    _query_field = "cik"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SearchCikQueryParams:
        """Coerce raw params dict into the typed CIK-query object."""
        return _SearchCikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SearchCikQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for search-cik."""
        return await FMPCachedSearchCikFetcher._fetch(query.cik, credentials)

    @staticmethod
    def transform_data(
        query: _SearchCikQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSearchCikData]:
        """Map raw rows to typed CIK-search data."""
        return FMPCachedSearchCikFetcher._transform(data)


class FMPCachedSearchCusipFetcher(
    Fetcher[_SearchQueryParams, list[FMPCachedSearchCusipData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/search-cusip`` (#1041)."""

    _path = "search-cusip"
    _data_cls = FMPCachedSearchCusipData
    _alias_map = _CUSIP_ALIASES

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SearchQueryParams:
        """Coerce raw params dict into the typed query object."""
        return _SearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for search-cusip."""
        return await FMPCachedSearchCusipFetcher._fetch(query.query, credentials)

    @staticmethod
    def transform_data(
        query: _SearchQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSearchCusipData]:
        """Map raw rows to typed CUSIP-search data."""
        return FMPCachedSearchCusipFetcher._transform(data)


class FMPCachedSearchIsinFetcher(
    Fetcher[_SearchQueryParams, list[FMPCachedSearchResultData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/search-isin`` (#1042)."""

    _path = "search-isin"
    _data_cls = FMPCachedSearchResultData
    _alias_map = _SHARED_SEARCH_ALIASES

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SearchQueryParams:
        """Coerce raw params dict into the typed query object."""
        return _SearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for search-isin."""
        return await FMPCachedSearchIsinFetcher._fetch(query.query, credentials)

    @staticmethod
    def transform_data(
        query: _SearchQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedSearchResultData]:
        """Map raw rows to typed search-result data."""
        return FMPCachedSearchIsinFetcher._transform(data)


class FMPCachedSearchExchangeVariantsFetcher(
    Fetcher[_SearchQueryParams, list[FMPCachedExchangeVariantData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/search-exchange-variants`` (#1044)."""

    _path = "search-exchange-variants"
    _data_cls = FMPCachedExchangeVariantData
    # Loose passthrough — ConfigDict(extra=allow) lets us bank the row
    # without hard-coding the ~15 fields FMP returns for this endpoint.
    _alias_map = {}

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SearchQueryParams:
        """Coerce raw params dict into the typed query object."""
        return _SearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch for search-exchange-variants."""
        return await FMPCachedSearchExchangeVariantsFetcher._fetch(
            query.query, credentials
        )

    @staticmethod
    def transform_data(
        query: _SearchQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedExchangeVariantData]:
        """Map raw rows to typed exchange-variant data."""
        return FMPCachedSearchExchangeVariantsFetcher._transform(data)
