"""Probability of Backtest Overfitting via CSCV (component 08, §2).

:func:`pbo` implements **Combinatorially-Symmetric Cross-Validation** from Bailey,
Borwein, López de Prado & Zhu, *The Probability of Backtest Overfitting*
(J. Computational Finance, 2017) — re-implemented from the public paper, never
from ``mlfinlab`` (Commons-Clause restricted, license rule §08).

Given a performance matrix ``M`` of shape ``(T_slices, N_configs)`` (each column a
strategy configuration, each row that config's performance on one time slice):

1. partition the ``T`` rows into ``S`` contiguous groups;
2. for each of the ``C(S, S/2)`` symmetric splits of the groups into equal
   in-sample (IS) / out-of-sample (OOS) halves, sum performance per config over
   each half;
3. take the IS-best config ``n*``; find its OOS **relative rank**
   ``ω = rank(n*) / (N + 1) ∈ (0, 1)`` and the logit ``λ = ln(ω / (1 − ω))``;
4. **PBO** is the fraction of partitions with ``λ ≤ 0`` — i.e. the IS-best config
   landed in the bottom OOS half (median or worse), the signature of overfitting.

A dominant config that always wins gives ``PBO = 0``; an anti-correlated config
whose IS win guarantees an OOS loss gives ``PBO = 1``; pure noise gives ``≈ 0.5``.
The function is pure and deterministic for a fixed matrix (no RNG inside).

See ``docs/designs/backtest-design/08-validation.md`` §2.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from itertools import combinations

import numpy as np


def pbo(performance_matrix: np.ndarray, *, n_groups: int = 16) -> float:
    """Probability of Backtest Overfitting of a config performance matrix.

    Parameters
    ----------
    performance_matrix
        Shape ``(T_slices, N_configs)``: column ``j`` is configuration ``j``'s
        performance (e.g. per-slice Sharpe or return) across ``T`` time slices.
    n_groups
        Number of contiguous row-groups ``S`` for CSCV (must be even and ``≤ T``);
        the partition count is ``C(S, S/2)``.

    Returns
    -------
    float
        PBO in ``[0, 1]`` — the fraction of symmetric IS/OOS partitions on which
        the in-sample-best config ranked in the bottom OOS half.

    Raises
    ------
    ValueError
        If the matrix is not 2-D, has fewer than 2 configs, or ``n_groups`` is
        odd or exceeds the number of slices.
    """
    matrix = np.asarray(performance_matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"performance_matrix must be 2-D, got {matrix.ndim}-D")
    t_slices, n_configs = matrix.shape
    if n_configs < 2:
        raise ValueError(f"need at least 2 configs to compare, got {n_configs}")
    if n_groups % 2 != 0:
        raise ValueError(f"n_groups must be even for symmetric CSCV, got {n_groups}")
    if n_groups > t_slices:
        raise ValueError(
            f"n_groups ({n_groups}) cannot exceed the number of slices ({t_slices})"
        )

    groups = np.array_split(np.arange(t_slices), n_groups)

    logits: list[float] = []
    for is_groups, oos_groups in _cscv_partitions(n_groups):
        is_rows = np.concatenate([groups[g] for g in is_groups])
        oos_rows = np.concatenate([groups[g] for g in oos_groups])

        is_perf = matrix[is_rows].sum(axis=0)
        oos_perf = matrix[oos_rows].sum(axis=0)

        best = int(np.argmax(is_perf))
        # Relative rank of the IS-best config among OOS performances, in (0, 1).
        rank = int(np.sum(oos_perf < oos_perf[best])) + 1
        omega = rank / (n_configs + 1)
        logits.append(math.log(omega / (1.0 - omega)))

    return float(np.mean(np.asarray(logits) <= 0.0))


def _cscv_partitions(n_groups: int) -> Iterator[tuple[tuple[int, ...], tuple[int, ...]]]:
    """Yield every symmetric ``(IS_groups, OOS_groups)`` split of ``n_groups``.

    Enumerates all ``C(S, S/2)`` ways to choose the in-sample half of the ``S``
    row-groups; the complement is the out-of-sample half. Deterministic ordering
    (``itertools.combinations``) so PBO is reproducible for a fixed matrix.
    """
    all_groups = range(n_groups)
    half = n_groups // 2
    for is_groups in combinations(all_groups, half):
        oos_groups = tuple(g for g in all_groups if g not in is_groups)
        yield is_groups, oos_groups
