"""Top-level techtrade router.

Assembles the public ``obb.techtrade.*`` surface. Sub-routers (segments/movers,
signals, plan/scan/orders, simulate, export, validate) are attached lazily inside
:func:`_include_subrouters` as each is implemented per the PRD roadmap (§18); a
missing optional sub-router is skipped so the extension imports cleanly during
incremental development.

The ``about`` command returns a bare ``OBBject`` (no parametrized model) so the
static package builder renders a valid, importable return annotation — see
``docs/superpowers/plans/2026-06-13-techtrade-scaffold.md`` (Critical Design
Constraint) and ``package_builder.build_func_returns``.

See PRD §9.1 (layout) and §9.2 (command surface).
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(
    prefix="", description="Segment-aware technical-indicator trading engine."
)


def _include_subrouters() -> None:
    """Lazily attach sub-routers as their components are implemented.

    Each entry is attempted once its module exists; missing optional sub-routers
    are skipped so the extension imports cleanly during incremental development
    (PRD roadmap §18: P1 screener, P3 signals, P4 plan/orders, P5 export, ...).
    """
    for module_path, attr in (
        ("openbb_techtrade.engine.screener_router", "router"),
        ("openbb_techtrade.engine.signals_router", "router"),
        ("openbb_techtrade.engine.plan_router", "router"),
        ("openbb_techtrade.reporting.export_router", "router"),
        ("openbb_techtrade.validation.validate_router", "router"),
        ("openbb_techtrade.tuning.tune_router", "router"),  # NEW (#83 P7)
    ):
        try:
            module = import_module(module_path)
        except ImportError:
            continue
        router.include_router(getattr(module, attr))


_include_subrouters()


@router.command(
    methods=["GET"],
    examples=[APIEx(parameters={})],
)
def about() -> OBBject:
    """Return techtrade extension metadata.

    Returns
    -------
    OBBject
        An OBBject whose ``results`` is a dict of extension name + version.
    """
    try:
        ext_version = version("openbb-techtrade")
    except PackageNotFoundError:
        ext_version = "0.0.0"
    return OBBject(
        results={"extension_name": "techtrade", "extension_version": ext_version}
    )
