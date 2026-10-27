"""Basket look-through, sector roll-up and concentration tools (#2313, N05a).

Routes under ``/api/v1/story/analytics``, the server-side form of the
portfolio notebooks' x-ray chapter (``portfolio/03`` §3-§8):

- ``POST /basket/effective_positions``: flatten a basket through its funds'
  SEC N-PORT filings.
- ``POST /basket/sector_view``: sector weights after look-through.
- ``POST /concentration``: HHI, effective-N, top-K and a single-name shock.
- ``POST /construction``: target bands with enforced concentration caps.

The math is :mod:`openbb_portfolio_intel.analytics.basket_lookthrough`, the
same engine the notebook calls, so both compute the same numbers. Provider
data comes from the SEC and ``fmp_cached`` providers through three seams
(``_nport_rows``, ``_search_ticker``, ``_profile_sector``); nothing here
reads notebook state or writes a file. Inputs are size-bounded and weights
must be finite and non-negative.
"""

from __future__ import annotations

import copy
import logging
import math
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.app.service.auth_service import AuthService
from openbb_portfolio_intel.analytics.basket_lookthrough import (
    NportUnavailable,
    basket_sector_view,
    concentration,
    construction_targets,
    effective_positions,
    strip_corp_suffix,
)
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

logger = logging.getLogger(__name__)

__all__ = ["NportUnavailable", "compose_story_analytics_app"]

MAX_BASKET = 200
MAX_CLASS_SYMBOLS = 200
MAX_WEIGHTS = 5000
_SYMBOL = Annotated[
    str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-^=]+$")
]


def _json_safe(value: Any) -> Any:
    """Replace NaN or infinity with text that is not a number.

    The float check then rejects it with that text as the error's input, so
    the 422 response stays valid JSON; echoing the raw NaN would make the
    error response itself fail to encode (a 500).
    """
    if isinstance(value, float) and not math.isfinite(value):
        return f"non-finite number ({value})"
    return value


_WEIGHT = Annotated[
    float, BeforeValidator(_json_safe), Field(ge=0, allow_inf_nan=False)
]
_FRACTION = Annotated[
    float, BeforeValidator(_json_safe), Field(ge=0, le=1, allow_inf_nan=False)
]
_CAP = Annotated[
    float, BeforeValidator(_json_safe), Field(gt=0, le=1, allow_inf_nan=False)
]


def _obb() -> Any:
    """Return the in-process Platform app, imported only when a tool runs."""
    from openbb import obb  # pylint: disable=import-outside-toplevel

    return obb


def _nport_rows(symbol: str) -> list[dict[str, Any]]:
    """Return one fund's N-PORT holdings from the SEC provider."""
    try:
        result = _obb().etf.nport_disclosure(symbol=symbol, provider="sec")
    except Exception as exc:  # pylint: disable=broad-except
        message = str(exc)
        if "No N-Port records" in message or "not found" in message.lower():
            raise NportUnavailable(f"{symbol}: not an N-PORT filer") from exc
        raise
    return [
        {
            "name": row.name,
            "weight": float(row.weight or 0.0),
            "cusip": row.cusip,
            "asset_category": row.asset_category,
        }
        for row in result.results
    ]


def _search_ticker(query: str) -> str | None:
    """Return the first SEC search hit's ticker for an issuer name."""
    hits = _obb().equity.search(query=query, provider="sec").results
    return hits[0].symbol if hits else None


def _profile_sector(symbol: str) -> str | None:
    """Return a listed symbol's sector from ``fmp_cached``."""
    profile = _obb().equity.profile(symbol=symbol, provider="fmp_cached").results
    return getattr(profile[0], "sector", None) if profile else None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BasketPosition(_Strict):
    """One basket row: a symbol and its weight as a fraction of the book."""

    symbol: _SYMBOL
    weight: _WEIGHT


class _BasketRequest(_Strict):
    basket: list[BasketPosition] = Field(min_length=1, max_length=MAX_BASKET)
    equity_etfs: list[_SYMBOL] = Field(
        default_factory=list,
        max_length=MAX_CLASS_SYMBOLS,
        description="Funds to expand into their N-PORT issuers.",
    )
    bond_etfs: list[_SYMBOL] = Field(
        default_factory=list,
        max_length=MAX_CLASS_SYMBOLS,
        description="Funds kept as one fixed-income bucket each.",
    )
    commodity_trusts: list[_SYMBOL] = Field(
        default_factory=list,
        max_length=MAX_CLASS_SYMBOLS,
        description="Trusts that file no N-PORT; kept opaque.",
    )

    def classes(self) -> dict[str, set[str]]:
        return {
            "equity_etfs": set(self.equity_etfs),
            "bond_etfs": set(self.bond_etfs),
            "commodity_trusts": set(self.commodity_trusts),
        }

    def positions(self) -> list[dict[str, Any]]:
        return [p.model_dump() for p in self.basket]


