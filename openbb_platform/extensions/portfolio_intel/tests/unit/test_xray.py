"""Unit tests for X-Ray look-through + rollups + HHI (#526, #535, #536)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from openbb_portfolio_intel.analytics import (
    Holding,
    effective_n,
    herfindahl_hirschman,
    look_through,
    overlap_count,
    rollup_by,
)

# ---------------------------------------------------------------------------
# Fixtures — small realistic holdings graphs.
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_etf_portfolio() -> list[Holding]:
    """50/50 split between two ETFs, each holding 3 underlying stocks."""
    return [
        Holding(symbol="SPY", weight=Decimal("0.5")),
        Holding(symbol="QQQ", weight=Decimal("0.5")),
    ]


@pytest.fixture
def holdings_provider_two_etfs() -> dict[str, list[Holding]]:
    """SPY and QQQ each hold AAPL/MSFT/GOOGL in overlapping weights."""
    return {
        "SPY": [
            Holding(symbol="AAPL", weight=Decimal("0.4")),
            Holding(symbol="MSFT", weight=Decimal("0.3")),
            Holding(symbol="GOOGL", weight=Decimal("0.3")),
        ],
        "QQQ": [
            Holding(symbol="AAPL", weight=Decimal("0.5")),
            Holding(symbol="MSFT", weight=Decimal("0.3")),
            Holding(symbol="AMZN", weight=Decimal("0.2")),
        ],
    }


@pytest.fixture
def attribute_provider_faang() -> dict[str, Holding]:
    """Sector + country + mcap attributes for the underlying tickers."""
    return {
        "AAPL": Holding(
            "AAPL", Decimal("1"), sector="Tech", country="US", mcap_bucket="large"
        ),
        "MSFT": Holding(
            "MSFT", Decimal("1"), sector="Tech", country="US", mcap_bucket="large"
        ),
        "GOOGL": Holding(
            "GOOGL", Decimal("1"), sector="Tech", country="US", mcap_bucket="large"
        ),
        "AMZN": Holding(
            "AMZN", Decimal("1"), sector="Cons", country="US", mcap_bucket="large"
        ),
    }


# ---------------------------------------------------------------------------
# look_through (#526)
# ---------------------------------------------------------------------------


def test_look_through_terminal_single_security() -> None:
    """A single stock with no fund-lookup returns itself at weight 1.0."""
    result = look_through([Holding("AAPL", Decimal("1"))], {})
    assert result.effective == {"AAPL": Decimal("1")}
    assert result.depth_reached == 0
    assert result.unresolved == []


def test_look_through_unwraps_two_etfs(
    simple_etf_portfolio: list[Holding],
    holdings_provider_two_etfs: dict[str, list[Holding]],
) -> None:
    """SPY 0.5 + QQQ 0.5 → weighted combination of underlying."""
    result = look_through(simple_etf_portfolio, holdings_provider_two_etfs)
    # AAPL: 0.5*0.4 + 0.5*0.5 = 0.20 + 0.25 = 0.45
    # MSFT: 0.5*0.3 + 0.5*0.3 = 0.30
    # GOOGL: 0.5*0.3 = 0.15
    # AMZN: 0.5*0.2 = 0.10
    assert result.effective == {
        "AAPL": Decimal("0.45"),
        "MSFT": Decimal("0.30"),
        "GOOGL": Decimal("0.15"),
        "AMZN": Decimal("0.10"),
    }
    # Sum must be 1.0 exactly (weights are exact Decimals here).
    assert sum(result.effective.values()) == Decimal("1")
    assert result.depth_reached == 1


def test_look_through_respects_max_depth() -> None:
    """A cycle-like fund-of-fund stops at max_depth and leaves the leaf terminal."""
    # A holds 100% B; B holds 100% C; C holds 100% D. With max_depth=2 we
    # unwrap A→B→C, then stop; C shouldn't be resolved to D.
    portfolio = [Holding("A", Decimal("1"))]
    provider = {
        "A": [Holding("B", Decimal("1"))],
        "B": [Holding("C", Decimal("1"))],
        "C": [Holding("D", Decimal("1"))],
    }
    result = look_through(portfolio, provider, max_depth=2)
    # depth 0=A, 1=B, 2=C (stop). Effective should have C not D.
    assert "C" in result.effective
    assert "D" not in result.effective
    assert result.depth_reached == 2


def test_look_through_raises_on_bad_top_level_weights() -> None:
    """Top-level weights that don't sum to 1.0 raise ValueError."""
    bad = [
        Holding("AAPL", Decimal("0.5")),
        Holding("MSFT", Decimal("0.4")),
    ]  # sums to 0.9
    with pytest.raises(ValueError, match="must sum to 1.0"):
        look_through(bad, {})


def test_look_through_normalizes_underlying_rounding_drift() -> None:
    """A nearly complete provider vector is normalized before composition."""
    provider = {
        "SPY": [
            Holding("AAPL", Decimal("0.6")),
            Holding("MSFT", Decimal("0.385")),
        ]
    }

    result = look_through([Holding("SPY", Decimal("1"))], provider)

    assert sum(result.effective.values()) == Decimal("1")
    assert result.effective == {
        "AAPL": Decimal("0.6") / Decimal("0.985"),
        "MSFT": Decimal("0.385") / Decimal("0.985"),
    }


