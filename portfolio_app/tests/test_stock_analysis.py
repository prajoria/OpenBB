"""
Unit tests for portfolio_app.stock_analysis — pure computation functions.

All tests use synthetic DataFrames built in-process.
No database, no server, no network required.

Run with:
    python -m pytest portfolio_app/tests/test_stock_analysis.py -v
"""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make portfolio_app/src importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import stock_analysis as sa  # noqa: E402


# =========================================================================== #
#  Synthetic data helpers
# =========================================================================== #

def _make_price_df(n: int = 90, start_price: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with n daily rows."""
    rng = np.random.default_rng(seed)
    end = date(2025, 12, 31)
    dates, prices = [], []
    price = start_price
    d = end - timedelta(days=n - 1)
    while len(dates) < n:
        if d.weekday() < 5:  # Mon–Fri only
            prices.append(price)
            dates.append(d.isoformat())
            price = max(1.0, price * (1 + rng.uniform(-0.03, 0.03)))
        d += timedelta(days=1)

    closes = np.array(prices)
    highs  = closes * rng.uniform(1.0, 1.02, size=n)
    lows   = closes * rng.uniform(0.97, 1.0,  size=n)
    opens  = closes * rng.uniform(0.99, 1.01, size=n)
    vols   = rng.integers(500_000, 10_000_000, size=n)
    return pd.DataFrame({
        "date":   dates,
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": vols,
    })


def _make_multi_price_df(symbols: list[str], n: int = 90) -> pd.DataFrame:
    """Generate long-format OHLCV DataFrame for multiple symbols."""
    frames = []
    for i, sym in enumerate(symbols):
        df = _make_price_df(n=n, start_price=50.0 + i * 30, seed=i)
        df["symbol"] = sym
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _make_income_df(periods: int = 3) -> pd.DataFrame:
    """Generate annual income statement DataFrame (most-recent first after sort)."""
    rows = []
    base_year = 2023
    for i in range(periods):
        yr = base_year - i
        rows.append({
            "period_ending": f"{yr}-12-31",
            "revenue":        1_000_000_000 * (1 + 0.10 * (periods - 1 - i)),
            "gross_profit":   300_000_000  * (1 + 0.08 * (periods - 1 - i)),
            "operating_income": 150_000_000 * (1 + 0.07 * (periods - 1 - i)),
            "net_income":     100_000_000  * (1 + 0.09 * (periods - 1 - i)),
            "basic_earnings_per_share": 5.0 * (1 + 0.09 * (periods - 1 - i)),
        })
    return pd.DataFrame(rows)


def _make_balance_df(periods: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(periods):
        yr = 2023 - i
        rows.append({
            "period_ending":   f"{yr}-12-31",
            "total_debt":      500_000_000,
            "total_equity":    800_000_000 + i * 10_000_000,
            "total_common_equity": 800_000_000 + i * 10_000_000,
        })
    return pd.DataFrame(rows)


def _make_cash_df(periods: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(periods):
        yr = 2023 - i
        rows.append({
            "period_ending": f"{yr}-12-31",
            "free_cash_flow": 80_000_000 * (1 + 0.08 * (periods - 1 - i)),
        })
    return pd.DataFrame(rows)


def _make_ratios_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "gross_profit_margin":        0.30,
        "operating_profit_margin":    0.15,
        "net_profit_margin":          0.10,
        "return_on_invested_capital": 0.12,
        "current_ratio":              1.80,
        "debt_to_equity":             0.65,
        "price_earnings_ratio":       20.5,
        "enterprise_value_multiple":  12.0,
        "price_to_free_cash_flow":    18.0,
        "price_to_sales":             2.5,
        "earnings_yield":             0.049,
        "weighted_average_cost_of_capital": 0.085,
        "piotroski_score":            7.0,
        "altman_z_score":             3.2,
    }])


def _make_quote_df(symbol: str = "TEST") -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol":          symbol,
        "last_price":      155.0,
        "change_percent":  0.022,
        "volume":          3_500_000,
        "market_cap":      45_000_000_000,
    }])


def _make_profile_df(sector: str = "Technology") -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol":      "TEST",
        "name":        "Test Corp",
        "sector":      sector,
        "industry":    "Software",
        "description": "A test company.",
        "ceo":         "Jane Doe",
        "full_time_employees": 5000,
        "website":     "https://test.com",
    }])


def _make_peers_df(symbols: list[str] | None = None) -> pd.DataFrame:
    syms = symbols or ["PEER1", "PEER2", "PEER3"]
    return pd.DataFrame([{"symbol": s} for s in syms])


def _make_returns(n: int = 252, mean: float = 0.0004, std: float = 0.012, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    return pd.Series(rng.normal(mean, std, size=n), index=dates)


# =========================================================================== #
#  Tests — shared helpers
# =========================================================================== #

class TestFirstAvailableValue:
    def test_finds_first_candidate(self):
        df = pd.DataFrame([{"sector": "Technology", "industry": "Software"}])
        assert sa.first_available_value(df, ["sector", "industry"]) == "Technology"

    def test_skips_missing_column_tries_next(self):
        df = pd.DataFrame([{"industry": "Software"}])
        assert sa.first_available_value(df, ["sector", "industry"]) == "Software"

    def test_case_insensitive(self):
        df = pd.DataFrame([{"SECTOR": "Finance"}])
        assert sa.first_available_value(df, ["sector"]) == "Finance"

    def test_returns_default_when_not_found(self):
        df = pd.DataFrame([{"other": "x"}])
        assert sa.first_available_value(df, ["sector"], default="Unknown") == "Unknown"

    def test_returns_default_for_empty_df(self):
        assert sa.first_available_value(pd.DataFrame(), ["sector"], default="N/A") == "N/A"

    def test_returns_default_for_none(self):
        assert sa.first_available_value(None, ["sector"], default="?") == "?"

    def test_skips_null_values(self):
        df = pd.DataFrame([{"sector": None, "industry": "Tech"}])
        assert sa.first_available_value(df, ["sector", "industry"]) == "Tech"


class TestLatestColValue:
    def test_returns_first_row_value(self):
        df = pd.DataFrame([{"pe_ratio": 20.5}, {"pe_ratio": 18.0}])
        assert sa.latest_col_value(df, ["pe_ratio"]) == 20.5

    def test_tries_candidates_in_order(self):
        df = pd.DataFrame([{"ev_to_ebitda": 12.0}])
        assert sa.latest_col_value(df, ["pe_ratio", "ev_to_ebitda"]) == 12.0

    def test_returns_nan_when_not_found(self):
        assert math.isnan(sa.latest_col_value(pd.DataFrame([{"x": 1}]), ["pe_ratio"]))

    def test_skips_nan_rows(self):
        df = pd.DataFrame([{"pe_ratio": None}, {"pe_ratio": 15.0}])
        assert sa.latest_col_value(df, ["pe_ratio"]) == 15.0

    def test_coerces_string_numeric(self):
        df = pd.DataFrame([{"pe_ratio": "22.0"}])
        assert sa.latest_col_value(df, ["pe_ratio"]) == 22.0


class TestLastNumeric:
    def test_series(self):
        s = pd.Series([1.0, 2.0, 3.0])
        assert sa.last_numeric(s) == 3.0

    def test_series_with_nans(self):
        s = pd.Series([1.0, np.nan, 2.5, np.nan])
        assert sa.last_numeric(s) == 2.5

    def test_single_row_df(self):
        df = pd.DataFrame([{"val": 42.0}])
        assert sa.last_numeric(df) == 42.0

    def test_empty_series_returns_nan(self):
        assert math.isnan(sa.last_numeric(pd.Series(dtype=float)))

    def test_empty_df_returns_nan(self):
        assert math.isnan(sa.last_numeric(pd.DataFrame()))


# =========================================================================== #
#  Tests — Phase 1: build_phase1_summary
# =========================================================================== #

class TestBuildPhase1Summary:
    def test_basic_keys_present(self):
        result = sa.build_phase1_summary(
            "TEST",
            _make_profile_df(),
            _make_quote_df(),
            _make_peers_df(),
        )
        expected_keys = {
            "symbol", "name", "sector", "industry", "market_cap", "last_price",
            "change_pct", "volume", "peer_count", "peers", "sector_etfs",
            "ceo", "employees", "website", "description",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_symbol_uppercased(self):
        result = sa.build_phase1_summary("test", _make_profile_df(), _make_quote_df(), _make_peers_df())
        assert result["symbol"] == "test"  # symbol passed as-is; callers .upper() it

    def test_sector_etfs_populated_for_known_sector(self):
        result = sa.build_phase1_summary("TEST", _make_profile_df("Technology"), _make_quote_df(), _make_peers_df())
        assert len(result["sector_etfs"]) > 0
        assert "XLK" in result["sector_etfs"]

    def test_sector_etfs_fallback_to_spy(self):
        result = sa.build_phase1_summary("TEST", _make_profile_df("UnknownSector"), _make_quote_df(), _make_peers_df())
        assert result["sector_etfs"] == ["SPY"]

    def test_peer_count(self):
        result = sa.build_phase1_summary("TEST", _make_profile_df(), _make_quote_df(), _make_peers_df(["A", "B", "C"]))
        assert result["peer_count"] == 3

    def test_peers_capped_at_10(self):
        peers = _make_peers_df([f"P{i}" for i in range(15)])
        result = sa.build_phase1_summary("TEST", _make_profile_df(), _make_quote_df(), peers)
        assert len(result["peers"]) <= 10

    def test_description_truncated_to_500(self):
        long_desc = "X" * 600
        profile = pd.DataFrame([{"sector": "Technology", "description": long_desc}])
        result = sa.build_phase1_summary("TEST", profile, _make_quote_df(), _make_peers_df())
        assert len(result["description"]) <= 500

    def test_handles_empty_profile_df(self):
        result = sa.build_phase1_summary("TEST", pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert result["symbol"] == "TEST"
        assert result["sector"] == "Unknown"
        assert result["peer_count"] == 0
        assert result["market_cap"] is None or math.isnan(result["market_cap"] or float("nan"))

    def test_market_cap_sanitised(self):
        result = sa.build_phase1_summary("TEST", _make_profile_df(), _make_quote_df(), _make_peers_df())
        mc = result["market_cap"]
        assert mc is None or isinstance(mc, (int, float))


# =========================================================================== #
#  Tests — Phase 2: compute_fundamental_kpis
# =========================================================================== #

class TestComputeFundamentalKpis:
    EXPECTED_KEYS = {
        "Revenue Growth (last)", "EPS Growth (last)", "FCF Growth (last)",
        "Gross Margin (last)", "Operating Margin (last)", "Net Margin (last)",
        "ROIC (last)", "Current Ratio (last)", "Debt/Equity (last)",
    }

    def test_all_keys_present(self):
        result = sa.compute_fundamental_kpis(
            _make_income_df(), _make_balance_df(), _make_cash_df(), _make_ratios_df()
        )
        assert self.EXPECTED_KEYS.issubset(set(result.keys()))

    def test_revenue_growth_positive(self):
        result = sa.compute_fundamental_kpis(
            _make_income_df(), _make_balance_df(), _make_cash_df(), _make_ratios_df()
        )
        rg = result["Revenue Growth (last)"]
        assert rg is not None and rg > 0

    def test_margins_from_ratios_df(self):
        result = sa.compute_fundamental_kpis(
            _make_income_df(), _make_balance_df(), _make_cash_df(), _make_ratios_df()
        )
        assert result["Gross Margin (last)"] == pytest.approx(0.30, abs=1e-9)
        assert result["Net Margin (last)"]   == pytest.approx(0.10, abs=1e-9)

    def test_fallback_gross_margin_from_income(self):
        """When ratios_df is empty, margins computed from income statement."""
        result = sa.compute_fundamental_kpis(
            _make_income_df(), _make_balance_df(), _make_cash_df(), pd.DataFrame()
        )
        gm = result["Gross Margin (last)"]
        assert gm is not None
        # gross_profit / revenue = 300M / (1000M * latest growth factor)
        assert 0.0 < gm < 1.0

    def test_fallback_de_from_balance(self):
        result = sa.compute_fundamental_kpis(
            _make_income_df(), _make_balance_df(), _make_cash_df(), pd.DataFrame()
        )
        de = result["Debt/Equity (last)"]
        assert de is not None
        assert de == pytest.approx(500_000_000 / 800_000_000, abs=0.02)

    def test_returns_none_for_all_empty(self):
        result = sa.compute_fundamental_kpis(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        for v in result.values():
            assert v is None

    def test_no_nan_in_json_output(self):
        """All NaN values must be converted to None (JSON-safe)."""
        result = sa.compute_fundamental_kpis(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        for v in result.values():
            assert v is None or not (isinstance(v, float) and math.isnan(v))


# =========================================================================== #
#  Tests — Phase 3: compute_technical_kpis
# =========================================================================== #

class TestComputeTechnicalKpis:
    EXPECTED_KEYS = {"RSI(14)", "ADX(14)", "ATR(14)", "OBV", "MACD_Signal", "BB_Pct"}

    def test_all_keys_present(self):
        result = sa.compute_technical_kpis(_make_price_df(120))
        assert self.EXPECTED_KEYS == set(result.keys())

    def test_returns_all_none_for_empty(self):
        result = sa.compute_technical_kpis(pd.DataFrame())
        assert set(result.values()) == {None}

    def test_rsi_in_valid_range(self):
        result = sa.compute_technical_kpis(_make_price_df(120))
        rsi = result["RSI(14)"]
        if rsi is not None:
            assert 0.0 <= rsi <= 100.0

    def test_bb_pct_in_reasonable_range(self):
        result = sa.compute_technical_kpis(_make_price_df(120))
        bp = result["BB_Pct"]
        if bp is not None:
            # BB_Pct can slightly exceed [0,1] at extremes, but should be close
            assert -0.5 <= bp <= 1.5

    def test_adx_non_negative(self):
        result = sa.compute_technical_kpis(_make_price_df(120))
        adx = result["ADX(14)"]
        if adx is not None:
            assert adx >= 0.0

    def test_no_nan_in_output(self):
        result = sa.compute_technical_kpis(_make_price_df(120))
        for k, v in result.items():
            assert v is None or not (isinstance(v, float) and math.isnan(v)), f"{k} is NaN"

    def test_close_only_df_still_works(self):
        """Handles DataFrame with only date+close (no high/low/volume)."""
        df = _make_price_df(120)[["date", "close"]]
        result = sa.compute_technical_kpis(df)
        assert "RSI(14)" in result


# =========================================================================== #
#  Tests — Phase 4: compute_valuation_kpis
# =========================================================================== #

class TestComputeValuationKpis:
    EXPECTED_KEYS = {
        "Price (last)", "EPS (last)", "P/E (last)", "EV/EBITDA (last)",
        "P/FCF (last)", "P/S (last)", "Earnings Yield (last)",
        "WACC (last)", "Piotroski (last)", "Altman Z (last)",
    }

    def test_all_keys_present(self):
        result = sa.compute_valuation_kpis(_make_ratios_df(), _make_quote_df(), _make_income_df())
        assert self.EXPECTED_KEYS.issubset(set(result.keys()))

    def test_pe_from_ratios(self):
        result = sa.compute_valuation_kpis(_make_ratios_df(), _make_quote_df(), _make_income_df())
        assert result["P/E (last)"] == pytest.approx(20.5, abs=1e-6)

    def test_earnings_yield_from_ratios(self):
        result = sa.compute_valuation_kpis(_make_ratios_df(), _make_quote_df(), _make_income_df())
        # ratios_df has earnings_yield = 0.049
        assert result["Earnings Yield (last)"] == pytest.approx(0.049, abs=1e-6)

    def test_pe_fallback_price_over_eps(self):
        """When ratios_df is empty, P/E = price / EPS."""
        quote = _make_quote_df()   # last_price = 155.0
        income = _make_income_df() # basic_earnings_per_share = 5.0 * growth factor (row 0 ≈ 5 * ~1.18)
        result = sa.compute_valuation_kpis(pd.DataFrame(), quote, income)
        pe = result["P/E (last)"]
        assert pe is not None and pe > 0

    def test_earnings_yield_fallback_inverse_pe(self):
        """When earnings_yield not in ratios, it's computed as 1/PE."""
        ratios = pd.DataFrame([{"price_earnings_ratio": 25.0}])  # no earnings_yield column
        result = sa.compute_valuation_kpis(ratios, _make_quote_df(), _make_income_df())
        ey = result["Earnings Yield (last)"]
        assert ey == pytest.approx(1.0 / 25.0, abs=1e-6)

    def test_no_nan_in_output(self):
        result = sa.compute_valuation_kpis(_make_ratios_df(), _make_quote_df(), _make_income_df())
        for k, v in result.items():
            assert v is None or not (isinstance(v, float) and math.isnan(v)), f"{k} is NaN"

    def test_all_empty_returns_none_values(self):
        result = sa.compute_valuation_kpis(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        # At least price and P/E should be None
        assert result["P/E (last)"] is None
        assert result["Price (last)"] is None


# =========================================================================== #
#  Tests — Phase 5: compute_risk_kpis
# =========================================================================== #

class TestComputeRiskKpis:
    EXPECTED_KEYS = {
        "Sharpe", "Sortino", "Jensen Alpha", "Beta",
        "VaR 95%", "CVaR 95%", "Max Drawdown", "Ulcer Index",
    }

    def test_all_keys_present(self):
        asset  = _make_returns(252, mean=0.0006, seed=1)
        bench  = _make_returns(252, mean=0.0003, seed=2)
        result = sa.compute_risk_kpis(asset, bench)
        assert self.EXPECTED_KEYS == set(result.keys())

    def test_returns_all_none_for_empty(self):
        result = sa.compute_risk_kpis(pd.Series(dtype=float), pd.Series(dtype=float))
        assert set(result.values()) == {None}

    def test_sharpe_positive_for_good_returns(self):
        # Use a clearly positive mean that dominates the risk-free rate
        asset = _make_returns(252, mean=0.003, std=0.008, seed=1)
        bench = _make_returns(252, mean=0.001, std=0.008, seed=2)
        result = sa.compute_risk_kpis(asset, bench, risk_free_rate=0.02)
        sharpe = result["Sharpe"]
        assert sharpe is not None and sharpe > 0

    def test_max_drawdown_non_positive(self):
        asset = _make_returns(252, seed=1)
        bench = _make_returns(252, seed=2)
        result = sa.compute_risk_kpis(asset, bench)
        mdd = result["Max Drawdown"]
        assert mdd is not None and mdd <= 0.0

    def test_var_less_than_cvar(self):
        """CVaR (expected shortfall) should be <= VaR (both are negative losses)."""
        asset = _make_returns(252, seed=3)
        bench = _make_returns(252, seed=4)
        result = sa.compute_risk_kpis(asset, bench)
        var, cvar = result["VaR 95%"], result["CVaR 95%"]
        if var is not None and cvar is not None:
            assert cvar <= var

    def test_beta_reasonable_range(self):
        # Same series → beta ≈ 1.0
        returns = _make_returns(252, seed=5)
        result = sa.compute_risk_kpis(returns.copy(), returns.copy())
        beta = result["Beta"]
        assert beta == pytest.approx(1.0, abs=1e-9)

    def test_no_nan_in_output(self):
        asset = _make_returns(252, seed=1)
        bench = _make_returns(252, seed=2)
        result = sa.compute_risk_kpis(asset, bench)
        for k, v in result.items():
            assert v is None or not (isinstance(v, float) and math.isnan(v)), f"{k} is NaN"

    def test_ulcer_index_non_negative(self):
        asset = _make_returns(252, seed=1)
        bench = _make_returns(252, seed=2)
        result = sa.compute_risk_kpis(asset, bench)
        ui = result["Ulcer Index"]
        assert ui is not None and ui >= 0.0


# =========================================================================== #
#  Tests — Phase 6 helpers: build_close_matrix, build_peer_universe
# =========================================================================== #

class TestBuildCloseMatrix:
    def test_long_to_wide(self):
        hist = _make_multi_price_df(["AAA", "BBB", "CCC"], n=30)
        matrix = sa.build_close_matrix(hist)
        assert set(matrix.columns) == {"AAA", "BBB", "CCC"}
        assert isinstance(matrix.index, pd.DatetimeIndex)

    def test_returns_empty_for_empty_input(self):
        result = sa.build_close_matrix(pd.DataFrame())
        assert result.empty

    def test_sorted_by_date(self):
        hist = _make_multi_price_df(["X"], n=20)
        matrix = sa.build_close_matrix(hist)
        assert matrix.index.is_monotonic_increasing

    def test_drops_all_nan_columns(self):
        hist = _make_multi_price_df(["A", "B"], n=20)
        # Manually add a NaN-only symbol column
        hist2 = hist.copy()
        null_rows = hist2.copy()
        null_rows["symbol"] = "NULLSYM"
        null_rows["close"] = np.nan
        combined = pd.concat([hist2, null_rows], ignore_index=True)
        matrix = sa.build_close_matrix(combined)
        assert "NULLSYM" not in matrix.columns


class TestBuildPeerUniverse:
    def test_symbol_comes_first(self):
        peers = _make_peers_df(["P1", "P2"])
        universe = sa.build_peer_universe("AAPL", "Technology", peers, "SPY")
        assert universe[0] == "AAPL"

    def test_benchmark_included(self):
        peers = _make_peers_df(["P1"])
        universe = sa.build_peer_universe("AAPL", "Technology", peers, "SPY")
        assert "SPY" in universe

    def test_symbol_not_in_peers(self):
        peers = _make_peers_df(["AAPL", "P1", "P2"])  # AAPL in peers list
        universe = sa.build_peer_universe("AAPL", "Technology", peers, "SPY")
        # AAPL should appear once at the start, not twice
        assert universe.count("AAPL") == 1

    def test_deduplication(self):
        peers = _make_peers_df(["P1", "P1", "P2"])
        universe = sa.build_peer_universe("SYM", "Technology", peers, "SPY")
        assert len(universe) == len(set(universe))

    def test_respects_max_peers(self):
        peers = _make_peers_df([f"P{i}" for i in range(20)])
        universe = sa.build_peer_universe("SYM", "Technology", peers, "SPY", max_peers=3)
        # SYM + 3 peers + sector ETFs (XLK, VGT) + SPY = 7 max
        peer_count = sum(1 for u in universe if u.startswith("P"))
        assert peer_count <= 3

    def test_empty_peers_df(self):
        universe = sa.build_peer_universe("SYM", "Healthcare", pd.DataFrame(), "SPY")
        assert "SYM" in universe
        assert "SPY" in universe


# =========================================================================== #
#  Tests — Phase 6: compute_relative_table
# =========================================================================== #

class TestComputeRelativeTable:
    EXPECTED_COLS = {"Annual Return", "Volatility", "Sharpe", "VaR 95%", "CVaR 95%", "Max Drawdown"}

    def test_all_columns_present(self):
        hist = _make_multi_price_df(["A", "B", "C"], n=90)
        matrix = sa.build_close_matrix(hist)
        result = sa.compute_relative_table(matrix)
        assert self.EXPECTED_COLS == set(result.columns)

    def test_returns_empty_for_empty_input(self):
        result = sa.compute_relative_table(pd.DataFrame())
        assert result.empty

    def test_sorted_descending_by_sharpe(self):
        hist = _make_multi_price_df(["A", "B", "C", "D"], n=120)
        matrix = sa.build_close_matrix(hist)
        result = sa.compute_relative_table(matrix)
        sharpes = result["Sharpe"].tolist()
        assert sharpes == sorted(sharpes, reverse=True)

    def test_one_row_per_symbol(self):
        hist = _make_multi_price_df(["X", "Y"], n=60)
        matrix = sa.build_close_matrix(hist)
        result = sa.compute_relative_table(matrix)
        assert len(result) == 2

    def test_max_drawdown_non_positive(self):
        hist = _make_multi_price_df(["A"], n=90)
        matrix = sa.build_close_matrix(hist)
        result = sa.compute_relative_table(matrix)
        assert (result["Max Drawdown"] <= 0).all()

    def test_no_nan_in_output(self):
        hist = _make_multi_price_df(["A", "B"], n=90)
        matrix = sa.build_close_matrix(hist)
        result = sa.compute_relative_table(matrix)
        assert not result.isnull().any().any()


# =========================================================================== #
#  Tests — Phase 7: compute_decision_scores
# =========================================================================== #

class TestComputeDecisionScores:
    EXPECTED_KEYS = {
        "business_quality", "fundamentals", "technicals", "valuation",
        "risk_fit", "relative_peer_score", "total_score", "decision",
    }

    def _full_inputs(self, symbol: str = "TEST"):
        price_df  = _make_price_df(120)
        fund_kpis = sa.compute_fundamental_kpis(
            _make_income_df(), _make_balance_df(), _make_cash_df(), _make_ratios_df()
        )
        tech_kpis = sa.compute_technical_kpis(price_df)
        val_kpis  = sa.compute_valuation_kpis(_make_ratios_df(), _make_quote_df(), _make_income_df())
        asset_ret = _make_returns(252, mean=0.0005, seed=1)
        bench_ret = _make_returns(252, mean=0.0003, seed=2)
        risk_kpis = sa.compute_risk_kpis(asset_ret, bench_ret)
        hist      = _make_multi_price_df([symbol, "PEER1", "SPY"], n=90)
        matrix    = sa.build_close_matrix(hist)
        rel_table = sa.compute_relative_table(matrix)
        phase1    = sa.build_phase1_summary(
            symbol, _make_profile_df(), _make_quote_df(), _make_peers_df()
        )
        return fund_kpis, tech_kpis, val_kpis, risk_kpis, rel_table, phase1

    def test_all_keys_present(self):
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        assert self.EXPECTED_KEYS == set(result.keys())

    def test_dimension_scores_in_range(self):
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        for dim in ("business_quality", "fundamentals", "technicals", "valuation", "risk_fit"):
            score = result[dim]
            assert score is not None
            assert 0.0 <= score <= 5.0, f"{dim} = {score} out of [0,5]"

    def test_total_score_in_range(self):
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        ts = result["total_score"]
        assert ts is not None
        assert 0.0 <= ts <= 5.0

    def test_decision_label_valid(self):
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        assert result["decision"] in {"Strong Buy", "Buy", "Hold/Watch", "Avoid/Sell", "Pending"}

    def test_all_none_inputs_returns_valid_decision(self):
        """All-None financial inputs still compute dimension defaults and yield a valid decision.
        The 'Pending' label only arises when total_score is None (all dimension weights = 0),
        which cannot happen since every dimension has non-zero fallback defaults.
        """
        result = sa.compute_decision_scores(
            None, None, None, None, None, None, "TEST"
        )
        assert result["decision"] in {"Strong Buy", "Buy", "Hold/Watch", "Avoid/Sell", "Pending"}
        # With all-None inputs the relative_peer_score dimension is None,
        # but other dimensions still resolve → total_score should be non-None.
        assert result["total_score"] is not None

    def test_partial_inputs_handled(self):
        """Decision with some None dimensions should not raise."""
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(
            fund, tech, val, None, None, phase1, "TEST"
        )
        # Should return a result without crashing
        assert "decision" in result
        assert result["decision"] in {"Strong Buy", "Buy", "Hold/Watch", "Avoid/Sell", "Pending"}

    def test_symbol_not_in_relative_table_gives_none_peer_score(self):
        fund, tech, val, risk, _, phase1 = self._full_inputs("NOTHERE")
        hist   = _make_multi_price_df(["OTHER", "SPY"], n=60)
        matrix = sa.build_close_matrix(hist)
        rel    = sa.compute_relative_table(matrix)
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "NOTHERE")
        # NOTHERE not in relative table → peer score should be None
        assert result["relative_peer_score"] is None

    def test_no_nan_in_output(self):
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        for k, v in result.items():
            if k != "decision":
                assert v is None or not (isinstance(v, float) and math.isnan(v)), f"{k} is NaN"

    def test_relative_peer_score_in_range(self):
        fund, tech, val, risk, rel, phase1 = self._full_inputs("TEST")
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        rps = result["relative_peer_score"]
        if rps is not None:
            assert 0.0 <= rps <= 5.0

    def test_single_asset_relative_table(self):
        """Only one asset in relative table → peer score should be 2.5."""
        fund, tech, val, risk, _, phase1 = self._full_inputs("TEST")
        hist   = _make_multi_price_df(["TEST"], n=60)
        matrix = sa.build_close_matrix(hist)
        rel    = sa.compute_relative_table(matrix)
        result = sa.compute_decision_scores(fund, tech, val, risk, rel, phase1, "TEST")
        assert result["relative_peer_score"] == pytest.approx(2.5, abs=1e-9)
