"""Top-level fmp_trading router.

Assembles the public ``obb.fmp_trading.*`` surface. Sub-routers (session, snapshot,
data, alert, session_state, report) are attached lazily inside
:func:`_include_subrouters` as each is implemented per PRD §10 (P2 tick loop, P3
agent turns, P4 alerts, P5 report). Missing sub-routers are skipped so the extension
imports cleanly during incremental development.

The ``doctor`` command returns a bare ``OBBject`` (no parametrized model) so the
static package builder renders a valid, importable return annotation — see the
Critical Design Constraint in the Phase 1 plan and ``package_builder.build_func_returns``.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_fmp_trading.core.doctor import run_doctor

router = Router(
    prefix="",
    description="Intraday day-trading automation on fmp_cached (deterministic core).",
)


def _include_subrouters() -> None:
    for module_path, attr in (
        ("openbb_fmp_trading.routers.session_router", "router"),
        ("openbb_fmp_trading.routers.snapshot_router", "router"),
        ("openbb_fmp_trading.routers.data_router", "router"),
        ("openbb_fmp_trading.routers.alert_router", "router"),
        ("openbb_fmp_trading.routers.session_state_router", "router"),
        ("openbb_fmp_trading.routers.report_router", "router"),
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
def doctor() -> OBBject:
    """Return an fmp_trading environment health report.

    Checks: FMP credentials, MySQL cache reachability, exchange_calendars data,
    techtrade installation + version, [agent] / [xlsxwriter] / [validation]
    extras, and remaining monthly bandwidth budget.

    Return annotation is bare ``OBBject`` per the Critical Design Constraint
    (see the Phase 1 plan header). The ``HealthReport`` model is instantiated
    inside the function body and its ``.model_dump()`` becomes ``results``.
    """
    state_path = Path.home() / ".openbb_platform" / "fmp_trading" / "bandwidth.json"
    report = run_doctor(
        bandwidth_state_path=state_path,
        bandwidth_budget_bytes=50 * 1024**3,
    )
    return OBBject(results=report.model_dump(mode="json"))
