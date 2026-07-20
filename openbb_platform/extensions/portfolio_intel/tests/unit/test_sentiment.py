"""Unit tests for sentiment rollup (#570).

Covers:
- Per-holding upside math (including R7.3 zero-price / missing-price guards).
- Rollup rating math under both weighting schemes.
- Coverage_pct correctness (the load-bearing invariant that prevents
  silent "rating from 10% of the book").
- Loud-empty on zero-weight / all-None-rating input.
- Reverse-verify (R7.11): swap in mutated snapshots and confirm the
  rating rollup actually changes — proves the tests discriminate.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from openbb_portfolio_intel.analytics.sentiment import (
    AnalystSnapshot,
    rollup_sentiment,
    score_and_rollup,
    score_holding,
)

D = Decimal


# ---------------------------------------------------------------------------
# Per-holding score_holding
# ---------------------------------------------------------------------------


def test_score_holding_computes_upside() -> None:
    snap = AnalystSnapshot(
        symbol="AAPL",
        weight=D("0.1"),
        price=D("100"),
        pt_median=D("115"),
        rating=D("4.2"),
        analyst_count=30,
    )
    r = score_holding(snap)
    assert r.upside_pct == D("0.15")
    assert r.rating == D("4.2")


def test_score_holding_zero_price_returns_none_upside() -> None:
    """R7.3 guard: divide-by-zero must NOT crash; returns None."""
    snap = AnalystSnapshot(
        symbol="ZERO", weight=D("0.01"), price=D("0"), pt_median=D("50")
    )
    r = score_holding(snap)
    assert r.upside_pct is None


def test_score_holding_missing_price_returns_none_upside() -> None:
    snap = AnalystSnapshot(symbol="X", weight=D("0.01"), pt_median=D("50"))
    r = score_holding(snap)
    assert r.upside_pct is None


def test_score_holding_missing_target_returns_none_upside() -> None:
    snap = AnalystSnapshot(symbol="X", weight=D("0.01"), price=D("100"))
    r = score_holding(snap)
    assert r.upside_pct is None


def test_score_holding_net_updowngrades_is_upgrades_minus_downgrades() -> None:
    snap = AnalystSnapshot(
        symbol="X", weight=D("0.01"), upgrades_recent=5, downgrades_recent=2
    )
    assert score_holding(snap).net_updowngrades == 3


# ---------------------------------------------------------------------------
# rollup_sentiment — portfolio weighting
# ---------------------------------------------------------------------------


def _mk(sym: str, w: str, rating: str | None, count: int, price="100", pt="110"):
    return AnalystSnapshot(
        symbol=sym,
        weight=D(w),
        price=D(price) if price else None,
        pt_median=D(pt) if pt else None,
        rating=D(rating) if rating else None,
        analyst_count=count,
    )


def test_rollup_portfolio_weight_equals_weighted_average_rating() -> None:
    scored, roll = score_and_rollup(
        [
            _mk("A", "0.5", "4.0", 20),  # 4.0 * 0.5 = 2.0
            _mk("B", "0.5", "2.0", 20),  # 2.0 * 0.5 = 1.0
        ]
    )
    assert roll.rating == D("3.0")  # (2.0 + 1.0) / 1.0
    assert roll.coverage_pct == D("1")


def test_rollup_analyst_count_weighting_biases_toward_high_coverage() -> None:
    _, roll = score_and_rollup(
        [
            _mk("A", "0.5", "5.0", 30),  # heavy coverage bull
            _mk("B", "0.5", "1.0", 3),  # thin coverage bear
        ],
        weighting="analyst_count",
    )
    # Weighted by analyst_count: (5*0.5*30 + 1*0.5*3) / (0.5*30 + 0.5*3)
    # = (75 + 1.5) / 16.5 = 76.5 / 16.5 ≈ 4.636...
    assert roll.rating is not None
    assert D("4.5") < roll.rating < D("4.7")


def test_rollup_holdings_without_rating_excluded_from_rating_but_kept_for_coverage() -> None:
    """Coverage_pct is the flagship invariant. Verify it directly."""
    _, roll = score_and_rollup(
        [
            _mk("A", "0.3", "4.0", 20),
            _mk("B", "0.7", None, 0),  # no coverage
        ]
    )
    # Rating comes only from A: 4.0 (single rated holding weighted 0.3 = 4.0)
    assert roll.rating == D("4.0")
    # Coverage is 30% of the book — critical for downstream widgets.
    assert roll.coverage_pct == D("0.3")


def test_rollup_upside_excludes_holdings_with_no_target() -> None:
    _, roll = score_and_rollup(
        [
            AnalystSnapshot(
                symbol="A",
                weight=D("0.5"),
                price=D("100"),
                pt_median=D("120"),
                rating=D("4.0"),
            ),  # upside = 0.2
            AnalystSnapshot(
                symbol="B", weight=D("0.5"), price=D("100"), rating=D("3.0")
            ),  # no target — excluded from upside
        ]
    )
    # Only A contributes to upside: 0.2 * 0.5 / 0.5 = 0.2
    assert roll.upside_pct == D("0.2")


def test_rollup_net_updowngrades_is_raw_sum_not_weighted() -> None:
    _, roll = score_and_rollup(
        [
            AnalystSnapshot(
                symbol="A", weight=D("0.99"), upgrades_recent=1, downgrades_recent=0
            ),
            AnalystSnapshot(
                symbol="B", weight=D("0.01"), upgrades_recent=5, downgrades_recent=2
            ),
        ]
    )
    # Raw net = (1-0) + (5-2) = 4  (weight-independent)
    assert roll.net_updowngrades == 4


def test_rollup_empty_returns_loud_empty_state() -> None:
    """R7.3: empty input yields coverage=0, rating=None — caller-visible."""
    roll = rollup_sentiment([])
    assert roll.rating is None
    assert roll.upside_pct is None
    assert roll.coverage_pct == D("0")
    assert roll.holding_count == 0


def test_rollup_all_holdings_uncovered_yields_none_rating_zero_coverage() -> None:
    _, roll = score_and_rollup(
        [
            _mk("A", "0.6", None, 0),
            _mk("B", "0.4", None, 0),
        ]
    )
    assert roll.rating is None
    assert roll.coverage_pct == D("0")
    assert roll.holding_count == 2


# ---------------------------------------------------------------------------
# Coverage_pct switches on weighting scheme? MUST NOT.
# ---------------------------------------------------------------------------


def test_coverage_pct_is_portfolio_weight_regardless_of_weighting_scheme() -> None:
    """Coverage semantics must NOT change under analyst_count weighting.

    Coverage answers "how much of MY book had a rating" — always
    portfolio-weight. If it flipped to analyst_count weighting the
    number would inflate misleadingly (a heavily-covered thin position
    would drown out an uncovered heavy position).
    """
    snaps = [
        _mk("A", "0.2", "4.0", 30),
        _mk("B", "0.8", None, 0),
    ]
    _, roll_p = score_and_rollup(snaps, weighting="portfolio")
    _, roll_a = score_and_rollup(snaps, weighting="analyst_count")
    assert roll_p.coverage_pct == D("0.2")
    assert roll_a.coverage_pct == D("0.2")


# ---------------------------------------------------------------------------
# R7.11 reverse-verify: mutate a snapshot, confirm rollup rating changes
# ---------------------------------------------------------------------------


def test_reverse_verify_rating_mutation_actually_changes_rollup() -> None:
    """If this fails, the rollup fixture doesn't discriminate a bug fix.

    Runs the same math twice with only one rating flipped — output
    MUST differ. If it doesn't, the fixture is dominated by other
    weights and the coverage_pct test would be ceremonial.
    """
    base = [_mk("A", "0.5", "4.0", 20), _mk("B", "0.5", "2.0", 20)]
    mutated = [_mk("A", "0.5", "5.0", 20), _mk("B", "0.5", "2.0", 20)]
    _, roll_base = score_and_rollup(base)
    _, roll_mut = score_and_rollup(mutated)
    assert roll_base.rating != roll_mut.rating, (
        "fixture is ceremonial — mutation didn't change output"
    )
    assert roll_mut.rating > roll_base.rating


def test_reverse_verify_coverage_mutation_changes_coverage() -> None:
    """Toggle one holding from uncovered to covered; coverage MUST rise."""
    uncovered = [_mk("A", "0.5", "4.0", 20), _mk("B", "0.5", None, 0)]
    covered = [_mk("A", "0.5", "4.0", 20), _mk("B", "0.5", "3.0", 5)]
    _, roll_u = score_and_rollup(uncovered)
    _, roll_c = score_and_rollup(covered)
    assert roll_u.coverage_pct == D("0.5")
    assert roll_c.coverage_pct == D("1.0")


# ---------------------------------------------------------------------------
# Invalid weighting scheme (defensive typing)
# ---------------------------------------------------------------------------


def test_rollup_rejects_unknown_weighting_via_type_hint() -> None:
    """The Literal type keeps us honest; but at runtime the else branch
    treats unknown as "portfolio". Assert that behavior so a future
    refactor doesn't silently split."""
    snaps = [_mk("A", "0.5", "4.0", 20), _mk("B", "0.5", "2.0", 5)]
    scored = [score_holding(s) for s in snaps]
    # Force via typing-cheat: bypass literal, pass an unrecognized string.
    roll = rollup_sentiment(scored, weighting="unknown_scheme")  # type: ignore[arg-type]
    # Expected: falls through to portfolio-weight branch.
    assert roll.rating == D("3.0")


def test_score_and_rollup_returns_both_scored_and_rollup() -> None:
    scored, roll = score_and_rollup([_mk("A", "0.5", "4.0", 20)])
    assert len(scored) == 1
    assert scored[0].symbol == "A"
    assert roll.rating == D("4.0")
