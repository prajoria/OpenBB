"""FMP news-extras endpoints — 5 fetchers.

Port of 5 news-domain endpoints to plain ``fmp`` (#1544-#1548).

Symbols + range (2):
- ``news/crypto``           (#1544) — symbols + from + to
- ``news/forex``            (#1546) — symbols + from + to

Page+limit (3):
- ``news/crypto-latest``    (#1545)
- ``news/forex-latest``     (#1547)
- ``fmp-articles``          (#1548)
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


class FMPNewsSymbolsRangeQueryParams(QueryParams):
    """Symbols + range query params."""

    symbols: str | list[str] = Field(description="Comma-separated tickers or list.")
    from_date: date_type | str | None = Field(
        default=None, description="Range start.", alias="from"
    )
    to_date: date_type | str | None = Field(
        default=None, description="Range end.", alias="to"
    )

    model_config = ConfigDict(populate_by_name=True)


class FMPNewsPageLimitQueryParams(QueryParams):
    """Page + limit query params."""

    page: int = Field(default=0, description="Page number.")
    limit: int = Field(default=10, description="Page size.")


def _symbols_to_csv(v: str | list[str]) -> str:
    """Coerce list-or-str to CSV."""
    return ",".join(str(x).strip() for x in v if x) if isinstance(v, list) else str(v)


class FMPNewsCryptoData(Data):
    """Row from ``/stable/news/crypto`` (#1544)."""

    model_config = ConfigDict(extra="allow")


class FMPNewsCryptoLatestData(Data):
    """Row from ``/stable/news/crypto-latest`` (#1545)."""

    model_config = ConfigDict(extra="allow")


class FMPNewsForexData(Data):
    """Row from ``/stable/news/forex`` (#1546)."""

    model_config = ConfigDict(extra="allow")


class FMPNewsForexLatestData(Data):
    """Row from ``/stable/news/forex-latest`` (#1547)."""

    model_config = ConfigDict(extra="allow")


class FMPFmpArticlesData(Data):
    """Row from ``/stable/fmp-articles`` (#1548)."""

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


class FMPNewsCryptoFetcher(
    Fetcher[FMPNewsSymbolsRangeQueryParams, list[FMPNewsCryptoData]]
):
    """Fetcher for ``/stable/news/crypto`` (#1544)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNewsSymbolsRangeQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNewsSymbolsRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNewsSymbolsRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch crypto news for symbols + range."""
        return await _fmp_stable_get(
            "news/crypto",
            {
                "symbols": _symbols_to_csv(query.symbols),
                "from": query.from_date,
                "to": query.to_date,
            },
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPNewsSymbolsRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPNewsCryptoData]:
        """Map raw rows to typed model instances."""
        return [FMPNewsCryptoData.model_validate(r) for r in data]


class FMPNewsForexFetcher(
    Fetcher[FMPNewsSymbolsRangeQueryParams, list[FMPNewsForexData]]
):
    """Fetcher for ``/stable/news/forex`` (#1546)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNewsSymbolsRangeQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNewsSymbolsRangeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNewsSymbolsRangeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch forex news for symbols + range."""
        return await _fmp_stable_get(
            "news/forex",
            {
                "symbols": _symbols_to_csv(query.symbols),
                "from": query.from_date,
                "to": query.to_date,
            },
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPNewsSymbolsRangeQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPNewsForexData]:
        """Map raw rows to typed model instances."""
        return [FMPNewsForexData.model_validate(r) for r in data]


class FMPNewsCryptoLatestFetcher(
    Fetcher[FMPNewsPageLimitQueryParams, list[FMPNewsCryptoLatestData]]
):
    """Fetcher for ``/stable/news/crypto-latest`` (#1545)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNewsPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNewsPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNewsPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch latest crypto news."""
        return await _fmp_stable_get(
            "news/crypto-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPNewsPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPNewsCryptoLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPNewsCryptoLatestData.model_validate(r) for r in data]


class FMPNewsForexLatestFetcher(
    Fetcher[FMPNewsPageLimitQueryParams, list[FMPNewsForexLatestData]]
):
    """Fetcher for ``/stable/news/forex-latest`` (#1547)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNewsPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNewsPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNewsPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch latest forex news."""
        return await _fmp_stable_get(
            "news/forex-latest",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPNewsPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPNewsForexLatestData]:
        """Map raw rows to typed model instances."""
        return [FMPNewsForexLatestData.model_validate(r) for r in data]


class FMPFmpArticlesFetcher(
    Fetcher[FMPNewsPageLimitQueryParams, list[FMPFmpArticlesData]]
):
    """Fetcher for ``/stable/fmp-articles`` (#1548)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPNewsPageLimitQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPNewsPageLimitQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPNewsPageLimitQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch FMP-authored articles."""
        return await _fmp_stable_get(
            "fmp-articles",
            {"page": query.page, "limit": query.limit},
            credentials,
        )

    @staticmethod
    def transform_data(
        query: FMPNewsPageLimitQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPFmpArticlesData]:
        """Map raw rows to typed model instances."""
        return [FMPFmpArticlesData.model_validate(r) for r in data]
