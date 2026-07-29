"""FMP SEC-extras endpoints — 5 fetchers (#1549-#1553)."""

# pylint: disable=unused-argument

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_core.provider.utils.helpers import amake_request
from pydantic import ConfigDict, Field

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


class FMPSec8kQueryParams(QueryParams):
    """8-K filings: from + to + page + limit."""

    from_date: date_type | str | None = Field(default=None, alias="from")
    to_date: date_type | str | None = Field(default=None, alias="to")
    page: int = Field(default=0)
    limit: int = Field(default=10)

    model_config = ConfigDict(populate_by_name=True)


class FMPSymbolQueryParams(QueryParams):
    """Symbol-only query params."""

    symbol: str = Field(description="Ticker symbol.")


class FMPEmptyQueryParams(QueryParams):
    """No args."""


class FMPIndustryClassificationSearchQueryParams(QueryParams):
    """Industry classification search — at least one of cik / sicCode / symbol."""

    symbol: str | None = Field(default=None)
    cik: str | None = Field(default=None)
    sic_code: str | None = Field(default=None, alias="sicCode")

    model_config = ConfigDict(populate_by_name=True)


class FMPSecFilings8kData(Data):
    """Row from ``/stable/sec-filings-8k`` (#1549)."""

    model_config = ConfigDict(extra="allow")


class FMPSecProfileData(Data):
    """Row from ``/stable/sec-profile`` (#1550)."""

    model_config = ConfigDict(extra="allow")


class FMPStandardIndustrialClassificationListData(Data):
    """Row from ``/stable/standard-industrial-classification-list`` (#1551)."""

    model_config = ConfigDict(extra="allow")


class FMPAllIndustryClassificationData(Data):
    """Row from ``/stable/all-industry-classification`` (#1552)."""

    model_config = ConfigDict(extra="allow")


class FMPIndustryClassificationSearchData(Data):
    """Row from ``/stable/industry-classification-search`` (#1553)."""

    model_config = ConfigDict(extra="allow")


async def _fmp_stable_get(
    path: str, params: dict[str, Any], credentials: dict[str, str] | None
) -> list[dict]:
    """GET /stable/<path>?<params>&apikey=<K>."""
    api_key = (credentials or {}).get("fmp_api_key", "")
    url = f"{_FMP_STABLE_BASE}/{path}"
    full_params = {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in {**params, "apikey": api_key}.items()
        if v is not None
    }
    payload = await amake_request(url, params=full_params)
    if not isinstance(payload, list):
        raise EmptyDataError(
            f"{path}: unexpected response shape from FMP "
            f"(got {type(payload).__name__}; expected list)."
        )
    return payload


class FMPSecFilings8kFetcher(Fetcher[FMPSec8kQueryParams, list[FMPSecFilings8kData]]):
    """Fetcher for ``/stable/sec-filings-8k`` (#1549)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSec8kQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSec8kQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSec8kQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch 8-K filings for range."""
        return await _fmp_stable_get(
            "sec-filings-8k",
            {
                "from": query.from_date,
                "to": query.to_date,
                "page": query.page,
                "limit": query.limit,
            },
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPSec8kQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSecFilings8kData]:
        """Map raw rows to typed model instances."""
        return [FMPSecFilings8kData.model_validate(r) for r in data]


class FMPSecProfileFetcher(Fetcher[FMPSymbolQueryParams, list[FMPSecProfileData]]):
    """Fetcher for ``/stable/sec-profile`` (#1550)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch SEC profile for symbol."""
        return await _fmp_stable_get(
            "sec-profile", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSecProfileData]:
        """Map raw rows to typed model instances."""
        return [FMPSecProfileData.model_validate(r) for r in data]


class FMPStandardIndustrialClassificationListFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPStandardIndustrialClassificationListData]]
):
    """Fetcher for ``/stable/standard-industrial-classification-list`` (#1551)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEmptyQueryParams:
        """No params."""
        return FMPEmptyQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPEmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch SIC code list."""
        return await _fmp_stable_get(
            "standard-industrial-classification-list", {}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPStandardIndustrialClassificationListData]:
        """Map raw rows to typed model instances."""
        return [
            FMPStandardIndustrialClassificationListData.model_validate(r) for r in data
        ]


class FMPAllIndustryClassificationFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPAllIndustryClassificationData]]
):
    """Fetcher for ``/stable/all-industry-classification`` (#1552)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEmptyQueryParams:
        """No params."""
        return FMPEmptyQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPEmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch full industry classification table."""
        return await _fmp_stable_get("all-industry-classification", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAllIndustryClassificationData]:
        """Map raw rows to typed model instances."""
        return [FMPAllIndustryClassificationData.model_validate(r) for r in data]


class FMPIndustryClassificationSearchFetcher(
    Fetcher[
        FMPIndustryClassificationSearchQueryParams,
        list[FMPIndustryClassificationSearchData],
    ]
):
    """Fetcher for ``/stable/industry-classification-search`` (#1553)."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPIndustryClassificationSearchQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPIndustryClassificationSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPIndustryClassificationSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search industry classification by symbol/cik/sicCode."""
        return await _fmp_stable_get(
            "industry-classification-search",
            {
                "symbol": query.symbol,
                "cik": query.cik,
                "sicCode": query.sic_code,
            },
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPIndustryClassificationSearchQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPIndustryClassificationSearchData]:
        """Map raw rows to typed model instances."""
        return [FMPIndustryClassificationSearchData.model_validate(r) for r in data]
