"""Cached equity_profile model for FMP with dedicated database persistence."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.equity_profile import (
    FMPEquityProfileData,
    FMPEquityProfileFetcher,
    FMPEquityProfileQueryParams,
)
from openbb_fmp_cached.utils.cache_schema import create_equity_profile_table
from openbb_fmp_cached.utils.database import execute_query, init_database

logger = logging.getLogger(__name__)

PROFILE_TTL_DAYS = 7


class FMPCachedEquityProfileFetcher(FMPEquityProfileFetcher):
    """FMP Cached Equity Profile Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEquityProfileQueryParams:
        """Transform query params."""
        return FMPEquityProfileQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityProfileQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract equity profile data with database persistence."""
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_equity_profile_table()
        except Exception as exc:
            logger.warning("Profile cache init failed, using direct FMP call: %s", exc)
            return await FMPEquityProfileFetcher.aextract_data(
                query, resolved_credentials, **kwargs
            )

        symbols = [
            symbol.strip() for symbol in query.symbol.split(",") if symbol.strip()
        ]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        for symbol in symbols:
            cached = _get_cached_profile(symbol)
            if cached:
                results.append(cached)
            else:
                symbols_to_fetch.append(symbol)

        if symbols_to_fetch:
            fetch_query = FMPEquityProfileQueryParams(symbol=",".join(symbols_to_fetch))
            fresh_data = await FMPEquityProfileFetcher.aextract_data(
                fetch_query, resolved_credentials, **kwargs
            )
            if fresh_data:
                _store_profiles(fresh_data)
                results.extend(fresh_data)

        return sorted(results, key=lambda item: symbols.index(item.get("symbol", "")))

    @staticmethod
    def transform_data(
        query: FMPEquityProfileQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEquityProfileData]:
        """Transform raw data to standardized model."""
        return FMPEquityProfileFetcher.transform_data(query, data, **kwargs)


def _resolve_credentials(credentials: dict[str, str] | None) -> dict[str, str] | None:
    """Resolve credentials and translate fmp_cached key if needed."""
    if credentials and credentials.get("fmp_api_key"):
        return credentials

    if credentials and credentials.get("fmp_cached_api_key"):
        return {"fmp_api_key": credentials["fmp_cached_api_key"]}

    try:
        from openbb_core.app.service.user_service import UserService

        user_settings = UserService().default_user_settings
        api_key = getattr(user_settings.credentials, "fmp_api_key", None)
        if api_key:
            api_key_value = (
                api_key.get_secret_value()
                if hasattr(api_key, "get_secret_value")
                else str(api_key)
            )
            return {"fmp_api_key": api_key_value}
    except Exception as exc:
        logger.warning("Unable to resolve FMP credentials from user settings: %s", exc)

    return credentials


def _get_cached_profile(symbol: str) -> dict[str, Any] | None:
    """Read recent profile data from cache."""
    freshness_cutoff = datetime.now() - timedelta(days=PROFILE_TTL_DAYS)
    query = """
    SELECT data_json
    FROM equity_profile
    WHERE symbol = %s
      AND is_valid = TRUE
      AND cached_at >= %s
    ORDER BY cached_at DESC
    LIMIT 1
    """

    rows = execute_query(query, (symbol, freshness_cutoff))
    if not rows:
        return None

    payload = rows[0].get("data_json")
    if not payload:
        return None

    return json.loads(payload) if isinstance(payload, str) else payload


def _store_profiles(profiles: list[dict[str, Any]]) -> None:
    """Persist profile records in cache with upsert semantics."""
    insert_query = """
    INSERT INTO equity_profile (
        symbol,
        company_name,
        exchange,
        industry,
        sector,
        market_cap,
        price,
        currency,
        country,
        website,
        data_json,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
        company_name = VALUES(company_name),
        exchange = VALUES(exchange),
        industry = VALUES(industry),
        sector = VALUES(sector),
        market_cap = VALUES(market_cap),
        price = VALUES(price),
        currency = VALUES(currency),
        country = VALUES(country),
        website = VALUES(website),
        data_json = VALUES(data_json),
        is_valid = TRUE,
        cached_at = CURRENT_TIMESTAMP
    """

    for item in profiles:
        execute_query(
            insert_query,
            (
                item.get("symbol"),
                item.get("companyName"),
                item.get("exchange"),
                item.get("industry"),
                item.get("sector"),
                item.get("marketCap"),
                item.get("price"),
                item.get("currency"),
                item.get("country"),
                item.get("website"),
                json.dumps(item),
            ),
        )
