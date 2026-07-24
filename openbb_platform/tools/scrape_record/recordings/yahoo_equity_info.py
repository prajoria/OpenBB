"""Recording: capture Yahoo Finance company profile via Playwright.

Called by ``scrape-record record yahoo_equity_info --symbol MSFT``.
Navigates to ``finance.yahoo.com/quote/<SYM>/profile`` and captures
the ``quoteSummary`` JSON XHR that carries summaryProfile +
assetProfile + secFilings.

Part of sub-epic #1374 / PR-2 (#1376), unblocking #1373.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

YAHOO_PROFILE_URL = "https://finance.yahoo.com/quote/{symbol}/profile"
YAHOO_API_MATCH = "/quoteSummary/"


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo profile page; capture summaryProfile / assetProfile.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_equity_info.extract``.
    """
    captured: dict[str, Any] | None = None

    async def _on_response(response):
        if YAHOO_API_MATCH not in response.url:
            return
        # Profile page always requests summaryProfile or assetProfile
        if not any(
            m in response.url for m in ("summaryProfile", "assetProfile", "secFilings")
        ):
            return
        try:
            body = await response.json()
        except Exception:  # pragma: no cover
            return
        nonlocal captured
        captured = body

    page.on("response", _on_response)

    url = YAHOO_PROFILE_URL.format(symbol=symbol.upper())
    await page.goto(url, wait_until="networkidle", timeout=30_000)

    await asyncio.sleep(1.0)

    return {
        "source_url": url,
        "symbol": symbol.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quoteSummary": (captured or {}).get("quoteSummary") if captured else None,
    }
