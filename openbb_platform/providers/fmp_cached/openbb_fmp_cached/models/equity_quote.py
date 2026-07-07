"""Cached equity_quote model for FMP with dedicated database persistence."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.equity_quote import (
    FMPEquityQuoteData,
    FMPEquityQuoteFetcher,
    FMPEquityQuoteQueryParams,
)
from openbb_fmp_cached.utils.cache_schema import create_equity_quote_table
from openbb_fmp_cached.utils.database import execute_query, execute_many, init_database

logger = logging.getLogger(__name__)

QUOTE_TTL_SECONDS = 300


class FMPCachedEquityQuoteFetcher(FMPEquityQuoteFetcher):
    """FMP Cached Equity Quote Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEquityQuoteQueryParams:
        """Transform query params."""
        return FMPEquityQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract equity quote data with database persistence."""
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_equity_quote_table()
        except Exception as exc:
            logger.warning("Quote cache init failed, using direct FMP call: %s", exc)
            return await FMPEquityQuoteFetcher.aextract_data(
                query, resolved_credentials, **kwargs
            )

        symbols = [
            symbol.strip() for symbol in query.symbol.split(",") if symbol.strip()
        ]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        for symbol in symbols:
            cached = _get_cached_quote(symbol)
            if cached:
                results.append(cached)
            else:
                symbols_to_fetch.append(symbol)

        if symbols_to_fetch:
            fetch_query = query.model_copy(
                update={"symbol": ",".join(symbols_to_fetch)}
            )
            fresh_data = await FMPEquityQuoteFetcher.aextract_data(
                fetch_query, resolved_credentials, **kwargs
            )
            if fresh_data:
                _store_quotes(fresh_data)
                results.extend(fresh_data)

        return sorted(results, key=lambda item: symbols.index(item.get("symbol", "")))

    @staticmethod
    def transform_data(
        query: FMPEquityQuoteQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEquityQuoteData]:
        """Transform raw data to standardized model."""
        return FMPEquityQuoteFetcher.transform_data(query, data, **kwargs)


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


def _get_cached_quote(symbol: str) -> dict[str, Any] | None:
    """Read recent quote data from cache."""
    freshness_cutoff = datetime.now() - timedelta(seconds=QUOTE_TTL_SECONDS)
    query = """
    SELECT data_json
    FROM equity_quote
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


def _store_quotes(quotes: list[dict[str, Any]]) -> None:
    """Persist quote records in cache."""
    cleanup_query = "DELETE FROM equity_quote WHERE symbol = %s"
    insert_query = """
    INSERT INTO equity_quote (
        symbol,
        exchange,
        price,
        open,
        high,
        low,
        volume,
        market_cap,
        currency,
        change_amount,
        change_percent,
        data_json,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """

    symbols = {
        (item.get("symbol") or "").strip() for item in quotes if item.get("symbol")
    }
    for symbol in symbols:
        execute_query(cleanup_query, (symbol,))

    params_list = [
        (
            item.get("symbol"),
            item.get("exchange"),
            item.get("price"),
            item.get("open"),
            item.get("dayHigh"),
            item.get("dayLow"),
            item.get("volume"),
            item.get("marketCap"),
            item.get("currency"),
            item.get("change"),
            item.get("changePercentage"),
            json.dumps(item),
        )
        for item in quotes
    ]

    if params_list:
        execute_many(insert_query, params_list)
