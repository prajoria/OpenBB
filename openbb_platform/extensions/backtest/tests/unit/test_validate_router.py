"""Unit tests for the validate sub-router: validate / tearsheet (component 09.4).

Like the engine (09.2) and factor (09.3) routers, this router is orchestration,
not math. Two commands sit on top of the validation framework (component 08) and
the analytics layer (component 07):

- :func:`validate` resolves the strategy, runs the per-fold engine+analytics
  backend (the heavy, engine-coupled work — faked here behind ``_run_folds``),
  then assembles the report through the **real** ``build_validation_report`` so
  the verdict derivation is exercised at the router boundary.
- :func:`tearsheet` runs the engine (faked) and hands the equity curve to the
  **real** in-house ``build_tearsheet`` analytics, optionally exporting an HTML
  artifact via the lazily-imported quantstats backend (degrades to
  :class:`OptionalDependencyError` when absent).

Both commands are ``async def`` (long-running per ``09-api-surface.md`` §2) and
are driven via :func:`asyncio.run` here so the suite needs no asyncio plugin mode.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

# ---- shared fakes / builders --------------------------------------------


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="c094_fake",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 13),
        engine="auto",
        initial_cash=Decimal("100000"),
    )
    params.update(kw)
    return BacktestConfig(**params)


def _metrics(sharpe: float = 1.0):
    from openbb_backtest.models import PerformanceMetrics

    return PerformanceMetrics(
        cagr=0.1, sharpe=sharpe, sortino=1.0, calmar=1.0, max_drawdown=-0.05,
        volatility=0.1, var_95=-0.02, cvar_95=-0.03, win_rate=0.6,
        profit_factor=1.5, turnover=2.0,
    )


_EQUITY = (
    100000.0, 100500.0, 100200.0, 100800.0,
    101000.0, 100700.0, 101200.0, 101500.0,
)

#: A monotonically declining curve -> negative aggregate OOS Sharpe (for the
#: MinBTL non-positive-Sharpe guard test).
_DECLINING_EQUITY = (
    100000.0, 99400.0, 98900.0, 98200.0,
    97600.0, 97100.0, 96500.0, 95900.0,
)


def _mk_result(engine_name: str = "vectorized", equity=_EQUITY):
    from openbb_backtest.models import BacktestResult, EquityPoint

    equity_curve = [
        EquityPoint(
            date=datetime(2021, 1, 4 + i), equity=Decimal(str(v)),
            cash=Decimal("0"), exposure=1.0,
        )
        for i, v in enumerate(equity)
    ]
    return BacktestResult(
        equity_curve=equity_curve,
        trades=[],
        positions=[],
        metrics=_metrics(),
        engine_used=engine_name,
        config=_config(),
    )


class _FakeEngine:
    """Returns a deterministic, positions-free result for the tear sheet path."""

    def __init__(self, name: str = "vectorized", equity=_EQUITY) -> None:
        self.name = name
        self.equity = equity

    def run(self, strategy, config, feed, broker):
        return _mk_result(self.name, self.equity)


def _patch_common(monkeypatch):
    """Stub strategy factory, feed and broker builders (engine-agnostic plumbing)."""
    from openbb_backtest.routers import validate_router as vr

    monkeypatch.setattr(vr, "_strategy_factory", lambda name: (lambda **p: object()))
    monkeypatch.setattr(vr, "_build_feed", lambda config, provider: object())
    monkeypatch.setattr(vr, "_build_broker", lambda config: object())


def _fake_outcome(pbo: float = 0.1, dsr: float = 0.99, sharpe: float = 1.0):
    from openbb_backtest.models import FoldResult
    from openbb_backtest.routers import validate_router as vr

    return vr._FoldOutcome(
        folds=[FoldResult(fold=0, metrics=_metrics(sharpe), path_id=None)],
        oos_metrics=_metrics(sharpe),
        pbo=pbo,
        deflated_sharpe=dsr,
        min_backtest_length_years=1.5,
    )


# ---- validate ------------------------------------------------------------


def test_validate_returns_obbject_validation_report(monkeypatch):
    from openbb_backtest.models import ValidationReport
    from openbb_backtest.routers import validate_router as vr
    from openbb_core.app.model.obbject import OBBject

    _patch_common(monkeypatch)
    monkeypatch.setattr(vr, "_run_folds", lambda *a, **k: _fake_outcome())
    out = asyncio.run(vr.validate(_config(), method="wfo"))
    assert isinstance(out, OBBject)
    assert isinstance(out.results, ValidationReport)
    # pbo<0.2 & dsr>0.95 & oos sharpe>0 -> the real verdict gate says robust.
    assert out.results.verdict == "robust"
    assert out.results.pbo == pytest.approx(0.1)
    assert out.results.method == "wfo"


def test_validate_high_pbo_yields_overfit_verdict(monkeypatch):
    from openbb_backtest.routers import validate_router as vr

    _patch_common(monkeypatch)
    monkeypatch.setattr(vr, "_run_folds", lambda *a, **k: _fake_outcome(pbo=0.6))
    out = asyncio.run(vr.validate(_config()))
    # PBO >= 0.5 condemns the strategy regardless of the other metrics.
    assert out.results.verdict == "overfit"
    assert out.results.pbo == pytest.approx(0.6)


def test_validate_passes_method_through_to_report(monkeypatch):
    from openbb_backtest.routers import validate_router as vr

    _patch_common(monkeypatch)
    seen: dict[str, str] = {}

    def _capture(*args, method, **kwargs):
        seen["method"] = method
        return _fake_outcome()

    monkeypatch.setattr(vr, "_run_folds", _capture)
    out = asyncio.run(vr.validate(_config(), method="cpcv"))
    assert seen["method"] == "cpcv"
    assert out.results.method == "cpcv"


def test_validate_records_threshold_overrides(monkeypatch):
    from openbb_backtest.routers import validate_router as vr

    _patch_common(monkeypatch)
    monkeypatch.setattr(vr, "_run_folds", lambda *a, **k: _fake_outcome(pbo=0.1))
    # Tighten the robust PBO cut so 0.1 is no longer robust -> fragile band.
    out = asyncio.run(vr.validate(_config(), thresholds={"pbo_robust": 0.05}))
    assert out.results.thresholds["pbo_robust"] == pytest.approx(0.05)
    assert out.results.verdict == "fragile"


# ---- tearsheet (real in-house analytics over a faked engine result) ------


def test_tearsheet_returns_obbject_tearsheet(monkeypatch):
    from openbb_backtest.models import TearSheet
    from openbb_backtest.routers import validate_router as vr
    from openbb_core.app.model.obbject import OBBject

    _patch_common(monkeypatch)
    monkeypatch.setattr(vr, "_engine_for", lambda name: _FakeEngine(name))
    out = asyncio.run(vr.tearsheet(_config(), rolling_window=3))
    assert isinstance(out, OBBject)
    assert isinstance(out.results, TearSheet)
    # The real analytics layer produced metrics + a rolling-Sharpe series.
    assert out.results.metrics.sharpe == out.results.metrics.sharpe  # finite float
    assert len(out.results.rolling_sharpe) >= 1
    # No export requested -> the heavy artifact path was not taken.
    assert out.results.html_path is None


def test_tearsheet_export_sets_html_path(monkeypatch):
    from openbb_backtest.routers import validate_router as vr

    _patch_common(monkeypatch)
    monkeypatch.setattr(vr, "_engine_for", lambda name: _FakeEngine(name))
    monkeypatch.setattr(
        vr, "_export_html", lambda returns, *, title: "/exports/tearsheet_x.html"
    )
    out = asyncio.run(vr.tearsheet(_config(), rolling_window=3, export=True))
    assert out.results.html_path == "/exports/tearsheet_x.html"


def test_export_html_missing_quantstats_raises_optional_dependency_error(monkeypatch):
    # quantstats is the no-fallback export backend; when its import fails the
    # router seam must degrade to an actionable OptionalDependencyError.
    from openbb_backtest import analytics
    from openbb_backtest.errors import OptionalDependencyError
    from openbb_backtest.routers import validate_router as vr

    def _boom(*args, **kwargs):
        raise ImportError("No module named 'quantstats'")

    monkeypatch.setattr(analytics, "export_html", _boom)
    returns = pd.Series([0.0, 0.01, -0.005], name="returns")
    with pytest.raises(OptionalDependencyError) as excinfo:
        vr._export_html(returns, title="t")
    message = str(excinfo.value)
    assert "quantstats" in message
    assert "pip install" in message


# ---- registration & async contract --------------------------------------


def test_validate_tearsheet_routes_registered():
    from openbb_backtest.routers import validate_router as vr

    paths = {
        route.path
        for route in vr.router.api_router.routes
        if hasattr(route, "path")
    }
    assert {"/validate", "/tearsheet"} <= paths


def test_validate_and_tearsheet_are_async():
    # Long-running paths are declared async (09-api-surface.md §2) so the REST
    # layer can stream/poll a multi-minute CPCV run without blocking.
    from openbb_backtest.routers import validate_router as vr

    assert inspect.iscoroutinefunction(vr.validate)
    assert inspect.iscoroutinefunction(vr.tearsheet)


# ---- simplify hardening: _run_folds / _pbo_from_folds correctness ---------


class _SessionFeed:
    """Feed stub exposing only the session calendar ``_run_folds`` consumes."""

    def __init__(self, sessions):
        self._sessions = sessions

    def sessions(self, start, end):
        return self._sessions


def _daily_sessions(n: int = 8):
    return list(pd.date_range("2021-01-04", periods=n, freq="D"))


def test_validate_rejects_unknown_method(monkeypatch):
    # ``method`` is validated at the router boundary (against the model's
    # Literal["wfo", "cpcv"]) *before* the multi-minute fold backend runs, so a
    # typo fails fast and clearly instead of silently defaulting to walk-forward.
    from openbb_backtest.routers import validate_router as vr

    _patch_common(monkeypatch)
    calls = {"n": 0}

    def _should_not_run(*args, **kwargs):
        calls["n"] += 1
        return _fake_outcome()

    monkeypatch.setattr(vr, "_run_folds", _should_not_run)
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(vr.validate(_config(), method="bogus"))
    assert "bogus" in str(excinfo.value)
    assert calls["n"] == 0  # rejected before the heavy backend was invoked


def test_run_folds_rejects_unknown_method(monkeypatch):
    # Defense in depth: the seam itself refuses an unknown method rather than
    # silently treating anything non-"cpcv" as walk-forward.
    from openbb_backtest.routers import validate_router as vr

    monkeypatch.setattr(vr, "_engine_for", lambda name: _FakeEngine(name))
    feed = _SessionFeed(_daily_sessions())
    with pytest.raises(ValueError) as excinfo:
        vr._run_folds(lambda: object(), _config(), feed, object(), method="bogus")
    assert "bogus" in str(excinfo.value)


def test_pbo_from_folds_caps_partition_groups(monkeypatch):
    # CSCV enumerates C(n_groups, n_groups/2) partitions; using the raw OOS path
    # length as n_groups makes validate hang on realistic windows. The helper must
    # cap n_groups at the framework default (16) so the partition count is bounded.
    from openbb_backtest import validation
    from openbb_backtest.routers import validate_router as vr

    seen = {}

    def _spy_pbo(matrix, *, n_groups):
        seen["n_groups"] = n_groups
        return 0.5

    monkeypatch.setattr(validation, "pbo", _spy_pbo)
    curves = [pd.Series([float(i) for i in range(24)]) for _ in range(3)]
    result = vr._pbo_from_folds(curves)
    assert result == pytest.approx(0.5)
    assert seen["n_groups"] == 16  # min(16, 24) — bounded, not 24


def test_run_folds_deannualizes_sharpe_for_deflated_sharpe(monkeypatch):
    # deflated_sharpe expects a *per-observation* Sharpe (it applies sqrt(n_obs-1)
    # itself); feeding the annualized Sharpe saturates DSR to ~1 and corrupts the
    # verdict. _run_folds must de-annualize (divide by sqrt(sessions/yr)) first.
    from openbb_backtest import validation
    from openbb_backtest.routers import validate_router as vr

    monkeypatch.setattr(vr, "_engine_for", lambda name: _FakeEngine(name))
    captured = {}

    def _spy_dsr(sr, *, n_trials, skew, kurt, n_obs):
        captured["sr"] = sr
        return 0.99

    monkeypatch.setattr(validation, "deflated_sharpe", _spy_dsr)
    feed = _SessionFeed(_daily_sessions())
    outcome = vr._run_folds(lambda: object(), _config(), feed, object(), method="wfo")
    assert outcome.oos_metrics.sharpe != 0.0  # guard: the fixture has drift
    # 252 daily sessions/yr -> per-observation Sharpe = annualized / sqrt(252).
    assert captured["sr"] == pytest.approx(outcome.oos_metrics.sharpe / (252 ** 0.5))


def test_run_folds_builds_fresh_strategy_per_fold(monkeypatch):
    # A single strategy instance reused across folds leaks state into later OOS
    # windows for path-dependent strategies; _run_folds must build a fresh
    # instance for each fold's engine run (plus one probe for engine selection).
    from openbb_backtest.routers import validate_router as vr

    monkeypatch.setattr(vr, "_engine_for", lambda name: _FakeEngine(name))
    built = {"n": 0}

    def _counting_factory():
        built["n"] += 1
        return object()

    feed = _SessionFeed(_daily_sessions())
    outcome = vr._run_folds(_counting_factory, _config(), feed, object(), method="wfo")
    # one probe (engine selection) + one fresh strategy per fold.
    assert built["n"] == len(outcome.folds) + 1
    assert len(outcome.folds) >= 1


def test_run_folds_minbtl_guards_non_positive_sharpe(monkeypatch):
    # MinBTL = 2*ln(n)/SR^2 is only defined for SR > 0 and the primitive raises
    # otherwise. A losing strategy (negative aggregate OOS Sharpe) must not be
    # rescued by abs()/epsilon into a fabricated finite MinBTL; the helper should
    # report 0.0 (undefined) for a non-positive Sharpe.
    from openbb_backtest.routers import validate_router as vr

    monkeypatch.setattr(
        vr, "_engine_for", lambda name: _FakeEngine(name, equity=_DECLINING_EQUITY)
    )
    feed = _SessionFeed(_daily_sessions())
    outcome = vr._run_folds(lambda: object(), _config(), feed, object(), method="wfo")
    assert outcome.oos_metrics.sharpe < 0.0  # guard: the fixture really loses
    # Undefined for a non-positive Sharpe -> reported as 0.0, never fabricated.
    assert outcome.min_backtest_length_years == 0.0
