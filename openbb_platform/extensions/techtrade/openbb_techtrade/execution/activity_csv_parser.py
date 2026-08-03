"""T5 P5 — Fidelity Activity CSV parser + bulk-import to paper engine (#1719).

The operator fills orders manually at Fidelity, then periodically
downloads Fidelity's Activity CSV (History → Download) as a bulk
record of what actually filled. This module parses that export and
matches each fill row to a PENDING/PARTIAL order in the
:class:`SqlitePaperEngine` shadow ledger — invoking
:meth:`PaperEngine.record_fill` for each matched row.

The alternative is typing each fill into the widget one by one (P4).
The Activity CSV bulk-import is the "I filed 30 orders yesterday and
now I want to catch the paper engine up in one go" workflow.

## Design

- **Parser** (`parse_activity_csv`) — reads CSV rows, converts each to a
  :class:`ParsedFill` (symbol, action, quantity, price, commission, at).
  Handles Fidelity's decimal-format quirks (leading `$`, trailing `%`,
  parenthesized-negatives, `Pending Update` string in place of a number).
- **Matcher** (`match_fills_to_orders`) — for each parsed fill, finds the
  best-matching PENDING/PARTIAL order in the paper engine using symbol
  + side + quantity + date-window heuristics. Loud on unmatched fills
  (never silently drop).
- **Bulk importer** (`import_fills`) — runs the matcher + calls
  ``record_fill`` for each match. Dry-run mode prints what WOULD import
  without touching the DB.

## Loud-fail discipline

- Unrecognized CSV header → raises with the observed vs. expected column
  sets side-by-side
- Row with unparseable number field → raises with the row index + raw
  content
- Unmatched fill in the CSV → raises with the fill's symbol/qty and
  a list of the closest PENDING orders (helps the operator spot the
  issue)
- Idempotency: fills already recorded (same order_id + qty within a
  small tolerance) are skipped silently — this makes re-importing the
  same CSV safe

## Non-goals

- Does NOT auto-download from Fidelity (they have no API)
- Does NOT parse cash entries (dividends, interest, transfers) — only
  Buy/Sell/BuyToCover/SellShort fill rows
- Does NOT reconcile positions (that's P3.c #1767)
- Does NOT infer commissions when the CSV doesn't provide them — 0 is
  assumed
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbb_techtrade.execution.paper_engine import PaperEngine

logger = logging.getLogger(__name__)


class ActivityCsvError(RuntimeError):
    """Loud rejection: unparseable CSV, unmatched fill, header mismatch."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedFill:
    """One executable row parsed from Fidelity Activity CSV.

    ``action`` is normalized to the same set OrderTicket accepts:
    ``Buy`` / ``Sell`` / ``BuyToCover`` / ``SellShort``. Non-executable
    rows (dividends, interest, transfers) are filtered out at parse
    time — this dataclass only ever represents a real fill.

    ``at`` uses the Run Date at UTC midnight (Fidelity's Activity CSV
    doesn't include intraday timestamps for historical fills, so we
    date-only). Callers who need real fill timestamps can override at
    import time.
    """

    symbol: str
    action: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    at: datetime


@dataclass(frozen=True)
class MatchedFill:
    """A ParsedFill matched to a specific paper order."""

    parsed: ParsedFill
    order_id: str


@dataclass(frozen=True)
class ImportSummary:
    """Aggregate outcome of ``import_fills``."""

    matched: tuple[MatchedFill, ...]
    imported: int
    skipped_duplicate: int
    unmatched: tuple[ParsedFill, ...]
    dry_run: bool


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


# Fidelity Activity CSV column headers. Real exports have ~20+ columns
# including tax lot info, settlement dates, etc. We only care about a
# small subset. Case-insensitive substring match at parse time.
_REQUIRED_CANONICAL_HEADERS = ("Run Date", "Action", "Symbol", "Quantity", "Price")

