"""Paper-trading alert wiring (#574).

One command:
- ``obb.portfolio_intel.paper.alerts(account_id, since_seconds, ...)``
  Reads paper-trading ledger events since ``since_seconds`` ago, maps
  fills / rejections / low-buying-power / GTC-expiring-soon into
  :class:`analytics.alerts.PaperTradingEvent` records, feeds them
  through the alert engine, returns the resulting alerts.

Composes:
- ``paper.InMemoryLedgerStore`` (or another :class:`paper.LedgerStore`)
  for the event source.
- ``analytics.alerts.evaluate_paper_trading_events`` for the mapper.

## Authorization model (post-security-review of PR #950)

``user_id`` MUST come from the authenticated session, NOT from the
request body — otherwise any caller could enumerate ``user_id`` values
and read other people's paper accounts (classic IDOR).

This module resolves the principal via :func:`_resolve_principal`, a
seam that returns the current OpenBB user context. The seam raises
``PermissionError`` when no session is authenticated; tests inject a
stub principal that returns a fixed ``user_id``.

Before every store call we call ``_verify_account_ownership`` which
looks up the account and rejects when its ``user_id`` does not match
the resolved principal. On rejection the route returns an alert-free
response with an ``ACL denied`` warning — no cash balance, no ledger
row, no metadata leaks about whether the account actually exists.
"""

# pylint: disable=unused-argument
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_portfolio_intel.analytics.alerts import (
    Alert,
    PaperTradingEvent,
    Severity,
    TriggerType,
    evaluate_paper_trading_events,
)
from openbb_portfolio_intel.models import PaperAlertItem, PaperAlertsResult

logger = logging.getLogger(__name__)

router = Router(
    prefix="/paper",
    description=(
        "Paper-trading alert stream — fills, rejections, low buying-power, "
        "GTC-expiring-soon. Feeds the same in-widget alert panel as market "
        "events."
    ),
)


# ---------------------------------------------------------------------------
# Auth seams
# ---------------------------------------------------------------------------


def _resolve_principal() -> str:
    """Return the authenticated ``user_id`` from the current session.

    Production wiring will read from ``openbb_core.app.service.user_service``
    — deferred to the platform-auth integration follow-up. Until then this
    raises so no route can be called unauthenticated, and tests override
    the seam explicitly.
    """
    raise PermissionError(
        "no authenticated principal — set _resolve_principal in test / wire "
        "platform user service in production"
    )


def _verify_account_ownership(
    account_store, *, principal: str, account_id: str
) -> bool:
    """Return True iff the account exists and belongs to ``principal``.

    Returns False on any mismatch or fetch error — never raises. The
    caller decides how to fail closed (typically returning an empty
    alert list with an ``ACL denied`` warning).
    """
    try:
        account = account_store.get(user_id=principal, account_id=account_id)
    except Exception:  # noqa: BLE001
        return False
    if account is None:
        return False
    return getattr(account, "user_id", None) == principal


# ---------------------------------------------------------------------------
# Seams for dependency injection (real stores injected in tests)
# ---------------------------------------------------------------------------


def _default_ledger_store():
    """Lazily import and return the shared in-memory ledger store.

    In production this returns a process-local :class:`InMemoryLedgerStore`
    singleton. Tests replace this seam with a purpose-built store.
    """
    from openbb_portfolio_intel.paper import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        InMemoryLedgerStore,
    )

    global _LEDGER_SINGLETON  # noqa: PLW0603
    if _LEDGER_SINGLETON is None:
        _LEDGER_SINGLETON = InMemoryLedgerStore()
    return _LEDGER_SINGLETON


def _default_account_store():
    from openbb_portfolio_intel.paper import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        InMemoryAccountStore,
    )

    global _ACCOUNT_SINGLETON  # noqa: PLW0603
    if _ACCOUNT_SINGLETON is None:
        _ACCOUNT_SINGLETON = InMemoryAccountStore()
    return _ACCOUNT_SINGLETON


_LEDGER_SINGLETON = None
_ACCOUNT_SINGLETON = None


# ---------------------------------------------------------------------------
# Mappers — ledger entry -> alert event
# ---------------------------------------------------------------------------


def _ledger_to_paper_events(entries) -> list[PaperTradingEvent]:
    """Map :class:`paper.LedgerEntry` iterables to :class:`PaperTradingEvent`.

    Only ``TRADE`` entries produce events. Positive quantity => FILLED
    buy; negative quantity => FILLED sell. Ledger has no REJECTED entry
    type by design (rejections don't hit the ledger), so those must be
    surfaced by the calling context via the ``recent_rejections`` param.
    """
    events: list[PaperTradingEvent] = []
    for entry in entries:
        entry_type = getattr(entry, "entry_type", None)
        # Support both enum and string types defensively.
        if str(entry_type).endswith("TRADE") or str(entry_type) == "trade":
            symbol = getattr(entry, "symbol", None)
            qty = getattr(entry, "quantity", None)
            price = getattr(entry, "price", None)
            when = getattr(entry, "at", None) or getattr(entry, "timestamp", None)
            if symbol is None or when is None:
                continue
            events.append(
                PaperTradingEvent(
                    symbol=str(symbol),
                    when=(
                        when
                        if isinstance(when, datetime)
                        else datetime.now(tz=timezone.utc)
                    ),
                    status="FILLED",
                    quantity=Decimal(str(qty)) if qty is not None else None,
                    fill_price=Decimal(str(price)) if price is not None else None,
                )
            )
    return events


