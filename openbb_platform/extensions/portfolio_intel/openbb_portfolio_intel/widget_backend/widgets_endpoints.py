"""Widget endpoints for portfolio-intel — batch shipped for the P1/P2/P3 backlog.

Every function here is a **thin adapter** that returns Workspace-consumable
JSON matching the ``type`` declared in ``widgets.json``. Real analytics-
module wiring lands per widget in follow-up PRs; each stub is loud about
what's not wired yet (returns marker rows with an explicit ``note``, never
silent empty responses).

Split out of ``main.py`` so the FastAPI app definition stays compact.
The endpoints are registered by importing this module for its side
effects (``main.py`` does that).
"""

# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time

from fastapi import HTTPException, Request

from openbb_portfolio_intel.basket_resolver import (
    BasketNotFoundError,
    resolve_basket,
)
from openbb_portfolio_intel.providers.probe import TierHealth, probe_tier
from openbb_portfolio_intel.providers.registry import (
    TRACK_A_DEFAULT,
    TRACK_B_DEFAULT,
)
from openbb_portfolio_intel.providers.retrofit import with_chain
from openbb_portfolio_intel.widget_backend._app import app
from openbb_portfolio_intel.widget_backend._shared import (
    _SYMBOL_RE,
    require_auth,
    validate_account,
)

logger = logging.getLogger(__name__)


# Local aliases so the existing function bodies (that call _require_auth
# and _validate_account) keep working without a global rename.
_require_auth = require_auth
_validate_account = validate_account


# ---------------------------------------------------------------------------
# Provider-chain ledger (#1715)
# ---------------------------------------------------------------------------

# Endpoint -> currently-active tier ledger. Populated by @with_chain
# decorators (retrofit); read by provider_health() to render "which tier
# is serving endpoint X". Kept at module scope so decorators applied to
# endpoint functions defined below can reference it lazily.
_TIER_IN_USE: dict[str, str] = {}


def record_tier_used(endpoint: str, tier: str) -> None:
    """Update the tier-in-use ledger.

    Called by the ChainedFetcher wiring after every successful fetch so
    the provider-health widget can render "endpoint X: currently served
    by tier Y". Kept module-level so the retrofit sites are one-liners.
    """
    _TIER_IN_USE[endpoint] = tier


def _validate_symbol(symbol: str) -> str:
    """Return uppercased ticker or raise 400."""
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail="symbol invalid")
    return sym


# ---------------------------------------------------------------------------
# @with_chain security hooks (#1715 review)
# ---------------------------------------------------------------------------
#
# These run in the wrapper BEFORE any tier is dispatched, so the auth &
# input-validation posture holds identically whether a live tier or the
# stub-body eventually serves the response. Without them, a wired tier
# would bypass the ``_require_auth(request)`` and ``_validate_symbol()``
# calls that live inside the stub body.


def _find_request(args: tuple, kwargs: dict) -> Request | None:
    """Locate the FastAPI Request instance regardless of call style."""
    for a in args:
        if isinstance(a, Request):
            return a
    val = kwargs.get("request")
    return val if isinstance(val, Request) else None


def _require_auth_from_call(*args: object, **kwargs: object) -> None:
    """Wrapper-hook that pulls ``request`` out of the endpoint args."""
    req = _find_request(args, kwargs)
    if req is None:
        raise HTTPException(
            status_code=500, detail="internal: request not passed to auth hook"
        )
    require_auth(req)


def _validate_symbol_from_call(
    *_args: object, symbol: str = "AAPL", **_kwargs: object
) -> None:
    """Wrapper-hook that validates the ``symbol=`` param before dispatch."""
    _validate_symbol(symbol)


def _validate_account_from_call(
    *_args: object, account_id: str = "demo", **_kwargs: object
) -> None:
    """Wrapper-hook that validates the ``account_id=`` param before dispatch."""
    _validate_account(account_id)


def _account_kwargs(
    *_args: object, account_id: str = "demo", **_kwargs: object
) -> dict:
    """Extract ``account_id`` for ChainedFetcher kwargs."""
    return {"account_id": account_id}


def _symbol_kwargs(*_args: object, symbol: str = "AAPL", **_kwargs: object) -> dict:
    """Forward the *normalized* ``symbol`` to a symbol-only tier call.

    The default ``kwargs_from`` forwards the raw ``symbol``; a live tier must
    receive the same normalized ticker (strip + upper) the stub body would
    use, otherwise a valid-but-unnormalized input like ``" aapl "`` reaches
    the provider verbatim, returns empty, and silently falls through the chain
    to the demo stub — fabricated data masquerading as live (PR #1899 review).
    """
    return {"symbol": _validate_symbol(symbol)}


def _price_history_kwargs(
    *_args: object,
    symbol: str = "AAPL",
    chart_type: str = "line",
    **_kwargs: object,
) -> dict:
    """Extract ``symbol`` + ``chart_type`` for the price-history tier call.

    The default ``kwargs_from`` forwards only ``symbol``; price-history's
    live tier needs ``chart_type`` too so it can shape line vs candle rows.

    The symbol is normalized via ``_validate_symbol`` (strip + upper) so the
    live ``fmp_cached`` tier queries the *same* ticker the stub body would
    (which re-normalizes at ``sym = symbol.strip().upper()``). Forwarding the
    raw symbol would let ``" aapl "`` reach the provider verbatim, get an
    empty result, and silently fall through the chain to the demo stub —
    fabricated data masquerading as live prices (code-review PR #1899).
    """
    return {"symbol": _validate_symbol(symbol), "chart_type": chart_type}


def _validate_price_history_from_call(
    *_args: object,
    symbol: str = "AAPL",
    chart_type: str = "line",
    **_kwargs: object,
) -> None:
    """Validate ``symbol`` AND ``chart_type`` before any tier is dispatched.

    Both checks MUST run in this pre-dispatch hook (not only in the stub
    body): once a live tier serves the request the stub body is bypassed,
    so validation living only there would let an invalid ``chart_type``
    reach the shaper and silently return candle rows (the #1898 bug). The
    ``_ALLOWED_CHART_TYPES`` global is resolved at call time.
    """
    _validate_symbol(symbol)
    if chart_type not in _ALLOWED_CHART_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"chart_type must be one of {_ALLOWED_CHART_TYPES}; "
                f"got {chart_type!r}. Use ``line`` or ``candle``."
            ),
        )


# ---------------------------------------------------------------------------
# X-Ray widgets (#529, #530)
# ---------------------------------------------------------------------------


@app.get("/pi/xray/country")
@with_chain(
    endpoint="pi/xray/country",
    family="xray/country",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def xray_country(
    request: Request, account_id: str = "demo"
) -> list[dict[str, float | str]]:
    """Country-weight rows for the effective book (post ETF look-through)."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return [
            {"country": "United States", "weight": 0.72},
            {"country": "China", "weight": 0.08},
            {"country": "Japan", "weight": 0.05},
            {"country": "United Kingdom", "weight": 0.04},
            {"country": "Germany", "weight": 0.03},
            {"country": "Other", "weight": 0.08},
        ]
    logger.warning("xray/country: account resolver not wired for %r", account_id)
    return [{"country": "(no data — account resolver not wired)", "weight": 0.0}]


@app.get("/pi/lookthrough/top25")
@with_chain(
    endpoint="pi/lookthrough/top25",
    family="lookthrough/top25",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def lookthrough_top25(
    request: Request, account_id: str = "demo"
) -> list[dict[str, float | str]]:
    """Effective top-25 holdings after ETF look-through (#530)."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        demo = [
            ("AAPL", "Apple Inc.", 0.078),
            ("MSFT", "Microsoft Corp.", 0.071),
            ("NVDA", "NVIDIA Corp.", 0.063),
            ("AMZN", "Amazon.com Inc.", 0.041),
            ("GOOGL", "Alphabet Inc. Class A", 0.033),
            ("META", "Meta Platforms Inc.", 0.028),
            ("TSLA", "Tesla Inc.", 0.024),
            ("BRK.B", "Berkshire Hathaway B", 0.021),
            ("JPM", "JPMorgan Chase & Co.", 0.018),
            ("LLY", "Eli Lilly & Co.", 0.017),
            ("V", "Visa Inc.", 0.016),
            ("UNH", "UnitedHealth Group", 0.015),
            ("XOM", "Exxon Mobil Corp.", 0.014),
            ("MA", "Mastercard Inc.", 0.013),
            ("PG", "Procter & Gamble", 0.012),
            ("JNJ", "Johnson & Johnson", 0.011),
            ("HD", "Home Depot Inc.", 0.010),
            ("COST", "Costco Wholesale", 0.010),
            ("ABBV", "AbbVie Inc.", 0.009),
            ("BAC", "Bank of America", 0.009),
            ("AVGO", "Broadcom Inc.", 0.009),
            ("KO", "Coca-Cola Co.", 0.008),
            ("PEP", "PepsiCo Inc.", 0.008),
            ("MRK", "Merck & Co.", 0.008),
            ("CVX", "Chevron Corp.", 0.007),
        ]
        return [
            {"symbol": s, "name": n, "effective_weight": w, "rank": i + 1}
            for i, (s, n, w) in enumerate(demo)
        ]
    logger.warning("lookthrough/top25: account resolver not wired for %r", account_id)
    return [
        {
            "symbol": "(no-data)",
            "name": "account resolver not wired",
            "effective_weight": 0.0,
            "rank": 1,
        }
    ]


@app.get("/pi/concentration")
@with_chain(
    endpoint="pi/concentration",
    family="concentration",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def concentration(request: Request, account_id: str = "demo") -> dict[str, float | str]:
    """Herfindahl-Hirschman concentration index for the effective book (#530)."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        weights = [
            0.078,
            0.071,
            0.063,
            0.041,
            0.033,
            0.028,
            0.024,
            0.021,
            0.018,
            0.017,
            0.016,
            0.015,
            0.014,
            0.013,
            0.012,
            0.011,
            0.010,
            0.010,
            0.009,
            0.009,
            0.009,
            0.008,
            0.008,
            0.008,
            0.007,
            0.464,
        ]
        hhi = sum(w * w for w in weights)
        return {
            "value": round(hhi, 4),
            "label": "HHI (0..1; higher = more concentrated)",
            "note": "demo book",
        }
    logger.warning("concentration: account resolver not wired for %r", account_id)
    return {"value": 0.0, "label": "HHI", "note": "account resolver not wired"}


# ---------------------------------------------------------------------------
# Event Calendar (#531)
# ---------------------------------------------------------------------------


@app.get("/pi/events/calendar")
@with_chain(
    endpoint="pi/events/calendar",
    family="events/calendar",
    record_tier_used=record_tier_used,
    kwargs_from=lambda *_a, account_id="demo", horizon_days="14", **_k: {
        "account_id": account_id,
        "horizon_days": horizon_days,
    },
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def events_calendar(
    request: Request, account_id: str = "demo", horizon_days: str = "14"
) -> list[dict[str, str]]:
    """Upcoming earnings + ex-div + 8-K for held symbols."""
    _require_auth(request)
    _validate_account(account_id)
    try:
        days = int(horizon_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="horizon_days not int") from exc
    if not 1 <= days <= 365:
        raise HTTPException(status_code=400, detail="horizon_days out of range")
    if account_id == "demo":
        return [
            {
                "symbol": "AAPL",
                "type": "earnings",
                "date": "2026-07-25",
                "detail": "Q3 2026",
            },
            {
                "symbol": "MSFT",
                "type": "earnings",
                "date": "2026-07-30",
                "detail": "FY26 Q4",
            },
            {
                "symbol": "AAPL",
                "type": "ex_dividend",
                "date": "2026-08-08",
                "detail": "$0.24/sh",
            },
            {
                "symbol": "NVDA",
                "type": "form_8k",
                "date": "2026-07-22",
                "detail": "Item 7.01",
            },
            {
                "symbol": "META",
                "type": "earnings",
                "date": "2026-07-24",
                "detail": "Q2 2026",
            },
        ]
    return [
        {
            "symbol": "(no-data)",
            "type": "info",
            "date": "",
            "detail": "account resolver not wired",
        }
    ]


# ---------------------------------------------------------------------------
# Smart-Money ribbon (#532)
# ---------------------------------------------------------------------------


@app.get("/pi/smart-money/ribbon")
@with_chain(
    endpoint="pi/smart-money/ribbon",
    family="smart-money/ribbon",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def smart_money_ribbon(
    request: Request, account_id: str = "demo"
) -> list[dict[str, str | float]]:
    """Recent notable insider + institutional moves in held names."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return [
            {
                "symbol": "NVDA",
                "kind": "insider_buy",
                "actor": "CFO",
                "value_usd": 2_400_000,
                "date": "2026-07-18",
            },
            {
                "symbol": "AAPL",
                "kind": "13F_increase",
                "actor": "Berkshire Hathaway",
                "value_usd": 180_000_000,
                "date": "2026-07-15",
            },
            {
                "symbol": "TSLA",
                "kind": "insider_sell",
                "actor": "Director",
                "value_usd": 1_100_000,
                "date": "2026-07-17",
            },
        ]
    return [
        {
            "symbol": "(no-data)",
            "kind": "info",
            "actor": "",
            "value_usd": 0.0,
            "date": "",
        }
    ]


# ---------------------------------------------------------------------------
# Risk Dashboard (#533)
# ---------------------------------------------------------------------------


@app.get("/pi/risk/dashboard")
@with_chain(
    endpoint="pi/risk/dashboard",
    family="risk/dashboard",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def risk_dashboard(
    request: Request, account_id: str = "demo"
) -> dict[str, float | str]:
    """Number-grid risk metrics for the paper account."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return {
            "vol_annualized": 0.184,
            "var_95_1d": -0.021,
            "beta_spy": 1.08,
            "note": "demo book",
        }
    return {
        "vol_annualized": 0.0,
        "var_95_1d": 0.0,
        "beta_spy": 0.0,
        "note": "not wired",
    }


@app.get("/pi/risk/vol")
@with_chain(
    endpoint="pi/risk/vol",
    family="risk/vol",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def risk_vol(
    request: Request, account_id: str = "demo"
) -> list[dict[str, float | str]]:
    """Return rolling 20d / 60d realized volatility."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return [
            {
                "date": f"2026-06-{d:02d}",
                "vol_20d": 0.16 + 0.02 * ((d % 5) - 2) / 3,
                "vol_60d": 0.18 + 0.01 * ((d % 7) - 3) / 3,
            }
            for d in range(1, 31)
        ]
    return [{"date": "", "vol_20d": 0.0, "vol_60d": 0.0}]


# ---------------------------------------------------------------------------
# Paper Trading widgets (#549, #550, #551, #555)
# ---------------------------------------------------------------------------


@app.get("/pi/paper/ticket")
def paper_ticket(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    request: Request,
    account_id: str = "demo",
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: str = "100",
    confirm: str = "false",
) -> str:
    """Two-step paper order ticket. First call previews, second commits."""
    _require_auth(request)
    _validate_account(account_id)
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail="symbol invalid")
    if side not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="side must be buy or sell")
    try:
        qty = int(quantity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="quantity not int") from exc
    if qty <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    commit = confirm.lower() == "true"
    verb = "COMMITTED" if commit else "PREVIEW"
    tail = (
        "> Order committed to the paper ledger (stub — full wiring to "
        "`paper.ledger.LedgerStore.append` pending)."
        if commit
        else "> Preview only. Re-submit with `confirm=true` to commit."
    )
    return (
        f"## Paper Order — {verb}\n\n"
        f"- **Account:** `{account_id}`\n"
        f"- **Side:** {side.upper()}\n"
        f"- **Symbol:** `{sym}`\n"
        f"- **Quantity:** {qty}\n\n"
        f"{tail}"
    )