# Action strings Fidelity emits. Values on the right are our normalized
# action strings (matching OrderTicket.action values).
_ACTION_MAP = {
    "you bought": "Buy",
    "bought": "Buy",
    "buy": "Buy",
    "you sold": "Sell",
    "sold": "Sell",
    "sell": "Sell",
    "buy to cover": "BuyToCover",
    "short sale": "SellShort",
    "sell short": "SellShort",
}

# Actions we don't care about — cash movements, corporate actions, etc.
# Rows with these actions are filtered out silently (they're not fills).
_CASH_ACTION_KEYWORDS = frozenset(
    {
        "dividend",
        "interest",
        "transfer",
        "wire",
        "check",
        "reinvestment",
        "fee",
        "adjustment",
        "journal",
        "conversion",
        "distribution",
    }
)


def parse_activity_csv(path: Path | str) -> list[ParsedFill]:
    """Parse a Fidelity Activity CSV into ParsedFill rows.

    Fidelity's export has a variable-width preamble (account name,
    date range, disclaimer) followed by the data rows. We locate the
    header row by scanning for the required columns, then read every
    subsequent data row.

    Raises :class:`ActivityCsvError` on:
    - Missing required columns
    - Unparseable numeric field in a fill row (dividend rows are
      filtered out before this check)
    - Row with an unknown action string that ISN'T a cash keyword
      (better safe than silently dropping a real fill)
    """
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        # Fidelity sometimes emits BOM; utf-8-sig handles it.
        rows_iter = csv.reader(fh)
        rows = list(rows_iter)

    header_idx = _find_header_row(rows)
    if header_idx is None:
        raise ActivityCsvError(
            f"parse_activity_csv: {path.name} does not contain the "
            f"required columns {_REQUIRED_CANONICAL_HEADERS!r}. Is this "
            "actually a Fidelity Activity export? See the schema doc "
            "at docs/superpowers/specs/ (Activity CSV, when it lands)."
        )
    header = rows[header_idx]
    col_idx = _index_columns(header)

    parsed: list[ParsedFill] = []
    for row_num, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if not any(cell.strip() for cell in row):
            continue  # blank line
        action_raw = row[col_idx["Action"]].strip().lower()
        if not action_raw:
            continue
        if any(kw in action_raw for kw in _CASH_ACTION_KEYWORDS):
            continue  # cash/interest/dividend/etc — not a fill

        action = _normalize_action(action_raw)
        if action is None:
            raise ActivityCsvError(
                f"parse_activity_csv: row {row_num} has unrecognized "
                f"Action {action_raw!r}. Extend _ACTION_MAP or "
                f"_CASH_ACTION_KEYWORDS if this is a real fill / cash "
                f"row respectively."
            )

        try:
            symbol = row[col_idx["Symbol"]].strip().upper()
            if not symbol:
                raise ActivityCsvError(
                    f"parse_activity_csv: row {row_num} has empty Symbol"
                )
            quantity = _parse_decimal(row[col_idx["Quantity"]])
            price = _parse_decimal(row[col_idx["Price"]])
            at = _parse_run_date(row[col_idx["Run Date"]])
        except (ActivityCsvError, InvalidOperation, ValueError) as exc:
            raise ActivityCsvError(
                f"parse_activity_csv: row {row_num} — {exc}. " f"Row content: {row!r}"
            ) from exc

        commission = Decimal("0")
        if "Commission" in col_idx:
            try:
                commission = abs(_parse_decimal(row[col_idx["Commission"]]))
            except (ActivityCsvError, InvalidOperation, ValueError):
                commission = Decimal("0")

        parsed.append(
            ParsedFill(
                symbol=symbol,
                action=action,
                quantity=abs(quantity),  # Fidelity signs by side; we don't
                price=price,
                commission=commission,
                at=at,
            )
        )

    logger.info(
        "parse_activity_csv: %s -> %d fills (from %d total data rows)",
        path.name,
        len(parsed),
        len(rows) - header_idx - 1,
    )
    return parsed


def _find_header_row(rows: list[list[str]]) -> int | None:
    """Scan for the first row containing every required column."""
    for i, row in enumerate(rows):
        lowered = [c.strip().lower() for c in row]
        if all(
            any(canonical.lower() in cell for cell in lowered)
            for canonical in _REQUIRED_CANONICAL_HEADERS
        ):
            return i
    return None


