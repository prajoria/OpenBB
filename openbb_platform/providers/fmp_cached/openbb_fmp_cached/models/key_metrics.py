"""Cached key_metrics model for FMP with dedicated database persistence."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.key_metrics import (
    FMPKeyMetricsData,
    FMPKeyMetricsFetcher,
    FMPKeyMetricsQueryParams,
)
from openbb_fmp_cached.utils.cache_schema import create_key_metrics_table
from openbb_fmp_cached.utils.database import execute_query, execute_many, init_database

logger = logging.getLogger(__name__)

KEY_METRICS_TTL_DAYS = 1


class FMPCachedKeyMetricsFetcher(FMPKeyMetricsFetcher):
    """FMP Cached Key Metrics Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPKeyMetricsQueryParams:
        """Transform query params."""
        return FMPKeyMetricsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPKeyMetricsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract key metrics data with database persistence."""
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_key_metrics_table()
        except Exception as exc:
            logger.warning(
                "Key metrics cache init failed, using direct FMP call: %s", exc
            )
            return await FMPKeyMetricsFetcher.aextract_data(
                query, resolved_credentials, **kwargs
            )

        symbols = [
            symbol.strip() for symbol in query.symbol.split(",") if symbol.strip()
        ]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        for symbol in symbols:
            cached = _get_cached_key_metrics(symbol, query)
            if cached:
                results.extend(cached)
            else:
                symbols_to_fetch.append(symbol)

        if symbols_to_fetch:
            fetch_query = query.model_copy(
                update={"symbol": ",".join(symbols_to_fetch)}
            )
            fresh_data = await FMPKeyMetricsFetcher.aextract_data(
                fetch_query, resolved_credentials, **kwargs
            )
            if fresh_data:
                _store_key_metrics(fresh_data)
                results.extend(fresh_data)

        return sorted(
            results,
            key=lambda item: (
                (
                    symbols.index(item.get("symbol", ""))
                    if item.get("symbol") in symbols
                    else len(symbols)
                ),
                item.get("date", ""),
            ),
            reverse=True,
        )

    @staticmethod
    def transform_data(
        query: FMPKeyMetricsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPKeyMetricsData]:
        """Transform raw data to standardized model."""
        return FMPKeyMetricsFetcher.transform_data(query, data, **kwargs)


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


def _get_cached_key_metrics(
    symbol: str, query_params: FMPKeyMetricsQueryParams
) -> list[dict[str, Any]]:
    """Read recent key metrics data from cache."""
    freshness_cutoff = datetime.now() - timedelta(days=KEY_METRICS_TTL_DAYS)
    query = """
    SELECT data_json
    FROM key_metrics
    WHERE symbol = %s
      AND is_valid = TRUE
      AND cached_at >= %s
    ORDER BY date DESC
    """

    rows = execute_query(query, (symbol, freshness_cutoff))
    if not rows:
        return []

    loaded = []
    for row in rows:
        payload = row.get("data_json")
        if not payload:
            continue
        loaded.append(json.loads(payload) if isinstance(payload, str) else payload)

    if query_params.ttm == "only":
        loaded = [
            item
            for item in loaded
            if str(item.get("fiscal_period", "")).upper() == "TTM"
        ]
    elif query_params.ttm == "exclude":
        loaded = [
            item
            for item in loaded
            if str(item.get("fiscal_period", "")).upper() != "TTM"
        ]

    if query_params.limit and query_params.ttm != "only":
        loaded = loaded[: query_params.limit]

    return loaded


def _store_key_metrics(metrics: list[dict[str, Any]]) -> None:
    """Persist key metrics records in cache."""
    cleanup_query = "DELETE FROM key_metrics WHERE symbol = %s"
    insert_query = """
    INSERT INTO key_metrics (
        symbol,
        date,
        period,
        currency,
        market_cap,
        data_json,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """

    symbols = {
        (item.get("symbol") or "").strip() for item in metrics if item.get("symbol")
    }
    for symbol in symbols:
        execute_query(cleanup_query, (symbol,))

    params_list = [
        (
            item.get("symbol"),
            item.get("date"),
            item.get("fiscal_period") or item.get("period"),
            item.get("reportedCurrency"),
            item.get("marketCap"),
            json.dumps(item),
        )
        for item in metrics
    ]

    if params_list:
        execute_many(insert_query, params_list)
