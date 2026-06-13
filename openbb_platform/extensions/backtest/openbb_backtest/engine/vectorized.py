"""Vectorized in-house research engine (component 04).

The high-throughput ``(T, S)`` matrix engine for fast parameter sweeps. It
implements the :class:`~openbb_backtest.interfaces.Engine` protocol and shares
the same :class:`~openbb_backtest.engine.execution` cost model as the
event-driven engine, so the reconciliation gate (``engine/reconcile.py``) is
meaningful.

Design highlights (see ``docs/designs/backtest-design/04-vectorized-engine.md``):

- **Mandatory 1-bar lag** — :func:`lag_weights` is applied unconditionally inside
  the engine, so a strategy can never fill on its own signal bar.
- **Numba hot paths** — the inherently sequential kernels (``_running_drawdown``,
  ``_apply_constraints``, ``_tax_lot_pnl``, ``_volume_cap_fills``) are ``@njit``
  compiled when numba is installed and run as *correct* pure-Python otherwise.
  CPU is always correct and is the default.
- **CPU NumPy math** — the matrix accounting runs on NumPy (the default and only
  backend wired here). On-device GPU batching is a separate, later component
  (component 13); the kernels are kept array-module-agnostic so that tier can
  drop in without reworking this math.
"""

from __future__ import annotations

import itertools
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timezone

import numpy as np
import pandas as pd

from openbb_backtest.interfaces import DataFeed, Strategy
from openbb_backtest.models import (
    BacktestConfig,
    BacktestResult,
    CommissionModel,
    EquityPoint,
    PerformanceMetrics,
    SlippageModel,
)
from openbb_backtest.registry import register_engine

# --- Optional Numba ------------------------------------------------------
# Kernels are written once and JIT-compiled when numba is present; otherwise
# the identity decorator runs the same source as pure-Python (always correct).
try:  # pragma: no cover - exercised by whichever path is installed
    from numba import njit

    _HAS_NUMBA = True
except Exception:  # pragma: no cover - numba is an optional accelerator

    def njit(*args, **kwargs):  # type: ignore[misc]
        """No-op ``@njit`` shim used when numba is not installed."""
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def _wrap(func):
            return func

        return _wrap

    _HAS_NUMBA = False


_BPS = 1e4


# --- Accounting math (pure NumPy, GPU-portable via xp) -------------------


def lag_weights(weights: np.ndarray) -> np.ndarray:
    """Shift target weights down one session (the MANDATORY look-ahead guard).

    Row ``t`` of the result holds the weights *generated* at ``t-1``; the first
    session holds nothing, so a strategy can never trade on its own signal bar.
    """
    lagged = np.zeros_like(weights)
    if weights.shape[0] > 1:
        lagged[1:] = weights[:-1]
    return lagged


def simple_returns(close: np.ndarray) -> np.ndarray:
    """Per-session simple returns of ``close`` (first row is zero)."""
    rets = np.zeros_like(close, dtype=float)
    if close.shape[0] > 1:
        prev = close[:-1]
        rets[1:] = np.where(prev != 0, (close[1:] - prev) / prev, 0.0)
    return rets


def turnover(weights_lag: np.ndarray) -> np.ndarray:
    """Per-session turnover: the sum of absolute weight changes across symbols."""
    delta = np.diff(weights_lag, axis=0, prepend=np.zeros((1, weights_lag.shape[1])))
    return np.abs(delta).sum(axis=1)


def cost_rate(commission: CommissionModel, slippage: SlippageModel) -> float:
    """Flat per-turnover cost rate combining slippage and percent commission.

    The vectorized path expresses costs as a single rate applied to weight
    turnover. ``fixed_bps`` slippage and ``percent`` commission map directly;
    notional-based kinds (handled exactly by the event engine) cannot be
    expressed as a flat turnover rate, so they contribute zero here and are
    reconciled separately. When such a kind carries a non-zero value it is being
    silently dropped from the fast path, so a :class:`UserWarning` is emitted to
    flag the modeling gap (the zero-valued frictionless defaults stay silent).
    """
    slip = float(slippage.value) / _BPS if slippage.kind == "fixed_bps" else 0.0
    comm = float(commission.value) if commission.kind == "percent" else 0.0
    if commission.kind != "percent" and float(commission.value) != 0.0:
        warnings.warn(
            f"vectorized cost model cannot express {commission.kind!r} commission; "
            "dropping it from the fast path (reconcile against the event engine)",
            UserWarning,
            stacklevel=2,
        )
    if slippage.kind != "fixed_bps" and float(slippage.value) != 0.0:
        warnings.warn(
            f"vectorized cost model cannot express {slippage.kind!r} slippage; "
            "dropping it from the fast path (reconcile against the event engine)",
            UserWarning,
            stacklevel=2,
        )
    return slip + comm


