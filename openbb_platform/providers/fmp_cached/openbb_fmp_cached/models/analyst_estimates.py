"""Cached analyst_estimates model for FMP with database persistence.

This module provides intelligent caching for FMP analyst estimates data with the following features:

1. **Database Persistence**: Stores analyst estimates in MySQL for fast retrieval
2. **Multi-Symbol Support**: Handles comma-separated symbols efficiently
3. **Period Awareness**: Caches quarterly and annual estimates separately
4. **Smart Caching**: Only fetches missing data from FMP API
5. **Complete Independence**: Zero dependencies on openbb_fmp module

Usage:
    The fetcher automatically handles caching. First requests populate the cache,
    subsequent requests use cached data and only fetch missing estimates.

Database Schema:
    analyst_estimates table with all FMP API response fields
"""

# Pre-existing pylint suppressions surfaced by CI (#909) — these patterns
# are used throughout fmp_cached and are out of scope for this hygiene PR.
# pylint: disable=import-outside-toplevel  # lazy imports for optional deps
# pylint: disable=logging-fstring-interpolation  # f-strings in log calls
# pylint: disable=unused-argument  # signature-required unused params
# pylint: disable=broad-exception-caught  # per-source failure isolation
# pylint: disable=redefined-outer-name,reimported  # per-function re-import guards
# pylint: disable=too-many-lines,too-many-locals,too-many-branches  # legacy
# pylint: disable=too-many-statements,too-many-return-statements
# pylint: disable=too-many-nested-blocks,too-many-arguments,too-many-positional-arguments

import logging
from datetime import datetime, date
from typing import Any, Dict, List, Literal, Optional
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.data import ForceInt
from openbb_core.provider.standard_models.analyst_estimates import (
    AnalystEstimatesData,
    AnalystEstimatesQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field
from openbb_fmp_cached.utils.database import execute_query, execute_many, init_database

logger = logging.getLogger(__name__)


class FMPCachedAnalystEstimatesQueryParams(AnalystEstimatesQueryParams):
    """FMP Cached Analyst Estimates Query Parameters.

    Independent query parameters for the cached provider.
    """

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}

    period: Literal["quarter", "annual"] = Field(
        default="annual", description=QUERY_DESCRIPTIONS.get("period", "")
    )
    limit: int | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("limit", "")
    )
    page: int | None = Field(
        default=None, description="Page number for paginated results. Used with limit."
    )


class FMPCachedAnalystEstimatesData(AnalystEstimatesData):
    """FMP Cached Analyst Estimates Data.

    Independent data model for the cached provider.
    """

    __alias_dict__ = {
        "estimated_revenue_low": "revenueLow",
        "estimated_revenue_high": "revenueHigh",
        "estimated_revenue_avg": "revenueAvg",
        "estimated_sga_expense_low": "sgaExpenseLow",
        "estimated_sga_expense_high": "sgaExpenseHigh",
        "estimated_sga_expense_avg": "sgaExpenseAvg",
        "estimated_ebitda_low": "ebitdaLow",
        "estimated_ebitda_high": "ebitdaHigh",
        "estimated_ebitda_avg": "ebitdaAvg",
        "estimated_ebit_low": "ebitLow",
        "estimated_ebit_high": "ebitHigh",
        "estimated_ebit_avg": "ebitAvg",
        "estimated_net_income_low": "netIncomeLow",
        "estimated_net_income_high": "netIncomeHigh",
        "estimated_net_income_avg": "netIncomeAvg",
        "estimated_eps_low": "epsLow",
        "estimated_eps_high": "epsHigh",
        "estimated_eps_avg": "epsAvg",
        "number_analysts_estimated_revenue": "numAnalystsRevenue",
        "number_analysts_estimated_eps": "numAnalystsEps",
    }


