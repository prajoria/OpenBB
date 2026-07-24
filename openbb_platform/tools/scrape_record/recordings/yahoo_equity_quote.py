"""Recording: capture Yahoo Finance equity quote via Playwright.

Called by ``scrape-record record yahoo_equity_quote --symbol MSFT``.
Navigates to ``finance.yahoo.com/quote/<SYM>`` and captures the
``quoteSummary`` JSON XHR that carries price + summaryDetail +
defaultKeyStatistics.

Yahoo returns JSON for the quote page via ``/quoteSummary/<SYM>``.
The page fires the XHR on load; we intercept via
``page.expect_response(...)`` so we don't have to parse the DOM at all —
the JSON is the source of truth.

**Loud-empty discipline** (per review of PR #1381 issue #1 and
CLAUDE.md Testing Rule #3): if the target XHR is never captured,
``capture()`` raises ``RecordingCaptureError``. That surfaces the
failure through ``run_recording`` → the sweep's per-capture
try/except → the coverage matrix's ``failed`` bucket, instead of
silently writing a hollow snapshot that reports as OK.

Part of sub-epic #1374 / PR-2 (#1376), unblocking #1373.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"
YAHOO_API_MATCH = "/quoteSummary/"
# Modules the quote page requests. If we don't see at least one of these
# in the intercepted XHR URL, the response is not a quote-page payload.
QUOTE_MODULES = ("summaryDetail", "price", "defaultKeyStatistics")


class RecordingCaptureError(RuntimeError):
    """Raised when the target XHR was not observed within timeout.

    Signalled to ``run_recording`` and up through the sweep so failed
    captures land in the ``failed`` bucket instead of producing a
    valid-shaped-but-hollow snapshot (the anti-pattern CLAUDE.md
    Testing Rule #3 calls "loud empties").
    """


def _is_quote_response(response) -> bool:
    if YAHOO_API_MATCH not in response.url:
        return False
    return any(m in response.url for m in QUOTE_MODULES)


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo quote page for ``symbol``; capture the quoteSummary JSON.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_equity_quote.extract``.

    Strategy: arm ``page.expect_response`` BEFORE ``goto`` so the initial
    XHR is caught deterministically, then load the page with
    ``domcontentloaded`` (avoids the ``networkidle`` timeout pitfall on
    Yahoo's long-poll connections). Raise on miss.
    """
    url = YAHOO_QUOTE_URL.format(symbol=symbol.upper())

    try:
        async with page.expect_response(_is_quote_response, timeout=20_000) as info:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        response = await info.value
        body = await response.json()
    except Exception as exc:  # pragma: no cover - live-browser failure paths
        raise RecordingCaptureError(
            f"yahoo_equity_quote: no quoteSummary XHR observed for {symbol} "
            f"({type(exc).__name__}: {exc}). Check Yahoo consent flow / module drift."
        ) from exc

    summary = (body or {}).get("quoteSummary")
    if not summary or not (summary.get("result") or []):
        raise RecordingCaptureError(
            f"yahoo_equity_quote: quoteSummary XHR returned empty result for {symbol}. "
            "Refusing to save hollow snapshot."
        )

    return {
        "source_url": url,
        "symbol": symbol.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "quoteSummary": summary,
    }
