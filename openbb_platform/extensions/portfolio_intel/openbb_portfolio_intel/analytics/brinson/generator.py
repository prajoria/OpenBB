"""Brinson-Fachler deterministic test-case generator (#935).

Produces valid random portfolio/benchmark books (weights that sum to 1
by construction, via Dirichlet draws) plus flag-driven edge cases where
BF implementations historically break:

- zero portfolio weight in a group (``w_p_i = 0``) — "I own none of it"
- off-benchmark holding (``w_b_i = 0``) — group present in book, absent
  from benchmark; selection term vanishes so ALL active return in that
  group must land in allocation
- identical portfolio == benchmark → all three effects exactly 0

Every case is a *pure function* of ``(n_groups, seed, flags)``, so the
same input yields byte-stable output across machines and CI runs.

Notes on the design:

- **Dirichlet, not uniform.** Uniform random floats normalized to sum
  to 1 have skewed marginals. Dirichlet(alpha=1) gives a uniform
  simplex — the natural distribution for "random valid weight vector".
- **Signed returns.** Normal draws with modest volatility (portfolio
  ~8%, benchmark ~6%). Returns are unbounded on purpose — the oracle
  and implementation must handle negative returns without special
  cases.
- **No coupling to #559.** The generator emits a plain DataFrame; the
  fixture format (:mod:`.fixtures`) is the API contract with the
  attribution engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BrinsonCase:
    """One generated test case + the parameters that produced it.

    The ``df`` is what the oracle and the attribution engine consume;
    ``case_id`` is a stable string for fixture-file naming.
    """

    case_id: str
    df: pd.DataFrame
    n_groups: int
    seed: int
    identical: bool = False


def _dirichlet_weights(n: int, rng: np.random.Generator) -> np.ndarray:
    """Draw n weights on the simplex (sum == 1 by construction).

    Dirichlet(alpha=1) is the uniform distribution over the (n-1)-simplex.
    """
    return rng.dirichlet(np.ones(n))


def make_case(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    n_groups: int,
    seed: int,
    *,
    zero_wp: bool = False,
    zero_wb: bool = False,
    identical: bool = False,
    all_negative: bool = False,
) -> BrinsonCase:
    """Build one deterministic, valid BF test case.

    Parameters
    ----------
    n_groups
        Number of groups (sectors / countries / factors). Must be >= 1.
    seed
        RNG seed. Same seed + same flags → byte-identical DataFrame.
    zero_wp
        If True, force ``w_p[0] = 0`` (I own none of group 0), then
        renormalize so ``w_p`` still sums to 1.
    zero_wb
        If True, force ``w_b[0] = 0`` (off-benchmark holding: group 0
        is in my book but not in the benchmark). Renormalized.
    identical
        If True, set ``w_b = w_p`` and ``r_b = r_p``. The oracle MUST
        return all three effects == 0 exactly (up to float error).
    all_negative
        If True, draw returns from a strictly-negative distribution
        (bear-market sign test). ``r_p`` centered at -8%, ``r_b`` at -6%.

    Returns
    -------
    BrinsonCase
        With a ``df`` carrying columns ``group, w_p, w_b, r_p, r_b``.
    """
    if n_groups < 1:
        raise ValueError(f"n_groups must be >= 1; got {n_groups}")
    if zero_wp and n_groups < 2:
        raise ValueError(
            "zero_wp requires n_groups >= 2 (else renormalize divides by 0)"
        )
    if zero_wb and n_groups < 2:
        raise ValueError(
            "zero_wb requires n_groups >= 2 (else renormalize divides by 0)"
        )

    rng = np.random.default_rng(seed)
    w_p = _dirichlet_weights(n_groups, rng)
    w_b = _dirichlet_weights(n_groups, rng)

    if all_negative:
        r_p = rng.normal(-0.08, 0.03, n_groups)
        r_b = rng.normal(-0.06, 0.02, n_groups)
    else:
        r_p = rng.normal(0.0, 0.08, n_groups)
        r_b = rng.normal(0.0, 0.06, n_groups)

    if zero_wp:
        w_p[0] = 0.0
        w_p = w_p / w_p.sum()
    if zero_wb:
        w_b[0] = 0.0
        w_b = w_b / w_b.sum()

    if identical:
        w_b = w_p.copy()
        r_b = r_p.copy()

    df = pd.DataFrame(
        {
            "group": [f"S{i}" for i in range(n_groups)],
            "w_p": w_p,
            "w_b": w_b,
            "r_p": r_p,
            "r_b": r_b,
        }
    )

    flag_bits = []
    if zero_wp:
        flag_bits.append("zwp")
    if zero_wb:
        flag_bits.append("zwb")
    if identical:
        flag_bits.append("id")
    if all_negative:
        flag_bits.append("neg")
    flag_str = ("-" + "-".join(flag_bits)) if flag_bits else ""
    case_id = f"bf-n{n_groups}-seed{seed}{flag_str}"

    return BrinsonCase(
        case_id=case_id,
        df=df,
        n_groups=n_groups,
        seed=seed,
        identical=identical,
    )
