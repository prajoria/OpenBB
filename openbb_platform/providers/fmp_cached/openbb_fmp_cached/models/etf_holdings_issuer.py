"""Issuer-file ETF holdings tier (#97 L6).

Free, no-key daily holdings files published by ETF issuers. Today seeded
with the 11 GICS sector SPDRs from State Street (SSGA) -- which is the
exact universe ``obb.techtrade.scan`` needs to stop degenerating to the
EURKR symptom. Extensible to iShares / Vanguard / etc. via new
``ISSUER_REGISTRY`` entries.

This module is called from ``FMPCachedEtfHoldingsFetcher._try_issuer``
when the FMP tier returns 402 / empty. It MUST fail soft: any HTTP error,
parse error, or unknown ticker returns ``[]`` so the caller can fall
through to the next tier (SEC N-PORT, when that lands).

Spike-confirmed layout (design doc §0.4, 2026-06-27): SSGA workbooks have
metadata in rows 0-3 then a header row at index 4 with columns
``Name|Ticker|Identifier|SEDOL|Weight|Sector|Shares Held|Local Currency``.
``Identifier`` is the 9-char CUSIP. ``Weight`` is a percentage-as-decimal
(14.79788 means 14.79788% -- normalize to fraction by dividing by 100).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from typing import NamedTuple

import openpyxl
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "OpenBBTechnical/etf-holdings/0.1"
DEFAULT_TIMEOUT_SECS = 30


class IssuerSpec(NamedTuple):
    """Per-issuer (URL template, parser callable, data_source tag).

    The parser signature is ``(content_bytes: bytes, *, ticker: str) -> list[dict]``.
    Typed with ``...`` so mypy doesn't complain about the keyword arg at the
    call site (NamedTuple + Callable[[bytes], ...] would forbid the ticker kwarg).
    """

    url: str
    parser: Callable[..., list[dict]]
    issuer_id: str


def _parse_ssga_xlsx(content: bytes, *, ticker: str) -> list[dict]:
    """Parse an SSGA holdings .xlsx (spike-confirmed layout) into dict rows.

    Returns rows with keys: ``symbol, name, weight (fraction), shares,
    value (None for SSGA), cusip, isin (None for SSGA), data_source``.
    Skips USD CASH and dash-only rows. Never raises -- returns ``[]`` on any
    error (workbook open failure, missing header, missing columns).
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
    except Exception as exc:  # noqa: BLE001
        logger.warning("SSGA workbook open failed for %s: %s", ticker, exc)
        return []

    rows_iter = ws.iter_rows(values_only=True)
    header: list = []
    # Find the header row: it has 'Ticker' AND 'Name' AND 'Weight' columns.
    for row in rows_iter:
        if not row:
            continue
        cells = [c.strip() if isinstance(c, str) else c for c in row]
        cells_lower = {c.lower() if isinstance(c, str) else c for c in cells}
        if {"ticker", "name", "weight"}.issubset(cells_lower):
            header = list(cells)
            break
    if not header:
        logger.warning("SSGA %s: header row (Ticker/Name/Weight) not found", ticker)
        return []

    def _idx(name: str) -> int | None:
        for i, h in enumerate(header):
            if isinstance(h, str) and h.strip().lower() == name.lower():
                return i
        return None

    idx_ticker = _idx("Ticker")
    idx_name = _idx("Name")
    idx_cusip = _idx("Identifier") or _idx("CUSIP")
    idx_weight = _idx("Weight")
    idx_shares = _idx("Shares Held")
    idx_value = _idx("Market Value")  # not in current SSGA file; will be None
    idx_isin = _idx("ISIN")

    if idx_ticker is None or idx_name is None:
        logger.warning("SSGA %s: missing required Ticker/Name column", ticker)
        return []

    def _g(row, idx):
        return row[idx] if idx is not None and idx < len(row) else None

    def _to_float(v):
        if v is None or (isinstance(v, str) and v.strip() in ("-", "")):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    holdings: list[dict] = []
    for row in rows_iter:
        if not row:
            continue
        sym = _g(row, idx_ticker)
        # Skip dash-only and empty-ticker rows
        if sym is None or (isinstance(sym, str) and sym.strip() in ("-", "")):
            continue
        name = _g(row, idx_name)
        # Skip cash rows: name contains "CASH" (case-insensitive)
        if isinstance(name, str) and "CASH" in name.strip().upper():
            continue

        weight = _to_float(_g(row, idx_weight))
        # SSGA expresses the "Weight" column as a percent (14.79788 =
        # 14.79788%). This is the SAME shape FMP's API returns for the
        # weight field, so we emit percentages unchanged — the
        # FMPEtfHoldingsData validator normalizes percent → fraction
        # on model construction (openbb_fmp/models/etf_holdings.py
        # `normalize_percent` field_validator, mode='before'). Passing
        # a fraction here would cause a second /100 divide, producing
        # weights 100× too small (verified live for #512 —
        # SPY.total_weight = 0.01 vs expected 1.0).
        # NOTE: the previous `if weight > 1: weight /= 100` heuristic
        # was ALSO wrong (silently dropped sub-1% holdings' 100× division
        # relative to large holdings inside the same file), but both
        # buggy behaviors were masked because callers never summed weights
        # end-to-end until #512's coverage test added the assertion.

        cusip_raw = _g(row, idx_cusip)
        cusip: str | None = None
        if cusip_raw is not None and not (
            isinstance(cusip_raw, str) and cusip_raw.strip() in ("-", "")
        ):
            cusip = str(cusip_raw).strip().zfill(9)[:9]

        holdings.append(
            {
                "symbol": str(sym).strip().upper(),
                "name": str(name).strip() if name else None,
                "weight": weight,
                "shares": _to_float(_g(row, idx_shares)),
                "value": _to_float(_g(row, idx_value)),
                "cusip": cusip,
                "isin": str(_g(row, idx_isin)).strip() if _g(row, idx_isin) else None,
                "data_source": "issuer_ssga",
            }
        )
    return holdings


