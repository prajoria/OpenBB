"""FMP statements-extras endpoints — 12 fetchers.

Port of the ``fmp_cached`` statements-extras drain to the plain ``fmp``
provider under Tier-A parity (#1488-#1499).

Endpoints:

Symbol-only (11):
- ``enterprise-values``                          (#1488)
- ``financial-growth``                           (#1489)
- ``financial-scores``                           (#1490)
- ``key-metrics-ttm``                            (#1491)
- ``owner-earnings``                             (#1492)
- ``ratios-ttm``                                 (#1493)
- ``income-statement-as-reported``               (#1494)
- ``balance-sheet-statement-as-reported``        (#1495)
- ``cash-flow-statement-as-reported``            (#1496)
- ``financial-statement-full-as-reported``       (#1497)
- ``financial-reports-dates``                    (#1498)

Symbol + year + period (1):
- ``financial-reports-json``                     (#1499)

Design note: unlike the ``fmp_cached`` copies these do NOT cache.
Every call hits FMP live. Caching is ``fmp_cached``'s job by design
(see repo CLAUDE.md "Provider rule").

FinancialReportsJson gotcha: FMP returns a single JSON object (not
a list) keyed by section headers ("INCOME STATEMENTS", "BALANCE SHEETS",
etc.). We wrap it in a one-row list so the ``Fetcher[..., list[Data]]``
contract holds; ``extra=allow`` lets consumers read the section keys.
"""

# pylint: disable=unused-argument

from __future__ import annotations

from typing import Any, Literal

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


class FMPStatementSymbolQueryParams(QueryParams):
    """Symbol-only query parameters shared by 11 statements-extras endpoints."""

    symbol: str = Field(description="Ticker symbol.")


class FMPFinancialReportsJsonQueryParams(QueryParams):
    """Query parameters for the ``financial-reports-json`` endpoint.

    Requires ``year`` and ``period`` in addition to ``symbol``. FMP
    treats ``period`` as a fiscal-quarter label (Q1 / Q2 / Q3 / Q4 / FY).
    """

    symbol: str = Field(description="Ticker symbol.")
    year: int = Field(description="Fiscal year (e.g. 2024).")
    period: Literal["Q1", "Q2", "Q3", "Q4", "FY"] = Field(
        default="FY", description="Fiscal period label."
    )


# ---------------------------------------------------------------------------
# Data models. All use ``extra=allow`` so schema drift on FMP's side
# (new column added) doesn't break the fetcher for the fields we DO map.
# ---------------------------------------------------------------------------


def _make_data_class(name: str, doc: str) -> type[Data]:
    """Create a minimal Data subclass that keeps ``symbol`` typed and
    lets everything else pass through via ``extra=allow``. Keeping every
    endpoint's Data class distinct so ``Fetcher[..., list[DataCls]]``
    remains a concrete generic (OpenBB's RegistryMap._validate rejects
    bare ``list``).
    """

    def _init_subclass():
        cls = type(
            name,
            (Data,),
            {
                "__doc__": doc,
                "model_config": ConfigDict(extra="allow"),
                "__annotations__": {"symbol": str | None},
                "symbol": Field(default=None, description="Ticker symbol."),
            },
        )
        return cls

    return _init_subclass()


class FMPEnterpriseValuesData(Data):
    """Row from ``/stable/enterprise-values`` — enterprise value time series."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPFinancialGrowthData(Data):
    """Row from ``/stable/financial-growth`` — growth-rate time series."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPFinancialScoresData(Data):
    """Row from ``/stable/financial-scores`` — Altman / Piotroski rollup."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPKeyMetricsTtmData(Data):
    """Row from ``/stable/key-metrics-ttm`` — trailing-12-month key metrics."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPOwnerEarningsData(Data):
    """Row from ``/stable/owner-earnings`` — Buffett-style owner earnings."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPRatiosTtmData(Data):
    """Row from ``/stable/ratios-ttm`` — trailing-12-month ratios."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPIncomeStatementAsReportedData(Data):
    """Row from ``/stable/income-statement-as-reported`` — raw XBRL."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPBalanceSheetStatementAsReportedData(Data):
    """Row from ``/stable/balance-sheet-statement-as-reported`` — raw XBRL."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPCashFlowStatementAsReportedData(Data):
    """Row from ``/stable/cash-flow-statement-as-reported`` — raw XBRL."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPFinancialStatementFullAsReportedData(Data):
    """Row from ``/stable/financial-statement-full-as-reported`` — raw XBRL."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPFinancialReportsDatesData(Data):
    """Row from ``/stable/financial-reports-dates`` — filing-date index."""

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")


