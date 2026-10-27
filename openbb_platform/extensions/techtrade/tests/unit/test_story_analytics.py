"""TechTrade story analytics (#2316, N05d).

Hand-computed expectations, plus notebook parity: reviewed cells of the
TechTrade notebooks are executed with printing and rendering stubbed out,
and their variables are the oracle.
"""

# The oracle is the notebooks' own code, so these tests exec their cells.
# pylint: disable=exec-used,unused-argument,redefined-outer-name
# pylint: disable=too-many-positional-arguments

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from openbb_techtrade.engine.story_analytics import (
    actionable_plans,
    market_weather,
    replay_recommendation,
    replay_summary,
    round_trip_pnl,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
NOTEBOOKS = REPO_ROOT / "notebooks" / "techtrade"


def _cell(notebook: str, needle: str) -> str:
    cells = json.loads((NOTEBOOKS / notebook).read_text(encoding="utf-8"))["cells"]
    matches = [
        "".join(c["source"])
        for c in cells
        if c["cell_type"] == "code" and needle in "".join(c["source"])
    ]
    assert len(matches) == 1, (notebook, needle, len(matches))
    return matches[0]


def _notebook(name: str):
    return pytest.mark.skipif(
        not (NOTEBOOKS / name).is_file(), reason="TechTrade notebooks not in checkout"
    )


def _quiet() -> dict:
    return {"print": lambda *a, **k: None}


# --- market weather -------------------------------------------------------


def _closes(trend: float, wobble: float, days: int = 260) -> list[float]:
    """Build a deterministic price path: drift plus an alternating wobble."""
    return [100.0 * (1 + trend) ** i * (1 + wobble * (-1) ** i) for i in range(days)]


def test_calm_uptrend_is_green() -> None:
    """Low vol, above the 200-day, rising and a golden cross: all green."""
    weather = market_weather(_closes(0.002, 0.001))
    assert weather.volatility.tone == "green"
    assert weather.trend.tone == "green"
    assert weather.momentum.tone == "green"
    assert weather.cross.tone == "green"
    assert weather.verdict == "green"


def test_downtrend_is_red() -> None:
    """A steady decline is a bear regime with a death cross."""
    weather = market_weather(_closes(-0.002, 0.001))
    assert weather.trend.tone == "red"
    assert weather.cross.tone == "red"
    assert weather.verdict == "red"


def test_combined_signal_needs_both_sides() -> None:
    """TRADE needs green weather and a phase-7 score of at least 3.6."""
    calm = _closes(0.002, 0.001)
    assert market_weather(calm, p7_composite_score=3.7).combined == "trade"
    assert market_weather(calm, p7_composite_score=3.0).combined == "watch"
    assert market_weather(calm, p7_composite_score=2.7).combined == "pass"
    assert market_weather(calm).combined is None


def test_too_little_history_is_an_error() -> None:
    """A 200-day average cannot come from fewer than 200 closes."""
    with pytest.raises(ValueError, match="200"):
        market_weather(_closes(0.001, 0.001, days=150))


def _random_paths(count: int = 150):
    """Seeded random walks with drift and volatility spanning every threshold."""
    rng = np.random.default_rng(2316)
    for _ in range(count):
        drift = rng.uniform(-0.002, 0.002)
        vol = rng.uniform(0.004, 0.03)
        steps = rng.normal(drift, vol, 300)
        yield list(100 * np.exp(np.cumsum(steps))), float(rng.uniform(2.4, 4.2))


@_notebook("01-foundations-techtrade-and-analysis.ipynb")
def test_market_weather_matches_notebook(monkeypatch) -> None:
    """Every tone, the verdict and the combined call match §3 on 150 paths."""
    source = _cell(
        "01-foundations-techtrade-and-analysis.ipynb",
        "spy_raw = obb.equity.price.historical(",
    )
    colour = {"\x1b[92m": "green", "\x1b[93m": "yellow", "\x1b[91m": "red"}
    seen = set()
    for closes, p7 in _random_paths():
        frame = pd.DataFrame(
            {"date": pd.bdate_range("2025-01-01", periods=len(closes)), "close": closes}
        )

        def historical(frame=frame, **kwargs):
            return SimpleNamespace(to_df=frame.copy)

        fake = ModuleType("openbb")
        fake.obb = SimpleNamespace(
            equity=SimpleNamespace(price=SimpleNamespace(historical=historical))
        )
        monkeypatch.setitem(sys.modules, "openbb", fake)
        namespace = {
            "results": {"p7": SimpleNamespace(composite_score=p7, action_label="x")},
            "cfg": SimpleNamespace(symbol="MSFT"),
            **_quiet(),
        }
        exec(source, namespace)  # noqa: S102
        weather = market_weather(closes, p7_composite_score=p7)
        assert weather.volatility.tone == colour[namespace["rv_color"]]
        assert weather.trend.tone == colour[namespace["trend_color"]]
        assert weather.momentum.tone == colour[namespace["mom_color"]]
        assert weather.cross.tone == colour[namespace["cross_color"]]
        assert weather.verdict == colour[namespace["verdict_color"]]
        assert weather.volatility.value == pytest.approx(namespace["rv_pct"])
        # Elevated and High share a tone; the category word tells them apart.
        assert weather.volatility.label.split()[0] == namespace["rv_label"].split()[0]
        assert weather.combined.upper() in namespace["combined"]
        seen.add((weather.verdict, weather.combined))
    assert len(seen) >= 4, f"paths did not exercise enough outcomes: {seen}"


# --- actionable plans -----------------------------------------------------


def _plan(symbol, segment, score, conviction="High", rr=2.5, qty=100, bars=10):
    return {
        "symbol": symbol,
        "segment": segment,
        "score": score,
        "action": "BUY" if score > 0 else "SELL_SHORT",
        "conviction": conviction,
        "risk_reward": rr,
        "position_size": qty,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_price": 112.5,
        "time_stop_bars": bars,
        "as_of": "2026-10-23",
        "votes": [
            {"family": "trend", "name": "ema", "vote": 1.0, "weight": 0.2},
            {"family": "momentum", "name": "rsi", "vote": -0.5, "weight": 0.6},
        ],
    }


PLANS = [
    _plan("AAA", "Tech", 0.9),
    _plan("BBB", "Tech", -0.8),
    _plan("CCC", "Tech", 0.7),  # third Tech name: over the per-sector cap
    _plan("DDD", "Energy", 0.6, conviction="Medium"),
    _plan("EEE", "Energy", 0.5, rr=1.5),
    _plan("FFF", "Energy", 0.4, bars=None),
]


def test_actionable_filter_by_hand() -> None:
    """High conviction, r:r >= 2, at most two per sector, strongest first."""
    review = actionable_plans(PLANS)
    assert [p["symbol"] for p in review.actionable] == ["AAA", "BBB", "FFF"]
    assert review.actionable[0]["hold_by"] == "2026-11-06"  # Fri + 10 business days
    assert review.actionable[2]["hold_by"] is None
    assert [p["symbol"] for p in review.ranking][:3] == ["AAA", "BBB", "CCC"]


def test_audit_trail_orders_votes_by_contribution() -> None:
    """The top actionable plan's votes, largest |vote x weight| first."""
    audit = actionable_plans(PLANS).audit
    assert audit["symbol"] == "AAA"
    assert [(v["name"], v["contribution"]) for v in audit["votes"]] == [
        ("rsi", pytest.approx(-0.3)),
        ("ema", pytest.approx(0.2)),
    ]


def test_risk_scaling_is_linear() -> None:
    """Quantity scales with the risk fraction relative to the base risk."""
    scaled = actionable_plans(PLANS, risk_levels=(0.005, 0.02)).risk_scaling
    assert scaled == [
        {"risk": 0.005, "quantity": 50.0},
        {"risk": 0.02, "quantity": 200.0},
    ]


def test_no_plans_is_an_empty_review() -> None:
    """Nothing in, nothing out, and no audit."""
    review = actionable_plans([])
    assert (review.ranking, review.actionable, review.audit) == ([], [], None)


@_notebook("02-morning-scan.ipynb")
def test_actionable_plans_match_notebook() -> None:
    """The §6 actionable list and §10 risk scaling come out identical."""

    def _obj(p):
        rec = SimpleNamespace(
            conviction=p["conviction"],
            risk_reward=p["risk_reward"],
            time_stop_bars=p["time_stop_bars"],
            as_of=date.fromisoformat(p["as_of"]),
            action=p["action"],
            entry_price=p["entry_price"],
            stop_price=p["stop_price"],
            target_price=p["target_price"],
            position_size=p["position_size"],
        )
        return SimpleNamespace(
            symbol=p["symbol"],
            segment=p["segment"],
            signal=SimpleNamespace(score=p["score"]),
            recommendation=rec,
        )

    namespace = {"plans": [_obj(p) for p in PLANS], **_quiet()}
    exec(_cell("02-morning-scan.ipynb", "PER_SECTOR_CAP = 2"), namespace)  # noqa: S102
    review = actionable_plans(PLANS)
    assert [p["symbol"] for p in review.actionable] == [
        p.symbol for p in namespace["actionable"]
    ]
    hold = [
        namespace["max_hold_date"](
            p.recommendation.as_of, p.recommendation.time_stop_bars
        )
        for p in namespace["actionable"]
    ]
    assert [p["hold_by"] for p in review.actionable] == [
        None if h is None else str(h) for h in hold
    ]


# --- round-trip P&L -------------------------------------------------------


def _fill(side, price, qty=10, slippage=0.5, commission=1.0, ts="2026-10-20"):
    return {
        "side": side,
        "price": price,
        "quantity": qty,
        "slippage": slippage,
        "commission": commission,
        "timestamp": ts,
    }


def test_long_round_trip_by_hand() -> None:
    """Buy 10 at 100, sell at 110: gross 100, costs 3, net 97."""
    pnl = round_trip_pnl([_fill("buy", 100), _fill("sell", 110)])
    assert (pnl["gross"], pnl["costs"], pnl["net"]) == (100.0, 3.0, 97.0)
    assert pnl["net_pct_of_notional"] == pytest.approx(9.7)


def test_short_round_trip_by_hand() -> None:
    """Short 10 at 100, cover at 90: gross +100."""
    pnl = round_trip_pnl([_fill("sell_short", 100), _fill("buy_to_cover", 90)])
    assert pnl["gross"] == 100.0


def test_an_open_position_has_no_realized_pnl() -> None:
    """Entry without exit is reported as open, not as zero P&L."""
    assert round_trip_pnl([_fill("buy", 100)])["status"] == "open"
    assert round_trip_pnl([])["status"] == "no-fills"


@_notebook("03-single-position-deep-dive.ipynb")
def test_round_trip_matches_notebook() -> None:
    """Gross and net match §6 for long and short paths."""
    for fills in (
        [_fill("buy", 100, slippage=0.25), _fill("sell", 104.5, commission=0.0)],
        [_fill("sell_short", 50, qty=7), _fill("buy_to_cover", 53)],
    ):
        objects = [SimpleNamespace(**f) for f in fills]
        source = _cell("03-single-position-deep-dive.ipynb", "slippage_total = float(")
        namespace = {"fills": objects, **_quiet()}
        exec(source, namespace)  # noqa: S102
        pnl = round_trip_pnl(fills)
        assert pnl["gross"] == pytest.approx(namespace["gross"])
        assert pnl["net"] == pytest.approx(namespace["net"])


# --- replay ---------------------------------------------------------------


def _bars(rows):
    index = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        [r[1:] for r in rows], index=index, columns=["open", "high", "low", "close"]
    )


