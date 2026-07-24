"""Extractor for Yahoo Finance ETF-holdings snapshots.

Input (``raw``) is what ``recordings/yahoo_etf_holdings.py`` captures
from the Yahoo ``quoteSummary`` endpoint with
``modules=topHoldings,fundOwnership,sectorWeightings``.

Contrast with the bond-focused ``yahoo_bond_etf_holdings`` extractor:
that one flattens BOND positions (symbol, coupon, maturity, ytm,
rating). This one flattens EQUITY positions (symbol, name, weight)
which is what NB03's ``look_through`` needs.
"""

from __future__ import annotations

from typing import Any


def _dig(d: dict, *path: str, default: Any = None) -> Any:
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _num(v: Any) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("raw")
    return v


def _flatten_holding(row: dict) -> dict:
    """Normalize a topHoldings row to snake_case."""
    return {
        "symbol": row.get("symbol") or row.get("holdingSymbol"),
        "name": row.get("holdingName") or row.get("name"),
        "weight": _num(row.get("holdingPercent") or row.get("weight")),
    }


def _flatten_sector(row: dict) -> dict[str, float]:
    """Yahoo's sectorWeightings is a list of single-key dicts. Merge them."""
    if not isinstance(row, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in row.items():
        num = _num(v)
        if num is not None:
            out[str(k)] = num
    return out


def extract(raw: dict) -> dict:
    """Normalize Yahoo ETF-holdings response into ``etf_symbol`` + ``holdings`` list."""
    # Pre-flattened path
    if "etf_symbol" in raw and "quoteSummary" not in raw:
        return _passthrough(raw)

    result = _dig(raw, "quoteSummary", "result", default=None)
    if not result or not isinstance(result, list) or not result[0]:
        return {
            "etf_symbol": raw.get("etf_symbol") or raw.get("symbol"),
            "holdings": [],
            "sector_weights": {},
            "captured_at": raw.get("captured_at"),
        }

    node = result[0]
    top = node.get("topHoldings") or {}
    price = node.get("price") or {}

    holdings_raw = top.get("holdings") or []
    holdings = [_flatten_holding(h) for h in holdings_raw if isinstance(h, dict)]

    sectors_raw = top.get("sectorWeightings") or []
    sectors: dict[str, float] = {}
    for s in sectors_raw:
        sectors.update(_flatten_sector(s))

    return {
        "etf_symbol": price.get("symbol") or raw.get("symbol") or raw.get("etf_symbol"),
        "etf_name": price.get("longName") or price.get("shortName"),
        "holdings": holdings,
        "sector_weights": sectors,
        "captured_at": raw.get("captured_at"),
    }


def _passthrough(raw: dict) -> dict:
    holdings_raw = raw.get("holdings") or raw.get("top_holdings") or []
    return {
        "etf_symbol": raw.get("etf_symbol") or raw.get("symbol"),
        "etf_name": raw.get("etf_name") or raw.get("name"),
        "holdings": [_flatten_holding(h) for h in holdings_raw if isinstance(h, dict)],
        "sector_weights": raw.get("sector_weights") or {},
        "captured_at": raw.get("captured_at"),
    }