# ---------------------------------------------------------------------------
# Policy triggers unique to paper trading
# ---------------------------------------------------------------------------


def _low_buying_power_alerts(
    account,
    now: datetime,
    threshold_pct: float = 0.10,
) -> list[Alert]:
    """Fire one alert when buying-power / equity < threshold.

    We approximate equity as ``cash_balance`` — full equity requires
    marking positions to market which is out of scope for this route.
    Downstream #928-class work will refine to actual equity.
    """
    if account is None:
        return []
    cash = Decimal(str(getattr(account, "cash_balance", 0) or 0))
    starting = Decimal(str(getattr(account, "starting_cash", None) or cash or 1))
    if starting <= 0:
        return []
    ratio = float(cash / starting) if starting > 0 else 0.0
    if ratio >= threshold_pct:
        return []
    return [
        Alert(
            trigger=TriggerType.PAPER_TRADING_EVENT,
            severity=Severity.WARNING,
            symbol="*",  # portfolio-level, not per-symbol
            when=now,
            message=(
                f"Buying power low: cash={float(cash):.2f} "
                f"({ratio * 100:.1f}% of starting)"
            ),
            key=f"paper:bp:{getattr(account, 'account_id', 'unknown')}:{ratio:.2f}",
            payload={"cash": str(cash), "ratio": ratio, "threshold": threshold_pct},
        )
    ]


def _gtc_expiring_alerts(
    open_orders, now: datetime, horizon_days: int = 3
) -> list[Alert]:
    """Emit alerts for GTC orders whose ``expires_at`` is within horizon."""
    out: list[Alert] = []
    cutoff = now + timedelta(days=horizon_days)
    for order in open_orders or ():
        tif = str(getattr(order, "time_in_force", "") or "")
        if tif.lower() != "gtc":
            continue
        expires = getattr(order, "expires_at", None)
        if not isinstance(expires, datetime):
            continue
        if expires <= cutoff and expires >= now:
            symbol = str(getattr(order, "symbol", "?"))
            oid = str(getattr(order, "order_id", ""))
            days = (expires - now).days
            out.append(
                Alert(
                    trigger=TriggerType.PAPER_TRADING_EVENT,
                    severity=Severity.INFO,
                    symbol=symbol,
                    when=now,
                    message=f"GTC order for {symbol} expires in {days}d",
                    key=f"paper:gtc:{oid}",
                    payload={"expires_at": expires.isoformat(), "days_until": days},
                )
            )
    return out


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _alert_to_item(a: Alert) -> PaperAlertItem:
    return PaperAlertItem(
        trigger=a.trigger.value,
        severity=a.severity.value,
        symbol=a.symbol,
        when=a.when.isoformat(),
        message=a.message,
        key=a.key,
        payload=a.payload,
    )


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Paper-trading alert stream for the last hour.",
            code=[
                "obb.portfolio_intel.paper.alerts("
                'account_id="acc-1", since_seconds=3600)',
            ],
        )
    ],
)
def alerts(
    account_id: str,
    since_seconds: int = 3600,
    low_buying_power_pct: float = 0.10,
    gtc_horizon_days: int = 3,
) -> OBBject[PaperAlertsResult]:
    """Aggregate paper-trading alerts for a specific account.

    Authorization: ``user_id`` is resolved from the authenticated
    session (not the request), then ``account_id`` is verified to
    belong to that principal. On any auth failure the route returns
    an empty alert list plus an ``ACL denied`` warning — never leaks
    account existence, balance, or ledger contents.

    Parameters
    ----------
    account_id : str
        Account to fetch alerts for. MUST belong to the caller.
    since_seconds : int
        Lookback in seconds. Default 3600 (1 hour).
    low_buying_power_pct : float
        Threshold ratio of cash / starting_cash below which the
        low-buying-power alert fires. Default 10%.
    gtc_horizon_days : int
        GTC-expiring-soon horizon. Default 3 days.
    """
    ledger_store = _default_ledger_store()
    account_store = _default_account_store()

    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(seconds=since_seconds)

    warnings: list[str] = []
    combined: list[Alert] = []

    # ---- authorize -------------------------------------------------------
    try:
        principal = _resolve_principal()
    except PermissionError as exc:
        return OBBject(
            results=PaperAlertsResult(alerts=[], warnings=[f"ACL denied: {exc}"])
        )
    if not _verify_account_ownership(
        account_store, principal=principal, account_id=account_id
    ):
        # Deliberately vague error — no oracle for account existence.
        return OBBject(
            results=PaperAlertsResult(
                alerts=[], warnings=["ACL denied: account not accessible"]
            )
        )
    user_id = principal

    try:
        entries = ledger_store.list_for_account(user_id=user_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"ledger read failed: {exc}")
        entries = []
    events = _ledger_to_paper_events(entries)
    combined += evaluate_paper_trading_events(events, since=since)

    try:
        account = account_store.get(user_id=user_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"account read failed: {exc}")
        account = None
    combined += _low_buying_power_alerts(
        account, now=now, threshold_pct=low_buying_power_pct
    )

    open_orders = getattr(account, "open_orders", None) if account is not None else None
    combined += _gtc_expiring_alerts(
        open_orders, now=now, horizon_days=gtc_horizon_days
    )

    combined.sort(
        key=lambda a: (
            -{"critical": 3, "warning": 2, "info": 1}[a.severity.value],
            a.when,
            a.symbol,
            a.key,
        )
    )
    return OBBject(
        results=PaperAlertsResult(
            alerts=[_alert_to_item(a) for a in combined],
            warnings=warnings,
        )
    )
