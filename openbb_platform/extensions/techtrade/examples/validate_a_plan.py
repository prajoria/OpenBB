"""Build a plan, then call ``obb.techtrade.validate`` to score its robustness.

Live run:

    .venv_win\\Scripts\\python.exe -m openbb_techtrade.examples.validate_a_plan

Requires the ``[validation]`` extra:

    pip install 'openbb-techtrade[validation]'

When the extra is absent, ``validate`` raises ``TechtradeDependencyError`` with a
pip-install hint; this example catches that and prints a skip notice rather than
crashing — mirrors the integration-test skipif pattern (#82 test_validate.py).

Demonstrates the user-visible robustness gate: WFO folds + PBO + Deflated Sharpe
+ verdict (one of ``robust`` / ``fragile`` / ``overfit``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main(
    *,
    symbol: str = "MSFT",
    method: str = "wfo",
    horizon_years: int = 5,
    preset: str = "trend_follow",
    risk: float = 0.01,
    signal_fetcher=None,
    level_fetcher=None,
    BacktestConfig=None,  # noqa: N803 — mirrors the openbb_backtest name
):
    """Plan a symbol, then validate the plan. Return the ValidationReport or None.

    Returns ``None`` when ``openbb-backtest`` (the ``[validation]`` extra) is
    absent — the example degrades to a skip notice rather than a crash so it can
    be smoke-tested on a bare install.
    """
    from openbb import obb  # noqa: PLC0415

    # 1. Build a single-symbol plan.
    plan_kwargs = {"symbols": [symbol], "preset": preset, "risk": risk}
    if signal_fetcher is not None:
        plan_kwargs["signal_fetcher"] = signal_fetcher
    if level_fetcher is not None:
        plan_kwargs["level_fetcher"] = level_fetcher
    plans = obb.techtrade.plan(**plan_kwargs).results
    if not plans:
        logger.info("no plan produced for %s; nothing to validate", symbol)
        return None
    plan = plans[0]

    # 2. Validate. Catches the soft-dep-absent error and degrades to None so the
    #    example runs on a bare install (and the smoke test exercises both paths).
    try:
        from openbb_techtrade.validation.backtest_bridge import (  # noqa: PLC0415
            TechtradeDependencyError,
        )
    except ImportError:  # pragma: no cover — validation module always ships in techtrade
        logger.error("validation module not importable; cannot continue")
        return None

    try:
        result = obb.techtrade.validate(
            plan=plan, method=method, horizon_years=horizon_years,
        )
    except TechtradeDependencyError as exc:
        logger.warning(
            "validate skipped: %s\n  install with: pip install 'openbb-techtrade[validation]'",
            exc,
        )
        return None

    report = result.results
    logger.info(
        "verdict=%s  pbo=%.3f  dsr=%.3f  oos_sharpe=%.3f",
        report.verdict,
        getattr(report, "pbo", float("nan")),
        getattr(report, "deflated_sharpe", float("nan")),
        getattr(getattr(report, "oos_metrics", None), "sharpe", float("nan")),
    )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
