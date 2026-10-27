"""Brinson attribution, what-if diff and candidate trades (#2315, N05c).

Routes under ``/api/v1/story/analytics``, the server-side form of the
portfolio notebooks' what-if and attribution chapter (``portfolio/05``):

- ``POST /brinson``: single-period Brinson-Fachler effects through the
  trusted reference oracle in ``openbb_portfolio_intel.analytics.brinson``.
- ``POST /whatif_diff``: how share trades move a basket's weights and
  concentration.
- ``POST /candidate_trades``: the chapter's conviction-to-trade rule.

All three are pure computation over the caller's inputs: no provider
calls, no notebook state, no files. Inputs are bounded, numbers must be
finite, and inputs the engines would have to guess around (weights that do
not sum to one, a missing price, a trade that goes short, a duplicated
basket row) are 422s naming the problem.
"""

from __future__ import annotations

import copy
import math
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.app.service.auth_service import AuthService
from openbb_portfolio_intel.analytics.brinson.oracle import brinson_reference
from openbb_portfolio_intel.analytics.trade_preview import (
    candidate_trades,
    whatif_weight_diff,
)
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

MAX_ROWS = 200
MAX_TRADES = 100
_SYMBOL = Annotated[
    str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-^=]+$")
]


def _json_safe(value: Any) -> Any:
    """Replace NaN or infinity with text that is not a number.

    The float check then rejects it with that text as the error's input, so
    the 422 response stays valid JSON.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return f"non-finite number ({value})"
    return value


_FINITE = Annotated[float, BeforeValidator(_json_safe), Field(allow_inf_nan=False)]
_WEIGHT = Annotated[
    float, BeforeValidator(_json_safe), Field(ge=0, le=1, allow_inf_nan=False)
]
_PRICE = Annotated[float, BeforeValidator(_json_safe), Field(gt=0, allow_inf_nan=False)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrinsonGroup(_Strict):
    """One group (sector, country, ...): weights and returns."""

    group: Annotated[str, Field(min_length=1, max_length=100)]
    w_p: _WEIGHT = Field(description="Portfolio weight; all groups sum to 1.")
    w_b: _WEIGHT = Field(description="Benchmark weight; all groups sum to 1.")
    r_p: _FINITE = Field(description="Portfolio return of the group.")
    r_b: _FINITE = Field(description="Benchmark return of the group.")


class BrinsonRequest(_Strict):
    """Per-group weights and returns for one period."""

    groups: list[BrinsonGroup] = Field(min_length=1, max_length=MAX_ROWS)


class BrinsonResponse(BaseModel):
    """Aggregate Brinson-Fachler effects; they add up to the active return."""

    active_return: float
    allocation: float
    selection: float
    interaction: float
    dominant_effect: Literal["allocation", "selection"]


class BasketRow(_Strict):
    """One basket position."""

    symbol: _SYMBOL
    weight: _WEIGHT


class Trade(_Strict):
    """A share trade; negative sells."""

    symbol: _SYMBOL
    delta_shares: Annotated[
        float, BeforeValidator(_json_safe), Field(allow_inf_nan=False, ge=-1e9, le=1e9)
    ]


def _unique_symbols(rows: list[BasketRow]) -> list[BasketRow]:
    symbols = [row.symbol for row in rows]
    duplicated = sorted({s for s in symbols if symbols.count(s) > 1})
    if duplicated:
        raise ValueError(f"duplicate basket symbols: {', '.join(duplicated)}")
    return rows


class WhatIfRequest(_Strict):
    """A basket, prices for every symbol involved, and the trades."""

    basket: Annotated[
        list[BasketRow],
        Field(min_length=1, max_length=MAX_ROWS),
        AfterValidator(_unique_symbols),
    ]
    prices: dict[_SYMBOL, _PRICE] = Field(
        max_length=2 * MAX_ROWS,
        description="Last price per symbol, e.g. from equity_price_quote.",
    )
    trades: list[Trade] = Field(default_factory=list, max_length=MAX_TRADES)
    account_size: Annotated[
        float, BeforeValidator(_json_safe), Field(gt=0, le=1e12, allow_inf_nan=False)
    ] = 100_000.0


class SymbolWeight(BaseModel):
    """One symbol's weight."""

    symbol: str
    weight: float


class WhatIfResponse(BaseModel):
    """Weights and concentration before and after the trades."""

    weights_before: list[SymbolWeight]
    weights_after: list[SymbolWeight]
    hhi_before: float
    hhi_after: float
    effective_n_before: float | None
    effective_n_after: float | None
    verdict: Literal["concentrated", "diversified", "unchanged"]


