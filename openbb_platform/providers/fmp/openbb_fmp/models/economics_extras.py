"""FMP economics-extras endpoints — 5 fetchers.

Port of 5 economics-domain endpoints to plain ``fmp`` provider under
Tier-A parity (#1529-#1533).

Endpoints:
- ``economic-indicators``               (#1529) — name + from + to
- ``market-risk-premium``               (#1530) — no args
- ``commitment-of-traders-analysis``    (#1531) — symbol
- ``commitment-of-traders-list``        (#1532) — no args
- ``commitment-of-traders-report``      (#1533) — symbol
"""

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


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class FMPEmptyQueryParams(QueryParams):
    """No-args query params."""


class FMPSymbolQueryParams(QueryParams):
    """Symbol-only query params."""

    symbol: str = Field(description="Instrument symbol.")


class FMPEconomicIndicatorQueryParams(QueryParams):
    """Economic-indicator query params (name + optional from/to range)."""

    name: str = Field(description="Indicator name, e.g. 'CPI', 'unemploymentRate'.")
    from_date: date_type | str | None = Field(
        default=None, description="Range start YYYY-MM-DD.", alias="from"
    )
    to_date: date_type | str | None = Field(
        default=None, description="Range end YYYY-MM-DD.", alias="to"
    )

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPEconomicIndicatorsData(Data):
    """Row from ``/stable/economic-indicators`` (#1529)."""

    model_config = ConfigDict(extra="allow")


class FMPMarketRiskPremiumData(Data):
    """Row from ``/stable/market-risk-premium`` (#1530)."""

    model_config = ConfigDict(extra="allow")


class FMPCommitmentOfTradersAnalysisData(Data):
    """Row from ``/stable/commitment-of-traders-analysis`` (#1531)."""

    model_config = ConfigDict(extra="allow")


class FMPCommitmentOfTradersListData(Data):
    """Row from ``/stable/commitment-of-traders-list`` (#1532)."""

    model_config = ConfigDict(extra="allow")


class FMPCommitmentOfTradersReportData(Data):
    """Row from ``/stable/commitment-of-traders-report`` (#1533)."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Shared fetch helper
# ---------------------------------------------------------------------------


async def _fmp_stable_get(
    path: str, params: dict[str, Any], credentials: dict[str, str] | None
) -> list[dict]:
    """GET /stable/<path>?<params>&apikey=<K>. Raises EmptyDataError on non-list."""
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
# Fetchers
# ---------------------------------------------------------------------------


class FMPEconomicIndicatorsFetcher(
    Fetcher[FMPEconomicIndicatorQueryParams, list[FMPEconomicIndicatorsData]]
):
    """Fetcher for ``/stable/economic-indicators`` (#1529)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEconomicIndicatorQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPEconomicIndicatorQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEconomicIndicatorQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch time series for named indicator."""
        return await _fmp_stable_get(
            "economic-indicators",
            {"name": query.name, "from": query.from_date, "to": query.to_date},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPEconomicIndicatorQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPEconomicIndicatorsData]:
        """Map raw rows to typed model instances."""
        return [FMPEconomicIndicatorsData.model_validate(r) for r in data]


class FMPMarketRiskPremiumFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPMarketRiskPremiumData]]
):
    """Fetcher for ``/stable/market-risk-premium`` (#1530)."""

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
        """Fetch full market risk-premium table by country."""
        return await _fmp_stable_get("market-risk-premium", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPMarketRiskPremiumData]:
        """Map raw rows to typed model instances."""
        return [FMPMarketRiskPremiumData.model_validate(r) for r in data]


class FMPCommitmentOfTradersAnalysisFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPCommitmentOfTradersAnalysisData]]
):
    """Fetcher for ``/stable/commitment-of-traders-analysis`` (#1531)."""

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
        """Fetch COT analysis for symbol."""
        return await _fmp_stable_get(
            "commitment-of-traders-analysis", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCommitmentOfTradersAnalysisData]:
        """Map raw rows to typed model instances."""
        return [FMPCommitmentOfTradersAnalysisData.model_validate(r) for r in data]


class FMPCommitmentOfTradersListFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPCommitmentOfTradersListData]]
):
    """Fetcher for ``/stable/commitment-of-traders-list`` (#1532)."""

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
        """Fetch the list of instruments COT covers."""
        return await _fmp_stable_get("commitment-of-traders-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCommitmentOfTradersListData]:
        """Map raw rows to typed model instances."""
        return [FMPCommitmentOfTradersListData.model_validate(r) for r in data]


class FMPCommitmentOfTradersReportFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPCommitmentOfTradersReportData]]
):
    """Fetcher for ``/stable/commitment-of-traders-report`` (#1533)."""

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
        """Fetch COT full report for symbol."""
        return await _fmp_stable_get(
            "commitment-of-traders-report", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCommitmentOfTradersReportData]:
        """Map raw rows to typed model instances."""
        return [FMPCommitmentOfTradersReportData.model_validate(r) for r in data]