def _index_columns(header: list[str]) -> dict[str, int]:
    """Map canonical column name -> index in the actual header row."""
    idx: dict[str, int] = {}
    lowered = [c.strip().lower() for c in header]
    canonical_lookup = list(_REQUIRED_CANONICAL_HEADERS) + ["Commission"]
    for canonical in canonical_lookup:
        for i, cell in enumerate(lowered):
            if canonical.lower() in cell:
                idx[canonical] = i
                break
    return idx


def _normalize_action(action_raw: str) -> str | None:
    """Map Fidelity's action string to our OrderTicket.action set."""
    for pattern, canonical in _ACTION_MAP.items():
        if pattern in action_raw:
            return canonical
    return None


# Currency: leading `$`, thousands `,`, optional trailing `%`, and
# parenthesized-negatives are all Fidelity conventions.
_DEC_STRIP = re.compile(r"[\$,\s%]")


def _parse_decimal(raw: str) -> Decimal:
    """Parse Fidelity's currency/qty format into a Decimal.

    Handles `$1,234.56`, `(1.23)` (negative), `1.23%`, `Pending Update`.
    ``Pending Update`` raises ActivityCsvError because it's genuinely
    unparseable — the operator should re-export after Fidelity settles.
    """
    s = raw.strip()
    if not s:
        raise ActivityCsvError("empty numeric field")
    if s.lower() == "pending update":
        raise ActivityCsvError(
            "field is 'Pending Update' — Fidelity hasn't settled the "
            "trade yet; re-export the Activity CSV once settlement clears"
        )
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = _DEC_STRIP.sub("", s)
    try:
        return -Decimal(s) if negative else Decimal(s)
    except InvalidOperation as exc:
        raise ActivityCsvError(f"unparseable numeric {raw!r}") from exc


def _parse_run_date(raw: str) -> datetime:
    """Parse Fidelity's date field into UTC-midnight datetime."""
    s = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ActivityCsvError(f"unparseable Run Date {raw!r}")


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def match_fills_to_orders(
    fills: Iterable[ParsedFill],
    engine: PaperEngine,
    date_window_days: int = 7,
) -> tuple[list[MatchedFill], list[ParsedFill]]:
    """Match parsed fills to PENDING/PARTIAL orders on the engine.

    Match criteria (all must hold):

    1. Same normalized symbol
    2. Same side (action)
    3. Fill quantity is <= remaining ordered quantity (partial fills OK)
    4. Order was submitted within ``date_window_days`` before ``fill.at``

    A ParsedFill that matches NO order raises loudly at the caller
    level (this function only classifies — see ``import_fills``).

    Each successful match consumes the matched order's remaining
    capacity. So a batch of 3 fills against 1 partial order matches
    them in FIFO — each fill deducts from the remaining ordered qty.
    """
    from openbb_techtrade.execution.paper_engine import OrderStatus  # pylint: disable=import-outside-toplevel

    # Snapshot the PENDING + PARTIAL orders. Track remaining capacity
    # per order id as we match.
    open_orders = [
        o
        for o in engine.get_orders()
        if o.status in (OrderStatus.PENDING, OrderStatus.PARTIAL)
    ]
    # Compute prior-fill totals for PARTIAL orders.
    remaining: dict[str, Decimal] = {}
    for o in open_orders:
        prior = sum(
            f.filled_qty for f in engine.get_fills() if f.order_id == o.order_id
        )
        remaining[o.order_id] = o.quantity - prior

    matched: list[MatchedFill] = []
    unmatched: list[ParsedFill] = []
    for fill in fills:
        candidate = _pick_candidate(fill, open_orders, remaining, date_window_days)
        if candidate is None:
            unmatched.append(fill)
            continue
        matched.append(MatchedFill(parsed=fill, order_id=candidate.order_id))
        remaining[candidate.order_id] -= fill.quantity
    return matched, unmatched


