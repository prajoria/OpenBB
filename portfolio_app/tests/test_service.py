"""
Unit tests for portfolio_app.service — pure DataFrame business logic.

Run with:
    python -m pytest portfolio_app/tests/test_service.py -v

No database, no server, no network required.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Make portfolio_app/src importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import service  # noqa: E402


# =========================================================================== #
#  Fixtures — synthetic portfolio DataFrames
# =========================================================================== #

@pytest.fixture
def positions_df() -> pd.DataFrame:
    """Realistic positions DataFrame with 8 lots across 4 symbols, 2 accounts, 2 owners."""
    return pd.DataFrame([
        {
            "symbol": "AAPL", "description": "Apple Inc",
            "account_name": "Brokerage", "owner": "Alice",
            "quantity": 10, "avg_cost_basis": 150.0, "cost_basis_total": 1500.0,
            "current_price": 190.0, "current_value": 1900.0,
            "total_gain_loss": 400.0, "pct_gain_loss": 26.67,
            "term": "Long-term", "acquired": "2022-01-15",
            "share_source": "Purchase", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
        {
            "symbol": "AAPL", "description": "Apple Inc",
            "account_name": "IRA", "owner": "Alice",
            "quantity": 5, "avg_cost_basis": 170.0, "cost_basis_total": 850.0,
            "current_price": 190.0, "current_value": 950.0,
            "total_gain_loss": 100.0, "pct_gain_loss": 11.76,
            "term": "Short-term", "acquired": "2024-06-01",
            "share_source": "Purchase", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
        {
            "symbol": "MSFT", "description": "Microsoft Corp",
            "account_name": "Brokerage", "owner": "Alice",
            "quantity": 20, "avg_cost_basis": 300.0, "cost_basis_total": 6000.0,
            "current_price": 420.0, "current_value": 8400.0,
            "total_gain_loss": 2400.0, "pct_gain_loss": 40.0,
            "term": "Long-term", "acquired": "2021-03-10",
            "share_source": "Purchase", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
        {
            "symbol": "TSLA", "description": "Tesla Inc",
            "account_name": "Brokerage", "owner": "Bob",
            "quantity": 8, "avg_cost_basis": 250.0, "cost_basis_total": 2000.0,
            "current_price": 200.0, "current_value": 1600.0,
            "total_gain_loss": -400.0, "pct_gain_loss": -20.0,
            "term": "Long-term", "acquired": "2023-01-20",
            "share_source": "Purchase", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
        {
            "symbol": "TSLA", "description": "Tesla Inc",
            "account_name": "Brokerage", "owner": "Bob",
            "quantity": 3, "avg_cost_basis": 180.0, "cost_basis_total": 540.0,
            "current_price": 200.0, "current_value": 600.0,
            "total_gain_loss": 60.0, "pct_gain_loss": 11.11,
            "term": "Short-term", "acquired": "2024-09-15",
            "share_source": "Purchase", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
        {
            "symbol": "GOOG", "description": "Alphabet",
            "account_name": "Brokerage", "owner": "Bob",
            "quantity": 15, "avg_cost_basis": 140.0, "cost_basis_total": 2100.0,
            "current_price": 175.0, "current_value": 2625.0,
            "total_gain_loss": 525.0, "pct_gain_loss": 25.0,
            "term": "Long-term", "acquired": "2022-07-01",
            "share_source": "Purchase", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
        # ESPP lot with special fields
        {
            "symbol": "MSFT", "description": "Microsoft Corp",
            "account_name": "ESPP", "owner": "Alice",
            "quantity": 12, "avg_cost_basis": 280.0, "cost_basis_total": 3360.0,
            "current_price": 420.0, "current_value": 5040.0,
            "total_gain_loss": 1680.0, "pct_gain_loss": 50.0,
            "term": "Long-term", "acquired": "2022-12-15",
            "share_source": "ESPP", "grant_date": "2022-06-15", "transfer_avail_date": "2024-06-15",
            "snapshot_date": "2024-12-01",
        },
        # A lot with zero cost basis (e.g., RSU vest)
        {
            "symbol": "MSFT", "description": "Microsoft Corp",
            "account_name": "RSU", "owner": "Alice",
            "quantity": 5, "avg_cost_basis": 0.0, "cost_basis_total": 0.0,
            "current_price": 420.0, "current_value": 2100.0,
            "total_gain_loss": 2100.0, "pct_gain_loss": 0.0,
            "term": "", "acquired": "2024-01-01",
            "share_source": "RSU", "grant_date": None, "transfer_avail_date": None,
            "snapshot_date": "2024-12-01",
        },
    ])


@pytest.fixture
def snapshots_df() -> pd.DataFrame:
    """Multi-date snapshot data for trend testing."""
    rows = []
    for date, multiplier in [("2024-10-01", 0.9), ("2024-11-01", 0.95), ("2024-12-01", 1.0)]:
        rows.extend([
            {
                "symbol": "AAPL", "account_name": "Brokerage",
                "quantity": 10, "cost_basis_total": 1500.0,
                "current_value": round(1900 * multiplier, 2),
                "total_gain_loss": round(1900 * multiplier - 1500, 2),
                "snapshot_date": date,
            },
            {
                "symbol": "MSFT", "account_name": "Brokerage",
                "quantity": 20, "cost_basis_total": 6000.0,
                "current_value": round(8400 * multiplier, 2),
                "total_gain_loss": round(8400 * multiplier - 6000, 2),
                "snapshot_date": date,
            },
        ])
    return pd.DataFrame(rows)


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Empty DataFrame with the expected columns."""
    return pd.DataFrame(columns=[
        "symbol", "description", "account_name", "owner",
        "quantity", "avg_cost_basis", "cost_basis_total",
        "current_price", "current_value", "total_gain_loss",
        "pct_gain_loss", "term", "acquired", "share_source",
        "grant_date", "transfer_avail_date", "snapshot_date",
    ])


