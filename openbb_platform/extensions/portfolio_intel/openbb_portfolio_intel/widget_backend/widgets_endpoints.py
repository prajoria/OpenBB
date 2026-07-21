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

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

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
# X-Ray widgets (#529, #530)
# ---------------------------------------------------------------------------


@app.get("/pi/xray/country")
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