# Spike-confirmed SSGA URL pattern: holdings-daily-us-en-<ticker>.xlsx (§0.4 Q1)
_SSGA_URL_TEMPLATE = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-{ticker_lower}.xlsx"
)


def _ssga_spec(ticker: str) -> IssuerSpec:
    return IssuerSpec(
        url=_SSGA_URL_TEMPLATE.format(ticker_lower=ticker.lower()),
        parser=_parse_ssga_xlsx,
        issuer_id="issuer_ssga",
    )


# All 11 GICS sector SPDRs are State Street funds; same URL template.
# Matches openbb_techtrade.engine.screener.GICS_SECTOR_ETFS.values() exactly.
_SPDR_SECTORS = (
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)

# SSGA also publishes the SPDR trust products (SPY = S&P 500, DIA = DJIA)
# via the same URL template + same workbook layout — no new parser needed.
# Added for #512 to unblock the portfolio_basket universe. Follow-ups:
# QQQ (Invesco), IWM/IVV/ACWI/EFA/EEM (iShares), VTI/VOO (Vanguard) each
# need a distinct parser and are tracked as separate issues.
_SSGA_TRUST_PRODUCTS = ("SPY", "DIA")

ISSUER_REGISTRY: dict[str, IssuerSpec] = {
    t: _ssga_spec(t) for t in (*_SPDR_SECTORS, *_SSGA_TRUST_PRODUCTS)
}


def fetch_issuer_holdings(symbol: str, *, http=requests) -> list[dict]:
    """Fetch + parse an ETF's holdings from its issuer's file.

    Returns ``[]`` for unknown ticker, HTTP error, or empty workbook -- never
    raises. The caller (``FMPCachedEtfHoldingsFetcher._try_issuer``) treats
    ``[]`` as "fall through to next tier".

    ``http`` is the HTTP client (``requests`` by default; patched in tests).
    """
    if not symbol:
        return []
    key = symbol.strip().upper()
    spec = ISSUER_REGISTRY.get(key)
    if spec is None:
        logger.debug("issuer-tier: %s not in ISSUER_REGISTRY", key)
        return []
    try:
        r = http.get(
            spec.url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=DEFAULT_TIMEOUT_SECS,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("issuer-tier %s fetch failed: %s", key, exc)
        return []
    rows = spec.parser(r.content, ticker=key)
    logger.info("issuer-tier %s [%s]: %d holdings", key, spec.issuer_id, len(rows))
    return rows
