"""Shared cost-basis + P&L math (#548).

Prevents divergence risk between paper trading and the real portfolio
service. **Both** the paper fill engine (#563) and the eventual real
portfolio-cost service compose from the pure functions in this module —
call-site parity is the load-bearing guarantee.

## Model

- **Weighted-average cost basis** on longs. Buys accumulate cost; sells
  realize P&L at the current weighted-average cost and shrink the
  position. When a position is fully closed and then re-opened, the
  cost basis resets.
- **Signed quantities.** ``qty > 0`` = long, ``qty < 0`` = short. On a
  short position, cost basis represents the weighted-average proceeds
  per share. Realized P&L on a short buy-to-cover = (avg_proceeds -
  cover_price) * qty_covered.
- **Flipping** (long → short or vice versa in one fill) is handled by
  splitting the fill: first close the existing position (realize P&L),
  then open the opposite side at the fill price.
- **Fees & commissions** reduce realized P&L on the closing side. Buy
  commissions are added to cost basis; sell commissions are subtracted
  from proceeds.
- **All arithmetic in Decimal.** Matches the SQL schema (DECIMAL(18,4))
  and prevents float drift on tax-reporting numbers.

## Public API

- ``Lot`` — snapshot of one symbol's tax lot (qty, avg_cost, realized_pnl)
- ``FillEvent`` — one incoming fill (signed qty, price, commission)
- ``apply_fill(lot, fill)`` → ``(new_lot, realized_pnl_from_this_fill)``
- ``unrealized_pnl(lot, mark_price)`` → Decimal
- ``mark_to_market(lot, mark_price)`` → tuple[unrealized, market_value]

## Out of scope (deferred)

- **Specific-lot / FIFO / LIFO accounting.** This cut is weighted-average
  only. Tax-optimization lot selection is a separate module.
- **Wash-sale detection.** SEC wash-sale rules require a 30-day window;
  belongs on a reporting layer, not the fill accounting core.
- **Corporate actions.** Splits, dividends, spin-offs are ledger events
  (#545 owns paper_ledger) and adjust cost-basis via separate helpers
  (follow-up).
- **Multi-currency.** All fills assumed to be in the account's base
  currency.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal


@dataclass(frozen=True)
class Lot:
    """One symbol's tax-lot snapshot at a point in time.

    ``qty`` is signed. ``avg_cost`` is the weighted-average per-share
    cost (for longs) or per-share proceeds (for shorts). ``realized_pnl``
    is the cumulative realized P&L on this symbol since inception.

    A brand-new position starts as ``Lot(symbol, Decimal(0), Decimal(0),
    Decimal(0))``. All fields are non-negative when the position is
    flat; ``qty`` and ``avg_cost`` become non-zero after the first fill.
    """

    symbol: str
    qty: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal = Decimal("0")


@dataclass(frozen=True)
class FillEvent:
    """One executed fill against a specific symbol.

    ``qty`` is signed: positive = buy, negative = sell. ``price`` is the
    fill price INCLUDING slippage but EXCLUDING commission (commission
    is a separate field, folded into P&L by the cost-basis math).

    ``qty == 0`` is rejected at :func:`apply_fill` boundary — same
    posture as #561's backtest export.
    """

    symbol: str
    qty: Decimal  # signed
    price: Decimal
    commission: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CostBasisError(ValueError):
    """Raised on ill-formed input to the cost-basis math."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_fill(lot: Lot, fill: FillEvent) -> tuple[Lot, Decimal]:
    """Apply one fill to a lot and return (new_lot, realized_pnl_from_fill).

    Handles opening, closing, and flipping in one call. Cost basis
    updates use weighted-average accounting.

    Returns
    -------
    (new_lot, realized_pnl_from_fill)
        ``new_lot`` is the resulting Lot after the fill. ``realized_pnl_from_fill``
        is the P&L realized specifically by this fill (positive for
        gains, negative for losses). ``new_lot.realized_pnl`` includes
        this and all prior realized P&L.

    Raises
    ------
    CostBasisError
        - ``fill.symbol != lot.symbol``
        - ``fill.qty == 0``
        - ``fill.price`` not finite or negative
        - ``fill.commission`` not finite or negative
    """
    _validate_fill(fill, lot)

    # Case 1: opening (from flat)
    if lot.qty == 0:
        return _open(lot, fill)

    # Case 2: same-side add (long adding to long, short adding to short)
    same_side_add = (lot.qty > 0 and fill.qty > 0) or (lot.qty < 0 and fill.qty < 0)
    if same_side_add:
        return _add(lot, fill)

    # Case 3: closing (partial or full) or flipping
    # Note: covers both "sell into a long" and "buy into a short".
    return _close_or_flip(lot, fill)


