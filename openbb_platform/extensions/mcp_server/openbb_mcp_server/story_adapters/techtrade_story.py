"""TechTrade story tools (#2316, N05d).

Routes under ``/api/v1/story/techtrade``, the server-side form of the
calculations the TechTrade notebooks run on top of the engine's outputs:

- ``POST /market_weather``: chapter 1's market traffic light for a symbol
  (SPY by default), optionally combined with a phase-7 score.
- ``POST /institutional``: chapter 1's 13F institutional-ownership summary
  from the server's local SEC 13F index.
- ``POST /actionable_plans``: chapter 2's ranking, actionable filter,
  time-stop dates, vote audit and risk scaling over ``techtrade_scan`` plans.
- ``POST /round_trip_pnl``: chapter 3's realized P&L for simulated fills.
- ``POST /replay``: chapter 6's forward-bar replay and discipline summary.
- ``POST /indicator_config``: chapter 5's default indicator config, the
  tuned-segment summary and a candidate's knob diff.

The math is :mod:`openbb_techtrade.engine.story_analytics`. Provider data
comes through three seams (``_daily_closes``, ``_forward_bars``,
``_institutional``); a provider failure is an error, never a made-up
reading. Inputs are bounded and numbers must be finite.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import logging
import math
from datetime import date, timedelta
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.app.service.auth_service import AuthService
from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, build_indicator_panel
from openbb_techtrade.engine.story_analytics import (
    actionable_plans,
    config_diff,
    market_weather,
    replay_recommendation,
    replay_summary,
    round_trip_pnl,
)
from openbb_techtrade.tuning.tuned_defaults import read_tuned
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

logger = logging.getLogger(__name__)

MAX_PLANS = 200
MAX_FILLS = 100
MAX_REPLAYS = 25
_SYMBOL = Annotated[
    str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-^=]+$")
]
_TEXT = Annotated[str, Field(max_length=2000)]


def _json_safe(value: Any) -> Any:
    """Replace NaN or infinity with text that is not a number.

    The float check then rejects it with that text as the error's input, so
    the 422 response stays valid JSON.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return f"non-finite number ({value})"
    return value


_FINITE = Annotated[float, BeforeValidator(_json_safe), Field(allow_inf_nan=False)]
_NON_NEGATIVE = Annotated[
    float, BeforeValidator(_json_safe), Field(ge=0, allow_inf_nan=False)
]
_POSITIVE = Annotated[
    float, BeforeValidator(_json_safe), Field(gt=0, allow_inf_nan=False)
]


def default_config() -> dict[str, Any]:
    """Return the default indicator configuration as a plain dict."""
    return dataclasses.asdict(DEFAULT_CONFIG)


def _obb() -> Any:
    """Return the in-process Platform app, imported only when a tool runs."""
    from openbb import obb  # pylint: disable=import-outside-toplevel

    return obb


def _daily_closes(symbol: str, lookback_days: int) -> list[float]:
    """Return daily closes for ``symbol`` over ``lookback_days``, oldest first."""
    end = date.today()
    frame = (
        _obb()
        .equity.price.historical(
            symbol=symbol,
            start_date=str(end - timedelta(days=lookback_days)),
            end_date=str(end),
            interval="1d",
            provider="fmp_cached",
        )
        .to_df()
    )
    frame.columns = [str(c).lower() for c in frame.columns]
    if "date" in frame.columns and not isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.set_index(pd.to_datetime(frame["date"]))
    return [float(c) for c in frame.sort_index()["close"].dropna()]


def _forward_bars(symbol: str, as_of: date, days_ahead: int) -> pd.DataFrame:
    """Return the daily bars after ``as_of`` (never at or before it)."""
    start = as_of + timedelta(days=1)
    frame = (
        _obb()
        .equity.price.historical(
            symbol=symbol,
            start_date=str(start),
            end_date=str(start + timedelta(days=days_ahead * 2)),
            provider="fmp_cached",
        )
        .to_df()
    )
    frame.index = pd.to_datetime(frame.index)
    return frame[frame.index.date > as_of]


