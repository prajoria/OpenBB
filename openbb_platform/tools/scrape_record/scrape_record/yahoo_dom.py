"""DOM-scrape helpers for Yahoo Finance SvelteKit pages.

Fallback layer used by ``scrape_record/recordings/yahoo_equity_*.py``
when ``yahoo_query1.fetch_quote_summary`` raises ``Query1Error``.

Contract: each helper is an async function that takes a live Playwright
``page`` (already navigated to the target URL) and returns a dict shaped
like Yahoo's ``quoteSummary`` REST payload. This lets the same extractor
consume either code path — the extractor doesn't care whether the data
came from ``query1`` or the DOM.

See ``.dev-cycle/yahoo-scraping-investigation/INVESTIGATION_REPORT.md``
for the DOM structure documentation this module is built against.
"""

# pylint: disable=too-many-locals

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Low-level DOM readers
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")


def _parse_number(text: str | None) -> float | None:
    """Yahoo renders numbers like ``12,345.67`` / ``$381.70`` / ``+0.03%``.

    Returns the first numeric token as a float, or None if unparseable.
    """
    if not text:
        return None
    text = text.strip()
    if not text or text in ("--", "-", "N/A"):
        return None
    m = _NUMBER_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _parse_bignum(text: str | None) -> float | None:
    """Parse ``2.83T``, ``1.5B``, ``221k`` — Yahoo's abbreviated scale strings."""
    if not text:
        return None
    text = text.strip()
    if not text or text in ("--", "-", "N/A"):
        return None
    m = re.match(r"^\s*(-?[\d.,]+)\s*([KMBT])?\s*$", text, re.IGNORECASE)
    if not m:
        return _parse_number(text)
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (m.group(2) or "").upper()
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(suffix, 1.0)
    return n * scale


async def _testid_text(page, testid: str) -> str | None:
    """Inner text of the first element with the given data-testid, or None."""
    loc = page.locator(f'[data-testid="{testid}"]').first
    try:
        return (await loc.inner_text(timeout=3_000)).strip()
    except Exception:  # pragma: no cover  (missing selector)
        return None


async def _testid_texts(page, testid: str, limit: int = 100) -> list[str]:
    """Inner text of every element with the given data-testid."""
    loc = page.locator(f'[data-testid="{testid}"]')
    out: list[str] = []
    try:
        count = await loc.count()
    except Exception:  # pragma: no cover
        return out
    for i in range(min(count, limit)):
        try:
            out.append((await loc.nth(i).inner_text(timeout=1_500)).strip())
        except (
            Exception
        ):  # noqa: BLE001, S112 - per-locator miss is row-level; skip is intended
            continue
    return out


async def _read_all_tables(page, max_tables: int = 20) -> list[list[list[str]]]:
    """Return every ``<table>`` on the page as a list of rows-of-cells.

    Uses ``page.evaluate`` to serialize in one shot — much faster than
    per-cell ``inner_text`` calls.
    """
    js = f"""() => {{
        const tables = Array.from(document.querySelectorAll('table')).slice(0, {max_tables});
        return tables.map(t => {{
            const rows = Array.from(t.querySelectorAll('tr'));
            return rows.map(r => {{
                const cells = Array.from(r.querySelectorAll('th, td'));
                return cells.map(c => (c.innerText || '').trim());
            }});
        }});
    }}"""
    try:
        return await page.evaluate(js)
    except Exception:  # pragma: no cover
        return []


# ---------------------------------------------------------------------------
# Composers — return quoteSummary-shaped payloads
# ---------------------------------------------------------------------------


def _wrap_raw(value: Any) -> dict[str, Any] | None:
    """Wrap a scalar as Yahoo's ``{"raw": ..., "fmt": ...}`` shape."""
    if value is None:
        return None
    return {"raw": value, "fmt": str(value)}


