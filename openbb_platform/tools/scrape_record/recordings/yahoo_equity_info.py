"""Recording: capture Yahoo Finance company profile via layered fast+fallback.

Fast path: ``query1`` with modules
``summaryProfile,assetProfile,secFilings,price``.
Fallback: DOM-scrape ``/quote/<SYM>/profile`` via
``scrape_record.yahoo_dom.scrape_profile``.

Part of sub-epic #1384 / PR-A (#1385). See sibling recording
``yahoo_equity_quote`` for full design notes.
"""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PROFILE_MODULES = "summaryProfile,assetProfile,secFilings,price"
YAHOO_PROFILE_URL = "https://finance.yahoo.com/quote/{symbol}/profile"


class RecordingCaptureError(RuntimeError):
    """Both fast path and DOM fallback failed for this (endpoint, symbol)."""


async def capture(page, symbol: str) -> dict[str, Any]:
    """Return the raw snapshot dict consumed by the yahoo_equity_info extractor."""
    from scrape_record.config import load_config
    from scrape_record.yahoo_dom import scrape_profile
    from scrape_record.yahoo_query1 import Query1Error, fetch_quote_summary

    cfg = load_config()
    sym = symbol.upper()

    fast_error: str | None = None
    try:
        payload = fetch_quote_summary(cfg, sym, PROFILE_MODULES)
        return {
            "source_url": (
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
                f"?modules={PROFILE_MODULES}"
            ),
            "symbol": sym,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "capture_layer": "query1",
            "quoteSummary": payload["quoteSummary"],
        }
    except Query1Error as exc:
        fast_error = str(exc)

    url = YAHOO_PROFILE_URL.format(symbol=sym)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        payload = await scrape_profile(page, sym)
    except Exception as exc:  # pragma: no cover
        raise RecordingCaptureError(
            f"yahoo_equity_info: fast+fallback both failed for {sym}. "
            f"fast: {fast_error}. dom: {type(exc).__name__}: {exc}"
        ) from exc

    result = ((payload.get("quoteSummary") or {}).get("result") or [{}])[0]
    profile = result.get("summaryProfile") or {}
    # Require at least name (from price block) OR sector to have loaded
    price_block = result.get("price") or {}
    if not (price_block.get("longName") or profile.get("sector")):
        raise RecordingCaptureError(
            f"yahoo_equity_info: DOM fallback returned empty profile for {sym}. "
            f"fast_error: {fast_error}"
        )
    return {
        "source_url": url,
        "symbol": sym,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_layer": "dom",
        "capture_notes": f"query1 fell back: {fast_error}" if fast_error else "",
        "quoteSummary": payload["quoteSummary"],
    }
