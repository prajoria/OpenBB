"""Validate sub-router: ``validate`` / ``tearsheet`` (component 09.4).

The robustness face of ``obb.backtest.*``. Two long-running commands sit on top
of the validation framework (component 08) and the analytics layer (component 07):

- :func:`validate` resolves the strategy, runs the per-fold engine+analytics
  backend (the heavy, engine-coupled work lives behind the :func:`_run_folds`
  seam), then assembles the report through the **real**
  :func:`~openbb_backtest.validation.build_validation_report` so the verdict gate
  (overfit > robust > fragile) is exercised at the router boundary.
- :func:`tearsheet` runs the engine, hands the equity curve to the **real**
  in-house :func:`~openbb_backtest.analytics.build_tearsheet`, and optionally
  exports an HTML artifact via the lazily-imported quantstats backend — which
  degrades to :class:`~openbb_backtest.errors.OptionalDependencyError` (with a
  ready-to-run ``pip install`` hint) when the dependency is absent.

Both commands are ``async def`` per ``09-api-surface.md`` §2 ("commands are
defined ``async`` where the work is long — full backtests, sweeps, validation"),
so the REST layer can stream/poll a multi-minute CPCV run without blocking. The
heavy validation / analytics modules (and their optional deps) are imported only
inside the function bodies, keeping ``import openbb`` light.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2 and
``08-validation.md`` §3.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_backtest.errors import OptionalDependencyError
from openbb_backtest.models import (
    BacktestConfig,
    FoldResult,
    PerformanceMetrics,
    TearSheet,
    ValidationReport,
)
from openbb_backtest.router_helpers import build_feed, resolve_engine, resolve_provider

if TYPE_CHECKING:
    import pandas as pd

    from openbb_backtest.interfaces import Broker, DataFeed, Engine, Strategy

logger = logging.getLogger(__name__)

router = Router(prefix="", description="Validate strategies and build tear sheets.")

#: Trading sessions per year by bar frequency; drives analytics annualization
#: (matches the vectorized engine's 252-session daily convention, never hardcoded
#: downstream — the resolved value is threaded into the analytics layer).
_SESSIONS_PER_YEAR: dict[str, int] = {
    "daily": 252,
    "hourly": 252 * 7,  # ~6.5 trading hours/session, rounded up to a whole count
    "minute": 252 * 390,  # 390 minutes per regular session
}

#: Resampling methods the validator accepts (mirrors ``ValidationReport.method``'s
#: ``Literal["wfo", "cpcv"]``); validated at the router boundary before the
#: multi-minute fold backend runs.
_VALID_METHODS: tuple[str, ...] = ("wfo", "cpcv")

#: Upper bound on CSCV row-groups. CSCV enumerates ``C(n_groups, n_groups/2)``
#: partitions, which explodes combinatorially; the framework default is 16, so the
#: per-fold PBO never derives a larger (and intractable) ``n_groups`` from the
#: OOS path length.
_PBO_MAX_GROUPS = 16


def _check_method(method: str) -> str:
    """Validate a resampling ``method`` against :data:`_VALID_METHODS`.

    Raises a clear :class:`ValueError` (listing the valid choices) for an unknown
    method so a typo fails fast at the router boundary instead of silently
    defaulting to walk-forward. Returns ``method`` unchanged when valid.
    """
    if method not in _VALID_METHODS:
        choices = ", ".join(_VALID_METHODS)
        raise ValueError(
            f"unknown validation method '{method}'. Choose one of: {choices}."
        )
    return method


# --- collaborator seams (patched in unit tests; lazy in production) ------


def _strategy_factory(name: str) -> Callable[..., Strategy]:
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
    heavy modules stay out of ``import openbb`` time until validation actually
    runs. ``name`` is the concrete engine name from :func:`resolve_engine`.
    """
    import openbb_backtest.engine  # noqa: F401  (registers vectorized + event)
    from openbb_backtest.registry import get_engine

    return get_engine(name)()


def _build_feed(config: BacktestConfig, provider: str) -> DataFeed:
    """Build the point-in-time :class:`DataFeed` for ``config`` from ``provider``.

    Thin seam over :func:`~openbb_backtest.router_helpers.build_feed` (the shared
    ingest/load logic the other routers use too) so unit tests can monkeypatch
    the feed per router.
    """
    return build_feed(config, provider)