class FMPFinancialReportsJsonData(Data):
    """One report from ``/stable/financial-reports-json`` — full 10-K JSON.

    FMP returns a single object keyed by section names; wrapped in a
    one-row list to satisfy the ``list[Data]`` fetcher contract.
    """

    model_config = ConfigDict(extra="allow")
    symbol: str | None = Field(default=None, description="Ticker symbol.")
    period: str | None = Field(default=None, description="Fiscal period.")
    year: int | None = Field(default=None, description="Fiscal year.")


# ---------------------------------------------------------------------------
# Shared fetch helper
# ---------------------------------------------------------------------------


async def _fmp_stable_get(
    path: str,
    params: dict[str, Any],
    credentials: dict[str, str] | None,
) -> Any:
    """GET ``/stable/<path>?<params>&apikey=<K>`` and return parsed JSON.

    Returns list or dict as-is (endpoints vary). Raises
    ``EmptyDataError`` when the payload doesn't parse as either.
    Routes apikey through ``params`` (not URL) so it stays out of
    tracebacks and proxy logs.
    """
    api_key = (credentials or {}).get("fmp_api_key", "")
    url = f"{_FMP_STABLE_BASE}/{path}"
    full_params = {**params, "apikey": api_key}
    payload = await amake_request(url, params=full_params)
    if not isinstance(payload, (list, dict)):
        raise EmptyDataError(
            f"{path}: unexpected response shape from FMP "
            f"(got {type(payload).__name__})."
        )
    return payload


# ---------------------------------------------------------------------------
# Symbol-only fetcher template — factory keeps 11 fetcher classes readable.
# Each class is emitted explicitly (not via metaclass) so RegistryMap sees a
# concrete Fetcher[QueryParams, list[DataCls]] generic.
# ---------------------------------------------------------------------------


class FMPEnterpriseValuesFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPEnterpriseValuesData]]
):
    """Fetcher for ``/stable/enterprise-values`` (#1488)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "enterprise-values", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPEnterpriseValuesData]:
        """Map raw rows to typed model instances."""
        return [FMPEnterpriseValuesData.model_validate(r) for r in data]


class FMPFinancialGrowthFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPFinancialGrowthData]]
):
    """Fetcher for ``/stable/financial-growth`` (#1489)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "financial-growth", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFinancialGrowthData]:
        """Map raw rows to typed model instances."""
        return [FMPFinancialGrowthData.model_validate(r) for r in data]


class FMPFinancialScoresFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPFinancialScoresData]]
):
    """Fetcher for ``/stable/financial-scores`` (#1490)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "financial-scores", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFinancialScoresData]:
        """Map raw rows to typed model instances."""
        return [FMPFinancialScoresData.model_validate(r) for r in data]


class FMPKeyMetricsTtmFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPKeyMetricsTtmData]]
):
    """Fetcher for ``/stable/key-metrics-ttm`` (#1491)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "key-metrics-ttm", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPKeyMetricsTtmData]:
        """Map raw rows to typed model instances."""
        return [FMPKeyMetricsTtmData.model_validate(r) for r in data]


class FMPOwnerEarningsFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPOwnerEarningsData]]
):
    """Fetcher for ``/stable/owner-earnings`` (#1492)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "owner-earnings", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPOwnerEarningsData]:
        """Map raw rows to typed model instances."""
        return [FMPOwnerEarningsData.model_validate(r) for r in data]


class FMPRatiosTtmFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPRatiosTtmData]]
):
    """Fetcher for ``/stable/ratios-ttm`` (#1493)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "ratios-ttm", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPRatiosTtmData]:
        """Map raw rows to typed model instances."""
        return [FMPRatiosTtmData.model_validate(r) for r in data]


class FMPIncomeStatementAsReportedFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPIncomeStatementAsReportedData]]
):
    """Fetcher for ``/stable/income-statement-as-reported`` (#1494)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "income-statement-as-reported", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPIncomeStatementAsReportedData]:
        """Map raw rows to typed model instances."""
        return [FMPIncomeStatementAsReportedData.model_validate(r) for r in data]


class FMPBalanceSheetStatementAsReportedFetcher(
    Fetcher[
        FMPStatementSymbolQueryParams,
        list[FMPBalanceSheetStatementAsReportedData],
    ]
):
    """Fetcher for ``/stable/balance-sheet-statement-as-reported`` (#1495)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "balance-sheet-statement-as-reported",
            {"symbol": query.symbol},
            credentials,
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPBalanceSheetStatementAsReportedData]:
        """Map raw rows to typed model instances."""
        return [FMPBalanceSheetStatementAsReportedData.model_validate(r) for r in data]


