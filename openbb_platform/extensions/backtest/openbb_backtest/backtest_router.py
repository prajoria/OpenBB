"""Top-level backtest router.

Assembles the public ``obb.backtest.*`` surface. The four sub-routers -- engine
(``run`` / ``sweep`` / ``reconcile``), factor (``pipeline`` / ``factor_eval``),
validation (``validate`` / ``tearsheet``) and bundle (``bundle.ingest`` /
``bundle.list``) -- are attached at import inside :func:`_include_subrouters`;
each keeps its heavy numeric/IO dependencies out of ``import openbb`` time by
importing them lazily inside the command bodies. This module also exposes the
``about`` metadata command.

See ``docs/designs/backtest-design/01-scaffolding.md`` and ``09-api-surface.md``.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import BaseModel

router = Router(prefix="", description="Backtesting engine.")


def _include_subrouters() -> None:
    """Lazily attach sub-routers as their components are implemented.

    Each ``include_router`` is added once its module exists; missing optional
    sub-routers are skipped so the extension imports cleanly during incremental
    development.
    """
    for module_path, attr in (
        ("openbb_backtest.routers.run_router", "router"),
        ("openbb_backtest.routers.factor_router", "router"),
        ("openbb_backtest.routers.validate_router", "router"),
        ("openbb_backtest.routers.bundle_router", "router"),
    ):
        try:
            module = __import__(module_path, fromlist=[attr])
        except ImportError:
            continue
        router.include_router(getattr(module, attr))


_include_subrouters()


class BacktestAbout(BaseModel):
    """Extension metadata."""

    extension_name: str
    extension_version: str


@router.command(
    methods=["GET"],
    examples=[APIEx(parameters={})],
)
def about() -> OBBject[BacktestAbout]:
    """Return backtest extension metadata."""
    try:
        ext_version = version("openbb-backtest")
    except PackageNotFoundError:
        ext_version = "0.0.0"
    return OBBject(
        results=BacktestAbout(
            extension_name="backtest",
            extension_version=ext_version,
        )
    )
