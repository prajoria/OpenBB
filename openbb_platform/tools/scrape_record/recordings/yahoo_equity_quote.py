"""Recording: capture Yahoo Finance equity quote via Playwright.

Called by ``scrape-record record yahoo_equity_quote --symbol MSFT``.
Navigates to ``finance.yahoo.com/quote/<SYM>`` and captures the
``quoteSummary`` JSON XHR that carries price + summaryDetail +
defaultKeyStatistics.

Yahoo returns JSON for the quote page via ``/quoteSummary/<SYM>``.
The page fires the XHR on load; we intercept via
``page.on("response", ...)`` so we never touch the DOM.

Part of sub-epic #1374 / PR-2 (#1376), unblocking #1373.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"
YAHOO_API_MATCH = "/quoteSummary/"


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo quote page for ``symbol``; capture the quoteSummary JSON.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_equity_quote.extract``.

    Strategy: register the response listener BEFORE navigation, so the
    initial XHR is caught. The last matching XHR wins (Yahoo may fire
    multiple; the final one has the full quoteSummary shape).
    """
    captured: dict[str, Any] | None = None

    async def _on_response(response):
        if YAHOO_API_MATCH not in response.url:
            return
        # Match only quote-page relevant modules; filter aggressive to avoid
        # picking up the profile-page or holdings-page XHRs when both are
        # captured in one session (e.g. the sweep script reuses the page).
        # A quote-page XHR always requests summaryDetail or price.
        if not any(
            m in response.url
            for m in ("summaryDetail", "price", "defaultKeyStatistics")
        ):
            return
        try:
            body = await response.json()
        except Exception:  # pragma: no cover - non-JSON bodies ignored
            return
        nonlocal captured
        captured = body

    page.on("response", _on_response)

    url = YAHOO_QUOTE_URL.format(symbol=symbol.upper())
    await page.goto(url, wait_until="networkidle", timeout=30_000)

    # Small settle window so late XHRs land
    await asyncio.sleep(1.0)

    return {
        "source_url": url,
        "symbol": symbol.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quoteSummary": (captured or {}).get("quoteSummary") if captured else None,
    }
