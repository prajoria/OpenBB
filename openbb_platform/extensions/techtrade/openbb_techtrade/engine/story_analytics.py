"""TechTrade notebook analytics as reusable functions (#2316).

The arithmetic the TechTrade notebooks run locally on top of the engine's
outputs, lifted here so the MCP story tools compute the same answers:

- :func:`market_weather` — chapter 1's SPY traffic light (volatility, trend,
  momentum, moving-average cross) and its combination with a phase-7 score.
- :func:`actionable_plans` — chapter 2's ranking, actionable filter,
  time-stop dates, vote audit and risk-knob scaling over scan plans.
- :func:`round_trip_pnl` — chapter 3's realized P&L for a simulated path.
- :func:`replay_recommendation` and :func:`replay_summary` — chapter 6's
  forward-bar replay of a recommendation and the discipline statistics.
- :func:`config_diff` — chapter 5's default-versus-candidate knob table.

Pure functions over plain mappings and bars; no provider calls.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class WeatherReading:
    """One traffic-light component."""

    tone: str  # "green", "yellow" or "red"
    value: float
    label: str


@dataclass(frozen=True)
class MarketWeather:
    """Chapter 1's market-conditions read."""

    volatility: WeatherReading
    trend: WeatherReading
    momentum: WeatherReading
    cross: WeatherReading
    verdict: str
    action: str
    # "trade", "watch" or "pass" when a phase-7 score was given.
    combined: str | None


_VERDICT_ACTIONS = {
    "green": "Proceed using the position size from Phase 5 (recommended_size).",
    "yellow": "Halve Phase 5 recommended_size. Use hard stop at ATR x 1.5.",
    "red": "Stay in cash or paper-trade only. Re-run daily.",
}


def market_weather(
    closes: Sequence[float], *, p7_composite_score: float | None = None
) -> MarketWeather:
    """Read market conditions from a daily close series (oldest first).

    Needs at least 200 closes for the 200-day average; raises
    :class:`ValueError` otherwise.
    """
    close = pd.Series([float(c) for c in closes]).dropna()
    if len(close) < 200:
        raise ValueError(
            f"need at least 200 daily closes for the 200-day average, got {len(close)}"
        )
    returns = close.pct_change().dropna()
    vol = float(returns.rolling(21).std().iloc[-1] * math.sqrt(TRADING_DAYS)) * 100
    if vol < 15:
        volatility = WeatherReading("green", vol, "Low — market is calm")
    elif vol < 20:
        volatility = WeatherReading("green", vol, "Normal — typical operating range")
    elif vol < 25:
        volatility = WeatherReading("yellow", vol, "Elevated — reduce position size")
    elif vol < 35:
        volatility = WeatherReading("yellow", vol, "High — caution, tight stops")
    else:
        volatility = WeatherReading("red", vol, "Danger — do not add new positions")

    sma200 = float(close.rolling(200).mean().iloc[-1])
    last = float(close.iloc[-1])
    gap = (last / sma200 - 1) * 100
    if last > sma200 and gap > 5:
        trend = WeatherReading("green", gap, "Bull regime — above the 200-day average")
    elif last > sma200:
        trend = WeatherReading(
            "yellow", gap, "Mild bull — thin margin over the 200-day"
        )
    elif gap > -5:
        trend = WeatherReading("yellow", gap, "Borderline — just below the 200-day")
    else:
        trend = WeatherReading("red", gap, "Bear regime — below the 200-day average")

    momentum_pct = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100
    if momentum_pct > 2:
        momentum = WeatherReading("green", momentum_pct, "Positive — market climbing")
    elif momentum_pct > -1:
        momentum = WeatherReading("yellow", momentum_pct, "Flat — no clear direction")
    else:
        momentum = WeatherReading("red", momentum_pct, "Negative — market pulling back")

    sma50 = float(close.rolling(50).mean().iloc[-1])
    cross_gap = (sma50 / sma200 - 1) * 100
    if sma50 > sma200 and cross_gap > 1:
        cross = WeatherReading("green", cross_gap, "Golden cross — long-term uptrend")
    elif sma50 > sma200:
        cross = WeatherReading("yellow", cross_gap, "Borderline — recently crossed")
    else:
        cross = WeatherReading("red", cross_gap, "Death cross — long-term downtrend")

    tones = [volatility.tone, trend.tone, momentum.tone, cross.tone]
    greens, reds = tones.count("green"), tones.count("red")
    if reds == 0 and greens >= 3:
        verdict = "green"
    elif reds <= 1 and greens >= 2:
        verdict = "yellow"
    else:
        verdict = "red"

    combined = None
    if p7_composite_score is not None:
        if verdict == "green" and p7_composite_score >= 3.6:
            combined = "trade"
        elif verdict == "red" or p7_composite_score < 2.8:
            combined = "pass"
        else:
            combined = "watch"
    return MarketWeather(
        volatility, trend, momentum, cross, verdict, _VERDICT_ACTIONS[verdict], combined
    )