@app.get("/pi/paper/blotter")
@with_chain(
    endpoint="pi/paper/blotter",
    family="paper/blotter",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def paper_blotter(
    request: Request, account_id: str = "demo"
) -> list[dict[str, str | float | int]]:
    """Recent paper orders + status."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return [
            {
                "time": "2026-07-20T14:30:00Z",
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 100,
                "status": "FILLED",
                "avg_price": 227.45,
            },
            {
                "time": "2026-07-19T15:02:00Z",
                "symbol": "NVDA",
                "side": "BUY",
                "qty": 50,
                "status": "FILLED",
                "avg_price": 118.20,
            },
            {
                "time": "2026-07-18T13:45:00Z",
                "symbol": "TSLA",
                "side": "SELL",
                "qty": 25,
                "status": "FILLED",
                "avg_price": 244.10,
            },
        ]
    return [
        {
            "time": "",
            "symbol": "(no-data)",
            "side": "",
            "qty": 0,
            "status": "not wired",
            "avg_price": 0.0,
        }
    ]


@app.get("/pi/paper/performance")
@with_chain(
    endpoint="pi/paper/performance",
    family="paper/performance",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def paper_performance(
    request: Request, account_id: str = "demo"
) -> list[dict[str, str | float]]:
    """Equity curve (records list for a raw chart)."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return [
            {
                "date": f"2026-06-{d:02d}",
                "equity": 100_000 * (1 + 0.001 * d + 0.0008 * ((d % 5) - 2)),
            }
            for d in range(1, 31)
        ]
    return [{"date": "", "equity": 0.0}]


@app.get("/pi/paper/perf-kpis")
@with_chain(
    endpoint="pi/paper/perf-kpis",
    family="paper/perf-kpis",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def paper_perf_kpis(
    request: Request, account_id: str = "demo"
) -> dict[str, float | str]:
    """Total return, Sharpe, max drawdown."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return {
            "total_return_pct": 3.24,
            "sharpe_annualized": 1.42,
            "max_drawdown_pct": -1.87,
            "note": "demo book — 30 trading days",
        }
    return {
        "total_return_pct": 0.0,
        "sharpe_annualized": 0.0,
        "max_drawdown_pct": 0.0,
        "note": "not wired",
    }


# ---------------------------------------------------------------------------
# What-If structured diff card (#552)
# ---------------------------------------------------------------------------


@app.get("/pi/whatif/card")
@with_chain(
    endpoint="pi/whatif/card",
    family="whatif/card",
    record_tier_used=record_tier_used,
    kwargs_from=lambda *_a, symbol="AAPL", delta_shares="100", **_k: {
        "symbol": symbol,
        "delta_shares": delta_shares,
    },
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def whatif_card(
    request: Request, symbol: str = "AAPL", delta_shares: str = "100"
) -> list[dict[str, float | str]]:
    """Structured before/after diff for the What-If trade."""
    _require_auth(request)
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail="symbol invalid")
    try:
        delta = int(delta_shares)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="delta_shares not int") from exc
    return [
        {
            "metric": "symbol_weight_%",
            "before": 4.8,
            "after": 4.8 + 0.001 * delta,
            "delta": 0.001 * delta,
        },
        {
            "metric": "sector_weight_%",
            "before": 37.2,
            "after": 37.2 + 0.001 * delta,
            "delta": 0.001 * delta,
        },
        {
            "metric": "cash_%",
            "before": 5.0,
            "after": 5.0 - 0.001 * delta,
            "delta": -0.001 * delta,
        },
        {
            "metric": "beta_spy",
            "before": 1.08,
            "after": 1.08 + 0.0002 * delta,
            "delta": 0.0002 * delta,
        },
    ]


# ---------------------------------------------------------------------------
# P3 widgets — News, Sentiment, Alerts, Backtest (#575, #576, #577)
# ---------------------------------------------------------------------------


@app.get("/pi/news")
@with_chain(
    endpoint="pi/news",
    family="news",
    record_tier_used=record_tier_used,
    kwargs_from=lambda *_a, account_id="demo", horizon_days="7", **_k: {
        "account_id": account_id,
        "horizon_days": horizon_days,
    },
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def pi_news(
    request: Request, account_id: str = "demo", horizon_days: str = "7"
) -> list[dict[str, str]]:
    """Recent news for held symbols."""
    _require_auth(request)
    _validate_account(account_id)
    try:
        days = int(horizon_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="horizon_days not int") from exc
    if not 1 <= days <= 90:
        raise HTTPException(status_code=400, detail="horizon_days out of range")
    if account_id == "demo":
        return [
            {
                "symbol": "AAPL",
                "when": "2026-07-19",
                "title": "Apple beats Q3 EPS; services growth accelerates",
                "severity": "material",
            },
            {
                "symbol": "NVDA",
                "when": "2026-07-18",
                "title": "NVIDIA announces new datacenter GPU",
                "severity": "material",
            },
            {
                "symbol": "MSFT",
                "when": "2026-07-17",
                "title": "Microsoft raises Azure guidance",
                "severity": "material",
            },
        ]
    return [
        {
            "symbol": "(no-data)",
            "when": "",
            "title": "account resolver not wired",
            "severity": "info",
        }
    ]


@app.get("/pi/sentiment")
@with_chain(
    endpoint="pi/sentiment",
    family="sentiment",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def pi_sentiment(request: Request, account_id: str = "demo") -> dict[str, float | str]:
    """Aggregate sentiment score across recent held-symbol news."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return {
            "value": 0.62,
            "label": "Sentiment (-1..+1)",
            "note": "demo — 7d window",
        }
    return {"value": 0.0, "label": "Sentiment", "note": "not wired"}


