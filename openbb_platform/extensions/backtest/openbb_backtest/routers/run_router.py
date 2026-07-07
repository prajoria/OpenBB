"""Engine sub-router: ``run`` / ``sweep`` / ``reconcile`` (component 09.2).

The execution face of ``obb.backtest.*``. These three commands are thin
orchestration over the heavy numeric layers — they resolve the engine per the
``engine=auto|vector|event`` policy (component 09.1), build the point-in-time
feed and execution broker, invoke the engine / vectorized sweep / reconciliation
gate, and return ``OBBject``-wrapped Data models. Two cross-cutting rules from
``09-api-surface.md`` §2 are enforced here at the boundary:

- **Privacy boundary** — :func:`run` pipes every engine result through
  :func:`~openbb_backtest.router_helpers.sanitize_result`, so raw positions / lot
  detail never cross the router; only normalized returns/metrics leave.
- **Lazy engine import** — engine modules (and their optional heavy deps) are
  imported only inside :func:`_engine_for`, keeping ``import openbb`` light.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_backtest.models import (
    BacktestConfig,
    BacktestResult,
    ReconciliationReport,
    SweepPoint,
    SweepResult,
)
from openbb_backtest.router_helpers import (
    build_feed,
    resolve_engine,
    resolve_provider,
    sanitize_result,
)

if TYPE_CHECKING:
    from openbb_backtest.interfaces import Broker, DataFeed, Engine, Strategy

logger = logging.getLogger(__name__)

router = Router(prefix="", description="Run, sweep and reconcile backtests.")


# --- collaborator seams (patched in unit tests; lazy in production) ------


def _strategy_factory(name: str):
    """Return a ``**params -> Strategy`` factory for the registered strategy ``name``.

    Defers to :func:`openbb_backtest.strategies.discovery.resolve`, which looks
    the class up in the registry (loading entry-point plugins on demand) and
    instantiates it from a params dict.
    """
    from openbb_backtest.strategies.discovery import resolve

    return lambda **params: resolve(name, params)


def _engine_for(name: str) -> Engine:
    """Lazily import the engine package and return the registered engine ``name``.

    Importing :mod:`openbb_backtest.engine` registers both concrete engines; the
    heavy modules stay out of ``import openbb`` time until a backtest is actually
    requested. ``name`` is the concrete engine name from :func:`resolve_engine`.
    """
    import openbb_backtest.engine  # noqa: F401  (registers vectorized + event)
    from openbb_backtest.registry import get_engine

    return get_engine(name)()


def _build_feed(config: BacktestConfig, provider: str) -> DataFeed:
    """Build the point-in-time :class:`DataFeed` for ``config`` from ``provider``.

    Thin seam over :func:`~openbb_backtest.router_helpers.build_feed` (the shared
    ingest/load logic) so unit tests can monkeypatch the feed per router.
    """
    return build_feed(config, provider)


def _build_broker(config: BacktestConfig) -> Broker:
    """Construct the shared execution broker from the config's cost models."""
    from openbb_backtest.engine.execution import RealisticBroker

    return RealisticBroker(config.commission, config.slippage)