REC = {
    "entry_price": 100.0,
    "stop_price": 95.0,
    "target_price": 110.0,
    "position_size": 10,
    "action": "BUY",
}


def test_replay_hits_the_target_first() -> None:
    """Fill at the first open; the first leg touched decides."""
    bars = _bars(
        [("2026-10-01", 101, 104, 99, 103), ("2026-10-02", 103, 111, 102, 110)]
    )
    out = replay_recommendation(REC, bars)
    assert out["status"] == "target"
    assert out["realized"] == pytest.approx((110 - 101) * 10)
    assert out["bars_held"] == 1


def test_replay_summary_by_hand() -> None:
    """Two wins at 2R and one loss: win rate 2/3, expectancy 1.0R."""
    outcomes = [
        {"status": "target", "realized": 50.0, "r:r": 2.0, "conviction": "High"},
        {"status": "target", "realized": 30.0, "r:r": 2.0, "conviction": "Medium"},
        {"status": "stop", "realized": -20.0, "r:r": 2.0, "conviction": "High"},
        {"status": "open", "realized": 5.0, "r:r": 2.0, "conviction": "High"},
        {"status": "missing-levels", "conviction": "Low"},
    ]
    summary = replay_summary(outcomes)
    assert (summary["closed"], summary["open"], summary["failed"]) == (3, 1, 1)
    assert summary["win_rate"] == pytest.approx(2 / 3)
    assert summary["expectancy_r"] == pytest.approx(2 / 3 * 2.0 - 1 / 3)
    assert summary["total_realized"] == pytest.approx(65.0)
    by = {row["conviction"]: row for row in summary["by_conviction"]}
    assert by["High"]["n"] == 2 and by["High"]["win_rate"] == pytest.approx(0.5)


