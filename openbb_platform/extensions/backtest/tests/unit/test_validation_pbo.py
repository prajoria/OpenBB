"""Unit tests for ``validation/pbo.py`` (component 08, §2 PBO via CSCV).

Covers :func:`pbo`, the Probability of Backtest Overfitting via
**Combinatorially-Symmetric Cross-Validation** (Bailey, Borwein, López de Prado &
Zhu, *The Probability of Backtest Overfitting*, J. Computational Finance 2017):

1. split the ``(T_slices, N_configs)`` performance matrix into ``S`` row-groups;
2. for every ``C(S, S/2)`` symmetric IS/OOS partition, pick the IS-best config;
3. find that config's OOS relative rank ``ω ∈ (0, 1)``, take the logit
   ``λ = ln(ω / (1 − ω))``;
4. PBO is the fraction of partitions with ``λ ≤ 0`` (IS-best lands in the bottom
   OOS half → overfit).

Pinned contract: exact combination counts (``C(S,S/2)``), the three analytic
fixtures (a dominant column ⇒ ``0``, an inverted/anti-correlated pair ⇒ ``1``,
pure seeded noise ⇒ ``≈ 0.5``), the ``[0, 1]`` range, determinism for a fixed
matrix, and ValueError on odd ``S`` / ``N < 2`` / shape mismatch.

See ``docs/designs/backtest-design/08-validation.md`` §2.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

# ---- combination counts --------------------------------------------------


@pytest.mark.parametrize(
    ("s", "expected"),
    [(4, 6), (8, 70), (16, 12870)],
)
def test_partition_count_is_central_binomial(s, expected):
    from openbb_backtest.validation.pbo import _cscv_partitions

    partitions = list(_cscv_partitions(s))
    assert len(partitions) == expected == math.comb(s, s // 2)
    # Each partition splits the S groups into equal IS/OOS halves.
    for is_groups, oos_groups in partitions:
        assert len(is_groups) == len(oos_groups) == s // 2
        assert set(is_groups).isdisjoint(oos_groups)
        assert set(is_groups) | set(oos_groups) == set(range(s))


# ---- analytic fixtures ---------------------------------------------------


def test_dominant_config_gives_zero_pbo():
    from openbb_backtest.validation.pbo import pbo

    # One column dwarfs the rest on every slice ⇒ IS-best is always OOS-best
    # ⇒ never in the bottom half ⇒ PBO == 0.
    matrix = np.tile(np.arange(1, 9, dtype=float), (8, 1))
    matrix[:, 3] += 100.0
    assert pbo(matrix, n_groups=8) == 0.0


def test_inverted_pair_gives_unit_pbo():
    from openbb_backtest.validation.pbo import pbo

    # Two perfectly anti-correlated configs: whichever wins IS necessarily loses
    # OOS on every symmetric partition ⇒ PBO == 1.
    col0 = np.array([1.0, 2.0, 4.0, -7.0])
    matrix = np.column_stack([col0, -col0])
    assert pbo(matrix, n_groups=4) == 1.0


def test_pure_noise_pbo_is_about_one_half_on_average():
    from openbb_backtest.validation.pbo import pbo

    # No genuine edge ⇒ IS-best is a coin-flip OOS. A single draw is high-variance,
    # so average the seeded estimate — it concentrates near 0.5.
    estimates = [
        pbo(np.random.default_rng(seed).standard_normal((200, 50)), n_groups=10)
        for seed in range(40)
    ]
    assert float(np.mean(estimates)) == pytest.approx(0.5, abs=0.1)
    assert all(0.0 <= e <= 1.0 for e in estimates)


def test_pbo_is_within_unit_interval_for_seeded_noise():
    from openbb_backtest.validation.pbo import pbo

    for seed in range(5):
        matrix = np.random.default_rng(seed).standard_normal((128, 20))
        value = pbo(matrix, n_groups=16)
        assert 0.0 <= value <= 1.0


# ---- determinism ---------------------------------------------------------


def test_pbo_is_deterministic_for_a_fixed_matrix():
    from openbb_backtest.validation.pbo import pbo

    matrix = np.random.default_rng(123).standard_normal((100, 12))
    assert pbo(matrix, n_groups=10) == pbo(matrix, n_groups=10)


# ---- validation ----------------------------------------------------------


def test_rejects_odd_group_count():
    from openbb_backtest.validation.pbo import pbo

    matrix = np.random.default_rng(0).standard_normal((90, 10))
    with pytest.raises(ValueError):
        pbo(matrix, n_groups=9)


def test_rejects_fewer_than_two_configs():
    from openbb_backtest.validation.pbo import pbo

    single = np.random.default_rng(0).standard_normal((50, 1))
    with pytest.raises(ValueError):
        pbo(single, n_groups=10)


def test_rejects_non_two_dimensional_matrix():
    from openbb_backtest.validation.pbo import pbo

    with pytest.raises(ValueError):
        pbo(np.arange(50.0), n_groups=10)


def test_rejects_more_groups_than_slices():
    from openbb_backtest.validation.pbo import pbo

    matrix = np.random.default_rng(0).standard_normal((6, 10))
    with pytest.raises(ValueError):
        pbo(matrix, n_groups=8)
