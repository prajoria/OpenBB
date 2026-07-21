"""Brinson-Fachler single-period reference oracle (#935).

Trusted-by-construction implementation of the single-period BF
decomposition. Kept as a *literal transcription* of the textbook
formulas — never "optimized" — so it stays obviously-correct-by-inspection
and can serve as ground truth for #559's implementation.

Single-period BF decomposes active return ``R_p - R_b`` into three
additive effects per group (sector, country, factor, ...):

    allocation_i  = (w_p_i - w_b_i) * (r_b_i - R_b)
    selection_i   =  w_b_i          * (r_p_i - r_b_i)
    interaction_i = (w_p_i - w_b_i) * (r_p_i - r_b_i)

where per group ``i``:
- ``w_p_i`` / ``w_b_i`` are portfolio / benchmark weights (sum to 1)
- ``r_p_i`` / ``r_b_i`` are portfolio / benchmark returns
- ``R_p`` = sum(w_p * r_p), ``R_b`` = sum(w_b * r_b)

The invariant ``sum(alloc + selc + inter) == R_p - R_b`` holds
exactly (float error only) and is asserted below as a self-check.

This is the **Brinson-Fachler** variant: allocation uses the
benchmark-relative ``(r_b - R_b)``, distinct from Brinson-Hood-Beebour
which uses plain ``r_b``. Do not "simplify" one into the other.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Textbook invariant tolerance — float error only, not a modeling threshold.
_INVARIANT_ATOL = 1e-9


@dataclass(frozen=True)
class BrinsonEffects:
    """Single-period BF effects, aggregated across all groups.

    ``allocation + selection + interaction == active_return`` up to
    float tolerance (:data:`_INVARIANT_ATOL` = 1e-9).
    """

    active_return: float
    allocation: float
    selection: float
    interaction: float

    def as_dict(self) -> dict[str, float]:
        """Return the four fields as a plain dict (fixture-friendly)."""
        return {
            "active_return": self.active_return,
            "allocation": self.allocation,
            "selection": self.selection,
            "interaction": self.interaction,
        }


def brinson_reference(df: pd.DataFrame) -> BrinsonEffects:
    """Trusted single-period Brinson-Fachler oracle.

    Parameters
    ----------
    df
        DataFrame with columns ``w_p``, ``w_b``, ``r_p``, ``r_b`` (one
        row per group). Weight columns MUST each sum to 1.0 within
        1e-12; violating this yields a ``ValueError`` (silent
        renormalization would mask upstream bugs).

    Returns
    -------
    BrinsonEffects
        Aggregate allocation / selection / interaction, plus
        ``active_return = R_p - R_b``. Guaranteed to satisfy the sum
        invariant to :data:`_INVARIANT_ATOL`.

    Raises
    ------
    ValueError
        If ``df`` lacks the required columns, if weight columns don't
        sum to 1.0, or if the sum invariant is violated (indicates a
        bug in the oracle itself — never fires under normal input).
    """
    required = {"w_p", "w_b", "r_p", "r_b"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"brinson_reference: DataFrame missing required columns: {sorted(missing)}"
        )
    if df.empty:
        raise ValueError(
            "brinson_reference: DataFrame is empty; need at least one group"
        )

    w_p_sum = float(df["w_p"].sum())
    w_b_sum = float(df["w_b"].sum())
    if not np.isclose(w_p_sum, 1.0, atol=1e-12):
        raise ValueError(
            f"brinson_reference: portfolio weights sum to {w_p_sum}, not 1.0"
        )
    if not np.isclose(w_b_sum, 1.0, atol=1e-12):
        raise ValueError(
            f"brinson_reference: benchmark weights sum to {w_b_sum}, not 1.0"
        )

    r_p_total = float((df["w_p"] * df["r_p"]).sum())
    r_b_total = float((df["w_b"] * df["r_b"]).sum())
    active = r_p_total - r_b_total

    # Per-group vectors (kept explicit so the formulas match the docstring)
    delta_w = df["w_p"] - df["w_b"]
    excess_b = df["r_b"] - r_b_total
    diff_r = df["r_p"] - df["r_b"]

    allocation = float((delta_w * excess_b).sum())
    selection = float((df["w_b"] * diff_r).sum())
    interaction = float((delta_w * diff_r).sum())

    # Self-check — never fires unless the formulas above are edited
    # incorrectly. Fires LOUD instead of silently returning wrong data.
    total = allocation + selection + interaction
    if not np.isclose(total, active, atol=_INVARIANT_ATOL):
        raise ValueError(
            "brinson_reference: sum invariant violated: "
            f"allocation+selection+interaction={total} != active_return={active} "
            f"(delta={total - active}); this is an oracle bug, not a data bug"
        )

    return BrinsonEffects(
        active_return=active,
        allocation=allocation,
        selection=selection,
        interaction=interaction,
    )
