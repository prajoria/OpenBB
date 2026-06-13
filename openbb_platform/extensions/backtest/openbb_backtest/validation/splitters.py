"""Walk-forward resampling: index splitter + :class:`Fold` (component 08, §1).

:func:`walk_forward` cuts a session index into successive train→test windows —
the only honest way to estimate out-of-sample performance: a strategy is re-fit
on ``train`` and scored on the immediately-following ``test``, never overlapping
(López de Prado, *Advances in Financial Machine Learning*, ch. 7).

Two regimes:

- **rolling** (default): a fixed-width ``train`` window that slides forward by
  ``step`` each fold;
- **anchored**: the train window always starts at session 0 and *grows* by
  ``step`` each fold (an expanding-window walk-forward).

The splitter is **engine-agnostic** — it operates purely on the index length and
emits **positional integer** arrays (into the supplied ``index``), so it drives
either the event or vectorized engine without importing one. Inputs may be any
sized sequence (``np.ndarray``, :class:`pandas.DatetimeIndex`, …); only the length
matters, and the output is always positional ``int`` indices.

See ``docs/designs/backtest-design/08-validation.md`` §1.
"""

from __future__ import annotations

from collections.abc import Sized
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Fold:
    """One train→test split as positional integer indices into a session index.

    Parameters
    ----------
    train_idx
        Positional indices of the training window.
    test_idx
        Positional indices of the test window (immediately follows ``train_idx``).
    path_id
        Optional CPCV path label; ``None`` for plain walk-forward folds (CPCV in
        component 08.3 sets it to group recombined out-of-sample paths).
    """

    train_idx: np.ndarray
    test_idx: np.ndarray
    path_id: int | None = None


def walk_forward(
    index: Sized,
    train: int,
    test: int,
    step: int,
    *,
    anchored: bool = False,
) -> list[Fold]:
    """Slice ``index`` into rolling (or anchored) walk-forward train→test folds.

    Fold ``k`` (rolling) trains on ``[k·step, k·step + train)`` and tests on the
    contiguous ``[k·step + train, k·step + train + test)``; anchored folds keep
    the train start pinned at ``0`` so the window expands. The number of folds is
    ``floor((T − train − test) / step) + 1`` where ``T == len(index)``.

    Parameters
    ----------
    index
        Any sized sequence (``np.ndarray``, :class:`pandas.DatetimeIndex`, …); only
        its length is used. Returned indices are positional into this sequence.
    train
        Training window width in sessions (``> 0``).
    test
        Test window width in sessions (``> 0``).
    step
        Sessions advanced between consecutive folds (``> 0``).
    anchored
        When ``True`` the train window starts at ``0`` and grows by ``step`` per
        fold; when ``False`` (default) it is a fixed-width window sliding by ``step``.

    Returns
    -------
    list[Fold]
        Folds in chronological order, each carrying positional ``int`` indices.

    Raises
    ------
    ValueError
        If ``train``/``test``/``step`` are not positive, or ``train + test``
        exceeds the index length (no valid fold can be formed).
    """
    if train <= 0:
        raise ValueError(f"train must be positive, got {train}")
    if test <= 0:
        raise ValueError(f"test must be positive, got {test}")
    if step <= 0:
        raise ValueError(f"step must be positive, got {step}")

    total = len(index)
    if train + test > total:
        raise ValueError(
            f"train + test ({train + test}) exceeds index length ({total}); "
            "no valid walk-forward fold can be formed"
        )

    n_folds = (total - train - test) // step + 1
    positions = np.arange(total)

    folds: list[Fold] = []
    for k in range(n_folds):
        offset = k * step
        train_start = 0 if anchored else offset
        train_end = offset + train  # exclusive; test begins exactly here
        test_end = train_end + test
        folds.append(
            Fold(
                train_idx=positions[train_start:train_end],
                test_idx=positions[train_end:test_end],
            )
        )
    return folds
