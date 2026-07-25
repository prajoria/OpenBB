"""Recording: capture Yahoo Finance equity quote via layered fast+fallback.

Called by ``scrape-record record yahoo_equity_quote --symbol MSFT``.

**Fast path** — ``query1.finance.yahoo.com/v10/finance/quoteSummary``
with a warmed browser session. Returns the canonical ``quoteSummary``
JSON in <1 second. No Playwright interaction beyond seeding cookies
once every ``SESSION_TTL`` (6h) and cache-refresh on 401.

**Fallback** — if ``query1`` returns 401 / bot-block / empty result,
navigate the Playwright page to ``/quote/<SYM>`` and DOM-scrape the
``data-testid="qsp-price"`` / labeled-stat grid. Result is wrapped
in the same ``quoteSummary`` shape so the extractor is agnostic.

**Loud-empty discipline**: if both layers fail, ``capture()`` raises
``RecordingCaptureError`` — the sweep counts it as ``failed``, no
hollow snapshot is written.

See ``.dev-cycle/yahoo-scraping-investigation/INVESTIGATION_REPORT.md``
for the SPA migration story that made this rewrite necessary.

Part of sub-epic #1384 / PR-A (#1385).
"""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

QUOTE_MODULES = "summaryDetail,price,defaultKeyStatistics"
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"


class RecordingCaptureError(RuntimeError):
    """Both fast path and DOM fallback failed for this (endpoint, symbol)."""


async def capture(page, symbol: str) -> dict[str, Any]:
    """Return the raw snapshot dict consumed by the yahoo_equity_quote extractor."""
    from scrape_record.config import load_config
    from scrape_record.yahoo_dom import scrape_quote
    from scrape_record.yahoo_query1 import Query1Error, fetch_quote_summary

    cfg = load_config()
    sym = symbol.upper()

    # Fast path — direct query1 call using the same persistent-profile session
    fast_error: str | None = None
    try:
        payload = fetch_quote_summary(cfg, sym, QUOTE_MODULES)
        return {
            "source_url": (
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
                f"?modules={QUOTE_MODULES}"
            ),
            "symbol": sym,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "capture_layer": "query1",
            "quoteSummary": payload["quoteSummary"],
        }
    except Query1Error as exc:
        fast_error = str(exc)

    # Fallback — DOM scrape via Playwright
    url = YAHOO_QUOTE_URL.format(symbol=sym)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        payload = await scrape_quote(page, sym)
    except Exception as exc:  # pragma: no cover - live-browser paths
        raise RecordingCaptureError(
            f"yahoo_equity_quote: fast+fallback both failed for {sym}. "
            f"fast: {fast_error}. dom: {type(exc).__name__}: {exc}"
        ) from exc

    result = ((payload.get("quoteSummary") or {}).get("result") or [{}])[0]
    price_block = result.get("price") or {}
    if not price_block.get("regularMarketPrice"):
        raise RecordingCaptureError(
            f"yahoo_equity_quote: DOM fallback returned empty price for {sym}. "
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
