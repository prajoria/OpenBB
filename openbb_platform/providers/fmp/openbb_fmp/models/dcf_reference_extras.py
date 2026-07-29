"""FMP DCF-extras + reference-lists — 11 fetchers (#1560-#1570).

DCF (4): all symbol-only.
Reference lists (7): all no-args.
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


class FMPEmptyQueryParams(QueryParams):
    """No args."""


# DCF data classes
class FMPDiscountedCashFlowData(Data):
    """Row from ``/stable/discounted-cash-flow`` (#1560)."""

    model_config = ConfigDict(extra="allow")


class FMPLeveredDiscountedCashFlowData(Data):
    """Row from ``/stable/levered-discounted-cash-flow`` (#1561)."""

    model_config = ConfigDict(extra="allow")


class FMPCustomDiscountedCashFlowData(Data):
    """Row from ``/stable/custom-discounted-cash-flow`` (#1562)."""

    model_config = ConfigDict(extra="allow")


class FMPCustomLeveredDiscountedCashFlowData(Data):
    """Row from ``/stable/custom-levered-discounted-cash-flow`` (#1563)."""

    model_config = ConfigDict(extra="allow")


# Reference-list data classes
class FMPStockListData(Data):
    """Row from ``/stable/stock-list`` (#1564)."""

    model_config = ConfigDict(extra="allow")


class FMPEtfListData(Data):
    """Row from ``/stable/etf-list`` (#1565)."""

    model_config = ConfigDict(extra="allow")


class FMPIndexListData(Data):
    """Row from ``/stable/index-list`` (#1566)."""

    model_config = ConfigDict(extra="allow")


class FMPCommoditiesListData(Data):
    """Row from ``/stable/commodities-list`` (#1567)."""

    model_config = ConfigDict(extra="allow")


class FMPForexListData(Data):
    """Row from ``/stable/forex-list`` (#1568)."""

    model_config = ConfigDict(extra="allow")


class FMPCryptocurrencyListData(Data):
    """Row from ``/stable/cryptocurrency-list`` (#1569)."""

    model_config = ConfigDict(extra="allow")


class FMPActivelyTradingListData(Data):
    """Row from ``/stable/actively-trading-list`` (#1570)."""

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


def _symbol_fetcher(path: str, data_cls: type[Data]) -> type[Fetcher]:
    """Local factory would break RegistryMap. Kept explicit below."""
    raise NotImplementedError


# DCF fetchers (4) — all symbol-only
class FMPDiscountedCashFlowFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPDiscountedCashFlowData]]
):
    """Fetcher for ``/stable/discounted-cash-flow`` (#1560)."""

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
        """Fetch DCF valuation for symbol."""
        return await _fmp_stable_get(
            "discounted-cash-flow", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPDiscountedCashFlowData]:
        """Map."""
        return [FMPDiscountedCashFlowData.model_validate(r) for r in data]


class FMPLeveredDiscountedCashFlowFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPLeveredDiscountedCashFlowData]]
):
    """Fetcher for ``/stable/levered-discounted-cash-flow`` (#1561)."""

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
        """Fetch levered DCF valuation."""
        return await _fmp_stable_get(
            "levered-discounted-cash-flow", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPLeveredDiscountedCashFlowData]:
        """Map."""
        return [FMPLeveredDiscountedCashFlowData.model_validate(r) for r in data]


class FMPCustomDiscountedCashFlowFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPCustomDiscountedCashFlowData]]
):
    """Fetcher for ``/stable/custom-discounted-cash-flow`` (#1562)."""

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
        """Fetch custom DCF valuation history."""
        return await _fmp_stable_get(
            "custom-discounted-cash-flow", {"symbol": query.symbol}, credentials
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCustomDiscountedCashFlowData]:
        """Map."""
        return [FMPCustomDiscountedCashFlowData.model_validate(r) for r in data]


class FMPCustomLeveredDiscountedCashFlowFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPCustomLeveredDiscountedCashFlowData]]
):
    """Fetcher for ``/stable/custom-levered-discounted-cash-flow`` (#1563)."""

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
        """Fetch custom levered DCF valuation history."""
        return await _fmp_stable_get(
            "custom-levered-discounted-cash-flow",
            {"symbol": query.symbol},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCustomLeveredDiscountedCashFlowData]:
        """Map."""
        return [FMPCustomLeveredDiscountedCashFlowData.model_validate(r) for r in data]


# Reference-list fetchers (7) — all no-args
class FMPStockListFetcher(Fetcher[FMPEmptyQueryParams, list[FMPStockListData]]):
    """Fetcher for ``/stable/stock-list`` (#1564)."""

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
        """Fetch full stock symbol list."""
        return await _fmp_stable_get("stock-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPStockListData]:
        """Map."""
        return [FMPStockListData.model_validate(r) for r in data]


class FMPEtfListFetcher(Fetcher[FMPEmptyQueryParams, list[FMPEtfListData]]):
    """Fetcher for ``/stable/etf-list`` (#1565)."""

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
        """Fetch full ETF symbol list."""
        return await _fmp_stable_get("etf-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPEtfListData]:
        """Map."""
        return [FMPEtfListData.model_validate(r) for r in data]


class FMPIndexListFetcher(Fetcher[FMPEmptyQueryParams, list[FMPIndexListData]]):
    """Fetcher for ``/stable/index-list`` (#1566)."""

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
        """Fetch full index list."""
        return await _fmp_stable_get("index-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPIndexListData]:
        """Map."""
        return [FMPIndexListData.model_validate(r) for r in data]


class FMPCommoditiesListFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPCommoditiesListData]]
):
    """Fetcher for ``/stable/commodities-list`` (#1567)."""

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
        """Fetch full commodities list."""
        return await _fmp_stable_get("commodities-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCommoditiesListData]:
        """Map."""
        return [FMPCommoditiesListData.model_validate(r) for r in data]


class FMPForexListFetcher(Fetcher[FMPEmptyQueryParams, list[FMPForexListData]]):
    """Fetcher for ``/stable/forex-list`` (#1568)."""

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
        """Fetch full forex pair list."""
        return await _fmp_stable_get("forex-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPForexListData]:
        """Map."""
        return [FMPForexListData.model_validate(r) for r in data]


class FMPCryptocurrencyListFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPCryptocurrencyListData]]
):
    """Fetcher for ``/stable/cryptocurrency-list`` (#1569)."""

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
        """Fetch full crypto list."""
        return await _fmp_stable_get("cryptocurrency-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCryptocurrencyListData]:
        """Map."""
        return [FMPCryptocurrencyListData.model_validate(r) for r in data]


class FMPActivelyTradingListFetcher(
    Fetcher[FMPEmptyQueryParams, list[FMPActivelyTradingListData]]
):
    """Fetcher for ``/stable/actively-trading-list`` (#1570)."""

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
        """Fetch actively-trading symbol list."""
        return await _fmp_stable_get("actively-trading-list", {}, credentials)

    @staticmethod
    def transform_data(
        query: FMPEmptyQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPActivelyTradingListData]:
        """Map."""
        return [FMPActivelyTradingListData.model_validate(r) for r in data]
