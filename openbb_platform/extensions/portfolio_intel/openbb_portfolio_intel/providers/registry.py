"""Tier registry — the single source of truth for provider fallback order.

Spec §T12.1 defines two chains:

- **Track A (paid)**: fmp_cached -> fmp -> cboe -> sec -> yfinance-snapshot
- **Track B (free)**: cboe -> sec -> yfinance

The registry keys by ``"<endpoint_family>:<track>"`` where ``track`` is
``"A"`` or ``"B"``. An endpoint family is a domain grouping — e.g.
``equity/header``, ``events/calendar`` — several widgets in the same
family typically share the same fallback order.

Kept as a plain module-level dict so it's:

- Trivially inspectable / greppable when we ask "which tiers back
  endpoint X?"
- Read-only at runtime (any mutation is a code change + PR)
- Fast to import (no network / no filesystem)
"""

from __future__ import annotations

from types import MappingProxyType

# ---------------------------------------------------------------------------
# Canonical tier lists
# ---------------------------------------------------------------------------

TRACK_A_DEFAULT: tuple[str, ...] = (
    "fmp_cached",
    "fmp",
    "cboe",
    "sec",
    "yfinance-snapshot",
)
"""Paid track: cache-hot FMP first, then live FMP, then free public data."""

TRACK_B_DEFAULT: tuple[str, ...] = (
    "cboe",
    "sec",
    "yfinance",
)
"""Free track — used when the caller has no paid credentials."""


# Some endpoint families need a specialized order — e.g. SEC filings
# only ever come from SEC. Any override goes here explicitly.

_EQUITY_A: tuple[str, ...] = TRACK_A_DEFAULT
_EQUITY_B: tuple[str, ...] = TRACK_B_DEFAULT

# Filings: fmp_cached serves SEC filings directly (verified live, #1914) —
# prefer it on the paid track, then live fmp, then SEC as the public
# fallback. The free track stays SEC-only.
_FILINGS_A: tuple[str, ...] = ("fmp_cached", "fmp", "sec")
_FILINGS_B: tuple[str, ...] = ("sec",)

# News / sentiment: fmp_cached carries news; fallback to yfinance news.
_NEWS_A: tuple[str, ...] = ("fmp_cached", "fmp", "yfinance-snapshot")
_NEWS_B: tuple[str, ...] = ("yfinance",)

# Options chains: cboe primary in both tracks (yfinance chains lag).
_OPTIONS_A: tuple[str, ...] = ("cboe", "fmp_cached", "fmp")
_OPTIONS_B: tuple[str, ...] = ("cboe", "yfinance")


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

TierList = tuple[str, ...]


def track_key(endpoint_family: str, track: str) -> str:
    """Build a registry lookup key, e.g. ``track_key("equity/header", "A")``.

    Raises ValueError for invalid track values so a typo can't silently
    fall through to a missing key.
    """
    if track not in ("A", "B"):
        raise ValueError(f"track must be 'A' or 'B', got {track!r}")
    return f"{endpoint_family}:{track}"


