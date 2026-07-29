"""FMP government-extras endpoints — 6 fetchers (#1554-#1559)."""

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


class FMPPageLimitQueryParams(QueryParams):
    """Page + limit."""

    page: int = Field(default=0)
    limit: int = Field(default=10)


class FMPNameQueryParams(QueryParams):
    """Name-only search."""

    name: str = Field(description="Free-text name query.")


class FMPSenateIdQueryParams(QueryParams):
    """SenateID query."""

    senate_id: str = Field(description="Bioguide ID.", alias="senateID")

    model_config = ConfigDict(populate_by_name=True)


class FMPEmptyQueryParams(QueryParams):
    """No args."""


class FMPHouseLatestData(Data):
    """Row from ``/stable/house-latest`` (#1554)."""

    model_config = ConfigDict(extra="allow")


class FMPSenateLatestData(Data):
    """Row from ``/stable/senate-latest`` (#1555)."""

    model_config = ConfigDict(extra="allow")


class FMPSenateNetWorthData(Data):
    """Row from ``/stable/senate-net-worth`` (#1556)."""

    model_config = ConfigDict(extra="allow")


class FMPSenateNetWorthAggregatedData(Data):
    """Row from ``/stable/senate-net-worth-aggregated`` (#1557)."""

    model_config = ConfigDict(extra="allow")


class FMPSenatePositionsData(Data):
    """Row from ``/stable/senate-positions`` (#1558)."""

    model_config = ConfigDict(extra="allow")


class FMPSenateProfileData(Data):
    """Row from ``/stable/senate-profile`` (#1559)."""

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


class FMPHouseLatestFetcher(Fetcher[FMPPageLimitQueryParams, list[FMPHouseLatestData]]):
    """Fetcher for ``/stable/house-latest`` (#1554)."""

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
        """Fetch latest House disclosures."""
        return await _fmp_stable_get(
            "house-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHouseLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPHouseLatestData.model_validate(r) for r in data]


class FMPSenateLatestFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPSenateLatestData]]
):
    """Fetcher for ``/stable/senate-latest`` (#1555)."""

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
        """Fetch latest Senate disclosures."""
        return await _fmp_stable_get(
            "senate-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSenateLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPSenateLatestData.model_validate(r) for r in data]


class FMPSenateNetWorthFetcher(
    Fetcher[FMPSenateIdQueryParams, list[FMPSenateNetWorthData]]
):
    """Fetcher for ``/stable/senate-net-worth`` (#1556)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSenateIdQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSenateIdQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSenateIdQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch senator net worth by ID."""
        return await _fmp_stable_get(
            "senate-net-worth", {"senateID": query.senate_id}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSenateIdQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSenateNetWorthData]:
        """Map raw rows to typed model instances."""
        return [FMPSenateNetWorthData.model_validate(r) for r in data]


class FMPSenateNetWorthAggregatedFetcher(
    Fetcher[FMPSenateIdQueryParams, list[FMPSenateNetWorthAggregatedData]]
):
    """Fetcher for ``/stable/senate-net-worth-aggregated`` (#1557)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSenateIdQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSenateIdQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSenateIdQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch aggregated net-worth series for senator ID."""
        return await _fmp_stable_get(
            "senate-net-worth-aggregated",
            {"senateID": query.senate_id},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPSenateIdQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSenateNetWorthAggregatedData]:
        """Map raw rows to typed model instances."""
        return [FMPSenateNetWorthAggregatedData.model_validate(r) for r in data]


class FMPSenatePositionsFetcher(
    Fetcher[FMPNameQueryParams, list[FMPSenatePositionsData]]
):
    """Fetcher for ``/stable/senate-positions`` (#1558)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNameQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNameQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNameQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search senator positions by name."""
        return await _fmp_stable_get(
            "senate-positions", {"name": query.name}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPNameQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSenatePositionsData]:
        """Map raw rows to typed model instances."""
        return [FMPSenatePositionsData.model_validate(r) for r in data]


class FMPSenateProfileFetcher(Fetcher[FMPNameQueryParams, list[FMPSenateProfileData]]):
    """Fetcher for ``/stable/senate-profile`` (#1559)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNameQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNameQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNameQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search senator profiles by name."""
        return await _fmp_stable_get(
            "senate-profile", {"name": query.name}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPNameQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSenateProfileData]:
        """Map raw rows to typed model instances."""
        return [FMPSenateProfileData.model_validate(r) for r in data]
