"""News + sentiment routes (#572).

Two commands:

- ``obb.portfolio_intel.news.timeline(basket, severity, days_back, provider)``
  Merged news + press-release + 8-K stream filtered to basket symbols,
  sorted newest-first, filtered by minimum severity.
- ``obb.portfolio_intel.sentiment.rollup(basket, weighting, provider)``
  Weighted analyst rating + PT upside + net updowngrades across the
  basket, plus per-holding drill-down and load-bearing ``coverage_pct``.

Composes:
- ``analytics.sentiment.score_and_rollup`` — pure reducer (#570).
- ``obb.equity.estimates.consensus`` + ``.price_target`` — per-holding
  analyst snapshots.
- ``obb.equity.price.quote`` — current price for upside math.
- ``obb.news.company`` — news items.
- ``obb.equity.fundamental.filings`` — 8-K feed.

Design mirrors the P1/P2 routers (xray, events, smart_money, risk):
- Public models in ``openbb_portfolio_intel.models``.
- ``list[dict]`` basket input, ``OBBject`` return.
- Provider fetch behind a seam so unit tests never hit the network.
"""

from __future__ import annotations

# pylint: disable=unused-argument
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_portfolio_intel.analytics.sentiment import (
    AnalystSnapshot,
    score_and_rollup,
)
from openbb_portfolio_intel.models import (
    BasketPosition,
    NewsItem,
    NewsTimelineResult,
    SentimentHoldingItem,
    SentimentRollupResult,
)
from openbb_portfolio_intel.routers.xray_router import _validate_basket

logger = logging.getLogger(__name__)

news_router = Router(
    prefix="/news",
    description=(
        "Merged news + press-release + 8-K stream, portfolio-scoped, "
        "filterable by severity."
    ),
)
sentiment_router = Router(
    prefix="/sentiment",
    description=(
        "Weighted analyst sentiment rollup — rating + PT upside + "
        "recent updowngrades — with per-holding drill-down."
    ),
)


# ---------------------------------------------------------------------------
# Fetch seams (test-patched)
# ---------------------------------------------------------------------------


_SEVERITY_RANK = {"critical": 3, "warning": 2, "info": 1}


def _fetch_news_company(symbol: str, *, provider: str | None):
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return obb.news.company(symbol=symbol, provider=provider)


def _now() -> datetime:
    """Wall-clock 'now' seam — monkeypatch in tests to pin the reference time.

    Fixes #1716: tests that stub news/filing rows with a fixed ``NOW`` need
    to pin ``now`` too or the router's real-clock ``days_back`` window
    drops them as stale. Keeping it as a module-level function makes the
    injection uniform with ``_fetch_news_company`` / ``_fetch_filings``.
    """
    return datetime.now(tz=timezone.utc)


def _fetch_filings(symbol: str, *, provider: str | None):
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return obb.equity.fundamental.filings(symbol=symbol, provider=provider)


def _fetch_consensus(symbol: str, *, provider: str | None):
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return obb.equity.estimates.consensus(symbol=symbol, provider=provider)


def _fetch_price_target(symbol: str, *, provider: str | None):
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return obb.equity.estimates.price_target(symbol=symbol, provider=provider)


def _fetch_quote(symbol: str, *, provider: str | None):
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return obb.equity.price.quote(symbol=symbol, provider=provider)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rows(response: Any) -> list:
    return getattr(response, "results", response) or []


def _positions_from_basket(basket: list[dict]) -> list[BasketPosition]:
    positions = [
        BasketPosition(symbol=str(r["symbol"]), weight=Decimal(str(r["weight"])))
        for r in basket
    ]
    _validate_basket(positions)
    return positions


def _iso(v: Any) -> str:
    """Best-effort ISO 8601 stringification."""
    if isinstance(v, datetime):
        return v.isoformat()
    if v is None:
        return ""
    return str(v)


# ---------------------------------------------------------------------------
# #572 /news/timeline
# ---------------------------------------------------------------------------


