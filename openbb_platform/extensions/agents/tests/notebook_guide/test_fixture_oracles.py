"""Frozen scenarios and independent parity expectations (#2213, N03).

The expectations are hand-computed literals in the scenario files. These tests
recheck each one with separate, deliberately plain arithmetic, so a typo in a
fixture fails here rather than silently becoming the "truth" an MCP result is
later compared with. Nothing here calls an engine, a provider or a wrapper.
"""

# pylint: disable=redefined-outer-name

import socket
from decimal import Decimal
from pathlib import Path

import pytest

from .conftest import load_scenarios

REPO_ROOT = Path(__file__).resolve().parents[5]
TOLERANCE = 1e-12


def test_weighted_return_oracle(scenario_factory):
    """The plan's anchor case: two equal weights, one asset flat."""
    scenario = scenario_factory("two_asset_equal_weight")
    assert scenario.weights == {"asset_a": 0.5, "asset_b": 0.5}
    assert scenario.returns == {"asset_a": 0.10, "asset_b": 0.0}
    assert scenario.expected["weighted_return"] == 0.05


@pytest.mark.parametrize(
    "scenario_id", ["two_asset_equal_weight", "three_asset_weighted_return"]
)
def test_weighted_returns_recompute(scenario_factory, scenario_id):
    """Weights sum to one and the weighted return matches its expectation."""
    scenario = scenario_factory(scenario_id)
    assert abs(sum(scenario.weights.values()) - 1.0) < TOLERANCE
    weighted = sum(scenario.weights[a] * scenario.returns[a] for a in scenario.weights)
    assert abs(weighted - scenario.expected["weighted_return"]) < TOLERANCE


def test_paper_cash_is_conserved(scenario_factory):
    """Equity equals starting cash plus realized and unrealized P&L minus fees."""
    scenario = scenario_factory("paper_cash_conservation")
    cash = Decimal(scenario.starting_cash)
    quantity, cost_basis, realized, fees = 0, Decimal("0"), Decimal("0"), Decimal("0")
    for fill in scenario.fills:
        price, fee = Decimal(fill["price"]), Decimal(fill["fee"])
        fees += fee
        if fill["side"] == "buy":
            cash -= price * fill["quantity"] + fee
            cost_basis = (cost_basis * quantity + price * fill["quantity"]) / (
                quantity + fill["quantity"]
            )
            quantity += fill["quantity"]
        else:
            cash += price * fill["quantity"] - fee
            realized += (price - cost_basis) * fill["quantity"]
            quantity -= fill["quantity"]
    mark = Decimal(scenario.mark_price)
    unrealized = (mark - cost_basis) * quantity
    equity = cash + mark * quantity
    expected = scenario.expected
    assert cash == Decimal(expected["cash"])
    assert quantity == expected["position_quantity"]
    assert realized == Decimal(expected["realized_pnl"])
    assert unrealized == Decimal(expected["unrealized_pnl"])
    assert fees == Decimal(expected["fees"])
    assert equity == Decimal(expected["equity"])
    assert equity == Decimal(scenario.starting_cash) + realized + unrealized - fees


def test_invalid_orders_have_explicit_reasons(scenario_factory):
    """Each bad order is rejected for its own reason; the valid one is kept."""
    scenario = scenario_factory("invalid_orders")
    cash = Decimal(scenario.starting_cash)
    holdings = dict(scenario.holdings)
    rejected, accepted = {}, []
    for order in scenario.orders:
        price = Decimal(order["price"])
        if order["quantity"] <= 0:
            rejected[order["id"]] = "quantity must be positive"
        elif price <= 0:
            rejected[order["id"]] = "price must be positive"
        elif order["side"] == "sell" and order["quantity"] > holdings.get(
            order["asset"], 0
        ):
            rejected[order["id"]] = "quantity exceeds holding"
        elif order["side"] == "buy" and price * order["quantity"] > cash:
            rejected[order["id"]] = "cost exceeds available cash"
        else:
            accepted.append(order["id"])
            cash -= price * order["quantity"]
    assert rejected == scenario.expected["rejected"]
    assert accepted == scenario.expected["accepted"]
    assert cash == Decimal(scenario.expected["cash_after_accepted"])


def test_split_adjustment_changes_the_answer(scenario_factory):
    """An unadjusted split produces a large, wrong loss."""
    scenario = scenario_factory("split_adjusted_return")
    split = scenario.split
    adjusted = [
        close / split["ratio"] if index < split["index"] else close
        for index, close in enumerate(scenario.raw_close)
    ]
    assert adjusted == scenario.expected["adjusted_close"]
    total = adjusted[-1] / adjusted[0] - 1
    naive = scenario.raw_close[-1] / scenario.raw_close[0] - 1
    assert abs(total - scenario.expected["adjusted_total_return"]) < TOLERANCE
    assert abs(naive - scenario.expected["naive_raw_return"]) < TOLERANCE
    assert total > 0 > naive