class FMPCachedAnalystEstimatesFetcher(
    Fetcher[
        FMPCachedAnalystEstimatesQueryParams,
        List[FMPCachedAnalystEstimatesData],
    ]
):
    """FMP Cached Analyst Estimates Fetcher with dedicated database caching."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCachedAnalystEstimatesQueryParams:
        """Transform the query params."""
        return FMPCachedAnalystEstimatesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCachedAnalystEstimatesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract analyst estimates data with intelligent caching."""

        # Get credentials from user settings if not provided
        if credentials is None or not credentials.get("fmp_api_key"):
            try:
                from openbb_core.app.service.user_service import UserService

                user_service = UserService()
                user_settings = user_service.default_user_settings
                fmp_api_key = getattr(user_settings.credentials, "fmp_api_key", None)

                if fmp_api_key:
                    api_key_value = (
                        fmp_api_key.get_secret_value()
                        if hasattr(fmp_api_key, "get_secret_value")
                        else str(fmp_api_key)
                    )
                    credentials = {"fmp_api_key": api_key_value}
                    logger.info("Using FMP API key from user settings")
                else:
                    logger.warning("No FMP API key found in user settings")
            except Exception as e:
                logger.warning(f"Could not load user settings: {e}")

        # Initialize database
        try:
            init_database()
            _create_analyst_estimates_table()
        except Exception as e:
            logger.warning(
                f"Database initialization failed, falling back to direct FMP: {e}"
            )
            return await _fetch_from_fmp_direct(query, credentials, **kwargs)

        # Fix credential mapping
        if credentials and "fmp_cached_api_key" in credentials:
            fmp_credentials = {"fmp_api_key": credentials["fmp_cached_api_key"]}
        else:
            fmp_credentials = credentials  # type: ignore[assignment]

        # Handle multiple symbols
        symbols = query.symbol.split(",") if "," in query.symbol else [query.symbol]
        all_results = []

        for symbol in symbols:
            # Create individual query for each symbol
            single_query = FMPCachedAnalystEstimatesQueryParams(
                symbol=symbol.strip(),
                period=query.period,
                limit=query.limit,
                page=query.page,
            )

            # Check cache first
            try:
                cached_data = _get_from_cache(single_query)

                if cached_data:
                    logger.info(
                        f"Cache HIT: Found {len(cached_data)} records for {symbol}"
                    )
                    all_results.extend(cached_data)
                    continue

                # Cache miss - fetch from FMP
                logger.info(f"Cache MISS: Fetching data for {symbol}")
                fmp_data = await _fetch_from_fmp_direct(
                    single_query, fmp_credentials, **kwargs
                )

                # Store in cache
                if fmp_data:
                    _store_in_cache(single_query, fmp_data)
                    logger.info(f"Cached {len(fmp_data)} records for {symbol}")
                    all_results.extend(fmp_data)

            except Exception as e:
                logger.warning(f"Cache operation failed for {symbol}: {e}")
                # Fallback to direct API call
                fallback_data = await _fetch_from_fmp_direct(
                    single_query, fmp_credentials, **kwargs
                )
                if fallback_data:
                    _store_in_cache(single_query, fallback_data)
                all_results.extend(fallback_data)

        logger.info(f"Returning {len(all_results)} total records")

        # Ensure we return dictionaries
        clean_results = []
        for item in all_results:
            if isinstance(item, dict):
                clean_results.append(item)
            elif hasattr(item, "model_dump"):
                clean_results.append(item.model_dump())
            elif hasattr(item, "__dict__"):
                clean_results.append(item.__dict__)

        return sorted(
            clean_results,
            key=lambda x: (x.get("date", ""), x.get("symbol", "")),
            reverse=False,
        )

    @staticmethod
    def transform_data(
        query: FMPCachedAnalystEstimatesQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCachedAnalystEstimatesData]:
        """Return the transformed data."""
        if not data:
            raise EmptyDataError("No data returned for the given symbols.")
        return [FMPCachedAnalystEstimatesData.model_validate(d) for d in data]


def _create_analyst_estimates_table() -> None:
    """Create analyst_estimates table if it doesn't exist."""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS analyst_estimates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10) NOT NULL,
        estimated_revenue_low BIGINT,
        estimated_revenue_high BIGINT,
        estimated_revenue_avg BIGINT,
        estimated_sga_expense_low BIGINT,
        estimated_sga_expense_high BIGINT,
        estimated_sga_expense_avg BIGINT,
        estimated_ebitda_low BIGINT,
        estimated_ebitda_high BIGINT,
        estimated_ebitda_avg BIGINT,
        estimated_ebit_low BIGINT,
        estimated_ebit_high BIGINT,
        estimated_ebit_avg BIGINT,
        estimated_net_income_low BIGINT,
        estimated_net_income_high BIGINT,
        estimated_net_income_avg BIGINT,
        estimated_eps_avg DECIMAL(20, 6),
        estimated_eps_high DECIMAL(20, 6),
        estimated_eps_low DECIMAL(20, 6),
        number_analysts_estimated_revenue INT,
        number_analysts_estimated_eps INT,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        UNIQUE KEY unique_estimate (symbol, date, period),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_symbol_period (symbol, period)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    try:
        execute_query(create_table_query)
        logger.info("Analyst estimates table ready")
    except Exception as e:
        logger.error(f"Failed to create analyst_estimates table: {e}")
        raise


