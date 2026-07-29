"""FMP indexes-extras endpoints — 14 fetchers.

Port of 14 indexes-domain endpoints to the plain ``fmp`` provider
under Tier-A parity (#1515-#1528).

No-arg endpoints (6):
- ``dowjones-constituent``                   (#1515)
- ``historical-dowjones-constituent``        (#1516)
- ``sp500-constituent``                      (#1517)
- ``historical-sp500-constituent``           (#1518)
- ``nasdaq-constituent``                     (#1519)
- ``historical-nasdaq-constituent``          (#1520)

Date-only snapshot endpoints (4):
- ``sector-performance-snapshot``            (#1521)
- ``sector-pe-snapshot``                     (#1523)
- ``industry-performance-snapshot``          (#1525)
- ``industry-pe-snapshot``                   (#1527)

Historical range endpoints (4):
- ``historical-sector-performance``          (#1522)  — sector + from + to
- ``historical-sector-pe``                   (#1524)  — sector + from + to
- ``historical-industry-performance``        (#1526)  — industry + from + to
- ``historical-industry-pe``                 (#1528)  — industry + from + to

Design note: unlike the ``fmp_cached`` copies these do NOT cache.
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


class FMPNoParamsQueryParams(QueryParams):
    """Empty query parameters for constituent endpoints."""


class FMPDateSnapshotQueryParams(QueryParams):
    """Date-only snapshot query parameters."""

    date: date_type | str | None = Field(
        default=None, description="Snapshot date YYYY-MM-DD (defaults to latest)."
    )


class FMPSectorRangeQueryParams(QueryParams):
    """Sector + date-range query parameters."""

    sector: str = Field(description="Sector name, e.g. 'Technology'.")
    from_date: date_type | str | None = Field(
        default=None, description="Range start YYYY-MM-DD.", alias="from"
    )
    to_date: date_type | str | None = Field(
        default=None, description="Range end YYYY-MM-DD.", alias="to"
    )

    model_config = ConfigDict(populate_by_name=True)


class FMPIndustryRangeQueryParams(QueryParams):
    """Industry + date-range query parameters."""

    industry: str = Field(description="Industry name, e.g. 'Software'.")
    from_date: date_type | str | None = Field(
        default=None, description="Range start YYYY-MM-DD.", alias="from"
    )
    to_date: date_type | str | None = Field(
        default=None, description="Range end YYYY-MM-DD.", alias="to"
    )

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Data models — extra=allow everywhere for FMP schema drift resilience.
# ---------------------------------------------------------------------------


def _mk(name: str, doc: str) -> type[Data]:
    """Emit a distinct Data subclass keeping RegistryMap happy."""
    return type(
        name, (Data,), {"__doc__": doc, "model_config": ConfigDict(extra="allow")}
    )


class FMPDowjonesConstituentData(Data):
    """Row from ``/stable/dowjones-constituent`` (#1515)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalDowjonesConstituentData(Data):
    """Row from ``/stable/historical-dowjones-constituent`` (#1516)."""

    model_config = ConfigDict(extra="allow")


class FMPSp500ConstituentData(Data):
    """Row from ``/stable/sp500-constituent`` (#1517)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalSp500ConstituentData(Data):
    """Row from ``/stable/historical-sp500-constituent`` (#1518)."""

    model_config = ConfigDict(extra="allow")


class FMPNasdaqConstituentData(Data):
    """Row from ``/stable/nasdaq-constituent`` (#1519)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalNasdaqConstituentData(Data):
    """Row from ``/stable/historical-nasdaq-constituent`` (#1520)."""

    model_config = ConfigDict(extra="allow")


class FMPSectorPerformanceSnapshotData(Data):
    """Row from ``/stable/sector-performance-snapshot`` (#1521)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalSectorPerformanceData(Data):
    """Row from ``/stable/historical-sector-performance`` (#1522)."""

    model_config = ConfigDict(extra="allow")


class FMPSectorPeSnapshotData(Data):
    """Row from ``/stable/sector-pe-snapshot`` (#1523)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalSectorPeData(Data):
    """Row from ``/stable/historical-sector-pe`` (#1524)."""

    model_config = ConfigDict(extra="allow")


class FMPIndustryPerformanceSnapshotData(Data):
    """Row from ``/stable/industry-performance-snapshot`` (#1525)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalIndustryPerformanceData(Data):
    """Row from ``/stable/historical-industry-performance`` (#1526)."""

    model_config = ConfigDict(extra="allow")


class FMPIndustryPeSnapshotData(Data):
    """Row from ``/stable/industry-pe-snapshot`` (#1527)."""

    model_config = ConfigDict(extra="allow")


class FMPHistoricalIndustryPeData(Data):
    """Row from ``/stable/historical-industry-pe`` (#1528)."""

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
    # Filter None values and coerce dates to ISO strings.
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
# No-arg constituent fetchers (6)
# ---------------------------------------------------------------------------


class FMPDowjonesConstituentFetcher(
    Fetcher[FMPNoParamsQueryParams, list[FMPDowjonesConstituentData]]
):
    """Fetcher for ``/stable/dowjones-constituent`` (#1515)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNoParamsQueryParams:
        """No params."""
        return FMPNoParamsQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPNoParamsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch full Dow Jones constituent list."""
        return await _fmp_stable_get("dowjones-constituent", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPNoParamsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPDowjonesConstituentData]:
        """Map raw rows to typed model instances."""
        return [FMPDowjonesConstituentData.model_validate(r) for r in data]


class FMPHistoricalDowjonesConstituentFetcher(
    Fetcher[FMPNoParamsQueryParams, list[FMPHistoricalDowjonesConstituentData]]
):
    """Fetcher for ``/stable/historical-dowjones-constituent`` (#1516)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNoParamsQueryParams:
        """No params."""
        return FMPNoParamsQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPNoParamsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch Dow Jones membership history."""
        return await _fmp_stable_get("historical-dowjones-constituent", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPNoParamsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalDowjonesConstituentData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalDowjonesConstituentData.model_validate(r) for r in data]


class FMPSp500ConstituentFetcher(
    Fetcher[FMPNoParamsQueryParams, list[FMPSp500ConstituentData]]
):
    """Fetcher for ``/stable/sp500-constituent`` (#1517)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNoParamsQueryParams:
        """No params."""
        return FMPNoParamsQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPNoParamsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch full S&P 500 constituent list."""
        return await _fmp_stable_get("sp500-constituent", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPNoParamsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSp500ConstituentData]:
        """Map raw rows to typed model instances."""
        return [FMPSp500ConstituentData.model_validate(r) for r in data]


class FMPHistoricalSp500ConstituentFetcher(
    Fetcher[FMPNoParamsQueryParams, list[FMPHistoricalSp500ConstituentData]]
):
    """Fetcher for ``/stable/historical-sp500-constituent`` (#1518)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNoParamsQueryParams:
        """No params."""
        return FMPNoParamsQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPNoParamsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch S&P 500 membership history."""
        return await _fmp_stable_get("historical-sp500-constituent", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPNoParamsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalSp500ConstituentData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalSp500ConstituentData.model_validate(r) for r in data]


class FMPNasdaqConstituentFetcher(
    Fetcher[FMPNoParamsQueryParams, list[FMPNasdaqConstituentData]]
):
    """Fetcher for ``/stable/nasdaq-constituent`` (#1519)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNoParamsQueryParams:
        """No params."""
        return FMPNoParamsQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPNoParamsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch full NASDAQ 100 constituent list."""
        return await _fmp_stable_get("nasdaq-constituent", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPNoParamsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPNasdaqConstituentData]:
        """Map raw rows to typed model instances."""
        return [FMPNasdaqConstituentData.model_validate(r) for r in data]


class FMPHistoricalNasdaqConstituentFetcher(
    Fetcher[FMPNoParamsQueryParams, list[FMPHistoricalNasdaqConstituentData]]
):
    """Fetcher for ``/stable/historical-nasdaq-constituent`` (#1520)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNoParamsQueryParams:
        """No params."""
        return FMPNoParamsQueryParams()

    @staticmethod
    async def aextract_data(
        query: FMPNoParamsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch NASDAQ 100 membership history."""
        return await _fmp_stable_get("historical-nasdaq-constituent", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPNoParamsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalNasdaqConstituentData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalNasdaqConstituentData.model_validate(r) for r in data]


# ---------------------------------------------------------------------------
# Date-snapshot fetchers (4)
# ---------------------------------------------------------------------------


class FMPSectorPerformanceSnapshotFetcher(
    Fetcher[FMPDateSnapshotQueryParams, list[FMPSectorPerformanceSnapshotData]]
):
    """Fetcher for ``/stable/sector-performance-snapshot`` (#1521)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPDateSnapshotQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPDateSnapshotQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPDateSnapshotQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch sector performance snapshot for date."""
        return await _fmp_stable_get(
            "sector-performance-snapshot", {"date": query.date}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPDateSnapshotQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSectorPerformanceSnapshotData]:
        """Map raw rows to typed model instances."""
        return [FMPSectorPerformanceSnapshotData.model_validate(r) for r in data]


class FMPSectorPeSnapshotFetcher(
    Fetcher[FMPDateSnapshotQueryParams, list[FMPSectorPeSnapshotData]]
):
    """Fetcher for ``/stable/sector-pe-snapshot`` (#1523)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPDateSnapshotQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPDateSnapshotQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPDateSnapshotQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch sector P/E snapshot for date."""
        return await _fmp_stable_get(
            "sector-pe-snapshot", {"date": query.date}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPDateSnapshotQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSectorPeSnapshotData]:
        """Map raw rows to typed model instances."""
        return [FMPSectorPeSnapshotData.model_validate(r) for r in data]


class FMPIndustryPerformanceSnapshotFetcher(
    Fetcher[FMPDateSnapshotQueryParams, list[FMPIndustryPerformanceSnapshotData]]
):
    """Fetcher for ``/stable/industry-performance-snapshot`` (#1525)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPDateSnapshotQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPDateSnapshotQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPDateSnapshotQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch industry performance snapshot for date."""
        return await _fmp_stable_get(
            "industry-performance-snapshot", {"date": query.date}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPDateSnapshotQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPIndustryPerformanceSnapshotData]:
        """Map raw rows to typed model instances."""
        return [FMPIndustryPerformanceSnapshotData.model_validate(r) for r in data]


class FMPIndustryPeSnapshotFetcher(
    Fetcher[FMPDateSnapshotQueryParams, list[FMPIndustryPeSnapshotData]]
):
    """Fetcher for ``/stable/industry-pe-snapshot`` (#1527)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPDateSnapshotQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPDateSnapshotQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPDateSnapshotQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch industry P/E snapshot for date."""
        return await _fmp_stable_get(
            "industry-pe-snapshot", {"date": query.date}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPDateSnapshotQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPIndustryPeSnapshotData]:
        """Map raw rows to typed model instances."""
        return [FMPIndustryPeSnapshotData.model_validate(r) for r in data]


# ---------------------------------------------------------------------------
# Historical range fetchers (4)
# ---------------------------------------------------------------------------


def _range_params(sector_or_industry_key: str, query: Any) -> dict[str, Any]:
    """Assemble sector/industry + from/to params, honoring alias fields."""
    key_val = getattr(query, sector_or_industry_key)
    # from_date/to_date fields carry the alias 'from'/'to' — send FMP-friendly names.
    return {
        sector_or_industry_key: key_val,
        "from": query.from_date,
        "to": query.to_date,
    }


class FMPHistoricalSectorPerformanceFetcher(
    Fetcher[FMPSectorRangeQueryParams, list[FMPHistoricalSectorPerformanceData]]
):
    """Fetcher for ``/stable/historical-sector-performance`` (#1522)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSectorRangeQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSectorRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSectorRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch historical sector performance for range."""
        return await _fmp_stable_get(
            "historical-sector-performance", _range_params("sector", query), credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSectorRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalSectorPerformanceData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalSectorPerformanceData.model_validate(r) for r in data]


class FMPHistoricalSectorPeFetcher(
    Fetcher[FMPSectorRangeQueryParams, list[FMPHistoricalSectorPeData]]
):
    """Fetcher for ``/stable/historical-sector-pe`` (#1524)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSectorRangeQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSectorRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSectorRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch historical sector P/E for range."""
        return await _fmp_stable_get(
            "historical-sector-pe", _range_params("sector", query), credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSectorRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalSectorPeData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalSectorPeData.model_validate(r) for r in data]


class FMPHistoricalIndustryPerformanceFetcher(
    Fetcher[FMPIndustryRangeQueryParams, list[FMPHistoricalIndustryPerformanceData]]
):
    """Fetcher for ``/stable/historical-industry-performance`` (#1526)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPIndustryRangeQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPIndustryRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPIndustryRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch historical industry performance for range."""
        return await _fmp_stable_get(
            "historical-industry-performance",
            _range_params("industry", query),
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPIndustryRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalIndustryPerformanceData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalIndustryPerformanceData.model_validate(r) for r in data]


class FMPHistoricalIndustryPeFetcher(
    Fetcher[FMPIndustryRangeQueryParams, list[FMPHistoricalIndustryPeData]]
):
    """Fetcher for ``/stable/historical-industry-pe`` (#1528)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPIndustryRangeQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPIndustryRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPIndustryRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch historical industry P/E for range."""
        return await _fmp_stable_get(
            "historical-industry-pe", _range_params("industry", query), credentials
        )

    @staticmethod
    def transform_data(
        query: FMPIndustryRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHistoricalIndustryPeData]:
        """Map raw rows to typed model instances."""
        return [FMPHistoricalIndustryPeData.model_validate(r) for r in data]
