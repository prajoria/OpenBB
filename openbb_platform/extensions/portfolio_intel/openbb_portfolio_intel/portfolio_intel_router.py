"""Top-level router for the portfolio_intel extension.

Assembles the public ``obb.portfolio_intel.*`` surface. Sub-routers are
attached lazily inside :func:`_include_subrouters` so that a missing
optional sub-router (still under construction in P1/P2/P3) never breaks
extension import. This mirrors the pattern used by ``openbb_backtest``.

.. note::
   The public namespace is ``obb.portfolio_intel.*`` (underscore, matching
   the ``openbb_core_extension`` entry-point key), NOT ``obb.portfolio.intel.*``.
   OpenBB's plugin loader does not dot-split entry-point keys — see the
   sibling ``openbb-backtest`` extension whose entry-point ``backtest`` maps
   to ``obb.backtest.*``. Nesting under ``obb.portfolio.*`` would collide
   with the ``openbb-portfolio`` / ``openbb-portfolio-custom`` namespace
   and was explicitly rejected during PR #466 review.

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


# Modules whose ImportError is expected to be swallowed silently (they are
# planned sub-routers, not yet implemented). Every other ImportError — e.g.
# a typo inside one of these modules once it exists — surfaces loudly so
# CI catches it, addressing PR #466 review finding 2 (blanket
# ``except ImportError`` was hiding real bugs).
_PLANNED_SUBROUTERS: tuple[str, ...] = (
    "openbb_portfolio_intel.routers.xray_router",
    "openbb_portfolio_intel.routers.events_router",
    "openbb_portfolio_intel.routers.smart_money_router",
    "openbb_portfolio_intel.routers.risk_router",
    "openbb_portfolio_intel.routers.whatif_router",
    "openbb_portfolio_intel.routers.paper_router",
    "openbb_portfolio_intel.routers.alerts_router",
)


def _include_subrouters() -> None:
    """Lazily attach sub-routers as they are implemented (P1 → P3).

    A ``ModuleNotFoundError`` whose ``.name`` matches the expected sub-router
    path is caught silently — the sub-router simply hasn't landed yet.
    Any other ``ModuleNotFoundError`` (from a typo inside a real sub-router
    dependency) is re-raised so CI fails visibly instead of silently
    dropping the sub-router from the public surface.
    """
    for module_path in _PLANNED_SUBROUTERS:
        try:
            module = __import__(module_path, fromlist=["router"])
        except ModuleNotFoundError as exc:
            # Only swallow if the missing module is THIS sub-router itself,
            # not a transitive dependency it tried to import.
            if exc.name == module_path:
                continue
            raise
        sub = getattr(module, "router", None)
        if sub is not None:
            router.include_router(sub)


@router.command(methods=["GET"])
def about() -> OBBject[ExtensionAbout]:
    """Return the extension name, version, and scope.

    Health-check command used by the M0 gate demo and by every derived
    analytic to stamp its response envelope with the extension version
    that produced it (per PRD §4 Guiding Principle 3 — deterministic
    outputs).

    Matches the ``@router.command(methods=["GET"])`` signature of
    ``openbb_backtest.backtest_router.about`` — passing ``model=<str>``
    triggers OpenBB's standard-models registry lookup, which fails for
    extension-local models (PR #466 review finding 4).
    """
    return OBBject(
        results=ExtensionAbout(
            name="portfolio_intel",
            version=__version__,
            scope="portfolio-level intelligence over portfolio_basket",
        )
    )


_include_subrouters()