def portfolio_returns(
    weights_lag: np.ndarray, returns: np.ndarray, costs: np.ndarray
) -> np.ndarray:
    """Per-session portfolio return: ``(w_lag * returns).sum(axis=1) - costs``."""
    return (weights_lag * returns).sum(axis=1) - costs


def equity_curve_values(initial_cash: float, port_returns: np.ndarray) -> np.ndarray:
    """Compound ``port_returns`` from ``initial_cash`` into an equity curve."""
    return initial_cash * np.cumprod(1.0 + port_returns)


# --- Numba hot-path kernels ----------------------------------------------


@njit(cache=True)
def _running_drawdown(equity: np.ndarray) -> np.ndarray:
    """Per-session drawdown ``equity / running_peak - 1`` (sequential max-so-far)."""
    n = equity.shape[0]
    out = np.zeros(n)
    peak = equity[0] if n > 0 else 0.0
    for i in range(n):
        peak = max(peak, equity[i])
        if peak != 0.0:
            out[i] = equity[i] / peak - 1.0
    return out


@njit(cache=True)
def _apply_constraints(
    weights: np.ndarray, max_pos: float, restricted: np.ndarray
) -> np.ndarray:
    """Clamp each weight to ``±max_pos``, zero restricted names, renormalize gross.

    If the resulting gross exposure exceeds 1.0 the vector is scaled so
    ``sum(|w|) == 1`` (no leverage beyond fully-invested by default).
    """
    n = weights.shape[0]
    out = np.empty(n)
    for i in range(n):
        w = weights[i]
        if restricted[i]:
            w = 0.0
        elif w > max_pos:
            w = max_pos
        elif w < -max_pos:
            w = -max_pos
        out[i] = w
    gross = 0.0
    for i in range(n):
        gross += abs(out[i])
    if gross > 1.0:
        for i in range(n):
            out[i] = out[i] / gross
    return out


@njit(cache=True)
def _volume_cap_fills(
    orders: np.ndarray, volume: np.ndarray, cap: float
) -> np.ndarray:
    """Partial-fill each order at ``cap * volume``, preserving sign."""
    n = orders.shape[0]
    out = np.empty(n)
    for i in range(n):
        limit = cap * volume[i]
        q = orders[i]
        if q > limit:
            out[i] = limit
        elif q < -limit:
            out[i] = -limit
        else:
            out[i] = q
    return out


@njit(cache=True)
def _tax_lot_pnl(qty: np.ndarray, price: np.ndarray, method: int) -> float:
    """Realized PnL from lot matching. ``method``: 0=FIFO, 1=LIFO.

    Positive ``qty`` opens a lot at ``price``; negative ``qty`` realizes against
    open lots from the front (FIFO) or back (LIFO).
    """
    n = qty.shape[0]
    lot_qty = np.zeros(n)
    lot_px = np.zeros(n)
    n_lots = 0
    realized = 0.0
    for i in range(n):
        q = qty[i]
        p = price[i]
        if q > 0.0:
            lot_qty[n_lots] = q
            lot_px[n_lots] = p
            n_lots += 1
        elif q < 0.0:
            remaining = -q
            while remaining > 0.0 and n_lots > 0:
                if method == 0:  # FIFO: oldest non-empty lot from the front
                    idx = 0
                    while idx < n_lots and lot_qty[idx] == 0.0:
                        idx += 1
                    if idx >= n_lots:
                        break
                else:  # LIFO: newest non-empty lot from the back
                    idx = n_lots - 1
                    while idx >= 0 and lot_qty[idx] == 0.0:
                        idx -= 1
                    if idx < 0:
                        break
                take = lot_qty[idx]
                take = min(take, remaining)
                realized += (p - lot_px[idx]) * take
                lot_qty[idx] -= take
                remaining -= take
    return realized


# --- Point-in-time MarketData view ---------------------------------------


class _PITView:
    """A :class:`~openbb_backtest.interfaces.MarketData` bounded at ``now``.

    Delegates to the feed's look-ahead-safe ``history`` so a strategy can only
    ever see bars up to the current session.
    """

    def __init__(self, feed: DataFeed, now: pd.Timestamp) -> None:
        self._feed = feed
        self._now = pd.Timestamp(now)

    @property
    def now(self) -> pd.Timestamp:
        """Current session timestamp."""
        return self._now

    def window(self, symbols: list[str], lookback: int) -> pd.DataFrame:
        """Trailing ``lookback`` bars for ``symbols`` up to (and including) now."""
        return self._feed.history(symbols, end=self._now, lookback=lookback)


