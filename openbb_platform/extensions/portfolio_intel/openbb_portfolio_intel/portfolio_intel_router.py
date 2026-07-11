"""Top-level router for the portfolio_intel extension.

Assembles the public ``obb.portfolio.intel.*`` surface. Sub-routers are
attached lazily inside :func:`_include_subrouters` so that a missing
optional sub-router (still under construction in P1/P2/P3) never breaks
extension import. This mirrors the pattern used by ``openbb_backtest``.

In M0 the only command is :func:`about` — a health-check that returns the
extension's version and name. Every widget that keys off
``portfolio_intel_cache`` (PRD §10.2) reads the version from here.

See ``docs/Specs/Portfolio-Intelligence-Engine-PRD.md`` §9 for the full
command inventory (P1+) and §8 for the layered architecture.
"""

from __future__ import annotations

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import BaseModel

from openbb_portfolio_intel import __version__

router = Router(prefix="", description="Portfolio Intelligence engine.")


class ExtensionAbout(BaseModel):
    """Minimal identity payload returned by :func:`about`."""

    name: str
    version: str
    scope: str


def _include_subrouters() -> None:
    """Lazily attach sub-routers as they are implemented (P1 → P3).

    Each ``include_router`` is added once its module exists; missing
    optional sub-routers are skipped so the extension imports cleanly
    during incremental development. This matches ``openbb_backtest``'s
    convention exactly so cross-extension review stays trivial.
    """
    for module_path, attr in (
        ("openbb_portfolio_intel.routers.xray_router", "router"),
        ("openbb_portfolio_intel.routers.events_router", "router"),
        ("openbb_portfolio_intel.routers.smart_money_router", "router"),
        ("openbb_portfolio_intel.routers.risk_router", "router"),
        ("openbb_portfolio_intel.routers.whatif_router", "router"),
        ("openbb_portfolio_intel.routers.paper_router", "router"),
        ("openbb_portfolio_intel.routers.alerts_router", "router"),
    ):
        try:
            module = __import__(module_path, fromlist=[attr])
        except ImportError:
            # Not yet implemented — expected during P0/P1 incremental land.
            continue
        sub = getattr(module, attr, None)
        if sub is not None:
            router.include_router(sub)


@router.command(
    model="ExtensionAbout",
    examples=[
        # Populated with APIEx / PythonEx once openbb_core.app.example_generators
        # is available in this extension's test env; kept empty in M0 to
        # avoid import-order coupling on the scaffold.
    ],
)
def about() -> OBBject[ExtensionAbout]:
    """Return the extension name, version, and scope.

    Health-check command used by the M0 gate demo and by every derived
    analytic to stamp its response envelope with the extension version
    that produced it (per PRD §4 Guiding Principle 3 — deterministic
    outputs).
    """
    return OBBject(
        results=ExtensionAbout(
            name="portfolio_intel",
            version=__version__,
            scope="portfolio-level intelligence over portfolio_basket",
        )
    )


_include_subrouters()
