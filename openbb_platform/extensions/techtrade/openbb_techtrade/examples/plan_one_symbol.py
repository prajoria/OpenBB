"""Build a single-symbol plan, materialize its orders, paper-fill them forward.

Live run:

    .venv_win\\Scripts\\python.exe -m openbb_techtrade.examples.plan_one_symbol

Requires:
- A configured ``fmp_cached`` API key in ``~/.openbb_platform/user_settings.json``.

Demonstrates the user-facing chain plan -> orders -> simulate for ONE symbol
(MSFT by default). The forward bar window for ``simulate`` is fetched on the live
path; tests inject a synthetic ``bars`` window so the smoke stays offline.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main(
    *,
    symbol: str = "MSFT",
    preset: str = "trend_follow",
    risk: float = 0.01,
    signal_fetcher=None,
    level_fetcher=None,
    bars=None,
) -> list:
    """Plan -> orders -> simulate; return the realized fills.

    Returns
    -------
    list[Fill]
        Paper fills for the plan's order legs (the fills are the user-visible
        outcome of paper-trading the plan forward).
    """
    from openbb import obb  # noqa: PLC0415

    # 1. Build a single-symbol plan (the engine ranks the symbol, builds the
    #    confluence signal, sizes the position, generates the order legs, and
    #    attaches an inline Recommendation).
    plan_kwargs = {"symbols": [symbol], "preset": preset, "risk": risk}
    if signal_fetcher is not None:
        plan_kwargs["signal_fetcher"] = signal_fetcher
    if level_fetcher is not None:
        plan_kwargs["level_fetcher"] = level_fetcher
    plans = obb.techtrade.plan(**plan_kwargs).results
    if not plans:
        logger.info("no plan produced for %s (signal below entry_threshold)", symbol)
        return []
    plan = plans[0]
    logger.info(
        "plan: %s score=%+.3f action=%s conviction=%s",
        plan.symbol, plan.signal.score, plan.recommendation.action,
        plan.recommendation.conviction,
    )

    # 2. Materialize the order legs (re-validates the plan; idempotent).
    orders = obb.techtrade.orders(plan=plan).results
    logger.info("orders: %d legs (%s)", len(orders), [o.intent for o in orders])

    # 3. Paper-fill the orders against a forward bar window. Real-money brokers
    #    are not engaged; every fill is at next-bar-open with configured slippage
    #    + commission (PRD §13 + #78).
    sim_kwargs = {"orders": orders}
    if bars is not None:
        sim_kwargs["bars"] = bars
    fills = obb.techtrade.simulate(**sim_kwargs).results
    logger.info("simulate: %d fills", len(fills))
    for fill in fills:
        logger.info(
            "  fill: %s %s qty=%s price=%s slippage=%s commission=%s",
            fill.symbol, fill.side, fill.quantity, fill.price,
            fill.slippage, fill.commission,
        )
    return fills


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