class _MemoizingFeed:
    """A :class:`~openbb_backtest.interfaces.DataFeed` that caches ``history``.

    A sweep re-queries the *same* point-in-time windows (identical symbols, end
    session and lookback) for every parameter combo — only the weights differ.
    Wrapping the feed here collapses those repeated reads to one per unique
    window, so feed I/O is independent of grid size (design §3). Cached frames
    are returned as copies so a strategy can never mutate another combo's view.
    """

    def __init__(self, inner: DataFeed) -> None:
        self._inner = inner
        self._cache: dict[tuple, pd.DataFrame] = {}

    def history(self, symbols, end, lookback) -> pd.DataFrame:
        """Return cached trailing history, reading the inner feed only on a miss."""
        key = (tuple(symbols), pd.Timestamp(end), int(lookback))
        frame = self._cache.get(key)
        if frame is None:
            frame = self._inner.history(symbols, end=end, lookback=lookback)
            self._cache[key] = frame
        return frame.copy()

    def sessions(self, start, end) -> pd.DatetimeIndex:
        """Delegate the trading-session calendar to the wrapped feed."""
        return self._inner.sessions(start, end)

    def as_of(self, symbol, field, when) -> float | None:
        """Delegate point-in-time fundamentals lookups to the wrapped feed."""
        return self._inner.as_of(symbol, field, when)


# --- Metrics (self-contained; C07 may later centralize) ------------------

_PERIODS_PER_YEAR = 252.0


def _metrics_from_returns(
    equity: np.ndarray,
    port_returns: np.ndarray,
    turnover_series: np.ndarray,
    *,
    periods_per_year: float = _PERIODS_PER_YEAR,
) -> PerformanceMetrics:
    """Compute summary metrics from the daily portfolio return series.

    Closed-form, dependency-free statistics so the vectorized engine is
    self-contained. Annualizes with ``periods_per_year`` (252 trading days by
    default); the analytics fallback reuses this with the config calendar's
    sessions/year so the two layers agree by construction.
    """
    n = port_returns.shape[0]
    std = float(port_returns.std()) if n > 1 else 0.0
    vol = std * np.sqrt(periods_per_year)
    mean = float(port_returns.mean()) if n else 0.0
    sharpe = mean / std * np.sqrt(periods_per_year) if std > 0 else 0.0
    downside = port_returns[port_returns < 0]
    dstd = float(downside.std()) if downside.size > 1 else 0.0
    sortino = mean / dstd * np.sqrt(periods_per_year) if dstd > 0 else 0.0
    dd = _running_drawdown(equity)
    max_dd = float(dd.min()) if n else 0.0
    years = n / periods_per_year if n else 0.0
    total = float(equity[-1] / equity[0]) if n and equity[0] != 0 else 1.0
    cagr = total ** (1.0 / years) - 1.0 if years > 0 and total > 0 else 0.0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0
    var_95 = float(np.percentile(port_returns, 5)) if n else 0.0
    tail = port_returns[port_returns <= var_95]
    cvar_95 = float(tail.mean()) if tail.size else var_95
    wins = port_returns[port_returns > 0]
    losses = port_returns[port_returns < 0]
    win_rate = float(wins.size / n) if n else 0.0
    gross_loss = float(-losses.sum())
    profit_factor = float(wins.sum()) / gross_loss if gross_loss > 0 else 0.0
    ann_turnover = float(turnover_series.mean()) * periods_per_year if n else 0.0
    return PerformanceMetrics(
        cagr=cagr,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown=max_dd,
        volatility=vol,
        var_95=var_95,
        cvar_95=cvar_95,
        win_rate=win_rate,
        profit_factor=profit_factor,
        turnover=ann_turnover,
    )


def _as_utc(session: pd.Timestamp) -> pd.Timestamp:
    """Coerce a (possibly naive) session timestamp to tz-aware UTC."""
    ts = pd.Timestamp(session)
    return ts.tz_localize(timezone.utc) if ts.tzinfo is None else ts.tz_convert("UTC")


# --- The engine ----------------------------------------------------------


@dataclass
class _PreparedMarket:
    """The session axis, symbol axis and shared ``(T, S)`` returns matrix."""

    sessions: pd.DatetimeIndex
    symbols: list[str]
    returns: np.ndarray