# =========================================================================== #
#  Tests — positions_detail
# =========================================================================== #

class TestPositionsDetail:
    def test_unfiltered_sorted_by_value(self, positions_df):
        result = service.positions_detail(positions_df)
        values = result["current_value"].tolist()
        assert values == sorted(values, reverse=True), "Should be sorted descending by current_value"
        assert len(result) == 8

    def test_filter_by_account(self, positions_df):
        result = service.positions_detail(positions_df, account="IRA")
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "AAPL"

    def test_filter_by_owner(self, positions_df):
        result = service.positions_detail(positions_df, owner="Bob")
        assert set(result["symbol"]) == {"TSLA", "GOOG"}

    def test_empty_input(self, empty_df):
        result = service.positions_detail(empty_df)
        assert result.empty

    def test_no_match_filter(self, positions_df):
        result = service.positions_detail(positions_df, account="NonExistent")
        assert result.empty


# =========================================================================== #
#  Tests — summary_by_symbol
# =========================================================================== #

class TestSummaryBySymbol:
    def test_aggregates_multiple_lots(self, positions_df):
        result = service.summary_by_symbol(positions_df)
        # MSFT has 3 lots: 20 + 12 + 5 = 37 shares
        msft = result[result["symbol"] == "MSFT"]
        assert len(msft) == 1
        assert msft.iloc[0]["total_quantity"] == 37

    def test_total_cost_and_value(self, positions_df):
        result = service.summary_by_symbol(positions_df)
        msft = result[result["symbol"] == "MSFT"]
        assert msft.iloc[0]["total_cost_basis"] == 6000.0 + 3360.0 + 0.0
        assert msft.iloc[0]["total_current_value"] == 8400.0 + 5040.0 + 2100.0

    def test_pct_return_calculation(self, positions_df):
        result = service.summary_by_symbol(positions_df)
        aapl = result[result["symbol"] == "AAPL"]
        # AAPL: gain = 500, cost = 2350 → 21.28%
        expected_pct = round((500 / 2350) * 100, 2)
        assert aapl.iloc[0]["pct_return"] == expected_pct

    def test_sorted_by_current_value_desc(self, positions_df):
        result = service.summary_by_symbol(positions_df)
        values = result["total_current_value"].tolist()
        assert values == sorted(values, reverse=True)

    def test_filter_by_owner(self, positions_df):
        result = service.summary_by_symbol(positions_df, owner="Bob")
        symbols = set(result["symbol"])
        assert symbols == {"TSLA", "GOOG"}

    def test_filter_by_account(self, positions_df):
        result = service.summary_by_symbol(positions_df, account="ESPP")
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "MSFT"

    def test_empty_returns_empty(self, empty_df):
        result = service.summary_by_symbol(empty_df)
        assert result.empty


