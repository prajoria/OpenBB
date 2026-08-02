"""Alert-rule engine — 6 trigger types (#571).

PRD 17 Phase 1. Pure-function rule evaluator over the composed
substrate (holdings + events + smart-money + sentiment + paper-trading
fills). Emits :class:`Alert` records that the router surfaces to the
in-widget alert panel.

## Six triggers

Every trigger takes a snapshot of the current substrate + a lookback
horizon and returns zero or more :class:`Alert` records. Triggers are
independent — a caller can enable / disable each without cross-effects.

1. ``earnings_upcoming`` — earnings within N days for any held symbol.
2. ``ex_div_upcoming`` — ex-dividend date within N days for any held.
3. ``insider_open_market_buy`` — SEC Form 4 open-market buy with
   dollar value ≥ threshold (default $100K) for a held symbol.
4. ``form_8k_for_held`` — 8-K filing for any held symbol within
   lookback.
5. ``analyst_downgrade_top10`` — recent downgrade for a top-10
   holding (ranked by portfolio weight).
6. ``paper_trading_event`` — order fill / rejection from the paper
   ledger since ``since_timestamp``.

## Design notes

- **Deterministic ordering**: :func:`evaluate_all` returns alerts
  sorted by (severity DESC, when ASC, symbol ASC) so UI ordering is
  stable across calls.
- **Idempotency**: :class:`Alert` carries a stable ``key`` that
  callers can use to dedupe against a "seen" set — same alert on
  two consecutive polls produces the same key.
- **No I/O**: caller pulls the substrate; this module reduces it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Trigger identity + Alert record
# ---------------------------------------------------------------------------


class TriggerType(str, Enum):
    """The six trigger types wired for PRD 17 Phase 1."""

    EARNINGS_UPCOMING = "earnings_upcoming"
    EX_DIV_UPCOMING = "ex_div_upcoming"
    INSIDER_OPEN_MARKET_BUY = "insider_open_market_buy"
    FORM_8K_FOR_HELD = "form_8k_for_held"
    ANALYST_DOWNGRADE_TOP10 = "analyst_downgrade_top10"
    PAPER_TRADING_EVENT = "paper_trading_event"


class Severity(str, Enum):
    """Ranked severity — sort order for the alert panel."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 3,
    Severity.WARNING: 2,
    Severity.INFO: 1,
}


@dataclass(frozen=True)
class Alert:
    """Single alert record.

    ``key`` is a deterministic idempotency handle: same trigger, same
    symbol, same anchor-date/id → same key across polls. Callers dedupe
    on ``key`` between renders.

    ``when`` is the alert's anchor timestamp. For calendar triggers,
    it's the event date; for paper-trading it's the fill's
    ``submitted_at``; for insider it's the transaction date. Used as
    the tiebreaker for sort order.

    ``payload`` is trigger-specific detail the UI can render (dollar
    value, price target, etc.). Never contains the raw provider row.
    """

    trigger: TriggerType
    severity: Severity
    symbol: str
    when: datetime
    message: str
    key: str
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Substrate inputs — minimal dataclasses so this module does zero I/O.
# Callers construct these from provider payloads.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldingRef:
    """Portfolio holding — just what the alert engine needs."""

    symbol: str
    weight: Decimal


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    date: date


@dataclass(frozen=True)
class DividendEvent:
    symbol: str
    ex_date: date


@dataclass(frozen=True)
class InsiderTrade:
    symbol: str
    transaction_date: date
    transaction_type: str  # "P" = open-market buy, "S" = open-market sell, etc.
    value_usd: Decimal  # signed dollar value of transaction


@dataclass(frozen=True)
class FormFiling:
    symbol: str
    form_type: str  # "8-K", "10-Q", etc.
    filed_at: datetime


@dataclass(frozen=True)
class AnalystAction:
    symbol: str
    action_date: date
    action: str  # "upgrade" | "downgrade" | "initiate"
    from_rating: str | None = None
    to_rating: str | None = None


