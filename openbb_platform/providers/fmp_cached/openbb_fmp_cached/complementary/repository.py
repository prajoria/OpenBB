"""Repository helpers for complementary market yield cache."""

import json
from datetime import date, datetime
from typing import Any

from openbb_fmp_cached.utils.cache_schema import (
    create_complementary_market_yields_table,
    get_table_name,
)
from openbb_fmp_cached.utils.database import execute_many, execute_query


def ensure_table() -> None:
    """Create complementary cache table if it doesn't exist."""
    create_complementary_market_yields_table()


def read_cached_rows(
    symbol: str,
    start_date: date,
    end_date: date,
    freshness_cutoff: datetime,
) -> list[dict[str, Any]]:
    """Read fresh cached rows for a symbol and date range."""
    table_name = get_table_name("complementary_market_yields")
    query = f"""
    SELECT date, close, additional_fields, data_json, cached_at
    FROM {table_name}
    WHERE symbol = %s
      AND date BETWEEN %s AND %s
      AND is_valid = TRUE
      AND cached_at >= %s
    ORDER BY date ASC
    """
    return execute_query(query, (symbol, start_date, end_date, freshness_cutoff)) or []


def upsert_rows(symbol: str, rows: list[dict[str, Any]]) -> None:
    """Upsert normalized rows into complementary cache table."""
    if not rows:
        return

    table_name = get_table_name("complementary_market_yields")
    query = f"""
    INSERT INTO {table_name} (
        symbol,
        date,
        close,
        data_json,
        additional_fields,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
        close = VALUES(close),
        data_json = VALUES(data_json),
        additional_fields = VALUES(additional_fields),
        is_valid = TRUE,
        cached_at = CURRENT_TIMESTAMP
    """

    params_list = [
        (
            symbol,
            item["date"],
            item["yield_pct"],
            json.dumps(item.get("raw", {})),
            json.dumps(
                {
                    "source": item.get("source"),
                    "source_symbol": item.get("source_symbol", symbol),
                    "retrieved_at": datetime.utcnow().isoformat(),
                }
            ),
        )
        for item in rows
        if item.get("date") is not None and item.get("yield_pct") is not None
    ]

    if params_list:
        execute_many(query, params_list)