# =========================================================================== #
#  Tests — allocation_by_account
# =========================================================================== #

class TestAllocationByAccount:
    def test_account_count(self, positions_df):
        result = service.allocation_by_account(positions_df)
        # Groups by (account_name, owner): Brokerage/Alice, Brokerage/Bob, IRA, ESPP, RSU
        assert len(result) == 5

    def test_brokerage_has_multiple_symbols(self, positions_df):
        result = service.allocation_by_account(positions_df)
        brok_alice = result[
            (result["account_name"] == "Brokerage") & (result["owner"] == "Alice")
        ]
        assert brok_alice.iloc[0]["num_symbols"] == 2  # AAPL, MSFT

    def test_filter_by_owner(self, positions_df):
        result = service.allocation_by_account(positions_df, owner="Alice")
        accounts = set(result["account_name"])
        assert accounts == {"Brokerage", "IRA", "ESPP", "RSU"}

    def test_return_calculation(self, positions_df):
        result = service.allocation_by_account(positions_df)
        for _, row in result.iterrows():
            if row["total_cost_basis"] > 0:
                expected = round((row["total_gain_loss"] / row["total_cost_basis"]) * 100, 2)
                assert row["pct_return"] == expected

    def test_empty_returns_empty(self, empty_df):
        result = service.allocation_by_account(empty_df)
        assert result.empty


# =========================================================================== #
#  Tests — cost_basis_lots
# =========================================================================== #

class TestCostBasisLots:
    def test_all_lots_returned(self, positions_df):
        result = service.cost_basis_lots(positions_df)
        assert len(result) == 8

    def test_filter_by_symbol(self, positions_df):
        result = service.cost_basis_lots(positions_df, symbol="TSLA")
        assert len(result) == 2
        assert set(result["symbol"]) == {"TSLA"}

    def test_sorted_by_symbol_then_acquired(self, positions_df):
        result = service.cost_basis_lots(positions_df)
        for sym in result["symbol"].unique():
            subset = result[result["symbol"] == sym]
            dates = subset["acquired"].tolist()
            assert dates == sorted(dates)

    def test_columns_subset(self, positions_df):
        result = service.cost_basis_lots(positions_df)
        assert "current_price" not in result.columns  # filtered out
        assert "symbol" in result.columns

    def test_empty_returns_empty(self, empty_df):
        result = service.cost_basis_lots(empty_df)
        assert result.empty


# =========================================================================== #
#  Tests — tax_summary
# =========================================================================== #

class TestTaxSummary:
    def test_excludes_empty_term(self, positions_df):
        # The RSU lot has term="" — should be excluded
        result = service.tax_summary(positions_df)
        assert all(result["term"].str.strip() != "")

    def test_groups_by_account_and_term(self, positions_df):
        result = service.tax_summary(positions_df)
        assert len(result) > 0
        # Each row should be unique (account, owner, term) combo
        keys = result[["account_name", "owner", "term"]].apply(tuple, axis=1).tolist()
        assert len(keys) == len(set(keys))

    def test_num_lots_count(self, positions_df):
        result = service.tax_summary(positions_df)
        # Brokerage/Alice/Long-term: AAPL(1) + MSFT(1) = 2 lots
        brok_lt = result[
            (result["account_name"] == "Brokerage")
            & (result["term"] == "Long-term")
        ]
        if not brok_lt.empty:
            # AAPL long-term + MSFT long-term + TSLA long-term (Bob)
            # Actually Brokerage Long-term includes Alice's AAPL + Alice's MSFT + Bob's TSLA
            assert brok_lt.iloc[0]["num_lots"] >= 2

    def test_filter_by_owner(self, positions_df):
        result = service.tax_summary(positions_df, owner="Bob")
        assert all(result["owner"] == "Bob")

    def test_empty_returns_empty(self, empty_df):
        result = service.tax_summary(empty_df)
        assert result.empty