@dataclass(frozen=True)
class PaperTradingEvent:
    """Adapter for paper-trading events we want to surface as alerts.

    Deliberately a thin projection of the paper ledger — the engine
    does not depend on the paper-trading module's Order/Fill types
    directly so the two subsystems stay independently testable.
    """

    symbol: str
    when: datetime
    status: str  # "FILLED" | "REJECTED" | "PARTIAL"
    reason: str = ""  # for REJECTED
    quantity: Decimal | None = None
    fill_price: Decimal | None = None


# ---------------------------------------------------------------------------
# Per-trigger evaluators
# ---------------------------------------------------------------------------


DEFAULT_UPCOMING_DAYS = 5
DEFAULT_INSIDER_BUY_USD = Decimal("100000")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_TOP_N = 10


def _held_symbols(holdings: Iterable[HoldingRef]) -> set[str]:
    return {h.symbol for h in holdings}


def _top_n_symbols(holdings: Iterable[HoldingRef], n: int) -> set[str]:
    return {
        h.symbol for h in sorted(holdings, key=lambda h: h.weight, reverse=True)[:n]
    }


def evaluate_earnings_upcoming(
    holdings: Iterable[HoldingRef],
    events: Iterable[EarningsEvent],
    *,
    today: date,
    horizon_days: int = DEFAULT_UPCOMING_DAYS,
) -> list[Alert]:
    """Trigger #1: earnings within ``horizon_days`` for any held symbol."""
    held = _held_symbols(holdings)
    cutoff = today + timedelta(days=horizon_days)
    out: list[Alert] = []
    for e in events:
        if e.symbol not in held or e.date < today or e.date > cutoff:
            continue
        days = (e.date - today).days
        sev = Severity.WARNING if days <= 2 else Severity.INFO
        out.append(
            Alert(
                trigger=TriggerType.EARNINGS_UPCOMING,
                severity=sev,
                symbol=e.symbol,
                when=datetime.combine(e.date, datetime.min.time()),
                message=f"{e.symbol} earnings in {days}d",
                key=f"earnings:{e.symbol}:{e.date.isoformat()}",
                payload={"date": e.date.isoformat(), "days_until": days},
            )
        )
    return out


def evaluate_ex_div_upcoming(
    holdings: Iterable[HoldingRef],
    events: Iterable[DividendEvent],
    *,
    today: date,
    horizon_days: int = DEFAULT_UPCOMING_DAYS,
) -> list[Alert]:
    """Trigger #2: ex-dividend within ``horizon_days`` for any held symbol."""
    held = _held_symbols(holdings)
    cutoff = today + timedelta(days=horizon_days)
    out: list[Alert] = []
    for e in events:
        if e.symbol not in held or e.ex_date < today or e.ex_date > cutoff:
            continue
        days = (e.ex_date - today).days
        out.append(
            Alert(
                trigger=TriggerType.EX_DIV_UPCOMING,
                severity=Severity.INFO,
                symbol=e.symbol,
                when=datetime.combine(e.ex_date, datetime.min.time()),
                message=f"{e.symbol} ex-dividend in {days}d",
                key=f"exdiv:{e.symbol}:{e.ex_date.isoformat()}",
                payload={"ex_date": e.ex_date.isoformat(), "days_until": days},
            )
        )
    return out


def evaluate_insider_open_market_buy(
    holdings: Iterable[HoldingRef],
    trades: Iterable[InsiderTrade],
    *,
    since: date,
    min_value_usd: Decimal = DEFAULT_INSIDER_BUY_USD,
) -> list[Alert]:
    """Trigger #3: SEC Form 4 open-market buy ≥ threshold for a held symbol.

    Only ``transaction_type == "P"`` (open-market purchase). Sells and
    option-related codes are ignored — the rule is "insider signaling
    conviction via cash," which is the buy-only interpretation used by
    the sentiment community.
    """
    held = _held_symbols(holdings)
    out: list[Alert] = []
    for t in trades:
        if t.symbol not in held:
            continue
        if t.transaction_date < since:
            continue
        if t.transaction_type != "P":
            continue
        if t.value_usd < min_value_usd:
            continue
        out.append(
            Alert(
                trigger=TriggerType.INSIDER_OPEN_MARKET_BUY,
                severity=Severity.WARNING,
                symbol=t.symbol,
                when=datetime.combine(t.transaction_date, datetime.min.time()),
                message=(
                    f"Insider open-market buy: {t.symbol} " f"${t.value_usd:,.0f}"
                ),
                key=(
                    f"insider:{t.symbol}:{t.transaction_date.isoformat()}"
                    f":{t.value_usd}"
                ),
                payload={
                    "value_usd": str(t.value_usd),
                    "transaction_date": t.transaction_date.isoformat(),
                },
            )
        )
    return out