def _get_from_cache(
    query: FMPCachedAnalystEstimatesQueryParams,
) -> List[Dict[str, Any]]:
    """Get analyst estimates from cache."""

    cache_query = """
    SELECT symbol, date, period,
           estimated_revenue_low, estimated_revenue_high, estimated_revenue_avg,
           estimated_sga_expense_low, estimated_sga_expense_high, estimated_sga_expense_avg,
           estimated_ebitda_low, estimated_ebitda_high, estimated_ebitda_avg,
           estimated_ebit_low, estimated_ebit_high, estimated_ebit_avg,
           estimated_net_income_low, estimated_net_income_high, estimated_net_income_avg,
           estimated_eps_avg, estimated_eps_high, estimated_eps_low,
           number_analysts_estimated_revenue, number_analysts_estimated_eps
    FROM analyst_estimates 
    WHERE symbol = %s 
    AND period = %s
    AND is_valid = TRUE
    ORDER BY date DESC
    """

    if query.limit:
        cache_query += f" LIMIT {query.limit}"
    if query.page and query.limit:
        offset = query.page * query.limit
        cache_query += f" OFFSET {offset}"

    try:
        results = execute_query(cache_query, (query.symbol, query.period))

        cached_data = []
        for row in results:
            data_dict = {
                "symbol": row["symbol"],
                "date": (
                    row["date"].strftime("%Y-%m-%d")
                    if isinstance(row["date"], date)
                    else row["date"]
                ),
                "revenueLow": (
                    int(row["estimated_revenue_low"])
                    if row["estimated_revenue_low"] is not None
                    else None
                ),
                "revenueHigh": (
                    int(row["estimated_revenue_high"])
                    if row["estimated_revenue_high"] is not None
                    else None
                ),
                "revenueAvg": (
                    int(row["estimated_revenue_avg"])
                    if row["estimated_revenue_avg"] is not None
                    else None
                ),
                "sgaExpenseLow": (
                    int(row["estimated_sga_expense_low"])
                    if row["estimated_sga_expense_low"] is not None
                    else None
                ),
                "sgaExpenseHigh": (
                    int(row["estimated_sga_expense_high"])
                    if row["estimated_sga_expense_high"] is not None
                    else None
                ),
                "sgaExpenseAvg": (
                    int(row["estimated_sga_expense_avg"])
                    if row["estimated_sga_expense_avg"] is not None
                    else None
                ),
                "ebitdaLow": (
                    int(row["estimated_ebitda_low"])
                    if row["estimated_ebitda_low"] is not None
                    else None
                ),
                "ebitdaHigh": (
                    int(row["estimated_ebitda_high"])
                    if row["estimated_ebitda_high"] is not None
                    else None
                ),
                "ebitdaAvg": (
                    int(row["estimated_ebitda_avg"])
                    if row["estimated_ebitda_avg"] is not None
                    else None
                ),
                "ebitLow": (
                    int(row["estimated_ebit_low"])
                    if row["estimated_ebit_low"] is not None
                    else None
                ),
                "ebitHigh": (
                    int(row["estimated_ebit_high"])
                    if row["estimated_ebit_high"] is not None
                    else None
                ),
                "ebitAvg": (
                    int(row["estimated_ebit_avg"])
                    if row["estimated_ebit_avg"] is not None
                    else None
                ),
                "netIncomeLow": (
                    int(row["estimated_net_income_low"])
                    if row["estimated_net_income_low"] is not None
                    else None
                ),
                "netIncomeHigh": (
                    int(row["estimated_net_income_high"])
                    if row["estimated_net_income_high"] is not None
                    else None
                ),
                "netIncomeAvg": (
                    int(row["estimated_net_income_avg"])
                    if row["estimated_net_income_avg"] is not None
                    else None
                ),
                "epsAvg": (
                    float(row["estimated_eps_avg"])
                    if row["estimated_eps_avg"] is not None
                    else None
                ),
                "epsHigh": (
                    float(row["estimated_eps_high"])
                    if row["estimated_eps_high"] is not None
                    else None
                ),
                "epsLow": (
                    float(row["estimated_eps_low"])
                    if row["estimated_eps_low"] is not None
                    else None
                ),
                "numAnalystsRevenue": (
                    int(row["number_analysts_estimated_revenue"])
                    if row["number_analysts_estimated_revenue"] is not None
                    else None
                ),
                "numAnalystsEps": (
                    int(row["number_analysts_estimated_eps"])
                    if row["number_analysts_estimated_eps"] is not None
                    else None
                ),
            }
            cached_data.append(data_dict)

        return cached_data

    except Exception as e:
        logger.error(f"Cache retrieval error: {e}")
        return []


