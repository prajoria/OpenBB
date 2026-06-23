"""Unit tests for the factor sub-router: pipeline / factor_eval (component 09.3).

Like the engine router (09.2), this router is orchestration, not math: it resolves
factor specs to :class:`~openbb_backtest.pipeline.factor.Factor` nodes, builds the
point-in-time feed, runs the cross-sectional pipeline, and (for ``factor_eval``)
delegates the alphalens-style IC / quantile diagnostics to a **lazily imported**
heavy backend that degrades to :class:`OptionalDependencyError` when absent.

The cross-sectional ``pipeline`` runner is exercised for real over a tiny in-memory
feed (it is light), while the alphalens backend is faked so unit tests never need
``alphalens-reloaded`` installed.

See ``docs/designs/backtest-design/09-api-surface.md`` §1.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

# ---- shared fakes / builders --------------------------------------------


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="c093_fake",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        engine="auto",
        initial_cash=Decimal("100000"),
    )
    params.update(kw)
    return BacktestConfig(**params)


_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
)


def _ohlcv_frame() -> pd.DataFrame:
    rows = []
    for sym, base, step in (("AAA", 100.0, 1.02), ("BBB", 100.0, 0.98)):
        price = base
        for sess in _SESSIONS:
            rows.append({"symbol": sym, "session": sess, "close": price})
            price *= step
    return pd.DataFrame(rows)


class _PriceFeed:
    """In-memory ``DataFeed`` (no look-ahead) for the pipeline test."""

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

    def as_of(self, symbol, field, when):
        return None


def _val(records, day, asset, col):
    for rec in records:
        if rec.asset == asset and rec.date.day == day:
            return rec.values[col]
    raise AssertionError(f"no record for {asset} on day {day}")


# ---- pipeline (real cross-sectional pipeline over an in-memory feed) -----


def test_pipeline_returns_obbject_factor_panel(monkeypatch):
    from openbb_backtest.models import FactorPanel
    from openbb_backtest.routers import factor_router as fr
    from openbb_core.app.model.obbject import OBBject

    monkeypatch.setattr(fr, "_build_feed", lambda config, provider: _PriceFeed(_ohlcv_frame()))
    out = asyncio.run(
        fr.pipeline(
            _config(),
            factors=[{"name": "momentum", "params": {"window_length": 2}}],
        )
    )
    assert isinstance(out, OBBject)
    assert isinstance(out.results, FactorPanel)
    assert out.results.factors == ["momentum_2"]


def test_pipeline_panel_is_full_grid_with_nan_for_insufficient_history(monkeypatch):
    import math

    from openbb_backtest.routers import factor_router as fr

    monkeypatch.setattr(fr, "_build_feed", lambda config, provider: _PriceFeed(_ohlcv_frame()))
    out = asyncio.run(
        fr.pipeline(
            _config(),
            factors=[{"name": "momentum", "params": {"window_length": 2}}],
        )
    )
    records = out.results.records
    # 5 sessions x 2 assets = full per-session grid.
    assert len(records) == 10
    # First session lacks a 2-bar window -> NaN (never a look-ahead fill).
    assert math.isnan(_val(records, 4, "AAA", "momentum_2"))
    # AAA rises +2%/bar; BBB falls -2%/bar.
    assert _val(records, 5, "AAA", "momentum_2") == pytest.approx(0.02)
    assert _val(records, 5, "BBB", "momentum_2") == pytest.approx(-0.02)


# ---- factor resolution seam ---------------------------------------------


def test_factor_for_resolves_registered_factor_with_params():
    from openbb_backtest.pipeline.factor import Momentum
    from openbb_backtest.routers import factor_router as fr

    default = fr._factor_for("momentum")
    assert isinstance(default, Momentum)
    assert default.window_length == 21
    tuned = fr._factor_for({"name": "momentum", "params": {"window_length": 5}})
    assert isinstance(tuned, Momentum)
    assert tuned.window_length == 5


def test_factor_for_unknown_name_raises_value_error():
    from openbb_backtest.routers import factor_router as fr

    with pytest.raises(ValueError, match="unknown factor"):
        fr._factor_for("not_a_factor")


# ---- factor_eval (alphalens backend faked) -------------------------------


def _fake_metrics(*args, **kwargs):
    return {
        "ic_mean": {"1": 0.1},
        "ic_std": {"1": 0.2},
        "quantile_returns": {"1": -0.01, "5": 0.03},
    }


def test_factor_eval_returns_obbject_factor_report(monkeypatch):
    from openbb_backtest.models import FactorReport
    from openbb_backtest.routers import factor_router as fr
    from openbb_core.app.model.obbject import OBBject

    monkeypatch.setattr(fr, "_build_feed", lambda config, provider: _PriceFeed(_ohlcv_frame()))
    monkeypatch.setattr(fr, "_alphalens_metrics", _fake_metrics)
    out = fr.factor_eval(_config(), factor="momentum", quantiles=5, periods=[1])
    assert isinstance(out, OBBject)
    assert isinstance(out.results, FactorReport)
    assert out.results.factor == "momentum_21"
    assert out.results.quantiles == 5
    assert out.results.periods == [1]
    assert out.results.quantile_returns == {"1": -0.01, "5": 0.03}


def test_factor_eval_computes_ic_ir_from_mean_and_std(monkeypatch):
    from openbb_backtest.routers import factor_router as fr

    monkeypatch.setattr(fr, "_build_feed", lambda config, provider: _PriceFeed(_ohlcv_frame()))
    monkeypatch.setattr(fr, "_alphalens_metrics", _fake_metrics)
    out = fr.factor_eval(_config(), factor="momentum", periods=[1])
    # IC IR is the risk-adjusted IC: mean / std = 0.1 / 0.2.
    assert out.results.ic_ir == {"1": pytest.approx(0.5)}
    assert out.results.ic_mean == {"1": pytest.approx(0.1)}


def test_factor_eval_missing_alphalens_raises_optional_dependency_error():
    # No monkeypatch on the backend: alphalens is genuinely absent, so the real
    # seam must degrade with an actionable install hint.
    from openbb_backtest.errors import OptionalDependencyError
    from openbb_backtest.routers import factor_router as fr

    factor_values = pd.Series(
        [0.1, 0.2],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2021-01-04"), "AAA"), (pd.Timestamp("2021-01-04"), "BBB")],
            names=["date", "asset"],
        ),
    )
    with pytest.raises(OptionalDependencyError) as excinfo:
        fr._alphalens_metrics(factor_values, object(), _config(), quantiles=5, periods=[1])
    message = str(excinfo.value)
    assert "alphalens" in message
    assert "pip install" in message


# ---- registration --------------------------------------------------------


def test_pipeline_factor_eval_routes_registered():
    from openbb_backtest.routers import factor_router as fr

    paths = {
        route.path
        for route in fr.router.api_router.routes
        if hasattr(route, "path")
    }
    assert {"/pipeline", "/factor_eval"} <= paths


# ---- Data models ---------------------------------------------------------


def test_factor_panel_data_model_roundtrips():
    from openbb_backtest.models import FactorExposure, FactorPanel

    panel = FactorPanel(
        factors=["momentum_2"],
        records=[
            FactorExposure(
                date=pd.Timestamp("2021-01-05"), asset="AAA",
                values={"momentum_2": 0.02},
            )
        ],
    )
    dumped = panel.model_dump()
    assert dumped["factors"] == ["momentum_2"]
    assert dumped["records"][0]["asset"] == "AAA"
    assert dumped["records"][0]["values"] == {"momentum_2": 0.02}


def test_factor_report_data_model_roundtrips():
    from openbb_backtest.models import FactorReport

    report = FactorReport(
        factor="momentum_21", periods=[1, 5], quantiles=5,
        ic_mean={"1": 0.1, "5": 0.08}, ic_std={"1": 0.2, "5": 0.2},
        ic_ir={"1": 0.5, "5": 0.4}, quantile_returns={"1": -0.01, "5": 0.03},
    )
    dumped = report.model_dump()
    assert dumped["factor"] == "momentum_21"
    assert dumped["periods"] == [1, 5]
    assert dumped["ic_ir"] == {"1": 0.5, "5": 0.4}
