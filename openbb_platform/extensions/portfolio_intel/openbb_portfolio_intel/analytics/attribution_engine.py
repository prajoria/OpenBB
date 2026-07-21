"""Brinson-Fachler attribution engine (#559).

Pure function that takes per-group weights + returns and produces a
``AttributionWaterfall`` (response shape from ``attribution.py``, #560).

Contract with #935:
- Consumes the same 4-column ``(w_p, w_b, r_p, r_b)`` shape the
  ``brinson.oracle`` produces + validates.
- Must match the golden JSON fixtures at ``analytics/brinson/fixtures/``
  to ±1bp per effect (issue's stated acceptance criterion).

Design:
- **Pure function**, no I/O. Caller assembles the group-level weights +
  returns from provider data (index-constituent history via #543, held
  positions via ``PositionStore``) and hands them in.
- **Per-group emission.** Every group produces one ``AttributionRow`` —
  the widget renders one bar per group. Aggregates + invariant checks
  are re-computed here (never trust upstream aggregates).
- **BF variant only.** Allocation uses ``(r_b_i - R_b)``, matching the
  #935 oracle. Plain-Brinson callers who want ``(r_b_i)`` need a
  separate function; do not add a mode flag (silent-swap risk).
- **Interaction folded separately.** The classic BF split emits three
  effects per group; ``AttributionRow.interaction`` carries the third
  so plain-Brinson consumers who set it to 0 still satisfy the
  aggregate invariant.

Silent-failure guards:
- Weights that don't sum to 1 → ``ValueError`` (same rule the oracle
  enforces). Silent renormalization would mask upstream bugs.
- Empty input → ``ValueError`` (no attribution to compute).
- Non-finite (NaN / Inf) returns → ``ValueError`` (would silently
  corrupt the aggregate; propagating NaN through Σ is exactly the
  "silent P&L drift" failure mode #558 hardened against).
- **Post-hoc invariant check.** The engine calls
  ``verify_sums_to_active_return`` on its own output before returning
  — catches implementation drift the moment it appears.

The ``build_from_dataframe`` variant accepts a plain pandas DataFrame
in the #935 fixture shape (``group, w_p, w_b, r_p, r_b``) so the
attribution engine can be run directly against every golden fixture in
CI. That's the primary correctness gate.
"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from openbb_portfolio_intel.analytics.attribution import (
    AttributionRow,
    AttributionWaterfall,
    verify_sums_to_active_return,
)

if TYPE_CHECKING:
    import pandas as pd


# Reject weight-sum drift larger than this. Same tolerance the oracle
# uses in #935 — keep them in sync so the two agree on what "valid"
# means.
_WEIGHT_SUM_TOL = 1e-12


def build_from_arrays(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    groups: list[str],
    w_p: list[float],
    w_b: list[float],
    r_p: list[float],
    r_b: list[float],
    *,
    window: str,
    benchmark_symbol: str,
) -> AttributionWaterfall:
    """Compute the full BF attribution waterfall from raw arrays.

    Parameters
    ----------
    groups
        Group labels (sectors / countries / factors). Length N.
    w_p, w_b
        Portfolio and benchmark weights per group. Each MUST sum to 1
        within :data:`_WEIGHT_SUM_TOL`. Length N.
    r_p, r_b
        Portfolio and benchmark returns per group (decimal, not %).
        Length N. Must be finite.
    window
        Free-form window label (e.g. ``"1M"``, ``"3M"``, ``"6M"``,
        ``"1Y"``). Copied verbatim into the response.
    benchmark_symbol
        Benchmark ticker (``"SPY"``, ``"ACWI"``, ...). Copied verbatim.

    Returns
    -------
    AttributionWaterfall
        One row per group with allocation / selection / interaction;
        aggregate totals + ``portfolio_return`` / ``benchmark_return``
        computed from the inputs. Sum invariant self-checked before
        returning.

    Raises
    ------
    ValueError
        If length mismatch, empty input, unnormalized weights, or any
        non-finite return. Never returns a silently-drifted waterfall.
    """
    n = len(groups)
    if n == 0:
        raise ValueError(
            "attribution engine: no groups; nothing to attribute. "
            "Empty input is a caller bug — the router should skip "
            "the call entirely."
        )
    if len(w_p) != n or len(w_b) != n or len(r_p) != n or len(r_b) != n:
        raise ValueError(
            "attribution engine: length mismatch — "
            f"groups={n}, w_p={len(w_p)}, w_b={len(w_b)}, "
            f"r_p={len(r_p)}, r_b={len(r_b)}"
        )

    w_p_sum = sum(w_p)
    w_b_sum = sum(w_b)
    if abs(w_p_sum - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"attribution engine: portfolio weights sum to {w_p_sum}, not 1.0"
        )
    if abs(w_b_sum - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"attribution engine: benchmark weights sum to {w_b_sum}, not 1.0"
        )

    # Reject non-finite before the aggregate — one NaN silently corrupts Σ.
    for i, (rp_i, rb_i) in enumerate(zip(r_p, r_b)):
        if not isfinite(rp_i) or not isfinite(rb_i):
            raise ValueError(
                f"attribution engine: non-finite return at group[{i}] "
                f"({groups[i]!r}): r_p={rp_i}, r_b={rb_i}. "
                "NaN/Inf in returns would silently corrupt the waterfall."
            )

    # Aggregate returns
    r_p_total = sum(wp * rp for wp, rp in zip(w_p, r_p))
    r_b_total = sum(wb * rb for wb, rb in zip(w_b, r_b))

    # Per-group BF effects — literal transcription, matches oracle.
    rows: list[AttributionRow] = []
    tot_alloc = 0.0
    tot_sel = 0.0
    tot_inter = 0.0
    for group, wp, wb, rp, rb in zip(groups, w_p, w_b, r_p, r_b):
        delta_w = wp - wb
        alloc = delta_w * (rb - r_b_total)
        sel = wb * (rp - rb)
        inter = delta_w * (rp - rb)
        rows.append(
            AttributionRow(
                sector=group,
                allocation=alloc,
                selection=sel,
                interaction=inter,
            )
        )
        tot_alloc += alloc
        tot_sel += sel
        tot_inter += inter

    waterfall = AttributionWaterfall(
        window=window,
        benchmark_symbol=benchmark_symbol,
        portfolio_return=r_p_total,
        benchmark_return=r_b_total,
        rows=rows,
        total_allocation=tot_alloc,
        total_selection=tot_sel,
        total_interaction=tot_inter,
    )

    # Post-hoc self-check — never ship a drifted waterfall. Raises on
    # any drift > SUM_INVARIANT_TOLERANCE (1e-9), which is safely below
    # the 1bp reporting granularity the widget consumes.
    verify_sums_to_active_return(waterfall)

    return waterfall


def build_from_dataframe(
    df: pd.DataFrame,
    *,
    window: str,
    benchmark_symbol: str,
) -> AttributionWaterfall:
    """Build a waterfall from a #935-shaped DataFrame (convenience wrapper).

    Expects columns ``group, w_p, w_b, r_p, r_b``. This is exactly the
    shape produced by ``brinson.generator.make_case()`` and consumed by
    ``brinson.oracle.brinson_reference()``, so the engine can be
    exercised against every committed golden fixture with one line.

    Any missing column raises ``ValueError`` — no silent NaN fill.
    """
    required = {"group", "w_p", "w_b", "r_p", "r_b"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"attribution engine: DataFrame missing required columns: {sorted(missing)}"
        )
    return build_from_arrays(
        groups=df["group"].tolist(),
        w_p=df["w_p"].tolist(),
        w_b=df["w_b"].tolist(),
        r_p=df["r_p"].tolist(),
        r_b=df["r_b"].tolist(),
        window=window,
        benchmark_symbol=benchmark_symbol,
    )
