"""Factor sub-router: ``pipeline`` / ``factor_eval`` (component 09.3).

The cross-sectional face of ``obb.backtest.*``. Two commands sit on top of the
component-05 pipeline:

- :func:`pipeline` resolves factor specs to concrete
  :class:`~openbb_backtest.pipeline.factor.Factor` nodes, runs the look-ahead-free
  cross-sectional runner over the point-in-time feed, and returns the panel as a
  serializable :class:`~openbb_backtest.models.FactorPanel`.
- :func:`factor_eval` computes alphalens-style IC / quantile-return diagnostics
  for a single factor. The heavy ``alphalens-reloaded`` backend is imported only
  inside :func:`_alphalens_metrics`, which degrades to
  :class:`~openbb_backtest.errors.OptionalDependencyError` (with a ready-to-run
  ``pip install`` hint) when the dependency is absent — keeping ``import openbb``
  light and the failure actionable.

See ``docs/designs/backtest-design/09-api-surface.md`` §1 and
``05-event-driven-engine.md`` §2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_backtest.errors import OptionalDependencyError
from openbb_backtest.models import (
    BacktestConfig,
    FactorExposure,
    FactorPanel,
    FactorReport,
)
from openbb_backtest.router_helpers import build_feed, resolve_provider

if TYPE_CHECKING:
    import pandas as pd

    from openbb_backtest.interfaces import DataFeed
    from openbb_backtest.pipeline.factor import Factor

logger = logging.getLogger(__name__)

router = Router(prefix="", description="Run factor pipelines and evaluate factors.")

#: Factor specs accepted by the router: a bare registered name, or a mapping
#: ``{"name": ..., "params": {...}}`` forwarding kwargs to the factor constructor.
FactorSpec = str | dict[str, Any]

#: Registered cross-sectional factors (component 05). Names are case-insensitive.
_FACTORS: dict[str, type] = {}


def _factor_registry() -> dict[str, type]:
    """Return the name -> :class:`Factor` class map (built lazily on first use)."""
    if not _FACTORS:
        from openbb_backtest.pipeline.factor import EarningsYield, Momentum

        _FACTORS.update({"momentum": Momentum, "earnings_yield": EarningsYield})
    return _FACTORS


# --- collaborator seams (patched in unit tests; lazy in production) ------


def _factor_for(spec: FactorSpec) -> Factor:
    """Resolve a factor spec to a concrete :class:`Factor` instance.

    ``spec`` is either a registered factor name or a mapping
    ``{"name": ..., "params": {...}}`` whose ``params`` are forwarded to the
    factor constructor. Unknown names raise :class:`ValueError`.
    """
    if isinstance(spec, str):
        name, params = spec, {}
    else:
        name = spec["name"]
        params = dict(spec.get("params", {}))
    registry = _factor_registry()
    try:
        cls = registry[name.lower()]
    except KeyError:
        choices = ", ".join(sorted(registry))
        raise ValueError(f"unknown factor '{name}'. Choose one of: {choices}.") from None
    return cls(**params)


def _build_feed(config: BacktestConfig, provider: str) -> DataFeed:
    """Build the point-in-time :class:`DataFeed` for ``config`` from ``provider``.

    Thin seam over :func:`~openbb_backtest.router_helpers.build_feed` (the shared
    ingest/load logic the engine router uses too) so unit tests can monkeypatch
    the feed per router.
    """
    return build_feed(config, provider)


def _alphalens_metrics(
    factor_values: pd.Series,
    feed: DataFeed,
    config: BacktestConfig,
    *,
    quantiles: int,
    periods: list[int],
) -> dict[str, dict[str, float]]:
    """Compute IC / quantile-return diagnostics via the alphalens backend.

    Lazily imports ``alphalens`` (``alphalens-reloaded``); when it is not
    installed this raises :class:`OptionalDependencyError` with an actionable
    install hint instead of a bare :class:`ImportError`. The heavy numeric work
    (forward-return alignment, IC, quantile grouping) lives in the backend; this
    seam only marshals the pipeline output into it.

    ``ic_mean`` / ``ic_std`` are the mean and standard deviation **of the per-date
    information-coefficient time series** (so ``ic_mean / ic_std`` is alphalens'
    Risk-Adjusted IC), and ``quantile_returns`` is the mean forward return of the
    longest period per factor quantile.
    """
    try:
        import alphalens  # noqa: F401  (heavy optional backend)
    except ImportError as exc:
        raise OptionalDependencyError(
            "alphalens-reloaded", feature="factor evaluation (factor_eval)"
        ) from exc

    from alphalens.performance import (
        factor_information_coefficient,
        mean_return_by_quantile,
    )
    from alphalens.utils import get_clean_factor_and_forward_returns

    prices = _forward_price_frame(feed, config, periods)
    clean = get_clean_factor_and_forward_returns(
        factor_values, prices, quantiles=quantiles, periods=tuple(periods)
    )
    # Per-date IC series -> its mean and std are the IC mean and IC std.
    ic_series = factor_information_coefficient(clean)
    longest = f"{periods[-1]}D"
    quantile_means = mean_return_by_quantile(clean)[0][longest]
    return {
        "ic_mean": {str(p): float(ic_series[f"{p}D"].mean()) for p in periods},
        "ic_std": {str(p): float(ic_series[f"{p}D"].std()) for p in periods},
        "quantile_returns": {
            str(int(q)): float(value) for q, value in quantile_means.items()
        },
    }


def _forward_price_frame(
    feed: DataFeed, config: BacktestConfig, periods: list[int]
) -> pd.DataFrame:
    """Build the ``date x asset`` close-price frame alphalens aligns returns from.

    Fetches ``max(periods)`` sessions of history *beyond* the factor window so the
    forward returns at the final factor dates are computable rather than dropped.
    Uses :meth:`~pandas.DataFrame.pivot` (a pure reshape) since the feed yields
    exactly one row per ``(symbol, session)`` — no aggregation is needed and NaNs
    are preserved.
    """
    import pandas as pd

    sessions = pd.DatetimeIndex(feed.sessions(config.start, config.end))
    horizon = max(periods) if periods else 0
    end = sessions[-1] if len(sessions) else pd.Timestamp(config.end)
    history = feed.history(
        list(config.universe), end=end, lookback=(len(sessions) or 1) + horizon
    )
    return history.pivot(index="session", columns="symbol", values="close")


def _to_panel_model(panel) -> FactorPanel:
    """Flatten the pipeline's internal ``FactorPanel`` into the Data model.

    Builds the records columnar-side (level arrays + ``to_dict("records")``)
    rather than per-row ``iterrows`` so a large ``(date, asset)`` grid marshals
    without the row-by-row Series allocation overhead.
    """
    frame = panel.to_frame()
    dates = frame.index.get_level_values(0)
    assets = frame.index.get_level_values(1)
    value_dicts = frame.to_dict("records")
    records = [
        FactorExposure(date=date, asset=str(asset), values=values)
        for date, asset, values in zip(dates, assets, value_dicts)
    ]
    return FactorPanel(factors=panel.factors, records=records)


def _safe_ratio(numerator: float, denominator: float | None) -> float:
    """Return ``numerator / denominator``, or ``0.0`` when it is not finite.

    Guards the IC information ratio against a zero, missing, or ``NaN`` IC std
    (NaN-laden factor data must not leak a ``NaN``/``inf`` ratio into the report).
    """
    import math

    if not denominator or not math.isfinite(denominator):
        return 0.0
    ratio = numerator / denominator
    return ratio if math.isfinite(ratio) else 0.0


# --- commands ------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a momentum factor cross-sectionally over a universe.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="factor_tilt", universe=["AAPL", "MSFT", "NVDA"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.pipeline(config=config, factors=[{"name": "momentum", "params": {"window_length": 126}}])',  # noqa: E501
            ],
        ),
    ],
)
async def pipeline(
    config: BacktestConfig,
    factors: list[FactorSpec],
    provider: str | None = None,
) -> OBBject[FactorPanel]:
    """Evaluate factors cross-sectionally per session over the config window.

    Each spec in ``factors`` is resolved to a concrete factor node and evaluated
    look-ahead-free against the point-in-time feed; the result is the full
    per-session ``(date, asset)`` grid flattened into a serializable panel.

    Parameters
    ----------
    config : BacktestConfig
        Universe and date range define the cross-section and calendar.
    factors : list[str | dict]
        Factor specs: a registered name (``"momentum"``) or a mapping
        ``{"name": ..., "params": {...}}`` forwarding constructor kwargs.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[FactorPanel]
        Factor column names plus the per-(date, asset) exposure grid.
    """
    from openbb_backtest.pipeline.runner import pipeline as _run_pipeline

    provider_name = resolve_provider(provider)
    feed = _build_feed(config, provider_name)
    nodes = [_factor_for(spec) for spec in factors]
    logger.debug("pipeline: factors=%s universe=%s", [n.name for n in nodes], config.universe)

    panel = _run_pipeline(nodes, list(config.universe), config.start, config.end, feed)
    return OBBject(results=_to_panel_model(panel))


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Evaluate a factor's IC and quantile spread with alphalens.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="factor_tilt", universe=["AAPL", "MSFT", "NVDA"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.factor_eval(config=config, factor="momentum", quantiles=5, periods=[1, 5, 21])',  # noqa: E501
            ],
        ),
    ],
)
def factor_eval(
    config: BacktestConfig,
    factor: FactorSpec,
    quantiles: int = 5,
    periods: list[int] | None = None,
    provider: str | None = None,
) -> OBBject[FactorReport]:
    """Score a single factor's predictive power (alphalens-style diagnostics).

    Runs the factor through the cross-sectional pipeline, then hands the panel to
    the alphalens backend for information-coefficient and quantile-return
    analysis. The IC information ratio (mean / std) is derived per forward period.
    Requires ``alphalens-reloaded``; an actionable
    :class:`~openbb_backtest.errors.OptionalDependencyError` is raised when it is
    not installed.

    Parameters
    ----------
    config : BacktestConfig
        Universe and date range define the cross-section and calendar.
    factor : str | dict
        Factor spec: a registered name or ``{"name": ..., "params": {...}}``.
    quantiles : int, optional
        Number of factor quantiles to form (default 5).
    periods : list[int], optional
        Forward return periods in sessions (default ``[1, 5, 21]``).
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[FactorReport]
        IC mean / std / information-ratio per period and mean quantile returns.
    """
    from openbb_backtest.pipeline.runner import pipeline as _run_pipeline

    period_list = list(periods) if periods else [1, 5, 21]
    provider_name = resolve_provider(provider)
    feed = _build_feed(config, provider_name)
    node = _factor_for(factor)
    logger.debug("factor_eval: factor=%s quantiles=%s periods=%s", node.name, quantiles, period_list)

    panel = _run_pipeline([node], list(config.universe), config.start, config.end, feed)
    factor_values = panel.to_frame()[node.name]
    metrics = _alphalens_metrics(
        factor_values, feed, config, quantiles=quantiles, periods=period_list
    )
    ic_mean = metrics["ic_mean"]
    ic_std = metrics["ic_std"]
    ic_ir = {
        period: _safe_ratio(ic_mean[period], ic_std.get(period)) for period in ic_mean
    }
    return OBBject(
        results=FactorReport(
            factor=node.name,
            periods=period_list,
            quantiles=quantiles,
            ic_mean=ic_mean,
            ic_std=ic_std,
            ic_ir=ic_ir,
            quantile_returns=metrics["quantile_returns"],
        )
    )
