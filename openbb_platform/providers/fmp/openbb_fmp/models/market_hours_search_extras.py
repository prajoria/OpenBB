"""FMP market-hours + search-extras — 13 fetchers.

Market-hours (2, #1571-#1572):
- ``all-exchange-market-hours``     (#1571) — no args
- ``holidays-by-exchange``          (#1572) — exchange

Search (11, #1467-#1477):
- ``search-symbol``                       (#1467) — query
- ``search-name``                         (#1468) — query
- ``search-cik``                          (#1469) — cik
- ``search-cusip``                        (#1470) — cusip
- ``search-isin``                         (#1471) — isin
- ``search-exchange-variants``            (#1472) — symbol
- ``cik-list``                            (#1473) — no args
- ``profile-cik``                         (#1474) — cik
- ``symbol-change``                       (#1475) — from + to
- ``financial-statement-symbol-list``     (#1476) — no args
- ``available-countries``                 (#1477) — no args
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
# Query params — one per parameter shape
# ---------------------------------------------------------------------------


class FMPEmptyQueryParams(QueryParams):
    """No args."""


class FMPQueryQueryParams(QueryParams):
    """Free-text search."""

    query: str = Field(description="Search query.")


class FMPCikQueryParams(QueryParams):
    """CIK query."""

    cik: str = Field(description="SEC CIK.")


class FMPCusipQueryParams(QueryParams):
    """CUSIP query."""

    cusip: str = Field(description="9-char CUSIP.")


class FMPIsinQueryParams(QueryParams):
    """ISIN query."""

    isin: str = Field(description="12-char ISIN.")


class FMPSymbolQueryParams(QueryParams):
    """Symbol query."""

    symbol: str = Field(description="Ticker symbol.")


class FMPExchangeQueryParams(QueryParams):
    """Exchange query."""

    exchange: str = Field(description="Exchange code.")


class FMPDateRangeQueryParams(QueryParams):
    """From/to date range."""

    from_date: date_type | str | None = Field(default=None, alias="from")
    to_date: date_type | str | None = Field(default=None, alias="to")

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class FMPAllExchangeMarketHoursData(Data):
    """Row from ``/stable/all-exchange-market-hours`` (#1571)."""

    model_config = ConfigDict(extra="allow")


class FMPHolidaysByExchangeData(Data):
    """Row from ``/stable/holidays-by-exchange`` (#1572)."""

    model_config = ConfigDict(extra="allow")


class FMPSearchSymbolData(Data):
    """Row from ``/stable/search-symbol`` (#1467)."""

    model_config = ConfigDict(extra="allow")


class FMPSearchNameData(Data):
    """Row from ``/stable/search-name`` (#1468)."""

    model_config = ConfigDict(extra="allow")


class FMPSearchCikData(Data):
    """Row from ``/stable/search-cik`` (#1469)."""

    model_config = ConfigDict(extra="allow")


class FMPSearchCusipData(Data):
    """Row from ``/stable/search-cusip`` (#1470)."""

    model_config = ConfigDict(extra="allow")


class FMPSearchIsinData(Data):
    """Row from ``/stable/search-isin`` (#1471)."""

    model_config = ConfigDict(extra="allow")


class FMPSearchExchangeVariantsData(Data):
    """Row from ``/stable/search-exchange-variants`` (#1472)."""

    model_config = ConfigDict(extra="allow")


class FMPCikListData(Data):
    """Row from ``/stable/cik-list`` (#1473)."""

    model_config = ConfigDict(extra="allow")


class FMPProfileCikData(Data):
    """Row from ``/stable/profile-cik`` (#1474)."""

    model_config = ConfigDict(extra="allow")


class FMPSymbolChangeData(Data):
    """Row from ``/stable/symbol-change`` (#1475)."""

    model_config = ConfigDict(extra="allow")


class FMPFinancialStatementSymbolListData(Data):
    """Row from ``/stable/financial-statement-symbol-list`` (#1476)."""

    model_config = ConfigDict(extra="allow")


class FMPAvailableCountriesData(Data):
    """Row from ``/stable/available-countries`` (#1477)."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Shared fetch helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Market-hours fetchers (2)
# ---------------------------------------------------------------------------


class FMPAllExchangeMarketHoursFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPAllExchangeMarketHoursData]]
):
    """Fetcher for ``/stable/all-exchange-market-hours`` (#1571)."""

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
        """Fetch market hours across exchanges."""
        return await _fmp_stable_get("all-exchange-market-hours", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAllExchangeMarketHoursData]:
        """Map."""
        return [FMPAllExchangeMarketHoursData.model_validate(r) for r in data]


class FMPHolidaysByExchangeFetcher(
    Fetcher[FMPExchangeQueryParams, list[FMPHolidaysByExchangeData]]
):
    """Fetcher for ``/stable/holidays-by-exchange`` (#1572)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPExchangeQueryParams:
        """Coerce."""
        return FMPExchangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPExchangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch holidays for exchange."""
        return await _fmp_stable_get(
            "holidays-by-exchange", {"exchange": query.exchange}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPExchangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPHolidaysByExchangeData]:
        """Map."""
        return [FMPHolidaysByExchangeData.model_validate(r) for r in data]


# ---------------------------------------------------------------------------
# Search fetchers (11)
# ---------------------------------------------------------------------------


class FMPSearchSymbolFetcher(Fetcher[FMPQueryQueryParams, list[FMPSearchSymbolData]]):
    """Fetcher for ``/stable/search-symbol`` (#1467)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQueryQueryParams:
        """Coerce."""
        return FMPQueryQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQueryQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search by symbol."""
        return await _fmp_stable_get(
            "search-symbol", {"query": query.query}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPQueryQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSearchSymbolData]:
        """Map."""
        return [FMPSearchSymbolData.model_validate(r) for r in data]


class FMPSearchNameFetcher(Fetcher[FMPQueryQueryParams, list[FMPSearchNameData]]):
    """Fetcher for ``/stable/search-name`` (#1468)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPQueryQueryParams:
        """Coerce."""
        return FMPQueryQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPQueryQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search by company name."""
        return await _fmp_stable_get("search-name", {"query": query.query}, credentials)

    @staticmethod
    def transform_data(
        query: FMPQueryQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSearchNameData]:
        """Map."""
        return [FMPSearchNameData.model_validate(r) for r in data]


class FMPSearchCikFetcher(Fetcher[FMPCikQueryParams, list[FMPSearchCikData]]):
    """Fetcher for ``/stable/search-cik`` (#1469)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCikQueryParams:
        """Coerce."""
        return FMPCikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCikQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search by CIK."""
        return await _fmp_stable_get("search-cik", {"cik": query.cik}, credentials)

    @staticmethod
    def transform_data(
        query: FMPCikQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSearchCikData]:
        """Map."""
        return [FMPSearchCikData.model_validate(r) for r in data]


class FMPSearchCusipFetcher(Fetcher[FMPCusipQueryParams, list[FMPSearchCusipData]]):
    """Fetcher for ``/stable/search-cusip`` (#1470)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCusipQueryParams:
        """Coerce."""
        return FMPCusipQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCusipQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search by CUSIP."""
        return await _fmp_stable_get(
            "search-cusip", {"cusip": query.cusip}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPCusipQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSearchCusipData]:
        """Map."""
        return [FMPSearchCusipData.model_validate(r) for r in data]


class FMPSearchIsinFetcher(Fetcher[FMPIsinQueryParams, list[FMPSearchIsinData]]):
    """Fetcher for ``/stable/search-isin`` (#1471)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPIsinQueryParams:
        """Coerce."""
        return FMPIsinQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPIsinQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Search by ISIN."""
        return await _fmp_stable_get("search-isin", {"isin": query.isin}, credentials)

    @staticmethod
    def transform_data(
        query: FMPIsinQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSearchIsinData]:
        """Map."""
        return [FMPSearchIsinData.model_validate(r) for r in data]


class FMPSearchExchangeVariantsFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPSearchExchangeVariantsData]]
):
    """Fetcher for ``/stable/search-exchange-variants`` (#1472)."""

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
        """Fetch exchange listings for a symbol."""
        return await _fmp_stable_get(
            "search-exchange-variants", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSearchExchangeVariantsData]:
        """Map."""
        return [FMPSearchExchangeVariantsData.model_validate(r) for r in data]


