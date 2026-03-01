"""FMP source adapter for complementary US10Y retrieval."""

from datetime import date
from typing import Any

from openbb_fmp.models.treasury_rates import FMPTreasuryRatesFetcher


async def fetch_us10y(
    start_date: date,
    end_date: date,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch and normalize US10Y from the FMP treasury rates endpoint."""
    query = FMPTreasuryRatesFetcher.transform_query(
        {"start_date": start_date, "end_date": end_date}
    )
    raw = await FMPTreasuryRatesFetcher.aextract_data(query, credentials, **kwargs)
    transformed = FMPTreasuryRatesFetcher.transform_data(query, raw, **kwargs)

    normalized: list[dict[str, Any]] = []
    for item in transformed:
        payload = item.model_dump(exclude_none=True)
        year_10 = payload.get("year_10")
        if year_10 is None:
            continue
        normalized.append(
            {
                "date": payload.get("date"),
                "yield_pct": float(year_10) * 100.0,
                "source": "fmp",
                "source_symbol": "year10",
                "raw": payload,
            }
        )

    return normalized
