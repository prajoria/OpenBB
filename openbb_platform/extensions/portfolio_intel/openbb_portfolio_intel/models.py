"""Public models for the portfolio_intel extension.

Any Pydantic/Data class that appears as a route input or `OBBject[X]`
return type MUST live in this module (or another top-level package
module), NOT inside a router sub-module. OpenBB's static-package
generator only imports models it can resolve at the package's top
level; classes defined inside `routers/xray_router.py` etc. leak into
generated code as unimported identifiers (verified live during #541
phase-6 verify).

Pattern mirrors `openbb_backtest.models`.
"""

from __future__ import annotations

from decimal import Decimal

from openbb_core.provider.abstract.data import Data
from pydantic import BaseModel, Field


class BasketPosition(Data):
    """One row of an input portfolio basket (#541)."""

    symbol: str = Field(description="Ticker (equity or ETF).")
    weight: Decimal = Field(description="Fraction of total portfolio (0 < w <= 1).")


class ConcentrationSummary(BaseModel):
    """Concentration metrics computed on post-unwrap effective weights (#541)."""

    hhi: float = Field(
        description="Herfindahl-Hirschman index on effective weights [0, 1]."
    )
    effective_n: float = Field(
        description="Reciprocal HHI — effective number of holdings."
    )
    top1: float = Field(description="Largest single effective exposure.")
    top5: float = Field(description="Sum of top-5 effective exposures.")
    top10: float = Field(description="Sum of top-10 effective exposures.")


class XRayLookThroughResult(BaseModel):
    """Nested response shape for the ``/xray/look_through`` route (#541)."""

    effective: dict[str, float] = Field(
        description="Symbol -> effective weight after unwrap."
    )
    sector_rollup: dict[str, float] = Field(
        description="Sector -> summed effective weight."
    )
    country_rollup: dict[str, float] = Field(
        description="Country -> summed effective weight."
    )
    concentration: ConcentrationSummary
    unresolved: list[str] = Field(
        description=(
            "Symbols that were expected to be ETFs but returned no "
            "holdings (fetch error or unknown ETF); kept at face weight."
        )
    )
    depth_reached: int = Field(
        description="Deepest recursion level hit during unwrap (0 = no unwrap)."
    )
    warnings: list[str] = Field(default_factory=list)


class RiskMetricsResult(BaseModel):
    """/risk/metrics response — parametric portfolio-level risk metrics (#528).

    All metrics use the parametric (Gaussian) VaR/CVaR variant — the only
    one that admits a clean Euler component decomposition (see #558 What-If
    §9.6). Callers who need historical VaR should call
    :func:`openbb_portfolio_intel.analytics.risk.value_at_risk` directly
    with a return series.
    """

    volatility: float | None = Field(
        default=None,
        description=(
            "Portfolio std-dev (per-period, same time-scale as input returns). "
            "None when the basket has any symbol missing from returns_source."
        ),
    )
    var_95: float | None = Field(
        default=None,
        description=(
            "Parametric VaR at 95% confidence (loss magnitude, positive). "
            "Computed as z * volatility."
        ),
    )
    cvar_95: float | None = Field(
        default=None,
        description=(
            "Parametric CVaR at 95% (expected shortfall, positive). "
            "Computed as phi(z) / (1 - Phi(z)) * volatility."
        ),
    )
    beta: float | None = Field(
        default=None,
        description="Portfolio beta vs benchmark_returns (cov / benchmark var).",
    )
    warnings: list[str] = Field(default_factory=list)


class CalendarEventItem(BaseModel):
    """One event in the merged /events/timeline (#542).

    ``date`` is serialized as an ISO ``YYYY-MM-DD`` string (not
    ``datetime.date``) to keep the response boundary trivially
    JSON-serializable — matches the /xray + /risk generator-quirk
    posture (extension-local types have to stay simple).
    """

    symbol: str = Field(description="Ticker the event pertains to.")
    date: str = Field(description="ISO date (YYYY-MM-DD) of the event.")
    event_type: str = Field(description="One of: earnings | dividend | split | ipo.")
    source: str = Field(description="Provider tag (e.g. 'fmp_cached').")
    details: dict = Field(
        default_factory=dict,
        description="Optional per-event-type payload (EPS estimate, div amount, etc.).",
    )


class EventTimelineResult(BaseModel):
    """Nested response shape for the /events/timeline route (#542)."""

    timeline: list[CalendarEventItem] = Field(
        description="Chronologically-sorted event list, portfolio-scoped."
    )
    by_symbol: dict[str, list[CalendarEventItem]] = Field(
        description="Same events grouped by symbol for per-holding widgets."
    )
    warnings: list[str] = Field(default_factory=list)
