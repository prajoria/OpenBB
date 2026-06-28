"""Unit tests for ``validation/splitters.py`` (component 08, §1 resampling).

Covers the walk-forward (WFO) index splitter and the :class:`Fold` value type:
:func:`walk_forward` slices a session index into rolling (or anchored) train→test
windows, returning **positional integer** index arrays so it drives either engine
without ever touching one (engine-agnostic, López de Prado *Advances in Financial
ML*, ch. 7).

These pin the splitter's arithmetic contract — exact rolling/anchored fold count
and window bounds, the no-gap / no-overlap / no-look-ahead invariant between
train and test, acceptance of both ``np.ndarray`` and ``DatetimeIndex`` inputs
(always yielding positional ints), determinism, and ValueError on degenerate
inputs.

See ``docs/designs/backtest-design/08-validation.md`` §1.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest


def _expected_rolling_count(t: int, train: int, test: int, step: int) -> int:
    return math.floor((t - train - test) / step) + 1


# ---- Fold value type -----------------------------------------------------


def test_fold_carries_train_test_and_optional_path_id():
    from openbb_backtest.validation.splitters import Fold

    fold = Fold(train_idx=np.array([0, 1, 2]), test_idx=np.array([3, 4]))
    assert list(fold.train_idx) == [0, 1, 2]
    assert list(fold.test_idx) == [3, 4]
    assert fold.path_id is None  # WFO folds have no CPCV path label

    labelled = Fold(train_idx=np.array([0]), test_idx=np.array([1]), path_id=7)
    assert labelled.path_id == 7


# ---- rolling walk-forward ------------------------------------------------


def test_rolling_fold_count_matches_floor_formula():
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    folds = walk_forward(index, train=40, test=10, step=10)
    assert len(folds) == _expected_rolling_count(100, 40, 10, 10) == 6


def test_rolling_fold_count_with_larger_step():
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    folds = walk_forward(index, train=40, test=10, step=25)
    assert len(folds) == _expected_rolling_count(100, 40, 10, 25) == 3


def test_rolling_windows_have_correct_bounds():
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    folds = walk_forward(index, train=40, test=10, step=10)

    # Fold k (rolling): train = [k·step, k·step+train), test follows immediately.
    for k, fold in enumerate(folds):
        start = k * 10
        assert list(fold.train_idx) == list(range(start, start + 40))
        assert list(fold.test_idx) == list(range(start + 40, start + 50))


def test_rolling_train_window_slides_forward():
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    folds = walk_forward(index, train=40, test=10, step=10)
    first_starts = int(folds[0].train_idx[0])
    second_starts = int(folds[1].train_idx[0])
    # Rolling: the train window start advances by ``step`` (not anchored at 0).
    assert first_starts == 0
    assert second_starts == 10


# ---- anchored walk-forward -----------------------------------------------


def test_anchored_train_always_starts_at_zero_and_grows():
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    folds = walk_forward(index, train=40, test=10, step=10, anchored=True)
    assert len(folds) == _expected_rolling_count(100, 40, 10, 10)

    prev_len = 0
    for k, fold in enumerate(folds):
        assert int(fold.train_idx[0]) == 0  # anchored at the very first session
        assert len(fold.train_idx) > prev_len  # expanding window
        prev_len = len(fold.train_idx)
        # Test block still immediately follows the (grown) train window.
        train_end = int(fold.train_idx[-1]) + 1
        assert list(fold.test_idx) == list(range(train_end, train_end + 10))
        assert train_end == 40 + k * 10


# ---- no gap / overlap / look-ahead invariant -----------------------------


@pytest.mark.parametrize("anchored", [False, True])
def test_train_and_test_are_disjoint_and_contiguous(anchored):
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    folds = walk_forward(index, train=40, test=10, step=10, anchored=anchored)
    for fold in folds:
        train = set(int(i) for i in fold.train_idx)
        test = set(int(i) for i in fold.test_idx)
        assert train.isdisjoint(test)  # no leakage
        # Test starts exactly at train end: no gap, no overlap, no look-ahead.
        assert int(fold.test_idx[0]) == int(fold.train_idx[-1]) + 1


# ---- input flexibility & positional output -------------------------------


def test_accepts_datetimeindex_and_returns_positional_ints():
    from openbb_backtest.validation.splitters import walk_forward

    index = pd.date_range("2020-01-01", periods=100, freq="B")
    folds = walk_forward(index, train=40, test=10, step=10)
    assert len(folds) == 6
    # Output is positional integers into the index, never the timestamps.
    assert np.issubdtype(np.asarray(folds[0].train_idx).dtype, np.integer)
    assert list(folds[0].test_idx) == list(range(40, 50))


def test_accepts_plain_length_via_ndarray():
    from openbb_backtest.validation.splitters import walk_forward

    folds = walk_forward(np.arange(50), train=30, test=10, step=5)
    assert len(folds) == _expected_rolling_count(50, 30, 10, 5)


# ---- determinism ---------------------------------------------------------


def test_walk_forward_is_deterministic():
    from openbb_backtest.validation.splitters import walk_forward

    index = np.arange(100)
    a = walk_forward(index, train=40, test=10, step=10)
    b = walk_forward(index, train=40, test=10, step=10)
    assert [(_l(f.train_idx), _l(f.test_idx)) for f in a] == [
        (_l(f.train_idx), _l(f.test_idx)) for f in b
    ]


def _l(arr) -> list:
    return [int(x) for x in arr]


# ---- degenerate inputs ---------------------------------------------------


def test_rejects_non_positive_train():
    from openbb_backtest.validation.splitters import walk_forward

    with pytest.raises(ValueError):
        walk_forward(np.arange(50), train=0, test=10, step=5)


def test_rejects_non_positive_test():
    from openbb_backtest.validation.splitters import walk_forward

    with pytest.raises(ValueError):
        walk_forward(np.arange(50), train=30, test=0, step=5)


def test_rejects_non_positive_step():
    from openbb_backtest.validation.splitters import walk_forward

    with pytest.raises(ValueError):
        walk_forward(np.arange(50), train=30, test=10, step=0)


def test_rejects_window_larger_than_index():
    from openbb_backtest.validation.splitters import walk_forward

    # train + test exceeds T ⇒ no valid fold can be formed.
    with pytest.raises(ValueError):
        walk_forward(np.arange(20), train=30, test=10, step=5)