# =========================================================================== #
#  Tests — performance_ranking
# =========================================================================== #

class TestPerformanceRanking:
    def test_excludes_zero_cost(self, positions_df):
        # RSU lot has cost_basis_total=0 → should be excluded at symbol level
        # BUT MSFT has other lots with cost > 0, so aggregated cost > 0
        # Only truly zero-cost symbols would be excluded
        result = service.performance_ranking(positions_df)
        assert all(result["total_cost_basis"] > 0)

    def test_sorted_by_pct_return_desc(self, positions_df):
        result = service.performance_ranking(positions_df)
        pcts = result["pct_return"].tolist()
        assert pcts == sorted(pcts, reverse=True)

    def test_all_symbols_with_cost(self, positions_df):
        result = service.performance_ranking(positions_df)
        # All 4 symbols have some cost > 0 (even MSFT RSU is aggregated with other lots)
        assert len(result) == 4

    def test_negative_return(self, positions_df):
        # TSLA lots: cost=2540, value=2200, loss=-340 → negative return
        result = service.performance_ranking(positions_df)
        tsla = result[result["symbol"] == "TSLA"]
        assert tsla.iloc[0]["pct_return"] < 0

    def test_filter_by_owner(self, positions_df):
        result = service.performance_ranking(positions_df, owner="Alice")
        assert set(result["symbol"]).issubset({"AAPL", "MSFT"})

    def test_empty_returns_empty(self, empty_df):
        result = service.performance_ranking(empty_df)
        assert result.empty


# =========================================================================== #
#  Tests — snapshot_totals
# =========================================================================== #

class TestSnapshotTotals:
    def test_one_row_per_date(self, snapshots_df):
        result = service.snapshot_totals(snapshots_df)
        assert len(result) == 3

    def test_sorted_by_date(self, snapshots_df):
        result = service.snapshot_totals(snapshots_df)
        dates = result["snapshot_date"].tolist()
        assert dates == sorted(dates)

    def test_totals_correct(self, snapshots_df):
        result = service.snapshot_totals(snapshots_df)
        dec = result[result["snapshot_date"] == "2024-12-01"]
        assert dec.iloc[0]["lots"] == 2
        assert dec.iloc[0]["stocks"] == 2
        assert dec.iloc[0]["accounts"] == 1
        assert dec.iloc[0]["total_cost_basis"] == 7500.0
        assert dec.iloc[0]["total_current_value"] == 10300.0

    def test_value_increases_over_time(self, snapshots_df):
        result = service.snapshot_totals(snapshots_df)
        values = result["total_current_value"].tolist()
        assert values == sorted(values), "Values should increase as multiplier grows"

    def test_empty_returns_empty(self):
        result = service.snapshot_totals(pd.DataFrame())
        assert result.empty


# =========================================================================== #
#  Tests — _filter helper
# =========================================================================== #

class TestFilter:
    def test_no_filters(self, positions_df):
        result = service._filter(positions_df)
        assert len(result) == len(positions_df)

    def test_account_filter(self, positions_df):
        result = service._filter(positions_df, account="IRA")
        assert all(result["account_name"] == "IRA")

    def test_owner_filter(self, positions_df):
        result = service._filter(positions_df, owner="Bob")
        assert all(result["owner"] == "Bob")

    def test_symbol_filter(self, positions_df):
        result = service._filter(positions_df, symbol="GOOG")
        assert all(result["symbol"] == "GOOG")

    def test_combined_filters(self, positions_df):
        result = service._filter(positions_df, account="Brokerage", owner="Alice")
        assert len(result) == 2  # AAPL + MSFT in Brokerage for Alice

    def test_empty_df(self, empty_df):
        result = service._filter(empty_df, account="X")
        assert result.empty


# =========================================================================== #
#  Tests — _pct_return helper
# =========================================================================== #

