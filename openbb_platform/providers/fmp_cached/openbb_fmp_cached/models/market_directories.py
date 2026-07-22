"""Cached FMP market-directory listings — commodities/crypto/forex/indexes lists.

Wave 4 Directory drain, batch 3 (#1158 #1173 #1182 #1197).

FMP's ``/stable/commodities-list``, ``cryptocurrency-list``,
``forex-list``, ``index-list`` are all no-param single-shot GETs
returning small (40-4785 row) reference directories. Same
architectural pattern as ``symbol_lists.py`` (batch 2, PR #1322):

- One module, four fetchers sharing ``_SymbolListFetcherBase``.
- Native fetchers, no ``openbb_fmp`` wrap.
- Persistent MySQL mirror; TRUNCATE + INSERT on refresh.
- Loud empty (raises, doesn't silently cache).
- ``raise_for_status_redacted`` for apikey scrubbing.

Response shape notes:
- ``commodities-list``: {symbol, name, exchange, tradeMonth, currency}
- ``cryptocurrency-list``: {symbol, name, exchange, icoDate, circulatingSupply, totalSupply}
- ``forex-list``: {symbol, fromCurrency, toCurrency, fromName, toName}
- ``index-list``: {symbol, name, exchange, currency}
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught,unused-argument

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from pydantic import Field

from openbb_fmp_cached.models.symbol_lists import (
    _EmptyQueryParams,
    _SymbolListFetcherBase,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedCommoditiesListData(Data):
    """One row from ``/stable/commodities-list``."""

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Commodity name.")
    exchange: str | None = Field(default=None, description="Exchange (may be null).")
    trade_month: str | None = Field(
        default=None, description="Contract trade month (e.g. 'Dec')."
    )
    currency: str | None = Field(default=None, description="Currency.")


class FMPCachedCryptocurrencyListData(Data):
    """One row from ``/stable/cryptocurrency-list``."""

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Crypto name.")
    exchange: str | None = Field(default=None, description="Exchange (typically CCC).")
    ico_date: str | None = Field(default=None, description="ICO date YYYY-MM-DD.")
    circulating_supply: float | None = Field(
        default=None, description="Circulating supply."
    )
    total_supply: float | None = Field(default=None, description="Total supply.")


class FMPCachedForexListData(Data):
    """One row from ``/stable/forex-list``."""

    symbol: str = Field(description="Forex pair symbol (e.g. 'EURUSD').")
    from_currency: str | None = Field(default=None, description="Base currency code.")
    to_currency: str | None = Field(default=None, description="Quote currency code.")
    from_name: str | None = Field(default=None, description="Base currency name.")
    to_name: str | None = Field(default=None, description="Quote currency name.")


class FMPCachedIndexListData(Data):
    """One row from ``/stable/index-list``."""

    symbol: str = Field(description="Index symbol (e.g. '^GSPC').")
    name: str | None = Field(default=None, description="Index name.")
    exchange: str | None = Field(default=None, description="Exchange.")
    currency: str | None = Field(default=None, description="Currency.")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


class FMPCachedCommoditiesListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedCommoditiesListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/commodities-list`` (#1173)."""

    _path = "commodities-list"
    _table = "commodities_list"
    _data_cls = FMPCachedCommoditiesListData
    _alias_map = {"tradeMonth": "trade_month"}

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full commodities list."""
        return await FMPCachedCommoditiesListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCommoditiesListData]:
        """Map raw JSON rows to typed commodities data."""
        return FMPCachedCommoditiesListFetcher._shared_transform(query, data, **kwargs)


class FMPCachedCryptocurrencyListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedCryptocurrencyListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/cryptocurrency-list`` (#1182)."""

    _path = "cryptocurrency-list"
    _table = "cryptocurrency_list"
    _data_cls = FMPCachedCryptocurrencyListData
    _alias_map = {
        "icoDate": "ico_date",
        "circulatingSupply": "circulating_supply",
        "totalSupply": "total_supply",
    }

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full cryptocurrency list."""
        return await FMPCachedCryptocurrencyListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedCryptocurrencyListData]:
        """Map raw JSON rows to typed cryptocurrency data."""
        return FMPCachedCryptocurrencyListFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedForexListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedForexListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/forex-list`` (#1197)."""

    _path = "forex-list"
    _table = "forex_list"
    _data_cls = FMPCachedForexListData
    _alias_map = {
        "fromCurrency": "from_currency",
        "toCurrency": "to_currency",
        "fromName": "from_name",
        "toName": "to_name",
    }

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full forex-pair list."""
        return await FMPCachedForexListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedForexListData]:
        """Map raw JSON rows to typed forex data."""
        return FMPCachedForexListFetcher._shared_transform(query, data, **kwargs)


class FMPCachedIndexListFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedIndexListData]],
    _SymbolListFetcherBase,
):
    """Cached fetcher for ``/stable/index-list`` (#1158)."""

    _path = "index-list"
    _table = "index_list"
    _data_cls = FMPCachedIndexListData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the full index list."""
        return await FMPCachedIndexListFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedIndexListData]:
        """Map raw JSON rows to typed index data."""
        return FMPCachedIndexListFetcher._shared_transform(query, data, **kwargs)