_TIER_REGISTRY_MUT: dict[str, TierList] = {
    # Equity single-name (default chain in both tracks)
    "equity/header:A": _EQUITY_A,
    "equity/header:B": _EQUITY_B,
    "equity/key-stats:A": _EQUITY_A,
    "equity/key-stats:B": _EQUITY_B,
    "equity/financials:A": _EQUITY_A,
    "equity/financials:B": _EQUITY_B,
    "equity/statements:A": _EQUITY_A,
    "equity/statements:B": _EQUITY_B,
    "equity/price-history:A": _EQUITY_A,
    "equity/price-history:B": _EQUITY_B,
    "equity/technicals:A": _EQUITY_A,
    "equity/technicals:B": _EQUITY_B,
    "equity/competitors:A": _EQUITY_A,
    "equity/competitors:B": _EQUITY_B,
    "equity/complementary:A": _EQUITY_A,
    "equity/complementary:B": _EQUITY_B,
    "equity/peer-multiples:A": _EQUITY_A,
    "equity/peer-multiples:B": _EQUITY_B,
    "equity/analyst-forecasts:A": _EQUITY_A,
    "equity/analyst-forecasts:B": _EQUITY_B,
    "equity/financial-charts:A": _EQUITY_A,
    "equity/financial-charts:B": _EQUITY_B,
    "equity/price-target-history:A": _EQUITY_A,
    "equity/price-target-history:B": _EQUITY_B,
    "equity/price-performance:A": _EQUITY_A,
    "equity/price-performance:B": _EQUITY_B,
    "equity/management-team:A": _EQUITY_A,
    "equity/management-team:B": _EQUITY_B,
    "equity/revenue-geography:A": _EQUITY_A,
    "equity/revenue-geography:B": _EQUITY_B,
    "equity/revenue-business-line:A": _EQUITY_A,
    "equity/revenue-business-line:B": _EQUITY_B,
    # Ownership — fmp_cached / fmp; sec 13F fallback
    "equity/institutional-ownership:A": ("fmp_cached", "fmp", "sec"),
    "equity/institutional-ownership:B": ("sec",),
    "equity/stock-ownership:A": ("fmp_cached", "fmp", "sec"),
    "equity/stock-ownership:B": ("sec",),
    "equity/insider-trading:A": ("fmp_cached", "fmp", "sec"),
    "equity/insider-trading:B": ("sec",),
    # Calendar / events
    "equity/earnings-history:A": _EQUITY_A,
    "equity/earnings-history:B": _EQUITY_B,
    "equity/stock-splits:A": _EQUITY_A,
    "equity/stock-splits:B": _EQUITY_B,
    "equity/dividend-payment:A": _EQUITY_A,
    "equity/dividend-payment:B": _EQUITY_B,
    "equity/company-filings:A": _FILINGS_A,
    "equity/company-filings:B": _FILINGS_B,
    "equity/earnings-transcripts:A": ("fmp_cached", "fmp"),
    "equity/earnings-transcripts:B": (),
    "events/calendar:A": _EQUITY_A,
    "events/calendar:B": _EQUITY_B,
    # News
    "news:A": _NEWS_A,
    "news:B": _NEWS_B,
    # Options
    "options/chains:A": _OPTIONS_A,
    "options/chains:B": _OPTIONS_B,
    # Risk / xray — fmp_cached is the primary; sec is only holdings source
    "xray/sector:A": ("fmp_cached", "fmp", "sec"),
    "xray/sector:B": ("sec",),
    "xray/country:A": ("fmp_cached", "fmp", "sec"),
    "xray/country:B": ("sec",),
    "concentration:A": ("fmp_cached", "fmp"),
    "concentration:B": (),
    "risk/dashboard:A": ("fmp_cached", "fmp", "yfinance-snapshot"),
    "risk/dashboard:B": ("yfinance",),
    "attribution:A": ("fmp_cached", "fmp"),
    "attribution:B": (),
    # Charting / historical
    "charting:A": _EQUITY_A,
    "charting:B": _EQUITY_B,
    # Basket / portfolio look-through
    "lookthrough/top25:A": ("fmp_cached", "fmp", "sec"),
    "lookthrough/top25:B": ("sec",),
    # Risk sub-endpoints
    "risk/vol:A": ("fmp_cached", "fmp", "yfinance-snapshot"),
    "risk/vol:B": ("yfinance",),
    # Smart-money / sentiment / alerts
    "smart-money/ribbon:A": ("fmp_cached", "fmp"),
    "smart-money/ribbon:B": (),
    "sentiment:A": ("fmp_cached", "fmp"),
    "sentiment:B": (),
    "alerts:A": ("fmp_cached", "fmp"),
    "alerts:B": (),
    # Paper trading (all synthesized; chain exists for symmetry with health widget)
    "paper/ticket:A": ("fmp_cached",),
    "paper/ticket:B": (),
    "paper/blotter:A": ("fmp_cached",),
    "paper/blotter:B": (),
    "paper/performance:A": ("fmp_cached",),
    "paper/performance:B": (),
    "paper/perf-kpis:A": ("fmp_cached",),
    "paper/perf-kpis:B": (),
    # What-if diff engine
    "whatif/card:A": ("fmp_cached", "fmp"),
    "whatif/card:B": (),
    # Backtest one-click hand-off
    "backtest/oneclick:A": ("fmp_cached",),
    "backtest/oneclick:B": (),
    # Basket analyst consensus (real basket resolution lives here #1714)
    "equity/basket-analyst-consensus:A": ("fmp_cached", "fmp"),
    "equity/basket-analyst-consensus:B": (),
}

TIER_REGISTRY: MappingProxyType[str, TierList] = MappingProxyType(_TIER_REGISTRY_MUT)
"""Read-only view over the registry — mutations at runtime are a bug."""
