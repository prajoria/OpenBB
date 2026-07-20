"""Attribution waterfall response shape (#560).

The Brinson (or Brinson-Fachler) attribution decomposition splits the
active return between a portfolio and its benchmark into per-sector
contributions along two orthogonal axes:

- **Allocation**: over- or under-weighting a sector vs the benchmark.
  If Tech outperforms the benchmark overall and I hold 30% Tech vs a
  20% benchmark weight, my allocation effect on Tech is positive.
- **Selection**: picking better- or worse-than-benchmark names WITHIN
  each sector. If I hold Tech names that beat the Tech sector's
  benchmark return, my selection effect on Tech is positive.

Sum of (allocation + selection) across all sectors ≡ total active return
(``portfolio_return - benchmark_return``). Small residual (< 1e-9) is
expected from float arithmetic; anything larger is an implementation bug.

This module ships the RESPONSE SHAPE only — the Brinson-Fachler math
lands separately in ``analytics.attribution`` (#559) and is out of
scope for this PR (blocked by #543 index-constituent history + #557
Bloomberg reference fixtures). The shape lives independently so that
routers, widgets, and the eventual math can all wire against a stable
contract from day one.

Design decisions:

1. **Sector-flat.** One ``AttributionRow`` per sector with both effects
   as scalar fields. Flat > nested for widget rendering (no per-sector
   dict traversal).
2. **Widget-optimized order.** The waterfall widget renders bars
   left-to-right; the natural order is: benchmark_return start →
   allocation stack → selection stack → interaction (if any) → total
   active return end. The dataclass order matches this.
3. **``interaction`` is optional.** Classic Brinson-Fachler folds
   interaction (residual from non-additive effects) into ``selection``.
   Some implementations report it separately as a third bar. Keep the
   field but default to ``0.0`` — a caller producing plain Brinson
   just leaves it zero and the sum invariant still holds.
4. **All floats.** Active-return is a diffed-percentage-return; there
   is no ``Decimal`` monetary quantity here. Matches ``WhatIfDiff``
   convention (#558 finding 9.5).
5. **Reciprocal validation.** ``verify_sums_to_active_return`` is
   exposed as a public helper — the router will call it before
   returning; tests call it as a property invariant. This is the
   load-bearing contract of the shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

# Tolerance for the sum-to-active-return invariant. Wider than typical
# float epsilon because per-sector contributions can be O(1e-3) and the
# reduction may accumulate ~N ulps of error. 1e-9 is comfortably below
# the "1 basis point" reporting granularity of the widget.
SUM_INVARIANT_TOLERANCE: float = 1e-9


@dataclass(frozen=True)
class AttributionRow:
    """One row in the attribution waterfall — a single sector.

    Sector-scoped. The two effects each carry the sign convention that
    positive = portfolio beat benchmark on this dimension:

    - ``allocation > 0``: the portfolio overweighted a sector whose
      benchmark return exceeded the total benchmark return (or
      underweighted a sector whose return was below). Either way, the
      allocation call was value-additive.
    - ``selection > 0``: within this sector, the portfolio's holdings
      returned more than the benchmark's holdings in the same sector.
    - ``interaction``: residual from non-additive effects (optional;
      defaults to 0.0 for plain Brinson).

    Sector-level total = ``allocation + selection + interaction``.
    """

    sector: str
    allocation: float
    selection: float
    interaction: float = 0.0

    def total(self) -> float:
        """Return the combined effect for this sector."""
        return self.allocation + self.selection + self.interaction


@dataclass(frozen=True)
class AttributionWaterfall:
    """The full waterfall response for one (portfolio, benchmark, window).

    Field order matches the widget's left-to-right rendering:

        benchmark_return  →  Σ allocation  →  Σ selection  →
        (Σ interaction)   →  portfolio_return

    Invariant (verified by :func:`verify_sums_to_active_return`):

        Σ row.total() == portfolio_return - benchmark_return   (±SUM_INVARIANT_TOLERANCE)

    Producers that only implement plain Brinson leave every
    ``row.interaction`` at 0.0 and the invariant still holds by
    construction.
    """

    # --- Window + book identity -------------------------------------
    window: str  # e.g. "1M", "3M", "6M", "1Y" — free-form; router owns the vocab
    benchmark_symbol: str  # e.g. "SPY", "ACWI"

    # --- Reference returns -------------------------------------------
    portfolio_return: float
    benchmark_return: float

    # --- The waterfall -----------------------------------------------
    rows: list[AttributionRow] = field(default_factory=list)

    # --- Convenience aggregates (populated by producer, verified by helper) ---
    total_allocation: float = 0.0
    total_selection: float = 0.0
    total_interaction: float = 0.0

    # --- Diagnostics + provenance ------------------------------------
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Property-check helpers
# ---------------------------------------------------------------------------


def active_return(w: AttributionWaterfall) -> float:
    """Return the active return: ``portfolio_return - benchmark_return``."""
    return w.portfolio_return - w.benchmark_return


def verify_sums_to_active_return(
    w: AttributionWaterfall, tolerance: float = SUM_INVARIANT_TOLERANCE
) -> None:
    """Raise ``ValueError`` if the waterfall doesn't sum to active return.

    Load-bearing contract test — the router calls this before returning
    to enforce the invariant. Callers who trust their producer can skip;
    downstream widgets rely on it holding.

    Parameters
    ----------
    tolerance
        Allowed absolute drift between ``Σ row.total()`` and
        ``portfolio_return - benchmark_return``. Defaults to
        ``SUM_INVARIANT_TOLERANCE`` (1e-9), several orders of magnitude
        below the 1-basis-point reporting granularity.

    Raises
    ------
    ValueError
        If the sum drifts by more than ``tolerance``.
    """
    if not isfinite(w.portfolio_return) or not isfinite(w.benchmark_return):
        raise ValueError(
            "portfolio_return / benchmark_return must be finite; "
            f"got portfolio={w.portfolio_return}, benchmark={w.benchmark_return}"
        )
    row_sum = 0.0
    for row in w.rows:
        for value in (row.allocation, row.selection, row.interaction):
            if not isfinite(value):
                raise ValueError(
                    f"{row.sector}: attribution values must be finite; got "
                    f"allocation={row.allocation}, selection={row.selection}, "
                    f"interaction={row.interaction}"
                )
        row_sum += row.total()
    target = active_return(w)
    drift = abs(row_sum - target)
    if drift > tolerance:
        raise ValueError(
            f"waterfall does not sum to active return: "
            f"Σ row.total() = {row_sum}, active_return = {target}, "
            f"drift = {drift} (tolerance = {tolerance}). "
            "This is the load-bearing invariant of the shape (#560)."
        )


def verify_aggregates_match_rows(
    w: AttributionWaterfall, tolerance: float = SUM_INVARIANT_TOLERANCE
) -> None:
    """Raise ``ValueError`` if aggregate fields don't equal per-row sums.

    Verifies:
      - ``w.total_allocation == Σ row.allocation``
      - ``w.total_selection == Σ row.selection``
      - ``w.total_interaction == Σ row.interaction``

    All three within ``tolerance``. Producers set the aggregates
    explicitly (to avoid re-summing at the widget layer); this helper
    catches producer bugs that would leave them stale.
    """
    alloc = sum(r.allocation for r in w.rows)
    sel = sum(r.selection for r in w.rows)
    inter = sum(r.interaction for r in w.rows)
    for name, computed, stored in (
        ("total_allocation", alloc, w.total_allocation),
        ("total_selection", sel, w.total_selection),
        ("total_interaction", inter, w.total_interaction),
    ):
        if abs(computed - stored) > tolerance:
            raise ValueError(
                f"{name} = {stored} does not match Σ row = {computed} "
                f"(drift {abs(computed - stored)}, tolerance {tolerance})"
            )
