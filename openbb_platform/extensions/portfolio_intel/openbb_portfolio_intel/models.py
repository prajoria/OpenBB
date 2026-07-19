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
