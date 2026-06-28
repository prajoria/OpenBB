"""Unit tests for ``validation/cpcv.py`` (component 08, §1 CPCV resampling).

Covers :func:`cpcv`, the Combinatorial Purged Cross-Validation splitter (López de
Prado, *Advances in Financial Machine Learning*, ch. 7): partition the session
index into ``n_groups`` contiguous groups, take every ``C(n_groups,
n_test_groups)`` combination of groups as the test set, **purge** training
observations whose forward label window overlaps a test block, and **embargo** a
post-test fraction to kill serial-correlation leakage. It reuses the
:class:`~openbb_backtest.validation.splitters.Fold` type and returns positional
integer indices (engine-agnostic).

Pinned contract: exact split count ``C(N, k)`` and reconstructed-path count
``C(N, k)·k / N`` (e.g. ``(6, 2) → 15`` splits, ``5`` paths); the purge invariant
(no surviving train label window overlaps any test block); exact embargo size
``ceil(embargo·T)`` (and ``0`` removes nothing); train ∩ test empty; determinism;
ValueError on degenerate parameters.

See ``docs/designs/backtest-design/08-validation.md`` §1.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

# ---- split & path counts -------------------------------------------------


@pytest.mark.parametrize(
    ("n_groups", "n_test", "splits"),
    [(6, 2, 15), (10, 2, 45), (8, 3, 56)],
)
def test_split_count_is_n_choose_k(n_groups, n_test, splits):
    from openbb_backtest.validation.cpcv import cpcv

    folds = cpcv(np.arange(120), n_groups=n_groups, n_test_groups=n_test)
    assert len(folds) == splits == math.comb(n_groups, n_test)


@pytest.mark.parametrize(
    ("n_groups", "n_test", "paths"),
    [(6, 2, 5), (10, 2, 9), (8, 3, 21)],
)
def test_backtest_path_count_formula(n_groups, n_test, paths):
    from openbb_backtest.validation.cpcv import n_backtest_paths

    assert n_backtest_paths(n_groups, n_test) == paths
    assert paths == math.comb(n_groups, n_test) * n_test // n_groups


# ---- test-set construction & coverage ------------------------------------


def test_test_set_is_union_of_selected_groups():
    from openbb_backtest.validation.cpcv import cpcv

    # T=60, 6 groups ⇒ width-10 groups; first combo (0,1) ⇒ contiguous [0,20).
    folds = cpcv(np.arange(60), n_groups=6, n_test_groups=2)
    assert list(folds[0].test_idx) == list(range(0, 20))


def test_every_group_is_tested_in_equal_number_of_splits():
    from openbb_backtest.validation.cpcv import cpcv

    folds = cpcv(np.arange(60), n_groups=6, n_test_groups=2)
    counts = np.zeros(60, dtype=int)
    for fold in folds:
        counts[np.asarray(fold.test_idx, dtype=int)] += 1
    # Each index is tested C(N-1, k-1) == 5 times (the reconstructed-path count).
    assert set(counts.tolist()) == {math.comb(5, 1)}


# ---- train / test disjointness -------------------------------------------


def test_train_and_test_are_always_disjoint():
    from openbb_backtest.validation.cpcv import cpcv

    folds = cpcv(np.arange(60), n_groups=6, n_test_groups=2, embargo=0.02, label_span=2)
    for fold in folds:
        assert set(int(i) for i in fold.train_idx).isdisjoint(
            int(i) for i in fold.test_idx
        )


# ---- purge ---------------------------------------------------------------


def test_purge_no_surviving_train_label_overlaps_test_block():
    from openbb_backtest.validation.cpcv import cpcv

    span = 3
    folds = cpcv(np.arange(60), n_groups=6, n_test_groups=2, embargo=0.0, label_span=span)
    for fold in folds:
        test_set = set(int(i) for i in fold.test_idx)
        for i in (int(x) for x in fold.train_idx):
            # The forward label window [i, i+span] must not touch any test index.
            assert set(range(i, i + span + 1)).isdisjoint(test_set)


def test_zero_label_span_purges_nothing_beyond_test():
    from openbb_backtest.validation.cpcv import cpcv

    # With span 0 and no embargo, train is exactly the complement of test.
    folds = cpcv(np.arange(60), n_groups=6, n_test_groups=2, embargo=0.0, label_span=0)
    for fold in folds:
        assert len(fold.train_idx) + len(fold.test_idx) == 60


# ---- embargo -------------------------------------------------------------


def test_embargo_removes_exactly_ceil_fraction_after_a_mid_test_block():
    from openbb_backtest.validation.cpcv import cpcv

    # T=100, 10 groups (width 10), single test group ⇒ folds[k] tests group k.
    # Group 4 = [40,50); embargo 0.05 ⇒ ceil(5) train sessions [50,55) removed.
    folds = cpcv(np.arange(100), n_groups=10, n_test_groups=1, embargo=0.05, label_span=0)
    mid = folds[4]
    embargoed = set(range(50, 55))
    train_set = set(int(i) for i in mid.train_idx)
    assert train_set.isdisjoint(embargoed)
    assert len(mid.train_idx) == 100 - 10 - math.ceil(0.05 * 100)


def test_zero_embargo_removes_no_post_test_sessions():
    from openbb_backtest.validation.cpcv import cpcv

    folds = cpcv(np.arange(100), n_groups=10, n_test_groups=1, embargo=0.0, label_span=0)
    for fold in folds:
        assert len(fold.train_idx) + len(fold.test_idx) == 100


# ---- determinism ---------------------------------------------------------


def test_cpcv_is_deterministic():
    from openbb_backtest.validation.cpcv import cpcv

    def _key(folds):
        return [
            (list(map(int, f.train_idx)), list(map(int, f.test_idx))) for f in folds
        ]

    a = cpcv(np.arange(60), n_groups=6, n_test_groups=2, embargo=0.02, label_span=1)
    b = cpcv(np.arange(60), n_groups=6, n_test_groups=2, embargo=0.02, label_span=1)
    assert _key(a) == _key(b)


def test_cpcv_reuses_the_shared_fold_type():
    from openbb_backtest.validation.cpcv import cpcv
    from openbb_backtest.validation.splitters import Fold

    folds = cpcv(np.arange(60), n_groups=6, n_test_groups=2)
    assert all(isinstance(f, Fold) for f in folds)


# ---- degenerate inputs ---------------------------------------------------


def test_rejects_too_few_groups():
    from openbb_backtest.validation.cpcv import cpcv

    with pytest.raises(ValueError):
        cpcv(np.arange(60), n_groups=1, n_test_groups=1)


def test_rejects_test_groups_not_smaller_than_groups():
    from openbb_backtest.validation.cpcv import cpcv

    with pytest.raises(ValueError):
        cpcv(np.arange(60), n_groups=6, n_test_groups=6)


def test_rejects_non_positive_test_groups():
    from openbb_backtest.validation.cpcv import cpcv

    with pytest.raises(ValueError):
        cpcv(np.arange(60), n_groups=6, n_test_groups=0)


def test_rejects_negative_embargo():
    from openbb_backtest.validation.cpcv import cpcv

    with pytest.raises(ValueError):
        cpcv(np.arange(60), n_groups=6, n_test_groups=2, embargo=-0.1)


def test_rejects_negative_label_span():
    from openbb_backtest.validation.cpcv import cpcv

    with pytest.raises(ValueError):
        cpcv(np.arange(60), n_groups=6, n_test_groups=2, label_span=-1)


def test_rejects_more_groups_than_sessions():
    from openbb_backtest.validation.cpcv import cpcv

    with pytest.raises(ValueError):
        cpcv(np.arange(4), n_groups=6, n_test_groups=2)
