"""Sentiment rollup — weighted analyst rating + PT upside + upgrades (#570).

PRD 9.9. Aggregates per-holding analyst sentiment into a portfolio-wide
view for the Sentiment widget. Pure functions, no I/O — the route layer
(portfolio_intel_router) feeds provider payloads in and this module
computes the reduction.

## Inputs

Callers construct :class:`AnalystSnapshot` per holding from three
provider payloads:

- ``obb.equity.estimates.consensus`` → ``rating`` (5-point buckets:
  Strong Buy=5, Buy=4, Hold=3, Sell=2, Strong Sell=1) and ``analyst_count``
- ``obb.equity.estimates.price_target`` → ``pt_median`` (median target)
- ``obb.equity.calendar.dividend`` / news → ``recent_updowngrades``
  counts over a caller-supplied lookback window (30/90d).

## Outputs

- :class:`HoldingSentiment` — per-holding scored view (rating on 1-5,
  upside percentage, updowngrade net = upgrades - downgrades).
- :class:`PortfolioSentiment` — weight-weighted rollup (rating,
  upside, net updowngrades) with a **coverage_pct** field: fraction
  of portfolio weight for which we had a non-null analyst payload.

The **coverage_pct** field is load-bearing: it prevents the R7.3
"loud empty" failure mode where 90% of the portfolio has no analyst
coverage and the rollup silently reports a rating from the 10% that
did. Downstream widgets MUST render coverage_pct when < 0.7 so the
user knows the rating is thin.

## Weighting

Two weighting strategies:

- ``"portfolio"`` (default): each holding contributes proportional to
  its portfolio weight — the natural weighting for "how does my book
  look."
- ``"analyst_count"``: each holding also multiplied by its analyst
  count, so a stock with 30 analysts covering it counts more than one
  with 3. Better for "aggregate market conviction."

## Design notes

- ``None`` fields (missing rating, missing target) exclude that holding
  from the specific aggregate (not the whole score) — losing a target
  doesn't remove the rating contribution.
- The upside calculation guards against zero current-price via an
  explicit skip; NaN never propagates. See R7.3.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalystSnapshot:
    """Per-holding analyst payload — one snapshot per symbol.

    Fields are all ``| None`` because analyst coverage is patchy;
    small caps and micro-caps often have zero analyst coverage. The
    reducer handles missing fields explicitly.

    Attributes
    ----------
    symbol : str
    weight : Decimal
        Portfolio weight of this holding (0-1 fractional).
    price : Decimal | None
        Current price. Required to compute upside.
    rating : Decimal | None
        Consensus rating on 1-5 scale (5=Strong Buy, 3=Hold, 1=Strong
        Sell). Providers use different scales; caller must normalize.
    analyst_count : int
        Number of analysts backing the rating. 0 means no coverage
        (rating should be ``None`` in that case).
    pt_median : Decimal | None
        Median analyst price target. Compared against ``price`` for
        upside.
    upgrades_recent : int
        Count of upgrades within the caller's lookback window.
    downgrades_recent : int
        Count of downgrades within the caller's lookback window.
    """

    symbol: str
    weight: Decimal
    price: Decimal | None = None
    rating: Decimal | None = None
    analyst_count: int = 0
    pt_median: Decimal | None = None
    upgrades_recent: int = 0
    downgrades_recent: int = 0


# ---------------------------------------------------------------------------
# Per-holding scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldingSentiment:
    """Scored view of one holding's analyst sentiment.

    ``upside_pct`` is ``(pt_median - price) / price`` expressed as a
    fraction (0.15 = 15% upside). ``None`` when either price or target
    is missing / non-positive.
    """

    symbol: str
    weight: Decimal
    rating: Decimal | None
    analyst_count: int
    upside_pct: Decimal | None
    net_updowngrades: int  # upgrades_recent - downgrades_recent


def score_holding(snap: AnalystSnapshot) -> HoldingSentiment:
    """Compute per-holding scored view.

    Upside guard (R7.3): if ``price`` is missing OR ``<= 0``, upside is
    ``None`` rather than propagating a division error or NaN. Same for
    missing ``pt_median``.
    """
    upside: Decimal | None = None
    if snap.price is not None and snap.pt_median is not None and snap.price > 0:
        upside = (snap.pt_median - snap.price) / snap.price
    return HoldingSentiment(
        symbol=snap.symbol,
        weight=snap.weight,
        rating=snap.rating,
        analyst_count=snap.analyst_count,
        upside_pct=upside,
        net_updowngrades=snap.upgrades_recent - snap.downgrades_recent,
    )


# ---------------------------------------------------------------------------
# Portfolio rollup
# ---------------------------------------------------------------------------


WeightingScheme = Literal["portfolio", "analyst_count"]


@dataclass(frozen=True)
class PortfolioSentiment:
    """Portfolio-wide rollup of holding sentiment.

    ``coverage_pct`` is the fraction of portfolio weight with a
    non-``None`` rating. Downstream widgets MUST surface this when
    below the reporting threshold (default 0.7) — a rollup rating on
    30% coverage is not the same as one on 100% coverage.
    """

    rating: Decimal | None
    upside_pct: Decimal | None
    net_updowngrades: int
    coverage_pct: Decimal
    weighting: WeightingScheme
    holding_count: int


def rollup_sentiment(
    holdings: Iterable[HoldingSentiment],
    *,
    weighting: WeightingScheme = "portfolio",
) -> PortfolioSentiment:
    """Weighted rollup across holdings.

    Parameters
    ----------
    holdings : Iterable[HoldingSentiment]
        Output of :func:`score_holding` per position.
    weighting : {"portfolio", "analyst_count"}
        - ``"portfolio"``: contribution = ``weight``
        - ``"analyst_count"``: contribution = ``weight * analyst_count``

    Notes
    -----
    - A holding with ``rating=None`` contributes to net updowngrades
      (they're a raw count, not a rating) but not to the rating rollup.
    - A holding with ``upside_pct=None`` similarly excluded from upside.
    - Coverage is computed on rating specifically — it's the primary
      signal for "is this rollup meaningful."
    - Empty input returns coverage_pct=0 and rating=None (loud empty
      by way of caller-visible coverage=0).
    """
    holdings = list(holdings)
    if not holdings:
        return PortfolioSentiment(
            rating=None,
            upside_pct=None,
            net_updowngrades=0,
            coverage_pct=Decimal("0"),
            weighting=weighting,
            holding_count=0,
        )

    def _contrib(h: HoldingSentiment) -> Decimal:
        if weighting == "analyst_count":
            return h.weight * Decimal(h.analyst_count)
        return h.weight

    # Rating rollup — weighted by _contrib, only rated holdings included.
    rating_num = Decimal("0")
    rating_denom = Decimal("0")
    for h in holdings:
        if h.rating is None:
            continue
        c = _contrib(h)
        rating_num += h.rating * c
        rating_denom += c
    rating = (rating_num / rating_denom) if rating_denom > 0 else None

    # Upside rollup — same scheme, only holdings with upside included.
    upside_num = Decimal("0")
    upside_denom = Decimal("0")
    for h in holdings:
        if h.upside_pct is None:
            continue
        c = _contrib(h)
        upside_num += h.upside_pct * c
        upside_denom += c
    upside = (upside_num / upside_denom) if upside_denom > 0 else None

    # Net updowngrades — raw sum, no weighting (it's a count).
    net = sum(h.net_updowngrades for h in holdings)

    # Coverage — fraction of PORTFOLIO weight (always the "portfolio"
    # scheme regardless of rollup weighting) with a rating. Otherwise
    # switching to analyst_count would silently inflate coverage_pct.
    total_weight = sum((h.weight for h in holdings), Decimal("0"))
    covered_weight = sum(
        (h.weight for h in holdings if h.rating is not None), Decimal("0")
    )
    coverage = (covered_weight / total_weight) if total_weight > 0 else Decimal("0")

    return PortfolioSentiment(
        rating=rating,
        upside_pct=upside,
        net_updowngrades=net,
        coverage_pct=coverage,
        weighting=weighting,
        holding_count=len(holdings),
    )


def score_and_rollup(
    snapshots: Iterable[AnalystSnapshot],
    *,
    weighting: WeightingScheme = "portfolio",
) -> tuple[list[HoldingSentiment], PortfolioSentiment]:
    """Convenience: score every snapshot then roll up.

    Returns the per-holding list too so the route can surface both
    "portfolio view" and "which holdings dragged it" in one call.
    """
    scored = [score_holding(s) for s in snapshots]
    return scored, rollup_sentiment(scored, weighting=weighting)


__all__ = [
    "AnalystSnapshot",
    "HoldingSentiment",
    "PortfolioSentiment",
    "WeightingScheme",
    "rollup_sentiment",
    "score_and_rollup",
    "score_holding",
]
