"""Recording: capture Yahoo Finance company profile via Playwright.

Called by ``scrape-record record yahoo_equity_info --symbol MSFT``.
Navigates to ``finance.yahoo.com/quote/<SYM>/profile`` and captures
the ``quoteSummary`` JSON XHR that carries summaryProfile +
assetProfile + secFilings.

**Loud-empty discipline**: raises ``RecordingCaptureError`` if the
target XHR was not observed within timeout, so failed captures land
in the sweep's ``failed`` bucket rather than silently writing hollow
snapshots (CLAUDE.md Testing Rule #3).

Part of sub-epic #1374 / PR-2 (#1376), unblocking #1373.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

YAHOO_PROFILE_URL = "https://finance.yahoo.com/quote/{symbol}/profile"
YAHOO_API_MATCH = "/quoteSummary/"
PROFILE_MODULES = ("summaryProfile", "assetProfile", "secFilings")


class RecordingCaptureError(RuntimeError):
    """Raised when the target XHR was not observed within timeout."""


def _is_profile_response(response) -> bool:
    if YAHOO_API_MATCH not in response.url:
        return False
    return any(m in response.url for m in PROFILE_MODULES)


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo profile page; capture summaryProfile / assetProfile.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_equity_info.extract``.
    Raises ``RecordingCaptureError`` if the XHR is not observed.
    """
    url = YAHOO_PROFILE_URL.format(symbol=symbol.upper())

    try:
        async with page.expect_response(_is_profile_response, timeout=20_000) as info:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        response = await info.value
        body = await response.json()
    except Exception as exc:  # pragma: no cover
        raise RecordingCaptureError(
            f"yahoo_equity_info: no quoteSummary XHR observed for {symbol} "
            f"({type(exc).__name__}: {exc}). Check Yahoo consent flow / module drift."
        ) from exc

    summary = (body or {}).get("quoteSummary")
    if not summary or not (summary.get("result") or []):
        raise RecordingCaptureError(
            f"yahoo_equity_info: quoteSummary XHR returned empty result for {symbol}. "
            "Refusing to save hollow snapshot."
        )

    return {
        "source_url": url,
        "symbol": symbol.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quoteSummary": summary,
    }