def evaluate_form_8k_for_held(
    holdings: Iterable[HoldingRef],
    filings: Iterable[FormFiling],
    *,
    since: datetime,
) -> list[Alert]:
    """Trigger #4: 8-K filing for a held symbol since ``since``."""
    held = _held_symbols(holdings)
    out: list[Alert] = []
    for f in filings:
        if f.symbol not in held:
            continue
        if f.form_type != "8-K":
            continue
        if f.filed_at < since:
            continue
        out.append(
            Alert(
                trigger=TriggerType.FORM_8K_FOR_HELD,
                severity=Severity.WARNING,
                symbol=f.symbol,
                when=f.filed_at,
                message=f"{f.symbol} filed 8-K",
                key=f"8k:{f.symbol}:{f.filed_at.isoformat()}",
                payload={"filed_at": f.filed_at.isoformat()},
            )
        )
    return out


def evaluate_analyst_downgrade_top10(
    holdings: Iterable[HoldingRef],
    actions: Iterable[AnalystAction],
    *,
    since: date,
    top_n: int = DEFAULT_TOP_N,
) -> list[Alert]:
    """Trigger #5: recent downgrade for a top-N holding.

    Note the top-N calculation is over the SUPPLIED holdings — the
    engine does not re-rank. The caller is expected to pass a fully
    computed weight per holding (weights are what the ranking uses).
    """
    top = _top_n_symbols(holdings, top_n)
    out: list[Alert] = []
    for a in actions:
        if a.symbol not in top:
            continue
        if a.action_date < since:
            continue
        if a.action != "downgrade":
            continue
        out.append(
            Alert(
                trigger=TriggerType.ANALYST_DOWNGRADE_TOP10,
                severity=Severity.CRITICAL,
                symbol=a.symbol,
                when=datetime.combine(a.action_date, datetime.min.time()),
                message=(
                    f"{a.symbol} (top-{top_n} holding) downgraded "
                    f"{a.from_rating or '?'} → {a.to_rating or '?'}"
                ),
                key=f"downgrade:{a.symbol}:{a.action_date.isoformat()}",
                payload={
                    "action_date": a.action_date.isoformat(),
                    "from_rating": a.from_rating,
                    "to_rating": a.to_rating,
                },
            )
        )
    return out


