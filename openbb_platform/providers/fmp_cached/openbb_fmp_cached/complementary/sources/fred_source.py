"""FRED source adapter for complementary US10Y retrieval."""

from datetime import date
from typing import Any

from openbb_fred.models.series import FredSeriesFetcher


async def fetch_us10y(
    start_date: date,
    end_date: date,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch and normalize US10Y from FRED series DGS10."""
    query = FredSeriesFetcher.transform_query(
        {
            "symbol": "DGS10",
            "start_date": start_date,
            "end_date": end_date,
            "limit": 100000,
        }
    )

    raw = await FredSeriesFetcher.aextract_data(query, credentials, **kwargs)
    transformed = FredSeriesFetcher.transform_data(query, raw, **kwargs)
    result = transformed.result if hasattr(transformed, "result") else transformed

    normalized: list[dict[str, Any]] = []
    for item in result:
        payload = item.model_dump(exclude_none=True)
        value = payload.get("DGS10") or payload.get("dgs10")
        if value is None:
            continue
        normalized.append(
            {
                "date": payload.get("date"),
                "yield_pct": float(value),
                "source": "fred",
                "source_symbol": "DGS10",
                "raw": payload,
            }
        )

    return normalized
