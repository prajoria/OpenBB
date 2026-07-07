"""Unit tests for the engine sub-router: run / sweep / reconcile (component 09.2).

The router's job is orchestration, not math: it resolves the engine per the
``engine=auto|vector|event`` policy (component 09.1), builds the feed/broker,
calls the engine, applies the **privacy sanitizer** (raw positions never cross
the router), and wraps the canonical result in an ``OBBject``. The heavy numeric
collaborators (engines, the vectorized sweep, the reconciliation gate) are tested
in their own modules, so here they are exercised through fakes / a small
in-memory feed to keep the router contract crisp.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

# ---- shared fakes / builders --------------------------------------------


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="c092_fake",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        engine="auto",
        initial_cash=Decimal("100000"),
    )
    params.update(kw)
    return BacktestConfig(**params)


def _mk_result(engine_name: str, equity=(100000.0, 101000.0), *, with_positions=True):
    from openbb_backtest.models import (
        BacktestResult,
        EquityPoint,
        PerformanceMetrics,
        PositionSnapshot,
    )

    metrics = PerformanceMetrics(
        cagr=0.1,
        sharpe=1.0,
        sortino=1.0,
        calmar=1.0,
        max_drawdown=-0.05,
        volatility=0.1,
        var_95=-0.02,
        cvar_95=-0.03,
        win_rate=0.6,
        profit_factor=1.5,
        turnover=2.0,
    )
    positions = (
        [
            PositionSnapshot(
                date=datetime(2021, 1, 4),
                symbol="AAA",
                quantity=Decimal("10"),
                market_value=Decimal("1000"),
                weight=1.0,
            )
        ]
        if with_positions
        else []
    )
    equity_curve = [
        EquityPoint(
            date=datetime(2021, 1, 4 + i),
            equity=Decimal(str(v)),
            cash=Decimal("0"),
            exposure=1.0,
        )
        for i, v in enumerate(equity)
    ]
    return BacktestResult(
        equity_curve=equity_curve,
        trades=[],
        positions=positions,
        metrics=metrics,
        engine_used=engine_name,
        config=_config(),
    )


class _FakeStrategy:
    """Minimal ``Strategy`` whose path-dependence is parametrizable."""

    def __init__(self, **params) -> None:
        self.id = "fake"
        self.path_dependent = bool(params.get("path_dependent", False))
        self.params = params

    def generate(self, data) -> pd.DataFrame:
        return pd.DataFrame({"weight": [0.5, 0.5]}, index=["AAA", "BBB"])


class _FakeEngine:
    """Records its name and returns a positions-bearing result."""

    def __init__(self, name: str, equity=(100000.0, 101000.0)) -> None:
        self.name = name
        self._equity = equity

    def run(self, strategy, config, feed, broker):
        return _mk_result(self.name, self._equity)


def _patch_run_collaborators(monkeypatch, *, engine_equity=None):
    """Stub the strategy factory, feed builder and engine factory.

    Returns the list that records every engine name ``run`` resolves to.
    """
    from openbb_backtest.routers import run_router as rr

    monkeypatch.setattr(
        rr, "_strategy_factory", lambda name: (lambda **p: _FakeStrategy(**p))
    )
    monkeypatch.setattr(rr, "_build_feed", lambda config, provider: object())

    requested: list[str] = []

    def _fake_engine_for(name: str):
        requested.append(name)
        equity = (engine_equity or {}).get(name, (100000.0, 101000.0))
        return _FakeEngine(name, equity)

    monkeypatch.setattr(rr, "_engine_for", _fake_engine_for)
    return requested


# ---- run -----------------------------------------------------------------


def test_run_returns_obbject_backtest_result(monkeypatch):
    from openbb_backtest.models import BacktestResult
    from openbb_backtest.routers import run_router as rr
    from openbb_core.app.model.obbject import OBBject

    _patch_run_collaborators(monkeypatch)
    out = asyncio.run(rr.run(_config(), engine="vector"))
    assert isinstance(out, OBBject)
    assert isinstance(out.results, BacktestResult)


def test_run_applies_privacy_sanitizer_strips_positions(monkeypatch):
    from openbb_backtest.routers import run_router as rr

    _patch_run_collaborators(monkeypatch)
    out = asyncio.run(rr.run(_config(), engine="vector"))
    # The fake engine returns a position snapshot; it must NOT cross the router.
    assert out.results.positions == []
    assert out.results.model_dump()["positions"] == []


def test_run_auto_resolves_to_vectorized(monkeypatch):
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    asyncio.run(rr.run(_config(), engine="auto"))
    assert requested == ["vectorized"]


def test_run_explicit_vector_alias_resolves_to_vectorized(monkeypatch):
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    asyncio.run(rr.run(_config(), engine="vector"))
    assert requested == ["vectorized"]


def test_run_explicit_event_passes_through(monkeypatch):
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    asyncio.run(rr.run(_config(), engine="event"))
    assert requested == ["event"]


def test_run_auto_picks_event_for_path_dependent_strategy(monkeypatch):
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    asyncio.run(
        rr.run(_config(), engine="auto", strategy_params={"path_dependent": True})
    )
    assert requested == ["event"]


def test_run_unknown_engine_raises_engine_selection_error(monkeypatch):
    from openbb_backtest.errors import EngineSelectionError
    from openbb_backtest.routers import run_router as rr

    _patch_run_collaborators(monkeypatch)
    with pytest.raises(EngineSelectionError):
        asyncio.run(rr.run(_config(), engine="turbo"))


# ---- config.engine precedence (bd-q7u5) ---------------------------------
#
# BacktestConfig declares an ``engine: EngineName`` field (models.py:108) but
# pre-fix ``run()`` silently ignored it — it always used the ``engine=``
# parameter's value (default ``"auto"``). The precedence rule is:
#
#   * If ``engine=`` is anything other than the ``"auto"`` sentinel, the
#     explicit call-site override wins over ``config.engine``.
#   * If ``engine="auto"`` (the default), fall back to ``config.engine`` so
#     the config field is finally honored.
#
# These four tests lock in each corner of the truth table.


def test_run_honors_config_engine_when_param_is_auto(monkeypatch):
    """config.engine='event' + engine='auto' (default) → event engine (bd-q7u5)."""
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    # Explicitly do NOT pass engine=, so the router sees the default "auto"
    # and MUST fall back to the config's engine field.
    asyncio.run(rr.run(_config(engine="event")))
    assert requested == ["event"], (
        "config.engine='event' was silently dropped — the router failed to "
        "fall back to config when engine=default 'auto' (bd-q7u5)."
    )


def test_run_explicit_param_overrides_config_engine(monkeypatch):
    """engine='vector' (explicit) beats config.engine='event' (bd-q7u5).

    Locks in the precedence rule: explicit call-site overrides win over stored
    config defaults. This matches the ergonomics of every other override in the
    router surface.
    """
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    asyncio.run(rr.run(_config(engine="event"), engine="vector"))
    assert requested == ["vectorized"]


def test_run_config_engine_event_auto_default(monkeypatch):
    """The bug scenario: BacktestConfig(engine='event') + bare run(config)."""
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    # Pre-fix: this silently used "auto" → "vectorized" (the field on config
    # was dead). Post-fix: config.engine wins, so we resolve to "event".
    asyncio.run(rr.run(_config(engine="event")))
    assert requested == ["event"]


def test_run_both_auto_still_resolves_via_path_dependence(monkeypatch):
    """Regression: engine='auto' + config.engine='auto' preserves auto-routing.

    When neither side pins an engine, the ``resolve_engine("auto", ...)``
    policy still runs — path-dependent strategies go to ``event``, everything
    else to ``vectorized``.
    """
    from openbb_backtest.routers import run_router as rr

    requested = _patch_run_collaborators(monkeypatch)
    asyncio.run(
        rr.run(
            _config(engine="auto"),
            engine="auto",
            strategy_params={"path_dependent": True},
        )
    )
    assert requested == ["event"]


def test_engine_for_lazily_imports_and_returns_registered_engine():
    # No monkeypatch: proves the lazy import + registry lookup wires the real
    # engine (heavy engine modules are only imported when first needed).
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.routers import run_router as rr

    engine = rr._engine_for("vectorized")
    assert isinstance(engine, VectorizedEngine)


# ---- sweep (real vectorized sweep over an in-memory feed) ----------------

_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
)


def _ohlcv_frame() -> pd.DataFrame:
    rows = []
    for sym, base, step in (("AAA", 100.0, 1.01), ("BBB", 100.0, 0.99)):
        price = base
        for sess in _SESSIONS:
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1_000_000.0,
                }
            )
            price *= step
    return pd.DataFrame(rows)


class _MatrixFeed:
    """In-memory ``DataFeed`` (no look-ahead) for the sweep test."""

    def __init__(self, ohlcv: pd.DataFrame) -> None:
        self._ohlcv = ohlcv

    def history(self, symbols, end, lookback):
        end = pd.Timestamp(end)
        frame = self._ohlcv
        mask = frame["symbol"].isin(symbols) & (frame["session"] <= end)
        return (
            frame.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    def sessions(self, start, end):
        s = self._ohlcv["session"]
        return pd.DatetimeIndex(
            sorted(s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))].unique())
        )


class _C092Tilt:
    """A sweepable tilt strategy registered for the sweep router test."""

    def __init__(self, tilt: float = 0.5) -> None:
        self.id = f"c092_tilt_{tilt}"
        self._tilt = float(tilt)

    def generate(self, data) -> pd.DataFrame:
        return pd.DataFrame(
            {"weight": [self._tilt, 1.0 - self._tilt]}, index=["AAA", "BBB"]
        )


@pytest.fixture
def _registered_tilt():
    from openbb_backtest.registry import _STRATEGIES, register_strategy

    name = "c092_tilt"
    if name not in _STRATEGIES:
        register_strategy(name)(_C092Tilt)
    yield name


def test_sweep_returns_obbject_sweep_result(monkeypatch, _registered_tilt):
    from openbb_backtest.models import SweepResult
    from openbb_backtest.routers import run_router as rr
    from openbb_core.app.model.obbject import OBBject

    monkeypatch.setattr(
        rr, "_build_feed", lambda config, provider: _MatrixFeed(_ohlcv_frame())
    )
    out = asyncio.run(
        rr.sweep(
            _config(strategy=_registered_tilt),
            param_grid={"tilt": [0.0, 0.5, 1.0]},
            rank_by="sharpe",
        )
    )
    assert isinstance(out, OBBject)
    assert isinstance(out.results, SweepResult)
    assert len(out.results.results) == 3
    assert out.results.rank_by == "sharpe"


def test_sweep_selects_best_combo(monkeypatch, _registered_tilt):
    from openbb_backtest.routers import run_router as rr

    monkeypatch.setattr(
        rr, "_build_feed", lambda config, provider: _MatrixFeed(_ohlcv_frame())
    )
    out = asyncio.run(
        rr.sweep(
            _config(strategy=_registered_tilt),
            param_grid={"tilt": [0.0, 1.0]},
            rank_by="sharpe",
        )
    )
    # AAA (+1%/day) all-in dominates BBB (-1%/day) on Sharpe.
    assert out.results.best == {"tilt": 1.0}


# ---- reconcile -----------------------------------------------------------


def test_reconcile_returns_obbject_report_when_engines_agree(monkeypatch):
    from openbb_backtest.models import ReconciliationReport
    from openbb_backtest.routers import run_router as rr
    from openbb_core.app.model.obbject import OBBject

    _patch_run_collaborators(monkeypatch)  # both engines return identical equity
    out = rr.reconcile(_config())
    assert isinstance(out, OBBject)
    assert isinstance(out.results, ReconciliationReport)
    assert out.results.passed is True
    assert out.results.reference_engine == "event"
    assert out.results.candidate_engine == "vectorized"


def test_reconcile_non_strict_reports_divergence(monkeypatch):
    from openbb_backtest.routers import run_router as rr

    _patch_run_collaborators(
        monkeypatch,
        engine_equity={
            "event": (100000.0, 101000.0),
            "vectorized": (100000.0, 200000.0),
        },
    )
    out = rr.reconcile(_config(), strict=False)
    assert out.results.passed is False
    assert out.results.max_divergence == pytest.approx(99000.0)


def test_reconcile_strict_raises_on_divergence(monkeypatch):
    from openbb_backtest.engine.reconcile import ReconciliationError
    from openbb_backtest.routers import run_router as rr

    _patch_run_collaborators(
        monkeypatch,
        engine_equity={
            "event": (100000.0, 101000.0),
            "vectorized": (100000.0, 200000.0),
        },
    )
    with pytest.raises(ReconciliationError):
        rr.reconcile(_config(), strict=True)


# ---- registration --------------------------------------------------------


def test_run_sweep_reconcile_routes_registered():
    from openbb_backtest.routers import run_router as rr

    paths = {
        route.path for route in rr.router.api_router.routes if hasattr(route, "path")
    }
    assert {"/run", "/sweep", "/reconcile"} <= paths


# ---- Data models ---------------------------------------------------------


def test_sweep_result_data_model_roundtrips():
    from openbb_backtest.models import PerformanceMetrics, SweepPoint, SweepResult

    m = PerformanceMetrics(
        cagr=0.1,
        sharpe=1.0,
        sortino=1.0,
        calmar=1.0,
        max_drawdown=-0.05,
        volatility=0.1,
        var_95=-0.02,
        cvar_95=-0.03,
        win_rate=0.6,
        profit_factor=1.5,
        turnover=2.0,
    )
    sr = SweepResult(
        results=[SweepPoint(params={"tilt": 1.0}, metrics=m)],
        best={"tilt": 1.0},
        best_metrics=m,
        rank_by="sharpe",
    )
    dumped = sr.model_dump()
    assert dumped["best"] == {"tilt": 1.0}
    assert dumped["rank_by"] == "sharpe"
    assert dumped["results"][0]["params"] == {"tilt": 1.0}


def test_reconciliation_report_data_model_fields():
    from openbb_backtest.models import ReconciliationReport

    report = ReconciliationReport(
        passed=True,
        max_divergence=1e-9,
        tolerance=1e-6,
        reference_engine="event",
        candidate_engine="vectorized",
    )
    assert report.passed is True
    assert report.reference_engine == "event"
    assert report.model_dump()["candidate_engine"] == "vectorized"
