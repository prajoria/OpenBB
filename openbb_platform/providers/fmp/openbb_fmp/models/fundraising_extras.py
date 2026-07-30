"""FMP fundraising-extras endpoints — 10 fetchers.

Port of 10 fundraising-domain endpoints to plain ``fmp`` (#1534-#1543).

CIK-based (2):
- ``fundraising``                       (#1534)
- ``crowdfunding-offerings``            (#1537)

Page+limit latest (4):
- ``fundraising-latest``                (#1535)
- ``crowdfunding-offerings-latest``     (#1538)
- ``mergers-acquisitions-latest``       (#1540)
- ``ipos-disclosure``                   (#1542)
- ``ipos-prospectus``                   (#1543)

Name-search (3):
- ``fundraising-search``                (#1536)
- ``crowdfunding-offerings-search``     (#1539)
- ``mergers-acquisitions-search``       (#1541)
"""

# pylint: disable=unused-argument

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_core.provider.utils.helpers import amake_request
from pydantic import ConfigDict, Field

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class FMPCikQueryParams(QueryParams):
    """SEC CIK query params (10-digit zero-padded)."""

    cik: str = Field(description="SEC CIK, 10-digit zero-padded.")


class FMPPageLimitQueryParams(QueryParams):
    """Paged listing query params."""

    page: int = Field(default=0, description="Page number.")
    limit: int = Field(default=10, description="Page size.")


class FMPNameSearchQueryParams(QueryParams):
    """Name-search query params."""

    name: str = Field(description="Free-text name query.")


# ---------------------------------------------------------------------------
# Data models — one distinct class per endpoint (RegistryMap requirement).
# ---------------------------------------------------------------------------


class FMPFundraisingData(Data):
    """Row from ``/stable/fundraising`` (#1534)."""

    model_config = ConfigDict(extra="allow")


class FMPFundraisingLatestData(Data):
    """Row from ``/stable/fundraising-latest`` (#1535)."""

    model_config = ConfigDict(extra="allow")


class FMPFundraisingSearchData(Data):
    """Row from ``/stable/fundraising-search`` (#1536)."""

    model_config = ConfigDict(extra="allow")


class FMPCrowdfundingOfferingsData(Data):
    """Row from ``/stable/crowdfunding-offerings`` (#1537)."""

    model_config = ConfigDict(extra="allow")


class FMPCrowdfundingOfferingsLatestData(Data):
    """Row from ``/stable/crowdfunding-offerings-latest`` (#1538)."""

    model_config = ConfigDict(extra="allow")


class FMPCrowdfundingOfferingsSearchData(Data):
    """Row from ``/stable/crowdfunding-offerings-search`` (#1539)."""

    model_config = ConfigDict(extra="allow")


class FMPMergersAcquisitionsLatestData(Data):
    """Row from ``/stable/mergers-acquisitions-latest`` (#1540)."""

    model_config = ConfigDict(extra="allow")


class FMPMergersAcquisitionsSearchData(Data):
    """Row from ``/stable/mergers-acquisitions-search`` (#1541)."""

    model_config = ConfigDict(extra="allow")


class FMPIposDisclosureData(Data):
    """Row from ``/stable/ipos-disclosure`` (#1542)."""

    model_config = ConfigDict(extra="allow")