class Conviction(_Strict):
    """One smart-money conviction row (from portfolio_intel_smart_money_rollup)."""

    symbol: _SYMBOL
    composite: Annotated[
        float, BeforeValidator(_json_safe), Field(ge=-1, le=1, allow_inf_nan=False)
    ]
    signal_count: Annotated[int, Field(ge=0, le=1_000_000)] = 0


class CandidateTradesRequest(_Strict):
    """A ranked conviction list and the rule's sizes."""

    top_conviction: list[Conviction] = Field(max_length=MAX_ROWS)
    top_n: Annotated[int, Field(ge=1, le=50)] = 3
    buy_shares: Annotated[int, Field(ge=1, le=1_000_000)] = 5
    close_shares: Annotated[int, Field(ge=1, le=1_000_000)] = 20
    label: Annotated[str, Field(max_length=100)] | None = Field(
        None, description="Provenance label appended to each rationale."
    )


class CandidateTrade(BaseModel):
    """One candidate trade with its rationale."""

    symbol: str
    action: Literal["buy", "close"]
    delta_shares: int
    rationale: str


class CandidateTradesResponse(BaseModel):
    """The candidate trades, possibly none."""

    trades: list[CandidateTrade]
    note: str | None = None


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _ranked(weights: dict[str, float]) -> list[SymbolWeight]:
    ordered = sorted(weights.items(), key=lambda kv: -kv[1])
    return [SymbolWeight(symbol=s, weight=w) for s, w in ordered]


def build_router() -> APIRouter:
    """Return the attribution and what-if routes."""
    router = APIRouter(prefix="/api/v1/story/analytics", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    @router.post(
        "/brinson",
        operation_id="story_brinson_attribution",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_brinson_attribution"}},
    )
    def story_brinson_attribution(request: BrinsonRequest) -> BrinsonResponse:
        """Single-period Brinson-Fachler attribution.

        Splits active return into allocation, selection and interaction.
        Portfolio and benchmark weights must each sum to 1.
        """
        frame = pd.DataFrame([g.model_dump() for g in request.groups])
        try:
            effects = brinson_reference(frame)
        except ValueError as exc:
            raise _unprocessable(exc) from exc
        dominant: Literal["allocation", "selection"] = (
            "allocation"
            if abs(effects.allocation) > abs(effects.selection)
            else "selection"
        )
        return BrinsonResponse(**effects.as_dict(), dominant_effect=dominant)

    @router.post(
        "/whatif_diff",
        operation_id="story_whatif_diff",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_whatif_diff"}},
    )
    def story_whatif_diff(request: WhatIfRequest) -> WhatIfResponse:
        """Preview how share trades move a basket's weights and concentration.

        Weights become shares at the given prices for ``account_size``; trades
        add shares; HHI and effective-N are compared, and a move of more than
        0.001 in HHI reads as concentrated or diversified.
        """
        try:
            diff = whatif_weight_diff(
                [row.model_dump() for row in request.basket],
                request.prices,
                [trade.model_dump() for trade in request.trades],
                account_size=request.account_size,
            )
        except ValueError as exc:
            raise _unprocessable(exc) from exc
        return WhatIfResponse(
            weights_before=_ranked(diff.weights_before),
            weights_after=_ranked(diff.weights_after),
            hhi_before=diff.hhi_before,
            hhi_after=diff.hhi_after,
            effective_n_before=diff.effective_n_before,
            effective_n_after=diff.effective_n_after,
            verdict=diff.verdict,  # type: ignore[arg-type]
        )

    @router.post(
        "/candidate_trades",
        operation_id="story_candidate_trades",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_candidate_trades"}},
    )
    def story_candidate_trades(
        request: CandidateTradesRequest,
    ) -> CandidateTradesResponse:
        """Turn a conviction ranking into candidate trades.

        Each of the first ``top_n`` names is a buy of ``buy_shares`` when its
        composite is positive, otherwise a close of ``close_shares``. An empty
        ranking returns no trades.
        """
        trades = candidate_trades(
            [c.model_dump() for c in request.top_conviction],
            top_n=request.top_n,
            buy_shares=request.buy_shares,
            close_shares=request.close_shares,
            label=request.label,
        )
        return CandidateTradesResponse(
            trades=[CandidateTrade(**t) for t in trades],
            note=None if trades else "no conviction ranking; no trades",
        )

    return router


def compose_attribution_app(source_app: FastAPI) -> FastAPI:
    """Add the attribution and what-if routes to an isolated app copy."""
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router())
    composed.openapi_schema = None
    return composed
