"""FMP Technical Indicator (Intraday) Model — /stable/technical-indicators/{indicator}."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

IndicatorName = Literal[
    "ADX", "RSI", "EMA", "SMA", "WMA", "DEMA", "TEMA", "WilliamsR", "StdDev"
]
Timeframe = Literal["1min", "5min", "15min", "30min", "1hour", "4hour", "1day"]


class FMPTechnicalIndicatorIntradayQueryParams(QueryParams):
    """FMP Technical Indicator (Intraday) Query.

    Source: https://site.financialmodelingprep.com/developer/docs#technical-indicators
    """

    symbol: str = Field(description="Ticker symbol.")
    indicator: IndicatorName = Field(description="Indicator name (FMP taxonomy).")
    period_length: int = Field(default=14, description="Lookback period.")
    timeframe: Timeframe = Field(default="5min", description="Bar timeframe.")


class FMPTechnicalIndicatorIntradayData(Data):
    """One (symbol, indicator, bar) point."""

    symbol: str = Field(description="Ticker symbol.")
    indicator: str = Field(description="Indicator name.")
    date: datetime = Field(description="Bar-start timestamp.")
    value: float | None = Field(
        default=None, description="Indicator value (None during warmup)."
    )
    period_length: int = Field(description="Lookback period used.")
    timeframe: str = Field(description="Bar timeframe.")


class FMPTechnicalIndicatorIntradayFetcher(
    Fetcher[
        FMPTechnicalIndicatorIntradayQueryParams,
        list[FMPTechnicalIndicatorIntradayData],
    ]
):
    """FMP Technical Indicator (Intraday) Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPTechnicalIndicatorIntradayQueryParams:
        return FMPTechnicalIndicatorIntradayQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPTechnicalIndicatorIntradayQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        url = (
            "https://financialmodelingprep.com/stable/technical-indicators/"
            f"{query.indicator}?symbol={query.symbol}"
            f"&periodLength={query.period_length}"
            f"&timeframe={query.timeframe}"
            f"&apikey={api_key}"
        )
        data = await amake_request(
            url, response_callback=response_callback, **kwargs
        )
        if not data:
            raise EmptyDataError("No indicator values returned from FMP.")
        # Enrich each row with query context so downstream models are self-describing.
        for row in data:
            row.setdefault("symbol", query.symbol)
            row.setdefault("indicator", query.indicator)
            row.setdefault("period_length", query.period_length)
            row.setdefault("timeframe", query.timeframe)
            # FMP returns the indicator under a key matching its name; normalize.
            if "value" not in row and query.indicator in row:
                row["value"] = row[query.indicator]
        return list(data)

    @staticmethod
    def transform_data(
        query: FMPTechnicalIndicatorIntradayQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPTechnicalIndicatorIntradayData]:
        return [FMPTechnicalIndicatorIntradayData.model_validate(d) for d in data]
