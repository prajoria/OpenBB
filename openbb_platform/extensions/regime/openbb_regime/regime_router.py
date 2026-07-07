"""Placeholder router — the public ``obb.regime.*`` surface ships in Phase B4.

This file exists so ``openbb-regime`` is a valid extension entry-point
(pyproject.toml declares ``regime = openbb_regime.regime_router:router``)
even before B4 lands. Consumers wanting the detector today should
import :func:`openbb_regime.detect_market_regime` directly.
"""

from __future__ import annotations

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(
    prefix="",
    description="Shared market-regime detector (Analysis + techtrade consumers).",
)


@router.command(
    methods=["GET"],
    include_in_schema=False,
    examples=[],
)
def about() -> OBBject:
    """Metadata endpoint. The typed ``detect`` command ships in B4."""
    return OBBject(
        results={
            "name": "openbb-regime",
            "purpose": "Shared MarketRegime detector for Analysis + techtrade",
            "note": "obb.regime.detect() ships in Phase B4 (bd-0h2.16)",
        }
    )
