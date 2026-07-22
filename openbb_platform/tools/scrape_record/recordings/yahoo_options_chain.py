"""Recording: capture Yahoo Finance options chain via Playwright.

Called by ``scrape-record record yahoo_options_chain --symbol AAPL``.
Navigates to ``finance.yahoo.com/quote/<SYM>/options``, iterates every
expiry tab, and captures the JSON response for each expiry's chain.

Yahoo returns options data via a JSON endpoint (``/v7/finance/options``)
that the page hits as XHR. We intercept those responses via
``page.on("response", ...)`` so we don't have to parse the DOM at all —
the JSON is the source of truth.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

YAHOO_OPTIONS_URL = "https://finance.yahoo.com/quote/{symbol}/options"
YAHOO_API_MATCH = "/v7/finance/options/"


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo options page for ``symbol``; capture JSON per expiry.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_options_chain.extract``.
    """
    captured: dict[str, dict] = {}  # unix_expiry -> chain block
    spot_price: float | None = None
    captured_expiries: list[int] = []

    async def _on_response(response):
        # Yahoo returns JSON for every expiry via /v7/finance/options/<SYM>
        if YAHOO_API_MATCH not in response.url:
            return
        try:
            body = await response.json()
        except Exception:  # pragma: no cover - non-JSON bodies ignored
            return
        result = ((body or {}).get("optionChain") or {}).get("result") or []
        if not result:
            return
        entry = result[0]
        quote = entry.get("quote") or {}
        nonlocal spot_price
        if spot_price is None and quote.get("regularMarketPrice") is not None:
            spot_price = float(quote["regularMarketPrice"])
        for chain_block in entry.get("options") or []:
            exp = chain_block.get("expirationDate")
            if exp is not None:
                captured[str(int(exp))] = chain_block
        for exp in entry.get("expirationDates") or []:
            if exp not in captured_expiries:
                captured_expiries.append(int(exp))

    page.on("response", _on_response)

    url = YAHOO_OPTIONS_URL.format(symbol=symbol.upper())
    await page.goto(url, wait_until="networkidle", timeout=30_000)

    # Iterate the expiry <select> options — Yahoo swaps the chain via
    # a client-side call, triggering another XHR that _on_response
    # captures. Fall back gracefully if the selector shape changes.
    try:
        opts = await page.locator("select[name='date']").locator("option").all()
        for opt in opts:
            val = await opt.get_attribute("value")
            if not val:
                continue
            try:
                await page.select_option("select[name='date']", val)
                # Give Yahoo a moment to serve the XHR + settle
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # pragma: no cover - one bad expiry shouldn't fail all
                continue
    except (
        Exception
    ):  # pragma: no cover - selector missing = no drop-down = single-expiry page
        pass

    # Small settle window so late XHRs land
    await asyncio.sleep(1.0)

    return {
        "source_url": url,
        "underlying_symbol": symbol.upper(),
        "spot_price": spot_price,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "captured_expiries": sorted(set(captured_expiries)),
        "chains_by_expiry": captured,
    }