async def scrape_quote(page, symbol: str) -> dict:
    """DOM-scrape the /quote/<SYM> page into a quoteSummary-shaped dict.

    Populates the ``price`` + ``summaryDetail`` modules with whatever
    scalars the SSR HTML exposes. Fields absent from the DOM come back
    as ``None`` (already wrapped by ``_wrap_raw``).
    """
    price_text = await _testid_text(page, "qsp-price")
    change_text = await _testid_text(page, "qsp-price-change")
    change_pct_text = await _testid_text(page, "qsp-price-change-percent")
    title_text = await _testid_text(page, "quote-title") or ""

    # "Microsoft Corporation (MSFT)" → long_name + symbol
    long_name = re.sub(r"\s*\(([A-Z.^=-]+)\)\s*$", "", title_text).strip() or None
    symbol_from_title = None
    m = re.search(r"\(([A-Z.^=-]+)\)\s*$", title_text)
    if m:
        symbol_from_title = m.group(1)

    price = _parse_number(price_text)
    change = _parse_number(change_text)
    change_pct = _parse_number(change_pct_text)

    price_block: dict[str, Any] = {
        "symbol": symbol_from_title or symbol.upper(),
        "longName": long_name,
        "shortName": long_name,
        "regularMarketPrice": _wrap_raw(price),
        "regularMarketChange": _wrap_raw(change),
        "regularMarketChangePercent": _wrap_raw(change_pct),
    }

    # summaryDetail comes from the ("Previous Close" / "Open" / "Day's Range" /
    # "Volume" / "Market Cap" ...) labeled fields — check the "quote-statistics"
    # / "price-statistic" testid regions.
    stats_map = await _collect_labeled_stats(page)
    summary_detail = {
        "previousClose": _wrap_raw(_parse_number(stats_map.get("Previous Close"))),
        "open": _wrap_raw(_parse_number(stats_map.get("Open"))),
        "dayLow": _wrap_raw(_parse_range_low(stats_map.get("Day's Range"))),
        "dayHigh": _wrap_raw(_parse_range_high(stats_map.get("Day's Range"))),
        "volume": _wrap_raw(_parse_bignum(stats_map.get("Volume"))),
        "marketCap": _wrap_raw(_parse_bignum(stats_map.get("Market Cap (intraday)"))),
    }

    return {
        "quoteSummary": {
            "result": [
                {
                    "price": price_block,
                    "summaryDetail": summary_detail,
                    "defaultKeyStatistics": {},
                }
            ],
            "error": None,
        },
        "_source": "dom",
    }


async def scrape_profile(page, symbol: str) -> dict:
    """DOM-scrape the /quote/<SYM>/profile page."""
    title_text = await _testid_text(page, "quote-title") or ""
    long_name = re.sub(r"\s*\(([A-Z.^=-]+)\)\s*$", "", title_text).strip() or None
    m = re.search(r"\(([A-Z.^=-]+)\)\s*$", title_text)
    symbol_from_title = m.group(1) if m else None

    # Profile page renders sector/industry as labeled dt/dd or typography rows.
    # Read every visible dd + look for company description.
    profile = await page.evaluate("""() => {
            const out = {};
            document.querySelectorAll('dt').forEach(dt => {
                const dd = dt.nextElementSibling;
                if (dd && dd.tagName === 'DD') {
                    out[(dt.innerText || '').trim()] = (dd.innerText || '').trim();
                }
            });
            const desc = document.querySelector('[data-testid="description"]');
            const bio = document.querySelector('section p');
            return {
                dl: out,
                description: (desc && desc.innerText) ||
                             (bio && bio.innerText) || null,
            };
        }""")
    dl = (profile or {}).get("dl") or {}
    description = (profile or {}).get("description")

    summary_profile = {
        "sector": dl.get("Sector") or dl.get("Sector(s)"),
        "industry": dl.get("Industry"),
        "country": dl.get("Country"),
        "website": dl.get("Website"),
        "longBusinessSummary": description,
        "fullTimeEmployees": _wrap_raw(_parse_bignum(dl.get("Full Time Employees"))),
    }
    price = {
        "symbol": symbol_from_title or symbol.upper(),
        "longName": long_name,
        "shortName": long_name,
    }
    return {
        "quoteSummary": {
            "result": [{"price": price, "summaryProfile": summary_profile}],
            "error": None,
        },
        "_source": "dom",
    }