class EffectivePositionsRequest(_BasketRequest):
    """Flatten a basket through N-PORT."""

    top_n_per_etf: int = Field(100, ge=1, le=500)


class SectorViewRequest(_BasketRequest):
    """Sector weights after look-through."""

    top_n_resolve: int = Field(30, ge=1, le=60)


def _bounded_weights(value: dict[str, float]) -> dict[str, float]:
    if not value:
        raise ValueError("at least one weight is required")
    if len(value) > MAX_WEIGHTS:
        raise ValueError(f"at most {MAX_WEIGHTS} weights are allowed")
    return value


_WEIGHT_MAP = Annotated[
    dict[Annotated[str, Field(min_length=1, max_length=200)], _WEIGHT],
    AfterValidator(_bounded_weights),
]


class ConcentrationRequest(_Strict):
    """A weight map: basket symbols or effective positions."""

    weights: _WEIGHT_MAP
    kill_shot_drop: _FRACTION = 0.20


class ConstructionRequest(_Strict):
    """Effective positions plus the policy's caps and tolerance band."""

    effective: _WEIGHT_MAP
    max_single_name: _CAP = 0.06
    top5_cap: _CAP = 0.35
    band_abs: Annotated[
        float, BeforeValidator(_json_safe), Field(ge=0, le=0.5, allow_inf_nan=False)
    ] = 0.015
    min_coverage: _FRACTION = 0.90


class WeightedKey(BaseModel):
    """One effective position."""

    key: str
    weight: float


class OpaquePosition(BaseModel):
    """A position kept at face weight, and why."""

    symbol: str
    reason: str


class EffectivePositionsResponse(BaseModel):
    """Effective positions, heaviest first."""

    positions: list[WeightedKey]
    coverage: float
    non_nport: list[str]
    opaque: list[OpaquePosition]


class SectorWeight(BaseModel):
    """One sector's weight."""

    sector: str
    weight: float


class SectorViewResponse(BaseModel):
    """Look-through sector weights, heaviest first."""

    sectors: list[SectorWeight]
    unknown_count: int = Field(
        description="Fund rows bucketed as Unknown or Other (small)."
    )
    lookup_errors: int = Field(
        description="Ticker or sector lookups that raised; counted as Unknown."
    )


class ConcentrationResponse(BaseModel):
    """HHI, effective-N, top-K weights and a single-name shock."""

    hhi: float
    effective_n: float | None
    top1: float
    top5: float
    top10: float
    largest: str | None
    largest_weight: float
    kill_shot: float


class Target(BaseModel):
    """One name's current weight, target and tolerance band."""

    name: str
    current: float
    target: float
    band_lo: float
    band_hi: float
    status: Literal["TRIM", "boost", "ok"]


class ConstructionResponse(BaseModel):
    """Targets, or a refusal when coverage is too thin."""

    refused: bool
    coverage: float
    targets: list[Target] | None
    residual: float = Field(description="Weight the caps could not place.")
    top5: float
    capped_names: int
    redistributed: float


class _SectorLookups:
    """Per-request, cached issuer and symbol sector lookups."""

    def __init__(self) -> None:
        self.errors = 0
        self._tickers: dict[str, str | None] = {}
        self._sectors: dict[str, str | None] = {}

    def _guard(self, call, argument: str) -> str | None:
        try:
            return call(argument)
        except Exception as exc:  # pylint: disable=broad-except
            self.errors += 1
            logger.warning("story sector lookup failed for %r: %s", argument, exc)
            return None

    def for_symbol(self, symbol: str) -> str | None:
        if symbol not in self._sectors:
            self._sectors[symbol] = self._guard(_profile_sector, symbol)
        return self._sectors[symbol]

    def for_name(self, name: str) -> str | None:
        if name not in self._tickers:
            ticker = None
            for query in dict.fromkeys((name, strip_corp_suffix(name))):
                ticker = self._guard(_search_ticker, query)
                if ticker:
                    break
            self._tickers[name] = ticker
        ticker = self._tickers[name]
        return self.for_symbol(ticker) if ticker else None


