"""T5 P3.c — reconciliation vs. Fidelity real positions (#1719).

The operator files orders manually at Fidelity, records the fills back
in the :class:`SqlitePaperEngine` shadow ledger, and periodically imports
Fidelity's Positions download into MySQL via #1744. This module diffs
the two views:

- **paper** — what :meth:`PaperEngine.get_positions` says we should hold
- **real** — what Fidelity's Positions CSV says we actually hold

Any variance is either (a) a missed manual fill (paper says we bought
X, real doesn't have it — the operator forgot to file the order at
Fidelity), or (b) a missed :meth:`record_fill` call (real has X, paper
doesn't — the operator filed at Fidelity but forgot to record it back).

Both directions of drift are real-money bugs. This module surfaces
them as a :class:`ReconciliationReport` — READ-ONLY, no silent
corrections. The operator decides what to do with each variance row.

Non-goals
---------
- Does NOT auto-fix drift. Report only.
- Does NOT reconcile cash. Cash lives in SPAXX/FCASH-style money-market
  positions on Fidelity; whether we treat those as "cash" or as
  positions is a downstream policy choice.
- Does NOT walk the fill log to explain WHY variance exists — that's a
  separate audit tool.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbb_techtrade.execution.paper_engine import PaperEngine

logger = logging.getLogger(__name__)


class VarianceKind(str, Enum):
    """Category of variance between paper and real positions."""

    MATCHED = "MATCHED"  # same qty on both sides (may still surface for audit)
    QTY_VARIANCE = "QTY_VARIANCE"  # both have it, different quantity
    PAPER_ONLY = "PAPER_ONLY"  # paper says we hold it, real doesn't
    FIDELITY_ONLY = "FIDELITY_ONLY"  # real has it, paper doesn't


@dataclass(frozen=True)
class VarianceRow:
    """One symbol's reconciliation row.

    ``paper_qty`` and ``real_qty`` are ``None`` on the side that didn't
    have the symbol at all — so a PAPER_ONLY row has ``real_qty=None``
    and a FIDELITY_ONLY row has ``paper_qty=None``.
    """

    symbol: str
    paper_qty: Decimal | None
    real_qty: Decimal | None
    delta: Decimal | None  # real - paper (None when either side is None)
    kind: VarianceKind


@dataclass(frozen=True)
class ReconciliationReport:
    """Full reconciliation output.

    Rows are grouped by :class:`VarianceKind`. The ``variance_count``
    property is the number of NON-matched rows — the operator's todo list.
    """

    rows: tuple[VarianceRow, ...]
    paper_symbol_count: int
    real_symbol_count: int

    @property
    def matched(self) -> tuple[VarianceRow, ...]:
        """Rows where paper and real agree on quantity."""
        return tuple(r for r in self.rows if r.kind == VarianceKind.MATCHED)

    @property
    def qty_variance(self) -> tuple[VarianceRow, ...]:
        """Rows where both sides have the symbol but quantities differ."""
        return tuple(r for r in self.rows if r.kind == VarianceKind.QTY_VARIANCE)

    @property
    def paper_only(self) -> tuple[VarianceRow, ...]:
        """Symbols paper thinks we hold but Fidelity doesn't confirm."""
        return tuple(r for r in self.rows if r.kind == VarianceKind.PAPER_ONLY)

    @property
    def fidelity_only(self) -> tuple[VarianceRow, ...]:
        """Symbols Fidelity has that paper doesn't know about."""
        return tuple(r for r in self.rows if r.kind == VarianceKind.FIDELITY_ONLY)

    @property
    def variance_count(self) -> int:
        """Total non-matched rows — the operator's action list length."""
        return sum(1 for r in self.rows if r.kind != VarianceKind.MATCHED)

    @property
    def is_reconciled(self) -> bool:
        """True iff paper and real fully agree on every symbol + quantity."""
        return self.variance_count == 0


def reconcile(
    paper: PaperEngine,
    real_positions: Mapping[str, Decimal],
) -> ReconciliationReport:
    """Diff paper positions against Fidelity real positions.

    ``real_positions`` maps symbol → quantity as reported by Fidelity's
    Positions download (parsed by
    :mod:`portfolio_snapshot_importer.ingest` and stored via
    :class:`MySqlPortfolioStore`). Zero-quantity symbols in either
    source are filtered out — a position that flattened to zero on
    both sides is not a variance.

    Symbols are case-normalized (upper-case) before comparison so
    ``MSFT`` and ``msft`` match.

    Decimal semantics: comparison uses :class:`decimal.Decimal`
    equality, so ``10.0 == 10.000`` — no float-precision surprises.
    """
    paper_pos_by_sym: dict[str, Decimal] = {
        p.symbol.upper(): p.quantity for p in paper.get_positions() if p.quantity != 0
    }
    real_by_sym: dict[str, Decimal] = {
        sym.upper(): qty for sym, qty in real_positions.items() if qty != 0
    }

    all_symbols = sorted(set(paper_pos_by_sym) | set(real_by_sym))
    rows: list[VarianceRow] = []
    for sym in all_symbols:
        paper_qty = paper_pos_by_sym.get(sym)
        real_qty = real_by_sym.get(sym)

        if paper_qty is not None and real_qty is not None:
            if paper_qty == real_qty:
                kind = VarianceKind.MATCHED
                delta = Decimal("0")
            else:
                kind = VarianceKind.QTY_VARIANCE
                delta = real_qty - paper_qty
        elif paper_qty is not None:
            kind = VarianceKind.PAPER_ONLY
            delta = None
        else:
            # real_qty is not None; paper doesn't have it
            kind = VarianceKind.FIDELITY_ONLY
            delta = None

        rows.append(
            VarianceRow(
                symbol=sym,
                paper_qty=paper_qty,
                real_qty=real_qty,
                delta=delta,
                kind=kind,
            )
        )

    report = ReconciliationReport(
        rows=tuple(rows),
        paper_symbol_count=len(paper_pos_by_sym),
        real_symbol_count=len(real_by_sym),
    )
    if report.variance_count > 0:
        logger.info(
            "reconcile: %d variance row(s) across %d symbols (paper=%d real=%d)",
            report.variance_count,
            len(all_symbols),
            report.paper_symbol_count,
            report.real_symbol_count,
        )
    return report


def reconcile_from_snapshot(
    paper: PaperEngine,
    snapshot_positions: Mapping[str, Decimal] | None,
    user_id: str = "",
) -> ReconciliationReport:
    """Reconcile paper positions against a possibly-missing snapshot dict.

    ``snapshot_positions=None`` means the caller couldn't fetch a
    Fidelity snapshot at all (e.g., MySQL unreachable). We raise
    loudly rather than silently succeed with a "reconciled" report —
    a missing snapshot is NOT the same as an empty snapshot.

    In real usage the caller passes
    ``MySqlPortfolioStore.latest_snapshot(user_id)`` result normalized
    to a ``{symbol: quantity}`` dict; this stub keeps the module
    independent of #1744.
    """
    if snapshot_positions is None:
        raise ValueError(
            f"reconcile_from_snapshot: no Fidelity snapshot for "
            f"user_id={user_id!r}. Import a Positions CSV first "
            "(see docs/superpowers/specs/2026-08-03-fidelity-positions-"
            "csv-schema.md) or pass an empty dict if you truly want to "
            "diff against 'no real positions'."
        )
    return reconcile(paper, snapshot_positions)
