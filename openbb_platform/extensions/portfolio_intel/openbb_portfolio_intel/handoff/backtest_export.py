"""Backtest hand-off contract for paper trading (#561).

PRD §16.9 — ``paper.account.export_backtest`` command generates an
openbb-backtest trade list from ``paper_fills`` so users can round-trip
their paper history through the backtest engine (walk-forward, param
sweeps, out-of-sample).

This module ships the **contract** (shape + conversion + shape checks)
without the paper-trading persistence layer (#544-548 owns paper_fills).
Once the paper subsystem lands, the router just:

    fills = paper_fill_store.query(account_id, since=..., until=...)
    export = build_export(fills, account_id=..., feature_flag=...)
    return export

The trade-shape converter targets the extant ``openbb_backtest.models.Trade``
schema (imported lazily; if the backtest extension is not installed, the
JSON fallback path is used automatically).

Design decisions:

1. **Feature-flagged fallback (PRD §16.9).** When
   ``openbb_backtest.models`` is importable, the export is a list of
   ``Trade`` objects. When it isn't, the export is a JSON-serializable
   list of dicts matching the same field names — same information,
   different envelope. Downstream consumers can degrade gracefully.
2. **Idempotent + deterministic.** Same input fills → same export
   bytes. Ordered by ``timestamp`` then ``symbol`` (stable secondary
   key for same-bar fills).
3. **All monetary quantities as Decimal** in the paper side; converted
   to whatever type ``openbb_backtest.Trade`` expects at the boundary.
   Matches the paper cost-basis convention (#548).
4. **``side`` inferred from signed qty.** Paper fills carry signed
   quantity (buy positive, sell negative); backtest Trade has an
   explicit ``Side`` enum. The converter maps sign → enum at the
   boundary and rejects zero-qty fills (a paper bug if they exist).
5. **``verify_exportable`` catches producer bugs.** Enforces that
   every fill has a symbol, positive absolute qty, finite price, and
   a timestamp. Called by the router before returning the payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable


class PaperSide(str, Enum):
    """Signed-quantity direction of a paper fill."""

    BUY = "BUY"
    SELL = "SELL"

    @classmethod
    def from_signed_quantity(cls, qty: Decimal) -> "PaperSide":
        if qty > 0:
            return cls.BUY
        if qty < 0:
            return cls.SELL
        raise ValueError(
            "cannot infer Side from zero quantity — paper fills should never "
            "have qty == 0 (this is a paper-fill producer bug, see #547/#548)"
        )


@dataclass(frozen=True)
class PaperFill:
    """One filled paper trade — the input shape to the exporter.

    The paper-trading subsystem (#544-548) owns persistence; the
    exporter treats these as an immutable input tuple.

    Signed convention: ``quantity > 0`` = buy, ``< 0`` = sell.
    ``price`` is the fill price INCLUDING slippage (matches the
    ``openbb_backtest.models.Trade.price`` semantic).
    """

    timestamp: datetime
    symbol: str
    quantity: Decimal  # signed
    price: Decimal
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    account_id: str = ""  # empty is legal when the exporter owns account scoping
    fill_id: str = ""  # empty is legal when the exporter owns idempotency


@dataclass(frozen=True)
class BacktestExport:
    """Result of a paper→backtest hand-off (#561).

    ``trades`` shape depends on ``format``:
      - ``"backtest_trade"``: list of ``openbb_backtest.models.Trade`` objects
      - ``"json_dict"``: list of JSON-serializable dicts with the same fields
    """

    account_id: str
    format: str  # "backtest_trade" | "json_dict"
    trades: list[Any]  # actual type depends on `format`
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature-flagged converter dispatch
# ---------------------------------------------------------------------------


def _backtest_trade_available() -> bool:
    """Return True iff ``openbb_backtest.models.Trade`` is importable.

    Used to pick the export format at runtime. Kept as a function
    (not a module-level bool) so tests can monkey-patch it without
    reloading the module.
    """
    try:
        import openbb_backtest.models  # noqa: F401,PLC0415  # pylint: disable=import-outside-toplevel,unused-import

        return True
    except ImportError:
        return False


def _paper_fill_to_backtest_trade(fill: PaperFill) -> Any:
    """Convert a PaperFill to an ``openbb_backtest.models.Trade``.

    Only called when ``_backtest_trade_available()`` is True. Import
    is lazy to keep this module import-safe when openbb-backtest is
    absent.
    """
    from openbb_backtest.models import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        Trade,
    )

    # openbb_backtest.Side is `Literal["buy","sell"]`, not an enum.
    side: str = "buy" if fill.quantity > 0 else "sell"
    return Trade(
        timestamp=fill.timestamp,
        symbol=fill.symbol,
        side=side,
        quantity=abs(fill.quantity),
        price=fill.price,
        commission=fill.commission,
        slippage=fill.slippage,
    )


def _paper_fill_to_json_dict(fill: PaperFill) -> dict:
    """Fallback: convert to a JSON-serializable dict.

    Field names match ``openbb_backtest.models.Trade`` so downstream
    consumers can uniformly read either format.
    """
    return {
        "timestamp": fill.timestamp.isoformat(),
        "symbol": fill.symbol,
        "side": PaperSide.from_signed_quantity(fill.quantity).value,
        "quantity": str(abs(fill.quantity)),
        "price": str(fill.price),
        "commission": str(fill.commission),
        "slippage": str(fill.slippage),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_export(
    fills: Iterable[PaperFill],
    *,
    account_id: str,
    force_json_fallback: bool = False,
) -> BacktestExport:
    """Convert an iterable of PaperFill → BacktestExport.

    Parameters
    ----------
    fills
        Paper fills for a single account. Ordered by (timestamp, symbol)
        in the output — order of the input is not preserved.
    account_id
        Owning account. Attached to the export envelope for downstream
        provenance / audit.
    force_json_fallback
        If True, always use the JSON-dict format regardless of whether
        ``openbb_backtest.models`` is importable. Test seam + escape
        hatch for consumers that don't want the openbb-backtest dep.

    Returns
    -------
    BacktestExport
        Immutable snapshot with sorted trades + provenance envelope.
    """
    fills_list = list(fills)
    verify_exportable(fills_list)

    # Deterministic sort — timestamp primary, symbol secondary, quantity tiebreak.
    fills_sorted = sorted(
        fills_list, key=lambda f: (f.timestamp, f.symbol, abs(f.quantity))
    )

    use_native = (not force_json_fallback) and _backtest_trade_available()
    if use_native:
        trades = [_paper_fill_to_backtest_trade(f) for f in fills_sorted]
        fmt = "backtest_trade"
        warnings: list[str] = []
    else:
        trades = [_paper_fill_to_json_dict(f) for f in fills_sorted]
        fmt = "json_dict"
        warnings = [
            "openbb-backtest not available (or forced fallback); "
            "returning JSON-dict format instead of Trade objects "
            "(PRD §16.9 feature-flagged fallback)"
        ]

    return BacktestExport(
        account_id=account_id,
        format=fmt,
        trades=trades,
        warnings=warnings,
    )


def verify_exportable(fills: list[PaperFill]) -> None:
    """Raise ``ValueError`` for any paper-fill producer bugs.

    Enforces:
      - non-empty symbol
      - quantity != 0
      - finite (non-NaN, non-Inf) price
      - finite commission, slippage (both >= 0)
      - timestamp is a datetime (not None)

    This is the shape contract — the router calls it before returning.
    Tests use it to guard against upstream drift in the paper subsystem.
    """
    for i, f in enumerate(fills):
        if not f.symbol:
            raise ValueError(f"fill {i}: symbol is empty")
        if f.quantity == 0:
            raise ValueError(
                f"fill {i} ({f.symbol}): quantity is zero — paper fills should "
                "never carry zero quantity (see #547/#548)"
            )
        if f.price is None or not f.price.is_finite():
            raise ValueError(f"fill {i} ({f.symbol}): price is not finite ({f.price})")
        if f.commission is None or not f.commission.is_finite() or f.commission < 0:
            raise ValueError(
                f"fill {i} ({f.symbol}): commission must be finite and >= 0 "
                f"(got {f.commission})"
            )
        if f.slippage is None or not f.slippage.is_finite() or f.slippage < 0:
            raise ValueError(
                f"fill {i} ({f.symbol}): slippage must be finite and >= 0 "
                f"(got {f.slippage})"
            )
        if f.timestamp is None:
            raise ValueError(f"fill {i} ({f.symbol}): timestamp is None")