def _holdings(symbol: str) -> list[dict[str, Any]]:
    try:
        return _nport_rows(symbol)
    except NportUnavailable:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("story N-PORT fetch failed for %s: %s", symbol, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"N-PORT holdings for {symbol} are unavailable from the provider "
            f"({type(exc).__name__}); no partial look-through was returned.",
        ) from exc


def build_router() -> APIRouter:
    """Return the story analytics routes."""
    router = APIRouter(prefix="/api/v1/story/analytics", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    @router.post(
        "/basket/effective_positions",
        operation_id="story_basket_effective_positions",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_basket_effective_positions"}},
    )
    def story_basket_effective_positions(
        request: EffectivePositionsRequest,
    ) -> EffectivePositionsResponse:
        """Flatten a basket through its funds' SEC N-PORT holdings.

        Equity funds expand into issuers (the tail beyond ``top_n_per_etf``
        becomes one ``TAIL_<ETF>`` row), bond funds become one
        ``BOND_<ETF>`` row, and commodity trusts or non-filers stay opaque.
        """
        result = effective_positions(
            request.positions(),
            _holdings,
            top_n_per_etf=request.top_n_per_etf,
            **request.classes(),
        )
        ranked = sorted(result.effective.items(), key=lambda kv: -kv[1])
        return EffectivePositionsResponse(
            positions=[WeightedKey(key=k, weight=w) for k, w in ranked],
            coverage=sum(result.effective.values()),
            non_nport=result.non_nport,
            opaque=[OpaquePosition(symbol=s, reason=r) for s, r in result.opaque],
        )

    @router.post(
        "/basket/sector_view",
        operation_id="story_basket_sector_view",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_basket_sector_view"}},
    )
    def story_basket_sector_view(request: SectorViewRequest) -> SectorViewResponse:
        """Sector weights after look-through.

        Commodity trusts count as Commodity and bond funds as Fixed Income;
        equity funds resolve their heaviest ``top_n_resolve`` issuers to a
        sector, and single names use their profile sector.
        """
        lookups = _SectorLookups()
        view = basket_sector_view(
            request.positions(),
            holdings_for=_holdings,
            sector_for_name=lookups.for_name,
            sector_for_symbol=lookups.for_symbol,
            top_n_resolve=request.top_n_resolve,
            **request.classes(),
        )
        ranked = sorted(view.sectors.items(), key=lambda kv: -kv[1])
        return SectorViewResponse(
            sectors=[SectorWeight(sector=k, weight=w) for k, w in ranked],
            unknown_count=view.unknown_count,
            lookup_errors=lookups.errors,
        )

    @router.post(
        "/concentration",
        operation_id="story_concentration",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_concentration"}},
    )
    def story_concentration(request: ConcentrationRequest) -> ConcentrationResponse:
        """Concentration of a weight map.

        Returns HHI, effective-N (1/HHI), top-1/5/10 weights and the
        portfolio loss if the largest position falls by ``kill_shot_drop``.
        """
        result = concentration(request.weights, kill_shot_drop=request.kill_shot_drop)
        return ConcentrationResponse(**result.__dict__)

    @router.post(
        "/construction",
        operation_id="story_construction_targets",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_construction_targets"}},
    )
    def story_construction_targets(
        request: ConstructionRequest,
    ) -> ConstructionResponse:
        """Target bands with enforced single-name and top-5 caps.

        Refuses when attributed coverage is below ``min_coverage``. Weight
        the caps cannot place is reported as ``residual``, never dropped.
        """
        result = construction_targets(
            request.effective,
            max_single_name=request.max_single_name,
            top5_cap=request.top5_cap,
            band_abs=request.band_abs,
            min_coverage=request.min_coverage,
        )
        targets = (
            None
            if result.targets is None
            else [Target(name=k, **v) for k, v in result.targets.items()]
        )
        return ConstructionResponse(
            refused=result.refused,
            coverage=result.coverage,
            targets=targets,
            residual=result.residual,
            top5=result.top5,
            capped_names=result.capped_names,
            redistributed=result.redistributed,
        )

    return router


def compose_story_analytics_app(source_app: FastAPI) -> FastAPI:
    """Add the story analytics routes to an isolated app copy."""
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router())
    composed.openapi_schema = None
    return composed
