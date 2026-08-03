"""Smart-money rollup route (#527).

One command:
- ``obb.portfolio_intel.smart_money.rollup(basket, window_days, top_n, provider)``
  Fetches insider transactions + 13F institutional holdings changes +
  senate disclosures for basket symbols in the last ``window_days`` days,
  aggregates via ``analytics.events_smartmoney.aggregate_smart_money``,
  returns per-symbol scores + ``top_conviction`` list.

Composes:
- ``openbb_portfolio_intel.analytics.events_smartmoney`` for aggregation
  + top-K conviction ranking (#538).
- Provider fetch via ``obb.equity.ownership.*`` (insider / institutional)
  and available SEC endpoints for senate disclosures.

Pattern-mirror of #541/#528/#542 — all lint pragmas pre-applied, models
in top-level file, list[dict] input, bare OBBject return.

Design: ``docs/superpowers/specs/2026-07-20-smart-money-route-design.md``.

Scope narrowed vs PRD §14 (documented):
- **Point-in-time rollup only** (no time-series).
- **3 sources: insider / form_13f / senate** — normalize signals inline
  from provider-specific row shapes into SmartMoneySignal.
- **SEC / US only** — non-US disclosures are P3+.
- **Per-source fetch failure = warning + partial result** (matches
  #542 posture).
"""

# pylint: disable=unused-argument  # rollup() 'provider' reserved for multi-provider follow-up
# pylint: disable=broad-exception-caught  # per-source failure isolation is intentional
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_portfolio_intel.analytics.events_smartmoney import (
    SmartMoneyScore,
    SmartMoneySignal,
    SmartMoneySource,
    aggregate_smart_money,
    top_conviction,
)
from openbb_portfolio_intel.models import (
    BasketPosition,
    SmartMoneyRollupResult,
    SmartMoneyScoreItem,
)
from openbb_portfolio_intel.routers.xray_router import _validate_basket

logger = logging.getLogger(__name__)

router = Router(
    prefix="/smart_money",
    description=(
        "Smart-money rollup for basket symbols. Aggregates insider "
        "transactions + 13F institutional changes + senate disclosures "
        "over a lookback window into per-symbol conviction scores."
    ),
)


# ---------------------------------------------------------------------------
# Collaborator seam (patched in unit tests; lazy in production)
# ---------------------------------------------------------------------------


_SOURCE_KINDS = ("insider", "form_13f", "senate")


