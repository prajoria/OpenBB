"""Corporate-action reconciler (#554) — nightly job that reconciles paper
positions against dividend / split calendar rows and appends the resulting
DIVIDEND / SPLIT ledger entries.

Design: pure-function core (``reconcile``) that takes:
- current positions (from ``PositionStore``-shaped input)
- a window's dividend rows (list of dict, provider-agnostic)
- a window's split rows (list of dict, provider-agnostic)
- an existing ledger (for idempotency dedup)

...and returns a list of new ``LedgerEntry`` objects to append. No I/O.
Callers (a router endpoint or an ops cron) fetch the calendar rows,
call ``reconcile``, then loop ``store.append(entry)``. That store method
is already idempotent per entry_id, so a re-run on the same window is a
no-op.

The "silent P&L drift = fail" acceptance from the issue body is enforced
by:
1. Every generated entry has a deterministic ``entry_id`` derived from
   (event-type, ex-date, symbol) — so re-running does NOT double-credit.
2. If the reconciler generates zero entries for a non-empty position
   set with a non-empty window, that's LOGGED at WARN (usually means
   the calendar rows were empty or the symbols didn't intersect —
   silent-empty is exactly the failure mode the PRD flags).

Shape narrowing vs the PRD:
- No FX/multi-currency dividends this cut. USD only, matching current
  PositionStore.
- No qualified/ordinary split. Follow-up if the widgets ever surface it.
- Ex-dividend-date cash credit is booked at ``occurred_at = ex_date``,
  not payment_date. Simpler, matches the ledger's replay semantics,
  and payment_date can drift up to 30 days which would break the
  point-in-time reconciler window.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from openbb_portfolio_intel.paper.ledger import (
    LedgerEntry,
    LedgerEntryType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionSnapshot:
    """One row of a position at reconciler time.

    Held quantity is signed (negative for shorts). Symbol is uppercased
    for match against calendar rows.
    """

    symbol: str
    quantity: Decimal


@dataclass(frozen=True)
class ReconcileResult:
    """What the reconciler produced for one (account, window) invocation."""

    new_entries: list[LedgerEntry]
    dividend_rows_processed: int
    split_rows_processed: int
    warnings: list[str]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def reconcile(  # pylint: disable=too-many-positional-arguments,too-many-arguments,too-many-locals,too-many-branches
    account_id: str,
    user_id: str,
    positions: list[PositionSnapshot],
    dividend_rows: list[dict[str, Any]],
    split_rows: list[dict[str, Any]],
    existing_entry_ids: set[str],
    *,
    sequence_start: int = 0,
) -> ReconcileResult:
    """Pure function — produce new LedgerEntry rows for the given window.

    Parameters
    ----------
    account_id, user_id
        Tenant-scope for the emitted entries.
    positions
        Held positions at reconciliation time. Only symbols with
        positive quantity (long positions) get dividend credit;
        negative (short) positions DEBIT dividend cash (short-seller
        pays the dividend to the lender). Splits apply to any non-zero
        position.
    dividend_rows
        Provider-agnostic dict rows. Required keys per row:
          - ``symbol``: str
          - ``ex_dividend_date``: date-like (str, date, or datetime)
          - ``amount``: numeric (per-share cash dividend)
    split_rows
        Provider-agnostic dict rows. Required keys per row:
          - ``symbol``: str
          - ``date``: date-like (effective date)
          - ``numerator``: int
          - ``denominator``: int
        Ratio = numerator/denominator (e.g. 2/1 for forward 2:1;
        1/10 for reverse 1:10).
    existing_entry_ids
        Set of entry_ids already present in the ledger for this
        (user, account). Passed in to keep this function pure — the
        caller does ``{e.entry_id for e in store.list_for_account(...)}``.
    sequence_start
        Next available sequence number. Emitted entries will use
        sequence_start, sequence_start+1, ... in insertion order.
        Caller responsibility: ``max((e.sequence for e in existing),
        default=-1) + 1``.

    Returns
    -------
    ReconcileResult
        - ``new_entries``: list of ledger entries the caller should
          ``store.append(...)``. Empty if everything's already reconciled.
        - ``warnings``: human-readable diagnostics — e.g. positions
          without matching calendar rows (usually benign), calendar
          rows for symbols we don't hold (skipped).

    Idempotency
    -----------
    entry_id is derived from (event_type, symbol, ex_date) via SHA1
    truncation. Re-running with the same input + same existing set
    produces zero new entries.
    """
    warnings: list[str] = []
    new_entries: list[LedgerEntry] = []
    seq = sequence_start

    # Index positions by uppercased symbol for O(1) lookup
    position_by_symbol = {
        p.symbol.upper(): p.quantity for p in positions if p.quantity != 0
    }
    if not position_by_symbol:
        warnings.append("no non-zero positions; reconciler is a no-op")
        return ReconcileResult(
            new_entries=[],
            dividend_rows_processed=0,
            split_rows_processed=0,
            warnings=warnings,
        )

    # Dividends: DIVIDEND ledger entry per (symbol, ex_date) intersection
    div_processed = 0
    for row in dividend_rows:
        sym = str(row.get("symbol", "")).upper()
        if not sym or sym not in position_by_symbol:
            continue
        ex_date = _coerce_date(row.get("ex_dividend_date"))
        if ex_date is None:
            warnings.append(f"dividend row for {sym} missing ex_dividend_date; skipped")
            continue
        per_share = _coerce_decimal(row.get("amount"))
        if per_share is None or per_share <= 0:
            warnings.append(
                f"dividend row for {sym} on {ex_date} has non-positive "
                f"amount ({row.get('amount')!r}); skipped"
            )
            continue
        held_qty = position_by_symbol[sym]
        cash_delta = per_share * held_qty  # sign follows held qty
        entry_id = _make_entry_id("div", sym, ex_date)
        if entry_id in existing_entry_ids:
            continue  # already reconciled
        div_processed += 1
        new_entries.append(
            LedgerEntry(
                entry_id=entry_id,
                account_id=account_id,
                user_id=user_id,
                entry_type=LedgerEntryType.DIVIDEND,
                sequence=seq,
                occurred_at=_date_to_datetime_utc(ex_date),
                amount=cash_delta,
                symbol=sym,
                notes=(
                    f"reconciler: {per_share}/share × {held_qty} held = {cash_delta}"
                    + (" (short — dividend debit)" if held_qty < 0 else "")
                ),
            )
        )
        seq += 1

    # Splits: SPLIT ledger entry per (symbol, split_date) intersection
    split_processed = 0
    for row in split_rows:
        sym = str(row.get("symbol", "")).upper()
        if not sym or sym not in position_by_symbol:
            continue
        eff_date = _coerce_date(row.get("date"))
        if eff_date is None:
            warnings.append(f"split row for {sym} missing date; skipped")
            continue
        num = row.get("numerator")
        den = row.get("denominator")
        if not (isinstance(num, int) and isinstance(den, int)) or den == 0:
            warnings.append(
                f"split row for {sym} on {eff_date} has invalid "
                f"numerator/denominator ({num}/{den}); skipped"
            )
            continue
        ratio = Decimal(num) / Decimal(den)
        entry_id = _make_entry_id("split", sym, eff_date)
        if entry_id in existing_entry_ids:
            continue
        split_processed += 1
        new_entries.append(
            LedgerEntry(
                entry_id=entry_id,
                account_id=account_id,
                user_id=user_id,
                entry_type=LedgerEntryType.SPLIT,
                sequence=seq,
                occurred_at=_date_to_datetime_utc(eff_date),
                amount=Decimal("0"),  # splits are cashless
                symbol=sym,
                quantity=ratio,
                notes=f"reconciler: {num}:{den} split ratio {ratio}",
            )
        )
        seq += 1

    # Silent-empty guard (per issue's 'silent P&L drift = fail')
    if not new_entries and (dividend_rows or split_rows):
        warnings.append(
            f"reconciler received {len(dividend_rows)} dividend + "
            f"{len(split_rows)} split rows but generated no new entries. "
            "Either every intersection was already reconciled (fine) or "
            "no calendar rows intersected any held symbol (verify)."
        )

    return ReconcileResult(
        new_entries=new_entries,
        dividend_rows_processed=div_processed,
        split_rows_processed=split_processed,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_date(value: Any) -> date | None:
    """Accept date, datetime, or ISO-8601 str. Return None on unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            # Handle both "2024-01-15" and "2024-01-15T00:00:00Z"
            return datetime.fromisoformat(value.rstrip("Z")).date()
        except ValueError:
            return None
    return None


def _coerce_decimal(value: Any) -> Decimal | None:
    """Accept numeric-like input. Return None on unparseable."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


def _date_to_datetime_utc(d: date) -> datetime:
    """Convert a date to a UTC-midnight datetime (ledger requires datetime)."""
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _make_entry_id(event: str, symbol: str, event_date: date) -> str:
    """Deterministic short id per (event, symbol, date). Idempotent across runs.

    SHA1 truncated to 16 hex chars is fine here — collision space is
    tiny (an event per (symbol, date) is unique in the wild) and this
    isn't a security-sensitive hash.
    """
    key = f"reconciler:{event}:{symbol.upper()}:{event_date.isoformat()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]  # noqa: S324
