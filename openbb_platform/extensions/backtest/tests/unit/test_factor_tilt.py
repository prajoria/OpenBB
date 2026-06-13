"""Unit tests for the factor-tilt strategy + Analysis score bridge (component 10.5).

``factor_tilt`` is a :class:`CrossSectionalStrategy` that tilts the book toward
symbols with a high per-symbol *factor score* supplied by an **injected** score
provider — either a static ``Mapping[symbol -> score]`` or a point-in-time
``Callable[[symbol, now], score]``. Injecting the provider keeps the strategy
deterministic, unit-testable, and look-ahead-safe (the callable only ever sees
``data.now``, never a future timestamp).

``analysis_bridge`` is a thin, separately-tested adapter that turns a
single-symbol ``Analysis.run_full_analysis`` result into one blended score
(Phase 7 composite + Phase 2 quality + Phase 4 valuation). It is exercised here
only with a *mocked* ``run_analysis`` callable; the live wiring is integration
gated (see ``tests/integration/test_factor_tilt_bridge.py``).

See ``docs/designs/backtest-design/10-strategy-library.md`` §3.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

_SESSIONS = pd.bdate_range("2021-01-04", periods=30)


# ---- in-memory market doubles -------------------------------------------


def _long_frame(closes: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    for sym, series in closes.items():
        for sess, px in zip(_SESSIONS[: len(series)], series):
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": float(px),
                    "high": float(px),
                    "low": float(px),
                    "close": float(px),
                    "volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


class _Market:
    """A minimal :class:`MarketData` exposing ``now`` (factor_tilt ignores prices)."""

    def __init__(self, now: pd.Timestamp | None = None) -> None:
        self._now = pd.Timestamp(now) if now is not None else _SESSIONS[-1]

    def window(self, symbols: list[str], lookback: int) -> pd.DataFrame:  # noqa: ARG002
        return pd.DataFrame()

    @property
    def now(self) -> pd.Timestamp:
        return self._now


class _MemFeed:
    def __init__(self, closes: dict[str, np.ndarray]) -> None:
        self._frame = _long_frame(closes)

    def history(self, symbols, end, lookback):  # noqa: ANN001
        end = pd.Timestamp(end)
        mask = self._frame["symbol"].isin(symbols) & (self._frame["session"] <= end)
        return (
            self._frame.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    def sessions(self, start, end):  # noqa: ANN001
        s = self._frame["session"]
        return pd.DatetimeIndex(
            sorted(s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))].unique())
        )


class _RecordingProvider:
    """A callable score provider that records every ``(symbol, now)`` it sees."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, pd.Timestamp]] = []

    def __call__(self, symbol: str, now: pd.Timestamp) -> float:
        self.calls.append((symbol, now))
        return self.scores[symbol]


# ---- factor_tilt: registration ------------------------------------------


def test_factor_tilt_registered_and_resolvable():
    import openbb_backtest.strategies  # noqa: F401
    from openbb_backtest.registry import list_strategies

    assert "factor_tilt" in list_strategies()


def test_factor_tilt_requires_a_score_provider():
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    with pytest.raises(ValueError, match="score_provider"):
        FactorTilt(symbols=["AAA"], score_provider=None)


# ---- factor_tilt: tilt mechanics ----------------------------------------


def test_factor_tilt_overweights_top_underweights_bottom():
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    scores = {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0}
    out = FactorTilt(symbols=["AAA", "BBB", "CCC"], score_provider=scores).generate(_Market())
    # Cross-sectional demeaning -> top score long, bottom short, ranked between.
    assert out.loc["AAA", "weight"] > out.loc["BBB", "weight"] > out.loc["CCC", "weight"]
    assert out.loc["AAA", "weight"] > 0.0 > out.loc["CCC", "weight"]


def test_factor_tilt_weights_sum_to_target_gross():
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    scores = {"AAA": 5.0, "BBB": 2.0, "CCC": 1.0}
    out = FactorTilt(
        symbols=["AAA", "BBB", "CCC"], score_provider=scores, gross=2.0
    ).generate(_Market())
    assert out["weight"].abs().sum() == pytest.approx(2.0)
    # Dollar-neutral: net exposure is ~zero.
    assert out["weight"].sum() == pytest.approx(0.0, abs=1e-9)


def test_factor_tilt_missing_symbol_scores_zero():
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    # CCC absent from the score map -> treated as a neutral 0.0 raw score.
    ft = FactorTilt(symbols=["AAA", "BBB", "CCC"], score_provider={"AAA": 3.0, "BBB": 1.0})
    ranks = ft.rank(_Market())
    assert ranks["CCC"] == 0.0