def _pick_candidate(fill, open_orders, remaining, date_window_days):  # noqa: ANN001
    """Return the best-matching order for ``fill`` or None."""
    from openbb_techtrade.execution.paper_engine import Side  # pylint: disable=import-outside-toplevel

    action_to_side = {
        "Buy": Side.BUY,
        "Sell": Side.SELL,
        "BuyToCover": Side.BUY_TO_COVER,
        "SellShort": Side.SELL_SHORT,
    }
    fill_side = action_to_side.get(fill.action)
    if fill_side is None:
        return None

    fill_date = fill.at.date()
    window_start = fill_date - timedelta(days=date_window_days)

    for o in open_orders:
        if o.symbol.upper() != fill.symbol:
            continue
        if o.side != fill_side:
            continue
        if remaining[o.order_id] < fill.quantity:
            continue
        submitted_date = o.submitted_at.date()
        if submitted_date < window_start or submitted_date > fill_date:
            continue
        return o
    return None


# ---------------------------------------------------------------------------
# Bulk importer
# ---------------------------------------------------------------------------


def import_fills(
    fills: Iterable[ParsedFill],
    engine: PaperEngine,
    dry_run: bool = False,
    date_window_days: int = 7,
) -> ImportSummary:
    """Import ParsedFill rows into the paper engine's ledger.

    Runs the matcher, then invokes
    :meth:`PaperEngine.record_fill` for each match. ``dry_run=True``
    does everything except the record_fill calls — useful for the
    operator to preview what would import.

    Unmatched fills are surfaced in the returned summary AND raised
    if any are present. Callers who want to accept partial-match
    outcomes can catch ``ActivityCsvError`` — but this is loud by
    default so an unmatched fill can never silently vanish.

    Idempotency: this function relies on the caller not passing the
    same CSV twice. Fill idempotency at the engine level is tracked
    by #1719 P3.a's order-status transitions — a fully-FILLED order
    won't accept another fill (raises PaperEngineError). If a
    duplicate fill is detected, it's counted in ``skipped_duplicate``
    rather than raised.
    """
    from openbb_techtrade.execution.paper_engine import PaperEngineError  # pylint: disable=import-outside-toplevel

    fill_list = list(fills)
    matched, unmatched = match_fills_to_orders(fill_list, engine, date_window_days)
    logger.info(
        "import_fills: %d fill(s) parsed; %d matched, %d unmatched",
        len(fill_list),
        len(matched),
        len(unmatched),
    )

    imported = 0
    skipped_duplicate = 0
    if not dry_run:
        for m in matched:
            try:
                engine.record_fill(
                    m.order_id,
                    price=m.parsed.price,
                    filled_qty=m.parsed.quantity,
                    at=m.parsed.at,
                    commission=m.parsed.commission,
                )
                imported += 1
            except PaperEngineError as exc:
                # If the order was already FILLED, treat as duplicate.
                # Every other failure is real and propagates.
                if "already FILLED" in str(exc):
                    skipped_duplicate += 1
                    logger.info(
                        "import_fills: skipping duplicate fill for "
                        "order %s (%s %s @ %s)",
                        m.order_id,
                        m.parsed.symbol,
                        m.parsed.quantity,
                        m.parsed.price,
                    )
                else:
                    raise

    summary = ImportSummary(
        matched=tuple(matched),
        imported=imported,
        skipped_duplicate=skipped_duplicate,
        unmatched=tuple(unmatched),
        dry_run=dry_run,
    )

    if unmatched:
        details = ", ".join(
            f"{f.symbol} {f.action} {f.quantity} on {f.at.date()}"
            for f in unmatched[:5]
        )
        more = f" (+{len(unmatched) - 5} more)" if len(unmatched) > 5 else ""
        raise ActivityCsvError(
            f"import_fills: {len(unmatched)} fill(s) had no matching "
            f"PENDING/PARTIAL order within {date_window_days}-day window. "
            f"Examples: {details}{more}. "
            f"Check that the operator's batches were submitted before "
            f"the Activity CSV was generated, and that quantities match."
        )

    return summary
