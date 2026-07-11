"""FMP Equity Quote Batch Short Model — /stable/batch-quote-short.

Deliberately uncached (tier-2 passthrough forever) — this endpoint IS the
"cheap and fast" poll primitive per PRD §5.1 rationale.
"""

# pylint: disable=unused-argument

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class FMPEquityQuoteBatchShortQueryParams(QueryParams):
    """FMP Batch Quote Short Query.

    Source: https://site.financialmodelingprep.com/developer/docs#batch-quote-short
    """

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    symbol: str = Field(description="Comma-separated symbols (batch endpoint).")


class FMPEquityQuoteBatchShortData(Data):
    """FMP Batch Quote Short row."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Last trade price.")
    change: float | None = Field(default=None, description="Change vs prev close.")
    volume: int | None = Field(default=None, description="Session volume.")


class FMPEquityQuoteBatchShortFetcher(
    Fetcher[
        FMPEquityQuoteBatchShortQueryParams,
        list[FMPEquityQuoteBatchShortData],
    ]
):
    """FMP Batch Quote Short Fetcher (single call, N symbols)."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPEquityQuoteBatchShortQueryParams:
        return FMPEquityQuoteBatchShortQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityQuoteBatchShortQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        symbols = ",".join(s.strip() for s in query.symbol.split(",") if s.strip())
        url = (
            "https://financialmodelingprep.com/stable/batch-quote-short?"
            f"symbols={symbols}&apikey={api_key}"
        )
        data = await amake_request(
            url, response_callback=response_callback, **kwargs
        )
        if not data:
            raise EmptyDataError("No batch quotes returned from FMP.")
        return list(data)

    @staticmethod
    def transform_data(
        query: FMPEquityQuoteBatchShortQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEquityQuoteBatchShortData]:
        return [FMPEquityQuoteBatchShortData.model_validate(d) for d in data]