@pytest.mark.parametrize(
    "weights",
    [
        (Decimal("0.006"), Decimal("0.004")),
        (Decimal("0.8"), Decimal("0.3")),
        (Decimal("-0.1"), Decimal("1.1")),
        (Decimal("0"), Decimal("0")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("Infinity"), Decimal("1")),
    ],
)
def test_look_through_rejects_invalid_underlying_weights(
    weights: tuple[Decimal, Decimal],
) -> None:
    """Malformed child vectors fail instead of distorting effective weights."""
    provider = {
        "SPY": [
            Holding("AAPL", weights[0]),
            Holding("MSFT", weights[1]),
        ]
    }

    with pytest.raises(ValueError, match=r"SPY.*weights"):
        look_through([Holding("SPY", Decimal("1"))], provider)


def test_look_through_unresolved_symbol_tracked_but_included() -> None:
    """Missing holdings data → symbol kept at face value; noted in unresolved is only
    for explicit provider misses, per the docstring.
    """
    # SPY is in provider but the provider has explicitly an empty holdings list.
    portfolio = [Holding("SPY", Decimal("1"))]
    provider: dict[str, list[Holding]] = {"SPY": []}
    result = look_through(portfolio, provider)
    # SPY IS a known fund with empty holdings — noted in unresolved.
    assert "SPY" in result.unresolved
    # Its weight lives at face value in effective.
    assert result.effective.get("SPY") == Decimal("1")


# ---------------------------------------------------------------------------
# rollup_by (#535)
# ---------------------------------------------------------------------------


def test_rollup_by_sector_matches_manual_sum(
    simple_etf_portfolio: list[Holding],
    holdings_provider_two_etfs: dict[str, list[Holding]],
    attribute_provider_faang: dict[str, Holding],
) -> None:
    """Rollup by sector: Tech = AAPL+MSFT+GOOGL; Cons = AMZN."""
    lt = look_through(simple_etf_portfolio, holdings_provider_two_etfs)
    by_sector = rollup_by(lt.effective, attribute_provider_faang, "sector")
    # Tech = 0.45 + 0.30 + 0.15 = 0.90; Cons = 0.10.
    assert by_sector == {"Tech": Decimal("0.90"), "Cons": Decimal("0.10")}


def test_rollup_by_missing_attribute_falls_into_unknown_bucket(
    simple_etf_portfolio: list[Holding],
    holdings_provider_two_etfs: dict[str, list[Holding]],
) -> None:
    """Symbols without an attribute row roll into (unknown) not silently drop."""
    lt = look_through(simple_etf_portfolio, holdings_provider_two_etfs)
    # Empty attribute provider → everything unknown.
    by_country = rollup_by(lt.effective, {}, "country")
    assert by_country == {"(unknown)": Decimal("1")}


def test_overlap_count_finds_shared_underlyings() -> None:
    """Symbols in multiple portfolios' effective sets get count > 1."""
    p1 = {"AAPL": Decimal("0.5"), "MSFT": Decimal("0.5")}
    p2 = {"AAPL": Decimal("0.4"), "GOOGL": Decimal("0.6")}
    p3 = {"MSFT": Decimal("0.3"), "AMZN": Decimal("0.7")}
    counts = overlap_count([p1, p2, p3])
    assert counts == {"AAPL": 2, "MSFT": 2, "GOOGL": 1, "AMZN": 1}


# ---------------------------------------------------------------------------
# HHI / effective_n (#536)
# ---------------------------------------------------------------------------


def test_hhi_fully_concentrated_is_one() -> None:
    """One holding at weight 1.0 → HHI = 1.0."""
    assert herfindahl_hirschman({"AAPL": Decimal("1")}) == Decimal("1")


def test_hhi_equal_weight_matches_reciprocal_n() -> None:
    """N equal-weight holdings → HHI = 1/N (classic result)."""
    n = 5
    w = Decimal("1") / n
    exposures = {f"S{i}": w for i in range(n)}
    hhi = herfindahl_hirschman(exposures)
    # HHI = N * (1/N)^2 = 1/N
    assert hhi == Decimal("1") / n
    assert effective_n(hhi) == Decimal(n)


def test_hhi_partial_concentration() -> None:
    """Half in one holding, half spread across four → HHI reflects the concentration."""
    exposures = {
        "BIG": Decimal("0.5"),
        "S1": Decimal("0.125"),
        "S2": Decimal("0.125"),
        "S3": Decimal("0.125"),
        "S4": Decimal("0.125"),
    }
    # 0.25 + 4*(0.015625) = 0.25 + 0.0625 = 0.3125
    assert herfindahl_hirschman(exposures) == Decimal("0.3125")
    # Effective N = 1/0.3125 = 3.2 (fewer than 5 raw holdings — the "BIG" one dominates)
    assert effective_n(Decimal("0.3125")) == Decimal("3.2")


def test_effective_n_raises_on_zero_hhi() -> None:
    """HHI = 0 would imply infinite diversification; guard against div-by-zero."""
    with pytest.raises(ValueError, match="must be positive"):
        effective_n(Decimal("0"))