class FMPCashFlowStatementAsReportedFetcher(
    Fetcher[
        FMPStatementSymbolQueryParams,
        list[FMPCashFlowStatementAsReportedData],
    ]
):
    """Fetcher for ``/stable/cash-flow-statement-as-reported`` (#1496)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "cash-flow-statement-as-reported", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCashFlowStatementAsReportedData]:
        """Map raw rows to typed model instances."""
        return [FMPCashFlowStatementAsReportedData.model_validate(r) for r in data]


class FMPFinancialStatementFullAsReportedFetcher(
    Fetcher[
        FMPStatementSymbolQueryParams,
        list[FMPFinancialStatementFullAsReportedData],
    ]
):
    """Fetcher for ``/stable/financial-statement-full-as-reported`` (#1497)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "financial-statement-full-as-reported",
            {"symbol": query.symbol},
            credentials,
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFinancialStatementFullAsReportedData]:
        """Map raw rows to typed model instances."""
        return [FMPFinancialStatementFullAsReportedData.model_validate(r) for r in data]


class FMPFinancialReportsDatesFetcher(
    Fetcher[FMPStatementSymbolQueryParams, list[FMPFinancialReportsDatesData]]
):
    """Fetcher for ``/stable/financial-reports-dates`` (#1498)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPStatementSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPStatementSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPStatementSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        payload = await _fmp_stable_get(
            "financial-reports-dates", {"symbol": query.symbol}, credentials
        )
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPStatementSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFinancialReportsDatesData]:
        """Map raw rows to typed model instances."""
        return [FMPFinancialReportsDatesData.model_validate(r) for r in data]


class FMPFinancialReportsJsonFetcher(
    Fetcher[FMPFinancialReportsJsonQueryParams, list[FMPFinancialReportsJsonData]]
):
    """Fetcher for ``/stable/financial-reports-json`` (#1499).

    FMP returns a single object with 15+ section keys (INCOME STATEMENTS,
    BALANCE SHEETS, ...). Wrapped in a one-row list so the fetcher
    contract holds; ``extra=allow`` lets consumers read the section keys.
    """

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPFinancialReportsJsonQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPFinancialReportsJsonQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPFinancialReportsJsonQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol/year/period."""
        payload = await _fmp_stable_get(
            "financial-reports-json",
            {"symbol": query.symbol, "year": query.year, "period": query.period},
            credentials,
        )
        # FMP returns a single dict, not a list — wrap.
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def transform_data(
        query: FMPFinancialReportsJsonQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPFinancialReportsJsonData]:
        """Map the single wrapped dict to a typed model instance."""
        return [FMPFinancialReportsJsonData.model_validate(r) for r in data]
