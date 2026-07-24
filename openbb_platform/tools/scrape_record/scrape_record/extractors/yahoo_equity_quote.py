"""Extractor for Yahoo Finance equity-quote snapshots.

Input (``raw``) is what ``recordings/yahoo_equity_quote.py`` captures
from the Yahoo ``quoteSummary`` endpoint. Yahoo's response nests the
fields inside ``quoteSummary.result[0].{price,summaryDetail,defaultKeyStatistics}``.

Output — a normalized flat dict matching
``recorded_equity_quote.YFinanceEquityQuoteRecordedData``'s field set.

Extractors are pure functions of the raw snapshot: same raw input →
same structured output, no network. This lets us evolve the extractor
and re-derive from old raw snapshots without re-scraping.
"""

from __future__ import annotations

from typing import Any


def _dig(d: dict, *path: str, default: Any = None) -> Any:
    """Walk a chain of dict keys; return ``default`` if any hop is missing."""
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _num(v: Any) -> float | int | None:
    """Yahoo wraps numbers as ``{"raw": 123.45, "fmt": "$123.45"}`` — unwrap."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("raw")
    return v


def extract(raw: dict) -> dict:
    """Normalize Yahoo ``quoteSummary`` output into a flat quote row.

    Handles two input shapes:
    - Yahoo native: ``{"quoteSummary": {"result": [{"price": ..., ...}]}}``
    - Pre-flattened (recordings that already did some parsing):
      keys ``symbol``, ``last_price``, ``previous_close``, etc. directly
      at the top level. In this case we pass through with light key
      normalization.
    """
    # Detect pre-flattened shape (recording script may have unwrapped already)
    if "symbol" in raw and "quoteSummary" not in raw:
        return _passthrough(raw)

    result = _dig(raw, "quoteSummary", "result", default=None)
    if not result or not isinstance(result, list) or not result[0]:
        return {"symbol": raw.get("symbol"), "captured_at": raw.get("captured_at")}

    node = result[0]
    price = node.get("price") or {}
    summary = node.get("summaryDetail") or {}
    stats = node.get("defaultKeyStatistics") or {}

    symbol = price.get("symbol") or raw.get("symbol")
    return {
        "symbol": symbol,
        "name": price.get("longName") or price.get("shortName"),
        "exchange": price.get("exchangeName") or price.get("exchange"),
        "currency": price.get("currency"),
        "last_price": _num(price.get("regularMarketPrice")),
        "previous_close": _num(summary.get("previousClose")),
        "open": _num(summary.get("open")),
        "high": _num(summary.get("dayHigh")),
        "low": _num(summary.get("dayLow")),
        "volume": _num(summary.get("volume")),
        "market_cap": _num(price.get("marketCap") or summary.get("marketCap")),
        "captured_at": raw.get("captured_at"),
    }


def _passthrough(raw: dict) -> dict:
    """Pre-flattened path — light normalization only."""
    return {
        "symbol": raw.get("symbol"),
        "name": raw.get("name") or raw.get("long_name") or raw.get("short_name"),
        "exchange": raw.get("exchange"),
        "currency": raw.get("currency"),
        "last_price": _num(raw.get("last_price") or raw.get("regularMarketPrice")),
        "previous_close": _num(raw.get("previous_close")),
        "open": _num(raw.get("open")),
        "high": _num(raw.get("high") or raw.get("day_high")),
        "low": _num(raw.get("low") or raw.get("day_low")),
        "volume": _num(raw.get("volume")),
        "market_cap": _num(raw.get("market_cap")),
        "captured_at": raw.get("captured_at"),
    }