def _store_in_cache(
    query: FMPCachedAnalystEstimatesQueryParams, fmp_data: List[Dict[str, Any]]
) -> None:
    """Store analyst estimates in database cache."""

    if not fmp_data:
        return

    insert_query = """
    INSERT INTO analyst_estimates 
    (symbol, date, period,
     estimated_revenue_low, estimated_revenue_high, estimated_revenue_avg,
     estimated_sga_expense_low, estimated_sga_expense_high, estimated_sga_expense_avg,
     estimated_ebitda_low, estimated_ebitda_high, estimated_ebitda_avg,
     estimated_ebit_low, estimated_ebit_high, estimated_ebit_avg,
     estimated_net_income_low, estimated_net_income_high, estimated_net_income_avg,
     estimated_eps_avg, estimated_eps_high, estimated_eps_low,
     number_analysts_estimated_revenue, number_analysts_estimated_eps,
     cached_at, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new_values
    ON DUPLICATE KEY UPDATE
    estimated_revenue_low = new_values.estimated_revenue_low,
    estimated_revenue_high = new_values.estimated_revenue_high,
    estimated_revenue_avg = new_values.estimated_revenue_avg,
    estimated_sga_expense_low = new_values.estimated_sga_expense_low,
    estimated_sga_expense_high = new_values.estimated_sga_expense_high,
    estimated_sga_expense_avg = new_values.estimated_sga_expense_avg,
    estimated_ebitda_low = new_values.estimated_ebitda_low,
    estimated_ebitda_high = new_values.estimated_ebitda_high,
    estimated_ebitda_avg = new_values.estimated_ebitda_avg,
    estimated_ebit_low = new_values.estimated_ebit_low,
    estimated_ebit_high = new_values.estimated_ebit_high,
    estimated_ebit_avg = new_values.estimated_ebit_avg,
    estimated_net_income_low = new_values.estimated_net_income_low,
    estimated_net_income_high = new_values.estimated_net_income_high,
    estimated_net_income_avg = new_values.estimated_net_income_avg,
    estimated_eps_avg = new_values.estimated_eps_avg,
    estimated_eps_high = new_values.estimated_eps_high,
    estimated_eps_low = new_values.estimated_eps_low,
    number_analysts_estimated_revenue = new_values.number_analysts_estimated_revenue,
    number_analysts_estimated_eps = new_values.number_analysts_estimated_eps,
    updated_at = CURRENT_TIMESTAMP,
    is_valid = new_values.is_valid
    """

    batch_data = []
    for row in fmp_data:
        date_str = row.get("date")
        if date_str:
            try:
                if isinstance(date_str, str):
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    date_obj = date_str
            except (ValueError, TypeError):
                logger.warning(f"Invalid date format: {date_str}")
                continue
        else:
            continue

        row_data = (
            query.symbol,
            date_obj,
            query.period,
            row.get("revenueLow"),
            row.get("revenueHigh"),
            row.get("revenueAvg"),
            row.get("sgaExpenseLow"),
            row.get("sgaExpenseHigh"),
            row.get("sgaExpenseAvg"),
            row.get("ebitdaLow"),
            row.get("ebitdaHigh"),
            row.get("ebitdaAvg"),
            row.get("ebitLow"),
            row.get("ebitHigh"),
            row.get("ebitAvg"),
            row.get("netIncomeLow"),
            row.get("netIncomeHigh"),
            row.get("netIncomeAvg"),
            row.get("epsAvg"),
            row.get("epsHigh"),
            row.get("epsLow"),
            row.get("numAnalystsRevenue"),
            row.get("numAnalystsEps"),
            datetime.now(),
            True,
        )
        batch_data.append(row_data)

    if not batch_data:
        return

    try:
        execute_many(insert_query, batch_data)
        logger.debug(
            f"Successfully stored {len(batch_data)} analyst estimates for {query.symbol}"
        )
    except Exception as e:
        logger.warning(f"Failed to store analyst estimates: {e}")
        raise


