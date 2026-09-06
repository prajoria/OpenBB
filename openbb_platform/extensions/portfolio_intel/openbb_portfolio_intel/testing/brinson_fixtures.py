"""Brinson-Fachler synthetic test-data generator + oracle (#935).

Provides deterministic synthetic (portfolio, benchmark) pairs whose
allocation/selection/interaction effects can be computed by an
independent "oracle" implementation of the Brinson-Fachler algebra.
This oracle side unblocks #559's ±1bp acceptance criterion WITHOUT
Bloomberg reference values — the two implementations (production
:func:`compute_brinson_fachler` and this oracle) must agree on every
generated case.

## Design

- **Generator** produces weight vectors + returns from a seeded RNG.
  Weights sum to 1.0 within 1e-12 on both sides. Deterministic
  ``(n_groups, seed, flags)`` inputs → byte-stable outputs.
- **Oracle** is a literal transcription of the Brinson-Fachler
  formulas — not "optimized," obviously correct by inspection.
- **Golden fixture set** covers the 6 edge cases from #935 §4.2:
  identical, all-alloc, all-selection, negative-benchmark, empty-
  sector, and small-weights.

## Public API

- ``generate_case(n_groups, seed, *, flags)`` → :class:`SyntheticCase`
- ``oracle_bf(case)`` → :class:`OracleResult`
- ``GOLDEN_CASES`` — list of hand-designed edge cases
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntheticCase:
    """One synthetic Brinson-Fachler test case.

    All arrays are aligned by index: index i = group i.
    """

    label: str
    group_names: list[str]
    portfolio_weight: np.ndarray  # sums to 1.0
    portfolio_return: np.ndarray  # per-group return in period
    benchmark_weight: np.ndarray  # sums to 1.0
    benchmark_return: np.ndarray  # per-group return in period


@dataclass(frozen=True)
class OracleResult:
    """Ground-truth attribution for one case, computed by the oracle."""

    allocation: np.ndarray  # per-group
    selection: np.ndarray
    interaction: np.ndarray
    total_active_return: float  # portfolio_ret − benchmark_ret
    portfolio_return: float
    benchmark_return: float


# ---------------------------------------------------------------------------
# Oracle — obvious-by-inspection BF formulas
# ---------------------------------------------------------------------------


def oracle_bf(case: SyntheticCase) -> OracleResult:
    """Compute BF allocation/selection/interaction per group.

    R_b = Σ w_b_i * r_b_i  (total benchmark return)
    R_p = Σ w_p_i * r_p_i  (total portfolio return)
    per group i:
        allocation_i  = (w_p_i - w_b_i) * (r_b_i - R_b)
        selection_i   = w_b_i * (r_p_i - r_b_i)
        interaction_i = (w_p_i - w_b_i) * (r_p_i - r_b_i)
    """
    w_p = case.portfolio_weight
    r_p = case.portfolio_return
    w_b = case.benchmark_weight
    r_b = case.benchmark_return

    R_b = float(np.dot(w_b, r_b))
    R_p = float(np.dot(w_p, r_p))

    allocation = (w_p - w_b) * (r_b - R_b)
    selection = w_b * (r_p - r_b)
    interaction = (w_p - w_b) * (r_p - r_b)

    return OracleResult(
        allocation=allocation,
        selection=selection,
        interaction=interaction,
        total_active_return=R_p - R_b,
        portfolio_return=R_p,
        benchmark_return=R_b,
    )


# ---------------------------------------------------------------------------
# Generator — random but deterministic + weight-normalized
# ---------------------------------------------------------------------------


def _normalize_dirichlet(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return a length-n weight vector summing to 1.0 within 1e-12."""
    raw = rng.dirichlet(np.ones(n))
    # Renormalize once to defend against float drift in dirichlet.
    return raw / raw.sum()