def _institutional(symbol: str) -> dict[str, Any] | None:
    """Summarize 13F holdings of ``symbol`` from the local SEC 13F index.

    Returns ``None`` when the index has no CUSIP for the symbol.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_sec.utils.thirteen_f_index import (
        holders_for_cusip,
        institutional_holding_summary,
        resolve_cusip,
        shares_outstanding_from_sec,
    )

    cusips = resolve_cusip(symbol)
    if not cusips:
        return None
    holders = holders_for_cusip(cusips)
    period = holders[0]["period"] if holders else None
    shares = shares_outstanding_from_sec(symbol, period)
    source = "SEC EDGAR (dei:EntityCommonStockSharesOutstanding)"
    if not shares:
        profile = _obb().equity.profile(symbol=symbol, provider="fmp_cached").results
        shares = getattr(profile[0], "shares_outstanding", None) if profile else None
        source = "fmp_cached profile" if shares else "unavailable"
    summary = institutional_holding_summary(
        cusips, period=period, shares_outstanding=shares
    )
    return {
        **summary,
        "shares_outstanding_source": source,
        "top_holders": [
            {
                "filer_name": h.get("filer_name"),
                "shares": h.get("shares"),
                "value_usd": h.get("value_usd"),
            }
            for h in holders[:10]
        ],
    }


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarketWeatherRequest(_Strict):
    """A symbol to read and an optional phase-7 composite score."""

    symbol: _SYMBOL = "SPY"
    lookback_days: Annotated[int, Field(ge=300, le=1000)] = 365
    p7_composite_score: (
        Annotated[
            float, BeforeValidator(_json_safe), Field(ge=0, le=5, allow_inf_nan=False)
        ]
        | None
    ) = None


class SymbolRequest(_Strict):
    """One symbol."""

    symbol: _SYMBOL


class Vote(_Strict):
    """One indicator family's vote on a plan."""

    family: Annotated[str, Field(max_length=50)]
    name: Annotated[str, Field(max_length=50)]
    vote: _FINITE
    weight: _FINITE


class Plan(_Strict):
    """The fields of a ``techtrade_scan`` / ``techtrade_plan`` plan this uses."""

    symbol: _SYMBOL
    segment: Annotated[str, Field(max_length=100)] = ""
    score: _FINITE
    action: Annotated[str, Field(max_length=20)] = ""
    conviction: Annotated[str, Field(max_length=20)] = ""
    risk_reward: _NON_NEGATIVE = 0.0
    position_size: _NON_NEGATIVE = 0.0
    entry_price: _NON_NEGATIVE | None = None
    stop_price: _NON_NEGATIVE | None = None
    target_price: _NON_NEGATIVE | None = None
    time_stop_bars: Annotated[int, Field(ge=0, le=10_000)] | None = None
    as_of: date | None = None
    votes: list[Vote] = Field(default_factory=list, max_length=50)
    reasoning: _TEXT | None = None
    caveats: _TEXT | None = None


class ActionablePlansRequest(_Strict):
    """Plans and the review's filters."""

    plans: list[Plan] = Field(max_length=MAX_PLANS)
    conviction: Annotated[str, Field(max_length=20)] = "High"
    min_risk_reward: _NON_NEGATIVE = 2.0
    per_sector_cap: Annotated[int, Field(ge=1, le=50)] = 2
    base_risk: Annotated[
        float, BeforeValidator(_json_safe), Field(gt=0, le=1, allow_inf_nan=False)
    ] = 0.01
    risk_levels: list[
        Annotated[
            float, BeforeValidator(_json_safe), Field(gt=0, le=1, allow_inf_nan=False)
        ]
    ] = Field(default_factory=lambda: [0.005, 0.015, 0.02], max_length=10)


class Fill(_Strict):
    """One simulated fill."""

    side: Literal["buy", "sell", "sell_short", "buy_to_cover"]
    price: _POSITIVE
    quantity: _POSITIVE
    slippage: _NON_NEGATIVE = 0.0
    commission: _NON_NEGATIVE = 0.0
    timestamp: Annotated[str, Field(max_length=40)] | None = None


