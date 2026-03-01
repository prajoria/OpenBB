"""Cached financial_ratios model for FMP with dedicated database persistence."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.financial_ratios import (
    FMPFinancialRatiosData,
    FMPFinancialRatiosFetcher,
    FMPFinancialRatiosQueryParams,
)
from openbb_fmp_cached.utils.cache_schema import create_financial_ratios_table
from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)

FINANCIAL_RATIOS_TTL_DAYS = 1


class FMPCachedFinancialRatiosFetcher(FMPFinancialRatiosFetcher):
    """FMP Cached Financial Ratios Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPFinancialRatiosQueryParams:
        """Transform query params."""
        return FMPFinancialRatiosQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPFinancialRatiosQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract financial ratios data with database persistence."""
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_financial_ratios_table()
        except Exception as exc:
            logger.warning("Financial ratios cache init failed, using direct FMP call: %s", exc)
            return await FMPFinancialRatiosFetcher.aextract_data(
                query,
                resolved_credentials,
                **kwargs,
            )

        symbols = [symbol.strip() for symbol in query.symbol.split(",") if symbol.strip()]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        for symbol in symbols:
            cached = _get_cached_financial_ratios(symbol, query)
            if cached:
                results.extend(cached)
            else:
                symbols_to_fetch.append(symbol)

        if symbols_to_fetch:
            fetch_query = FMPFinancialRatiosQueryParams(
                symbol=",".join(symbols_to_fetch),
                ttm=query.ttm,
                period=query.period,
                limit=query.limit,
            )
            fresh_data = await FMPFinancialRatiosFetcher.aextract_data(
                fetch_query,
                resolved_credentials,
                **kwargs,
            )
            if fresh_data:
                _store_financial_ratios(fresh_data)
                results.extend(fresh_data)

        return sorted(
            results,
            key=lambda item: (
                symbols.index(item.get("symbol", ""))
                if item.get("symbol") in symbols
                else len(symbols),
                item.get("date", ""),
            ),
            reverse=True,
        )

    @staticmethod
    def transform_data(
        query: FMPFinancialRatiosQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPFinancialRatiosData]:
        """Transform raw data to standardized model."""
        return FMPFinancialRatiosFetcher.transform_data(query, data, **kwargs)


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


def _get_cached_financial_ratios(
    symbol: str,
    query_params: FMPFinancialRatiosQueryParams,
) -> list[dict[str, Any]]:
    """Read recent financial ratios data from cache."""
    freshness_cutoff = datetime.now() - timedelta(days=FINANCIAL_RATIOS_TTL_DAYS)
    query = """
    SELECT data_json
    FROM financial_ratios
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

    loaded = _filter_by_ttm(loaded, query_params.ttm)
    if query_params.ttm != "only":
        loaded = _filter_by_period(loaded, str(query_params.period))
    max_records = query_params.limit if query_params.limit else 5
    if query_params.ttm == "only":
        return loaded
    return loaded[:max_records]


def _filter_by_ttm(records: list[dict[str, Any]], ttm: str) -> list[dict[str, Any]]:
    """Filter financial ratios records by TTM selection."""
    if ttm == "only":
        return [item for item in records if str(item.get("period", "")).upper() == "TTM"]
    if ttm == "exclude":
        return [item for item in records if str(item.get("period", "")).upper() != "TTM"]
    return records


def _filter_by_period(records: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """Filter financial ratios records by requested period when not TTM."""
    if not period:
        return records
    if period.upper() == "TTM":
        return records
    return [item for item in records if str(item.get("period", "")).lower() == period.lower()]


def _store_financial_ratios(ratios: list[dict[str, Any]]) -> None:
    """Persist financial ratios records in cache."""
    cleanup_query = "DELETE FROM financial_ratios WHERE symbol = %s"
    insert_query = """
    INSERT INTO financial_ratios (
        symbol,
        date,
        period,
        currency,
        pe_ratio,
        pb_ratio,
        debt_to_equity,
        current_ratio,
        roe,
        roa,
        data_json,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """

    symbols = {(item.get("symbol") or "").strip() for item in ratios if item.get("symbol")}
    for symbol in symbols:
        execute_query(cleanup_query, (symbol,))

    params_list = [
        (
            item.get("symbol"),
            item.get("date"),
            item.get("period"),
            item.get("reportedCurrency"),
            item.get("priceToEarningsRatio") or item.get("priceToEarningsRatioTTM"),
            item.get("priceToBookRatio") or item.get("priceToBookRatioTTM"),
            item.get("debtToEquityRatio") or item.get("debtToEquityRatioTTM"),
            item.get("currentRatio") or item.get("currentRatioTTM"),
            item.get("returnOnEquity") or item.get("returnOnEquityTTM"),
            item.get("returnOnAssets") or item.get("returnOnAssetsTTM"),
            json.dumps(item),
        )
        for item in ratios
    ]

    if params_list:
        execute_many(insert_query, params_list)