@app.get("/pi/alerts")
@with_chain(
    endpoint="pi/alerts",
    family="alerts",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def pi_alerts(request: Request, account_id: str = "demo") -> list[dict[str, str]]:
    """Active alerts for the paper account."""
    _require_auth(request)
    _validate_account(account_id)
    if account_id == "demo":
        return [
            {
                "severity": "warning",
                "kind": "form_8k_for_held",
                "symbol": "NVDA",
                "detail": "8-K Item 7.01 filed 2026-07-22",
            },
            {
                "severity": "info",
                "kind": "earnings_upcoming",
                "symbol": "AAPL",
                "detail": "Earnings 2026-07-25",
            },
            {
                "severity": "critical",
                "kind": "news_material",
                "symbol": "TSLA",
                "detail": "Recall notice",
            },
        ]
    return [
        {
            "severity": "info",
            "kind": "wiring",
            "symbol": "(no-data)",
            "detail": "account resolver not wired",
        }
    ]


@app.get("/pi/backtest/oneclick")
@with_chain(
    endpoint="pi/backtest/oneclick",
    family="backtest/oneclick",
    record_tier_used=record_tier_used,
    kwargs_from=_account_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_account_from_call,
)
def pi_backtest_oneclick(request: Request, account_id: str = "demo") -> str:
    """Kick off a walk-forward backtest (stub)."""
    _require_auth(request)
    _validate_account(account_id)
    return (
        "## Backtest — kicked off\n\n"
        f"- **Account:** `{account_id}`\n"
        "- **Status:** queued (stub — full wiring to `openbb_backtest.run` pending)\n\n"
        "> Preview stub: real button hands off the paper book's rules to "
        "`openbb-backtest` for a walk-forward run."
    )


# ---------------------------------------------------------------------------
# Equity Profile section widgets 990 through 996
# ---------------------------------------------------------------------------


@app.get("/pi/equity/header")
@with_chain(
    endpoint="pi/equity/header",
    family="equity/header",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_header(request: Request, symbol: str = "AAPL") -> str:
    """Equity Profile section 1 — header + live price ticker (markdown)."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    return (
        f"## {sym}\n\n"
        f"- **Exchange:** NASDAQ (stub)\n"
        f"- **Sector / Industry:** Technology / Consumer Electronics (stub)\n"
        f"- **Price:** $228.14 (stub)\n"
        f"- **Day Change:** +1.23 (+0.54%) (stub)\n"
        f"- **Live Price:** $228.14 (+1.23, +0.54%) — last update stub\n"
        f"- **Overnight (BOATS):** $228.20 (+0.06)\n\n"
        "> Preview stub — real wiring calls obb.equity.profile(symbol) plus "
        "obb.equity.price.quote(symbol) plus obb.equity.price.aftermarket_quote(symbol)."
    )


@app.get("/pi/equity/key-stats")
@with_chain(
    endpoint="pi/equity/key-stats",
    family="equity/key-stats",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_key_stats(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Equity Profile section 2 — key stats grid (table)."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    return [
        {"metric": "Market Cap", "value": "$3.47T"},
        {"metric": "P/E (TTM)", "value": 32.1},
        {"metric": "Forward P/E", "value": 29.4},
        {"metric": "EV/EBITDA", "value": 24.8},
        {"metric": "P/S (TTM)", "value": 8.7},
        {"metric": "EPS (TTM)", "value": 6.51},
        {"metric": "Revenue (FY)", "value": "$391B"},
        {"metric": "Net Income (FY)", "value": "$93B"},
        {"metric": "Shares Float", "value": "15.2B"},
        {"metric": "Short Interest", "value": "0.68%"},
        {"metric": "Insider Ownership", "value": "0.07%"},
        {"metric": "Beta (1Y)", "value": 1.20},
        {"metric": "Dividend Yield", "value": "0.42%"},
        {"metric": "Volume (today)", "value": "48M"},
        {"metric": "Volume (30d avg)", "value": "52M"},
        {"metric": "Next Earnings", "value": "2026-07-25 (Q3 2026)"},
        {"metric": "Symbol", "value": sym},
    ]


@app.get("/pi/equity/financials")
@with_chain(
    endpoint="pi/equity/financials",
    family="equity/financials",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_financials(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, float | str]]:
    """Equity Profile section 3 — 5-yr financials (chart raw)."""
    _require_auth(request)
    _validate_symbol(symbol)
    years = [2021, 2022, 2023, 2024, 2025]
    revs = [365.8, 394.3, 383.3, 391.0, 400.5]
    nis = [94.7, 99.8, 97.0, 93.0, 102.3]
    return [
        {
            "year": y,
            "revenue_b": r,
            "net_income_b": n,
            "net_margin_pct": round(n / r * 100, 2),
        }
        for y, r, n in zip(years, revs, nis)
    ]


@app.get("/pi/equity/technicals")
@with_chain(
    endpoint="pi/equity/technicals",
    family="equity/technicals",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_technicals(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Equity Profile section 4 — consensus + pivot matrix (table). IV blocked on gap 999."""
    _require_auth(request)
    _validate_symbol(symbol)
    high, low, close = 230.5, 226.2, 228.14
    p = (high + low + close) / 3
    r1, s1 = 2 * p - low, 2 * p - high
    r2, s2 = p + (high - low), p - (high - low)
    r3, s3 = high + 2 * (p - low), low - 2 * (high - p)
    return [
        {"metric": "Consensus", "value": "BUY", "note": "24 analysts"},
        {"metric": "R3 (Classic)", "value": round(r3, 2), "note": ""},
        {"metric": "R2 (Classic)", "value": round(r2, 2), "note": ""},
        {"metric": "R1 (Classic)", "value": round(r1, 2), "note": ""},
        {"metric": "P (Classic)", "value": round(p, 2), "note": "pivot"},
        {"metric": "S1 (Classic)", "value": round(s1, 2), "note": ""},
        {"metric": "S2 (Classic)", "value": round(s2, 2), "note": ""},
        {"metric": "S3 (Classic)", "value": round(s3, 2), "note": ""},
        {"metric": "ATM IV term structure", "value": "BLOCKED", "note": "gap 999"},
    ]


@app.get("/pi/equity/analyst-forecasts")
@with_chain(
    endpoint="pi/equity/analyst-forecasts",
    family="equity/analyst-forecasts",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_analyst_forecasts(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Equity Profile section 5 — analyst forecasts + surprise (table).

    Rating distribution (5B) is LIVE via FMPCachedAnalystRecommendationsFetcher
    (#997 / #1022). Historical revenue estimates (5C) still blocked on #998.
    """
    _require_auth(request)
    sym = _validate_symbol(symbol)

    rows: list[dict[str, str | float]] = [
        {"metric": "1Y target (consensus)", "value": 245.0, "note": "sample n=32"},
        {"metric": "Target range", "value": "215..280", "note": ""},
        {"metric": "Upside vs current", "value": "7.4%", "note": ""},
    ]

    # Rating distribution — live via #997
    # pylint: disable=import-outside-toplevel,broad-exception-caught,redefined-outer-name,reimported
    try:
        import asyncio

        from openbb_fmp_cached import fmp_cached_provider

        cls = fmp_cached_provider.fetcher_dict["AnalystRecommendations"]
        q = cls.transform_query({"symbol": sym})
        raw = asyncio.run(cls.aextract_data(q, None))
        summary = cls.transform_data(q, raw)[0]
        rows.extend(
            [
                {
                    "metric": "Rating: Strong Buy / Buy",
                    "value": f"{summary.strong_buy} / {summary.buy}",
                    "note": f"as of {summary.as_of}; n={summary.total} firms",
                },
                {
                    "metric": "Rating: Hold / Sell / Strong Sell",
                    "value": f"{summary.hold} / {summary.sell} / {summary.strong_sell}",
                    "note": (
                        f"unknown_count={summary.unknown_count}"
                        if summary.unknown_count
                        else ""
                    ),
                },
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyst-forecasts: recommendations fetch failed: %s", exc)
        # Never echo raw exception text to HTTP clients — exception
        # messages can carry credential fragments (e.g. an httpx error
        # embedding the request URL with apikey=... in the query
        # string). Return a static note; operators find the detail in
        # server logs via the WARN line above.
        rows.extend(
            [
                {
                    "metric": "Rating: Strong Buy / Buy",
                    "value": "n/a",
                    "note": "fetch failed (see server logs)",
                },
                {
                    "metric": "Rating: Hold / Sell / Strong Sell",
                    "value": "n/a",
                    "note": "fetch failed",
                },
            ]
        )

    rows.extend(
        [
            {
                "metric": "Q3 2025 EPS Surprise",
                "value": "+3.2%",
                "note": "actual 1.55 vs est 1.50",
            },
            {
                "metric": "Q2 2025 EPS Surprise",
                "value": "+1.9%",
                "note": "actual 1.52 vs est 1.49",
            },
        ]
    )

    # Revenue surprise (5C) — live via #998 opportunistic history
    # (#1025 / #1026). Only rendered when a historical snapshot exists;
    # otherwise render "insufficient history" so the widget documents
    # the state honestly rather than fabricating a surprise%.
    # pylint: disable=import-outside-toplevel,broad-exception-caught
    try:
        from datetime import (
            date as _date,
            timedelta as _td,
        )

        from openbb_fmp_cached.models.analyst_estimates import (
            get_estimate_as_of,
        )

        # Look up an estimate that was captured before the most recent
        # earnings release. For the demo path we probe the last-completed
        # quarter end (approximately today - 90 days).
        today = _date.today()
        approx_last_qend = today - _td(days=90)
        snap = get_estimate_as_of(
            symbol=sym,
            fiscal_period_end=approx_last_qend,
            as_of_date=approx_last_qend,
            period="quarter",
        )
        if snap and snap.get("estimated_revenue_avg"):
            rows.append(
                {
                    "metric": "Historical rev estimate (last Q)",
                    "value": float(snap["estimated_revenue_avg"]),
                    "note": (
                        f"snapshot {snap.get('snapshot_date')}; "
                        "surprise% computed once actual revenue lands"
                    ),
                }
            )
        else:
            rows.append(
                {
                    "metric": "Historical rev estimate",
                    "value": "insufficient history",
                    "note": (
                        "no snapshot in analyst_estimates_history yet; "
                        "surprise% available once opportunistic snapshots "
                        "accumulate (#998 / #1025)"
                    ),
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyst-forecasts: history lookup failed: %s", exc)
        # Don't echo raw exception to HTTP client — see rating-fetch
        # rationale above. Detail is in the WARN log.
        rows.append(
            {
                "metric": "Historical rev estimate",
                "value": "n/a",
                "note": "lookup failed (see server logs)",
            }
        )
    return rows


@app.get("/pi/equity/complementary")
@with_chain(
    endpoint="pi/equity/complementary",
    family="equity/complementary",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_complementary(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Equity Profile section 6 — ETF exposure + bond ladder (table). Bonds blocked on gap 1000."""
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {
            "kind": "ETF",
            "id": "SPY",
            "name": "SPDR S&P 500",
            "weight_pct": 7.0,
            "value_usd": "$62B",
        },
        {
            "kind": "ETF",
            "id": "QQQ",
            "name": "Invesco QQQ Trust",
            "weight_pct": 8.9,
            "value_usd": "$25B",
        },
        {
            "kind": "ETF",
            "id": "VOO",
            "name": "Vanguard S&P 500",
            "weight_pct": 7.0,
            "value_usd": "$52B",
        },
        {
            "kind": "ETF",
            "id": "XLK",
            "name": "SPDR Technology",
            "weight_pct": 22.1,
            "value_usd": "$14B",
        },
        {
            "kind": "Bond",
            "id": "BLOCKED",
            "name": "corporate bond ladder",
            "weight_pct": 0.0,
            "value_usd": "gap 1000",
        },
    ]


@app.get("/pi/equity/competitors")
@with_chain(
    endpoint="pi/equity/competitors",
    family="equity/competitors",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_competitors(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Equity Profile section 7 — competitor strip (table)."""
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {
            "symbol": "MSFT",
            "name": "Microsoft Corp.",
            "price": 428.10,
            "change_pct": 0.85,
        },
        {
            "symbol": "GOOGL",
            "name": "Alphabet Inc. Class A",
            "price": 178.40,
            "change_pct": -0.42,
        },
        {
            "symbol": "META",
            "name": "Meta Platforms Inc.",
            "price": 512.75,
            "change_pct": 1.20,
        },
        {
            "symbol": "AMZN",
            "name": "Amazon.com Inc.",
            "price": 194.30,
            "change_pct": 0.33,
        },
        {"symbol": "NVDA", "name": "NVIDIA Corp.", "price": 118.20, "change_pct": 2.10},
    ]


# ---------------------------------------------------------------------------
# Price-history widget with line ↔ candlestick toggle (#1702)
#
# Serves either a light ``{date, close}`` shape (default, backward-compat with
# the existing line-only chart contract) or a full ``{date, open, high, low,
# close, volume}`` OHLC shape when ``chart_type=candle``.
#
# Design notes:
# - Data is a deterministic demo dataset (hermetic, offline, hashes stable
#   across runs). Wiring to the fmp_cached provider is a follow-up (see the
#   ``TODO`` block in-body) — the shape contract is what the widget consumes,
#   so the toggle is testable end-to-end today.
# - Server chooses the row shape from the query param; the widget spec
#   surfaces the same param to the Workspace user via a dropdown.
# ---------------------------------------------------------------------------


_ALLOWED_CHART_TYPES = ("line", "candle")


def _demo_ohlc_series(symbol: str, days: int = 20) -> list[dict]:
    """Return a deterministic OHLC series keyed off the symbol hash.

    Uses a simple sinusoid + linear drift, seeded by the symbol so different
    tickers get visibly different (but reproducible) curves. Kept dependency-
    free so the unit tests never touch the network.
    """
    # Deterministic seed per symbol — never uses time.
    seed = sum(ord(c) for c in symbol.upper())
    base = 100.0 + (seed % 200)
    out: list[dict] = []
    for i in range(days):
        drift = i * 0.5
        wave = math.sin((seed + i) / 3.0) * 2.5
        close = round(base + drift + wave, 2)
        # Build a realistic bar around ``close``.
        open_ = round(close - math.cos((seed + i) / 3.0) * 1.0, 2)
        high = round(max(open_, close) + abs(math.sin((seed + i) / 2.0)) * 1.2, 2)
        low = round(min(open_, close) - abs(math.cos((seed + i) / 2.0)) * 1.2, 2)
        volume = int(1_000_000 + (seed * (i + 1)) % 5_000_000)
        out.append(
            {
                # Trailing "T00:00:00" makes the date parse-friendly in
                # Workspace's chart renderer without pinning a timezone.
                "date": f"2026-06-{(i % 28) + 1:02d}",
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return out


@app.get("/pi/equity/price-history")
@with_chain(
    endpoint="pi/equity/price-history",
    family="equity/price-history",
    record_tier_used=record_tier_used,
    kwargs_from=_price_history_kwargs,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_price_history_from_call,
)
def equity_price_history(
    request: Request,
    symbol: str = "AAPL",
    chart_type: str = "line",
) -> list[dict]:
    """Return a price-history series in either line or candlestick shape.

    * ``chart_type=line`` (default): rows are ``{date, close}``.
    * ``chart_type=candle``: rows are ``{date, open, high, low, close, volume}``.

    Any other ``chart_type`` value is a 400 — no silent fallback to line,
    because that would hide a UI wiring bug where the widget sent us a
    typo (which was #1633's failure mode: the chart-mapping silently
    normalized bad values). Loud rejection surfaces the mismatch at PR
    time via the manifest ↔ endpoint parity test.
    """
    require_auth(request)
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=400,
            detail=(
                "symbol must match [A-Z0-9.-]{1,10}; "
                f"got {symbol!r} (rejected before price-history fetch)"
            ),
        )
    if chart_type not in _ALLOWED_CHART_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"chart_type must be one of {_ALLOWED_CHART_TYPES}; "
                f"got {chart_type!r}. Use ``line`` or ``candle``."
            ),
        )

    # Live data is served by the ``fmp_cached`` tier registered in
    # ``widget_backend.tier_calls`` (full-wiring #1898), routed through the
    # provider chain by the ``@with_chain`` decorator above. This stub body
    # is the chain-exhaustion fallback only: it runs when fmp_cached (and any
    # lower tier) is unavailable/empty, keeping the widget renderable offline
    # and in hermetic tests. Shape here MUST match the tier call's shaper.
    bars = _demo_ohlc_series(sym)

    if chart_type == "line":
        return [{"date": b["date"], "close": b["close"]} for b in bars]
    # chart_type == "candle"
    return bars


# ---------------------------------------------------------------------------
# F1 Batch B — BUILD widgets over fmp_cached endpoints (stub-shaped)
# ---------------------------------------------------------------------------
#
# The four endpoints below all have corresponding FMPCached fetchers in
# openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/
#     price_performance.py, key_executives.py,
#     revenue_geographic.py, revenue_business_line.py
# Real fetcher wiring lands per-widget in a follow-up cycle (same
# stub-first policy as every other F0/F1 widget on this backend). The
# shape contract shipped here is what unlocks Workspace rendering and
# downstream tab work.


@app.get("/pi/equity/price-performance")
@with_chain(
    endpoint="pi/equity/price-performance",
    family="equity/price-performance",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_price_performance(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Price Performance rows (#1645) — trailing return by horizon (table)."""
    _require_auth(request)
    _validate_symbol(symbol)
    # Live-served via fmp_cached tier (#1900, register_all in tier_calls.py);
    # this stub body is the loud fallback when the live tier is empty/errors.
    return [
        {"period": "1D", "return_pct": 0.54},
        {"period": "1W", "return_pct": 1.82},
        {"period": "1M", "return_pct": 3.41},
        {"period": "3M", "return_pct": 7.20},
        {"period": "6M", "return_pct": 12.85},
        {"period": "YTD", "return_pct": 18.44},
        {"period": "1Y", "return_pct": 24.10},
        {"period": "3Y", "return_pct": 82.31},
        {"period": "5Y", "return_pct": 245.60},
    ]


@app.get("/pi/equity/management-team")
@with_chain(
    endpoint="pi/equity/management-team",
    family="equity/management-team",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_management_team(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | None]]:
    """Return Management Team rows (#1648) — key executives (table).

    Live-served from ``fmp_cached`` via the ``equity/management-team`` tier
    call (#1902); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {
            "name": "Timothy D. Cook",
            "title": "CEO",
            "pay_usd": 63209845,
            "tenure_years": 12,
        },
        {
            "name": "Luca Maestri",
            "title": "CFO",
            "pay_usd": 27129231,
            "tenure_years": 10,
        },
        {
            "name": "Jeff Williams",
            "title": "COO",
            "pay_usd": 26985763,
            "tenure_years": 8,
        },
        {
            "name": "Katherine L. Adams",
            "title": "General Counsel",
            "pay_usd": 26985763,
            "tenure_years": 7,
        },
        {
            "name": "Deirdre O'Brien",
            "title": "SVP Retail & People",
            "pay_usd": 26985763,
            "tenure_years": 6,
        },
    ]


@app.get("/pi/equity/revenue-geography")
@with_chain(
    endpoint="pi/equity/revenue-geography",
    family="equity/revenue-geography",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_revenue_geography(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Revenue Per Geography rows (#1649) — region/revenue (chart raw).

    Live-served from ``fmp_cached`` via the ``equity/revenue-geography`` tier
    call (#1904); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {"region": "Americas", "revenue": 162560},
        {"region": "Europe", "revenue": 94294},
        {"region": "Greater China", "revenue": 66952},
        {"region": "Japan", "revenue": 24257},
        {"region": "Rest of Asia Pacific", "revenue": 29615},
    ]


@app.get("/pi/equity/revenue-business-line")
@with_chain(
    endpoint="pi/equity/revenue-business-line",
    family="equity/revenue-business-line",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_revenue_business_line(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Revenue Per Business Line rows (#1650) — segment/revenue (chart raw).

    Live-served from ``fmp_cached`` via the ``equity/revenue-business-line``
    tier call (#1906); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {"segment": "iPhone", "revenue": 200583},
        {"segment": "Services", "revenue": 96169},
        {"segment": "Wearables, Home & Accessories", "revenue": 39845},
        {"segment": "Mac", "revenue": 29357},
        {"segment": "iPad", "revenue": 28300},
    ]


# ---------------------------------------------------------------------------
# Tier 1 — F5 Ownership + F6 Company Calendar + F7 Estimates (stub-shaped)
# ---------------------------------------------------------------------------
#
# 9 BUILD widgets over fmp_cached endpoints. Same stub-first policy every
# other F0/F1 widget follows. Real fetcher wiring per widget in follow-up.


@app.get("/pi/equity/institutional-ownership")
@with_chain(
    endpoint="pi/equity/institutional-ownership",
    family="equity/institutional-ownership",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_institutional_ownership(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | int]]:
    """Return Institutional Ownership rows (#1659) — 13F holders (table)."""
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1659): wire to FMPCachedInstitutionalOwnershipFetcher.
    return [
        {"holder": "Vanguard Group Inc", "shares": 1359000000, "pct_owned": 8.82},
        {"holder": "BlackRock Inc", "shares": 1050000000, "pct_owned": 6.82},
        {"holder": "Berkshire Hathaway Inc", "shares": 906000000, "pct_owned": 5.88},
        {"holder": "State Street Corp", "shares": 590000000, "pct_owned": 3.83},
        {"holder": "FMR LLC (Fidelity)", "shares": 340000000, "pct_owned": 2.21},
    ]


@app.get("/pi/equity/stock-ownership")
@with_chain(
    endpoint="pi/equity/stock-ownership",
    family="equity/stock-ownership",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_stock_ownership(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Stock Ownership rows (#1660) — insider/inst/retail split (chart raw)."""
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1660): wire to FMPCachedEquityOwnershipFetcher.
    return [
        {"bucket": "Institutions", "pct": 61.4},
        {"bucket": "Retail", "pct": 32.5},
        {"bucket": "ETFs", "pct": 5.4},
        {"bucket": "Insiders", "pct": 0.7},
    ]


@app.get("/pi/equity/insider-trading")
@with_chain(
    endpoint="pi/equity/insider-trading",
    family="equity/insider-trading",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_insider_trading(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | int]]:
    """Return Insider Trading rows (#1661) — recent transactions (table).

    Live-served from ``fmp_cached`` via the ``equity/insider-trading`` tier
    call (#1910); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {
            "name": "Cook Timothy D",
            "date": "2026-05-01",
            "shares": -223986,
            "transaction_type": "S-Sale",
            "price_usd": 173.45,
        },
        {
            "name": "Maestri Luca",
            "date": "2026-04-14",
            "shares": -50000,
            "transaction_type": "S-Sale",
            "price_usd": 169.85,
        },
        {
            "name": "Williams Jeff",
            "date": "2026-04-10",
            "shares": -25000,
            "transaction_type": "S-Sale",
            "price_usd": 168.10,
        },
        {
            "name": "Adams Katherine",
            "date": "2026-03-15",
            "shares": -10000,
            "transaction_type": "S-Sale",
            "price_usd": 173.20,
        },
    ]


@app.get("/pi/equity/earnings-history")
@with_chain(
    endpoint="pi/equity/earnings-history",
    family="equity/earnings-history",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_earnings_history(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | None]]:
    """Return Earnings History rows (#1663) — EPS actual vs. estimate (table).

    Live-served from ``fmp_cached`` via the ``equity/earnings-history`` tier
    call (#1912); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {
            "quarter": "Q3 2026",
            "eps_actual": 1.65,
            "eps_estimate": 1.60,
            "surprise_pct": 3.13,
        },
        {
            "quarter": "Q2 2026",
            "eps_actual": 1.53,
            "eps_estimate": 1.50,
            "surprise_pct": 2.00,
        },
        {
            "quarter": "Q1 2026",
            "eps_actual": 2.18,
            "eps_estimate": 2.10,
            "surprise_pct": 3.81,
        },
        {
            "quarter": "Q4 2025",
            "eps_actual": 1.46,
            "eps_estimate": 1.39,
            "surprise_pct": 5.04,
        },
        {
            "quarter": "Q3 2025",
            "eps_actual": 1.40,
            "eps_estimate": 1.35,
            "surprise_pct": 3.70,
        },
    ]


@app.get("/pi/equity/stock-splits")
@with_chain(
    endpoint="pi/equity/stock-splits",
    family="equity/stock-splits",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_stock_splits(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | int]]:
    """Return Stock Splits rows (#1664) — historical split events (table).

    Live-served from ``fmp_cached`` via the ``equity/stock-splits`` tier call
    (#1916); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {"date": "2020-08-31", "numerator": 4, "denominator": 1, "ratio": "4:1"},
        {"date": "2014-06-09", "numerator": 7, "denominator": 1, "ratio": "7:1"},
        {"date": "2005-02-28", "numerator": 2, "denominator": 1, "ratio": "2:1"},
        {"date": "2000-06-21", "numerator": 2, "denominator": 1, "ratio": "2:1"},
        {"date": "1987-06-16", "numerator": 2, "denominator": 1, "ratio": "2:1"},
    ]


@app.get("/pi/equity/dividend-payment")
@with_chain(
    endpoint="pi/equity/dividend-payment",
    family="equity/dividend-payment",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_dividend_payment(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Dividend Payment rows (#1665) — recent dividends (table).

    Live-served from ``fmp_cached`` via the ``equity/dividend-payment`` tier
    call (#1908); this stub body is the loud fallback when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    return [
        {"ex_date": "2026-05-10", "payment_date": "2026-05-16", "amount": 0.25},
        {"ex_date": "2026-02-09", "payment_date": "2026-02-15", "amount": 0.24},
        {"ex_date": "2025-11-10", "payment_date": "2025-11-16", "amount": 0.24},
        {"ex_date": "2025-08-11", "payment_date": "2025-08-17", "amount": 0.24},
    ]


@app.get("/pi/equity/company-filings")
@with_chain(
    endpoint="pi/equity/company-filings",
    family="equity/company-filings",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
    kwargs_from=_symbol_kwargs,
)
def equity_company_filings(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | None]]:
    """Return Company Filings rows (#1666) — recent SEC filings (table).

    Live data is served by the ``equity/company-filings`` fmp_cached tier
    call (:mod:`.tier_calls`); this stub body is the loud fallback the chain
    returns to only when the live tier fails or yields nothing.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    # Stub rows MUST use the SAME keys the live fmp_cached tier emits
    # (``_shape_company_filings`` -> filing_date/report_type/report_url/
    # filing_url). Keeping stub and live shapes identical makes the endpoint
    # column-stable regardless of cache state and the shape test deterministic
    # (anti-mock rule: stub shape == live shape).
    return [
        {
            "filing_date": "2026-05-01",
            "report_type": "10-Q",
            "report_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            "filing_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        },
        {
            "filing_date": "2026-04-15",
            "report_type": "8-K",
            "report_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            "filing_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        },
        {
            "filing_date": "2026-02-01",
            "report_type": "10-Q",
            "report_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            "filing_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        },
        {
            "filing_date": "2025-11-01",
            "report_type": "10-K",
            "report_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            "filing_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        },
        {
            "filing_date": "2025-10-27",
            "report_type": "8-K",
            "report_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            "filing_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        },
    ]


@app.get("/pi/equity/earnings-transcripts")
@with_chain(
    endpoint="pi/equity/earnings-transcripts",
    family="equity/earnings-transcripts",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_earnings_transcripts(request: Request, symbol: str = "AAPL") -> str:
    """Return Earnings Transcript preview (#1667) — latest call summary (markdown)."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    # TODO(gh-1667): wire to FMPCachedEarningsCallTranscriptFetcher.
    return (
        f"## {sym} — Latest Earnings Call (stub)\n\n"
        "- **Date:** 2026-05-01\n"
        "- **Quarter:** Q2 2026\n"
        "- **Speakers:** Timothy Cook (CEO), Luca Maestri (CFO)\n\n"
        "> Preview stub — real wiring pulls the full transcript from "
        "FMPCachedEarningsCallTranscriptFetcher and renders the opening "
        "remarks + Q&A digest here."
    )


@app.get("/pi/equity/price-target-history")
@with_chain(
    endpoint="pi/equity/price-target-history",
    family="equity/price-target-history",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_price_target_history(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Price Target vs. Close time series (#1669) — target evolution (chart)."""
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1669): wire to FMPCachedPriceTargetConsensusFetcher over time series.
    return [
        {"date": "2025-11-01", "close": 152.20, "target": 175.00},
        {"date": "2026-01-15", "close": 168.35, "target": 185.00},
        {"date": "2026-02-01", "close": 172.10, "target": 190.00},
        {"date": "2026-04-01", "close": 174.05, "target": 195.00},
        {"date": "2026-05-01", "close": 173.45, "target": 200.00},
    ]


# ---------------------------------------------------------------------------
# Tier 2 — F2 Financials + F3 Technicals + F4 Comparison (stub-shaped)
# ---------------------------------------------------------------------------


#: Allowed statement periods (widget-facing values, mapped in the tier call).
_STATEMENT_PERIODS = ("annual", "quarterly")


def _statements_kwargs(
    *_args: object,
    symbol: str = "AAPL",
    period: str = "annual",
    **_kwargs: object,
) -> dict:
    """Forward the normalized ``symbol`` + ``period`` to the statements tier.

    The default ``kwargs_from`` forwards only the raw ``symbol``; the live tier
    needs ``period`` too (to pick annual vs quarterly statements) and the
    *normalized* ticker so an unnormalized ``" aapl "`` cannot reach the
    provider verbatim, return empty, and silently fall to the demo stub.
    """
    return {"symbol": _validate_symbol(symbol), "period": period}


def _validate_statements_from_call(
    *_args: object,
    symbol: str = "AAPL",
    period: str = "annual",
    **_kwargs: object,
) -> None:
    """Validate ``symbol`` AND ``period`` before any tier is dispatched.

    Both checks must run pre-dispatch: once a live tier serves the request the
    stub body (with its own inline period check) is bypassed, so validation
    living only there would let an invalid ``period`` reach the tier call.
    """
    _validate_symbol(symbol)
    if period not in _STATEMENT_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"period must be 'annual' or 'quarterly', got {period!r}",
        )


@app.get("/pi/equity/statements")
@with_chain(
    endpoint="pi/equity/statements",
    family="equity/statements",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_statements_from_call,
    kwargs_from=_statements_kwargs,
)
def equity_statements(
    request: Request, symbol: str = "AAPL", period: str = "annual"
) -> list[dict[str, str | float | int | None]]:
    """Return Financial Statements rows (#1653) — IS/BS/CF (table).

    Live-served from ``fmp_cached`` via the ``equity/statements`` tier call
    (#1920): fetches income/balance/cash statements and maps nine canonical
    line items to a 2-period comparison. This stub body is the loud fallback
    when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    if period not in _STATEMENT_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"period must be 'annual' or 'quarterly', got {period!r}",
        )
    scale = 1.0 if period == "annual" else 0.25
    return [
        {
            "line_item": "Revenue",
            "period_1": 391000 * scale,
            "period_2": 383300 * scale,
        },
        {
            "line_item": "Gross Profit",
            "period_1": 170782 * scale,
            "period_2": 169148 * scale,
        },
        {
            "line_item": "Operating Income",
            "period_1": 118658 * scale,
            "period_2": 114301 * scale,
        },
        {
            "line_item": "Net Income",
            "period_1": 93000 * scale,
            "period_2": 96995 * scale,
        },
        {"line_item": "Total Assets", "period_1": 364980, "period_2": 352755},
        {"line_item": "Total Debt", "period_1": 104590, "period_2": 111088},
        {"line_item": "Cash & Equivalents", "period_1": 61555, "period_2": 61555},
        {
            "line_item": "Operating Cash Flow",
            "period_1": 122151 * scale,
            "period_2": 110543 * scale,
        },
        {
            "line_item": "Free Cash Flow",
            "period_1": 111443 * scale,
            "period_2": 99584 * scale,
        },
    ]


#: Allowed charting windows (resolved at call time by the validate hook).
_CHARTING_WINDOWS = ("1M", "3M", "6M", "YTD", "1Y")


def _charting_kwargs(
    *_args: object,
    symbol: str = "AAPL",
    window: str = "3M",
    **_kwargs: object,
) -> dict:
    """Forward the normalized ``symbol`` + ``window`` to the charting tier.

    The default ``kwargs_from`` forwards only the raw ``symbol``; the live
    tier needs ``window`` too (to slice the series) and the *normalized*
    ticker (strip + upper) so an unnormalized ``" aapl "`` cannot reach the
    provider verbatim, return empty, and silently fall to the demo stub.
    """
    return {"symbol": _validate_symbol(symbol), "window": window}


def _validate_charting_from_call(
    *_args: object,
    symbol: str = "AAPL",
    window: str = "3M",
    **_kwargs: object,
) -> None:
    """Validate ``symbol`` AND ``window`` before any tier is dispatched.

    Both checks must run pre-dispatch: once a live tier serves the request the
    stub body (with its own inline window check) is bypassed, so validation
    living only there would let an invalid ``window`` reach the shaper.
    """
    _validate_symbol(symbol)
    if window not in _CHARTING_WINDOWS:
        raise HTTPException(
            status_code=400,
            detail=f"window must be one of {_CHARTING_WINDOWS}, got {window!r}",
        )


@app.get("/pi/equity/charting")
@with_chain(
    endpoint="pi/equity/charting",
    family="charting",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_charting_from_call,
    kwargs_from=_charting_kwargs,
)
def equity_charting(
    request: Request, symbol: str = "AAPL", window: str = "3M"
) -> list[dict[str, str | float | int | None]]:
    """Return Charting rows (#1655) — OHLC + indicator overlays (chart).

    Live-served from ``fmp_cached`` via the ``charting`` tier call (#1918):
    reuses the price-history fetch and computes SMA20/SMA50/RSI14 over the
    full series, sliced to ``window``. This stub body is the loud fallback
    when no tier serves.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    if window not in _CHARTING_WINDOWS:
        raise HTTPException(
            status_code=400,
            detail=f"window must be one of {_CHARTING_WINDOWS}, got {window!r}",
        )
    # Stub fallback rows (served only when no live tier answers).
    return [
        {
            "date": "2026-04-01",
            "open": 170.10,
            "high": 172.50,
            "low": 169.20,
            "close": 171.35,
            "sma20": 168.40,
            "sma50": 165.20,
            "rsi14": 58.2,
        },
        {
            "date": "2026-04-15",
            "open": 172.00,
            "high": 174.30,
            "low": 171.20,
            "close": 173.10,
            "sma20": 170.10,
            "sma50": 166.85,
            "rsi14": 62.4,
        },
        {
            "date": "2026-05-01",
            "open": 173.50,
            "high": 175.80,
            "low": 172.90,
            "close": 173.45,
            "sma20": 171.85,
            "sma50": 168.30,
            "rsi14": 55.7,
        },
    ]


@app.get("/pi/equity/peer-multiples")
@with_chain(
    endpoint="pi/equity/peer-multiples",
    family="equity/peer-multiples",
    record_tier_used=record_tier_used,
    require_auth=_require_auth_from_call,
    validate_kwargs=_validate_symbol_from_call,
)
def equity_peer_multiples(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Peer Multiples rows (#1657) — self + peers valuation matrix (table)."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    # TODO(gh-1657): wire to FMPCachedPeersFetcher + fan out key-metrics.
    return [
        {
            "symbol": sym,
            "pe_ttm": 32.1,
            "pe_fwd": 29.4,
            "ev_ebitda": 24.8,
            "ps_ttm": 8.7,
        },
        {
            "symbol": "MSFT",
            "pe_ttm": 34.9,
            "pe_fwd": 31.2,
            "ev_ebitda": 26.1,
            "ps_ttm": 12.4,
        },
        {
            "symbol": "GOOGL",
            "pe_ttm": 26.3,
            "pe_fwd": 23.1,
            "ev_ebitda": 18.9,
            "ps_ttm": 6.2,
        },
        {
            "symbol": "META",
            "pe_ttm": 27.6,
            "pe_fwd": 24.7,
            "ev_ebitda": 17.2,
            "ps_ttm": 9.1,
        },
    ]


# ---------------------------------------------------------------------------
# Techtrade Morning Scan (#1692 T13.1) — stub-shaped
# ---------------------------------------------------------------------------
#
# 3 widgets under the tt_* prefix, hosted in the existing portfolio-intel
# widget_backend server (Option A architecture). Real wiring calls
# openbb_techtrade.engine.scan and .screener_router in follow-up.


_SEGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 &_-]{0,63}$")


def _validate_segment(segment: str) -> str:
    """Reject XSS/malformed segment strings before echoing into rows."""
    if not _SEGMENT_RE.match(segment):
        raise HTTPException(
            status_code=400,
            detail=f"segment must match [A-Za-z][A-Za-z0-9 &_-]{{0,63}}; got {segment!r}",
        )
    return segment


@app.get("/tt/scan/segment-movers")
def tt_scan_segment_movers(
    request: Request,
) -> list[dict[str, str | float]]:
    """Return Segment Movers rows (#1692) — top gainers/losers by segment (chart)."""
    _require_auth(request)
    # TODO(gh-1692): wire to openbb_techtrade.engine.screener_router.segments.
    return [
        {"segment": "Technology", "change_pct": +2.14, "bucket": "gainer"},
        {"segment": "Communication Services", "change_pct": +1.62, "bucket": "gainer"},
        {"segment": "Consumer Discretionary", "change_pct": +0.88, "bucket": "gainer"},
        {"segment": "Health Care", "change_pct": -0.31, "bucket": "loser"},
        {"segment": "Utilities", "change_pct": -0.94, "bucket": "loser"},
        {"segment": "Real Estate", "change_pct": -1.55, "bucket": "loser"},
    ]


@app.get("/tt/scan/table")
def tt_scan_table(request: Request, segment: str = "") -> list[dict[str, str | float]]:
    """Return Scan Table rows (#1692) — filtered ticker scan results (table)."""
    _require_auth(request)
    if segment:
        _validate_segment(segment)
    # TODO(gh-1692): wire to openbb_techtrade.engine.scan.scan_segments.
    all_rows: list[dict[str, str | float]] = [
        {
            "symbol": "NVDA",
            "segment": "Technology",
            "score": 0.94,
            "signal": "BREAKOUT",
        },
        {"symbol": "AAPL", "segment": "Technology", "score": 0.82, "signal": "TREND"},
        {"symbol": "MSFT", "segment": "Technology", "score": 0.78, "signal": "TREND"},
        {
            "symbol": "META",
            "segment": "Communication Services",
            "score": 0.71,
            "signal": "TREND",
        },
        {
            "symbol": "AMZN",
            "segment": "Consumer Discretionary",
            "score": 0.66,
            "signal": "BASE",
        },
        {
            "symbol": "TSLA",
            "segment": "Consumer Discretionary",
            "score": 0.58,
            "signal": "RANGE",
        },
    ]
    if segment:
        return [r for r in all_rows if r["segment"] == segment]
    return all_rows


@app.get("/tt/scan/export")
def tt_scan_export(request: Request) -> str:
    """Return Export button markdown (#1692) — CSV export link for the scan (markdown)."""
    _require_auth(request)
    # TODO(gh-1692): wire to an actual export route that streams the scan
    # snapshot as a CSV attachment.
    return (
        "### Export Scan\n\n"
        "- [Download CSV](#) — snapshot of the current scan table\n"
        "- [Copy JSON](#) — machine-readable copy\n\n"
        "> Stub — the CSV link will resolve to a real streaming download once "
        "the export route lands in a follow-up cycle."
    )


# ---------------------------------------------------------------------------
# F12 Portfolio-management workflow (#1685-#1689) — spec at
# docs/superpowers/specs/2026-07-31-f12-portfolio-workflow-design.md
# ---------------------------------------------------------------------------


_BASKET_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _validate_basket_id(basket_id: str) -> str:
    """Reject XSS/malformed basket_id strings before echoing into responses."""
    if not _BASKET_ID_RE.match(basket_id):
        raise HTTPException(
            status_code=400,
            detail=f"basket_id must match [A-Za-z0-9_.-]{{1,64}}; got {basket_id!r}",
        )
    return basket_id


# Exception → fixed note allowlist (spec §3 T12.1 P0-3 fix). NEVER return
# str(exc) or repr(exc) — they can carry API keys in URL fragments.
_EXC_NOTE_MAP: dict[str, str] = {
    "TimeoutError": "timeout",
    "ConnectError": "network_unreachable",
    "HTTPStatusError": "http_error",
    "ReadTimeout": "read_timeout",
    "ConnectTimeout": "connect_timeout",
}


# In-memory cache for provider-health probe results. Keys: track name (A/B).
# Value: dict with 'tiers' (list[TierHealth]) and 'checked_at' timestamp.
# 60s TTL per spec §3 T12.1.
_PROVIDER_HEALTH_CACHE: dict[str, dict[str, object]] = {}
_PROVIDER_HEALTH_TTL_S: float = 60.0


def _cached_health(track: str) -> list | None:
    """Return cached tier list if still within TTL, else None."""
    entry = _PROVIDER_HEALTH_CACHE.get(track)
    if entry is None:
        return None
    checked_at = entry.get("checked_at", 0.0)
    if not isinstance(checked_at, float):
        return None
    if time.monotonic() - checked_at > _PROVIDER_HEALTH_TTL_S:
        return None
    tiers = entry.get("tiers")
    return tiers if isinstance(tiers, list) else None


def _store_health(track: str, tiers: list) -> None:
    _PROVIDER_HEALTH_CACHE[track] = {
        "tiers": tiers,
        "checked_at": time.monotonic(),
    }


async def _probe_track(track_tiers: tuple[str, ...], budget_s: float) -> list:
    """Probe every tier concurrently, bounded by ``budget_s`` wall-clock.

    Uses ``asyncio.gather(..., return_exceptions=True)`` per spec §3 T12.1
    P0-1: a single hanging tier CANNOT block the widget. Each individual
    probe already has its own 2s timeout (default in probe_tier); the
    outer budget is defence-in-depth.
    """
    coros = [probe_tier(t) for t in track_tiers]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True), timeout=budget_s
        )
    except asyncio.TimeoutError:
        # Overall budget exceeded — return unknown-marked entries for
        # every tier so the widget shows the cold-cache state loudly.
        return [
            TierHealth(name=t, status="unknown", latency_ms=0, note="timeout")
            for t in track_tiers
        ]

    healths: list = []
    for tier, res in zip(track_tiers, results):
        if isinstance(res, TierHealth):
            healths.append(res)
        else:
            # An exception escaped probe_tier (shouldn't — it catches
            # everything internally — but be defensive).
            healths.append(
                TierHealth(name=tier, status="down", latency_ms=0, note="unknown_error")
            )
    return healths


@app.get("/pi/health/providers")
async def provider_health(request: Request) -> str:
    """Return Provider Health strip markdown (#1685 + #1715).

    Spec §3 T12.1: non-blocking cold cache (returns 'unknown' immediately),
    60s TTL, exception notes from the allowlist only, never raw exception
    strings. #1715 adds the ``in-use: <tier>`` annotation per endpoint,
    driven by :func:`record_tier_used` calls from retrofitted endpoints.
    """
    _require_auth(request)

    # Cold cache: return a fully-``unknown`` strip immediately per spec
    # §T12.1 P0-1. The next request within the TTL window still hits
    # cold-cache until the background refresh completes — that's OK,
    # the widget will simply re-render as soon as data is present.
    def _unknown_strip(tiers: tuple[str, ...]) -> list:
        return [
            TierHealth(
                name=t, status="unknown", latency_ms=0, note="probe_failed_cold_cache"
            )
            for t in tiers
        ]

    track_a = _cached_health("A")
    track_b = _cached_health("B")
    if track_a is None or track_b is None:
        # Probe both tracks concurrently, bounded by an overall budget so
        # cold-cache never blocks the widget for long. This endpoint is an
        # async route, so we AWAIT the probes on the running event loop —
        # do NOT use asyncio.run() here (#1871): asyncio.run() raises
        # RuntimeError inside uvicorn's running loop *before* the gather
        # runs, which leaks the un-awaited _probe_track coroutines and
        # forces every call onto the cold-cache 'unknown' fallback.
        try:
            probed_a, probed_b = await asyncio.wait_for(
                asyncio.gather(
                    _probe_track(TRACK_A_DEFAULT, budget_s=0.4),
                    _probe_track(TRACK_B_DEFAULT, budget_s=0.4),
                ),
                timeout=0.5,
            )
            _store_health("A", probed_a)
            _store_health("B", probed_b)
            track_a = probed_a
            track_b = probed_b
        except asyncio.TimeoutError:
            # Overall budget exceeded — render the cold-cache 'unknown'
            # strip loudly and try again on the next call (within TTL).
            track_a = track_a or _unknown_strip(TRACK_A_DEFAULT)
            track_b = track_b or _unknown_strip(TRACK_B_DEFAULT)

    def _render_tier(h: object) -> str:
        badge = {"healthy": "●", "degraded": "⚠", "down": "✕", "unknown": "?"}.get(
            getattr(h, "status", "unknown"), "?"
        )
        name = getattr(h, "name", "?")
        ms = getattr(h, "latency_ms", 0)
        note = getattr(h, "note", None)
        suffix = f" ({note})" if note else ""
        return f"{badge} {name} ({ms}ms){suffix}"

    a_str = "  ".join(_render_tier(t) for t in track_a)
    b_str = "  ".join(_render_tier(t) for t in track_b)

    # Optional "currently in-use" summary — only rendered if any endpoint
    # has actually gone through a ChainedFetcher yet. Sorted for
    # determinism.
    in_use_lines = ""
    if _TIER_IN_USE:
        summary = "\n".join(
            f"- `{ep}` → **{tier}**" for ep, tier in sorted(_TIER_IN_USE.items())
        )
        in_use_lines = f"\n\n**Currently serving:**\n{summary}"

    return (
        "**Track A (paid):**  " + a_str + "  \n"
        "**Track B (free):**  " + b_str + in_use_lines + "\n\n"
        "> Provider-health strip (#1685) with 5-tier probing + tier-in-use "
        "ledger (#1715). 60s cache, 2s per-tier timeout, 500ms overall "
        "cold-cache budget."
    )


# Demo basket rows used by the stub. Explicitly separate from any real
# basket definition (which is deferred to #1714).
_DEMO_BASKET_CONSENSUS: list[dict[str, str | float | int]] = [
    {
        "symbol": "AAPL",
        "avg_target": 200.0,
        "buy": 24,
        "hold": 8,
        "sell": 1,
        "consensus": "BUY",
    },
    {
        "symbol": "MSFT",
        "avg_target": 465.0,
        "buy": 28,
        "hold": 4,
        "sell": 0,
        "consensus": "STRONG_BUY",
    },
    {
        "symbol": "GOOGL",
        "avg_target": 210.0,
        "buy": 22,
        "hold": 10,
        "sell": 2,
        "consensus": "BUY",
    },
    {
        "symbol": "NVDA",
        "avg_target": 175.0,
        "buy": 32,
        "hold": 3,
        "sell": 0,
        "consensus": "STRONG_BUY",
    },
    {
        "symbol": "META",
        "avg_target": 530.0,
        "buy": 26,
        "hold": 5,
        "sell": 1,
        "consensus": "BUY",
    },
]


@app.get("/pi/equity/basket-analyst-consensus")
def equity_basket_analyst_consensus(
    request: Request, basket_id: str = "demo"
) -> list[dict[str, str | float | int]]:
    """Return Basket Analyst Consensus rows (#1687) — aggregated across a basket.

    #1714: real basket resolution now lifted from the 422 gate. Behavior:

    - ``basket_id="demo"`` returns the baked-in demo rows (no auth-scoped
      resolution needed — public reference basket).
    - Any other basket_id is resolved via
      :func:`openbb_portfolio_intel.basket_resolver.resolve_basket` against
      the canonical positions store (MySQL per #1744) — BUT only when
      ``PI_ALLOW_CROSS_USER_BASKET=true`` is set. Otherwise HTTP 403
      (see #1748 security review + #1714's ownership follow-up).
    - Unknown basket_id (no snapshot) raises HTTP 404 loud, never
      silently returns [].

    Authorization posture (#1748 security review): today the bearer-token
    auth model does not carry a per-user identity. That means any caller
    with a valid token could otherwise view ANY user's positions by
    passing that user's id as basket_id (classic IDOR). Until per-user
    session auth lands, non-demo resolution is disabled by default; the
    single-user operator must opt in via the env flag. Cross-cutting
    identity work is tracked in the #1714 follow-up ownership ticket.
    """
    _require_auth(request)
    _validate_basket_id(basket_id)
    if basket_id == "demo":
        return _DEMO_BASKET_CONSENSUS

    if os.environ.get("PI_ALLOW_CROSS_USER_BASKET", "").strip().lower() != "true":
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "basket_authorization_required",
                "message": (
                    "Non-demo basket resolution requires "
                    "PI_ALLOW_CROSS_USER_BASKET=true (single-user operator "
                    "mode) until per-user session auth ships. See #1714 "
                    "ownership follow-up + #1748 security review."
                ),
                "basket_id": basket_id,
            },
        )

    try:
        positions = resolve_basket(basket_id)
    except BasketNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "detail": "basket_not_found",
                "basket_id": basket_id,
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:  # bad basket_id shape (defense-in-depth)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # For each resolved symbol emit a stub consensus row. Per-symbol
    # obb.equity.estimates.consensus() calls will replace this loop as
    # ChainedFetcher tier registrations land (#1715 Phase 2B).
    return [
        {
            "symbol": p.symbol,
            "avg_target": 0.0,
            "buy": 0,
            "hold": 0,
            "sell": 0,
            "consensus": "PENDING",
            "note": (
                f"weight={p.weight:.4f} — per-symbol consensus wiring is "
                "#1715 Phase 2B"
            ),
        }
        for p in positions
    ]


# ---------------------------------------------------------------------------
# Techtrade Position Workbench (#1696 T13.2) — stub-shaped
# ---------------------------------------------------------------------------


@app.get("/tt/position/signal-card")
def tt_position_signal_card(request: Request, symbol: str = "AAPL") -> str:
    """Return Signal Card markdown (#1696) — active signal for a symbol."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    # TODO(gh-1696): wire to openbb_techtrade.engine.signal_router.
    return (
        f"## {sym} — Active Signal\n\n"
        "- **Type:** BREAKOUT\n"
        "- **Direction:** LONG\n"
        "- **Confidence:** 0.87\n"
        "- **Trigger:** close above 20d high on 1.4x volume\n\n"
        "> Stub — real wiring calls openbb_techtrade.engine.signal_router."
    )


@app.get("/tt/position/plan-card")
def tt_position_plan_card(request: Request, symbol: str = "AAPL") -> str:
    """Return Plan Card markdown (#1696) — entry/stop/target for a trade."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    # TODO(gh-1696): wire to openbb_techtrade.engine.plan_router.
    return (
        f"## {sym} — Trading Plan\n\n"
        "- **Entry:** $173.50 (limit)\n"
        "- **Stop:** $168.20 (-3.1%)\n"
        "- **Target:** $189.00 (+8.9%)\n"
        "- **R:R:** 2.9x\n"
        "- **Sizing:** 2.0% of book risk\n\n"
        "> Stub — real wiring calls openbb_techtrade.engine.plan_router."
    )


@app.get("/tt/position/order-legs")
def tt_position_order_legs(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | int]]:
    """Return Order Legs rows (#1696) — proposed order legs for the plan."""
    _require_auth(request)
    sym = _validate_symbol(symbol)
    # TODO(gh-1696): wire to openbb_techtrade.execution.order_builder.
    return [
        {
            "leg_type": "ENTRY",
            "side": "BUY",
            "symbol": sym,
            "quantity": 100,
            "price": 173.50,
            "order_type": "LIMIT",
        },
        {
            "leg_type": "STOP",
            "side": "SELL",
            "symbol": sym,
            "quantity": 100,
            "price": 168.20,
            "order_type": "STOP_LIMIT",
        },
        {
            "leg_type": "TARGET",
            "side": "SELL",
            "symbol": sym,
            "quantity": 100,
            "price": 189.00,
            "order_type": "LIMIT",
        },
    ]


@app.get("/tt/position/simulate")
def tt_position_simulate(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float | int]]:
    """Return Simulate Result rows (#1696) — simulated P&L trajectory (chart raw)."""
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1696): wire to openbb_techtrade.engine.simulate_router.
    # Deterministic stub: monotonic-ish P&L climb with two drawdown wobbles.
    trajectory = [0, 15, 32, 28, 42, 55, 48, 63, 78, 71, 85, 100, 95, 108, 118]
    return [{"day": d, "pnl": p} for d, p in enumerate(trajectory)]


# ---------------------------------------------------------------------------
# Techtrade T13.3-T13.7: Validation + Tuning + Audit + Engine + Execute
# ---------------------------------------------------------------------------


@app.get("/tt/validation/verdict")
def tt_validation_verdict(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Validation Verdict rows (#1697) — PBO/DSR/OOS-Sharpe + verdict."""
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1697): wire to openbb_techtrade.engine.validate_router.
    return [
        {"metric": "PBO", "value": 0.18, "threshold": 0.30, "gate": "PASS"},
        {"metric": "DSR", "value": 1.47, "threshold": 1.00, "gate": "PASS"},
        {"metric": "OOS Sharpe", "value": 1.62, "threshold": 1.00, "gate": "PASS"},
        {"metric": "Verdict", "value": "PASS", "threshold": "PASS", "gate": "PASS"},
    ]


@app.get("/tt/tuning/report")
def tt_tuning_report(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Tuning Report rows (#1698) — tuneta proposal + validate gate.

    Persist behavior is stub-only. Real state persistence follow-up
    is filed under the broader techtrade epic.
    """
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1698): wire to openbb_techtrade.engine.tune_router (tuneta).
    return [
        {
            "param": "atr_period",
            "current": 14,
            "proposed": 20,
            "delta": +6,
            "validate_gate": "PASS",
        },
        {
            "param": "sma_fast",
            "current": 20,
            "proposed": 15,
            "delta": -5,
            "validate_gate": "PASS",
        },
        {
            "param": "sma_slow",
            "current": 50,
            "proposed": 55,
            "delta": +5,
            "validate_gate": "PASS",
        },
        {
            "param": "risk_pct",
            "current": 2.0,
            "proposed": 1.5,
            "delta": -0.5,
            "validate_gate": "FAIL",
        },
    ]


@app.get("/tt/audit/journal")
def tt_audit_journal(
    request: Request, symbol: str = "AAPL"
) -> list[dict[str, str | float]]:
    """Return Audit Journal rows (#1699) — replay vs forward P&L + deviation."""
    _require_auth(request)
    _validate_symbol(symbol)
    # TODO(gh-1699): wire to openbb_techtrade.reporting.audit.
    return [
        {
            "bar_date": "2026-07-25",
            "replay_pnl": 128.4,
            "forward_pnl": 130.2,
            "deviation_bps": 14.0,
        },
        {
            "bar_date": "2026-07-26",
            "replay_pnl": 132.1,
            "forward_pnl": 131.7,
            "deviation_bps": -3.0,
        },
        {
            "bar_date": "2026-07-27",
            "replay_pnl": 135.8,
            "forward_pnl": 137.9,
            "deviation_bps": 15.5,
        },
        {
            "bar_date": "2026-07-28",
            "replay_pnl": 141.3,
            "forward_pnl": 142.0,
            "deviation_bps": 5.0,
        },
        {
            "bar_date": "2026-07-29",
            "replay_pnl": 144.9,
            "forward_pnl": 138.7,
            "deviation_bps": -42.8,
        },
    ]


@app.get("/tt/engine/status")
def tt_engine_status(request: Request) -> str:
    """Return Engine Status markdown (#1700) — scheduler/signal/execution state."""
    _require_auth(request)
    # TODO(gh-1700): wire to openbb_techtrade.engine.status.
    return (
        "## Techtrade Engine Status\n\n"
        "- **Scheduler:** RUNNING (next tick in 47s)\n"
        "- **Signal engine:** READY (last signal: NVDA BREAKOUT at 09:32:14)\n"
        "- **Execution engine:** IDLE (verdict gate: PASS)\n"
        "- **Data feed:** LIVE (fmp_cached hit-rate 98.2%)\n\n"
        "> Stub — real wiring calls openbb_techtrade.engine.status."
    )


@app.get("/tt/execute/bridge")
def tt_execute_bridge(request: Request, verdict: str = "PASS") -> str:
    """Return Execute Bridge markdown (#1700 T5, wired to real endpoints per #1719).

    Now points readers at the actual write-batch + paper-status endpoints
    that landed in P4 (#1768). The gate semantics remain — verdict=FAIL
    still blocks. The verdict=PASS branch documents the real double-gate
    (env var + explicit confirm) so operators know what's needed to
    trigger a real write.
    """
    _require_auth(request)
    if verdict not in {"PASS", "FAIL"}:
        raise HTTPException(
            status_code=400,
            detail=f"verdict must be PASS or FAIL; got {verdict!r}",
        )
    execute_allowed = (
        os.environ.get("PI_ALLOW_T5_EXECUTE", "").strip().lower() == "true"
    )
    if verdict == "FAIL":
        return (
            "## Execute Bridge: BLOCKED\n\n"
            "Verdict gate: **FAIL** — execution blocked.\n\n"
            "> Re-run T4 validation; only a PASS verdict opens the "
            "write-batch path."
        )
    ready_signal = (
        "🟢 Real writes ENABLED (`PI_ALLOW_T5_EXECUTE=true`)."
        if execute_allowed
        else "🟡 Real writes DISABLED — set `PI_ALLOW_T5_EXECUTE=true` " "to enable."
    )
    return (
        "## Execute Bridge: READY\n\n"
        f"Verdict gate: **PASS** — bridge ready to submit. {ready_signal}\n\n"
        "### Next steps\n\n"
        "1. **Write batch** — `POST /tt/execute/write-batch"
        "?verdict=PASS&confirm=yes` (triple-gate: env + verdict + confirm).\n"
        "2. **File orders manually** at Fidelity using the produced XLSX "
        "as your cheat sheet.\n"
        "3. **Record fills** into the paper engine via a widget action "
        "or bulk-import a Fidelity Activity CSV (P5).\n\n"
        "> See `docs/superpowers/specs/2026-08-03-t5-e2e-test-guide.md` "
        "for the E2E test guide."
    )


@app.get("/tt/execute/paper-status/markdown")
def tt_execute_paper_status_markdown(request: Request) -> str:
    """Render the paper engine snapshot as a markdown widget (#1777).

    Companion to /tt/execute/paper-status (JSON). This endpoint returns a
    markdown-formatted view suitable for the ``tt_execute_paper_status``
    markdown widget — no JS required.

    Fresh install (no paper.db) returns a friendly "nothing yet" message
    rather than an error — same discipline as the JSON version.
    """
    _require_auth(request)

    # pylint: disable=import-outside-toplevel
    try:
        from pathlib import Path  # noqa: PLC0415

        from openbb_techtrade.execution.paper_engine import (  # noqa: PLC0415
            OrderStatus,
            SqlitePaperEngine,
        )
    except ImportError:
        return (
            "## Paper Trading Engine\n\n"
            "*T5 dependencies not installed. Install `openbb_techtrade` "
            "editable to see paper engine state.*"
        )

    db_path = Path(
        os.environ.get(
            "PI_PAPER_DB",
            str(Path.home() / ".portfolio_intel" / "paper.db"),
        )
    )
    if not db_path.exists():
        return (
            "## Paper Trading Engine\n\n"
            "**No batches submitted yet.**\n\n"
            "Submit a batch via the Execute Bridge widget "
            "(`POST /tt/execute/write-batch`) to see cash, positions, "
            "and P&L here."
        )

    engine = SqlitePaperEngine(db_path)
    try:
        acct = engine.get_account()
        positions = engine.get_positions()
        pending = engine.get_orders(status=OrderStatus.PENDING)
        filled = engine.get_orders(status=OrderStatus.FILLED)

        # Build the markdown body.
        lines: list[str] = [
            "## Paper Trading Engine",
            "",
            f"**Account** `{acct.account_id}`",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Starting cash | ${acct.starting_cash} |",
            f"| Cash | ${acct.cash} |",
            f"| Realized P&L | ${acct.realized_pl} |",
            "",
            f"**Positions** ({len(positions)})",
            "",
        ]
        if positions:
            lines.append("| Symbol | Qty | Avg cost | Realized P&L |")
            lines.append("| --- | ---: | ---: | ---: |")
            for p in positions:
                lines.append(
                    f"| {p.symbol} | {p.quantity} | ${p.avg_cost} | ${p.realized_pl} |"
                )
        else:
            lines.append("*No open positions.*")
        lines.extend(
            [
                "",
                f"**Orders**: {len(pending)} PENDING, {len(filled)} FILLED",
                "",
                "> Read-only view. Use the Execute Bridge widget to write "
                "new batches; record fills via the widget action or a "
                "Fidelity Activity CSV bulk import (P5).",
            ]
        )
        return "\n".join(lines)
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# T5 P4 real-execute endpoints (#1768). Wires the widget to the paper
# trading engine + PaperOrderSink shipped in P1/P2/P3.a.
# ---------------------------------------------------------------------------


# Env gate for the whole P4 surface. Off by default in dev, must be
# explicitly opted-in — matches the #1748 auth pattern for basket
# resolution.
_ENV_ALLOW_EXECUTE = "PI_ALLOW_T5_EXECUTE"


def _t5_execute_allowed() -> bool:
    """Return True iff PI_ALLOW_T5_EXECUTE=true is set in the environment."""
    return os.environ.get(_ENV_ALLOW_EXECUTE, "").strip().lower() == "true"


@app.post("/tt/execute/write-batch")
def tt_execute_write_batch(  # pylint: disable=too-many-return-statements
    request: Request,
    verdict: str = "PASS",
    confirm: str = "",
    plan_id: str = "",
) -> dict:
    """T5 P4 — write a demo batch to disk + submit to paper engine.

    Double-gate: verdict must be PASS AND the caller must send
    ``confirm=yes`` (an explicit-confirm string, not a boolean flag).
    The confirm string is deliberately unusual so a stray reload of a
    misconfigured page can't accidentally trigger a write.

    Third gate: ``PI_ALLOW_T5_EXECUTE=true`` env var. Off by default so
    dev deployments don't accidentally spawn paper.db files. Matches
    the auth-gate pattern from #1748.

    Returns a dict with:
      - ``batch_sha`` — 8-char short SHA
      - ``csv_path`` / ``xlsx_path`` — absolute paths of the written files
      - ``order_ids`` — list of PENDING orders now in the paper engine
      - ``next_step`` — a human-legible next-action hint

    The batch content is a fixed demo (3-symbol basket) for this phase;
    real integration with T4's plan output is a follow-up.
    """
    _require_auth(request)

    if not _t5_execute_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "t5_execute_not_allowed: set PI_ALLOW_T5_EXECUTE=true "
                "to enable the real T5 write path. Default OFF to prevent "
                "accidental disk writes from dev deployments."
            ),
        )
    if verdict != "PASS":
        raise HTTPException(
            status_code=400,
            detail=(
                f"verdict_gate_blocked: verdict={verdict!r}; write-batch "
                "requires verdict=PASS. Rerun the plan validation first."
            ),
        )
    if confirm != "yes":
        raise HTTPException(
            status_code=400,
            detail=(
                "explicit_confirm_required: pass confirm=yes to acknowledge "
                "this write will persist to disk + the paper trading engine. "
                "A stray reload without confirm=yes is intentionally rejected."
            ),
        )

    # Deferred imports so the widget backend loads cleanly even when
    # techtrade isn't installed (matches basket_resolver pattern from
    # #1714).
    # pylint: disable=import-outside-toplevel
    try:
        import tempfile  # noqa: PLC0415
        from decimal import Decimal  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from openbb_techtrade.execution.order_sink import (  # noqa: PLC0415
            OrderBatch,
            OrderTicket,
            PaperOrderSink,
        )
        from openbb_techtrade.execution.paper_engine import (  # noqa: PLC0415
            SqlitePaperEngine,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"t5_dependencies_missing: {exc}. Install openbb_techtrade "
                "editable to enable the T5 execute endpoints."
            ),
        ) from exc

    # Demo batch. Real batch composition from a T4 plan is a follow-up.
    batch = OrderBatch(
        tickets=(
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("10"),
                order_type="Limit",
                limit_price=Decimal("400.00"),
            ),
            OrderTicket(
                symbol="AAPL",
                action="Buy",
                quantity=Decimal("25"),
                order_type="Limit",
                limit_price=Decimal("180.00"),
            ),
            OrderTicket(
                symbol="NVDA",
                action="Buy",
                quantity=Decimal("5"),
                order_type="Limit",
                limit_price=Decimal("130.00"),
            ),
        ),
        plan_id=plan_id or "widget-demo",
        verdict_gate_pass=True,
    )

    out_dir = Path(
        os.environ.get(
            "PI_T5_EXECUTE_OUTPUT_DIR",
            str(Path(tempfile.gettempdir()) / "pi_t5_execute"),
        )
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    sink = PaperOrderSink(out_dir)
    art = sink.write_batch(batch)

    # Submit to the paper engine.
    db_path = Path(
        os.environ.get(
            "PI_PAPER_DB",
            str(Path.home() / ".portfolio_intel" / "paper.db"),
        )
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = SqlitePaperEngine(db_path)
    order_ids = engine.submit_batch(batch, plan_id=batch.plan_id)
    engine.close()

    return {
        "batch_sha": batch.sha_short(),
        "csv_path": str(art.csv_path),
        "xlsx_path": str(art.xlsx_path),
        "order_ids": order_ids,
        "next_step": (
            "Review the XLSX workbook, then file orders manually at "
            "Fidelity. Record fills via /tt/execute/record-fill or bulk-"
            "import a Fidelity Activity CSV via the P5 module."
        ),
    }


@app.get("/tt/execute/paper-status")
def tt_execute_paper_status(request: Request) -> dict:
    """T5 P4 — read the paper trading engine's current state.

    No writes. No env-gate needed (read-only endpoints are safe even
    when execute is disabled). Returns:

    - ``account`` — cash, realized_pl, starting_cash
    - ``positions`` — current positions (symbol, qty, avg_cost)
    - ``pending_order_count`` — how many PENDING orders await fills
    - ``filled_order_count`` — how many orders have been FILLED so far

    Returns an empty state (no positions, no orders) if the paper DB
    doesn't exist yet — that's the natural "no batches submitted yet"
    state, not an error.
    """
    _require_auth(request)

    # pylint: disable=import-outside-toplevel
    try:
        from pathlib import Path  # noqa: PLC0415

        from openbb_techtrade.execution.paper_engine import (  # noqa: PLC0415
            OrderStatus,
            SqlitePaperEngine,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"t5_dependencies_missing: {exc}.",
        ) from exc

    db_path = Path(
        os.environ.get(
            "PI_PAPER_DB",
            str(Path.home() / ".portfolio_intel" / "paper.db"),
        )
    )
    # If the DB doesn't exist, return an empty snapshot (fresh install).
    if not db_path.exists():
        return {
            "account": None,
            "positions": [],
            "pending_order_count": 0,
            "filled_order_count": 0,
            "note": "No paper.db yet — submit a batch via /tt/execute/write-batch",
        }

    engine = SqlitePaperEngine(db_path)
    try:
        acct = engine.get_account()
        positions = engine.get_positions()
        pending = len(engine.get_orders(status=OrderStatus.PENDING))
        filled = len(engine.get_orders(status=OrderStatus.FILLED))
        return {
            "account": {
                "account_id": acct.account_id,
                "cash": str(acct.cash),
                "realized_pl": str(acct.realized_pl),
                "starting_cash": str(acct.starting_cash),
            },
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": str(p.quantity),
                    "avg_cost": str(p.avg_cost),
                    "realized_pl": str(p.realized_pl),
                }
                for p in positions
            ],
            "pending_order_count": pending,
            "filled_order_count": filled,
        }
    finally:
        engine.close()
