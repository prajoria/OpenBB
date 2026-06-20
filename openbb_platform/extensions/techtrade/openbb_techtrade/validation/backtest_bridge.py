"""``backtest_bridge`` -- TradePlan -> openbb-backtest.validate (issue #82, PRD §15).

The thin translation layer behind ``obb.techtrade.validate``: turn a single-symbol
:class:`~openbb_techtrade.models.TradePlan` into the
:class:`openbb_backtest.models.BacktestConfig` that ``openbb-backtest``'s
:func:`validate` expects, call into backtest's validate (WFO / CPCV folds, PBO,
Deflated Sharpe, MinBTL, verdict gate), and attach the returned
:class:`openbb_backtest.models.ValidationReport` to ``plan.validation`` so every
downstream consumer (#80 caveats, #81 Summary coverage) can read the verdict.

The clean architectural principle (PRD §15, design L4): **techtrade generates,
backtest validates**. This module is the *only* techtrade module that imports
``openbb_backtest``, and it does so **lazily inside function bodies** so
``import openbb_techtrade`` stays clean when backtest is absent (design Q-F).

**Dependency posture: SOFT / optional** (design Q-A, contrast with #73 which made
``openbb-technical`` a hard dependency). If ``openbb-backtest`` is not installed,
:func:`validate_plan` raises a leaf :class:`TechtradeDependencyError` with a
ready-to-run ``pip install`` hint, while **every other** part of
``obb.techtrade.*`` (movers / signals / plan / scan / export) keeps importing
and running untouched. This soft-dep guarantee is enforced by the #85
core-unchanged-when-removed discipline test.

**The bridge does NOT re-implement the verdict gate** (design L5): backtest's
:func:`build_validation_report` owns the precedence
``overfit > robust > fragile`` and the effective thresholds. The bridge forwards
``method``, ``thresholds``, and ``provider`` unchanged.

**The bridge does NOT read the plan's orders / fills**: ``validate`` reconstructs
returns from history by re-running the registered ``techtrade_confluence`` strategy
(design Q-B B2) over each fold's OOS window. The TradePlan exists only to:
1. supply ``symbol`` for the universe (``[plan.symbol]``);
2. supply ``as_of`` for the fold window (``[as_of - horizon, as_of]``);
3. supply the ``EntryExitRule.entry_threshold`` that parameterizes the strategy;
4. **be the attach target** for the returned ``ValidationReport`` (design Q-D).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from openbb_core.app.model.abstract.error import OpenBBError

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import cost
    from openbb_backtest.models import BacktestConfig, ValidationReport
    from openbb_techtrade.models import TradePlan

logger = logging.getLogger(__name__)

#: Default horizon (years) used to derive the fold window from a single ``as_of``.
DEFAULT_HORIZON_YEARS: int = 5

#: Strategy name registered in :mod:`openbb_techtrade.validation.confluence_strategy`
#: and advertised via the ``openbb_backtest_strategies`` entry-point group.
STRATEGY_NAME: str = "techtrade_confluence"

#: Hint emitted with :class:`TechtradeDependencyError` (kept verbatim so users can copy-paste).
_PIP_INSTALL_HINT: str = "pip install 'openbb-techtrade[validation]'"


class TechtradeDependencyError(OpenBBError):
    """An optional techtrade dependency (``openbb-backtest``) is not installed.

    Raised by :func:`validate_plan` when ``import openbb_backtest`` fails. Subclasses
    :class:`~openbb_core.app.model.abstract.error.OpenBBError` so existing
    ``except OpenBBError`` handlers catch it (and so techtrade does not need to
    import :class:`openbb_backtest.errors.OptionalDependencyError`, which would
    itself fail in the absent case).

    The error message is ready-to-action: it tells the user the exact ``pip
    install`` command to make the command work.
    """


def _require_backtest() -> tuple[type, Any]:
    """Lazily import openbb-backtest entrypoints, or raise a clear error.

    Returns
    -------
    tuple[type, callable]
        ``(BacktestConfig, validate_coroutine)`` -- the config class to build and
        the awaitable to call.

    Raises
    ------
    TechtradeDependencyError
        When ``openbb_backtest`` is not importable in this Python environment.
        The exception message carries the ``pip install`` hint.
    """
    try:
        from openbb_backtest.models import BacktestConfig
        from openbb_backtest.routers.validate_router import validate as backtest_validate
    except ImportError as exc:
        raise TechtradeDependencyError(
            "obb.techtrade.validate requires the 'openbb-backtest' extension, "
            f"which is not installed. Install it with: {_PIP_INSTALL_HINT}"
        ) from exc
    return BacktestConfig, backtest_validate


def _start_date(as_of: date, horizon_years: int) -> date:
    """Subtract ``horizon_years`` from ``as_of`` (Feb-29 safe).

    Uses ``date.replace(year=...)`` for the common path; falls back to ``Mar 1`` on
    a Feb-29 leap-day so the bridge never raises on a single edge case.
    """
    try:
        return as_of.replace(year=as_of.year - horizon_years)
    except ValueError:
        # Feb 29 on a non-leap landing year -> bump to Mar 1 of the landing year.
        return date(as_of.year - horizon_years, 3, 1)


def plan_to_config(
    plan: "TradePlan",
    *,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
    BacktestConfig: type | None = None,  # noqa: N803 - mirrors backtest's name
) -> "BacktestConfig":
    """Translate a :class:`TradePlan` into a :class:`BacktestConfig` for validate (design §3).

    Pure translation -- no I/O, no openbb-backtest call. The shipped strategy is the
    :data:`STRATEGY_NAME` (``techtrade_confluence``) advertised via the
    ``openbb_backtest_strategies`` entry-point group; ``strategy_params`` for it
    (``symbols`` + ``entry_threshold``) are passed to ``validate`` separately
    (see :func:`validate_plan`).

    Parameters
    ----------
    plan : TradePlan
        The plan whose ``symbol`` + ``as_of`` + ``rule`` parameterize the run.
    horizon_years : int, optional
        Fold-window length. Defaults to :data:`DEFAULT_HORIZON_YEARS` (5y of daily
        bars ~= 1260 sessions; design Q-B answer 3).
    BacktestConfig : type | None, optional
        The class to instantiate. ``None`` (default) lazy-imports it via
        :func:`_require_backtest` (the dependency-degradation path). Tests inject
        a fake to keep the unit suite hermetic.

    Returns
    -------
    BacktestConfig
        Backtest config: single-symbol universe ``[plan.symbol]``,
        window ``[as_of - horizon_years, as_of]``, ``strategy=STRATEGY_NAME``,
        defaults for everything else (engine='auto', frequency='daily',
        calendar='XNYS', etc.).
    """
    if BacktestConfig is None:
        BacktestConfig, _ = _require_backtest()
    start = _start_date(plan.as_of, horizon_years)
    return BacktestConfig(
        strategy=STRATEGY_NAME,
        universe=[plan.symbol],
        start=start,
        end=plan.as_of,
        # engine/frequency/calendar/seed/commission/slippage default;
        # 'XNYS' default calendar matches techtrade's session snapping (#79).
    )


def _strategy_params(plan: "TradePlan") -> dict[str, Any]:
    """Build the ``strategy_params`` dict passed to backtest's ``validate``.

    The registered :class:`~openbb_techtrade.validation.confluence_strategy.TechtradeConfluence`
    takes ``symbols`` + ``entry_threshold`` (+ optional ``lookback`` / ``gross``).
    We thread the plan's rule threshold so the validated rule is the rule the user
    is acting on -- not a default-paramed proxy.
    """
    return {
        "symbols": [plan.symbol],
        "entry_threshold": plan.rule.entry_threshold,
    }


async def validate_plan(
    plan: "TradePlan",
    *,
    method: str = "wfo",
    thresholds: dict[str, float] | None = None,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
    provider: str | None = None,
) -> tuple["TradePlan", "ValidationReport"]:
    """Run openbb-backtest's :func:`validate` for ``plan`` and attach the report (design §4).

    The pure, async core behind ``obb.techtrade.validate`` (design Q-D
    return + attach). Translates the plan into a :class:`BacktestConfig`, calls
    backtest's :func:`validate` with the techtrade strategy + per-rule params,
    then attaches the returned :class:`ValidationReport` to ``plan.validation``
    via :meth:`~pydantic.BaseModel.model_copy` (immutable discipline).

    Parameters
    ----------
    plan : TradePlan
        The plan to validate. Must carry a non-flat ``rule.entry_threshold`` and a
        valid ``symbol`` + ``as_of``.
    method : str, optional
        Resampling method, forwarded 1:1 to backtest. ``"wfo"`` (default) or
        ``"cpcv"``.
    thresholds : dict[str, float] | None, optional
        Verdict-threshold overrides merged over backtest's defaults
        (``pbo_robust`` / ``pbo_overfit`` / ``dsr_robust`` / ``dsr_overfit``).
        ``None`` (default) uses backtest's defaults (design L5 -- single source of
        truth).
    horizon_years : int, optional
        Fold-window length passed to :func:`plan_to_config`. Defaults to
        :data:`DEFAULT_HORIZON_YEARS`.
    provider : str | None, optional
        Data provider for the fold history (passed through to backtest). ``None``
        uses backtest's default (``fmp_cached`` in this fork).

    Returns
    -------
    tuple[TradePlan, ValidationReport]
        The plan with ``validation`` populated, and the report itself (for the
        router to wrap in ``OBBject``).

    Raises
    ------
    TechtradeDependencyError
        When ``openbb_backtest`` is not installed (caller can install via
        ``pip install 'openbb-techtrade[validation]'``).
    """
    BacktestConfig, backtest_validate = _require_backtest()
    config = plan_to_config(plan, horizon_years=horizon_years, BacktestConfig=BacktestConfig)
    logger.debug(
        "validate_plan: symbol=%s as_of=%s start=%s strategy=%s method=%s",
        plan.symbol, plan.as_of, config.start, STRATEGY_NAME, method,
    )
    obbject = await backtest_validate(
        config=config,
        method=method,
        thresholds=thresholds,
        strategy_params=_strategy_params(plan),
        provider=provider,
    )
    # backtest's router returns ``OBBject[ValidationReport]`` -- unwrap the .results.
    report = obbject.results
    updated = plan.model_copy(update={"validation": report})
    return updated, report