@_notebook("06-audit-and-replay.ipynb")
def test_replay_matches_notebook() -> None:
    """replay_one and the §4/§5 summary statistics come out identical."""
    namespace = {"date": date, **_quiet()}
    exec(_cell("06-audit-and-replay.ipynb", "def replay_one("), namespace)  # noqa: S102
    cases = [
        _bars([("2026-10-01", 101, 104, 94, 96)]),
        _bars([("2026-10-01", 101, 104, 99, 103), ("2026-10-05", 103, 111, 102, 110)]),
        _bars([("2026-10-01", 101, 104, 99, 103), ("2026-10-02", 103, 105, 101, 104)]),
        # One bar touches both legs: the stop is checked first and wins.
        _bars([("2026-10-01", 101, 104, 99, 103), ("2026-10-02", 103, 120, 80, 100)]),
    ]
    for action in ("BUY", "SELL_SHORT"):
        rec = dict(REC, action=action)
        if action == "SELL_SHORT":
            rec.update(stop_price=106.0, target_price=96.0)
        for bars in cases:
            expected = namespace["replay_one"](pd.Series(rec), bars)
            assert replay_recommendation(rec, bars) == pytest.approx(expected)
    outcomes = [
        {"status": "target", "realized": 50.0, "r:r": 2.5, "conviction": "High"},
        {"status": "stop", "realized": -20.0, "r:r": 2.0, "conviction": "High"},
        {"status": "target", "realized": 10.0, "r:r": 3.0, "conviction": "Low"},
        {"status": "open", "realized": 1.0, "r:r": 2.0, "conviction": "Low"},
    ]
    stats = {
        "replay_df": pd.DataFrame(outcomes),
        "WORKBOOK": Path("w.xlsx"),
        **_quiet(),
    }
    exec(_cell("06-audit-and-replay.ipynb", "avg_loss_r = -1.0"), stats)  # noqa: S102
    by_conviction = _cell("06-audit-and-replay.ipynb", 'closed.groupby("conviction")')
    exec(by_conviction, stats)  # noqa: S102
    summary = replay_summary(outcomes)
    assert summary["win_rate"] == pytest.approx(stats["win_rate"])
    assert summary["expectancy_r"] == pytest.approx(stats["expectancy"])
    assert summary["total_realized"] == pytest.approx(stats["total_realized"])
    nb = stats["by_conv"].set_index("conviction")
    for row in summary["by_conviction"]:
        assert row["n"] == nb.loc[row["conviction"], "n"]
        assert row["win_rate"] == pytest.approx(nb.loc[row["conviction"], "win_rate"])
        assert row["avg_realized"] == pytest.approx(
            nb.loc[row["conviction"], "avg_realized"]
        )


def test_nan_free_outputs() -> None:
    """Summaries of empty inputs are zeros, never NaN."""
    summary = replay_summary([])
    assert summary["win_rate"] == 0.0
    assert not any(isinstance(v, float) and math.isnan(v) for v in summary.values())
    assert np.isfinite(summary["expectancy_r"])