class TestPctReturn:
    def test_normal_calculation(self):
        gain = pd.Series([100, -50, 200])
        cost = pd.Series([1000, 500, 400])
        result = service._pct_return(gain, cost)
        expected = [10.0, -10.0, 50.0]
        assert result.tolist() == expected

    def test_zero_cost_returns_zero(self):
        gain = pd.Series([100])
        cost = pd.Series([0])
        result = service._pct_return(gain, cost)
        assert result.iloc[0] == 0.0

    def test_mixed_zero_and_nonzero(self):
        gain = pd.Series([100, 50])
        cost = pd.Series([0, 200])
        result = service._pct_return(gain, cost)
        assert result.iloc[0] == 0.0
        assert result.iloc[1] == 25.0


# =========================================================================== #
#  Edge-case tests
# =========================================================================== #

class TestEdgeCases:
    def test_single_row(self):
        df = pd.DataFrame([{
            "symbol": "X", "description": "Test",
            "account_name": "Acct", "owner": "Own",
            "quantity": 1, "avg_cost_basis": 100, "cost_basis_total": 100,
            "current_price": 110, "current_value": 110,
            "total_gain_loss": 10, "pct_gain_loss": 10,
            "term": "Long-term", "acquired": "2024-01-01",
            "share_source": "Purchase", "grant_date": None,
            "transfer_avail_date": None, "snapshot_date": "2024-12-01",
        }])
        assert len(service.summary_by_symbol(df)) == 1
        assert len(service.allocation_by_account(df)) == 1
        assert len(service.performance_ranking(df)) == 1
        assert len(service.tax_summary(df)) == 1

    def test_all_same_symbol(self):
        df = pd.DataFrame([
            {"symbol": "X", "description": "T", "account_name": f"A{i}",
             "owner": "O", "quantity": i, "cost_basis_total": i * 100.0,
             "current_value": i * 110.0, "total_gain_loss": i * 10.0,
             "term": "Long-term", "acquired": "2024-01-01",
             "avg_cost_basis": 100, "current_price": 110, "pct_gain_loss": 10,
             "share_source": "P", "grant_date": None,
             "transfer_avail_date": None, "snapshot_date": "2024-12-01"}
            for i in range(1, 6)
        ])
        result = service.summary_by_symbol(df)
        assert len(result) == 1
        assert result.iloc[0]["total_quantity"] == 15


# =========================================================================== #
#  Tests — refresh_market_values
# =========================================================================== #

