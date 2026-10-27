"""Basket look-through, sector roll-up and concentration engine (#2313).

Every expected value here is computed by hand from the synthetic inputs,
never by calling the engine, so a wrong formula cannot agree with itself.
The notebook-parity tests live in ``test_basket_lookthrough_parity.py``.
"""

from __future__ import annotations

import logging

import pytest
from openbb_portfolio_intel.analytics.basket_lookthrough import (
    NportUnavailable,
    basket_sector_view,
    category_bucket,
    concentration,
    construction_targets,
    effective_positions,
    sector_rollup,
)

ETF_HOLDINGS = {
    "EQX": [
        {"name": "Alpha Corp", "weight": 0.6, "asset_category": "EC"},
        {"name": "Beta Inc", "weight": 0.3, "asset_category": "EC"},
        {"name": "Gamma Ltd", "weight": 0.1, "asset_category": "EC"},
    ],
    "BDX": [
        {"name": "Treasury 1", "weight": 0.7, "asset_category": "DBT"},
        {"name": "Treasury 2", "weight": 0.3, "asset_category": "DBT"},
    ],
}


def _holdings_for(symbol: str) -> list[dict]:
    if symbol not in ETF_HOLDINGS:
        raise NportUnavailable(f"{symbol}: not an N-PORT filer")
    return ETF_HOLDINGS[symbol]


BASKET = [
    {"symbol": "EQX", "weight": 0.5},
    {"symbol": "BDX", "weight": 0.3},
    {"symbol": "GLDX", "weight": 0.1},
    {"symbol": "SNGL", "weight": 0.1},
]
CLASSES = {
    "equity_etfs": {"EQX", "MISS"},
    "bond_etfs": {"BDX"},
    "commodity_trusts": {"GLDX"},
}


def test_effective_positions_flattens_each_class_by_hand() -> None:
    """Equity, bond, commodity and single-name rows flatten as worked out by hand."""
    result = effective_positions(BASKET, _holdings_for, top_n_per_etf=2, **CLASSES)
    assert result.effective == pytest.approx(
        {
            "Alpha Corp": 0.30,  # 0.5 * 0.6
            "Beta Inc": 0.15,  # 0.5 * 0.3
            "TAIL_EQX": 0.05,  # 0.5 * 0.1, beyond top-2
            "BOND_BDX": 0.30,  # 0.3 * (0.7 + 0.3), one opaque bucket
            "GLDX": 0.10,
            "SNGL": 0.10,
        }
    )
    assert not result.non_nport
    assert result.opaque == [("GLDX", "commodity trust — no look-through")]


def test_ticker_key_is_accepted_like_the_notebook_basket() -> None:
    """NB01 baskets key positions by ``ticker``."""
    result = effective_positions(
        [{"ticker": "SNGL", "weight": 1.0}], _holdings_for, **CLASSES
    )
    assert result.effective == {"SNGL": 1.0}


def test_unavailable_filer_is_kept_at_face_weight_and_reported() -> None:
    """A non-filer stays at face weight and is reported."""
    result = effective_positions(
        [{"symbol": "MISS", "weight": 0.4}, {"symbol": "SNGL", "weight": 0.6}],
        _holdings_for,
        **CLASSES,
    )
    assert result.effective == pytest.approx({"MISS": 0.4, "SNGL": 0.6})
    assert result.non_nport == ["MISS"]
    assert result.opaque == [("MISS", "MISS: not an N-PORT filer")]


def test_empty_flatten_of_a_nonempty_basket_is_loud(caplog) -> None:
    """Nothing out of a non-empty basket logs a warning."""
    with caplog.at_level(
        logging.WARNING, logger="openbb_portfolio_intel.analytics.basket_lookthrough"
    ):
        result = effective_positions(
            [{"symbol": "EQX", "weight": 1.0}], lambda _symbol: [], **CLASSES
        )
    assert not result.effective
    assert [r for r in caplog.records if "no effective positions" in r.getMessage()]


@pytest.mark.parametrize(
    ("category", "bucket"),
    [
        ("DBT", "Fixed Income"),
        ("ABS-MBS", "Fixed Income"),
        ("LOAN", "Fixed Income"),
        ("STIV", "Short-Term / Cash"),
        ("RE", "Real Estate (direct)"),
        ("COMM", "Commodity"),
        ("EC", None),
        (None, None),
    ],
)
def test_category_bucket(category, bucket) -> None:
    """Non-equity N-PORT categories bucket without a lookup."""
    assert category_bucket(category) == bucket