def unrealized_pnl(lot: Lot, mark_price: Decimal) -> Decimal:
    """Return unrealized P&L at the given mark price.

    For a long: ``(mark - avg_cost) * qty``
    For a short: ``(avg_cost - mark) * |qty|`` (equivalently
    ``(mark - avg_cost) * qty`` since qty is negative)
    For a flat position: 0.

    Raises
    ------
    CostBasisError
        If ``mark_price`` is not finite or negative.
    """
    if not mark_price.is_finite():
        raise CostBasisError(f"mark_price {mark_price} is not finite")
    if mark_price < 0:
        raise CostBasisError(f"mark_price {mark_price} must be >= 0")
    if lot.qty == 0:
        return Decimal("0")
    return (mark_price - lot.avg_cost) * lot.qty


def mark_to_market(lot: Lot, mark_price: Decimal) -> tuple[Decimal, Decimal]:
    """Return (unrealized_pnl, market_value) at the mark price.

    Market value of a long: ``mark * qty`` (positive)
    Market value of a short: ``mark * qty`` (negative — a short liability)
    Market value of a flat position: 0.
    """
    up = unrealized_pnl(lot, mark_price)
    return up, mark_price * lot.qty


# ---------------------------------------------------------------------------
# Internal helpers — cases
# ---------------------------------------------------------------------------


def _open(lot: Lot, fill: FillEvent) -> tuple[Lot, Decimal]:
    """Opening a position from flat.

    Long open: new_avg = (price * qty + commission) / qty  (commission
    added to cost basis)
    Short open: new_avg = (price * |qty| - commission) / |qty|
    (commission reduces the effective proceeds per share)
    """
    if fill.qty > 0:
        # Long open
        new_avg = (fill.price * fill.qty + fill.commission) / fill.qty
    else:
        # Short open — treat proceeds per share as the "avg_cost" so that
        # cover P&L works out symmetrically with the long case.
        abs_qty = -fill.qty
        new_avg = (fill.price * abs_qty - fill.commission) / abs_qty
    return (
        Lot(
            symbol=lot.symbol,
            qty=fill.qty,
            avg_cost=new_avg,
            realized_pnl=lot.realized_pnl,
        ),
        Decimal("0"),  # no realized P&L on opening
    )


def _add(lot: Lot, fill: FillEvent) -> tuple[Lot, Decimal]:
    """Same-side add — weighted-average update, no realized P&L."""
    new_qty = lot.qty + fill.qty
    # Weighted-average: (existing_qty * existing_avg + fill_qty * fill_price + commission_adjustment) / new_qty
    # For long adds, commission increases total cost. For short adds,
    # commission reduces total proceeds.
    if lot.qty > 0:
        # Long add
        total_cost = lot.qty * lot.avg_cost + fill.qty * fill.price + fill.commission
        new_avg = total_cost / new_qty
    else:
        # Short add — qty is negative; total_proceeds is negative-of-total
        abs_existing = -lot.qty
        abs_fill = -fill.qty
        total_proceeds = (
            abs_existing * lot.avg_cost + abs_fill * fill.price - fill.commission
        )
        abs_new = abs_existing + abs_fill
        new_avg = total_proceeds / abs_new
    return (
        Lot(
            symbol=lot.symbol,
            qty=new_qty,
            avg_cost=new_avg,
            realized_pnl=lot.realized_pnl,
        ),
        Decimal("0"),
    )


