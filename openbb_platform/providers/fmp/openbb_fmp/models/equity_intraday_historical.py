"""FMP Equity Intraday Historical Bar Model — /stable/historical-chart/{interval}."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

IntradayInterval = Literal["1min", "5min", "15min", "30min", "1hour", "4hour"]


class FMPEquityIntradayHistoricalQueryParams(QueryParams):
    """FMP Equity Intraday Historical Query.

    Source: https://site.financialmodelingprep.com/developer/docs#historical-chart
    """

    __alias_dict__ = {"start_date": "from", "end_date": "to"}
    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}

    symbol: str = Field(description="Symbol or comma-separated symbols.")
    interval: IntradayInterval = Field(
        default="5min", description="Bar interval."
    )
    start_date: datetime | None = Field(
        default=None, description="Start of bar window (inclusive)."
    )
    end_date: datetime | None = Field(
        default=None, description="End of bar window (inclusive)."
    )
    extended_hours: bool = Field(
        default=False, description="Include pre-/post-market bars."
    )


class FMPEquityIntradayHistoricalData(Data):
    """FMP Equity Intraday Historical Bar."""

    symbol: str = Field(description="Ticker symbol.")
    interval: IntradayInterval = Field(description="Bar interval.")
    date: datetime = Field(description="Bar-start timestamp (exchange local, tz-naive).")
    open: float = Field(description="Opening price of the bar.")
    high: float = Field(description="High price of the bar.")
    low: float = Field(description="Low price of the bar.")
    close: float = Field(description="Closing price of the bar.")
    volume: int = Field(description="Bar volume.")


class FMPEquityIntradayHistoricalFetcher(
    Fetcher[
        FMPEquityIntradayHistoricalQueryParams,
        list[FMPEquityIntradayHistoricalData],
    ]
):
    """FMP Equity Intraday Historical Bar Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPEquityIntradayHistoricalQueryParams:
        """Transform the query params."""
        return FMPEquityIntradayHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityIntradayHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return raw bars from FMP for one or many symbols."""
        # pylint: disable=import-outside-toplevel
        import asyncio

        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        base = (
            f"https://financialmodelingprep.com/stable/historical-chart/{query.interval}"
        )
        symbols = [s.strip() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        async def get_one(sym: str) -> None:
            url = f"{base}?symbol={sym}&apikey={api_key}"
            if query.start_date is not None:
                url += f"&from={query.start_date.date().isoformat()}"
            if query.end_date is not None:
                url += f"&to={query.end_date.date().isoformat()}"
            data = await amake_request(
                url, response_callback=response_callback, **kwargs
            )
            for row in data or []:
                row["symbol"] = sym
                row["interval"] = query.interval
                results.append(row)

        await asyncio.gather(*(get_one(s) for s in symbols))

        if not results:
            raise EmptyDataError("No intraday bars returned from FMP.")
        return results

    @staticmethod
    def transform_data(
        query: FMPEquityIntradayHistoricalQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEquityIntradayHistoricalData]:
        """Transform to typed rows, sorted (symbol, date)."""
        return [
            FMPEquityIntradayHistoricalData.model_validate(d)
            for d in sorted(data, key=lambda r: (r["symbol"], r["date"]))
        ]