def _build_weights(
    strategy: Strategy,
    feed: DataFeed,
    sessions: pd.DatetimeIndex,
    symbols: list[str],
) -> np.ndarray:
    """Query the strategy at every session into a ``(T, S)`` weight matrix."""
    weights = np.zeros((len(sessions), len(symbols)))
    col = {sym: j for j, sym in enumerate(symbols)}
    for i, sess in enumerate(sessions):
        gen = strategy.generate(_PITView(feed, sess))
        if gen is None or len(gen) == 0:
            continue
        wcol = "weight" if "weight" in gen.columns else "signal"
        pairs = [
            (col[s], float(v))
            for s, v in gen[wcol].items()
            if s in col and pd.notna(v)
        ]
        if pairs:
            idx, vals = zip(*pairs)
            weights[i, list(idx)] = vals
    return weights


def _prepare(config: BacktestConfig, feed: DataFeed) -> _PreparedMarket:
    """Compute the shared ``(T, S)`` returns matrix ONCE for a feed/config.

    Sweeps reuse this across every parameter combo, which is the core
    performance lever (design §3 — returns matrix computed once and shared).
    Raises :class:`ValueError` when the calendar yields no sessions, so callers
    get a clear domain error rather than an opaque indexing failure.
    """
    sessions = pd.DatetimeIndex(feed.sessions(config.start, config.end))
    if len(sessions) == 0:
        raise ValueError(
            "no trading sessions in "
            f"[{config.start}, {config.end}] for calendar {config.calendar!r}"
        )
    symbols = list(config.universe)
    hist = feed.history(symbols, end=sessions[-1], lookback=len(sessions))
    close = hist.pivot_table(
        index="session", columns="symbol", values="close"
    ).reindex(index=sessions, columns=symbols)
    returns = np.nan_to_num(simple_returns(close.to_numpy(dtype=float)))
    return _PreparedMarket(sessions=sessions, symbols=symbols, returns=returns)


