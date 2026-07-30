"""FMP company-extras endpoints — 6 fetchers (#1500-#1505).

- ``company-notes``                                   (#1500) — symbol
- ``delisted-companies``                              (#1501) — page + limit
- ``shares-float``                                    (#1502) — symbol
- ``shares-float-all``                                (#1503) — page + limit
- ``acquisition-of-beneficial-ownership``             (#1504) — symbol
- ``executive-compensation-benchmark``                (#1505) — year
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


class FMPSymbolQueryParams(QueryParams):
    """Symbol-only."""

    symbol: str = Field(description="Ticker symbol.")


class FMPPageLimitQueryParams(QueryParams):
    """Page + limit."""

    page: int = Field(default=0)
    limit: int = Field(default=10)


class FMPYearQueryParams(QueryParams):
    """Year."""

    year: int = Field(description="Fiscal year.")


class FMPCompanyNotesData(Data):
    """Row from ``/stable/company-notes`` (#1500)."""

    model_config = ConfigDict(extra="allow")


class FMPDelistedCompaniesData(Data):
    """Row from ``/stable/delisted-companies`` (#1501)."""

    model_config = ConfigDict(extra="allow")


class FMPSharesFloatData(Data):
    """Row from ``/stable/shares-float`` (#1502)."""

    model_config = ConfigDict(extra="allow")


class FMPSharesFloatAllData(Data):
    """Row from ``/stable/shares-float-all`` (#1503)."""

    model_config = ConfigDict(extra="allow")


class FMPAcquisitionOfBeneficialOwnershipData(Data):
    """Row from ``/stable/acquisition-of-beneficial-ownership`` (#1504)."""

    model_config = ConfigDict(extra="allow")


class FMPExecutiveCompensationBenchmarkData(Data):
    """Row from ``/stable/executive-compensation-benchmark`` (#1505)."""

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


class FMPCompanyNotesFetcher(Fetcher[FMPSymbolQueryParams, list[FMPCompanyNotesData]]):
    """Fetcher for ``/stable/company-notes`` (#1500)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch company notes for symbol."""
        return await _fmp_stable_get(
            "company-notes", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCompanyNotesData]:
        """Map."""
        return [FMPCompanyNotesData.model_validate(r) for r in data]


class FMPDelistedCompaniesFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPDelistedCompaniesData]]
):
    """Fetcher for ``/stable/delisted-companies`` (#1501)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch delisted-companies pagination."""
        return await _fmp_stable_get(
            "delisted-companies",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPDelistedCompaniesData]:
        """Map."""
        return [FMPDelistedCompaniesData.model_validate(r) for r in data]


class FMPSharesFloatFetcher(Fetcher[FMPSymbolQueryParams, list[FMPSharesFloatData]]):
    """Fetcher for ``/stable/shares-float`` (#1502)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch shares float for symbol."""
        return await _fmp_stable_get(
            "shares-float", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSharesFloatData]:
        """Map."""
        return [FMPSharesFloatData.model_validate(r) for r in data]


class FMPSharesFloatAllFetcher(
    Fetcher[FMPPageLimitQueryParams, list[FMPSharesFloatAllData]]
):
    """Fetcher for ``/stable/shares-float-all`` (#1503)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPPageLimitQueryParams:
        """Coerce."""
        return FMPPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch all shares-float pagination."""
        return await _fmp_stable_get(
            "shares-float-all",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSharesFloatAllData]:
        """Map."""
        return [FMPSharesFloatAllData.model_validate(r) for r in data]


class FMPAcquisitionOfBeneficialOwnershipFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPAcquisitionOfBeneficialOwnershipData]]
):
    """Fetcher for ``/stable/acquisition-of-beneficial-ownership`` (#1504)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch 13D/G acquisition filings for symbol."""
        return await _fmp_stable_get(
            "acquisition-of-beneficial-ownership",
            {"symbol": query.symbol},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAcquisitionOfBeneficialOwnershipData]:
        """Map."""
        return [FMPAcquisitionOfBeneficialOwnershipData.model_validate(r) for r in data]


class FMPExecutiveCompensationBenchmarkFetcher(
    Fetcher[FMPYearQueryParams, list[FMPExecutiveCompensationBenchmarkData]]
):
    """Fetcher for ``/stable/executive-compensation-benchmark`` (#1505)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPYearQueryParams:
        """Coerce."""
        return FMPYearQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPYearQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch executive-compensation benchmark for year."""
        return await _fmp_stable_get(
            "executive-compensation-benchmark",
            {"year": query.year},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPYearQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPExecutiveCompensationBenchmarkData]:
        """Map."""
        return [FMPExecutiveCompensationBenchmarkData.model_validate(r) for r in data]