async def scrape_etf_holdings(page, symbol: str) -> dict:
    """DOM-scrape the /quote/<SYM>/holdings page for equity-ETF composition."""
    title_text = await _testid_text(page, "quote-title") or ""
    long_name = re.sub(r"\s*\(([A-Z.^=-]+)\)\s*$", "", title_text).strip() or None
    m = re.search(r"\(([A-Z.^=-]+)\)\s*$", title_text)
    symbol_from_title = m.group(1) if m else None

    tables = await _read_all_tables(page)
    holdings: list[dict[str, Any]] = []
    sector_weights: dict[str, float] = {}
    for tbl in tables:
        # Detect "Top holdings" style: first cell is a ticker symbol
        for row in tbl:
            if not row:
                continue
            cells = [c.strip() for c in row if c.strip()]
            if len(cells) < 2:
                continue
            # Sector weights row: ("Technology", "42.30%")
            if len(cells) == 2 and cells[1].endswith("%"):
                pct = _parse_number(cells[1])
                if pct is not None and pct <= 100.0:
                    key = cells[0]
                    # Accept generic key/percent rows — well-known ETF composition
                    # labels (Stocks/Bonds/Cash/Other) AND sector-weight rows all
                    # follow the same "Label | NN%" shape.
                    sector_weights[key] = pct / 100.0
            # Holdings row heuristic: uppercase-looking ticker + name + weight
            elif len(cells) >= 3 and re.match(r"^[A-Z.\-]{1,6}$", cells[0]):
                weight = _parse_number(cells[-1])
                holdings.append(
                    {
                        "symbol": cells[0],
                        "holdingName": cells[1],
                        "holdingPercent": _wrap_raw(
                            (weight or 0.0) / 100.0 if weight is not None else None
                        ),
                    }
                )

    return {
        "quoteSummary": {
            "result": [
                {
                    "price": {
                        "symbol": symbol_from_title or symbol.upper(),
                        "longName": long_name,
                        "shortName": long_name,
                    },
                    "topHoldings": {
                        "holdings": holdings,
                        "sectorWeightings": [
                            {k: _wrap_raw(v)} for k, v in sector_weights.items()
                        ],
                    },
                }
            ],
            "error": None,
        },
        "_source": "dom",
    }


# ---------------------------------------------------------------------------
# Labeled-stat helpers  (for the quote page's "Previous Close / Open / ..." grid)
# ---------------------------------------------------------------------------


async def _collect_labeled_stats(page) -> dict[str, str]:
    """Read the "Previous Close / Open / ..." labeled grid.

    Yahoo renders these as ``<li>`` items with a label span + value span.
    We enumerate all ``li`` elements under the price-statistic region.
    """
    try:
        pairs = await page.evaluate("""() => {
                const out = {};
                // The layout uses <li> pairs of label + value.
                document.querySelectorAll('li').forEach(li => {
                    const spans = li.querySelectorAll('span');
                    if (spans.length >= 2) {
                        const label = (spans[0].innerText || '').trim();
                        const value = (spans[spans.length - 1].innerText || '').trim();
                        if (label && value && label !== value) {
                            out[label] = value;
                        }
                    }
                });
                return out;
            }""")
    except Exception:  # pragma: no cover
        return {}
    return pairs or {}


def _parse_range_low(text: str | None) -> float | None:
    if not text:
        return None
    parts = re.split(r"\s*-\s*", text)
    if len(parts) != 2:
        return None
    return _parse_number(parts[0])


def _parse_range_high(text: str | None) -> float | None:
    if not text:
        return None
    parts = re.split(r"\s*-\s*", text)
    if len(parts) != 2:
        return None
    return _parse_number(parts[1])
