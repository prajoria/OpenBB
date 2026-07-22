"""Extractor for Yahoo Finance options chain snapshots.

Input (``raw``) is the shape our ``recordings/yahoo_options_chain.py``
capture returns:

.. code-block:: python

    {
        "source_url": "https://finance.yahoo.com/quote/AAPL/options",
        "underlying_symbol": "AAPL",
        "spot_price": 327.74,
        "captured_expiries": [1735689600, 1738108800, ...],  # unix epoch
        "chains_by_expiry": {
            "1735689600": {
                "expirationDate": 1735689600,
                "hasMiniOptions": False,
                "calls": [{"strike": 300.0, "impliedVolatility": 0.32, ...}, ...],
                "puts":  [{"strike": 300.0, "impliedVolatility": 0.35, ...}, ...],
            },
            ...
        },
    }

Output — structured chain rows PLUS an ATM IV term-structure roll-up
(the shape #999 actually asks for). We surface both because the raw
chain is expensive to reconstruct downstream but the ATM term structure
is the primary consumer.
"""

from __future__ import annotations

from typing import Any


def _pick_atm_iv(contracts: list[dict], spot: float | None) -> dict | None:
    """Return the contract whose strike is closest to spot (with its IV)."""
    if not contracts or spot is None:
        return None
    with_strike = [c for c in contracts if c.get("strike") is not None]
    if not with_strike:
        return None
    closest = min(with_strike, key=lambda c: abs(float(c["strike"]) - float(spot)))
    return {
        "strike": closest.get("strike"),
        "impliedVolatility": closest.get("impliedVolatility"),
        "lastPrice": closest.get("lastPrice"),
        "bid": closest.get("bid"),
        "ask": closest.get("ask"),
        "volume": closest.get("volume"),
        "openInterest": closest.get("openInterest"),
        "contractSymbol": closest.get("contractSymbol"),
    }


def _flatten_chain(contracts: list[dict], side: str) -> list[dict]:
    """Add ``side`` marker (call/put) and normalize a few field aliases."""
    out = []
    for c in contracts or []:
        row = {
            "side": side,
            "contract_symbol": c.get("contractSymbol"),
            "strike": c.get("strike"),
            "last_price": c.get("lastPrice"),
            "bid": c.get("bid"),
            "ask": c.get("ask"),
            "volume": c.get("volume"),
            "open_interest": c.get("openInterest"),
            "implied_volatility": c.get("impliedVolatility"),
            "in_the_money": c.get("inTheMoney"),
            "currency": c.get("currency"),
        }
        out.append(row)
    return out


def extract(raw: dict[str, Any]) -> dict[str, Any]:
    """Transform raw Yahoo options snapshot into structured chain + ATM-IV term.

    Returns a dict with:

    - ``symbol``: underlying ticker
    - ``spot``: underlying spot at capture time (nullable)
    - ``captured_at``: ISO timestamp propagated from raw (nullable)
    - ``chains``: list of {expiration_unix, calls[], puts[]}
    - ``atm_iv_term``: list of {expiration_unix, atm_call, atm_put} with
      the ATM strike + IV per expiry — this is the primary shape the
      Equity Profile §4B widget consumes for the term-structure plot.
    """
    symbol = raw.get("underlying_symbol") or raw.get("symbol") or ""
    spot = raw.get("spot_price")
    captured_at = raw.get("captured_at")
    chains_by_expiry = raw.get("chains_by_expiry", {}) or {}

    chains: list[dict] = []
    atm_iv_term: list[dict] = []

    # Sort expiries chronologically (they're unix epoch as string keys)
    for expiry_key in sorted(chains_by_expiry, key=lambda x: int(x)):
        block = chains_by_expiry[expiry_key] or {}
        expiry_unix = int(block.get("expirationDate") or expiry_key)
        calls_raw = block.get("calls", []) or []
        puts_raw = block.get("puts", []) or []
        chains.append(
            {
                "expiration_unix": expiry_unix,
                "calls": _flatten_chain(calls_raw, "call"),
                "puts": _flatten_chain(puts_raw, "put"),
            }
        )
        atm_iv_term.append(
            {
                "expiration_unix": expiry_unix,
                "atm_call": _pick_atm_iv(calls_raw, spot),
                "atm_put": _pick_atm_iv(puts_raw, spot),
            }
        )

    return {
        "symbol": symbol,
        "spot": spot,
        "captured_at": captured_at,
        "chains": chains,
        "atm_iv_term": atm_iv_term,
    }