def evaluate_paper_trading_events(
    events: Iterable[PaperTradingEvent],
    *,
    since: datetime,
) -> list[Alert]:
    """Trigger #6: paper-trading fill / rejection since ``since``.

    Not scoped by ``holdings``: a paper order is always relevant to
    the user by definition. Rejections are WARNING (usually the user
    tried something invalid); fills are INFO.
    """
    out: list[Alert] = []
    for e in events:
        if e.when < since:
            continue
        sev = Severity.WARNING if e.status == "REJECTED" else Severity.INFO
        if e.status == "REJECTED":
            msg = f"Order rejected for {e.symbol}: {e.reason or 'no reason given'}"
        elif e.status == "FILLED":
            qty = f" qty={e.quantity}" if e.quantity is not None else ""
            px = f" @ {e.fill_price}" if e.fill_price is not None else ""
            msg = f"Order filled: {e.symbol}{qty}{px}"
        else:
            msg = f"Order {e.status.lower()} for {e.symbol}"
        out.append(
            Alert(
                trigger=TriggerType.PAPER_TRADING_EVENT,
                severity=sev,
                symbol=e.symbol,
                when=e.when,
                message=msg,
                key=f"paper:{e.symbol}:{e.when.isoformat()}:{e.status}",
                payload={"status": e.status, "reason": e.reason},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertContext:
    """Full substrate the engine reads.

    Any field left at its default empty tuple simply disables the
    corresponding trigger — no error, no warning.
    """

    holdings: tuple[HoldingRef, ...] = ()
    earnings: tuple[EarningsEvent, ...] = ()
    dividends: tuple[DividendEvent, ...] = ()
    insider_trades: tuple[InsiderTrade, ...] = ()
    filings: tuple[FormFiling, ...] = ()
    analyst_actions: tuple[AnalystAction, ...] = ()
    paper_events: tuple[PaperTradingEvent, ...] = ()


@dataclass(frozen=True)
class AlertConfig:
    """Per-trigger enable + threshold config."""

    enabled: frozenset[TriggerType] = frozenset(TriggerType)
    upcoming_days: int = DEFAULT_UPCOMING_DAYS
    insider_buy_min_usd: Decimal = DEFAULT_INSIDER_BUY_USD
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    top_n: int = DEFAULT_TOP_N


def evaluate_all(
    ctx: AlertContext,
    *,
    now: datetime,
    config: AlertConfig | None = None,
) -> list[Alert]:
    """Run every enabled trigger and return the merged, sorted alert list.

    Sort order: severity DESC, when ASC, symbol ASC. Stable across
    calls given equal input.
    """
    cfg = config or AlertConfig()
    today = now.date()
    since_date = today - timedelta(days=cfg.lookback_days)
    since_dt = now - timedelta(days=cfg.lookback_days)

    out: list[Alert] = []

    if TriggerType.EARNINGS_UPCOMING in cfg.enabled:
        out += evaluate_earnings_upcoming(
            ctx.holdings, ctx.earnings, today=today, horizon_days=cfg.upcoming_days
        )
    if TriggerType.EX_DIV_UPCOMING in cfg.enabled:
        out += evaluate_ex_div_upcoming(
            ctx.holdings, ctx.dividends, today=today, horizon_days=cfg.upcoming_days
        )
    if TriggerType.INSIDER_OPEN_MARKET_BUY in cfg.enabled:
        out += evaluate_insider_open_market_buy(
            ctx.holdings,
            ctx.insider_trades,
            since=since_date,
            min_value_usd=cfg.insider_buy_min_usd,
        )
    if TriggerType.FORM_8K_FOR_HELD in cfg.enabled:
        out += evaluate_form_8k_for_held(ctx.holdings, ctx.filings, since=since_dt)
    if TriggerType.ANALYST_DOWNGRADE_TOP10 in cfg.enabled:
        out += evaluate_analyst_downgrade_top10(
            ctx.holdings, ctx.analyst_actions, since=since_date, top_n=cfg.top_n
        )
    if TriggerType.PAPER_TRADING_EVENT in cfg.enabled:
        out += evaluate_paper_trading_events(ctx.paper_events, since=since_dt)

    out.sort(key=lambda a: (-_SEVERITY_RANK[a.severity], a.when, a.symbol, a.key))
    return out


__all__ = [
    "DEFAULT_INSIDER_BUY_USD",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_TOP_N",
    "DEFAULT_UPCOMING_DAYS",
    "Alert",
    "AlertConfig",
    "AlertContext",
    "AnalystAction",
    "DividendEvent",
    "EarningsEvent",
    "FormFiling",
    "HoldingRef",
    "InsiderTrade",
    "PaperTradingEvent",
    "Severity",
    "TriggerType",
    "evaluate_all",
    "evaluate_analyst_downgrade_top10",
    "evaluate_earnings_upcoming",
    "evaluate_ex_div_upcoming",
    "evaluate_form_8k_for_held",
    "evaluate_insider_open_market_buy",
    "evaluate_paper_trading_events",
]