class FMPIposProspectusData(Data):
    """Row from ``/stable/ipos-prospectus`` (#1543)."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Shared fetch helper
# ---------------------------------------------------------------------------


async def _fmp_stable_get(
    path: str, params: dict[str, Any], credentials: dict[str, str] | None
) -> list[dict]:
    """GET /stable/<path>?<params>&apikey=<K>; raise EmptyDataError on non-list."""
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


# ---------------------------------------------------------------------------
# CIK-based fetchers (2)
# ---------------------------------------------------------------------------


class FMPFundraisingFetcher(Fetcher[FMPCikQueryParams, list[FMPFundraisingData]]):
    """Fetcher for ``/stable/fundraising`` (#1534)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCikQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPCikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCikQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch fundraising history by CIK."""
        return await _fmp_stable_get("fundraising", {"cik": query.cik}, credentials)

    @staticmethod
    def transform_data(
        query: FMPCikQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFundraisingData]:
        """Map raw rows to typed model instances."""
        return [FMPFundraisingData.model_validate(r) for r in data]


class FMPCrowdfundingOfferingsFetcher(
    Fetcher[FMPCikQueryParams, list[FMPCrowdfundingOfferingsData]]
):
    """Fetcher for ``/stable/crowdfunding-offerings`` (#1537)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCikQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPCikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCikQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch crowdfunding offerings by CIK."""
        return await _fmp_stable_get(
            "crowdfunding-offerings", {"cik": query.cik}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPCikQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCrowdfundingOfferingsData]:
        """Map raw rows to typed model instances."""
        return [FMPCrowdfundingOfferingsData.model_validate(r) for r in data]


# ---------------------------------------------------------------------------
# Page+limit latest fetchers (5)
# ---------------------------------------------------------------------------


class FMPFundraisingLatestFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPFundraisingLatestData]]
):
    """Fetcher for ``/stable/fundraising-latest`` (#1535)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch latest Form-D fundraising filings."""
        return await _fmp_stable_get(
            "fundraising-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFundraisingLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPFundraisingLatestData.model_validate(r) for r in data]


class FMPCrowdfundingOfferingsLatestFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPCrowdfundingOfferingsLatestData]]
):
    """Fetcher for ``/stable/crowdfunding-offerings-latest`` (#1538)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch latest crowdfunding offerings."""
        return await _fmp_stable_get(
            "crowdfunding-offerings-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCrowdfundingOfferingsLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPCrowdfundingOfferingsLatestData.model_validate(r) for r in data]


class FMPMergersAcquisitionsLatestFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPMergersAcquisitionsLatestData]]
):
    """Fetcher for ``/stable/mergers-acquisitions-latest`` (#1540)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch latest M&A filings."""
        return await _fmp_stable_get(
            "mergers-acquisitions-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPMergersAcquisitionsLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPMergersAcquisitionsLatestData.model_validate(r) for r in data]


class FMPIposDisclosureFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPIposDisclosureData]]
):
    """Fetcher for ``/stable/ipos-disclosure`` (#1542)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch IPO disclosure listings."""
        return await _fmp_stable_get(
            "ipos-disclosure",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPIposDisclosureData]:
        """Map raw rows to typed model instances."""
        return [FMPIposDisclosureData.model_validate(r) for r in data]


class FMPIposProspectusFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPIposProspectusData]]
):
    """Fetcher for ``/stable/ipos-prospectus`` (#1543)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch IPO prospectus listings."""
        return await _fmp_stable_get(
            "ipos-prospectus",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPIposProspectusData]:
        """Map raw rows to typed model instances."""
        return [FMPIposProspectusData.model_validate(r) for r in data]


# ---------------------------------------------------------------------------
# Name-search fetchers (3)
# ---------------------------------------------------------------------------


class FMPFundraisingSearchFetcher(
    Fetcher[FMPNameSearchQueryParams, list[FMPFundraisingSearchData]]
):
    """Fetcher for ``/stable/fundraising-search`` (#1536)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNameSearchQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNameSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNameSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search fundraising records by name."""
        return await _fmp_stable_get(
            "fundraising-search", {"name": query.name}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPNameSearchQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFundraisingSearchData]:
        """Map raw rows to typed model instances."""
        return [FMPFundraisingSearchData.model_validate(r) for r in data]


class FMPCrowdfundingOfferingsSearchFetcher(
    Fetcher[FMPNameSearchQueryParams, list[FMPCrowdfundingOfferingsSearchData]]
):
    """Fetcher for ``/stable/crowdfunding-offerings-search`` (#1539)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNameSearchQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNameSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNameSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search crowdfunding records by name."""
        return await _fmp_stable_get(
            "crowdfunding-offerings-search", {"name": query.name}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPNameSearchQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCrowdfundingOfferingsSearchData]:
        """Map raw rows to typed model instances."""
        return [FMPCrowdfundingOfferingsSearchData.model_validate(r) for r in data]


class FMPMergersAcquisitionsSearchFetcher(
    Fetcher[FMPNameSearchQueryParams, list[FMPMergersAcquisitionsSearchData]]
):
    """Fetcher for ``/stable/mergers-acquisitions-search`` (#1541)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNameSearchQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNameSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNameSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search M&A records by name."""
        return await _fmp_stable_get(
            "mergers-acquisitions-search", {"name": query.name}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPNameSearchQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPMergersAcquisitionsSearchData]:
        """Map raw rows to typed model instances."""
        return [FMPMergersAcquisitionsSearchData.model_validate(r) for r in data]
