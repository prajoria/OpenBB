"""Extractor for Yahoo Finance bond-ETF holdings snapshots.

Input (``raw``) is the shape our ``recordings/yahoo_bond_etf_holdings.py``
capture returns:

.. code-block:: python

    {
        "source_url": "https://finance.yahoo.com/quote/BND/holdings",
        "etf_symbol": "BND",
        "etf_name": "Vanguard Total Bond Market Index Fund ETF Shares",
        "as_of_date": "2025-06-30",  # holdings snapshot date
        "captured_at": "2026-07-22T18:00:00+00:00",
        "top_holdings": [
            {
                "symbol": "T 4.5 02/15/36",
                "issuer": "United States Treasury Note/Bond",
                "coupon": 4.5,
                "maturity": "2036-02-15",
                "weight": 0.043,
                "ytm": 4.32,      # if Yahoo surfaces it
                "rating": "AAA",
            },
            ...
        ],
        "sector_weights": {"Treasury": 0.42, "Corporate": 0.28, ...},
        "credit_quality_breakdown": {"AAA": 0.68, "AA": 0.11, ...},
        "average_ytm": 4.85,       # portfolio-level, if surfaced
        "duration_years": 6.2,     # portfolio-level, if surfaced
    }

Output — normalized bond ladder + portfolio-level roll-up. Since #1000
was "corporate bond issuance + YTM", we surface the holdings list
(each row = one bond position; issuer + coupon + maturity + weight +
YTM approximation from ETF-level metrics) and the roll-up (average
YTM, duration) as separate keys.
"""

from __future__ import annotations

from typing import Any


def _flatten_holding(row: dict) -> dict:
    """Normalize a holding row to snake_case with sensible fallbacks."""
    return {
        "symbol": row.get("symbol") or row.get("holding_symbol"),
        "issuer": row.get("issuer") or row.get("name"),
        "coupon": row.get("coupon"),
        "maturity": row.get("maturity"),
        "weight": row.get("weight"),
        "ytm": row.get("ytm"),
        "rating": row.get("rating"),
    }


def extract(raw: dict[str, Any]) -> dict[str, Any]:
    """Transform raw Yahoo bond-ETF holdings snapshot into structured ladder.

    Returns a dict with:

    - ``etf_symbol``: the ETF ticker (BND, AGG, etc.)
    - ``etf_name``: human-readable ETF name
    - ``as_of_date``: holdings-snapshot date reported by Yahoo (str)
    - ``captured_at``: ISO timestamp propagated from raw
    - ``holdings``: list of {symbol, issuer, coupon, maturity, weight,
      ytm, rating} — the actual bond-ladder rows
    - ``sector_weights``: dict of {sector_name: weight_fraction}
    - ``credit_quality_breakdown``: dict of {rating: weight_fraction}
    - ``portfolio_avg_ytm``: float | None (portfolio-level YTM if Yahoo
      surfaces it)
    - ``portfolio_duration_years``: float | None
    """
    etf_symbol = raw.get("etf_symbol") or raw.get("symbol") or ""
    etf_name = raw.get("etf_name") or raw.get("name")
    as_of_date = raw.get("as_of_date")
    captured_at = raw.get("captured_at")

    holdings_raw = raw.get("top_holdings") or raw.get("holdings") or []
    holdings = [_flatten_holding(h) for h in holdings_raw if isinstance(h, dict)]

    sector_weights = raw.get("sector_weights") or {}
    credit_quality_breakdown = raw.get("credit_quality_breakdown") or {}
    portfolio_avg_ytm = raw.get("average_ytm") or raw.get("portfolio_avg_ytm")
    portfolio_duration_years = raw.get("duration_years") or raw.get(
        "portfolio_duration_years"
    )

    return {
        "etf_symbol": etf_symbol,
        "etf_name": etf_name,
        "as_of_date": as_of_date,
        "captured_at": captured_at,
        "holdings": holdings,
        "sector_weights": sector_weights,
        "credit_quality_breakdown": credit_quality_breakdown,
        "portfolio_avg_ytm": portfolio_avg_ytm,
        "portfolio_duration_years": portfolio_duration_years,
    }
