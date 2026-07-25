"""Recording: capture Yahoo Finance ETF holdings via layered fast+fallback.

Fast path: ``query1`` with modules
``topHoldings,fundOwnership,sectorWeightings,price``.
Fallback: DOM-scrape ``/quote/<SYM>/holdings`` via
``scrape_record.yahoo_dom.scrape_etf_holdings``.

**Equity ETFs only.** Bond ETFs (BND, AGG, ...) render holdings as
HTML tables with no clean JSON — use the DOM-scrape recording
``yahoo_bond_etf_holdings`` for those. The sweep script routes
correctly (see ``scripts/record_universe_snapshots.py``).

Part of sub-epic #1384 / PR-A (#1385). See sibling recording
``yahoo_equity_quote`` for full design notes.
"""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

HOLDINGS_MODULES = "topHoldings,fundOwnership,sectorWeightings,price"
YAHOO_HOLDINGS_URL = "https://finance.yahoo.com/quote/{symbol}/holdings"


class RecordingCaptureError(RuntimeError):
    """Both fast path and DOM fallback failed for this (endpoint, symbol)."""


async def capture(page, symbol: str) -> dict[str, Any]:
    """Return the raw snapshot dict consumed by the yahoo_etf_holdings extractor."""
    from scrape_record.config import load_config
    from scrape_record.yahoo_dom import scrape_etf_holdings
    from scrape_record.yahoo_query1 import Query1Error, fetch_quote_summary

    cfg = load_config()
    sym = symbol.upper()

    fast_error: str | None = None
    try:
        payload = fetch_quote_summary(cfg, sym, HOLDINGS_MODULES)
        # Require non-empty holdings — bond ETFs 200 OK with empty list here
        result = ((payload.get("quoteSummary") or {}).get("result") or [{}])[0]
        holdings = (result.get("topHoldings") or {}).get("holdings") or []
        if not holdings:
            raise Query1Error(
                f"query1 returned OK but topHoldings.holdings empty for {sym}. "
                "Probably a bond ETF — route to yahoo_bond_etf_holdings instead."
            )
        return {
            "source_url": (
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
                f"?modules={HOLDINGS_MODULES}"
            ),
            "symbol": sym,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "capture_layer": "query1",
            "quoteSummary": payload["quoteSummary"],
        }
    except Query1Error as exc:
        fast_error = str(exc)

    url = YAHOO_HOLDINGS_URL.format(symbol=sym)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        payload = await scrape_etf_holdings(page, sym)
    except Exception as exc:  # pragma: no cover
        raise RecordingCaptureError(
            f"yahoo_etf_holdings: fast+fallback both failed for {sym}. "
            f"fast: {fast_error}. dom: {type(exc).__name__}: {exc}"
        ) from exc

    result = ((payload.get("quoteSummary") or {}).get("result") or [{}])[0]
    holdings = (result.get("topHoldings") or {}).get("holdings") or []
    if not holdings:
        raise RecordingCaptureError(
            f"yahoo_etf_holdings: no holdings for {sym} via DOM either. "
            "Bond ETFs (BND, AGG) should route to yahoo_bond_etf_holdings — this "
            f"recording is equity-ETF only. fast_error: {fast_error}"
        )
    return {
        "source_url": url,
        "symbol": sym,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_layer": "dom",
        "capture_notes": f"query1 fell back: {fast_error}" if fast_error else "",
        "quoteSummary": payload["quoteSummary"],
    }