class RoundTripRequest(_Strict):
    """Fills of one simulated position, in order."""

    fills: list[Fill] = Field(max_length=MAX_FILLS)


class Recommendation(_Strict):
    """One recommendation to replay."""

    symbol: _SYMBOL
    action: Literal["BUY", "SELL_SHORT"]
    entry_price: _POSITIVE
    stop_price: _POSITIVE
    target_price: _POSITIVE
    position_size: _POSITIVE
    conviction: Annotated[str, Field(max_length=20)] = ""
    risk_reward: _NON_NEGATIVE | None = None


class ReplayRequest(_Strict):
    """Recommendations made on ``as_of`` and how far forward to look."""

    recommendations: list[Recommendation] = Field(min_length=1, max_length=MAX_REPLAYS)
    as_of: date
    days_ahead: Annotated[int, Field(ge=1, le=60)] = 30


def run_replay(request: ReplayRequest) -> dict[str, Any]:
    """Replay each recommendation; a failed fetch is that outcome, not an error."""
    outcomes = []
    for rec in request.recommendations:
        fields = rec.model_dump()
        try:
            bars = _forward_bars(rec.symbol.upper(), request.as_of, request.days_ahead)
            outcome = replay_recommendation(fields, bars)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("story replay fetch failed for %s: %s", rec.symbol, exc)
            outcome = {"status": "fetch-failed"}
        outcome.update(
            {
                "symbol": rec.symbol.upper(),
                "as_of": request.as_of.isoformat(),
                "action": rec.action,
                "conviction": rec.conviction,
                "r:r": rec.risk_reward,
            }
        )
        outcomes.append(outcome)
    return {"outcomes": outcomes, "summary": replay_summary(outcomes)}


def tunable_knobs() -> list[dict[str, Any]]:
    """Return the period knobs tuning searches over, with their ranges."""
    # The knob table is pure data; reading it does not import tuneta.
    from openbb_techtrade.tuning.tuneta_adapter import (  # pylint: disable=import-outside-toplevel
        KNOB_TABLE,
    )

    return [
        {"field": field, "indicator": indicator, "low": low, "high": high}
        for field, indicator, (low, high) in KNOB_TABLE
    ]


def _known_knobs(candidate: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(candidate) - set(default_config()))
    if unknown:
        raise ValueError(f"unknown config knobs: {', '.join(unknown)}")
    return candidate


class IndicatorConfigRequest(_Strict):
    """An optional candidate configuration to compare with the defaults."""

    candidate: Annotated[
        dict[Annotated[str, Field(max_length=100)], _FINITE],
        AfterValidator(_known_knobs),
    ] = Field(default_factory=dict, max_length=100)


def _bad_gateway(what: str, exc: Exception) -> HTTPException:
    logger.warning("story techtrade %s failed: %s", what, exc)
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        f"{what} is unavailable from the provider ({type(exc).__name__}).",
    )


def _reading(component: Any) -> dict[str, Any]:
    return {"tone": component.tone, "value": component.value, "label": component.label}