def _close_or_flip(lot: Lot, fill: FillEvent) -> tuple[Lot, Decimal]:
    """Closing (partial/full) or flipping through zero.

    Realized P&L is booked against the portion being closed at the
    weighted-average cost basis. If the fill quantity exceeds the
    existing position, the excess opens the opposite side at the fill
    price (a new "opening" fill).
    """
    # Quantity being closed (positive number of shares)
    closing_qty = min(abs(fill.qty), abs(lot.qty))
    # Direction of the close: closing a long = selling; closing a short = buying
    # Sign convention for realized P&L:
    #   long close (sell):  gain = (price - avg_cost) * qty_closed - commission_portion
    #   short close (buy):  gain = (avg_cost - price) * qty_closed - commission_portion
    # Commission on the closing side always reduces realized P&L.
    # Prorate the commission by the fraction of the fill that's actually
    # closing (the flip's opening portion is a separate open below).
    close_fraction = closing_qty / abs(fill.qty)
    close_commission = fill.commission * close_fraction
    if lot.qty > 0:
        # Long close (fill.qty < 0 means sell)
        realized = (fill.price - lot.avg_cost) * closing_qty - close_commission
    else:
        # Short close (fill.qty > 0 means buy-to-cover)
        realized = (lot.avg_cost - fill.price) * closing_qty - close_commission

    # Determine new position state
    remaining_lot_qty = lot.qty + fill.qty  # signed arithmetic
    if remaining_lot_qty == 0:
        # Full close — position flat, avg_cost resets to 0
        new_lot = Lot(
            symbol=lot.symbol,
            qty=Decimal("0"),
            avg_cost=Decimal("0"),
            realized_pnl=lot.realized_pnl + realized,
        )
        return new_lot, realized

    if (remaining_lot_qty > 0) == (lot.qty > 0):
        # Partial close — same side, avg_cost unchanged (only qty shrinks)
        new_lot = Lot(
            symbol=lot.symbol,
            qty=remaining_lot_qty,
            avg_cost=lot.avg_cost,
            realized_pnl=lot.realized_pnl + realized,
        )
        return new_lot, realized

    # Flip — remaining opens the opposite side at fill.price
    # Recurse into _open with the remaining piece, but preserve realized
    # cumulative P&L (only the closing portion booked realized).
    flip_qty = remaining_lot_qty  # signed; opposite side
    flip_commission = fill.commission * (1 - close_fraction)
    opening_fill = FillEvent(
        symbol=fill.symbol,
        qty=flip_qty,
        price=fill.price,
        commission=flip_commission,
    )
    # Base for the open: a flat lot carrying the realized-P&L accumulated
    # from the close.
    base = replace(
        lot,
        qty=Decimal("0"),
        avg_cost=Decimal("0"),
        realized_pnl=lot.realized_pnl + realized,
    )
    opened_lot, _ = _open(base, opening_fill)
    return opened_lot, realized


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_fill(fill: FillEvent, lot: Lot) -> None:
    if fill.symbol != lot.symbol:
        raise CostBasisError(
            f"fill.symbol={fill.symbol!r} does not match lot.symbol={lot.symbol!r}"
        )
    if fill.qty == 0:
        raise CostBasisError("fill.qty must be non-zero")
    if not fill.price.is_finite() or fill.price < 0:
        raise CostBasisError(f"fill.price {fill.price} must be finite and >= 0")
    if not fill.commission.is_finite() or fill.commission < 0:
        raise CostBasisError(
            f"fill.commission {fill.commission} must be finite and >= 0"
        )