@dataclass(frozen=True)
class PlanReview:
    """Chapter 2's review of a scan's plans."""

    ranking: list[dict[str, Any]]
    actionable: list[dict[str, Any]]
    audit: dict[str, Any] | None
    risk_scaling: list[dict[str, float]]


def _hold_by(as_of: Any, bars: int | None) -> str | None:
    if bars is None:
        return None
    anchor = np.datetime64(str(as_of)[:10], "D")
    return str(
        np.busday_offset(anchor, int(bars), roll="forward").astype("datetime64[D]")
    )


def actionable_plans(
    plans: Iterable[Mapping[str, Any]],
    *,
    conviction: str = "High",
    min_risk_reward: float = 2.0,
    per_sector_cap: int = 2,
    ranking_limit: int = 15,
    base_risk: float = 0.01,
    risk_levels: Sequence[float] = (0.005, 0.015, 0.02),
) -> PlanReview:
    """Rank plans by |score| and keep today's actionable ones.

    A plan is actionable at the given ``conviction`` with ``risk_reward`` of
    at least ``min_risk_reward``, at most ``per_sector_cap`` per segment,
    strongest first. Each actionable plan gets its latest exit date
    (``hold_by``: ``as_of`` plus ``time_stop_bars`` business days, weekends
    skipped but not holidays). The audit explains the top actionable plan's
    votes, and the risk scaling shows its quantity at other risk fractions.
    """
    ordered = sorted(plans, key=lambda p: -abs(float(p["score"])))
    actionable: list[dict[str, Any]] = []
    per_sector: dict[str, int] = defaultdict(int)
    for plan in ordered:
        if plan.get("conviction") != conviction:
            continue
        if float(plan.get("risk_reward") or 0.0) < min_risk_reward:
            continue
        if per_sector[plan.get("segment", "")] >= per_sector_cap:
            continue
        per_sector[plan.get("segment", "")] += 1
        actionable.append(
            {**plan, "hold_by": _hold_by(plan.get("as_of"), plan.get("time_stop_bars"))}
        )

    audit = None
    scaling: list[dict[str, float]] = []
    if actionable:
        top = actionable[0]
        votes = [
            {**vote, "contribution": float(vote["vote"]) * float(vote["weight"])}
            for vote in top.get("votes") or []
        ]
        votes.sort(key=lambda v: -abs(v["contribution"]))
        audit = {
            "symbol": top["symbol"],
            "segment": top.get("segment"),
            "score": float(top["score"]),
            "votes": votes,
            "reasoning": top.get("reasoning"),
            "caveats": top.get("caveats"),
        }
        base_qty = float(top.get("position_size") or 0.0)
        scaling = [
            {"risk": float(r), "quantity": base_qty * (float(r) / base_risk)}
            for r in risk_levels
        ]
    ranking = [dict(plan) for plan in ordered[:ranking_limit]]
    return PlanReview(ranking, actionable, audit, scaling)