def build_router() -> APIRouter:  # noqa: PLR0915
    """Return the TechTrade story routes."""
    router = APIRouter(prefix="/api/v1/story/techtrade", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    def _route(path: str, name: str):
        return router.post(
            path,
            operation_id=name,
            dependencies=authenticated,
            openapi_extra={"mcp_config": {"name": name}},
        )

    @_route("/market_weather", "story_market_weather")
    def story_market_weather(request: MarketWeatherRequest) -> dict[str, Any]:
        """Market traffic light: volatility, trend, momentum and the 50/200 cross.

        Green, yellow or red overall; with ``p7_composite_score`` it also says
        trade, watch or pass. Uses daily ``fmp_cached`` closes.
        """
        symbol = request.symbol.upper()
        try:
            closes = _daily_closes(symbol, request.lookback_days)
        except Exception as exc:  # pylint: disable=broad-except
            raise _bad_gateway(f"Daily history for {symbol}", exc) from exc
        try:
            weather = market_weather(
                closes, p7_composite_score=request.p7_composite_score
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        return {
            "symbol": symbol,
            "closes": len(closes),
            "components": {
                "volatility": _reading(weather.volatility),
                "trend": _reading(weather.trend),
                "momentum": _reading(weather.momentum),
                "cross": _reading(weather.cross),
            },
            "verdict": weather.verdict,
            "action": weather.action,
            "combined": weather.combined,
        }

    @_route("/institutional", "story_institutional_summary")
    def story_institutional_summary(request: SymbolRequest) -> dict[str, Any]:
        """13F institutional ownership of a symbol from the local SEC 13F index.

        Holder count, total shares and value, percent institutional (when
        shares outstanding is known, with its source) and the top holders.
        """
        symbol = request.symbol.upper()
        try:
            summary = _institutional(symbol)
        except Exception as exc:  # pylint: disable=broad-except
            raise _bad_gateway(f"The 13F summary for {symbol}", exc) from exc
        if summary is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"{symbol} has no CUSIP in the local SEC 13F index.",
            )
        return {"symbol": symbol, **summary}

    @_route("/actionable_plans", "story_actionable_plans")
    def story_actionable_plans(request: ActionablePlansRequest) -> dict[str, Any]:
        """Rank scan plans and keep today's actionable ones.

        Actionable: the given conviction, risk/reward of at least
        ``min_risk_reward``, at most ``per_sector_cap`` per segment, strongest
        first, each with its latest exit date. Also explains the top plan's
        votes and scales its quantity to other risk fractions.
        """
        review = actionable_plans(
            [plan.model_dump(mode="json") for plan in request.plans],
            conviction=request.conviction,
            min_risk_reward=request.min_risk_reward,
            per_sector_cap=request.per_sector_cap,
            base_risk=request.base_risk,
            risk_levels=request.risk_levels,
        )
        return dataclasses.asdict(review)

    @_route("/round_trip_pnl", "story_round_trip_pnl")
    def story_round_trip_pnl(request: RoundTripRequest) -> dict[str, Any]:
        """Realized P&L of the first entry and exit among simulated fills.

        Gross, slippage, commission and net; ``status`` is ``open`` or
        ``no-fills`` when no round trip completed.
        """
        return round_trip_pnl([fill.model_dump() for fill in request.fills])

    @_route("/replay", "story_replay_recommendations")
    def story_replay_recommendations(request: ReplayRequest) -> dict[str, Any]:
        """Replay recommendations against the bars that followed ``as_of``.

        Fills at the next open; the first of stop or target touched decides;
        otherwise the position is marked to market. Returns each outcome and
        the win rate, expectancy in R and a breakdown by conviction.
        """
        return run_replay(request)

    @_route("/indicator_config", "story_indicator_config")
    def story_indicator_config(request: IndicatorConfigRequest) -> dict[str, Any]:
        """Return the default indicator config, tuned segments and a candidate's diff.

        Lists each segment tuned on this server with its verdict, the knobs
        tuning searches over with their ranges, and the indicator-panel
        builder's parameters.
        """
        tuned = read_tuned() or {}
        segments = [
            {
                "segment": segment,
                "verdict": (entry.get("meta") or {}).get("verdict"),
                "tuned_at": (entry.get("meta") or {}).get("tuned_at"),
            }
            for segment, entry in sorted((tuned.get("segments") or {}).items())
        ]
        defaults = default_config()
        return {
            "defaults": defaults,
            "tuned_segments": segments,
            "tunable_knobs": tunable_knobs(),
            "diff": (
                config_diff(defaults, request.candidate) if request.candidate else []
            ),
            "panel_parameters": list(
                inspect.signature(build_indicator_panel).parameters
            ),
        }

    return router


def compose_techtrade_story_app(source_app: FastAPI) -> FastAPI:
    """Add the TechTrade story routes to an isolated app copy."""
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router())
    composed.openapi_schema = None
    return composed
