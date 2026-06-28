"""Combinatorial Purged Cross-Validation (component 08, §1).

:func:`cpcv` implements CPCV from López de Prado, *Advances in Financial Machine
Learning*, ch. 7 — the resampling scheme that produces many out-of-sample paths
while killing look-ahead leakage:

1. partition the session index into ``n_groups`` contiguous groups;
2. for every ``C(n_groups, n_test_groups)`` combination of groups, take their
   union as the **test** set (the remaining groups seed the train set);
3. **purge** any training observation whose forward label window ``[i, i +
   label_span]`` overlaps a test block (its label is contaminated by test data);
4. **embargo** the ``ceil(embargo · T)`` sessions immediately *after* each
   contiguous test block, to sever serial-correlation leakage into the train set.

Reconstructing the OOS folds yields ``C(n_groups, n_test_groups) · n_test_groups /
n_groups`` independent backtest paths (:func:`n_backtest_paths`). The splitter is
**engine-agnostic** — it reuses the shared
:class:`~openbb_backtest.validation.splitters.Fold` and returns positional integer
indices, so it drives either engine without importing one.

See ``docs/designs/backtest-design/08-validation.md`` §1.
"""

from __future__ import annotations

import math
from collections.abc import Sized
from itertools import combinations

import numpy as np

from openbb_backtest.validation.splitters import Fold


def cpcv(
    index: Sized,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: float = 0.01,
    label_span: int = 0,
) -> list[Fold]:
    """Combinatorial Purged CV folds over ``index`` with purge & embargo.

    Parameters
    ----------
    index
        Any sized sequence (only its length is used); returned indices are
        positional into it.
    n_groups
        Number of contiguous groups ``N`` to partition the sessions into
        (``≥ 2`` and ``≤ len(index)``).
    n_test_groups
        Groups per test set ``k`` (``1 ≤ k < N``); the test count is ``C(N, k)``.
    embargo
        Fraction of total sessions removed from training immediately after each
        contiguous test block (``≥ 0``); the size is ``ceil(embargo · T)``.
    label_span
        Forward label horizon ``h`` (sessions, ``≥ 0``): a training index ``i`` is
        purged if any of ``[i, i + h]`` falls in a test block.

    Returns
    -------
    list[Fold]
        One :class:`Fold` per group combination, in deterministic
        ``itertools.combinations`` order, with positional ``int`` indices.

    Raises
    ------
    ValueError
        If ``n_groups < 2``, ``n_test_groups`` is not in ``[1, n_groups)``,
        ``embargo`` or ``label_span`` is negative, or ``n_groups`` exceeds the
        number of sessions.
    """
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if n_test_groups < 1:
        raise ValueError(f"n_test_groups must be >= 1, got {n_test_groups}")
    if n_test_groups >= n_groups:
        raise ValueError(
            f"n_test_groups ({n_test_groups}) must be < n_groups ({n_groups})"
        )
    if embargo < 0.0:
        raise ValueError(f"embargo must be non-negative, got {embargo}")
    if label_span < 0:
        raise ValueError(f"label_span must be non-negative, got {label_span}")

    total = len(index)
    if n_groups > total:
        raise ValueError(
            f"n_groups ({n_groups}) cannot exceed the number of sessions ({total})"
        )

    groups = np.array_split(np.arange(total), n_groups)
    embargo_size = math.ceil(embargo * total)
    positions = np.arange(total)

    folds: list[Fold] = []
    for combo in combinations(range(n_groups), n_test_groups):
        test_idx = np.concatenate([groups[g] for g in combo])
        test_set = set(int(i) for i in test_idx)
        embargoed = _embargo_indices(test_set, embargo_size, total)

        train_idx = np.array(
            [
                i
                for i in range(total)
                if i not in test_set
                and i not in embargoed
                and not _label_overlaps_test(i, label_span, total, test_set)
            ],
            dtype=int,
        )
        folds.append(Fold(train_idx=positions[train_idx], test_idx=test_idx))
    return folds


def n_backtest_paths(n_groups: int, n_test_groups: int) -> int:
    """Number of reconstructed OOS backtest paths: ``C(N, k) · k / N``.

    Each of the ``C(N, k)`` splits contributes ``k`` tested groups, and every group
    is tested in ``C(N-1, k-1)`` splits, so the recombined OOS paths number
    ``C(N, k) · k / N`` (López de Prado, AFML ch. 7) — e.g. ``(6, 2) → 5``.
    """
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if not 1 <= n_test_groups < n_groups:
        raise ValueError(
            f"n_test_groups ({n_test_groups}) must be in [1, n_groups)"
        )
    return math.comb(n_groups, n_test_groups) * n_test_groups // n_groups


# --- internal helpers -----------------------------------------------------


def _embargo_indices(test_set: set[int], embargo_size: int, total: int) -> set[int]:
    """Indices removed by embargo: ``embargo_size`` sessions after each test block.

    The test set may span several non-adjacent contiguous blocks (a combination of
    non-adjacent groups), so embargo is applied after the end of *each* block.
    """
    if embargo_size == 0:
        return set()
    embargoed: set[int] = set()
    for _, end in _contiguous_blocks(sorted(test_set)):
        embargoed.update(range(end + 1, min(end + 1 + embargo_size, total)))
    return embargoed


def _label_overlaps_test(i: int, label_span: int, total: int, test_set: set[int]) -> bool:
    """Whether training index ``i``'s forward label window touches a test index."""
    window_end = min(i + label_span + 1, total)
    return any(j in test_set for j in range(i, window_end))


def _contiguous_blocks(sorted_idx: list[int]) -> list[tuple[int, int]]:
    """Maximal inclusive ``[start, end]`` runs of consecutive integers."""
    if not sorted_idx:
        return []
    blocks: list[tuple[int, int]] = []
    start = prev = sorted_idx[0]
    for value in sorted_idx[1:]:
        if value == prev + 1:
            prev = value
        else:
            blocks.append((start, prev))
            start = prev = value
    blocks.append((start, prev))
    return blocks