def test_factor_tilt_accepts_callable_point_in_time_provider():
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    provider = _RecordingProvider({"AAA": 4.0, "BBB": 1.0})
    market = _Market(now=_SESSIONS[10])
    ft = FactorTilt(symbols=["AAA", "BBB"], score_provider=provider)
    out = ft.generate(market)
    # The callable was queried per symbol, always as-of data.now (no future peek).
    assert {sym for sym, _ in provider.calls} == {"AAA", "BBB"}
    assert all(ts == market.now for _, ts in provider.calls)
    assert out.loc["AAA", "weight"] > out.loc["BBB", "weight"]


def test_factor_tilt_is_deterministic_given_same_inputs():
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    scores = {"AAA": 2.5, "BBB": 4.0, "CCC": 1.5}
    ft = FactorTilt(symbols=["AAA", "BBB", "CCC"], score_provider=scores)
    pd.testing.assert_frame_equal(ft.generate(_Market()), ft.generate(_Market()))


def test_factor_tilt_runs_e2e_on_vectorized_engine():
    from openbb_backtest.engine.execution import RealisticBroker
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    closes = {
        "AAA": np.linspace(100.0, 130.0, len(_SESSIONS)),
        "BBB": np.linspace(100.0, 80.0, len(_SESSIONS)),
    }
    cfg = BacktestConfig(
        strategy="factor_tilt",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=_SESSIONS[-1].date(),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    res = VectorizedEngine().run(
        FactorTilt(symbols=["AAA", "BBB"], score_provider={"AAA": 3.0, "BBB": 1.0}),
        cfg,
        _MemFeed(closes),
        RealisticBroker(cfg.commission, cfg.slippage),
    )
    assert len(res.equity_curve) == len(_SESSIONS)


# ---- analysis_bridge (mocked run_full_analysis) -------------------------


def _fake_results(*, composite=None, quality=None, mos=None) -> dict:
    out: dict = {}
    if composite is not None:
        out["p7"] = SimpleNamespace(composite_score=composite, action_label="Buy")
    if quality is not None:
        out["p2"] = SimpleNamespace(score=quality)
    if mos is not None:
        out["p4"] = SimpleNamespace(margin_of_safety=mos)
    return out


def test_analysis_bridge_blends_phase_scores_with_default_weights():
    from openbb_backtest.strategies.analysis_bridge import make_analysis_score_provider

    def fake_run(symbol: str) -> dict:  # noqa: ARG001
        return _fake_results(composite=4.0, quality=3.0, mos=0.2)

    provider = make_analysis_score_provider(run_analysis=fake_run)
    # default blend: 0.5*composite + 0.3*quality + 0.2*(mos*5)
    # = 0.5*4 + 0.3*3 + 0.2*(0.2*5) = 2.0 + 0.9 + 0.2 = 3.1
    assert provider("MSFT", _SESSIONS[-1]) == pytest.approx(3.1)


def test_analysis_bridge_honors_custom_weights():
    from openbb_backtest.strategies.analysis_bridge import make_analysis_score_provider

    def fake_run(symbol: str) -> dict:  # noqa: ARG001
        return _fake_results(composite=4.0, quality=2.0, mos=0.0)

    provider = make_analysis_score_provider(
        run_analysis=fake_run, weights={"composite": 1.0, "quality": 0.0, "valuation": 0.0}
    )
    assert provider("MSFT", _SESSIONS[-1]) == pytest.approx(4.0)


def test_analysis_bridge_missing_phases_default_to_zero():
    from openbb_backtest.strategies.analysis_bridge import make_analysis_score_provider

    def fake_run(symbol: str) -> dict:  # noqa: ARG001
        return _fake_results(composite=2.0)  # no p2 / p4

    provider = make_analysis_score_provider(run_analysis=fake_run)
    # 0.5*2.0 + 0.3*0 + 0.2*0 = 1.0
    assert provider("MSFT", _SESSIONS[-1]) == pytest.approx(1.0)


def test_analysis_bridge_rejects_unknown_weight_key():
    from openbb_backtest.strategies.analysis_bridge import make_analysis_score_provider

    with pytest.raises(ValueError, match="weight"):
        make_analysis_score_provider(run_analysis=lambda s: {}, weights={"bogus": 1.0})


def test_analysis_bridge_feeds_factor_tilt_end_to_end():
    from openbb_backtest.strategies.analysis_bridge import make_analysis_score_provider
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    table = {
        "AAA": _fake_results(composite=4.5, quality=4.0, mos=0.3),
        "BBB": _fake_results(composite=2.0, quality=2.5, mos=-0.1),
    }
    provider = make_analysis_score_provider(run_analysis=lambda s: table[s])
    out = FactorTilt(symbols=["AAA", "BBB"], score_provider=provider).generate(_Market())
    # AAA scores higher on every phase -> it is the long leg.
    assert out.loc["AAA", "weight"] > 0.0 > out.loc["BBB", "weight"]