def generate_case(
    n_groups: int,
    seed: int,
    *,
    label: str | None = None,
    allow_short_names_to_match: bool = True,
) -> SyntheticCase:
    """Generate one deterministic BF test case.

    Returns will be in the [-0.20, +0.30] range per group (period-plausible).
    Weights are Dirichlet(1) distributed (uniform over the simplex).
    """
    if n_groups < 1:
        raise ValueError(f"n_groups must be >= 1; got {n_groups}")
    rng = np.random.default_rng(seed)
    w_p = _normalize_dirichlet(rng, n_groups)
    w_b = _normalize_dirichlet(rng, n_groups)
    r_p = rng.uniform(-0.20, 0.30, size=n_groups)
    r_b = rng.uniform(-0.20, 0.30, size=n_groups)

    names: list[str]
    if allow_short_names_to_match:
        names = [f"g{i}" for i in range(n_groups)]
    else:
        names = [f"group_{i:03d}" for i in range(n_groups)]

    return SyntheticCase(
        label=label or f"synth_n{n_groups}_seed{seed}",
        group_names=names,
        portfolio_weight=w_p,
        portfolio_return=r_p,
        benchmark_weight=w_b,
        benchmark_return=r_b,
    )


# ---------------------------------------------------------------------------
# Golden fixtures — the six §4.2 edge cases
# ---------------------------------------------------------------------------


def _mk_case(
    label: str, w_p: list[float], r_p: list[float], w_b: list[float], r_b: list[float]
) -> SyntheticCase:
    return SyntheticCase(
        label=label,
        group_names=[f"g{i}" for i in range(len(w_p))],
        portfolio_weight=np.array(w_p),
        portfolio_return=np.array(r_p),
        benchmark_weight=np.array(w_b),
        benchmark_return=np.array(r_b),
    )


GOLDEN_CASES: list[SyntheticCase] = [
    # 1. Identical: portfolio == benchmark → zero active return, all effects 0
    _mk_case(
        "identical",
        w_p=[0.3, 0.4, 0.3],
        r_p=[0.05, 0.10, -0.02],
        w_b=[0.3, 0.4, 0.3],
        r_b=[0.05, 0.10, -0.02],
    ),
    # 2. Pure allocation: same per-group returns; only weights differ
    _mk_case(
        "pure_allocation",
        w_p=[0.6, 0.4],
        r_p=[0.10, 0.02],
        w_b=[0.3, 0.7],
        r_b=[0.10, 0.02],
    ),
    # 3. Pure selection: identical weights on both sides; returns differ
    _mk_case(
        "pure_selection",
        w_p=[0.5, 0.5],
        r_p=[0.12, 0.03],
        w_b=[0.5, 0.5],
        r_b=[0.08, 0.01],
    ),
    # 4. Negative benchmark: some group returns negative on both sides
    _mk_case(
        "negative_benchmark",
        w_p=[0.4, 0.3, 0.3],
        r_p=[-0.05, 0.03, 0.10],
        w_b=[0.5, 0.2, 0.3],
        r_b=[-0.08, 0.04, 0.06],
    ),
    # 5. Empty sector on portfolio (weight = 0) but present on benchmark
    _mk_case(
        "empty_portfolio_sector",
        w_p=[0.5, 0.5, 0.0],
        r_p=[0.10, 0.05, 0.00],  # r_p of empty sector arbitrary
        w_b=[0.3, 0.3, 0.4],
        r_b=[0.08, 0.04, 0.15],
    ),
    # 6. Small-weights: tiny overweight in one sector
    _mk_case(
        "small_weights",
        w_p=[0.001, 0.499, 0.500],
        r_p=[0.20, 0.05, -0.02],
        w_b=[0.000, 0.500, 0.500],
        r_b=[0.00, 0.05, -0.02],
    ),
]


def iter_random_cases(
    n_cases: int = 20,
    seed_start: int = 0,
    group_sizes: Iterable[int] = (2, 3, 5, 7, 11),
) -> Iterable[SyntheticCase]:
    """Deterministic stream of random cases across a range of group sizes."""
    sizes = list(group_sizes)
    for i in range(n_cases):
        n = sizes[i % len(sizes)]
        yield generate_case(n, seed_start + i, label=f"rand_{i}_n{n}")
