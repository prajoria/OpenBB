"""FMP available-lists extras — 3 no-args fetchers (#1478-#1480)."""

# pylint: disable=unused-argument

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_core.provider.utils.helpers import amake_request
from pydantic import ConfigDict

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


class FMPEmptyQueryParams(QueryParams):
    """No args."""


class FMPAvailableExchangesData(Data):
    """Row from ``/stable/available-exchanges`` (#1478)."""

    model_config = ConfigDict(extra="allow")


class FMPAvailableIndustriesData(Data):
    """Row from ``/stable/available-industries`` (#1479)."""

    model_config = ConfigDict(extra="allow")


class FMPAvailableSectorsData(Data):
    """Row from ``/stable/available-sectors`` (#1480)."""

    model_config = ConfigDict(extra="allow")


async def _fmp_stable_get(path: str, credentials: dict[str, str] | None) -> list[dict]:
    """GET /stable/<path>?apikey=<K>."""
    api_key = (credentials or {}).get("fmp_api_key", "")
    url = f"{_FMP_STABLE_BASE}/{path}"
    payload = await amake_request(url, params={"apikey": api_key})
    if not isinstance(payload, list):
        raise EmptyDataError(
            f"{path}: unexpected response shape from FMP "
            f"(got {type(payload).__name__}; expected list)."
        )
    return payload


class FMPAvailableExchangesFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPAvailableExchangesData]]
):
    """Fetcher for ``/stable/available-exchanges`` (#1478)."""

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
        """Fetch full exchange list."""
        return await _fmp_stable_get("available-exchanges", credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAvailableExchangesData]:
        """Map."""
        return [FMPAvailableExchangesData.model_validate(r) for r in data]


class FMPAvailableIndustriesFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPAvailableIndustriesData]]
):
    """Fetcher for ``/stable/available-industries`` (#1479)."""

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
        """Fetch full industry list."""
        return await _fmp_stable_get("available-industries", credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAvailableIndustriesData]:
        """Map."""
        return [FMPAvailableIndustriesData.model_validate(r) for r in data]


class FMPAvailableSectorsFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPAvailableSectorsData]]
):
    """Fetcher for ``/stable/available-sectors`` (#1480)."""

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
        """Fetch full sector list."""
        return await _fmp_stable_get("available-sectors", credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAvailableSectorsData]:
        """Map."""
        return [FMPAvailableSectorsData.model_validate(r) for r in data]