def test_dividend_counts_in_total_return(scenario_factory):
    """A flat price with a dividend has zero price return but positive total."""
    scenario = scenario_factory("dividend_total_return")
    start, end = scenario.close[0], scenario.close[-1]
    price_return = end / start - 1
    total_return = (end - start + scenario.dividend["amount"]) / start
    assert price_return == scenario.expected["price_return"]
    assert abs(total_return - scenario.expected["total_return"]) < TOLERANCE


def test_missing_observation_is_reported_not_filled(scenario_factory):
    """A gap is named in the expectation, never replaced with a number."""
    scenario = scenario_factory("missing_observation")
    missing = [
        f"{asset}@{day}"
        for asset, series in scenario.returns.items()
        for day in scenario.dates
        if day not in series
    ]
    assert scenario.expected == {"status": "incomplete", "missing": missing}


def test_empty_period_is_empty_not_zero(scenario_factory):
    """No observations means no result, not a 0% return."""
    scenario = scenario_factory("empty_period")
    assert scenario.observations == []
    assert scenario.expected["status"] == "empty"
    assert "return" not in scenario.expected


def test_money_is_exact_in_decimal(scenario_factory):
    """Money expectations are exact decimal strings, not float approximations."""
    scenario = scenario_factory("decimal_money_precision")
    fills = sum((Decimal(a) for a in scenario.fill_amounts), Decimal("0"))
    fees = sum((Decimal(a) for a in scenario.fee_amounts), Decimal("0"))
    assert str(fills) == scenario.expected["fills_total"]
    assert str(fees) == scenario.expected["fees_total"]
    assert sum(float(a) for a in scenario.fee_amounts) != 0.30


def test_synthetic_universe_is_internally_consistent(scenario_factory):
    """Basket weights sum to one and every series spans the calendar."""
    scenario = scenario_factory("synthetic_universe")
    weights = scenario.basket_weights
    assert abs(sum(weights.values()) - scenario.expected["weights_sum"]) < TOLERANCE
    for series in scenario.close.values():
        assert (
            len(series) == len(scenario.calendar) == scenario.expected["observations"]
        )
        assert (
            abs(series[-1] / series[0] - 1 - scenario.expected["asset_total_return"])
            < TOLERANCE
        )
    basket = sum(weights[a] * (s[-1] / s[0] - 1) for a, s in scenario.close.items())
    assert abs(basket - scenario.expected["basket_total_return"]) < TOLERANCE
    assert all(not name[-1].isdigit() for name in weights), "placeholders, not tickers"


def test_provider_field_expectations_match_the_provider_models(scenario_factory):
    """Frozen per-provider field availability still matches the real models."""
    # pylint: disable=import-outside-toplevel
    fmp_cached = pytest.importorskip("openbb_fmp_cached")
    yfinance = pytest.importorskip("openbb_yfinance")
    providers = {
        "fmp_cached": fmp_cached.fmp_cached_provider,
        "yfinance": yfinance.yfinance_provider,
    }
    scenario = scenario_factory("provider_field_availability")
    for model, expected in scenario.expected.items():
        fields = {
            name: set(provider.fetcher_dict[model].data_type.model_fields)
            for name, provider in providers.items()
        }
        probed = set(
            expected["fmp_cached_only"] + expected["yfinance_only"] + expected["both"]
        )
        assert {
            f
            for f in probed
            if f in fields["fmp_cached"] and f not in fields["yfinance"]
        } == set(expected["fmp_cached_only"]), model
        assert {
            f
            for f in probed
            if f in fields["yfinance"] and f not in fields["fmp_cached"]
        } == set(expected["yfinance_only"]), model
        assert {
            f for f in probed if f in fields["fmp_cached"] and f in fields["yfinance"]
        } == set(expected["both"]), model


def test_every_story_has_a_scenario():
    """All 25 stories have deterministic inputs (FR-05, AC-N03)."""
    # pylint: disable=import-outside-toplevel
    from scripts.notebook_story_inventory import inventory_notebooks

    stories = {
        source.story_id for source in inventory_notebooks(REPO_ROOT / "notebooks")
    }
    covered = {
        story for scenario in load_scenarios().values() for story in scenario.stories
    }
    assert stories <= covered
    assert covered <= stories, "a scenario names a story that does not exist"


def test_scenarios_are_synthetic_and_carry_provenance():
    """Every scenario declares synthetic, hand-computed, redistributable data."""
    scenarios = load_scenarios()
    assert len(scenarios) >= 10
    for scenario in scenarios.values():
        assert scenario.provenance.kind == "synthetic"
        assert scenario.provenance.redistributable is True


def test_network_is_denied():
    """The autouse guard really blocks connections."""
    with pytest.raises(AssertionError, match="must not open network"):
        socket.create_connection(("127.0.0.1", 9))


def test_home_directory_is_isolated(isolated_home):
    """Nothing can read the operator's real home directory."""
    assert Path.home() == isolated_home
    assert not (Path.home() / ".portfolio_importer").exists()
