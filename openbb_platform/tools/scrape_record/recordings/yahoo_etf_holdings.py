"""Recording: capture Yahoo Finance ETF holdings via Playwright.

Called by ``scrape-record record yahoo_etf_holdings --symbol QQQ``.
Navigates to ``finance.yahoo.com/quote/<SYM>/holdings`` and captures
the ``quoteSummary`` JSON XHR that carries topHoldings + fundOwnership
+ sectorWeightings.

**Only for equity ETFs.** Bond ETFs (BND, AGG, ...) render holdings as
HTML tables with no clean JSON path — use the DOM-scrape recording
``yahoo_bond_etf_holdings`` for those. The sweep script excludes
bond ETFs from this endpoint (see ``scripts/record_universe_snapshots.py``).

**Loud-empty discipline**: raises ``RecordingCaptureError`` if the
target XHR was not observed OR returned an empty holdings list, so
failed captures land in the sweep's ``failed`` bucket rather than
silently writing hollow snapshots (CLAUDE.md Testing Rule #3).

Part of sub-epic #1374 / PR-2 (#1376), unblocking #1373.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

YAHOO_HOLDINGS_URL = "https://finance.yahoo.com/quote/{symbol}/holdings"
YAHOO_API_MATCH = "/quoteSummary/"
HOLDINGS_MODULES = ("topHoldings", "fundOwnership", "sectorWeightings")


class RecordingCaptureError(RuntimeError):
    """Raised when the target XHR was not observed OR returned no holdings."""


def _is_holdings_response(response) -> bool:
    if YAHOO_API_MATCH not in response.url:
        return False
    return any(m in response.url for m in HOLDINGS_MODULES)


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo ETF-holdings page; capture topHoldings + sectorWeightings.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_etf_holdings.extract``.
    Raises ``RecordingCaptureError`` if the XHR is not observed or the
    ``topHoldings.holdings`` list is empty (which happens for bond ETFs
    that shouldn't be routed here in the first place).
    """
    url = YAHOO_HOLDINGS_URL.format(symbol=symbol.upper())

    try:
        async with page.expect_response(_is_holdings_response, timeout=20_000) as info:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        response = await info.value
        body = await response.json()
    except Exception as exc:  # pragma: no cover
        raise RecordingCaptureError(
            f"yahoo_etf_holdings: no quoteSummary XHR observed for {symbol} "
            f"({type(exc).__name__}: {exc}). Check Yahoo consent flow / module drift."
        ) from exc

    result = ((body or {}).get("quoteSummary") or {}).get("result") or []
    if not result:
        raise RecordingCaptureError(
            f"yahoo_etf_holdings: quoteSummary XHR returned empty result for {symbol}."
        )
    top = (result[0].get("topHoldings") or {}).get("holdings") or []
    if not top:
        raise RecordingCaptureError(
            f"yahoo_etf_holdings: no topHoldings for {symbol}. Bond ETFs (BND, AGG) "
            "should be routed to yahoo_bond_etf_holdings instead — this recording "
            "is equity-ETF only."
        )

    return {
        "source_url": url,
        "symbol": symbol.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quoteSummary": body.get("quoteSummary"),
    }