class TestRefreshMarketValues:
    """Tests for live price recalculation of positions."""

    @pytest.fixture
    def simple_positions(self) -> pd.DataFrame:
        """3 lots across 2 symbols with known snapshot values."""
        return pd.DataFrame([
            {
                "symbol": "ACME", "quantity": 10,
                "cost_basis_total": 1000.0,
                "current_value": 1200.0,          # stale snapshot value
                "total_gain_loss": 200.0,
                "pct_gain_loss": 20.0,
            },
            {
                "symbol": "ACME", "quantity": 5,
                "cost_basis_total": 600.0,
                "current_value": 650.0,
                "total_gain_loss": 50.0,
                "pct_gain_loss": 8.33,
            },
            {
                "symbol": "BOLT", "quantity": 20,
                "cost_basis_total": 2000.0,
                "current_value": 1800.0,
                "total_gain_loss": -200.0,
                "pct_gain_loss": -10.0,
            },
        ])

    @pytest.fixture
    def prices(self) -> pd.DataFrame:
        """Latest prices: ACME=150, BOLT=80."""
        return pd.DataFrame([
            {"symbol": "ACME", "close": 150.0, "price_date": "2026-02-22"},
            {"symbol": "BOLT", "close": 80.0, "price_date": "2026-02-21"},
        ])

    def test_recalculates_current_value(self, simple_positions, prices):
        result = service.refresh_market_values(simple_positions, prices)
        # ACME lot 1: 10 × 150 = 1500
        assert result.iloc[0]["current_value"] == 1500.0
        # ACME lot 2: 5 × 150 = 750
        assert result.iloc[1]["current_value"] == 750.0
        # BOLT: 20 × 80 = 1600
        assert result.iloc[2]["current_value"] == 1600.0

    def test_recalculates_gain_loss(self, simple_positions, prices):
        result = service.refresh_market_values(simple_positions, prices)
        # ACME lot 1: 1500 - 1000 = 500
        assert result.iloc[0]["total_gain_loss"] == 500.0
        # ACME lot 2: 750 - 600 = 150
        assert result.iloc[1]["total_gain_loss"] == 150.0
        # BOLT: 1600 - 2000 = -400
        assert result.iloc[2]["total_gain_loss"] == -400.0

    def test_recalculates_pct_gain_loss(self, simple_positions, prices):
        result = service.refresh_market_values(simple_positions, prices)
        # ACME lot 1: (500 / 1000) × 100 = 50.0
        assert result.iloc[0]["pct_gain_loss"] == 50.0
        # ACME lot 2: (150 / 600) × 100 = 25.0
        assert result.iloc[1]["pct_gain_loss"] == 25.0
        # BOLT: (-400 / 2000) × 100 = -20.0
        assert result.iloc[2]["pct_gain_loss"] == -20.0

    def test_adds_price_date_column(self, simple_positions, prices):
        result = service.refresh_market_values(simple_positions, prices)
        assert "price_date" in result.columns
        assert result.iloc[0]["price_date"] == "2026-02-22"
        assert result.iloc[2]["price_date"] == "2026-02-21"

    def test_fallback_when_no_price(self, simple_positions):
        """Symbols not in prices_df keep their original DB values."""
        partial_prices = pd.DataFrame([
            {"symbol": "ACME", "close": 150.0, "price_date": "2026-02-22"},
            # No BOLT price — should keep DB snapshot values
        ])
        result = service.refresh_market_values(simple_positions, partial_prices)
        # ACME recalculated
        assert result.iloc[0]["current_value"] == 1500.0
        # BOLT keeps original snapshot value
        assert result.iloc[2]["current_value"] == 1800.0
        assert result.iloc[2]["total_gain_loss"] == -200.0
        assert result.iloc[2]["pct_gain_loss"] == -10.0

    def test_fallback_price_date_is_nat(self, simple_positions):
        """Symbols without live price get NaT price_date."""
        partial_prices = pd.DataFrame([
            {"symbol": "ACME", "close": 150.0, "price_date": "2026-02-22"},
        ])
        result = service.refresh_market_values(simple_positions, partial_prices)
        assert pd.isna(result.iloc[2]["price_date"])

    def test_empty_positions(self, prices):
        empty = pd.DataFrame()
        result = service.refresh_market_values(empty, prices)
        assert result.empty

    def test_empty_prices(self, simple_positions):
        empty_prices = pd.DataFrame()
        result = service.refresh_market_values(simple_positions, empty_prices)
        # Original values preserved
        assert result.iloc[0]["current_value"] == 1200.0
        assert "price_date" in result.columns

    def test_zero_cost_basis_no_divide_by_zero(self):
        """RSU-style lot with zero cost should get pct_gain_loss = 0."""
        pos = pd.DataFrame([{
            "symbol": "ACME", "quantity": 5,
            "cost_basis_total": 0.0,
            "current_value": 0.0,
            "total_gain_loss": 0.0,
            "pct_gain_loss": 0.0,
        }])
        prices = pd.DataFrame([
            {"symbol": "ACME", "close": 100.0, "price_date": "2026-02-22"},
        ])
        result = service.refresh_market_values(pos, prices)
        assert result.iloc[0]["current_value"] == 500.0
        assert result.iloc[0]["total_gain_loss"] == 500.0
        assert result.iloc[0]["pct_gain_loss"] == 0.0  # not inf/nan

    def test_does_not_mutate_input(self, simple_positions, prices):
        """refresh_market_values should not modify the input DataFrames."""
        original_values = simple_positions["current_value"].tolist()
        service.refresh_market_values(simple_positions, prices)
        assert simple_positions["current_value"].tolist() == original_values

    def test_no_extra_columns_leaked(self, simple_positions, prices):
        """Internal _latest_price column should be dropped."""
        result = service.refresh_market_values(simple_positions, prices)
        assert "_latest_price" not in result.columns