# --- commands ------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a registered strategy with automatic engine selection.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["AAPL", "MSFT"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                "obb.backtest.run(config=config)",
            ],
        ),
        PythonEx(
            description="Force the event-driven engine for a path-dependent strategy.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="momentum_12_1", universe=["SPY"], start="2018-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.run(config=config, engine="event")',
            ],
        ),
    ],
)
async def run(
    config: BacktestConfig,
    engine: str = "auto",
    strategy_params: dict[str, Any] | None = None,
    provider: str | None = None,
) -> OBBject[BacktestResult]:
    """Run a single backtest and return its normalized result.

    Resolves the strategy and engine, executes the backtest, and strips raw
    position/lot detail at the privacy boundary before returning. With
    ``engine="auto"`` a path-dependent strategy routes to the event-driven engine
    and everything else to the vectorized engine; ``"vector"``/``"event"`` force
    a concrete engine.

    Parameters
    ----------
    config : BacktestConfig
        Strategy name, universe, date range and cost/engine settings.
    engine : str, optional
        ``"auto"`` (default), ``"vector"``/``"vectorized"``, or ``"event"``.
    strategy_params : dict, optional
        Keyword arguments forwarded to the strategy constructor.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[BacktestResult]
        The equity curve, trades and metrics — positions are sanitized away.
    """
    provider_name = resolve_provider(provider)
    strategy: Strategy = _strategy_factory(config.strategy)(**(strategy_params or {}))
    path_dependent = bool(getattr(strategy, "path_dependent", False))
    engine_name = resolve_engine(engine, path_dependent=path_dependent)
    logger.debug(
        "run: strategy=%s engine=%s provider=%s",
        config.strategy,
        engine_name,
        provider_name,
    )

    feed = _build_feed(config, provider_name)
    broker = _build_broker(config)
    result = _engine_for(engine_name).run(strategy, config, feed, broker)
    return OBBject(results=sanitize_result(result))


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Sweep a parameter grid on the vectorized engine, ranked by Sharpe.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="momentum_12_1", universe=["SPY"], start="2015-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.sweep(config=config, param_grid={"lookback": [60, 120, 252]}, rank_by="sharpe")',  # noqa: E501
            ],
        ),
    ],
)
async def sweep(
    config: BacktestConfig,
    param_grid: dict[str, list],
    rank_by: str = "sharpe",
    provider: str | None = None,
) -> OBBject[SweepResult]:
    """Evaluate a strategy across a parameter grid on the vectorized engine.

    The shared returns matrix is computed once and reused across every grid
    combination (the core sweep performance lever); each combo's metrics are
    returned alongside the winning combo selected by ``rank_by``.

    Parameters
    ----------
    config : BacktestConfig
        Backtest settings; ``config.strategy`` names the swept strategy.
    param_grid : dict[str, list]
        Maps each strategy keyword argument to the list of values to try; the
        cartesian product is evaluated.
    rank_by : str, optional
        :class:`PerformanceMetrics` field used to pick ``best`` (default ``sharpe``).
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[SweepResult]
        Per-combo metrics plus the best combo and its metrics.
    """
    from openbb_backtest.engine.vectorized import sweep as _engine_sweep

    provider_name = resolve_provider(provider)
    feed = _build_feed(config, provider_name)
    factory = _strategy_factory(config.strategy)
    logger.debug(
        "sweep: strategy=%s combos=%s rank_by=%s", config.strategy, param_grid, rank_by
    )

    engine_result = _engine_sweep(factory, param_grid, config, feed, rank_by=rank_by)
    model = SweepResult(
        results=[
            SweepPoint(params=params, metrics=metrics)
            for params, metrics in engine_result.results
        ],
        best=engine_result.best,
        best_metrics=engine_result.best_metrics,
        rank_by=engine_result.rank_by,
    )
    return OBBject(results=model)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Reconcile the vectorized engine against the event-driven source of truth.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["AAPL"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                "obb.backtest.reconcile(config=config)",
            ],
        ),
    ],
)
def reconcile(
    config: BacktestConfig,
    strategy_params: dict[str, Any] | None = None,
    strict: bool = False,
    tolerance: float | None = None,
    provider: str | None = None,
) -> OBBject[ReconciliationReport]:
    """Run one config through both engines and compare their equity curves.

    The event-driven engine is the source of truth; the vectorized engine is the
    candidate under test. A divergence beyond ``tolerance`` marks the report as
    failed and, when ``strict`` is set, raises ``ReconciliationError`` instead.

    Parameters
    ----------
    config : BacktestConfig
        Backtest settings run identically through both engines.
    strategy_params : dict, optional
        Keyword arguments forwarded to the strategy constructor.
    strict : bool, optional
        Raise ``ReconciliationError`` on divergence instead of reporting it.
    tolerance : float, optional
        Max allowed equity divergence; defaults to the settings reconcile tolerance.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[ReconciliationReport]
        Whether the engines agreed and the largest equity divergence observed.
    """
    from openbb_backtest.engine.reconcile import reconcile as _engine_reconcile

    provider_name = resolve_provider(provider)
    strategy: Strategy = _strategy_factory(config.strategy)(**(strategy_params or {}))
    feed = _build_feed(config, provider_name)
    broker = _build_broker(config)
    reference = _engine_for("event")
    candidate = _engine_for("vectorized")
    logger.debug(
        "reconcile: strategy=%s strict=%s tol=%s", config.strategy, strict, tolerance
    )

    report = _engine_reconcile(
        reference,
        candidate,
        strategy,
        config,
        feed,
        broker,
        tolerance=tolerance,
        strict=strict,
    )
    return OBBject(
        results=ReconciliationReport(
            passed=report.passed,
            max_divergence=report.max_divergence,
            tolerance=report.tolerance,
            reference_engine=report.reference_engine,
            candidate_engine=report.candidate_engine,
        )
    )