def test_sector_rollup_resolves_top_n_and_buckets_the_rest() -> None:
    """Only the heaviest rows resolve; the tail is Other (small)."""
    holdings = [
        {"name": "Gamma Ltd", "weight": 0.1, "asset_category": "EC"},
        {"name": "Alpha Corp", "weight": 0.5, "asset_category": "EC"},
        {"name": "Cash Sweep", "weight": 0.05, "asset_category": "STIV"},
        {"name": "Beta Inc", "weight": 0.3, "asset_category": "EC"},
        {"name": "Note 1", "weight": 0.05, "asset_category": "DBT"},
    ]
    sectors = {"Alpha Corp": "Technology"}  # Beta Inc does not resolve
    weights, counts = sector_rollup(
        holdings, sectors.get, weight_scale=0.5, top_n_resolve=2
    )
    # Sorted: Alpha .5 (idx0) Beta .3 (idx1) Gamma .1 (idx2, tail) ...
    assert weights == pytest.approx(
        {
            "Technology": 0.25,
            "Unknown": 0.15,
            "Other (small)": 0.05,
            "Short-Term / Cash": 0.025,
            "Fixed Income": 0.025,
        }
    )
    assert counts == {
        "Technology": 1,
        "Unknown": 1,
        "Other (small)": 1,
        "Short-Term / Cash": 1,
        "Fixed Income": 1,
    }


def test_basket_sector_view_composes_classes() -> None:
    """Each fund class contributes its own sector bucket."""
    sectors_by_name = {"Alpha Corp": "Technology", "Beta Inc": "Health Care"}
    sectors_by_symbol = {"SNGL": "Technology"}
    view = basket_sector_view(
        BASKET + [{"symbol": "MISS", "weight": 0.0}],
        holdings_for=_holdings_for,
        sector_for_name=sectors_by_name.get,
        sector_for_symbol=sectors_by_symbol.get,
        top_n_resolve=2,
        **CLASSES,
    )
    assert view.sectors == pytest.approx(
        {
            "Technology": 0.30 + 0.10,
            "Health Care": 0.15,
            "Other (small)": 0.05,
            "Fixed Income": 0.30,
            "Commodity": 0.10,
            "MISS": 0.0,
        }
    )
    assert view.unknown_count == 1  # Gamma Ltd fell into "Other (small)"


def test_concentration_two_equal_names() -> None:
    """Two equal names: HHI 0.5, effective-N 2."""
    result = concentration({"A": 0.5, "B": 0.5})
    assert result.hhi == pytest.approx(0.5)
    assert result.effective_n == pytest.approx(2.0)
    assert result.top1 == pytest.approx(0.5)
    assert result.top5 == pytest.approx(1.0)
    assert result.largest in {"A", "B"}
    assert result.kill_shot == pytest.approx(0.1)  # 20% drop on 0.5


def test_concentration_by_hand() -> None:
    """A seven-name book matches hand arithmetic."""
    weights = {f"N{i}": w for i, w in enumerate([0.4, 0.2, 0.1, 0.1, 0.1, 0.05, 0.05])}
    result = concentration(weights, kill_shot_drop=0.5)
    # 0.16 + 0.04 + 3 * 0.01 + 2 * 0.0025
    assert result.hhi == pytest.approx(0.235)
    assert result.effective_n == pytest.approx(1 / 0.235)
    assert result.top5 == pytest.approx(0.9)
    assert result.top10 == pytest.approx(1.0)
    assert (result.largest, result.largest_weight) == ("N0", 0.4)
    assert result.kill_shot == pytest.approx(0.2)


def test_concentration_of_nothing_has_no_effective_n() -> None:
    """An empty map has no effective-N rather than infinity."""
    result = concentration({})
    assert result.hhi == 0.0
    assert result.effective_n is None
    assert result.largest is None


def test_construction_refuses_thin_coverage() -> None:
    """Coverage below the threshold refuses to emit targets."""
    result = construction_targets({"A": 0.5, "B": 0.3}, min_coverage=0.9)
    assert result.refused
    assert result.targets is None
    assert result.coverage == pytest.approx(0.8)


def test_construction_caps_are_enforced_and_nothing_leaks() -> None:
    """Both caps hold and targets plus residual equal coverage."""
    effective = {"A": 0.30, "B": 0.20}
    effective.update({f"S{i}": 0.025 for i in range(20)})  # 0.5 spread thin
    result = construction_targets(
        effective, max_single_name=0.06, top5_cap=0.35, band_abs=0.01
    )
    assert not result.refused
    targets = result.targets
    assert targets is not None
    assert all(t["target"] <= 0.06 + 1e-9 for t in targets.values())
    top5 = sorted((t["target"] for t in targets.values()), reverse=True)[:5]
    assert sum(top5) <= 0.35 + 1e-9
    emitted = sum(t["target"] for t in targets.values())
    assert emitted + result.residual == pytest.approx(1.0)
    assert targets["A"]["status"] == "TRIM"
    assert targets["S0"]["status"] == "boost"
    assert result.capped_names == 2
    a = targets["A"]
    assert (a["band_lo"], a["band_hi"]) == pytest.approx(
        (a["target"] - 0.01, a["target"] + 0.01)
    )


def test_construction_saturated_book_reports_unplaceable_weight() -> None:
    """Weight with nowhere to go is reported, not dropped."""
    # Two names, each capped at 0.3: 0.4 can never be placed.
    result = construction_targets(
        {"A": 0.5, "B": 0.5}, max_single_name=0.3, top5_cap=1.0
    )
    assert result.residual == pytest.approx(0.4)
    assert sum(t["target"] for t in result.targets.values()) == pytest.approx(0.6)
