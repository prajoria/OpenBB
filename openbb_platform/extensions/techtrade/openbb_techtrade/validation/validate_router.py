"""Validation sub-router: ``validate`` -> robustness verdict + attach (PRD §15, issue #82).

The validation face of ``obb.techtrade.*``. :func:`validate` is the thin async command
that delegates to :func:`~openbb_techtrade.validation.backtest_bridge.validate_plan`:
it translates a :class:`~openbb_techtrade.models.TradePlan` into an ``openbb-backtest``
:class:`~openbb_backtest.models.BacktestConfig`, calls backtest's ``validate`` over WFO
/ CPCV folds (PBO + Deflated Sharpe + MinBTL + verdict gate), attaches the returned
:class:`~openbb_backtest.models.ValidationReport` to ``plan.validation``, and returns
the verdict as ``OBBject[ValidationReport]``.

**Soft dependency on openbb-backtest** (design Q-A). The command raises a clear
:class:`~openbb_techtrade.validation.backtest_bridge.TechtradeDependencyError`
(with a ``pip install`` hint) when ``openbb-backtest`` is not installed; every other
``obb.techtrade.*`` command keeps importing and running untouched. The router itself
is auto-wired by :func:`openbb_techtrade.techtrade_router._include_subrouters` (which
already lists this module path); auto-wiring degrades cleanly because the include
loop catches :class:`ImportError`, so a missing ``openbb-backtest`` never breaks
``obb.techtrade.*`` registration.

Note: this module deliberately does **not** use ``from __future__ import annotations``.
The ``validate`` command takes a ``plan: TradePlan`` model parameter, and the static
package builder must see the real :class:`TradePlan` class (not a stringized
annotation) to emit its import into the generated package -- mirroring the
``plan_router.orders`` and ``export_router.export`` conventions.
"""

from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_techtrade.models import TradePlan

router = Router(prefix="", description="Robustness-validate a TradePlan via openbb-backtest.")


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Validate a plan with default WFO folds.",
            code=[
                "plans = obb.techtrade.plan(segment='Information Technology').results",
                "report = obb.techtrade.validate(plan=plans[0]).results",
            ],
        ),
        PythonEx(
            description="Validate with CPCV over a 3-year horizon.",
            code=[
                "plans = obb.techtrade.plan(segment='Information Technology').results",
                "report = obb.techtrade.validate(plan=plans[0], method='cpcv', horizon_years=3).results",
            ],
        ),
    ],
)
async def validate(
    plan: TradePlan,
    method: str = "wfo",
    thresholds: dict[str, float] | None = None,
    horizon_years: int = 5,
    provider: str | None = None,
) -> OBBject:
    """Robustness-validate a TradePlan via openbb-backtest (PRD §15, issue #82).

    Translates ``plan`` into a :class:`~openbb_backtest.models.BacktestConfig` (universe
    ``[plan.symbol]``, window ``[as_of - horizon_years, as_of]``, strategy
    ``techtrade_confluence``), calls ``openbb-backtest``'s ``validate`` over WFO / CPCV
    folds, attaches the returned :class:`~openbb_backtest.models.ValidationReport` to
    ``plan.validation`` via :meth:`~pydantic.BaseModel.model_copy` (immutable
    discipline), and returns the verdict.

    The reported ``verdict`` is one of ``"robust"`` / ``"fragile"`` / ``"overfit"``,
    derived by ``openbb-backtest``'s gate (precedence ``overfit > robust > fragile``);
    the effective thresholds are recorded on ``report.thresholds`` so the verdict is
    auditable. techtrade does not re-implement the gate (design L4 / L5).

    Parameters
    ----------
    plan : TradePlan
        The plan to validate (single-symbol, single ``as_of``).
    method : str, optional
        Resampling method: ``"wfo"`` (default) or ``"cpcv"``. Forwarded 1:1 to
        backtest's validator.
    thresholds : dict[str, float] | None, optional
        Verdict-threshold overrides merged over backtest's defaults
        (``pbo_robust`` / ``pbo_overfit`` / ``dsr_robust`` / ``dsr_overfit``).
        ``None`` uses backtest's defaults (design L5).
    horizon_years : int, optional
        Number of years of history to span the folds (default 5).
    provider : str | None, optional
        Data provider for the fold history; ``None`` uses backtest's default
        (``fmp_cached`` in this fork).

    Returns
    -------
    OBBject
        OBBject whose ``results`` is the :class:`ValidationReport`. The
        ``validation``-attached plan is available via ``plan.model_copy(...)`` /
        the bridge return -- the router returns the report itself per design Q-D.

    Raises
    ------
    TechtradeDependencyError
        When ``openbb-backtest`` is not installed. The message carries
        ``pip install 'openbb-techtrade[validation]'`` so the user can act immediately.
    """
    from openbb_techtrade.validation.backtest_bridge import validate_plan

    _updated_plan, report = await validate_plan(
        plan,
        method=method,
        thresholds=thresholds,
        horizon_years=horizon_years,
        provider=provider,
    )
    return OBBject(results=report)
