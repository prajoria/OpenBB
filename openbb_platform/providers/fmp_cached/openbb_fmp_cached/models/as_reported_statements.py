"""Cached FMP as-reported statement family + financial-reports-json.

W1 Statements drain, batch 14 (#1142 #1146 #1147 #1148 #1149).

5 endpoints returning wide/nested rows — all use extra=allow because
the ``data`` field is a free-form dict of report line items.

- ``income-statement-as-reported`` (#1146)
- ``balance-sheet-statement-as-reported`` (#1147)
- ``cash-flow-statement-as-reported`` (#1148)
- ``financial-statement-full-as-reported`` (#1149)
- ``financial-reports-json`` (#1142) — 10-K sections as nested dict

All symbol=<TICKER>-keyed except financial-reports-json which needs
symbol+year+period.

**Not shipped**: #1143 (financial-reports-xlsx) returns a binary
Excel blob, incompatible with the JSON-blob Data model. Handled
separately (closed as not_planned in this session).
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import ConfigDict, Field

from openbb_fmp_cached.models.search_endpoints import _SearchFetcherBase
from openbb_fmp_cached.models.single_param_endpoints import _SymbolQueryParams

logger = logging.getLogger(__name__)


class _SymbolYearPeriodQueryParams(QueryParams):
    """Query params for financial-reports-json (symbol + year + period)."""

    symbol: str = Field(description="Ticker symbol.")
    year: str = Field(description="Fiscal year (as string, e.g. '2025').")
    period: str = Field(description="Period label (e.g. 'Q1', 'Q2', 'FY').")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedAsReportedData(Data):
    """Row from any of the 4 as-reported statement endpoints.

    Shape: {symbol, fiscalYear, period, reportedCurrency, date, data: {...}}.
    The nested ``data`` dict is FMP's raw as-filed line items.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    fiscal_year: int | None = Field(default=None, description="Fiscal year.")
    period: str | None = Field(default=None, description="Period label.")
    reported_currency: str | None = Field(default=None, description="Currency.")
    date: str | None = Field(default=None, description="Report date.")
    data: dict[str, Any] | None = Field(
        default=None, description="Raw as-reported line items."
    )


class FMPCachedFinancialReportsJsonData(Data):
    """Row from ``/stable/financial-reports-json``.

    Shape: {symbol, period, year, <section-name>: [...], ...} where the
    sections (Cover Page, Balance Sheet, etc.) are free-form. Keep it
    loose via extra=allow.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    period: str | None = Field(default=None, description="Period label.")
    year: str | None = Field(default=None, description="Fiscal year as string.")


_AS_REPORTED_ALIASES = {
    "fiscalYear": "fiscal_year",
    "reportedCurrency": "reported_currency",
}


# ---------------------------------------------------------------------------
# Fetchers — 4 as-reported (symbol) + 1 financial-reports-json (symbol/year/period)
# ---------------------------------------------------------------------------


class FMPCachedIncomeStatementAsReportedFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedAsReportedData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/income-statement-as-reported`` (#1146)."""

    _path = "income-statement-as-reported"
    _data_cls = FMPCachedAsReportedData
    _alias_map = _AS_REPORTED_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedIncomeStatementAsReportedFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAsReportedData]:
        """Map raw rows to typed as-reported data."""
        return FMPCachedIncomeStatementAsReportedFetcher._transform(data)


class FMPCachedBalanceSheetAsReportedFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedAsReportedData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/balance-sheet-statement-as-reported`` (#1147)."""

    _path = "balance-sheet-statement-as-reported"
    _data_cls = FMPCachedAsReportedData
    _alias_map = _AS_REPORTED_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedBalanceSheetAsReportedFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAsReportedData]:
        """Map raw rows to typed as-reported data."""
        return FMPCachedBalanceSheetAsReportedFetcher._transform(data)


class FMPCachedCashFlowAsReportedFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedAsReportedData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/cash-flow-statement-as-reported`` (#1148)."""

    _path = "cash-flow-statement-as-reported"
    _data_cls = FMPCachedAsReportedData
    _alias_map = _AS_REPORTED_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedCashFlowAsReportedFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAsReportedData]:
        """Map raw rows to typed as-reported data."""
        return FMPCachedCashFlowAsReportedFetcher._transform(data)


class FMPCachedFinancialStatementFullAsReportedFetcher(
    Fetcher[_SymbolQueryParams, list[FMPCachedAsReportedData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/financial-statement-full-as-reported`` (#1149)."""

    _path = "financial-statement-full-as-reported"
    _data_cls = FMPCachedAsReportedData
    _alias_map = _AS_REPORTED_ALIASES
    _query_field = "symbol"

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch."""
        return await FMPCachedFinancialStatementFullAsReportedFetcher._fetch(
            query.symbol, credentials
        )

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAsReportedData]:
        """Map raw rows to typed as-reported data."""
        return FMPCachedFinancialStatementFullAsReportedFetcher._transform(data)


class FMPCachedFinancialReportsJsonFetcher(
    Fetcher[_SymbolYearPeriodQueryParams, list[FMPCachedFinancialReportsJsonData]],
    _SearchFetcherBase,
):
    """Cached fetcher for ``/stable/financial-reports-json`` (#1142).

    Overrides ``_fetch`` to send 3 params (symbol/year/period) instead
    of the single ``_query_field`` the base assumes. Also handles the
    fact that FMP returns a *single dict object*, not a list, so we
    wrap it in a list before transform.
    """

    _path = "financial-reports-json"
    _data_cls = FMPCachedFinancialReportsJsonData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolYearPeriodQueryParams:
        """Coerce raw params dict into typed 3-field query object."""
        return _SymbolYearPeriodQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolYearPeriodQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch with 3 params + wrap single-dict response."""
        import httpx

        from openbb_fmp_cached.models.available_directories import _resolve_api_key
        from openbb_fmp_cached.utils.security import raise_for_status_redacted

        api_key = _resolve_api_key(credentials)
        params = {
            "symbol": query.symbol,
            "year": query.year,
            "period": query.period,
            "apikey": api_key,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://financialmodelingprep.com/stable/{FMPCachedFinancialReportsJsonFetcher._path}",
                params=params,
            )
        raise_for_status_redacted(resp)
        payload = resp.json()
        # FMP returns a single dict object for this endpoint, not a list.
        # Wrap it so downstream transform_data sees a list of 1 row.
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return payload
        raise RuntimeError(
            f"financial-reports-json: unexpected response shape: "
            f"{type(payload).__name__}"
        )

    @staticmethod
    def transform_data(
        query: _SymbolYearPeriodQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedFinancialReportsJsonData]:
        """Map raw rows to typed financial-reports-json data."""
        return FMPCachedFinancialReportsJsonFetcher._transform(data)
