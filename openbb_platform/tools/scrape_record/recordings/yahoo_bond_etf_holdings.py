"""Recording: capture Yahoo Finance bond-ETF holdings page via Playwright.

Called by ``scrape-record record yahoo_bond_etf_holdings --symbol BND``.
Navigates to ``finance.yahoo.com/quote/<SYM>/holdings`` and captures
holdings tables + roll-up statistics (average YTM, duration, sector
weights, credit quality breakdown).

**Recording strategy:** Yahoo's bond ETF holdings page renders most
data in DOM tables — there's no clean JSON endpoint like the options
page uses. This capture:

1. Waits for the holdings table to load.
2. Reads visible tables via ``locator.all_text_contents()``.
3. Extracts each numeric roll-up (YTM/duration) from named
   ``data-test`` spans.
4. Returns a raw dict that the paired extractor
   (:mod:`scrape_record.extractors.yahoo_bond_etf_holdings`) can
   normalize.

**Scope note:** Full-real Yahoo scraping needs iterative refinement
against the live page (Yahoo A/B-tests the ETF pages heavily). Ship
the scaffold; refine when Daisy has a re-record session. The checked-
in BND fixture is hand-crafted from a snapshot of Yahoo's rendered
data and is representative enough for the fetcher to work against.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

YAHOO_HOLDINGS_URL = "https://finance.yahoo.com/quote/{symbol}/holdings"


async def capture(page, symbol: str) -> dict[str, Any]:
    """Navigate to the Yahoo holdings page for ``symbol``; capture raw scrape.

    Returns the raw snapshot dict consumed by
    ``scrape_record.extractors.yahoo_bond_etf_holdings.extract``.

    Skeleton implementation — refine on a live Yahoo session. The
    checked-in BND fixture demonstrates the target output shape.
    """
    url = YAHOO_HOLDINGS_URL.format(symbol=symbol.upper())
    await page.goto(url, wait_until="networkidle", timeout=30_000)

    # Give the page time to hydrate its holdings tables
    await asyncio.sleep(2.0)

    # Read the ETF name from the header
    etf_name: str | None = None
    try:
        header = await page.locator("h1[data-test='qsp-price']").inner_text(
            timeout=5_000
        )
        etf_name = header.strip()
    except Exception:  # pragma: no cover - selector drift
        pass

    # Best-effort scrape of the top-holdings table into a list of dicts.
    # NOTE: Yahoo's holdings table structure changes frequently — this
    # scaffold expects roughly {name, weight, coupon, maturity} columns.
    # Refine selectors when the live page schema is known.
    top_holdings: list[dict] = []
    try:
        rows = await page.locator("table[data-test='holdings-table'] tbody tr").all()
        for row in rows[:10]:
            cells = await row.locator("td").all_text_contents()
            if len(cells) >= 4:
                top_holdings.append(
                    {
                        "issuer": cells[0].strip(),
                        "weight": _parse_percent(cells[1]),
                        "coupon": _parse_number(cells[2]) if len(cells) > 2 else None,
                        "maturity": cells[3].strip() if len(cells) > 3 else None,
                    }
                )
    except Exception:  # pragma: no cover - table shape may differ
        pass

    # Best-effort scrape of the numeric roll-ups
    average_ytm = await _try_number(page, "[data-test='YIELD_TO_MATURITY-value']")
    duration_years = await _try_number(page, "[data-test='DURATION-value']")

    return {
        "source_url": url,
        "etf_symbol": symbol.upper(),
        "etf_name": etf_name,
        "as_of_date": None,  # Yahoo shows this above the holdings table; scrape when refined
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "top_holdings": top_holdings,
        "sector_weights": {},  # scrape when refined against live page
        "credit_quality_breakdown": {},
        "average_ytm": average_ytm,
        "duration_years": duration_years,
    }


def _parse_percent(text: str) -> float | None:
    """Parse '4.3%' → 0.043."""
    if not text:
        return None
    try:
        stripped = text.strip().rstrip("%")
        return float(stripped) / 100.0
    except (ValueError, AttributeError):
        return None


def _parse_number(text: str) -> float | None:
    """Parse a numeric cell into float, tolerating stray whitespace."""
    if not text:
        return None
    try:
        return float(text.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None


async def _try_number(page, selector: str) -> float | None:
    """Best-effort: grab a numeric span; return None on selector drift."""
    try:
        text = await page.locator(selector).first.inner_text(timeout=3_000)
        return _parse_number(text)
    except Exception:  # pragma: no cover - selector drift is expected
        return None