def _build_broker(config: BacktestConfig) -> Broker:
    """Construct the shared execution broker from the config's cost models."""
    from openbb_backtest.engine.execution import RealisticBroker

    return RealisticBroker(config.commission, config.slippage)


@dataclass(frozen=True)
class _FoldOutcome:
    """The engine+analytics backend's per-fold output, pre-verdict.

    Carries everything :func:`~openbb_backtest.validation.build_validation_report`
    needs except the verdict (which it derives): the per-fold OOS
    :class:`~openbb_backtest.models.FoldResult` list, the aggregated OOS metrics,
    and the three overfitting statistics (PBO, deflated Sharpe, MinBTL).
    """

    folds: list[FoldResult]
    oos_metrics: PerformanceMetrics
    pbo: float
    deflated_sharpe: float
    min_backtest_length_years: float


def _run_folds(
    strategy_factory: Callable[[], Strategy],
    config: BacktestConfig,
    feed: DataFeed,
    broker: Broker,
    *,
    method: str,
) -> _FoldOutcome:
    """Run the resampled folds through the engine + analytics path (integration seam).

    The heavy, engine-coupled backend behind :func:`validate`: it splits the
    config's session calendar into walk-forward (``method="wfo"``) or CPCV
    (``method="cpcv"``) folds, runs the strategy through the engine on each fold's
    out-of-sample window, scores it with the real analytics layer (component 07),
    then aggregates the OOS returns and derives the overfitting statistics
    (PBO / deflated Sharpe / MinBTL) from the real validation primitives
    (component 08). Faked wholesale in unit tests (acceptance: "no backend in
    unit"); exercised end-to-end under the integration suite.

    All heavy imports are local so importing this router stays light.
    """
    import math

    import pandas as pd

    from openbb_backtest.analytics import compute_metrics, to_returns
    from openbb_backtest.validation import (
        cpcv,
        deflated_sharpe,
        min_backtest_length,
        walk_forward,
    )

    _check_method(method)
    sessions = pd.DatetimeIndex(feed.sessions(config.start, config.end))
    spy = _sessions_per_year(config)
    engine_name = resolve_engine(
        config.engine,
        path_dependent=bool(getattr(strategy_factory(), "path_dependent", False)),
    )

    if method == "cpcv":
        folds = cpcv(sessions)
    else:
        train = max(1, len(sessions) // 2)
        test = max(1, len(sessions) // 4)
        folds = walk_forward(sessions, train, test, test)

    fold_results: list[FoldResult] = []
    oos_curves: list[pd.Series] = []
    engine = _engine_for(engine_name)
    for i, fold in enumerate(folds):
        window = sessions[fold.test_idx]
        sub = config.model_copy(
            update={"start": window[0].date(), "end": window[-1].date()}
        )
        # Fresh strategy per fold: a reused instance would leak state into later
        # OOS windows for path-dependent strategies.
        result = engine.run(strategy_factory(), sub, feed, broker)
        returns = to_returns(result.equity_curve)
        fold_results.append(
            FoldResult(
                fold=i,
                metrics=compute_metrics(returns, None, result.trades, spy),
                path_id=fold.path_id,
            )
        )
        oos_curves.append(returns)

    aggregate = (
        pd.concat(oos_curves)
        if oos_curves
        else pd.Series([], dtype=float, name="returns")
    )
    oos_metrics = compute_metrics(aggregate, None, [], spy)
    n_trials = max(1, len(fold_results))
    # DSR wants a *per-observation* Sharpe (it applies sqrt(n_obs-1) itself), so
    # de-annualize the annualized OOS Sharpe by sqrt(sessions/yr) before deflating.
    per_obs_sharpe = oos_metrics.sharpe / math.sqrt(spy)
    dsr = deflated_sharpe(
        per_obs_sharpe, n_trials=n_trials, skew=0.0, kurt=3.0,
        n_obs=max(2, int(aggregate.shape[0])),
    )
    # MinBTL = 2*ln(n)/SR^2 is only defined for a positive (annualized) Sharpe;
    # a losing strategy has no overfitting floor, so report 0.0 rather than
    # fabricating one from |SR|.
    minbtl = (
        min_backtest_length(oos_metrics.sharpe, n_trials)
        if oos_metrics.sharpe > 0.0
        else 0.0
    )
    return _FoldOutcome(
        folds=fold_results,
        oos_metrics=oos_metrics,
        pbo=_pbo_from_folds(oos_curves),
        deflated_sharpe=dsr,
        min_backtest_length_years=minbtl,
    )


def _pbo_from_folds(oos_curves: list[pd.Series]) -> float:
    """Probability of Backtest Overfitting across the fold OOS paths (integration seam).

    Stacks the equal-length head of each fold's OOS return path into a CSCV
    performance matrix (folds as the compared columns) and defers to the real
    :func:`~openbb_backtest.validation.pbo`. Returns ``0.0`` when there are too
    few folds / sessions to form a symmetric split (PBO is undefined there).
    """
    import numpy as np

    from openbb_backtest.validation import pbo

    if len(oos_curves) < 2:
        return 0.0
    min_len = min(int(c.shape[0]) for c in oos_curves)
    # Largest even count <= min_len, capped at the framework default: CSCV
    # enumerates C(n_groups, n_groups/2) partitions, so deriving n_groups from the
    # raw OOS path length would explode combinatorially (and hang validate).
    n_groups = min(_PBO_MAX_GROUPS, min_len - (min_len % 2))
    if n_groups < 2:
        return 0.0
    matrix = np.column_stack(
        [c.to_numpy(dtype=float)[:min_len] for c in oos_curves]
    )
    return pbo(matrix, n_groups=n_groups)


def _export_html(returns: pd.Series, *, title: str) -> str:
    """Export a quantstats HTML tear sheet, degrading to an actionable error.

    Delegates to :func:`openbb_backtest.analytics.export_html` (the no-fallback
    quantstats backend — the report *is* its output). quantstats is an optional
    dependency, so its absence surfaces as :class:`ImportError`; this seam maps
    that to :class:`~openbb_backtest.errors.OptionalDependencyError` with a
    ready-to-run ``pip install`` hint. Called through the ``analytics`` module so
    the export backend stays patchable in tests.
    """
    from openbb_backtest import analytics

    try:
        return analytics.export_html(returns, title=title)
    except ImportError as exc:
        raise OptionalDependencyError(
            "quantstats", feature="HTML tear-sheet export (tearsheet export=True)"
        ) from exc


def _sessions_per_year(config: BacktestConfig) -> int:
    """Trading sessions per year for ``config``'s bar frequency (annualization)."""
    return _SESSIONS_PER_YEAR.get(config.frequency, 252)


# --- commands ------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Validate a strategy out-of-sample with walk-forward folds.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="momentum_12_1", universe=["SPY"], start="2015-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.validate(config=config, method="wfo")',
            ],
        ),
        PythonEx(
            description="Run combinatorial purged CV and tighten the robust PBO cut.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="mean_reversion", universe=["AAPL", "MSFT"], start="2015-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.validate(config=config, method="cpcv", thresholds={"pbo_robust": 0.1})',  # noqa: E501
            ],
        ),
    ],
)
async def validate(
    config: BacktestConfig,
    method: str = "wfo",
    thresholds: dict[str, float] | None = None,
    strategy_params: dict[str, Any] | None = None,
    provider: str | None = None,
) -> OBBject[ValidationReport]:
    """Score a strategy's out-of-sample robustness (anti-overfitting report).

    Runs the strategy through resampled folds (walk-forward or CPCV), scores each
    out-of-sample window with the analytics layer, and assembles a
    :class:`~openbb_backtest.models.ValidationReport` whose ``verdict`` is derived
    by the real validation gate from ``(pbo, deflated_sharpe, oos_sharpe)``. The
    precedence is **overfit > robust > fragile**; the effective thresholds are
    recorded on the report so the verdict is auditable.

    Parameters
    ----------
    config : BacktestConfig
        Strategy name, universe, date range and cost/engine settings.
    method : str, optional
        Resampling method: ``"wfo"`` (default) or ``"cpcv"``.
    thresholds : dict, optional
        Verdict-threshold overrides merged over the design defaults
        (``pbo_robust`` / ``pbo_overfit`` / ``dsr_robust`` / ``dsr_overfit``).
    strategy_params : dict, optional
        Keyword arguments forwarded to the strategy constructor.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[ValidationReport]
        Per-fold OOS metrics, PBO / deflated Sharpe / MinBTL, and the verdict.
    """
    from openbb_backtest.validation import build_validation_report

    _check_method(method)
    provider_name = resolve_provider(provider)
    base_factory = _strategy_factory(config.strategy)

    def factory() -> Strategy:
        return base_factory(**(strategy_params or {}))

    feed = _build_feed(config, provider_name)
    broker = _build_broker(config)
    logger.debug(
        "validate: strategy=%s method=%s provider=%s",
        config.strategy, method, provider_name,
    )

    outcome = _run_folds(factory, config, feed, broker, method=method)
    report = build_validation_report(
        method=method,
        folds=outcome.folds,
        oos_metrics=outcome.oos_metrics,
        pbo=outcome.pbo,
        deflated_sharpe=outcome.deflated_sharpe,
        min_backtest_length_years=outcome.min_backtest_length_years,
        thresholds=thresholds,
    )
    return OBBject(results=report)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Build an institutional tear sheet for a strategy.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["AAPL", "MSFT"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                "obb.backtest.tearsheet(config=config)",
            ],
        ),
        PythonEx(
            description="Export the tear sheet to a quantstats HTML artifact.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["SPY"], start="2018-01-01", end="2023-01-01")',  # noqa: E501
                "obb.backtest.tearsheet(config=config, export=True)",
            ],
        ),
    ],
)
async def tearsheet(
    config: BacktestConfig,
    engine: str = "auto",
    rolling_window: int = 21,
    export: bool = False,
    strategy_params: dict[str, Any] | None = None,
    provider: str | None = None,
) -> OBBject[TearSheet]:
    """Build a structured tear sheet from a single backtest run.

    Runs the strategy once, converts the equity curve to normalized returns at
    the fork privacy boundary, and hands them to the in-house analytics layer for
    the metrics, rolling-Sharpe series, drawdown episodes and monthly-return
    buckets. With ``export=True`` a quantstats HTML report is rendered and its
    path recorded on ``html_path`` (the large artifact lives on disk, never in the
    model); when quantstats is absent this raises
    :class:`~openbb_backtest.errors.OptionalDependencyError`.

    Parameters
    ----------
    config : BacktestConfig
        Strategy name, universe, date range and cost/engine settings.
    engine : str, optional
        ``"auto"`` (default), ``"vector"``/``"vectorized"``, or ``"event"``.
    rolling_window : int, optional
        Lookback (sessions) for the rolling-Sharpe series (default 21).
    export : bool, optional
        Render and save a quantstats HTML artifact, recording its path.
    strategy_params : dict, optional
        Keyword arguments forwarded to the strategy constructor.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[TearSheet]
        Normalized metrics, rolling Sharpe, drawdowns and monthly returns.
    """
    from openbb_backtest.analytics import build_tearsheet, to_returns

    provider_name = resolve_provider(provider)
    strategy: Strategy = _strategy_factory(config.strategy)(**(strategy_params or {}))
    engine_name = resolve_engine(
        engine, path_dependent=bool(getattr(strategy, "path_dependent", False))
    )
    feed = _build_feed(config, provider_name)
    broker = _build_broker(config)
    logger.debug(
        "tearsheet: strategy=%s engine=%s export=%s",
        config.strategy, engine_name, export,
    )

    result = _engine_for(engine_name).run(strategy, config, feed, broker)
    returns = to_returns(result.equity_curve)
    sheet = build_tearsheet(
        returns, None, result.trades, _sessions_per_year(config),
        rolling_window=rolling_window,
    )
    if export:
        html_path = _export_html(returns, title=f"{config.strategy} Tear Sheet")
        sheet = sheet.model_copy(update={"html_path": html_path})
    return OBBject(results=sheet)