def _evaluate(
    weights: np.ndarray,
    market: _PreparedMarket,
    config: BacktestConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Turn a raw ``(T, S)`` weight matrix into ``(equity, port, turnover, w_lag)``.

    Applies the MANDATORY :func:`lag_weights` shift, the shared cost rate and the
    compounding — the single accounting path used by both :meth:`VectorizedEngine.run`
    and :func:`sweep` so their numbers match by construction. The lagged weight
    matrix is returned so callers reuse it (e.g. for exposure) without shifting
    twice.
    """
    w_lag = lag_weights(weights)
    rate = cost_rate(config.commission, config.slippage)
    turnover_series = turnover(w_lag)
    costs = turnover_series * rate
    port = portfolio_returns(w_lag, market.returns, costs)
    equity = equity_curve_values(float(config.initial_cash), port)
    return equity, port, turnover_series, w_lag


@register_engine("vectorized")
class VectorizedEngine:
    """High-throughput ``(T, S)`` matrix engine implementing ``Engine``.

    The matrix accounting runs on NumPy. The MANDATORY :func:`lag_weights` shift
    is applied inside :func:`_evaluate`, so no strategy can fill on its own
    signal bar.
    """

    name = "vectorized"

    def run(
        self,
        strategy: Strategy,
        config: BacktestConfig,
        feed: DataFeed,
        broker: object,
    ) -> BacktestResult:
        """Execute the vectorized backtest and return the canonical result."""
        market = _prepare(config, feed)
        weights = _build_weights(strategy, feed, market.sessions, market.symbols)
        equity, port, turnover_series, w_lag = _evaluate(weights, market, config)

        net_exposure = w_lag.sum(axis=1)
        equity_curve = [
            EquityPoint(
                date=_as_utc(sess),
                equity=_round_money(equity[i]),
                cash=_round_money(equity[i] * (1.0 - net_exposure[i])),
                exposure=float(net_exposure[i]),
            )
            for i, sess in enumerate(market.sessions)
        ]
        metrics = _metrics_from_returns(equity, port, turnover_series)
        return BacktestResult(
            equity_curve=equity_curve,
            trades=[],
            positions=[],
            metrics=metrics,
            engine_used=self.name,
            config=config,
        )


@dataclass
class SweepResult:
    """Outcome of a parameter sweep: per-combo metrics plus the best combo."""

    results: list[tuple[dict, PerformanceMetrics]]
    best: dict
    best_metrics: PerformanceMetrics
    rank_by: str


#: Metrics where a *smaller* value is better, so :func:`select_best` minimizes
#: them. Drawdown/VaR/CVaR are stored as signed negatives (closer to zero is
#: better), so they correctly stay in the default higher-is-better group.
_LOWER_IS_BETTER = frozenset({"volatility", "turnover"})


def select_best(
    results: Sequence[tuple[dict, PerformanceMetrics]], rank_by: str
) -> tuple[dict, PerformanceMetrics]:
    """Pick the ``(params, metrics)`` pair that optimizes ``rank_by``.

    ``rank_by`` must name a :class:`PerformanceMetrics` field. Most metrics are
    higher-is-better; the few in :data:`_LOWER_IS_BETTER` are minimized. Raises
    :class:`ValueError` for an unknown metric so a typo fails fast instead of
    silently ranking by ``None``.
    """
    if rank_by not in PerformanceMetrics.model_fields:
        valid = ", ".join(sorted(PerformanceMetrics.model_fields))
        raise ValueError(f"unknown rank_by {rank_by!r}; expected one of: {valid}")
    sign = -1.0 if rank_by in _LOWER_IS_BETTER else 1.0
    return max(results, key=lambda pm: sign * getattr(pm[1], rank_by))


def sweep(
    strategy_factory: Callable[..., Strategy],
    param_grid: Mapping[str, Sequence],
    config: BacktestConfig,
    feed: DataFeed,
    rank_by: str = "sharpe",
) -> SweepResult:
    """Evaluate ``strategy_factory`` across the cartesian product of ``param_grid``.

    The shared returns matrix is computed exactly once (via :func:`_prepare`) and
    reused for every combo — only the weight matrix is rebuilt per combo, and the
    feed is wrapped in a :class:`_MemoizingFeed` so repeated point-in-time reads
    collapse to one per unique window. ``rank_by`` names the
    :class:`PerformanceMetrics` field used to pick ``best`` (see
    :func:`select_best` for direction and validation).
    """
    if rank_by not in PerformanceMetrics.model_fields:
        valid = ", ".join(sorted(PerformanceMetrics.model_fields))
        raise ValueError(f"unknown rank_by {rank_by!r}; expected one of: {valid}")
    feed = _MemoizingFeed(feed)
    market = _prepare(config, feed)
    names = list(param_grid)
    combos = [
        dict(zip(names, values))
        for values in itertools.product(*(param_grid[n] for n in names))
    ]

    results: list[tuple[dict, PerformanceMetrics]] = []
    for params in combos:
        strategy = strategy_factory(**params)
        weights = _build_weights(strategy, feed, market.sessions, market.symbols)
        equity, port, turnover_series, _w_lag = _evaluate(weights, market, config)
        metrics = _metrics_from_returns(equity, port, turnover_series)
        results.append((params, metrics))

    best_params, best_metrics = select_best(results, rank_by)
    return SweepResult(
        results=results,
        best=best_params,
        best_metrics=best_metrics,
        rank_by=rank_by,
    )


#: NFR throughput target (design §3): a mid-range CPU should sustain at least
#: this many parameter combos per minute when the returns matrix is shared and
#: kernels are JIT-warmed (warm-up excluded). The GPU tier (component 13) raises
#: this to 100k via on-device batching.
TARGET_COMBOS_PER_MIN = 10_000


@dataclass
class BenchmarkResult:
    """Measured sweep throughput against the design NFR target."""

    n_combos: int
    elapsed_s: float
    combos_per_min: float
    target_combos_per_min: int
    result: SweepResult

    @property
    def meets_target(self) -> bool:
        """Whether measured throughput meets :data:`TARGET_COMBOS_PER_MIN`."""
        return self.combos_per_min >= self.target_combos_per_min


def benchmark_sweep(
    strategy_factory: Callable[..., Strategy],
    param_grid: Mapping[str, Sequence],
    config: BacktestConfig,
    feed: DataFeed,
    rank_by: str = "sharpe",
) -> BenchmarkResult:
    """Time a :func:`sweep` and report combos/min against the NFR target.

    This is the throughput harness referenced by the design's performance target
    (§3, ≥10k combos/min). It is intentionally a measuring tool rather than a
    hard-thresholded test: wall-clock asserts are flaky under shared CI load, so
    the harness *reports* throughput and travels with the documented target for
    comparison and regression tracking.
    """
    start = time.perf_counter()
    result = sweep(strategy_factory, param_grid, config, feed, rank_by=rank_by)
    elapsed = time.perf_counter() - start
    n = len(result.results)
    cpm = (n / elapsed * 60.0) if elapsed > 0 else float("inf")
    return BenchmarkResult(
        n_combos=n,
        elapsed_s=elapsed,
        combos_per_min=cpm,
        target_combos_per_min=TARGET_COMBOS_PER_MIN,
        result=result,
    )


def _round_money(value: float):
    """Convert a float to a Decimal with cent precision for money fields."""
    from decimal import ROUND_HALF_EVEN, Decimal

    return Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