@news_router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Merged news + 8-K stream for a two-symbol basket.",
            code=[
                "obb.portfolio_intel.news.timeline("
                'basket=[{"symbol":"AAPL","weight":0.5},{"symbol":"MSFT","weight":0.5}],'
                'severity="info", days_back=7)',
            ],
        )
    ],
)
def timeline(
    basket: list[dict],
    severity: str = "info",
    days_back: int = 7,
    provider: str | None = "fmp_cached",
) -> OBBject[NewsTimelineResult]:
    """News + press-release + 8-K stream for basket, filtered by severity.

    Parameters
    ----------
    basket : list[dict]
        Portfolio basket as list of {"symbol": str, "weight": number}.
        Weight is required (validated as a real basket) but ignored for
        news filtering — every basket symbol contributes equally.
    severity : str
        Minimum severity: "info" (all), "warning", "critical".
    days_back : int
        Lookback window in days from now.
    provider : str | None
        Provider tag passed through to underlying obb calls.
    """
    positions = _positions_from_basket(basket)
    sev_floor = _SEVERITY_RANK.get(severity.lower(), 1)
    warnings: list[str] = []

    now = _now()
    since = now - timedelta(days=days_back)
    items: list[NewsItem] = []

    for pos in positions:
        # --- news items --------------------------------------------------
        try:
            news_rows = _rows(_fetch_news_company(pos.symbol, provider=provider))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"news fetch failed for {pos.symbol}: {exc}")
            news_rows = []
        for r in news_rows:
            published = getattr(r, "date", None) or getattr(r, "published_at", None)
            if isinstance(published, datetime):
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published < since:
                    continue
            title = getattr(r, "title", "") or getattr(r, "headline", "")
            source = "press_release" if "press" in str(title).lower() else "news"
            item_sev = "info"
            if _SEVERITY_RANK[item_sev] < sev_floor:
                continue
            items.append(
                NewsItem(
                    symbol=pos.symbol,
                    published_at=_iso(published),
                    source=source,
                    severity=item_sev,
                    title=str(title),
                    url=str(getattr(r, "url", "") or ""),
                )
            )
        # --- 8-K filings -------------------------------------------------
        try:
            filing_rows = _rows(_fetch_filings(pos.symbol, provider=provider))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"filings fetch failed for {pos.symbol}: {exc}")
            filing_rows = []
        for r in filing_rows:
            form_type = str(
                getattr(r, "form_type", None) or getattr(r, "type", "") or ""
            )
            if "8-K" not in form_type:
                continue
            filed = getattr(r, "filing_date", None) or getattr(r, "date", None)
            if isinstance(filed, datetime):
                if filed.tzinfo is None:
                    filed = filed.replace(tzinfo=timezone.utc)
                if filed < since:
                    continue
            item_sev = "warning"
            if _SEVERITY_RANK[item_sev] < sev_floor:
                continue
            items.append(
                NewsItem(
                    symbol=pos.symbol,
                    published_at=_iso(filed),
                    source="8k",
                    severity=item_sev,
                    title=f"{pos.symbol} 8-K",
                    url=str(getattr(r, "url", "") or ""),
                )
            )

    # Newest first, then severity DESC as tiebreak for same timestamp.
    items.sort(
        key=lambda i: (i.published_at, _SEVERITY_RANK.get(i.severity, 1)),
        reverse=True,
    )
    if not items:
        warnings.append("no news/filings items matched — check severity or days_back")

    return OBBject(results=NewsTimelineResult(items=items, warnings=warnings))


# ---------------------------------------------------------------------------
# #572 /sentiment/rollup
# ---------------------------------------------------------------------------


