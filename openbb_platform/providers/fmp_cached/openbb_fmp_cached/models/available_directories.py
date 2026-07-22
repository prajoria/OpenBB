"""Cached FMP directory listings — available exchanges/sectors/industries/countries.

Wave 4 Directory drain (#1052 #1053 #1054 #1055).

FMP's ``/stable/available-*`` endpoints return small, slow-moving
directory data (11 sectors, ~160 industries, ~65 exchanges, ~115
countries). All are Free-tier + trivially cacheable — perfect first
demo of the fmp_cached endpoint playbook.

Design choices:
- **One module, four fetchers**: they share so much shape that
  splitting into 4 files would just duplicate the same 20-line pattern.
- **Native fetchers, no ``openbb_fmp`` wrap**: nothing in ``openbb_fmp``
  or ``openbb_core.provider.standard_models`` covers these directories.
  Same pattern used by ``AnalystRecommendations`` (#1022).
- **Persistent mirror, not TTL cache**: directory data updates
  monthly at most. We store the full list on first fetch; re-fetch
  overwrites via ``TRUNCATE + INSERT`` (idempotent, cheap on <200
  rows).
- **Loud empty**: an empty list from FMP is treated as an error
  (raises), not silently written to cache. These directories are
  never actually empty.
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught
# pylint: disable=unused-argument  # Fetcher ABC signature

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field

logger = logging.getLogger(__name__)

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# ---------------------------------------------------------------------------
# Shared query + fetch primitives
# ---------------------------------------------------------------------------


class _EmptyQueryParams(QueryParams):
    """Directory endpoints take no parameters."""


async def _fetch_directory(path: str, api_key: str) -> list[dict]:
    """Hit ``/stable/{path}`` and return the raw list.

    Redacts ``apikey`` from any HTTPError via
    ``raise_for_status_redacted`` (bd-6641 / bd-q4b4 / bd-ygtq).
    """
    import httpx

    from openbb_fmp_cached.utils.security import raise_for_status_redacted

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{_FMP_STABLE_BASE}/{path}", params={"apikey": api_key}
        )
    raise_for_status_redacted(resp)
    payload = resp.json()
    if not isinstance(payload, list):
        raise RuntimeError(
            f"available-{path}: unexpected response shape from FMP: "
            f"{type(payload).__name__}"
        )
    return payload


def _resolve_api_key(credentials: dict[str, str] | None) -> str:
    """fmp_cached_api_key -> fmp_api_key shim; falls back to user_settings."""
    if credentials:
        if credentials.get("fmp_api_key"):
            return credentials["fmp_api_key"]
        if credentials.get("fmp_cached_api_key"):
            return credentials["fmp_cached_api_key"]
    try:
        from openbb_core.app.service.user_service import UserService

        user_settings = UserService().default_user_settings
        api_key = getattr(user_settings.credentials, "fmp_api_key", None) or getattr(
            user_settings.credentials, "fmp_cached_api_key", None
        )
        if api_key:
            return (
                api_key.get_secret_value()
                if hasattr(api_key, "get_secret_value")
                else str(api_key)
            )
    except Exception as exc:
        logger.warning("directory: credential resolution failed: %s", exc)
    raise RuntimeError(
        "AvailableDirectory: fmp_api_key not configured; "
        "set fmp_api_key or fmp_cached_api_key in user_settings.json"
    )


def _persist_directory(table: str, key_col: str, rows: list[dict]) -> None:
    """TRUNCATE + INSERT the directory into ``table``. Fails soft on DB error.

    ``table`` must be in :data:`_ALLOWED_TABLES` — it is f-string
    interpolated into DDL. The correct schema-creator is dispatched by
    table name so both the available-* (#1052-#1055) and symbol-list
    (#1045-#1050) fetchers can share this helper.
    """
    if not rows:
        return
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"_persist_directory: table {table!r} not in allowlist "
            f"(expected one of {sorted(_ALLOWED_TABLES)})"
        )
    try:
        from openbb_fmp_cached.utils.cache_schema import (
            create_available_directory_tables,
            create_symbol_list_tables,
        )
        from openbb_fmp_cached.utils.database import execute_many, execute_query

        if table.startswith("available_"):
            create_available_directory_tables()
        else:
            create_symbol_list_tables()
        # Idempotent overwrite: TRUNCATE (fast on small tables) then INSERT.
        execute_query(
            f"TRUNCATE TABLE {table}"
        )  # noqa: S608  (table name from allowlist above)
        insert_sql = f"INSERT INTO {table} (data_json) VALUES (%s)"  # noqa: S608
        import json as _json

        execute_many(insert_sql, [(_json.dumps(r),) for r in rows])
    except Exception as exc:
        logger.warning("%s persist failed: %s", table, exc)


_ALLOWED_TABLES = {
    "available_exchanges",
    "available_sectors",
    "available_industries",
    "available_countries",
    # W4 symbol-list batch (#1045-#1050)
    "stock_list",
    "etf_list",
    "actively_trading_list",
    "financial_statement_symbol_list",
    "cik_list",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FMPCachedAvailableExchangeData(Data):
    """One row from ``/stable/available-exchanges``."""

    exchange: str = Field(description="Exchange code (e.g. AMEX, NYSE).")
    name: str | None = Field(default=None, description="Human-readable exchange name.")
    country_name: str | None = Field(default=None, description="Country name.")
    country_code: str | None = Field(default=None, description="Country ISO-2 code.")
    symbol_suffix: str | None = Field(
        default=None, description="Ticker suffix (or 'N/A')."
    )
    delay: str | None = Field(default=None, description="Real-time / delayed marker.")


class FMPCachedAvailableSectorData(Data):
    """One row from ``/stable/available-sectors``."""

    sector: str = Field(description="Sector name (e.g. 'Basic Materials').")


class FMPCachedAvailableIndustryData(Data):
    """One row from ``/stable/available-industries``."""

    industry: str = Field(description="Industry name (e.g. 'Steel').")


class FMPCachedAvailableCountryData(Data):
    """One row from ``/stable/available-countries``."""

    country: str = Field(description="Country ISO code (e.g. 'US', 'FK').")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


class _AvailableDirectoryFetcherBase:
    """Shared logic for the 4 directory fetchers. Not a public ABC."""

    _path: str = ""  # subclass overrides
    _table: str = ""  # subclass overrides
    _data_cls: type[Data] = Data  # subclass overrides
    _alias_map: dict[str, str] = {}  # raw -> model field renaming

    @classmethod
    async def _shared_extract(cls, credentials: dict[str, str] | None) -> list[dict]:
        api_key = _resolve_api_key(credentials)
        rows = await _fetch_directory(cls._path, api_key)
        if not rows:
            raise RuntimeError(
                f"available-{cls._path}: FMP returned empty list — likely tier or API issue"
            )
        _persist_directory(cls._table, "data_json", rows)
        return rows

    @classmethod
    def _shared_transform(
        cls, query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[Data]:
        out = []
        for row in data:
            mapped = {cls._alias_map.get(k, k): v for k, v in row.items()}
            out.append(cls._data_cls.model_validate(mapped))
        return out


class FMPCachedAvailableExchangesFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedAvailableExchangeData]],
    _AvailableDirectoryFetcherBase,
):
    """Cached fetcher for ``/stable/available-exchanges`` (#1052)."""

    _path = "available-exchanges"
    _table = "available_exchanges"
    _data_cls = FMPCachedAvailableExchangeData
    _alias_map = {
        "countryName": "country_name",
        "countryCode": "country_code",
        "symbolSuffix": "symbol_suffix",
    }

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce a raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the exchange directory."""
        return await FMPCachedAvailableExchangesFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAvailableExchangeData]:
        """Map raw JSON rows to typed exchange data."""
        return FMPCachedAvailableExchangesFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedAvailableSectorsFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedAvailableSectorData]],
    _AvailableDirectoryFetcherBase,
):
    """Cached fetcher for ``/stable/available-sectors`` (#1053)."""

    _path = "available-sectors"
    _table = "available_sectors"
    _data_cls = FMPCachedAvailableSectorData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce a raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the sector directory."""
        return await FMPCachedAvailableSectorsFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAvailableSectorData]:
        """Map raw JSON rows to typed sector data."""
        return FMPCachedAvailableSectorsFetcher._shared_transform(query, data, **kwargs)


class FMPCachedAvailableIndustriesFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedAvailableIndustryData]],
    _AvailableDirectoryFetcherBase,
):
    """Cached fetcher for ``/stable/available-industries`` (#1054)."""

    _path = "available-industries"
    _table = "available_industries"
    _data_cls = FMPCachedAvailableIndustryData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce a raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the industry directory."""
        return await FMPCachedAvailableIndustriesFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAvailableIndustryData]:
        """Map raw JSON rows to typed industry data."""
        return FMPCachedAvailableIndustriesFetcher._shared_transform(
            query, data, **kwargs
        )


class FMPCachedAvailableCountriesFetcher(
    Fetcher[_EmptyQueryParams, list[FMPCachedAvailableCountryData]],
    _AvailableDirectoryFetcherBase,
):
    """Cached fetcher for ``/stable/available-countries`` (#1055)."""

    _path = "available-countries"
    _table = "available_countries"
    _data_cls = FMPCachedAvailableCountryData

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EmptyQueryParams:
        """Coerce a raw params dict into the (empty) typed query object."""
        return _EmptyQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EmptyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch + persist the country directory."""
        return await FMPCachedAvailableCountriesFetcher._shared_extract(credentials)

    @staticmethod
    def transform_data(
        query: _EmptyQueryParams, data: list, **kwargs: Any
    ) -> list[FMPCachedAvailableCountryData]:
        """Map raw JSON rows to typed country data."""
        return FMPCachedAvailableCountriesFetcher._shared_transform(
            query, data, **kwargs
        )