def round_trip_pnl(fills: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Realized P&L of the first entry and exit in a fill list (chapter 3).

    Returns ``status`` ``"no-fills"`` or ``"open"`` (no completed round trip)
    instead of a zero P&L.
    """
    fills = list(fills)
    if not fills:
        return {"status": "no-fills"}
    entries = [f for f in fills if f["side"] in ("buy", "sell_short")]
    exits = [f for f in fills if f["side"] in ("sell", "buy_to_cover")]
    if not (entries and exits):
        return {"status": "open"}
    entry, exit_ = entries[0], exits[0]
    quantity = float(entry["quantity"])
    entry_price, exit_price = float(entry["price"]), float(exit_["price"])
    slippage = float(entry.get("slippage", 0)) + float(exit_.get("slippage", 0))
    commission = float(entry.get("commission", 0)) + float(exit_.get("commission", 0))
    # A long gains as the price rises; a short (sell_short) as it falls.
    direction = 1.0 if entry["side"] == "buy" else -1.0
    gross = direction * (exit_price - entry_price) * quantity
    net = gross - slippage - commission
    notional = entry_price * quantity
    return {
        "status": "closed",
        "side": entry["side"],
        "quantity": quantity,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_timestamp": exit_.get("timestamp"),
        "gross": gross,
        "slippage": slippage,
        "commission": commission,
        "costs": slippage + commission,
        "net": net,
        "notional": notional,
        "net_pct_of_notional": net / notional * 100 if notional else None,
    }


def replay_recommendation(rec: Mapping[str, Any], bars: pd.DataFrame) -> dict[str, Any]:
    """Replay one recommendation against its forward daily bars (chapter 6).

    Fills at the first bar's open; the first of stop or target touched on a
    later bar's range decides; otherwise the last close marks it to market.
    ``bars`` has a datetime index and ``open``/``high``/``low``/``close``.
    """
    if bars is None or bars.empty:
        return {"status": "no-forward-bars"}
    entry = float(rec["entry_price"]) if rec.get("entry_price") else None
    stop = float(rec["stop_price"]) if rec.get("stop_price") else None
    target = float(rec["target_price"]) if rec.get("target_price") else None
    quantity = float(rec["position_size"]) if rec.get("position_size") else 0.0
    if entry is None or stop is None or target is None or quantity <= 0:
        return {"status": "missing-levels"}

    entry_bar = bars.iloc[0]
    fill = float(entry_bar["open"])
    start = entry_bar.name.date()
    is_long = rec.get("action", "") == "BUY"
    for ts, row in bars.iterrows():
        high, low = float(row["high"]), float(row["low"])
        held = (ts.date() - start).days
        if is_long:
            if low <= stop:
                return _exit("stop", stop, ts, (stop - fill) * quantity, held)
            if high >= target:
                return _exit("target", target, ts, (target - fill) * quantity, held)
        else:
            if high >= stop:
                return _exit("stop", stop, ts, (fill - stop) * quantity, held)
            if low <= target:
                return _exit("target", target, ts, (fill - target) * quantity, held)
    final = float(bars.iloc[-1]["close"])
    realized = (final - fill) * quantity if is_long else (fill - final) * quantity
    return _exit("open", final, bars.index[-1], realized, len(bars))


def _exit(
    status: str, price: float, ts: Any, realized: float, held: int
) -> dict[str, Any]:
    return {
        "status": status,
        "exit_price": price,
        "exit_ts": ts.isoformat(),
        "realized": realized,
        "bars_held": held,
    }


def replay_summary(outcomes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Discipline statistics over replay outcomes (chapter 6 §4-§6).

    A stop counts as -1R and a win as the plan's ``r:r``; expectancy is in R
    per closed trade. ``total_realized`` covers every outcome with a
    realized figure, open positions included, as the notebook does.
    """
    rows = list(outcomes)
    closed = [r for r in rows if r.get("status") in ("stop", "target")]
    wins = [r for r in closed if r["status"] == "target"]
    win_rate = len(wins) / len(closed) if closed else 0.0
    avg_win_r = sum(float(r["r:r"]) for r in wins) / len(wins) if wins else 0.0
    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in closed:
        by[str(row.get("conviction") or "")].append(row)
    return {
        "plans": len(rows),
        "closed": len(closed),
        "open": sum(1 for r in rows if r.get("status") == "open"),
        "failed": sum(
            1 for r in rows if r.get("status") not in ("stop", "target", "open")
        ),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate": win_rate,
        "avg_win_r": avg_win_r,
        "avg_loss_r": -1.0,
        "expectancy_r": win_rate * avg_win_r + (1 - win_rate) * -1.0,
        "total_realized": sum(
            float(r["realized"]) for r in rows if r.get("realized") is not None
        ),
        "by_conviction": [
            {
                "conviction": key,
                "n": len(group),
                "wins": sum(1 for r in group if r["status"] == "target"),
                "win_rate": sum(1 for r in group if r["status"] == "target")
                / len(group),
                "avg_realized": sum(float(r.get("realized") or 0.0) for r in group)
                / len(group),
            }
            for key, group in sorted(by.items())
        ],
    }


def config_diff(
    default: Mapping[str, Any], candidate: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Knob-by-knob default versus candidate (chapter 5 §7)."""
    rows = []
    for knob, base in default.items():
        value = candidate.get(knob, base)
        numeric = isinstance(base, int | float) and isinstance(value, int | float)
        rows.append(
            {
                "knob": knob,
                "default": base,
                "candidate": value,
                "delta": value - base if numeric else None,
                "changed": value != base,
            }
        )
    return rows
