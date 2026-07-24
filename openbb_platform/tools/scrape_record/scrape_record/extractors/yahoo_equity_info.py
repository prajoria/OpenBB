"""Extractor for Yahoo Finance equity-info (company profile) snapshots.

Input (``raw``) is what ``recordings/yahoo_equity_info.py`` captures
from the Yahoo ``quoteSummary`` endpoint with
``modules=summaryProfile,assetProfile,secFilings``.
"""

from __future__ import annotations

from typing import Any


def _dig(d: dict, *path: str, default: Any = None) -> Any:
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _num(v: Any) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("raw")
    return v


def extract(raw: dict) -> dict:
    """Normalize Yahoo profile response into a flat company-profile row."""
    # Pre-flattened path (recording did some parsing)
    if "symbol" in raw and "quoteSummary" not in raw:
        return _passthrough(raw)

    result = _dig(raw, "quoteSummary", "result", default=None)
    if not result or not isinstance(result, list) or not result[0]:
        return {"symbol": raw.get("symbol"), "captured_at": raw.get("captured_at")}

    node = result[0]
    profile = node.get("summaryProfile") or {}
    asset = node.get("assetProfile") or {}
    price = node.get("price") or {}

    # summaryProfile is the primary source for equities; assetProfile for funds.
    src = profile if profile else asset

    return {
        "symbol": price.get("symbol") or raw.get("symbol"),
        "name": price.get("longName") or price.get("shortName"),
        "short_name": price.get("shortName"),
        "sector": src.get("sector"),
        "industry": src.get("industry") or src.get("industryDisp"),
        "country": src.get("country"),
        "website": src.get("website"),
        "long_business_summary": src.get("longBusinessSummary"),
        "full_time_employees": _num(src.get("fullTimeEmployees")),
        "captured_at": raw.get("captured_at"),
    }


def _passthrough(raw: dict) -> dict:
    return {
        "symbol": raw.get("symbol"),
        "name": raw.get("name") or raw.get("long_name"),
        "short_name": raw.get("short_name"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "country": raw.get("country"),
        "website": raw.get("website"),
        "long_business_summary": raw.get("long_business_summary")
        or raw.get("longBusinessSummary"),
        "full_time_employees": _num(raw.get("full_time_employees")),
        "captured_at": raw.get("captured_at"),
    }
