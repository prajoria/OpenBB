"""Yahoo Finance source adapter for complementary US10Y retrieval."""

from datetime import date
from typing import Any

from openbb_yfinance.models.index_historical import YFinanceIndexHistoricalFetcher


def _normalize_tnx_close(close_value: float) -> float:
    """Normalize TNX close to yield percent."""
    close_float = float(close_value)
    return close_float / 10.0 if close_float > 20 else close_float


def fetch_us10y(
    start_date: date,
    end_date: date,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch and normalize US10Y proxy from Yahoo index historical (^TNX)."""
    query = YFinanceIndexHistoricalFetcher.transform_query(
        {
            "symbol": "^TNX",
            "start_date": start_date,
            "end_date": end_date,
            "interval": "1d",
        }
    )
    raw = YFinanceIndexHistoricalFetcher.extract_data(query, credentials, **kwargs)
    transformed = YFinanceIndexHistoricalFetcher.transform_data(query, raw, **kwargs)

    normalized: list[dict[str, Any]] = []
    for item in transformed:
        payload = item.model_dump(exclude_none=True)
        close_value = payload.get("close")
        if close_value is None:
            continue
        normalized.append(
            {
                "date": payload.get("date"),
                "yield_pct": _normalize_tnx_close(float(close_value)),
                "source": "yfinance",
                "source_symbol": "^TNX",
                "raw": payload,
            }
        )

    return normalized