def _fetch_signals(
    kind: str, *, symbols: list[str], start_date: date, provider: str | None = None
):
    """Fetch one signal source. Seam: unit tests patch this."""
    from openbb import obb  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    # Which endpoint per kind — best-effort resolution. Unknown endpoint
    # names raise AttributeError and are caught by the caller.
    if kind == "insider":
        endpoint = obb.equity.ownership.insider_trading
    elif kind == "form_13f":
        endpoint = obb.equity.ownership.institutional
    elif kind == "senate":
        # OpenBB core may or may not have a `senate` endpoint under
        # regulators.sec; caller catches AttributeError.
        endpoint = obb.regulators.sec.senate_trades  # type: ignore[attr-defined]
    else:
        raise ValueError(f"unknown signal kind: {kind}")

    return endpoint(
        symbol=",".join(symbols),
        start_date=start_date,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _positions_from_basket(basket: list[dict]) -> list[BasketPosition]:
    """Coerce basket dicts → BasketPosition and reject empty/negative."""
    positions = [
        BasketPosition(symbol=str(r["symbol"]), weight=Decimal(str(r["weight"])))
        for r in basket
    ]
    _validate_basket(positions)
    return positions


def _extract_rows(response) -> list:
    return getattr(response, "results", response) or []


def _row_to_signal(row: Any, source: SmartMoneySource) -> SmartMoneySignal | None:
    """Convert one provider row → SmartMoneySignal, or None if malformed."""
    symbol = getattr(row, "symbol", None)
    if not symbol:
        return None

    direction = 0
    weight = Decimal("0")

    if source == SmartMoneySource.INSIDER:
        # Form 4: transaction_type P-Purchase / S-Sale
        tx = str(getattr(row, "transaction_type", "") or "").upper()
        if "PURCHASE" in tx or tx.startswith("P"):
            direction = 1
        elif "SALE" in tx or tx.startswith("S"):
            direction = -1
        shares = getattr(row, "shares", None)
        if shares is not None:
            try:
                weight = Decimal(str(abs(float(shares))))
            except (ValueError, TypeError):
                weight = Decimal("0")

    elif source == SmartMoneySource.FORM_13F:
        # Institutional 'change' field: +ve = increased holding
        change = getattr(row, "change", None)
        if change is not None:
            try:
                c = float(change)
                direction = 1 if c > 0 else (-1 if c < 0 else 0)
                weight = Decimal(str(abs(c)))
            except (ValueError, TypeError):
                pass

    elif source == SmartMoneySource.SENATE:
        tx = str(getattr(row, "transaction_type", "") or "").upper()
        if "PURCHASE" in tx or "BUY" in tx:
            direction = 1
        elif "SALE" in tx or "SELL" in tx:
            direction = -1
        amount = getattr(row, "amount", None)
        if amount is not None:
            try:
                weight = Decimal(str(abs(float(amount))))
            except (ValueError, TypeError):
                weight = Decimal("0")

    if weight == 0 and direction == 0:
        return None
    return SmartMoneySignal(
        symbol=str(symbol).upper(),
        source=source,
        direction=direction,
        weight=weight,
    )


def _score_to_item(score: SmartMoneyScore) -> SmartMoneyScoreItem:
    """Convert internal SmartMoneyScore → response-model item."""
    return SmartMoneyScoreItem(
        symbol=score.symbol,
        composite=float(score.composite),
        by_source={src.value: float(val) for src, val in score.by_source.items()},
        signal_count=score.signal_count,
    )


_KIND_TO_SOURCE: dict[str, SmartMoneySource] = {
    "insider": SmartMoneySource.INSIDER,
    "form_13f": SmartMoneySource.FORM_13F,
    "senate": SmartMoneySource.SENATE,
}


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Smart-money rollup for a 2-symbol basket over the last 90 days.",
            code=[
                "basket = [",
                '    {"symbol": "AAPL", "weight": 0.5},',
                '    {"symbol": "MSFT", "weight": 0.5},',
                "]",
                'r = obb.portfolio_intel.smart_money.rollup(basket=basket, window_days=90, provider="fmp_cached")',
                "for s in r.results.top_conviction[:5]:",
                "    print(s.symbol, s.composite, s.signal_count)",
            ],
        ),
    ],
)
def rollup(
    basket: list[dict],
    window_days: int = 90,
    top_n: int = 10,
    provider: str | None = None,
) -> OBBject:
    """Smart-money rollup for basket symbols over a lookback window.

    Fetches insider transactions, 13F holdings changes, and senate
    disclosures for basket symbols in the last ``window_days`` days,
    normalizes each into a ``SmartMoneySignal``, aggregates per-symbol
    via :func:`aggregate_smart_money`, and returns per-symbol scores
    plus a top-N ``top_conviction`` list (ranked by ``|composite|``).

    Weight-agnostic — ``basket`` weights are IGNORED (signals are per-symbol);
    the dict shape is kept identical to other routes for API consistency.

    Per-source fetch failures are non-fatal — a warning is added and the
    rollup includes whatever other sources succeeded.

    Returns
    -------
    OBBject[:class:`~openbb_portfolio_intel.models.SmartMoneyRollupResult`]
        Bare ``OBBject`` at the signature level (see #541); runtime
        ``.results`` is always ``SmartMoneyRollupResult``.

    Raises
    ------
    ValueError
        - Empty basket
        - ``window_days <= 0``
        - ``top_n <= 0``
    """
    positions = _positions_from_basket(basket)
    if window_days <= 0:
        raise ValueError(f"window_days must be positive; got {window_days}.")
    if top_n <= 0:
        raise ValueError(f"top_n must be positive; got {top_n}.")

    portfolio_symbols = {p.symbol.upper() for p in positions}
    start = date.today() - timedelta(days=window_days)

    warnings: list[str] = []
    all_signals: list[SmartMoneySignal] = []

    for kind in _SOURCE_KINDS:
        source = _KIND_TO_SOURCE[kind]
        try:
            response = _fetch_signals(
                kind,
                symbols=sorted(portfolio_symbols),
                start_date=start,
                provider=provider,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("smart_money: %s fetch failed: %s", kind, exc)
            warnings.append(
                f"{kind}: fetch raised ({type(exc).__name__}) — that "
                "source omitted from rollup"
            )
            continue

        rows = _extract_rows(response)
        for row in rows:
            sig = _row_to_signal(row, source)
            if sig is not None:
                all_signals.append(sig)

    scores = aggregate_smart_money(all_signals, portfolio_symbols=portfolio_symbols)
    top = top_conviction(scores, n=top_n, absolute=True)

    by_symbol_items = {sym: _score_to_item(sc) for sym, sc in scores.items()}
    top_items = [_score_to_item(sc) for sc in top]

    return OBBject(
        results=SmartMoneyRollupResult(
            by_symbol=by_symbol_items,
            top_conviction=top_items,
            warnings=warnings,
        )
    )