async def _fetch_from_fmp_direct(
    query: FMPCachedAnalystEstimatesQueryParams,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict]:
    """Fetch data directly from FMP API - completely independent implementation."""
    import asyncio
    import warnings
    from openbb_core.provider.utils.helpers import amake_request
    from openbb_core.provider.utils.errors import UnauthorizedError
    from openbb_core.app.model.abstract.error import OpenBBError

    async def response_callback(response, _):
        """Handle FMP API response."""
        if response.status != 200:
            msg = await response.text()
            code = response.status
            raise UnauthorizedError(f"Unauthorized FMP request -> {code} -> {msg}")

        data = await response.json()

        if isinstance(data, dict):
            error_message = data.get("Error Message", data.get("error"))

            if error_message is not None:
                conditions = (
                    "upgrade" in error_message.lower()
                    or "exclusive endpoint" in error_message.lower()
                    or "special endpoint" in error_message.lower()
                    or "premium query parameter" in error_message.lower()
                    or "subscription" in error_message.lower()
                    or "unauthorized" in error_message.lower()
                    or "premium" in error_message.lower()
                )

                if conditions:
                    raise UnauthorizedError(
                        f"Unauthorized FMP request -> {error_message}"
                    )

                raise OpenBBError(
                    f"FMP Error Message -> Status code: {response.status} -> {error_message}"
                )

        return data

    api_key = credentials.get("fmp_api_key") if credentials else ""
    symbols = query.symbol.split(",")
    results: list[dict] = []

    async def get_one(symbol):
        """Get data for one symbol."""
        url = (
            "https://financialmodelingprep.com/stable/analyst-estimates?"
            + f"symbol={symbol}&period={query.period}"
            + f"&page={query.page if query.page else 0}&limit={query.limit if query.limit else 1000}"
            + f"&apikey={api_key}"
        )
        result = await amake_request(url, response_callback=response_callback, **kwargs)
        if not result or len(result) == 0:
            warnings.warn(f"Symbol Error: No data found for {symbol}")
        if result:
            results.extend(result)

    await asyncio.gather(*[get_one(symbol) for symbol in symbols])

    if not results:
        raise EmptyDataError("No data returned for the given symbols.")

    return results


def get_cache_statistics(
    symbol: str | None = None, period: str | None = None
) -> Dict[str, Any]:
    """Get cache statistics for analyst estimates."""
    try:
        if symbol and period:
            stats_query = """
            SELECT 
                symbol,
                period,
                COUNT(*) as record_count,
                MIN(date) as earliest_date,
                MAX(date) as latest_date
            FROM analyst_estimates 
            WHERE symbol = %s AND period = %s AND is_valid = TRUE
            GROUP BY symbol, period
            """
            results = execute_query(stats_query, (symbol, period))
        elif symbol:
            stats_query = """
            SELECT 
                symbol,
                period,
                COUNT(*) as record_count,
                MIN(date) as earliest_date,
                MAX(date) as latest_date
            FROM analyst_estimates 
            WHERE symbol = %s AND is_valid = TRUE
            GROUP BY symbol, period
            """
            results = execute_query(stats_query, (symbol,))
        else:
            stats_query = """
            SELECT 
                COUNT(DISTINCT symbol) as unique_symbols,
                COUNT(*) as total_records,
                MIN(date) as earliest_date,
                MAX(date) as latest_date
            FROM analyst_estimates 
            WHERE is_valid = TRUE
            """
            results = execute_query(stats_query)

        return {"statistics": results}
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}")
        return {"error": str(e)}


def clear_cache_for_symbol(symbol: str, period: str | None = None) -> bool:
    """Clear cached analyst estimates for a specific symbol."""
    try:
        if period:
            delete_query = (
                "DELETE FROM analyst_estimates WHERE symbol = %s AND period = %s"
            )
            execute_query(delete_query, (symbol, period))
        else:
            delete_query = "DELETE FROM analyst_estimates WHERE symbol = %s"
            execute_query(delete_query, (symbol,))

        logger.info(
            f"Cleared cache for symbol {symbol}"
            + (f" period {period}" if period else "")
        )
        return True
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False