class FMPCikListFetcher(Fetcher[FMPEmptyQueryParams, list[FMPCikListData]]):
    """Fetcher for ``/stable/cik-list`` (#1473)."""

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
        """Fetch full CIK list."""
        return await _fmp_stable_get("cik-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCikListData]:
        """Map."""
        return [FMPCikListData.model_validate(r) for r in data]


class FMPProfileCikFetcher(Fetcher[FMPCikQueryParams, list[FMPProfileCikData]]):
    """Fetcher for ``/stable/profile-cik`` (#1474)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCikQueryParams:
        """Coerce."""
        return FMPCikQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCikQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch company profile by CIK."""
        return await _fmp_stable_get("profile-cik", {"cik": query.cik}, credentials)

    @staticmethod
    def transform_data(
        query: FMPCikQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPProfileCikData]:
        """Map."""
        return [FMPProfileCikData.model_validate(r) for r in data]


class FMPSymbolChangeFetcher(
    Fetcher[FMPDateRangeQueryParams, list[FMPSymbolChangeData]]
):
    """Fetcher for ``/stable/symbol-change`` (#1475)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPDateRangeQueryParams:
        """Coerce."""
        return FMPDateRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPDateRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch symbol-change filings for range."""
        return await _fmp_stable_get(
            "symbol-change",
            {"from": query.from_date, "to": query.to_date},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPDateRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPSymbolChangeData]:
        """Map."""
        return [FMPSymbolChangeData.model_validate(r) for r in data]


class FMPFinancialStatementSymbolListFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPFinancialStatementSymbolListData]]
):
    """Fetcher for ``/stable/financial-statement-symbol-list`` (#1476)."""

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
        """Fetch list of symbols with financial statements."""
        return await _fmp_stable_get("financial-statement-symbol-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFinancialStatementSymbolListData]:
        """Map."""
        return [FMPFinancialStatementSymbolListData.model_validate(r) for r in data]


class FMPAvailableCountriesFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPAvailableCountriesData]]
):
    """Fetcher for ``/stable/available-countries`` (#1477)."""

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
        """Fetch country coverage list."""
        return await _fmp_stable_get("available-countries", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPAvailableCountriesData]:
        """Map."""
        return [FMPAvailableCountriesData.model_validate(r) for r in data]