def _snapshot_for(
    symbol: str, weight: Decimal, *, provider: str | None
) -> AnalystSnapshot:
    """Compose an AnalystSnapshot from three provider fetches, all optional."""
    price: Decimal | None = None
    pt_median: Decimal | None = None
    rating: Decimal | None = None
    analyst_count = 0
    try:
        q = _rows(_fetch_quote(symbol, provider=provider))
        if q:
            last = getattr(q[0], "last_price", None) or getattr(q[0], "price", None)
            if last is not None:
                price = Decimal(str(last))
    except Exception:  # noqa: BLE001
        pass
    try:
        pt = _rows(_fetch_price_target(symbol, provider=provider))
        # Provider returns per-analyst rows; use their median target as a
        # cheap central estimate. When only one row is returned this is
        # that row's target.
        if pt:
            targets = [
                Decimal(
                    str(getattr(r, "price_target", None) or getattr(r, "target", 0))
                )
                for r in pt
                if (getattr(r, "price_target", None) or getattr(r, "target", None))
            ]
            if targets:
                targets.sort()
                mid = len(targets) // 2
                pt_median = (
                    targets[mid]
                    if len(targets) % 2 == 1
                    else (targets[mid - 1] + targets[mid]) / Decimal(2)
                )
    except Exception:  # noqa: BLE001
        pass
    try:
        cons = _rows(_fetch_consensus(symbol, provider=provider))
        if cons:
            row = cons[0]
            r_num = getattr(row, "consensus_rating", None) or getattr(
                row, "rating", None
            )
            if r_num is not None:
                rating = Decimal(str(r_num))
            n = getattr(row, "analyst_count", None) or getattr(
                row, "number_of_analysts", 0
            )
            analyst_count = int(n) if n else 0
    except Exception:  # noqa: BLE001
        pass
    return AnalystSnapshot(
        symbol=symbol,
        weight=weight,
        price=price,
        pt_median=pt_median,
        rating=rating,
        analyst_count=analyst_count,
    )


@sentiment_router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Portfolio-wide sentiment rollup with per-holding breakdown.",
            code=[
                "obb.portfolio_intel.sentiment.rollup("
                'basket=[{"symbol":"AAPL","weight":0.5},{"symbol":"MSFT","weight":0.5}])',
            ],
        )
    ],
)
def rollup(
    basket: list[dict],
    weighting: str = "portfolio",
    provider: str | None = "fmp_cached",
) -> OBBject[SentimentRollupResult]:
    """Weight-weighted analyst sentiment across the basket.

    ``weighting`` is ``"portfolio"`` (default, weight only) or
    ``"analyst_count"`` (weight * analyst count — biases toward
    heavily-followed names).

    Downstream widgets MUST render ``coverage_pct`` when < 0.7 so the
    user knows the rating rollup is thin. See :func:`analytics.sentiment.rollup_sentiment`.
    """
    if weighting not in ("portfolio", "analyst_count"):
        raise ValueError(
            f"weighting must be 'portfolio' or 'analyst_count', got {weighting!r}"
        )
    positions = _positions_from_basket(basket)

    snaps: list[AnalystSnapshot] = []
    warnings: list[str] = []
    for pos in positions:
        try:
            snaps.append(_snapshot_for(pos.symbol, pos.weight, provider=provider))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"snapshot failed for {pos.symbol}: {exc}")
            snaps.append(AnalystSnapshot(symbol=pos.symbol, weight=pos.weight))

    scored, roll = score_and_rollup(snaps, weighting=weighting)  # type: ignore[arg-type]

    holdings_items = [
        SentimentHoldingItem(
            symbol=h.symbol,
            weight=float(h.weight),
            rating=(float(h.rating) if h.rating is not None else None),
            analyst_count=h.analyst_count,
            upside_pct=(float(h.upside_pct) if h.upside_pct is not None else None),
            net_updowngrades=h.net_updowngrades,
        )
        for h in scored
    ]
    if float(roll.coverage_pct) < 0.7:
        warnings.append(
            f"coverage_pct={float(roll.coverage_pct):.2f} < 0.7 — rating rollup is thin"
        )

    return OBBject(
        results=SentimentRollupResult(
            rating=(float(roll.rating) if roll.rating is not None else None),
            upside_pct=(
                float(roll.upside_pct) if roll.upside_pct is not None else None
            ),
            net_updowngrades=roll.net_updowngrades,
            coverage_pct=float(roll.coverage_pct),
            weighting=roll.weighting,
            holding_count=roll.holding_count,
            holdings=holdings_items,
            warnings=warnings,
        )
    )


# Expose the two independent routers under a single module-level `router`
# so the auto-loader picks them both up. We merge by including one into
# the other under the sub-prefix.
router = Router(prefix="", description="News + sentiment routes.")
router.include_router(news_router)
router.include_router(sentiment_router)
