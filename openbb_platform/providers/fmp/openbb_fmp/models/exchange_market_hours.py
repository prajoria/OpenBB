"""FMP Exchange Market Hours Model — /stable/all-exchange-market-hours."""

# pylint: disable=unused-argument

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class FMPExchangeMarketHoursQueryParams(QueryParams):
    """FMP All Exchange Market Hours Query (no parameters).

    Source: https://site.financialmodelingprep.com/developer/docs#all-exchange-market-hours
    """


class FMPExchangeMarketHoursData(Data):
    """One row per exchange × session-status snapshot."""

    exchange: str = Field(description="Exchange code (e.g. NASDAQ, NYSE).")
    name: str | None = Field(default=None, description="Exchange full name.")
    opening_hour: str | None = Field(default=None, description="Regular open (local).")
    closing_hour: str | None = Field(default=None, description="Regular close (local).")
    timezone: str | None = Field(default=None, description="Exchange timezone.")
    is_market_open: bool | None = Field(
        default=None, description="True if currently in regular-hours session."
    )


class FMPExchangeMarketHoursFetcher(
    Fetcher[
        FMPExchangeMarketHoursQueryParams,
        list[FMPExchangeMarketHoursData],
    ]
):
    """FMP All Exchange Market Hours Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPExchangeMarketHoursQueryParams:
        return FMPExchangeMarketHoursQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPExchangeMarketHoursQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        url = (
            "https://financialmodelingprep.com/stable/"
            f"all-exchange-market-hours?apikey={api_key}"
        )
        data = await amake_request(
            url, response_callback=response_callback, **kwargs
        )
        if not data:
            raise EmptyDataError("No exchange hours returned from FMP.")
        return list(data)

    @staticmethod
    def transform_data(
        query: FMPExchangeMarketHoursQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPExchangeMarketHoursData]:
        return [FMPExchangeMarketHoursData.model_validate(d) for d in data]
