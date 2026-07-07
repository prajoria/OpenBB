"""Cached income_statement model for FMP with dedicated database persistence."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.income_statement import (
    FMPIncomeStatementData,
    FMPIncomeStatementFetcher,
    FMPIncomeStatementQueryParams,
)
from openbb_fmp_cached.utils.cache_schema import create_income_statement_table
from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)

INCOME_STATEMENT_TTL_DAYS = 1


class FMPCachedIncomeStatementFetcher(FMPIncomeStatementFetcher):
    """FMP Cached Income Statement Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPIncomeStatementQueryParams:
        """Transform query params."""
        return FMPIncomeStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPIncomeStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract income statement data with database persistence."""
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_income_statement_table()
        except Exception as exc:
            logger.warning(
                "Income statement cache init failed, using direct FMP call: %s", exc
            )
            return await FMPIncomeStatementFetcher.aextract_data(
                query,
                resolved_credentials,
                **kwargs,
            )

        symbols = [
            symbol.strip() for symbol in query.symbol.split(",") if symbol.strip()
        ]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        for symbol in symbols:
            cached = _get_cached_income_statement(symbol, query)
            if cached:
                results.extend(cached)
            else:
                symbols_to_fetch.append(symbol)

        if symbols_to_fetch:
            fetch_query = query.model_copy(
                update={"symbol": ",".join(symbols_to_fetch)}
            )
            fresh_data = await FMPIncomeStatementFetcher.aextract_data(
                fetch_query,
                resolved_credentials,
                **kwargs,
            )
            if fresh_data:
                _store_income_statement(fresh_data)
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
        query: FMPIncomeStatementQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPIncomeStatementData]:
        """Transform raw data to standardized model."""
        return FMPIncomeStatementFetcher.transform_data(query, data, **kwargs)


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


def _get_cached_income_statement(
    symbol: str,
    query_params: FMPIncomeStatementQueryParams,
) -> list[dict[str, Any]]:
    """Read recent income statement data from cache."""
    freshness_cutoff = datetime.now() - timedelta(days=INCOME_STATEMENT_TTL_DAYS)
    query = """
    SELECT data_json
    FROM income_statement
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

    loaded = _filter_by_period(loaded, str(query_params.period))
    max_records = query_params.limit if query_params.limit else 5
    return loaded[:max_records]


def _filter_by_period(
    records: list[dict[str, Any]], period: str
) -> list[dict[str, Any]]:
    """Filter income statement records by requested period."""
    if not period:
        return records

    normalized = period.upper()
    if normalized == "TTM":
        return [
            item for item in records if str(item.get("period", "")).upper() == "TTM"
        ]

    return [
        item
        for item in records
        if str(item.get("period", "")).lower() == period.lower()
    ]


def _store_income_statement(statements: list[dict[str, Any]]) -> None:
    """Persist income statement records in cache."""
    cleanup_query = "DELETE FROM income_statement WHERE symbol = %s"
    insert_query = """
    INSERT INTO income_statement (
        symbol,
        date,
        period,
        currency,
        revenue,
        net_income,
        data_json,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """

    symbols = {
        (item.get("symbol") or "").strip() for item in statements if item.get("symbol")
    }
    for symbol in symbols:
        execute_query(cleanup_query, (symbol,))

    params_list = [
        (
            item.get("symbol"),
            item.get("date"),
            item.get("period"),
            item.get("reportedCurrency"),
            item.get("revenue"),
            item.get("netIncome"),
            json.dumps(item),
        )
        for item in statements
    ]

    if params_list:
        execute_many(insert_query, params_list)
