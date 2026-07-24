"""Recording: capture Yahoo Finance ETF holdings via Playwright.

Called by ``scrape-record record yahoo_etf_holdings --symbol QQQ``.
Navigates to ``finance.yahoo.com/quote/<SYM>/holdings`` and captures
the ``quoteSummary`` JSON XHR that carries topHoldings + fundOwnership
+ sectorWeightings.

Contrast with ``yahoo_bond_etf_holdings``: that recording DOM-scrapes
because bond-ETF holdings render as HTML tables with no clean JSON
endpoint. This one captures the JSON XHR because equity-ETF holdings
DO have a canonical Yahoo JSON path.

Part of sub-epic #1374 / PR-2 (#1376), unblocking #1373.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

YAHOO_HOLDINGS_URL = "https://finance.yahoo.com/quote/{symbol}/holdings"
YAHOO_API_MATCH = "/quoteSummary/"


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo ETF-holdings page; capture topHoldings + sectorWeightings.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_etf_holdings.extract``.
    """
    captured: dict[str, Any] | None = None

    async def _on_response(response):
        if YAHOO_API_MATCH not in response.url:
            return
        # ETF-holdings page requests topHoldings; if we see it, keep the last one.
        if not any(
            m in response.url
            for m in ("topHoldings", "fundOwnership", "sectorWeightings")
        ):
            return
        try:
            body = await response.json()
        except Exception:  # pragma: no cover
            return
        nonlocal captured
        captured = body

    page.on("response", _on_response)

    url = YAHOO_HOLDINGS_URL.format(symbol=symbol.upper())
    await page.goto(url, wait_until="networkidle", timeout=30_000)

    await asyncio.sleep(1.0)

    return {
        "source_url": url,
        "symbol": symbol.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quoteSummary": (captured or {}).get("quoteSummary") if captured else None,
    }
