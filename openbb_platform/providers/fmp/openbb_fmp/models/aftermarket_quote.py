"""FMP Aftermarket Quote Model — /stable/aftermarket-quote."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator


class FMPAftermarketQuoteQueryParams(QueryParams):
    """FMP Aftermarket Quote Query.

    Source: https://site.financialmodelingprep.com/developer/docs#aftermarket-quote
    """

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    symbol: str = Field(description="Symbol or comma-separated symbols.")


class FMPAftermarketQuoteData(Data):
    """FMP Aftermarket Quote."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Last aftermarket price.")
    bid: float | None = Field(default=None, description="Best bid.")
    ask: float | None = Field(default=None, description="Best ask.")
    bid_size: int | None = Field(default=None, description="Bid size.")
    ask_size: int | None = Field(default=None, description="Ask size.")
    volume: int | None = Field(default=None, description="Aftermarket volume.")
    timestamp: datetime | None = Field(
        default=None, description="Quote timestamp (UTC)."
    )

    @field_validator("timestamp", mode="before", check_fields=False)
    @classmethod
    def _epoch_ms_to_datetime(cls, v: int | str | None):
        """FMP returns epoch milliseconds — convert to naive UTC datetime."""
        if v in (None, ""):
            return None
        try:
            i = int(v)
            return datetime.utcfromtimestamp(i / 1000 if i > 10**11 else i)
        except (TypeError, ValueError):
            return None


class FMPAftermarketQuoteFetcher(
    Fetcher[
        FMPAftermarketQuoteQueryParams,
        list[FMPAftermarketQuoteData],
    ]
):
    """FMP Aftermarket Quote Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPAftermarketQuoteQueryParams:
        return FMPAftermarketQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPAftermarketQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        import asyncio

        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        base = "https://financialmodelingprep.com/stable/aftermarket-quote"
        symbols = [s.strip() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        async def get_one(sym: str) -> None:
            url = f"{base}?symbol={sym}&apikey={api_key}"
            data = await amake_request(
                url, response_callback=response_callback, **kwargs
            )
            for row in data or []:
                row.setdefault("symbol", sym)
                results.append(row)

        await asyncio.gather(*(get_one(s) for s in symbols))
        if not results:
            raise EmptyDataError("No aftermarket quotes returned from FMP.")
        return results

    @staticmethod
    def transform_data(
        query: FMPAftermarketQuoteQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPAftermarketQuoteData]:
        return [FMPAftermarketQuoteData.model_validate(d) for d in data]
