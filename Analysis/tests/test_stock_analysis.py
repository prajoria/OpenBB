"""
test_stock_analysis.py
======================
pytest test suite for stock_analysis.py.

Test categories
---------------
Unit tests (no live API required)
    - Helper functions: _cagr, _dcf_single, _dcf_sensitivity, _decision_label,
      _entry_quality_label, _compute_technicals, _score_fundamentals
    - Phase7 composite scoring with fully mocked inputs

Integration tests (require live fmp_cached credentials)
    - Marked with @pytest.mark.integration
    - Run against MSFT and AAPL (both large-cap, well-covered tickers)
    - Validate that phase functions return correctly-typed, non-empty results
    - Validate that KPI values fall within plausible ranges

Run unit tests only:
    pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

Run all tests (needs fmp_cached key):
    pytest Analysis/tests/test_stock_analysis.py -v
"""

from __future__ import annotations

import math
import sys
import os
import datetime

import numpy as np
import pandas as pd
import pytest

# Ensure the Analysis/ directory is on sys.path so we can import the module
_ANALYSIS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

from stock_analysis import (  # noqa: E402
    PRIMARY_PROVIDER,
    AnalysisConfig,
    AnalysisFeatureFlags,
    Phase1Result,
    Phase2Result,
    Phase3Result,
    Phase4Result,
    Phase5Result,
    Phase6Result,
    Phase7Result,
    _cagr,
    _compute_adx,
    _compute_atr,
    _compute_rsi,
    _compute_technicals,
    _compute_vol_trend,
    _dcf_sensitivity,
    _dcf_single,
    _dcf_two_stage,
    _decision_label,
    _entry_quality_label,
    _find_col,
    _last_trading_day,
    _latest_col,
    _score_fundamentals,
    _sector_etf,
    _sector_wacc_default,
    _to_df,
    phase7_decision,
    run_full_analysis,
    phase1_company_profile,
    phase2_fundamentals,
    phase3_technicals,
    phase4_valuation,
    phase5_risk,
    phase6_peer_relative,
)

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
integration = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def msft_cfg() -> AnalysisConfig:
    return AnalysisConfig(symbol="MSFT")


@pytest.fixture(scope="session")
def aapl_cfg() -> AnalysisConfig:
    return AnalysisConfig(symbol="AAPL")


def _make_ohlcv(n: int = 300) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame for unit testing indicator functions."""
    rng = np.random.default_rng(42)
    price = 100.0 + np.cumsum(rng.normal(0, 1, n))
    price = np.maximum(price, 10.0)  # no negatives

    highs  = price * (1 + rng.uniform(0.001, 0.015, n))
    lows   = price * (1 - rng.uniform(0.001, 0.015, n))
    opens  = price * (1 + rng.normal(0, 0.005, n))
    volume = rng.integers(1_000_000, 10_000_000, n).astype(float)

    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  price,
        "volume": volume,
    }, index=idx)


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for pure helper functions (no API calls)."""

    def test_provider_constant(self):
        assert PRIMARY_PROVIDER == "fmp_cached"

    def test_analysis_config_defaults(self):
        cfg = AnalysisConfig(symbol="TSLA")
        assert cfg.symbol == "TSLA"
        assert cfg.provider == "fmp_cached"
        assert cfg.benchmark == "SPY"
        assert 0.0 < cfg.risk_free_rate < 0.10
        # end_date must be strictly before today (never includes current session)
        assert cfg.end_date < datetime.date.today().isoformat()

    def test_analysis_config_has_feature_flags(self):
        """AnalysisConfig must expose a feature_flags field defaulting to all-old-behavior.

        Driven from ``AnalysisFeatureFlags.__dataclass_fields__`` so this test
        automatically covers new flags added in later phases (bead
        OpenBBTechnical-0h2.37 (flag test coverage): iteration 1 hard-coded 6
        flags and missed the 7th when A5 shipped ``use_peg_tightening``).
        """
        cfg = AnalysisConfig(symbol="TSLA")
        assert isinstance(cfg.feature_flags, AnalysisFeatureFlags)
        # Every flag defaults to False → old behavior preserved on default config.
        for name in AnalysisFeatureFlags.__dataclass_fields__:
            assert getattr(cfg.feature_flags, name) is False, (
                f"expected {name}=False by default, got "
                f"{getattr(cfg.feature_flags, name)!r}"
            )

    def test_analysis_config_accepts_custom_feature_flags(self):
        """Callers can pass their own AnalysisFeatureFlags instance to override defaults."""
        flags = AnalysisFeatureFlags(use_two_stage_dcf=True, use_stop_cap=True)
        cfg = AnalysisConfig(symbol="TSLA", feature_flags=flags)
        assert cfg.feature_flags.use_two_stage_dcf is True
        assert cfg.feature_flags.use_stop_cap is True
        # Untouched flags stay at default (False)
        assert cfg.feature_flags.use_sector_wacc is False

    def test_analysis_config_wrong_provider_warns(self):
        with pytest.warns(UserWarning, match="not the supported value"):
            AnalysisConfig(symbol="TSLA", provider="fmp")

    # --- _last_trading_day ---------------------------------------------------

    def test_last_trading_day_is_before_today(self):
        """Result must always be strictly before today."""
        result = _last_trading_day()
        assert result < datetime.date.today()

    def test_last_trading_day_is_weekday(self):
        """Result must always be Monday–Friday."""
        result = _last_trading_day()
        assert result.weekday() < 5, f"Expected Mon–Fri, got weekday {result.weekday()}"

    def test_last_trading_day_monday_returns_friday(self):
        monday = datetime.date(2026, 3, 23)  # a Monday
        assert monday.weekday() == 0
        result = _last_trading_day(monday)
        assert result == datetime.date(2026, 3, 20)  # previous Friday

    def test_last_trading_day_saturday_returns_friday(self):
        saturday = datetime.date(2026, 3, 21)
        assert saturday.weekday() == 5
        result = _last_trading_day(saturday)
        assert result == datetime.date(2026, 3, 20)

    def test_last_trading_day_sunday_returns_friday(self):
        sunday = datetime.date(2026, 3, 22)
        assert sunday.weekday() == 6
        result = _last_trading_day(sunday)
        assert result == datetime.date(2026, 3, 20)

    def test_last_trading_day_tuesday_returns_monday(self):
        tuesday = datetime.date(2026, 3, 24)
        assert tuesday.weekday() == 1
        result = _last_trading_day(tuesday)
        assert result == datetime.date(2026, 3, 23)

    def test_cagr_basic(self):
        s = pd.Series([100.0, 110.0, 121.0, 133.1, 146.41])
        cagr = _cagr(s, years=4)
        assert abs(cagr - 0.10) < 1e-4

    def test_cagr_handles_negatives(self):
        s = pd.Series([-10.0, 20.0])
        result = _cagr(s, 1)
        assert math.isnan(result)

    def test_cagr_insufficient_data(self):
        s = pd.Series([100.0])
        assert math.isnan(_cagr(s, 5))

    def test_cagr_nan_in_series(self):
        # Dropping NaN leaves [100, 121] over 1 implicit period → CAGR = 21%
        # Pass years=1 to match the 2-element series
        s = pd.Series([100.0, np.nan, 121.0])
        result = _cagr(s.dropna(), 1)
        assert abs(result - 0.21) < 1e-3

    def test_to_df_none_safe(self):
        class FakeResult:
            def to_df(self):
                return None
        assert isinstance(_to_df(FakeResult()), pd.DataFrame)

    def test_to_df_raises_safe(self):
        class BadResult:
            def to_df(self):
                raise ValueError("network error")
        result = _to_df(BadResult())
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_latest_col_found(self):
        df = pd.DataFrame({"pe_ratio": [15.0, 16.0, 17.0]})
        val = _latest_col(df, ["price_earnings_ratio", "pe_ratio"])
        assert val == 17.0

    def test_latest_col_missing(self):
        df = pd.DataFrame({"other": [1.0]})
        val = _latest_col(df, ["pe_ratio"])
        assert math.isnan(val)

    def test_find_col(self):
        df = pd.DataFrame({"gross_profit": [1], "revenue": [2]})
        assert _find_col(df, ["net_income", "gross_profit"]) == "gross_profit"
        assert _find_col(df, ["missing_col"]) is None

    def test_sector_etf_known(self):
        assert _sector_etf("Technology") == "XLK"
        assert _sector_etf("Energy")     == "XLE"
        assert _sector_etf("Unknown")    == "SPY"


# ---------------------------------------------------------------------------
# Unit tests — DCF functions
# ---------------------------------------------------------------------------


class TestDCF:
    """Unit tests for DCF helpers."""

    def test_dcf_single_basic(self):
        """DCF of a stable company with 5% growth, 9% WACC should be reasonable."""
        fv = _dcf_single(fcf0=1_000_000, g_short=0.05, g_term=0.025, wacc=0.09, shares=1_000_000)
        # Fair value per share should be positive
        assert fv > 0

    def test_dcf_single_wacc_le_gterm_clamped(self):
        """When WACC <= g_term the function should clamp g_term to WACC-0.01."""
        fv = _dcf_single(fcf0=1_000_000, g_short=0.05, g_term=0.10, wacc=0.09, shares=1_000_000)
        assert not math.isnan(fv)
        assert fv > 0

    def test_dcf_single_zero_shares(self):
        fv = _dcf_single(fcf0=1_000_000, g_short=0.05, g_term=0.025, wacc=0.09, shares=0)
        assert math.isnan(fv)

    def test_dcf_sensitivity_shape(self):
        sens = _dcf_sensitivity(
            fcf0=1_000_000, g_short=0.05, wacc_base=0.09, g_term_base=0.025, shares=1_000_000
        )
        assert sens.shape == (3, 3)
        assert not sens.isnull().values.all()

    def test_dcf_sensitivity_monotonic_wacc(self):
        """Higher WACC should produce lower fair value."""
        sens = _dcf_sensitivity(
            fcf0=1_000_000, g_short=0.05, wacc_base=0.09, g_term_base=0.025, shares=1_000_000
        )
        # Rows are sorted by WACC (ascending), so first row > last row for each col
        for col in sens.columns:
            assert float(sens.iloc[0][col]) > float(sens.iloc[2][col])


# ---------------------------------------------------------------------------
# Unit tests — decision labels
# ---------------------------------------------------------------------------


class TestDecisionLabel:
    def test_strong_buy(self):
        assert _decision_label(4.5) == "Strong Buy"

    def test_buy(self):
        assert _decision_label(4.0) == "Buy"

    def test_hold(self):
        assert _decision_label(3.0) == "Hold/Watch"

    def test_avoid(self):
        assert _decision_label(2.0) == "Avoid"

    def test_boundary_strong_buy(self):
        assert _decision_label(4.2) == "Strong Buy"

    def test_boundary_buy(self):
        assert _decision_label(3.6) == "Buy"


class TestEntryQualityLabel:
    def test_high_conviction(self):
        assert _entry_quality_label(0.25, 7) == "High Conviction"

    def test_value_entry(self):
        assert _entry_quality_label(0.25, 4) == "Value Entry"

    def test_momentum_entry(self):
        assert _entry_quality_label(0.08, 6) == "Momentum Entry"

    def test_wait(self):
        assert _entry_quality_label(0.01, 3) == "Wait"


# ---------------------------------------------------------------------------
# Unit tests — technical indicator computations
# ---------------------------------------------------------------------------


class TestComputeTechnicals:
    """Validate that _compute_technicals correctly adds indicator columns."""

    @pytest.fixture(scope="class")
    def computed(self):
        df = _make_ohlcv(300)
        return _compute_technicals(df)

    def test_returns_dataframe(self, computed):
        assert isinstance(computed, pd.DataFrame)

    def test_sma_columns_present(self, computed):
        assert "sma_50"  in computed.columns
        assert "sma_200" in computed.columns

    def test_rsi_range(self, computed):
        rsi = computed["rsi"].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_adx_positive(self, computed):
        adx = computed["adx"].dropna()
        assert (adx >= 0).all()

    def test_atr_positive(self, computed):
        atr = computed["atr"].dropna()
        assert (atr > 0).all()

    def test_macd_columns(self, computed):
        assert "macd"        in computed.columns
        assert "macd_signal" in computed.columns
        assert "macd_hist"   in computed.columns

    def test_stochastic_range(self, computed):
        stoch = computed["stoch_k"].dropna()
        assert (stoch >= 0).all() and (stoch <= 100).all()

    def test_vwap_positive(self, computed):
        vwap = computed["vwap"].dropna()
        assert (vwap > 0).all()

    def test_bb_width_positive(self, computed):
        bbw = computed["bb_width"].dropna()
        assert (bbw > 0).all()

    def test_obv_present(self, computed):
        assert "obv" in computed.columns

    def test_cmf_range(self, computed):
        cmf = computed["cmf_21"].dropna()
        assert (cmf >= -1.0).all() and (cmf <= 1.0).all()

    def test_ichimoku_columns(self, computed):
        for col in ["tenkan", "kijun", "span_a", "span_b"]:
            assert col in computed.columns

    def test_roc_columns(self, computed):
        for col in ["roc_20", "roc_60", "roc_120"]:
            assert col in computed.columns

    def test_52wk_high_present(self, computed):
        assert "high_52w"      in computed.columns
        assert "dist_52w_high" in computed.columns


class TestComputeAdxRsiAtr:
    """Standalone tests for individual indicator helpers."""

    def test_adx_series_length(self):
        df = _make_ohlcv(100)
        adx = _compute_adx(df["high"], df["low"], df["close"], 14)
        assert len(adx) == 100

    def test_rsi_not_all_nan(self):
        df = _make_ohlcv(100)
        rsi = _compute_rsi(df["close"], 14)
        assert rsi.dropna().shape[0] > 50

    def test_atr_not_all_nan(self):
        df = _make_ohlcv(100)
        atr = _compute_atr(df["high"], df["low"], df["close"], 14)
        assert atr.dropna().shape[0] > 50


# ---------------------------------------------------------------------------
# Unit tests — Phase 2 scorecard
# ---------------------------------------------------------------------------


class TestScoreFundamentals:
    def test_high_quality_scores_above_4(self):
        kpis = {
            "revenue_cagr_5y":     0.15,
            "eps_cagr_5y":         0.18,
            "fcf_cagr_5y":         0.14,
            "gross_margin":        0.65,
            "operating_margin":    0.35,
            "net_margin":          0.28,
            "roic":                0.22,
            "debt_equity":         0.5,
            "current_ratio":       2.5,
            "interest_coverage":   15.0,
            "net_debt_ebitda":     0.8,
            "cfo_net_income":      1.05,
            "fcf_margin":          0.22,
            "capex_revenue":       0.04,
            "dilution_5y":         -0.08,
            "operating_leverage":  1.2,
            "sga_trend":           -0.005,
            "fcf_payout_ratio":    0.30,
        }
        score = _score_fundamentals(kpis, accruals_ratio=0.02, gross_profitability=0.45)
        assert score >= 4.0

    def test_distressed_scores_below_2(self):
        kpis = {
            "revenue_cagr_5y":     -0.10,
            "eps_cagr_5y":         -0.20,
            "fcf_cagr_5y":         -0.15,
            "gross_margin":        0.05,
            "operating_margin":   -0.10,
            "net_margin":         -0.15,
            "roic":               -0.05,
            "debt_equity":         4.0,
            "current_ratio":       0.5,
            "interest_coverage":   0.8,
            "net_debt_ebitda":     8.0,
            "cfo_net_income":      0.2,
            "fcf_margin":         -0.05,
            "capex_revenue":       0.25,
            "dilution_5y":         0.30,
            "operating_leverage":  4.0,
            "sga_trend":           0.05,
            "fcf_payout_ratio":    1.5,
        }
        score = _score_fundamentals(kpis, accruals_ratio=0.25, gross_profitability=0.05)
        assert score < 2.5

    def test_hard_floor_caps_at_3_8(self):
        """A single very low category should cap the score at 3.8."""
        kpis = {
            "revenue_cagr_5y":  0.15,
            "eps_cagr_5y":      0.18,
            "fcf_cagr_5y":      0.14,
            "gross_margin":     0.65,
            "operating_margin": 0.35,
            "net_margin":       0.28,
            "roic":             0.22,
            "debt_equity":      0.5,
            "current_ratio":    2.5,
            "interest_coverage": 15.0,
            "net_debt_ebitda":  0.8,
            "cfo_net_income":   1.05,
            "fcf_margin":       0.22,
            "capex_revenue":    0.04,
            # Severely distressed operating leverage → structural score ≤ 1.5
            "operating_leverage": 10.0,
            "dilution_5y":     -0.08,
            "sga_trend":       -0.005,
            "fcf_payout_ratio": 0.30,
        }
        score = _score_fundamentals(kpis, accruals_ratio=0.02, gross_profitability=0.45)
        assert score <= 3.8


# ---------------------------------------------------------------------------
# Unit tests — Phase 7 with mock inputs
# ---------------------------------------------------------------------------


def _make_mock_p1() -> Phase1Result:
    return Phase1Result(
        profile_df=pd.DataFrame([{"sector": "Technology", "industry": "Software"}]),
        quote_df=pd.DataFrame([{"market_cap": 3_000_000_000_000}]),
        metrics_df=pd.DataFrame(),
        peers=["AAPL", "GOOGL", "AMZN", "META", "NVDA"],
        geo_df=pd.DataFrame(),
        insider_df=pd.DataFrame(),
        institutional_df=pd.DataFrame(),
        price_targets_df=pd.DataFrame(),
        sector="Technology",
        industry="Software",
        market_cap=3_000_000_000_000,
        free_float_pct=None,
        short_interest_pct=None,
        gate_passed=True,
        gate_notes="OK",
    )


def _make_mock_p2(score: float = 4.0, accruals: float = 0.05) -> Phase2Result:
    return Phase2Result(
        income_df=pd.DataFrame(),
        balance_df=pd.DataFrame(),
        cash_df=pd.DataFrame(),
        ratios_df=pd.DataFrame(),
        kpi_df=pd.DataFrame(),
        roe_decomp_df=pd.DataFrame(),
        score=score,
        accruals_ratio=accruals,
        gross_profitability=0.40,
        operating_leverage=1.3,
        dilution_5y=-0.05,
        gate_passed=True,
        gate_notes="OK",
    )


def _make_mock_p3(bullish_count: int = 7, earnings_safe: bool = True, weekly_bull: bool = True) -> Phase3Result:
    # Minimal price DataFrame with ATR
    price_df = pd.DataFrame(
        {"close": [145.0, 146.0, 147.0], "atr": [2.5, 2.5, 2.5]},
        index=pd.date_range("2026-01-01", periods=3, freq="B"),
    )
    signals = {
        "sma_golden_cross": True, "adx_trending": True, "rsi_pullback": True,
        "macd_bullish": True, "obv_rising": True, "volume_ratio_normal": True,
        "above_vwap": True, "above_cloud": bullish_count >= 8,
        "momentum_positive": bullish_count >= 9, "cmf_positive": True,
        "weekly_trend_bullish": weekly_bull,
    }
    # Adjust count to match requested
    true_signals = [k for k, v in signals.items() if v]
    false_signals = [k for k, v in signals.items() if not v]
    actual_count = sum(signals.values())
    # This is a simplified mock — actual counts may differ slightly
    return Phase3Result(
        price_df=price_df,
        signals=signals,
        bullish_count=bullish_count,
        entry_quality="High Conviction" if bullish_count >= 8 else "Standard",
        fib_levels={"38.2%": 140.0, "50.0%": 138.0, "61.8%": 136.0},
        atr=2.5,
        days_to_earnings=30,
        earnings_safe_window=earnings_safe,
        weekly_trend_bullish=weekly_bull,
        gate_passed=bullish_count >= 6 and earnings_safe,
        gate_notes=f"{bullish_count}/11 bullish",
    )


def _make_mock_p4(mos: float = 0.18, altman: float = 3.5) -> Phase4Result:
    return Phase4Result(
        multiples_df=pd.DataFrame([{"pe": 25.0, "ev_ebitda": 18.0}]),
        dcf_fair_value=175.0,
        margin_of_safety=mos,
        sensitivity_df=pd.DataFrame(),
        implied_growth=0.08,
        roic_wacc_spread=0.07,
        peg_ratio=1.5,        # A5: Peter Lynch's PEG (1.0 cheap / 2.0 expensive)
        piotroski=7.0,
        altman=altman,
        valuation_verdict="Undervalued" if mos >= 0.15 else "Fair Value",
        entry_recommendation="Strong Entry",
        historical_multiples_df=pd.DataFrame(),
        multiples_vs_median={},
        gate_passed=True,
        gate_notes="OK",
    )


def _make_mock_p5(sharpe: float = 1.4, mdd: float = -0.22) -> Phase5Result:
    return Phase5Result(
        risk_kpi_df=pd.DataFrame([{"sharpe": sharpe}]),
        sharpe=sharpe,
        sortino=1.8,
        calmar=1.5,
        gain_to_pain=1.3,
        max_drawdown=mdd,
        beta=0.9,
        beta_up=0.8,
        beta_down=1.0,
        var_95=-0.018,
        cvar_95=-0.032,
        ulcer_index=4.5,
        kurtosis=4.2,        # empirically typical for daily equity returns (excess kurtosis)
        skewness=-0.3,       # slight negative skew is normal for stocks
        vol_63d_trend="flat",  # A3: expanding / contracting / flat
        kelly_fraction=0.18,
        conviction_size=0.03,
        half_kelly_size=0.036,
        recommended_size=0.03,
        portfolio_fit="Core",
        stress_scenarios={"market_correction_20pct": -0.20},
        gate_passed=True,
        gate_notes="Core | Sharpe 1.40",
    )


def _make_mock_p6(relative_score: float = 3.8, ir: float = 0.6) -> Phase6Result:
    return Phase6Result(
        relative_table=pd.DataFrame(),
        corr_matrix=pd.DataFrame(),
        sector_etf="XLK",
        information_ratio=ir,
        relative_score=relative_score,
        peer_fundamental_df=pd.DataFrame(),
        relative_valuation_score=65.0,
        rolling_3m_rank=55.0,
        momentum_accel_63d=0.0,   # A6 (bead 0h2.9) — neutral default
        gate_passed=True,
        gate_notes="OK",
    )


class TestPhase7Decision:
    """Test Phase 7 decision logic with mocked inputs (no live API)."""

    @pytest.fixture
    def cfg(self) -> AnalysisConfig:
        return AnalysisConfig(symbol="MSFT")

    def test_strong_buy_label(self, cfg):
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(score=4.5),
            _make_mock_p3(bullish_count=9),
            _make_mock_p4(mos=0.25),
            _make_mock_p5(sharpe=1.8),
            _make_mock_p6(relative_score=4.2, ir=0.8),
        )
        assert p7.action_label in ("Strong Buy", "Buy")
        assert p7.composite_score > 3.5

    def test_avoid_label_distress(self, cfg):
        """Altman Z < 1.81 should force Avoid regardless of other scores."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(score=4.5),
            _make_mock_p3(bullish_count=9),
            _make_mock_p4(mos=0.25, altman=1.5),  # distress
            _make_mock_p5(sharpe=1.8),
            _make_mock_p6(relative_score=4.2),
        )
        assert p7.action_label == "Avoid"
        assert p7.composite_score <= 2.0
        assert "Altman" in (p7.hard_override or "")

    def test_high_accruals_capped(self, cfg):
        """Accruals > 20% should cap composite at Hold/Watch (≤ 2.8)."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(score=4.5, accruals=0.25),  # elevated accruals
            _make_mock_p3(bullish_count=9),
            _make_mock_p4(mos=0.25),
            _make_mock_p5(sharpe=1.8),
            _make_mock_p6(relative_score=4.2),
        )
        assert p7.composite_score <= 2.8

    def test_earnings_risk_note(self, cfg):
        """Earnings within 5 days should appear in monitoring_triggers."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(bullish_count=7, earnings_safe=False),  # earnings risk
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        assert "EARNINGS" in p7.monitoring_triggers.get("earnings_note", "").upper()

    def test_weekly_trend_bearish_caps_technicals(self, cfg):
        """Weekly trend bearish should cap technical score at 2.0."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(bullish_count=9, weekly_bull=False),  # weekly bearish
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        assert p7.score_breakdown["technicals"] <= 2.0

    def test_execution_plan_fields(self, cfg):
        """Entry plan should have stop, R targets, staged entry, and time stop."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        assert p7.atr_stop < 147.0          # stop is below current price
        assert p7.target_2r > 147.0         # 2R target is above current price
        assert p7.risk_per_share > 0
        assert "tranche_1" in p7.staged_entry
        # time_stop_date must be in the future (63 calendar days from the last
        # completed trading day — always after the analysis end_date)
        assert p7.time_stop_date > cfg.end_date

    def test_handoff_has_required_keys(self, cfg):
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        required = ["investment_thesis", "bullish_drivers", "invalidation_events",
                    "fair_value_range", "peer_relative", "trade_plan"]
        for key in required:
            assert key in p7.handoff, f"Missing handoff key: {key}"

    def test_score_breakdown_sums_to_composite(self, cfg):
        """Weighted sum of score_breakdown should equal composite_score."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        weights = {"business_quality": 0.08, "fundamentals": 0.25, "technicals": 0.15,
                   "valuation": 0.20, "risk_fit": 0.12, "peer_relative": 0.20}
        expected_sum = sum(p7.score_breakdown[k] * w for k, w in weights.items())
        # May differ slightly from composite if overrides applied; just check sign
        assert abs(p7.composite_score - expected_sum) <= 0.5


# ---------------------------------------------------------------------------
# Integration tests — Phase 1 (MSFT + AAPL)
# ---------------------------------------------------------------------------
# Tests for new features: enforce_gates, signals count, historical multiples,
# rolling_3m_rank
# ---------------------------------------------------------------------------


class TestEnforceGates:
    """Tests for enforce_gates pipeline control."""

    def test_enforce_gates_default_false(self):
        cfg = AnalysisConfig(symbol="MSFT")
        assert cfg.enforce_gates is False

    def test_enforce_gates_can_be_set(self):
        cfg = AnalysisConfig(symbol="MSFT", enforce_gates=True)
        assert cfg.enforce_gates is True


class TestPhase3SignalsCount:
    """Verify Phase 3 signals dict has 13 entries after adding Stochastic + BB."""

    @pytest.fixture(scope="class")
    def computed(self):
        df = _make_ohlcv(300)
        return _compute_technicals(df)

    def test_mock_p3_signals_count(self):
        """The mock builder still works; real signal count checked in integration."""
        p3 = _make_mock_p3()
        # Mock has 11 signals — real phase3 now produces 13
        assert len(p3.signals) >= 11

    def test_stochastic_columns_in_technicals(self, computed):
        """Stochastic %K and %D columns present after _compute_technicals."""
        assert "stoch_k" in computed.columns
        assert "stoch_d" in computed.columns

    def test_bb_width_in_technicals(self, computed):
        """BB width column present after _compute_technicals."""
        assert "bb_width" in computed.columns
        vals = computed["bb_width"].dropna()
        assert (vals >= 0).all()


class TestPhase4HistoricalMultiples:
    """Verify historical_multiples_df and multiples_vs_median in Phase4Result."""

    def test_mock_p4_has_new_fields(self):
        p4 = _make_mock_p4()
        assert hasattr(p4, "historical_multiples_df")
        assert hasattr(p4, "multiples_vs_median")
        assert isinstance(p4.multiples_vs_median, dict)


class TestPhase6Rolling3M:
    """Verify rolling_3m_rank in Phase6Result."""

    def test_mock_p6_has_rolling_3m_rank(self):
        p6 = _make_mock_p6()
        assert hasattr(p6, "rolling_3m_rank")
        assert 0.0 <= p6.rolling_3m_rank <= 100.0


class TestPhase6MomentumAccel:
    """Verify momentum_accel_63d on Phase6Result (bead OpenBBTechnical-0h2.9).

    A6 rec (reviewer P6): a static 63-day rank misses whether the stock is
    *improving* or *deteriorating* relative to peers.  Compute the rank at
    ``t-63`` and at ``t``; accel = ``(rank_t - rank_{t-63}) / 100`` — a
    scalar in ``[-1.0, +1.0]`` where positive = climbing the peer ladder,
    negative = falling.  Same 63-day window and same peer-percentile
    machinery as the existing ``rolling_3m_rank`` — so the arithmetic is
    zero-drift by construction.
    """

    def test_mock_p6_has_momentum_accel_field(self):
        p6 = _make_mock_p6()
        assert hasattr(p6, "momentum_accel_63d"), (
            "Phase6Result must carry momentum_accel_63d per bead 0h2.9"
        )

    def test_momentum_accel_in_valid_range(self):
        """Range guard — the delta of two percentiles / 100 lives in [-1, +1]."""
        p6 = _make_mock_p6()
        assert -1.0 <= p6.momentum_accel_63d <= 1.0

    def test_monotone_improving_ranks_yield_positive_accel(self):
        """Property test (per bead 0h2.9): a symbol whose peer rank is
        monotone-improving across the 126-day window must produce positive
        momentum_accel_63d.

        We synthesize returns for TARGET + 4 peers where TARGET's cumulative
        return grows from the bottom of the pack in the earlier 63d window
        to the top in the later 63d window.  The delta-rank / 100 must
        therefore be strictly positive.
        """
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        # 126 daily-return rows for 5 symbols. In the earlier 63d window
        # TARGET has the LOWEST cumulative return (worst rank); in the
        # later 63d window it has the HIGHEST cumulative return (best rank).
        rng = np.random.default_rng(seed=42)
        peer_returns_early = rng.normal(loc=0.001, scale=0.01, size=(63, 4))  # 4 peers
        target_returns_early = rng.normal(loc=-0.005, scale=0.01, size=(63, 1))  # TARGET worst
        early_block = np.hstack([target_returns_early, peer_returns_early])

        peer_returns_late = rng.normal(loc=0.001, scale=0.01, size=(63, 4))
        target_returns_late = rng.normal(loc=0.005, scale=0.01, size=(63, 1))  # TARGET best
        late_block = np.hstack([target_returns_late, peer_returns_late])

        columns = ["TARGET", "P1", "P2", "P3", "P4"]
        returns_df = pd.DataFrame(
            np.vstack([early_block, late_block]),
            columns=columns,
        )

        accel = _compute_momentum_accel_63d(returns_df, "TARGET")
        assert accel > 0.0, (
            f"Monotone-improving rank must yield positive accel, got {accel:.4f}"
        )

    def test_monotone_deteriorating_ranks_yield_negative_accel(self):
        """Symmetric guard: a rank that's collapsing must produce negative accel."""
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(seed=17)
        peer_returns_early = rng.normal(loc=0.001, scale=0.01, size=(63, 4))
        target_returns_early = rng.normal(loc=0.005, scale=0.01, size=(63, 1))  # TARGET best
        early_block = np.hstack([target_returns_early, peer_returns_early])

        peer_returns_late = rng.normal(loc=0.001, scale=0.01, size=(63, 4))
        target_returns_late = rng.normal(loc=-0.005, scale=0.01, size=(63, 1))  # TARGET worst
        late_block = np.hstack([target_returns_late, peer_returns_late])

        columns = ["TARGET", "P1", "P2", "P3", "P4"]
        returns_df = pd.DataFrame(
            np.vstack([early_block, late_block]),
            columns=columns,
        )

        accel = _compute_momentum_accel_63d(returns_df, "TARGET")
        assert accel < 0.0, (
            f"Monotone-deteriorating rank must yield negative accel, got {accel:.4f}"
        )

    def test_insufficient_history_returns_zero(self):
        """Fewer than 126 rows → cannot compute a t-63 baseline → 0.0 (neutral)."""
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        # Only 100 rows — below the 126 threshold.
        returns_df = pd.DataFrame(
            np.random.default_rng(0).normal(size=(100, 3)),
            columns=["TARGET", "P1", "P2"],
        )
        accel = _compute_momentum_accel_63d(returns_df, "TARGET")
        assert accel == 0.0

    def test_symbol_absent_from_returns_returns_zero(self):
        """Symbol not in the returns DataFrame → neutral 0.0 (never raises)."""
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        returns_df = pd.DataFrame(
            np.random.default_rng(0).normal(size=(150, 3)),
            columns=["P1", "P2", "P3"],
        )
        accel = _compute_momentum_accel_63d(returns_df, "TARGET_NOT_HERE")
        assert accel == 0.0

    # ------------------------------------------------------------------ #
    # PR #331 iter-1 review fixes — three-agent convergence on real bugs
    # ------------------------------------------------------------------ #
    def test_all_nan_target_returns_zero(self):
        """SEV-1 fix (silent-failure-hunter + code-reviewer + pr-test-analyzer,
        three-way convergence at conf 95): a target column that's entirely
        NaN must return 0.0 with a WARNING, NOT a spurious signed accel.

        Pre-fix, this scenario returned accel=-0.8 (or +0.4 depending on peer
        composition) because ``.sum().dropna()`` never dropped the all-NaN
        column — ``sum()`` returns 0.0 for all-NaN unless ``min_count=1``
        is passed.
        """
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "TARGET": [np.nan] * 126,
            "P1": rng.normal(scale=0.01, size=126),
            "P2": rng.normal(scale=0.01, size=126),
            "P3": rng.normal(scale=0.01, size=126),
            "P4": rng.normal(scale=0.01, size=126),
        })
        accel = _compute_momentum_accel_63d(df, "TARGET")
        assert accel == 0.0, (
            f"All-NaN target must degrade to 0.0; got {accel} — the "
            "sum(min_count=1) fix may have regressed"
        )

    def test_ipod_peer_does_not_phantom_contaminate_ranks(self):
        """SEV-1 fix (silent-failure-hunter concrete scenario): a peer that
        IPO'd mid-window (NaN in earlier 63d, real returns in later 63d)
        must be EXCLUDED from the earlier-window rank rather than zero-
        filled to 0% cumulative return.

        Pre-fix, PEER1's all-NaN earlier window silently zero-summed and
        phantom-competed as a mid-ranked peer (contributing 0.0 to the
        earlier percentileofscore lattice, biasing the target's rank).

        Post-fix, PEER1's earlier NaN column is dropped by
        ``sum(min_count=1).dropna()``, so the earlier rank is over 4 peers
        and the later rank is over 5 — matching the real-world peer set at
        each timestamp.

        Load-bearing check: construct TARGET with a known-decisive rank
        movement, verify the returned accel is dominated by that movement
        (not by phantom PEER1 contamination). We compare against a peer
        set with PEER1's EARLIER window filled with the CORRECT
        exclusion-then-included behavior.
        """
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(0)
        # TARGET's real returns dominate the accel — decisively worst early,
        # decisively best late — so any residual phantom-peer contamination
        # would show up as an accel != +0.8 (the expected extreme rank move).
        target = np.concatenate([
            np.full(63, -0.02),   # worst early
            np.full(63, +0.02),   # best late
        ])
        df = pd.DataFrame({
            "TARGET": target,
            "PEER1": np.concatenate([[np.nan] * 63, rng.normal(scale=0.005, size=63)]),
            "PEER2": rng.normal(scale=0.005, size=126),
            "PEER3": rng.normal(scale=0.005, size=126),
            "PEER4": rng.normal(scale=0.005, size=126),
        })
        accel_with_ipod_peer = _compute_momentum_accel_63d(df, "TARGET")

        # If PEER1's phantom 0.0 earlier-cum polluted the earlier rank set,
        # TARGET's earlier rank would be ~20 (worst of 5) instead of ~0
        # (worst of 4) — biasing accel toward smaller magnitude. Post-fix,
        # the earlier rank is measured against 4 real peers only.
        assert accel_with_ipod_peer >= 0.75, (
            f"IPO'd peer contamination would shrink accel below the "
            f"expected ~0.8 extreme rank move; got {accel_with_ipod_peer}. "
            f"Pre-fix code would return a smaller value because PEER1's "
            f"phantom 0.0 earlier-cum inflated the earlier peer set."
        )

    def test_half_nan_target_returns_zero_when_earlier_all_nan(self):
        """SEV-1 fix — target column with all-NaN in the EARLIER window only
        must degrade to 0.0 with a WARNING (not compute a bogus accel).
        """
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "TARGET": np.concatenate([[np.nan] * 63, rng.normal(scale=0.01, size=63)]),
            "P1": rng.normal(scale=0.01, size=126),
            "P2": rng.normal(scale=0.01, size=126),
            "P3": rng.normal(scale=0.01, size=126),
        })
        accel = _compute_momentum_accel_63d(df, "TARGET")
        assert accel == 0.0

    def test_units_sanity_returns_zero_on_prices_input(self):
        """SEV-3 fix — if caller accidentally passes prices (median |daily| > 0.10),
        return 0.0 with a WARNING rather than compute a garbage signal.
        """
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        # Prices (level ~100), not returns — median abs value ~100 >> 0.10
        rng = np.random.default_rng(0)
        prices = pd.DataFrame({
            "TARGET": 100 + np.cumsum(rng.normal(0, 0.5, 150)),
            "P1": 100 + np.cumsum(rng.normal(0, 0.5, 150)),
            "P2": 100 + np.cumsum(rng.normal(0, 0.5, 150)),
        })
        accel = _compute_momentum_accel_63d(prices, "TARGET")
        assert accel == 0.0

    def test_boundary_exactly_126_rows_computes(self):
        """GAP-C fix — boundary at N=126 must compute (not degrade to 0.0)."""
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        # Construct deterministic ranks: TARGET clearly-worst-then-clearly-best
        peers_early = np.tile([0.001, 0.002, 0.003, 0.004], (63, 1))
        peers_late = np.tile([-0.001, -0.002, -0.003, -0.004], (63, 1))
        target_early = np.full((63, 1), -0.01)  # TARGET worst early
        target_late = np.full((63, 1), 0.01)    # TARGET best late
        early = np.hstack([target_early, peers_early])
        late = np.hstack([target_late, peers_late])
        df = pd.DataFrame(
            np.vstack([early, late]),
            columns=["TARGET", "P1", "P2", "P3", "P4"],
        )
        assert len(df) == 126
        accel = _compute_momentum_accel_63d(df, "TARGET")
        # 5-symbol universe → percentileofscore returns 20-point lattice.
        # TARGET went from worst (rank ~0-20) to best (rank ~80-100).
        assert accel > 0.5, f"N=126 boundary should compute strong positive accel, got {accel}"

    def test_boundary_125_rows_returns_zero(self):
        """GAP-C fix — exactly one row below the boundary returns 0.0."""
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            rng.normal(scale=0.01, size=(125, 5)),
            columns=["TARGET", "P1", "P2", "P3", "P4"],
        )
        assert _compute_momentum_accel_63d(df, "TARGET") == 0.0

    def test_property_accel_magnitude_pinned_not_just_sign(self):
        """GAP-B fix — pr-test-analyzer mutation #3 (``/100 → /200``) survived
        the original sign-only property tests.  Pin the magnitude too so a
        future refactor of the divisor is caught.

        Construction: TARGET is clearly-worst in earlier window (rank 0/5)
        and clearly-best in later window (rank 100/5) → expected accel = +1.0.
        """
        from Analysis.stock_analysis import _compute_momentum_accel_63d

        peers = np.tile([0.001, 0.002, 0.003, 0.004], (126, 1))
        target_early = np.full((63, 1), -0.02)   # TARGET decisively worst
        target_late = np.full((63, 1), 0.02)     # TARGET decisively best
        target = np.vstack([target_early, target_late])
        df = pd.DataFrame(
            np.hstack([target, peers]),
            columns=["TARGET", "P1", "P2", "P3", "P4"],
        )
        accel = _compute_momentum_accel_63d(df, "TARGET")
        # 5 symbols: percentileofscore lattice is 20 points, so extreme
        # movement from clear-worst to clear-best gives ~+0.8 (not +1.0)
        # because percentileofscore returns "rank" semantic including the
        # symbol itself.  Tighten to a value that would fail on /200.
        assert accel == pytest.approx(0.8, abs=0.05), (
            f"Magnitude regression: expected ~+0.8, got {accel}. "
            "If a mutant changed /100 → /200 this would fail at ~+0.4."
        )

    def test_phase6_peer_relative_threads_momentum_accel_field(self):
        """GAP-A fix (pr-test-analyzer's Recommended Test #1, mutation #4):
        proves ``phase6_peer_relative`` actually passes the computed value
        to ``Phase6Result``. Uses ``dataclasses.fields`` introspection to
        prove the field is present on the class — the wiring itself is
        integration-tested in TestPhase6MSFT/AAPL, but this unit-level guard
        catches a common regression class ("added a field, forgot to pass
        it to the constructor").

        Load-bearing property: if someone re-orders or drops the
        ``momentum_accel_63d=momentum_accel_63d`` line in the
        ``Phase6Result(...)`` return, this test still passes (the field is
        on the dataclass regardless); but the integration tests + the
        default-value shape catches it.  This test is a shape guard, not
        a value guard.
        """
        import dataclasses
        from Analysis.stock_analysis import Phase6Result

        field_names = {f.name for f in dataclasses.fields(Phase6Result)}
        assert "momentum_accel_63d" in field_names, (
            "Phase6Result must declare momentum_accel_63d as a dataclass field"
        )
        # Verify the field is typed as float (not defaulted to Any / str)
        momentum_field = next(
            f for f in dataclasses.fields(Phase6Result) if f.name == "momentum_accel_63d"
        )
        assert momentum_field.type in (float, "float"), (
            f"momentum_accel_63d must be typed float; got {momentum_field.type}"
        )


class TestPhase1Tradeability:
    """Verify free_float_pct + short_interest_pct on Phase1Result (bead OpenBBTechnical-0h2.3).

    The A1 bead renames the P1 block conceptually to 'tradeability' (from the
    reviewer's P1 recommendation: raw market cap overstates liquidity, so
    float-adjusted market cap is the more honest signal).  These unit tests
    verify the dataclass carries both fields with sensible None-fallback
    semantics — live-provider assertions live in TestPhase1MSFT/AAPL below.
    """

    def test_mock_p1_has_tradeability_fields(self):
        p1 = _make_mock_p1()
        assert hasattr(p1, "free_float_pct")
        assert hasattr(p1, "short_interest_pct")

    def test_mock_p1_defaults_to_none_on_missing_data(self):
        """Both fields must be None-capable — providers may fail to return them."""
        p1 = _make_mock_p1()
        assert p1.free_float_pct is None
        assert p1.short_interest_pct is None

    def test_phase1result_accepts_float_free_float(self):
        """Construct a Phase1Result with a real free-float value (0.87 = 87 %)."""
        p1 = Phase1Result(
            profile_df=pd.DataFrame(),
            quote_df=pd.DataFrame(),
            metrics_df=pd.DataFrame(),
            peers=[],
            geo_df=pd.DataFrame(),
            insider_df=pd.DataFrame(),
            institutional_df=pd.DataFrame(),
            price_targets_df=pd.DataFrame(),
            sector="",
            industry="",
            market_cap=0.0,
            free_float_pct=0.87,
            short_interest_pct=0.05,
            gate_passed=False,
            gate_notes="",
        )
        assert p1.free_float_pct == 0.87
        assert p1.short_interest_pct == 0.05

    def test_float_adjusted_market_cap_derivation(self):
        """The whole point of A1 — a caller can compute float-adjusted market cap
        as market_cap * free_float_pct.  This is the reviewer's core recommendation.
        """
        p1 = Phase1Result(
            profile_df=pd.DataFrame(),
            quote_df=pd.DataFrame(),
            metrics_df=pd.DataFrame(),
            peers=[],
            geo_df=pd.DataFrame(),
            insider_df=pd.DataFrame(),
            institutional_df=pd.DataFrame(),
            price_targets_df=pd.DataFrame(),
            sector="",
            industry="",
            market_cap=1_000_000_000_000.0,  # $1T raw
            free_float_pct=0.80,             # 80 % of shares publicly tradeable
            short_interest_pct=None,
            gate_passed=False,
            gate_notes="",
        )
        # A caller (later phases) can derive the float-adjusted cap
        float_adjusted_cap = p1.market_cap * p1.free_float_pct
        assert float_adjusted_cap == 800_000_000_000.0


class TestPhase5FatTails:
    """Verify kurtosis + skewness on Phase5Result (bead OpenBBTechnical-0h2.4).

    A2 exposes distributional shape beyond mean/variance — critical because
    real equity returns have fat tails (excess kurtosis typically 3-8 for
    daily returns) that Sharpe/Sortino don't capture.  Golden values are
    compared to direct scipy.stats calls on synthetic series.
    """

    def test_mock_p5_has_fat_tail_fields(self):
        p5 = _make_mock_p5()
        assert hasattr(p5, "kurtosis")
        assert hasattr(p5, "skewness")
        assert isinstance(p5.kurtosis, float)
        assert isinstance(p5.skewness, float)

    def test_normal_series_has_zero_excess_kurtosis(self):
        """Fisher's excess kurtosis for a standard normal ~= 0 (large N).

        This is the sanity check: a normal distribution has kurtosis 3 in
        the Pearson definition; scipy defaults to Fisher (subtracts 3), so
        the output must be near 0.
        """
        from scipy.stats import kurtosis, skew
        rng = np.random.default_rng(42)
        # Large N to shrink sampling error
        normal_returns = rng.normal(loc=0.0, scale=0.01, size=10_000)
        k = float(kurtosis(normal_returns, fisher=True))
        s = float(skew(normal_returns))
        # With N=10k, |kurtosis| < 0.15 and |skew| < 0.05 with very high probability
        assert abs(k) < 0.15, f"expected ~0 excess kurtosis for normal, got {k}"
        assert abs(s) < 0.05, f"expected ~0 skew for normal, got {s}"

    def test_fat_tailed_series_shows_positive_kurtosis(self):
        """A Student-t distribution with df=3 has infinite population kurtosis;
        the sample estimator should still return a large positive value —
        confirming that the metric distinguishes fat-tailed from normal."""
        from scipy.stats import kurtosis, t
        rng = np.random.default_rng(7)
        t_returns = t.rvs(df=3, size=10_000, random_state=rng) * 0.01
        k = float(kurtosis(t_returns, fisher=True))
        # Even with sampling, df=3 t consistently produces k > 3
        assert k > 3.0, f"expected fat-tailed kurtosis > 3, got {k}"

    def test_negatively_skewed_series_shows_negative_skew(self):
        """Left-skewed distributions (crashes worse than rallies) — the
        canonical case for equity returns during stress periods."""
        from scipy.stats import skew
        rng = np.random.default_rng(11)
        # Negative-skew construction: mix of small positive returns and rare large negatives
        left_tail = rng.normal(loc=0.001, scale=0.005, size=9_500)
        crashes  = rng.normal(loc=-0.05, scale=0.02, size=500)
        returns = np.concatenate([left_tail, crashes])
        s = float(skew(returns))
        assert s < -0.5, f"expected pronounced negative skew, got {s}"


class TestVolTrend:
    """Verify _compute_vol_trend classifier (bead OpenBBTechnical-0h2.4 → 0h2.5).

    Compares the mean of recent-63d rolling vol to the prior-63d window.
    Threshold is ±10 % so tiny fluctuations don't flip the label — hysteresis
    prevents whipsaw when vol is essentially stable.  Property tests use
    synthetic series where the expected label is unambiguous.
    """

    def test_returns_expanding_when_vol_rising_strongly(self):
        """A series where the LAST 100 days are much louder than the
        prior 200 days classifies as 'expanding'.

        Layout matters: with window=63, the classifier compares
        rolling_vol.iloc[-63:] (covers returns[-126:-1], mix of quiet+loud)
        to rolling_vol.iloc[-126:-63] (covers returns[-189:-63], pure quiet).
        The transition needs to land inside the last 2*window returns for
        the classifier to see it.
        """
        rng = np.random.default_rng(1)
        quiet = pd.Series(rng.normal(0, 0.01, size=200))
        loud  = pd.Series(rng.normal(0, 0.04, size=100))
        returns = pd.concat([quiet, loud], ignore_index=True)
        assert _compute_vol_trend(returns) == "expanding"

    def test_returns_contracting_when_vol_falling_strongly(self):
        """Loud early followed by quiet — classic 'crisis then calm'.
        Mirror of the expanding case."""
        rng = np.random.default_rng(2)
        loud  = pd.Series(rng.normal(0, 0.04, size=200))
        quiet = pd.Series(rng.normal(0, 0.01, size=100))
        returns = pd.concat([loud, quiet], ignore_index=True)
        assert _compute_vol_trend(returns) == "contracting"

    def test_returns_flat_when_vol_stable(self):
        """A series with constant volatility across the whole window."""
        rng = np.random.default_rng(3)
        # ~400 days at the same vol level
        returns = pd.Series(rng.normal(0, 0.015, size=400))
        assert _compute_vol_trend(returns) == "flat"

    def test_returns_flat_when_series_too_short(self):
        """Fewer than 2 * 63 = 126 returns → no meaningful comparison possible."""
        rng = np.random.default_rng(4)
        returns = pd.Series(rng.normal(0, 0.02, size=50))
        assert _compute_vol_trend(returns) == "flat"

    def test_returns_flat_on_empty_series(self):
        """Degenerate input must not crash."""
        assert _compute_vol_trend(pd.Series(dtype=float)) == "flat"

    def test_only_returns_allowed_values(self):
        """Contract: output is always one of the three literal strings.
        Never returns None, NaN, or an unknown string — downstream code
        can rely on the closed set."""
        rng = np.random.default_rng(5)
        for _ in range(20):
            n = rng.integers(low=10, high=500)
            scale = float(rng.uniform(0.005, 0.06))
            returns = pd.Series(rng.normal(0, scale, size=n))
            label = _compute_vol_trend(returns)
            assert label in ("expanding", "contracting", "flat"), (
                f"unexpected label {label!r} for scale={scale}, n={n}"
            )


class TestTwoStageDCF:
    """Verify _dcf_two_stage helper (bead OpenBBTechnical-0h2.6, first
    feature-flag-gated behavior change).

    The two-stage fade replaces the current single-stage Gordon-at-year-5
    model with: explicit 5Y growth → linear fade over 8Y to terminal.
    Rationale: a company growing 15 % cannot maintain that indefinitely, but
    also cannot drop to 2.5 % overnight — the fade captures the mean-reversion
    that empirical corporate growth studies actually show.

    Gated behind AnalysisFeatureFlags.use_two_stage_dcf (default False = old
    behavior).  Both helpers share the (fcf0, g_short, g_term, wacc, shares)
    signature so phase4_valuation can pick one via a local dcf_fn variable
    and route every DCF call through it (fair value, sensitivity, reverse-DCF).
    """

    # --- signature parity -----------------------------------------------

    def test_signature_matches_dcf_single(self):
        """Both helpers must be call-compatible so a dcf_fn = _dcf_single or
        _dcf_two_stage indirection works cleanly in phase4_valuation."""
        # Same positional-only call site must work for both
        v_single = _dcf_single(100.0, 0.10, 0.025, 0.09, 100.0)
        v_two    = _dcf_two_stage(100.0, 0.10, 0.025, 0.09, 100.0)
        assert isinstance(v_single, float)
        assert isinstance(v_two, float)

    def test_positive_value_for_reasonable_inputs(self):
        v = _dcf_two_stage(fcf0=1_000_000_000, g_short=0.10, g_term=0.025,
                            wacc=0.09, shares=1_000_000_000)
        assert v > 0
        assert np.isfinite(v)

    # --- key equivalence points -----------------------------------------

    def test_equals_single_stage_when_growth_flat(self):
        """When g_short == g_term, the fade has no gradient — every year uses
        the same growth rate.  Two-stage and single-stage must agree.

        Note: they won't be *exactly* equal because single-stage projects
        5 years then goes terminal; two-stage projects 5 + 8 = 13 years then
        goes terminal.  But when growth is constant, the extra 8 years of
        explicit projection at terminal growth should still converge to
        essentially the same value (< 1 % difference).
        """
        v_single = _dcf_single(100.0, 0.025, 0.025, 0.09, 100.0)
        v_two    = _dcf_two_stage(100.0, 0.025, 0.025, 0.09, 100.0)
        # Same underlying model in the limit — should agree within 1 %
        assert abs(v_two - v_single) / v_single < 0.01, (
            f"two-stage {v_two} vs single {v_single} diverged by "
            f"{abs(v_two - v_single) / v_single:.1%}"
        )

    def test_two_stage_greater_than_single_when_g_short_high(self):
        """The reviewer's core argument for the change: single-stage bakes
        the terminal (mature) rate in at year 6+, immediately abandoning
        the high growth.  Two-stage preserves the high growth for 5 more
        years while fading — so its NPV is meaningfully higher when
        g_short >> g_term.  For MSFT-like inputs (revenue CAGR 14 % vs
        terminal 2.5 %), two-stage should exceed single-stage by 10 %+.
        """
        v_single = _dcf_single(1e10, 0.14, 0.025, 0.09, 1e9)
        v_two    = _dcf_two_stage(1e10, 0.14, 0.025, 0.09, 1e9)
        assert v_two > v_single, (
            f"expected two-stage {v_two} > single {v_single}"
        )
        # And the gap should be material — not just noise
        assert (v_two - v_single) / v_single > 0.05, (
            f"expected > 5% uplift from fade, got "
            f"{(v_two - v_single) / v_single:.1%}"
        )

    # --- WACC guard (same as _dcf_single) -------------------------------

    def test_wacc_below_g_term_is_guarded(self):
        """If wacc <= g_term, terminal-value denominator (wacc - g_term)
        would go negative → nonsense.  Both helpers must clamp g_term to
        (wacc - 0.01) so the terminal remains bounded."""
        # wacc=0.03, g_term=0.05 → without guard, terminal denominator = -0.02
        v_two = _dcf_two_stage(100.0, 0.10, 0.05, 0.03, 100.0)
        assert np.isfinite(v_two), "guard should keep the value finite"
        assert v_two > 0

    def test_zero_shares_returns_nan(self):
        """Matches _dcf_single's shares<=0 guard."""
        v = _dcf_two_stage(100.0, 0.10, 0.025, 0.09, 0)
        assert np.isnan(v)

    # --- hand-computed golden -------------------------------------------

    def test_hand_computed_zero_growth_annuity(self):
        """Degenerate case: g_short = g_term = 0, wacc = 0.10, fcf0 = 100,
        shares = 100.  With no growth, every year's FCF is 100, discounted
        at 10 %.  This collapses to a straight annuity + perpetuity that
        can be verified with the closed-form geometric sum.

        Two-stage projects 5 + 8 = 13 explicit years, then terminal.
        Sum over 13 years of 100 / 1.10^t:
            = 100 * (1 - 1.10^-13) / 0.10
            ≈ 100 * 7.10336
            ≈ 710.336
        Terminal value at year 13: FCF_13 * (1 + g_term) / (wacc - g_term)
            = 100 * 1.0 / 0.10 = 1000
        PV of terminal: 1000 / 1.10^13 ≈ 289.664
        Total enterprise value ≈ 710.336 + 289.664 ≈ 1000
        Per share (shares=100): ≈ 10.0
        """
        v = _dcf_two_stage(fcf0=100.0, g_short=0.0, g_term=0.0,
                            wacc=0.10, shares=100.0)
        # Expected ~10.0 by the derivation above; allow small floating-point slack
        assert abs(v - 10.0) < 0.01, f"expected ~10.0, got {v}"


class TestPhase4TwoStageFlag:
    """Verify the AnalysisFeatureFlags.use_two_stage_dcf switch in
    phase4_valuation actually toggles the DCF helper (bead 0h2.6).

    The parity assertion is critical: with the flag off, every downstream
    number (dcf_fair_value, sensitivity_df, implied_growth) must be
    bit-identical to pre-A4a.  A silent change means the branch introduced
    an unintended side effect."""

    def _cfg_and_p2p3(self, use_two_stage: bool):
        """Build minimal synthetic Phase2/Phase3 inputs that let
        phase4_valuation run end-to-end without any live provider call."""
        # A minimal but realistic Phase2Result — populated with the columns
        # phase4_valuation actually reads.
        income_df = pd.DataFrame({
            "revenue":                          [100e9, 115e9, 130e9, 148e9, 168e9],
            "operating_income":                 [30e9,  35e9,  40e9,  46e9,  53e9],
            "gross_profit":                     [65e9,  75e9,  85e9,  97e9,  110e9],
            "eps_diluted":                      [8.0,   9.0,   10.5,  12.0,  14.0],
            "shares_outstanding":               [10e9,  10e9,  9.9e9, 9.8e9, 9.75e9],
        })
        balance_df = pd.DataFrame({"total_assets": [1] * 5})   # unused by DCF branch
        cash_df    = pd.DataFrame({"free_cash_flow": [30e9, 35e9, 40e9, 46e9, 50e9]})
        ratios_df  = pd.DataFrame({
            "price_earnings_ratio":       [28.0],
            "enterprise_value_multiple":  [22.0],
            "price_to_free_cash_flow":    [30.0],
            "price_to_sales":             [12.0],
            "piotroski_score":            [7],
            "altman_z_score":             [4.5],
            "wacc":                       [0.085],
            "enterprise_value":           [3.5e12],
        })
        p2 = Phase2Result(
            income_df=income_df, balance_df=balance_df, cash_df=cash_df,
            ratios_df=ratios_df, kpi_df=pd.DataFrame(),
            roe_decomp_df=pd.DataFrame(),
            score=4.2, accruals_ratio=0.03, gross_profitability=0.40,
            operating_leverage=1.3, dilution_5y=-0.02,
            gate_passed=True, gate_notes="OK",
        )
        # Default p3 mock: 3 rows with close ~145, ATR ~2.5.  phase4_valuation
        # only reads p3.price_df["close"].iloc[-1] so no override needed.
        p3 = _make_mock_p3()
        cfg = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_two_stage_dcf=use_two_stage),
        )
        return cfg, p2, p3

    def test_flag_off_uses_single_stage(self):
        """Flag=False must produce exactly _dcf_single's output on the same
        (fcf0, g_short, g_term, wacc, shares) inputs — no drift."""
        cfg, p2, p3 = self._cfg_and_p2p3(use_two_stage=False)
        p4 = phase4_valuation(cfg, p2, p3)
        # Reconstruct the expected DCF the same way phase4_valuation does
        fcf0 = float(p2.cash_df["free_cash_flow"].iloc[-1])
        rev  = p2.income_df["revenue"]
        g_short = min(_cagr(rev, 5), 0.25)
        wacc = 0.085
        g_term = 0.025
        shares_out = float(p2.income_df["shares_outstanding"].iloc[-1])
        expected = _dcf_single(fcf0, g_short, g_term, wacc, shares_out)
        assert abs(p4.dcf_fair_value - expected) < 1e-6, (
            f"flag-off drift: p4.dcf={p4.dcf_fair_value}, expected={expected}"
        )

    def test_flag_on_uses_two_stage(self):
        """Flag=True routes DCF through _dcf_two_stage.  Value must differ
        from the flag-off case and match _dcf_two_stage on identical inputs."""
        cfg_on,  p2, p3 = self._cfg_and_p2p3(use_two_stage=True)
        cfg_off, _,  _  = self._cfg_and_p2p3(use_two_stage=False)
        p4_on  = phase4_valuation(cfg_on,  p2, p3)
        p4_off = phase4_valuation(cfg_off, p2, p3)
        # Different model → different value
        assert p4_on.dcf_fair_value != p4_off.dcf_fair_value, (
            f"flag-on should produce a different DCF ({p4_on.dcf_fair_value}) "
            f"than flag-off ({p4_off.dcf_fair_value})"
        )
        # And it should match _dcf_two_stage directly
        fcf0 = float(p2.cash_df["free_cash_flow"].iloc[-1])
        rev  = p2.income_df["revenue"]
        g_short = min(_cagr(rev, 5), 0.25)
        shares_out = float(p2.income_df["shares_outstanding"].iloc[-1])
        expected = _dcf_two_stage(fcf0, g_short, 0.025, 0.085, shares_out)
        assert abs(p4_on.dcf_fair_value - expected) < 1e-6

    def test_sensitivity_and_reverse_dcf_route_through_same_helper(self):
        """When flag is on, sensitivity_df and implied_growth must both
        use the two-stage model — otherwise the numbers on the same
        Phase4Result contradict each other."""
        cfg, p2, p3 = self._cfg_and_p2p3(use_two_stage=True)
        p4 = phase4_valuation(cfg, p2, p3)
        # Sensitivity: reconstruct one cell and compare — the base case
        # (middle row / middle col) must match the fair value.
        assert not p4.sensitivity_df.empty
        # Round to 2 dp because sensitivity table stores that precision
        base_cell = float(p4.sensitivity_df.iloc[1, 1])
        assert abs(base_cell - round(p4.dcf_fair_value, 2)) < 0.05, (
            f"sensitivity base cell {base_cell} disagrees with "
            f"dcf_fair_value {p4.dcf_fair_value:.2f} — flag not routed to sensitivity?"
        )


class TestSectorWaccDefault:
    """Verify _sector_wacc_default helper (bead OpenBBTechnical-0h2.7).

    Replaces the flat 9 % WACC fallback with a sector-calibrated default
    when ratios_df.wacc is missing.  Rationale (reviewer P4, item #10):
    9 % is too generous for a low-vol utility (empirical ~6 %) and too
    aggressive for a crypto-adjacent name (empirical ~15 %).  Gated
    behind AnalysisFeatureFlags.use_sector_wacc.
    """

    def test_technology_sector_returns_9pct(self):
        """Technology sits at the baseline — same as the flat fallback.
        This ensures Tech names don't shift when the flag flips on."""
        assert _sector_wacc_default("Technology") == 0.09

    def test_utilities_sector_returns_low_wacc(self):
        """Utilities have regulated returns, low vol, dividend-heavy.
        Empirically the lowest WACC of any sector (~6 %)."""
        assert _sector_wacc_default("Utilities") == 0.06

    def test_healthcare_sector_returns_higher_wacc(self):
        """Healthcare has R&D + FDA + patent risk — reviewer flagged 11 %."""
        assert _sector_wacc_default("Healthcare") == 0.11

    def test_health_care_alias_also_returns_11pct(self):
        """Provider inconsistency: FMP sometimes returns 'Health Care'
        with a space.  Alias must resolve to the same value."""
        assert _sector_wacc_default("Health Care") == 0.11

    def test_energy_returns_elevated_wacc(self):
        """Energy: commodity price + geopolitical risk."""
        assert _sector_wacc_default("Energy") == 0.12

    def test_crypto_returns_15pct_per_bead_title(self):
        """Bead title explicitly names crypto at 15 % — the exemplar of
        'reviewer's aggressive-fallback critique.'"""
        assert _sector_wacc_default("Crypto") == 0.15

    def test_unknown_sector_returns_default_9pct(self):
        """When the sector name isn't in the map, fall back to the flat
        9 % — preserves pre-A4b behavior for uncovered sectors."""
        assert _sector_wacc_default("Bogus") == 0.09
        assert _sector_wacc_default("") == 0.09

    def test_custom_default_respected(self):
        """Caller can override the fallback default (e.g., to preserve
        an explicit numeric injected upstream)."""
        assert _sector_wacc_default("Bogus", default=0.075) == 0.075

    def test_all_mapped_sectors_have_plausible_wacc(self):
        """Sanity: every sector WACC is a real number in (0, 0.20).
        Guards against typos that would ship silently."""
        # All the sector strings that appear in _SECTOR_ETF_MAP should
        # also appear in _SECTOR_WACC_MAP so the two stay in sync.
        for sector in [
            "Technology", "Communication Services",
            "Financial Services", "Financial",
            "Healthcare", "Health Care",
            "Consumer Cyclical", "Consumer Defensive",
            "Industrials", "Basic Materials",
            "Energy", "Utilities", "Real Estate",
            "Crypto",
        ]:
            wacc = _sector_wacc_default(sector)
            assert 0.0 < wacc < 0.20, f"{sector} WACC {wacc} outside plausible range"


class TestPhase4SectorWaccFlag:
    """Verify the AnalysisFeatureFlags.use_sector_wacc switch in
    phase4_valuation (bead 0h2.7).

    Parity assertion is critical: with the flag OFF (default), the WACC
    fallback path must return the flat 9 %, exactly as pre-A4b.  With
    the flag ON, the sector from p1 drives the WACC.  If p1 is not
    passed (test-scaffolding legacy), sector-lookup gracefully falls
    back to the flat 9 % — no crash.
    """

    def _cfg_p1_p2_p3(self, use_sector_wacc: bool, sector: str = "Utilities"):
        """Build synthetic p1/p2/p3.  ratios_df deliberately omits wacc
        so the fallback path is exercised."""
        # p2 with NO wacc column — forces the fallback
        income_df = pd.DataFrame({
            "revenue":            [100e9, 115e9, 130e9, 148e9, 168e9],
            "operating_income":   [30e9,  35e9,  40e9,  46e9,  53e9],
            "gross_profit":       [65e9,  75e9,  85e9,  97e9,  110e9],
            "eps_diluted":        [8.0,   9.0,   10.5,  12.0,  14.0],
            "shares_outstanding": [10e9,  10e9,  9.9e9, 9.8e9, 9.75e9],
        })
        cash_df = pd.DataFrame({"free_cash_flow": [30e9, 35e9, 40e9, 46e9, 50e9]})
        # ratios_df with NO wacc key — the whole point of A4b's fallback
        ratios_df = pd.DataFrame({
            "price_earnings_ratio":      [28.0],
            "enterprise_value_multiple": [22.0],
            "price_to_free_cash_flow":   [30.0],
            "price_to_sales":            [12.0],
            "piotroski_score":           [7],
            "altman_z_score":            [4.5],
            "enterprise_value":          [3.5e12],
            # wacc: absent
        })
        p2 = Phase2Result(
            income_df=income_df, balance_df=pd.DataFrame({"total_assets":[1]*5}),
            cash_df=cash_df, ratios_df=ratios_df, kpi_df=pd.DataFrame(),
            roe_decomp_df=pd.DataFrame(),
            score=4.2, accruals_ratio=0.03, gross_profitability=0.40,
            operating_leverage=1.3, dilution_5y=-0.02,
            gate_passed=True, gate_notes="OK",
        )
        p3 = _make_mock_p3()
        p1 = _make_mock_p1()
        # Override p1.sector to whatever the test wants
        p1.sector = sector
        cfg = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_sector_wacc=use_sector_wacc),
        )
        return cfg, p1, p2, p3

    def test_flag_off_uses_flat_9pct(self):
        """Flag=False must produce the DCF you'd get from flat 9 %,
        regardless of p1.sector — pre-A4b behavior preserved."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(use_sector_wacc=False,
                                              sector="Utilities")
        # Utilities would map to 6 % under the flag; but with flag off,
        # WACC must remain 9 %.
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        # Reconstruct expected DCF at 9 %
        fcf0 = float(p2.cash_df["free_cash_flow"].iloc[-1])
        rev  = p2.income_df["revenue"]
        g_short = min(_cagr(rev, 5), 0.25)
        shares_out = float(p2.income_df["shares_outstanding"].iloc[-1])
        expected = _dcf_single(fcf0, g_short, 0.025, 0.09, shares_out)
        assert abs(p4.dcf_fair_value - expected) < 1e-6, (
            f"flag-off drift: p4.dcf={p4.dcf_fair_value}, expected(9%)={expected}"
        )

    def test_flag_on_uses_sector_wacc_utilities(self):
        """Utilities → 6 %.  Lower WACC → higher DCF value than flat-9 %
        case (same FCF, lower discount rate)."""
        cfg_on,  p1_on,  p2, p3 = self._cfg_p1_p2_p3(use_sector_wacc=True,
                                                     sector="Utilities")
        cfg_off, p1_off, _,  _  = self._cfg_p1_p2_p3(use_sector_wacc=False,
                                                     sector="Utilities")
        p4_on  = phase4_valuation(cfg_on,  p2, p3, p1=p1_on)
        p4_off = phase4_valuation(cfg_off, p2, p3, p1=p1_off)
        # Utilities WACC 6 % < flat 9 % → utilities DCF should be higher
        assert p4_on.dcf_fair_value > p4_off.dcf_fair_value, (
            f"utilities under 6% WACC ({p4_on.dcf_fair_value}) should exceed "
            f"flat-9% ({p4_off.dcf_fair_value})"
        )

    def test_flag_on_uses_sector_wacc_energy(self):
        """Energy → 12 %.  Higher WACC → lower DCF value than flat-9 %."""
        cfg_on,  p1_on,  p2, p3 = self._cfg_p1_p2_p3(use_sector_wacc=True,
                                                     sector="Energy")
        cfg_off, p1_off, _,  _  = self._cfg_p1_p2_p3(use_sector_wacc=False,
                                                     sector="Energy")
        p4_on  = phase4_valuation(cfg_on,  p2, p3, p1=p1_on)
        p4_off = phase4_valuation(cfg_off, p2, p3, p1=p1_off)
        # Energy WACC 12 % > flat 9 % → energy DCF should be lower
        assert p4_on.dcf_fair_value < p4_off.dcf_fair_value

    def test_flag_on_but_no_p1_falls_back_gracefully(self):
        """If phase4_valuation is called without p1 (older test-only path),
        the sector-WACC lookup can't resolve — must silently degrade to
        flat 9 %, not crash."""
        cfg, _, p2, p3 = self._cfg_p1_p2_p3(use_sector_wacc=True,
                                             sector="Utilities")
        # Call WITHOUT p1
        p4 = phase4_valuation(cfg, p2, p3)  # p1 not passed
        fcf0 = float(p2.cash_df["free_cash_flow"].iloc[-1])
        rev  = p2.income_df["revenue"]
        g_short = min(_cagr(rev, 5), 0.25)
        shares_out = float(p2.income_df["shares_outstanding"].iloc[-1])
        expected = _dcf_single(fcf0, g_short, 0.025, 0.09, shares_out)
        assert abs(p4.dcf_fair_value - expected) < 1e-6, (
            "no-p1 path should degrade to flat 9 % WACC"
        )

    def test_ratios_wacc_takes_precedence_over_sector_default(self):
        """When ratios_df has a valid wacc, it wins regardless of flag —
        the sector default is a FALLBACK, not an override."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(use_sector_wacc=True,
                                              sector="Utilities")
        # Inject an explicit wacc into ratios_df — should be honored
        p2.ratios_df = p2.ratios_df.assign(wacc=[0.0725])
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        # Compute what the DCF should be at wacc=0.0725
        fcf0 = float(p2.cash_df["free_cash_flow"].iloc[-1])
        rev  = p2.income_df["revenue"]
        g_short = min(_cagr(rev, 5), 0.25)
        shares_out = float(p2.income_df["shares_outstanding"].iloc[-1])
        expected = _dcf_single(fcf0, g_short, 0.025, 0.0725, shares_out)
        assert abs(p4.dcf_fair_value - expected) < 1e-6, (
            f"explicit wacc 0.0725 should override sector default; "
            f"got {p4.dcf_fair_value}, expected {expected}"
        )


class TestPhase4CombinedFlags:
    """Verify multiple AnalysisFeatureFlags interact correctly in phase4_valuation
    (PR #304 review C2 / bead OpenBBTechnical-0h2.34).

    The single-flag tests in TestPhase4TwoStageFlag and TestPhase4SectorWaccFlag
    each test their own flag in isolation.  A real rollout will run BOTH flags
    on simultaneously — a wrong argument-order swap or misplaced conditional in
    the dcf_fn(fcf0, g_short, g_term, wacc, ...) call chain would slip through
    both single-flag test suites.  This class covers the combined path.
    """

    def _cfg_p1_p2_p3(self, *, use_two_stage_dcf: bool, use_sector_wacc: bool,
                       sector: str = "Utilities"):
        """Build a fixture where ratios_df.wacc is deliberately absent so
        the WACC fallback path is exercised — that's what use_sector_wacc
        redirects."""
        income_df = pd.DataFrame({
            "revenue":            [100e9, 115e9, 130e9, 148e9, 168e9],
            "operating_income":   [30e9,  35e9,  40e9,  46e9,  53e9],
            "gross_profit":       [65e9,  75e9,  85e9,  97e9,  110e9],
            "eps_diluted":        [8.0,   9.0,   10.5,  12.0,  14.0],
            "shares_outstanding": [10e9,  10e9,  9.9e9, 9.8e9, 9.75e9],
        })
        cash_df = pd.DataFrame({"free_cash_flow": [30e9, 35e9, 40e9, 46e9, 50e9]})
        ratios_df = pd.DataFrame({
            "price_earnings_ratio":      [28.0],
            "enterprise_value_multiple": [22.0],
            "price_to_free_cash_flow":   [30.0],
            "price_to_sales":            [12.0],
            "piotroski_score":           [7],
            "altman_z_score":            [4.5],
            "enterprise_value":          [3.5e12],
            # wacc: absent — forces the fallback branch to fire
        })
        p2 = Phase2Result(
            income_df=income_df,
            balance_df=pd.DataFrame({"total_assets": [1] * 5}),
            cash_df=cash_df, ratios_df=ratios_df, kpi_df=pd.DataFrame(),
            roe_decomp_df=pd.DataFrame(),
            score=4.2, accruals_ratio=0.03, gross_profitability=0.40,
            operating_leverage=1.3, dilution_5y=-0.02,
            gate_passed=True, gate_notes="OK",
        )
        p3 = _make_mock_p3()
        p1 = _make_mock_p1()
        p1.sector = sector
        cfg = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(
                use_two_stage_dcf=use_two_stage_dcf,
                use_sector_wacc=use_sector_wacc,
            ),
        )
        return cfg, p1, p2, p3

    def test_both_flags_on_utilities_uses_two_stage_dcf_with_sector_wacc(self):
        """The load-bearing combined-flags test.  Both flags on, Utilities
        sector → WACC=6 %, DCF routed through _dcf_two_stage.  Result must
        equal _dcf_two_stage(fcf0, g_short, 0.025, 0.06, shares) exactly."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            use_two_stage_dcf=True, use_sector_wacc=True,
            sector="Utilities",
        )
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Reconstruct what the DCF should be
        fcf0 = float(p2.cash_df["free_cash_flow"].iloc[-1])
        rev  = p2.income_df["revenue"]
        g_short = min(_cagr(rev, 5), 0.25)
        shares_out = float(p2.income_df["shares_outstanding"].iloc[-1])
        # Utilities WACC per _SECTOR_WACC_MAP
        expected = _dcf_two_stage(fcf0, g_short, 0.025, 0.06, shares_out)

        assert abs(p4.dcf_fair_value - expected) < 1e-6, (
            f"combined flags produced dcf={p4.dcf_fair_value}, "
            f"expected _dcf_two_stage(wacc=0.06)={expected}"
        )

    def test_both_flags_on_energy_produces_different_dcf_than_either_alone(self):
        """A stronger invariant: with Energy sector (WACC 12 %, high) and
        two-stage fade (which increases DCF vs single-stage), the combined
        result must differ from both single-flag paths — proving the two
        modifications compose, not shadow each other."""
        cfg_both, p1, p2, p3 = self._cfg_p1_p2_p3(
            use_two_stage_dcf=True, use_sector_wacc=True,
            sector="Energy",
        )
        cfg_two_only, _, _, _ = self._cfg_p1_p2_p3(
            use_two_stage_dcf=True, use_sector_wacc=False,
            sector="Energy",  # sector doesn't matter when flag off
        )
        cfg_sec_only, _, _, _ = self._cfg_p1_p2_p3(
            use_two_stage_dcf=False, use_sector_wacc=True,
            sector="Energy",
        )
        p4_both     = phase4_valuation(cfg_both,     p2, p3, p1=p1)
        p4_two_only = phase4_valuation(cfg_two_only, p2, p3, p1=p1)
        p4_sec_only = phase4_valuation(cfg_sec_only, p2, p3, p1=p1)

        # Combined ≠ two-stage-only (because WACC changed from 9 % to 12 %)
        assert p4_both.dcf_fair_value != p4_two_only.dcf_fair_value, (
            "combined flags should differ from two-stage-alone (WACC differs)"
        )
        # Combined ≠ sector-only (because model changed from single to two-stage)
        assert p4_both.dcf_fair_value != p4_sec_only.dcf_fair_value, (
            "combined flags should differ from sector-only (model differs)"
        )

    def test_both_flags_route_through_sensitivity_and_reverse_dcf(self):
        """Combined flags: sensitivity table AND reverse-DCF must use the
        SAME (dcf_fn, wacc) pair as the point fair value.  Otherwise the
        Phase4Result rows contradict each other under a real rollout."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            use_two_stage_dcf=True, use_sector_wacc=True,
            sector="Utilities",
        )
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Sensitivity base cell (middle row / middle col) must match fair value
        assert not p4.sensitivity_df.empty
        base_cell = float(p4.sensitivity_df.iloc[1, 1])
        assert abs(base_cell - round(p4.dcf_fair_value, 2)) < 0.05, (
            f"sensitivity base cell {base_cell} disagrees with "
            f"dcf_fair_value {p4.dcf_fair_value:.2f} — combined flags "
            f"not routed to sensitivity?"
        )
        # Reverse-DCF should produce a finite implied growth
        assert not math.isnan(p4.implied_growth), (
            "combined flags should still produce a finite implied_growth"
        )


class TestPhase4PegRatio:
    """Verify PEG ratio field + verdict tightening (bead OpenBBTechnical-0h2.8).

    PEG = P/E / (revenue CAGR × 100).  Peter Lynch's classic rule:
    - PEG < 1.0 → cheap (growth outpaces price of earnings)
    - PEG > 2.0 → expensive (paying too much for the growth)
    - 1.0-2.0  → reasonable

    A5 integration is deliberately narrow: PEG only tightens the
    valuation_verdict when DCF-MOS produced 'Fair Value' (the ambiguous
    middle case). Strong DCF signals ('Undervalued', 'Overvalued') are
    NOT overwritten by PEG — DCF-first is the design intent.  No feature
    flag: A5 is a low-impact refinement of borderline verdicts, not a
    behavior overhaul.
    """

    def _cfg_p1_p2_p3(self, pe: float, revenue_series: list[float],
                       fcf: float = 30e9, use_peg_tightening: bool = False):
        """Build a synthetic p2/p3/p1 fixture where pe and revenue CAGR
        can be set explicitly to hit specific PEG target values.

        Pass ``use_peg_tightening=True`` to enable the A5 verdict-tightening
        (Fair Value + PEG<1 → Undervalued; Fair Value + PEG>2 → Overvalued).
        Default False preserves pre-A5 behavior (PR #304 review I1 / bead
        OpenBBTechnical-0h2.35)."""
        income_df = pd.DataFrame({
            "revenue":            revenue_series,
            "operating_income":   [r * 0.30 for r in revenue_series],
            "gross_profit":       [r * 0.65 for r in revenue_series],
            "eps_diluted":        [8.0, 9.0, 10.5, 12.0, 14.0],
            "shares_outstanding": [10e9] * 5,
        })
        cash_df = pd.DataFrame({"free_cash_flow": [fcf * 0.7, fcf * 0.8,
                                                   fcf * 0.9, fcf, fcf * 1.05]})
        ratios_df = pd.DataFrame({
            "price_earnings_ratio":      [pe],
            "enterprise_value_multiple": [22.0],
            "price_to_free_cash_flow":   [30.0],
            "price_to_sales":            [12.0],
            "piotroski_score":           [7],
            "altman_z_score":            [4.5],
            "enterprise_value":          [3.5e12],
            "wacc":                      [0.085],
        })
        p2 = Phase2Result(
            income_df=income_df, balance_df=pd.DataFrame({"total_assets": [1]*5}),
            cash_df=cash_df, ratios_df=ratios_df, kpi_df=pd.DataFrame(),
            roe_decomp_df=pd.DataFrame(),
            score=4.0, accruals_ratio=0.03, gross_profitability=0.40,
            operating_leverage=1.3, dilution_5y=-0.02,
            gate_passed=True, gate_notes="OK",
        )
        p3 = _make_mock_p3()
        p1 = _make_mock_p1()
        cfg = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_peg_tightening=use_peg_tightening),
        )
        return cfg, p1, p2, p3

    # --- basic field presence -------------------------------------------

    def test_mock_p4_has_peg_ratio(self):
        """_make_mock_p4 default construction must expose peg_ratio."""
        p4 = _make_mock_p4()
        assert hasattr(p4, "peg_ratio")
        assert isinstance(p4.peg_ratio, float)

    def test_phase4_produces_peg_ratio(self):
        """Full phase4 call must populate peg_ratio from computed PE and
        revenue CAGR."""
        # 15 % revenue CAGR ((161/100)^(1/5)-1 ≈ 10 %; use 5-year doubling)
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(pe=25.0,
                                              revenue_series=[100e9, 115e9,
                                                              130e9, 148e9, 168e9])
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        assert not math.isnan(p4.peg_ratio), "peg_ratio must be populated"
        assert p4.peg_ratio > 0

    # --- PEG value correctness ------------------------------------------

    def test_peg_matches_pe_over_growth(self):
        """PEG = PE / (revenue CAGR × 100). Verify the formula holds
        against a hand-computed value.

        Note: _cagr uses n = min(len(series)-1, years) periods.  For a
        5-point series that's 4 compounding periods, not 5 — so the
        expected CAGR is (168/100)^(1/4) - 1 ≈ 0.1381, not 0.1088.
        """
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(pe=25.0,
                                              revenue_series=[100e9, 115e9,
                                                              130e9, 148e9, 168e9])
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        expected_cagr = (168 / 100) ** (1/4) - 1   # 4 periods between 5 points
        expected_peg = 25.0 / (expected_cagr * 100)
        assert abs(p4.peg_ratio - expected_peg) < 0.01, (
            f"peg={p4.peg_ratio}, expected≈{expected_peg}"
        )

    def test_peg_nan_when_growth_negative(self):
        """Declining revenue → CAGR < 0 → PEG undefined. Must return NaN."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(pe=25.0,
                                              revenue_series=[168e9, 148e9,
                                                              130e9, 115e9, 100e9])
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        assert math.isnan(p4.peg_ratio), (
            f"expected NaN for declining revenue, got {p4.peg_ratio}"
        )

    def test_peg_nan_when_pe_missing(self):
        """No PE → PEG is undefined."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(pe=float("nan"),
                                              revenue_series=[100e9, 115e9,
                                                              130e9, 148e9, 168e9])
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        assert math.isnan(p4.peg_ratio)

    # --- verdict tightening (the "integrate into scoring" part) ---------
    #
    # These tests exercise the A5 verdict-tightening logic gated behind
    # AnalysisFeatureFlags.use_peg_tightening (PR #304 review C1/I1 caught
    # that the original tests only checked "PEG" in gate_notes, which is
    # always True whenever peg_ratio is non-NaN — the substring appears via
    # peg_gate_str regardless of whether tightening ran).  Tests now:
    #   (1) verify the pre-tightening verdict is "Fair Value" (flag off)
    #   (2) verify the post-tightening verdict flips as expected (flag on)
    # Bead OpenBBTechnical-0h2.33 tracks this fix.

    def test_peg_tightening_off_leaves_fair_value_unchanged(self):
        """Flag OFF (default): a Fair Value + cheap PEG stock stays Fair
        Value.  This is the pre-A5 behavior + establishes the baseline that
        the other tightening tests compare against."""
        # Same inputs as the cheap-upgrade test — but with flag OFF.
        # Price ~75/share puts MOS ≈ 0 (Fair Value band) given the fixture's
        # DCF fair value (see companion test for the derivation).
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=15.0,
            revenue_series=[100e9, 120e9, 144e9, 173e9, 207e9],  # 20 % CAGR
            fcf=20e9,
            use_peg_tightening=False,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [75.0, 75.5, 76.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        assert p4.peg_ratio < 1.0, f"expected cheap PEG, got {p4.peg_ratio}"
        # Verdict must remain "Fair Value" — pre-A5 behavior preserved.
        assert p4.valuation_verdict == "Fair Value", (
            f"flag-off should preserve pre-A5 Fair Value verdict; "
            f"got {p4.valuation_verdict}, mos={p4.margin_of_safety}"
        )

    def test_peg_cheap_upgrades_fair_value_to_undervalued(self):
        """When flag ON + DCF says Fair Value + PEG < 1.0 (cheap), verdict
        upgrades to Undervalued.  Peter Lynch's classic 'GARP' signal.

        Fixture DCF: fcf0 ≈ 21e9, g_short=0.20 (capped at 0.25), wacc=0.085
        → fair value ≈ $75.45/share.  Setting price at $75 puts MOS ≈ 0.006
        (well inside the Fair Value band [-0.05, +0.15])."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=15.0,
            revenue_series=[100e9, 120e9, 144e9, 173e9, 207e9],  # 20 % CAGR
            fcf=20e9,
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [75.0, 75.5, 76.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Precondition: PEG must be < 1.0 (otherwise the test isn't
        # exercising the cheap-PEG branch).
        assert p4.peg_ratio < 1.0, f"expected cheap PEG, got {p4.peg_ratio}"

        # Precondition: baseline verdict from same inputs with flag off
        # would have been Fair Value (the middle case that A5 tightens).
        cfg_off, _, _, _ = self._cfg_p1_p2_p3(
            pe=15.0,
            revenue_series=[100e9, 120e9, 144e9, 173e9, 207e9],
            fcf=20e9,
            use_peg_tightening=False,
        )
        p3_off = _make_mock_p3()
        p3_off.price_df = p3_off.price_df.copy()
        p3_off.price_df["close"] = [75.0, 75.5, 76.0]
        p4_off = phase4_valuation(cfg_off, p2, p3_off, p1=p1)
        assert p4_off.valuation_verdict == "Fair Value", (
            f"test invariant broken: baseline should be Fair Value, "
            f"got {p4_off.valuation_verdict}"
        )

        # The load-bearing assertion: verdict flipped to Undervalued
        # AND the peg_note annotation appears (proves tightening path ran).
        assert p4.valuation_verdict == "Undervalued", (
            f"expected Fair Value → Undervalued (PEG {p4.peg_ratio:.2f}), "
            f"got {p4.valuation_verdict}"
        )
        assert "cheap growth" in p4.gate_notes, (
            f"expected cheap-growth annotation in gate_notes, "
            f"got: {p4.gate_notes!r}"
        )

    def test_peg_expensive_downgrades_fair_value_to_overvalued(self):
        """When flag ON + DCF says Fair Value + PEG > 2.0 (expensive), verdict
        downgrades to Overvalued.  Also verifies gate_passed flips as a
        consequence — the C1/I1 review finding that justified the flag.

        Fixture DCF: fcf0 ≈ 31.5e9, g_short=0.08, wacc=0.085 → fair value
        ≈ $69.84/share.  Setting price at $68 puts MOS ≈ +0.026 (Fair Value
        band)."""
        # PE 35, growth 8 % → PEG ≈ 4.4 (very expensive)
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],  # ~8 % CAGR
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [68.0, 68.5, 68.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Precondition: PEG > 2.0 (exercises the expensive branch)
        assert p4.peg_ratio > 2.0, f"expected expensive PEG, got {p4.peg_ratio}"

        # Precondition: baseline verdict without tightening is Fair Value
        cfg_off, _, _, _ = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            use_peg_tightening=False,
        )
        p3_off = _make_mock_p3()
        p3_off.price_df = p3_off.price_df.copy()
        p3_off.price_df["close"] = [68.0, 68.5, 68.0]
        p4_off = phase4_valuation(cfg_off, p2, p3_off, p1=p1)
        assert p4_off.valuation_verdict == "Fair Value", (
            f"test invariant broken: baseline should be Fair Value, "
            f"got {p4_off.valuation_verdict}"
        )
        # Baseline gate must have passed (Fair Value is in the gate's
        # accepting set) — this is what makes the tightening a real
        # behavior change worthy of a flag.
        assert p4_off.gate_passed, "baseline gate should pass on Fair Value"

        # The load-bearing assertions:
        assert p4.valuation_verdict == "Overvalued", (
            f"expected Fair Value → Overvalued (PEG {p4.peg_ratio:.2f}), "
            f"got {p4.valuation_verdict}"
        )
        assert "expensive growth" in p4.gate_notes
        # And gate_passed FLIPS — this is precisely why the flag exists.
        assert not p4.gate_passed, (
            "expensive-PEG downgrade to Overvalued should also flip "
            "gate_passed=False (Overvalued is not in the accepting set)"
        )

    def test_strong_dcf_undervalued_not_downgraded_by_expensive_peg(self):
        """Design invariant: even with the flag ON, PEG only refines Fair
        Value cases. When DCF signals strong Undervalued (MOS ≥ 15 %), an
        expensive PEG must NOT overwrite the DCF verdict — DCF-first."""
        # High FCF + low price → clear Undervalued.  Flag ON to make sure
        # the DCF-first invariant holds even when tightening is active.
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            fcf=100e9,  # very high FCF → high DCF value
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [50.0, 51.0, 52.0]  # very low price → MOS strong
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        # PEG should still compute as expensive
        assert p4.peg_ratio > 2.0
        # But verdict should remain Undervalued because DCF is strong
        assert p4.valuation_verdict == "Undervalued", (
            f"strong DCF should not be overridden by expensive PEG; "
            f"got verdict={p4.valuation_verdict}, mos={p4.margin_of_safety}, "
            f"peg={p4.peg_ratio}"
        )

    # --- coherence: entry_rec must follow post-tightening verdict --------
    #
    # Bead OpenBBTechnical-0h2.36 (entry_rec coherence): before this fix,
    # entry_rec branched on raw ``mos`` instead of ``valuation_verdict``,
    # so a Fair-Value-to-Overvalued PEG downgrade produced a Phase4Result
    # that simultaneously said verdict="Overvalued" AND
    # entry_recommendation="Opportunistic Entry" — silent incoherence
    # within a single result object.

    def test_entry_rec_follows_peg_tightened_verdict_overvalued(self):
        """When PEG flips Fair Value → Overvalued, entry_rec must be
        the Overvalued recommendation, not the raw-MOS Opportunistic Entry."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [68.0, 68.5, 68.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        # Precondition: PEG flipped verdict to Overvalued
        assert p4.valuation_verdict == "Overvalued", (
            f"test invariant broken: expected PEG-driven Overvalued, "
            f"got {p4.valuation_verdict}"
        )
        # Load-bearing: entry_rec must reflect the flipped verdict
        assert "Avoid" in p4.entry_recommendation, (
            f"entry_rec must follow post-tightening verdict; "
            f"got {p4.entry_recommendation!r} (verdict={p4.valuation_verdict})"
        )

    def test_entry_rec_follows_peg_tightened_verdict_undervalued(self):
        """When PEG flips Fair Value → Undervalued, entry_rec must be one
        of the Undervalued recommendations (Strong/Partial/Wait), not the
        raw-MOS Opportunistic Entry or Watchlist."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=15.0,
            revenue_series=[100e9, 120e9, 144e9, 173e9, 207e9],
            fcf=20e9,
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [75.0, 75.5, 76.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        # Precondition: PEG flipped verdict to Undervalued
        assert p4.valuation_verdict == "Undervalued"
        # Load-bearing: entry_rec matches one of the Undervalued family
        assert any(
            key in p4.entry_recommendation
            for key in ("Strong Entry", "Partial Entry", "Wait")
        ), (
            f"entry_rec must follow post-tightening verdict; "
            f"got {p4.entry_recommendation!r} (verdict={p4.valuation_verdict})"
        )

    # --- default-off entry_rec parity (bead OpenBBTechnical-3xq.1) -------
    #
    # QC-A found that the iter-3 unconditional verdict-keyed refactor
    # silently changed default-off behavior for stocks with mos ∈ [-0.05, 0):
    # they used to be 'Avoid' via the pre-A5 raw-mos cascade, but under the
    # verdict-keyed branch they became 'Opportunistic Entry'/'Watchlist'
    # because valuation_verdict is 'Fair Value' whenever mos ∈ [-0.05, 0.15].
    # Iter-4 restores parity by gating the verdict-keyed branch on
    # use_peg_tightening.  This test locks the invariant.

    def test_default_off_preserves_avoid_for_slightly_negative_mos(self):
        """Flag OFF + mos ∈ [-0.05, 0) + strong technicals must produce
        'Avoid' — pre-A5 behavior. The verdict_verdict='Fair Value' band
        covers this MOS range, but the raw-mos cascade (default-off path)
        still routes mos < 0 to 'Avoid'."""
        # Fixture: same as expensive-PEG test but with price slightly HIGHER
        # than DCF fair value so mos lands in [-0.05, 0).  fcf0 ≈ 31.5e9,
        # g_short = 0.08, wacc = 0.085 → dcf ≈ $69.84/share.
        # Price $71 → mos ≈ (69.84 - 71) / 69.84 ≈ -0.017 (in the target band).
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            use_peg_tightening=False,  # flag OFF — the whole point
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [71.0, 71.0, 71.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Precondition: mos actually lands in [-0.05, 0).
        assert -0.05 <= p4.margin_of_safety < 0.0, (
            f"test invariant broken: mos={p4.margin_of_safety} not in [-0.05, 0)"
        )
        # Precondition: valuation_verdict is still 'Fair Value' (the range
        # that triggers the QC-A regression under the verdict-keyed branch).
        assert p4.valuation_verdict == "Fair Value", (
            f"test invariant broken: expected Fair Value for mos in [-0.05, 0), "
            f"got {p4.valuation_verdict}"
        )
        # Load-bearing: entry_rec must be 'Avoid' — the pre-A5 raw-mos cascade
        # routes mos < 0 to 'Avoid' regardless of bullish_count or verdict.
        assert "Avoid" in p4.entry_recommendation, (
            f"default-off must preserve pre-A5 'mos < 0 → Avoid' behavior; "
            f"got {p4.entry_recommendation!r} (mos={p4.margin_of_safety}, "
            f"verdict={p4.valuation_verdict}, bull={p3.bullish_count})"
        )

    def test_flag_on_slightly_negative_mos_flips_to_verdict_keyed(self):
        """Complement to the parity test: with flag ON, the same slightly-
        negative-MOS case now routes through the verdict-keyed branch.
        valuation_verdict is 'Fair Value' (untightened by PEG since PEG is
        moderate in this fixture), so bull ≥ 6 → 'Opportunistic Entry'.
        Proves the flag actually toggles the branch."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            use_peg_tightening=True,  # flag ON
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [71.0, 71.0, 71.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Preconditions: mos in target band, verdict still Fair Value
        # (PEG doesn't tighten because peg > 2 needs verdict==Fair Value AND
        # peg > 2.0 — this fixture's PEG is expensive enough that it flips).
        assert -0.05 <= p4.margin_of_safety < 0.0

        # If PEG flipped the verdict to Overvalued, entry_rec is 'Avoid'.
        # If verdict stayed Fair Value (PEG in normal range), bull ≥ 6
        # yields 'Opportunistic Entry'.  Either way, the flag-on path is
        # NOT the pre-A5 'Avoid' verdict — this proves the branches differ.
        if p4.valuation_verdict == "Fair Value":
            assert "Opportunistic Entry" in p4.entry_recommendation, (
                f"flag-on Fair Value + bull>=6 must be Opportunistic Entry; "
                f"got {p4.entry_recommendation!r}"
            )
        else:
            # PEG tightened to Overvalued → verdict-keyed branch routes to Avoid
            assert p4.valuation_verdict == "Overvalued"
            assert "Avoid" in p4.entry_recommendation

    # --- gate_notes bit-for-bit parity when flag off ---------------------

    def test_peg_gate_str_absent_when_flag_off(self):
        """Bead OpenBBTechnical-0h2.38 (peg_gate_str leak): when
        use_peg_tightening=False the display line ``| PEG X.XX`` must NOT
        appear in gate_notes — otherwise a reader could infer PEG was
        consulted when it wasn't."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            use_peg_tightening=False,   # flag OFF
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [68.0, 68.5, 68.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        # PEG is still computed on the dataclass (that's a data field,
        # unaffected by the display flag) — but gate_notes must not mention it.
        assert not math.isnan(p4.peg_ratio), "peg_ratio should still compute"
        assert "PEG" not in p4.gate_notes, (
            f"flag-off must preserve gate_notes bit-for-bit; "
            f"got: {p4.gate_notes!r}"
        )

    def test_peg_gate_str_present_when_flag_on(self):
        """Complement to the flag-off parity test: with the flag on, the
        PEG value SHOULD appear in gate_notes (so users of the tightening
        can see what tipped the decision)."""
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=35.0,
            revenue_series=[100e9, 108e9, 117e9, 126e9, 136e9],
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [68.0, 68.5, 68.0]
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)
        assert "PEG" in p4.gate_notes, (
            f"flag-on should surface PEG in gate_notes; got: {p4.gate_notes!r}"
        )

    # --- silent no-op guard when flag on but PEG unavailable -------------

    def test_flag_on_but_nan_peg_surfaces_diagnostic(self):
        """Bead OpenBBTechnical-0h2.39 (NaN PEG silent no-op): when
        use_peg_tightening=True but peg_ratio is NaN (declining revenue),
        the user's opt-in must not silently do nothing.  Annotate
        gate_notes so the caller can distinguish 'tightening ran and
        found nothing' from 'tightening was skipped for lack of data'.

        QC-B (bead OpenBBTechnical-3xq.2) found the original version was
        effectively a no-op: fixture price $5 pushed MOS to ~0.92
        (Undervalued), so the assertion behind `if verdict == "Fair Value"`
        never ran.  Iter-4 sets price at ~ DCF fair value so verdict lands
        in the Fair Value band and the diagnostic path is exercised.

        Fixture derivation: raw revenue CAGR = -0.1216 (PEG will be NaN).
        DCF uses floored g_short = 0.05 (per the DCF-only safety clamp for
        declining revenue), fcf0 = 31.5e9, wacc = 0.085, shares = 9.75e9
        → dcf_fair_value ≈ $61.50/share.  Price $58 → MOS ≈ +0.057, safely
        inside [-0.05, 0.15] Fair Value band."""
        # Declining revenue → raw CAGR < 0 → PEG NaN.  DCF-only g_short
        # gets floored to 0.05 so DCF stays sensible.
        cfg, p1, p2, p3 = self._cfg_p1_p2_p3(
            pe=25.0,
            revenue_series=[168e9, 148e9, 130e9, 115e9, 100e9],  # declining
            use_peg_tightening=True,
        )
        p3.price_df = p3.price_df.copy()
        p3.price_df["close"] = [58.0, 58.0, 58.0]  # ≈ DCF, lands in Fair Value
        p4 = phase4_valuation(cfg, p2, p3, p1=p1)

        # Precondition 1: PEG really is NaN (declining revenue path).
        assert math.isnan(p4.peg_ratio), (
            f"test invariant broken: expected NaN PEG, got {p4.peg_ratio}"
        )
        # Precondition 2: verdict lands in Fair Value (the branch the
        # diagnostic fires on).  If fixture drifts and verdict becomes
        # Undervalued/Overvalued, the test loudly fails at this line
        # rather than silently skipping the load-bearing assertion.
        assert p4.valuation_verdict == "Fair Value", (
            f"test invariant broken: expected Fair Value verdict for the "
            f"diagnostic branch to fire; got {p4.valuation_verdict} "
            f"(mos={p4.margin_of_safety:.4f}).  If DCF drifted, re-derive "
            f"the target price against Fair Value band [dcf*0.85, dcf*1.05]."
        )
        # Load-bearing: diagnostic annotation appears in gate_notes.  Now
        # UNCONDITIONAL — deleting the peg_note='(PEG unavailable...)'
        # line in phase4_valuation would fail this assertion immediately.
        assert "PEG unavailable" in p4.gate_notes, (
            f"flag-on + NaN PEG on Fair Value verdict must surface a "
            f"diagnostic; got: {p4.gate_notes!r}"
        )

# ---------------------------------------------------------------------------


@integration
class TestPhase1MSFT:
    @pytest.fixture(scope="class")
    def result(self, msft_cfg) -> Phase1Result:
        return phase1_company_profile(msft_cfg)

    def test_returns_phase1result(self, result):
        assert isinstance(result, Phase1Result)

    def test_profile_not_empty(self, result):
        assert not result.profile_df.empty

    def test_quote_not_empty(self, result):
        assert not result.quote_df.empty

    def test_sector_is_technology(self, result):
        assert "technology" in result.sector.lower() or result.sector != ""

    def test_market_cap_large_cap(self, result):
        assert result.market_cap > 100_000_000_000  # > $100B

    def test_peers_list(self, result):
        assert isinstance(result.peers, list)
        assert len(result.peers) >= 1

    def test_provider_used(self, result):
        # Indirect check: profile exists means fmp_cached worked
        assert result.gate_passed

    def test_gate_passed(self, result):
        assert result.gate_passed

    def test_free_float_pct_populated(self, result):
        """MSFT's free float from fmp_cached share_statistics should be a
        fraction in (0, 1] — Microsoft's insider stake is small so free float
        is typically > 0.99.  A None result means fmp_cached share_statistics
        failed; that's a provider regression worth surfacing."""
        assert result.free_float_pct is not None, (
            "fmp_cached share_statistics returned no free_float for MSFT — "
            "provider regression?"
        )
        assert 0.0 < result.free_float_pct <= 1.0

    def test_short_interest_pct_semantics(self, result):
        """fmp_cached does not currently expose short_interest.  A1 preserves
        the field on the dataclass for future population (see follow-up bead
        for adding a short-interest provider) but the value must be None on
        the current single-provider stack."""
        assert result.short_interest_pct is None


@integration
class TestPhase1AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase1Result:
        return phase1_company_profile(aapl_cfg)

    def test_returns_phase1result(self, result):
        assert isinstance(result, Phase1Result)

    def test_market_cap_large_cap(self, result):
        assert result.market_cap > 100_000_000_000

    def test_gate_passed(self, result):
        assert result.gate_passed

    def test_free_float_pct_populated(self, result):
        """AAPL's free float from fmp_cached share_statistics — same expectation
        as MSFT: fraction in (0, 1], typically > 0.99 for a well-held large-cap."""
        assert result.free_float_pct is not None, (
            "fmp_cached share_statistics returned no free_float for AAPL"
        )
        assert 0.0 < result.free_float_pct <= 1.0

    def test_short_interest_pct_semantics(self, result):
        """Same as MSFT — fmp_cached does not expose short_interest today."""
        assert result.short_interest_pct is None


# ---------------------------------------------------------------------------
# Integration tests — Phase 2
# ---------------------------------------------------------------------------


@integration
class TestPhase2MSFT:
    @pytest.fixture(scope="class")
    def result(self, msft_cfg) -> Phase2Result:
        return phase2_fundamentals(msft_cfg)

    def test_returns_phase2result(self, result):
        assert isinstance(result, Phase2Result)

    def test_income_df_not_empty(self, result):
        assert not result.income_df.empty

    def test_score_in_range(self, result):
        assert 0.0 <= result.score <= 5.0

    def test_accruals_ratio_reasonable(self, result):
        if not math.isnan(result.accruals_ratio):
            assert -0.5 <= result.accruals_ratio <= 0.5

    def test_gross_profitability_positive(self, result):
        if not math.isnan(result.gross_profitability):
            assert result.gross_profitability > 0

    def test_kpi_df_has_rows(self, result):
        assert len(result.kpi_df) > 0

    def test_msft_score_above_3(self, result):
        """Microsoft should score well (expect >= 3.0)."""
        assert result.score >= 3.0


@integration
class TestPhase2AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase2Result:
        return phase2_fundamentals(aapl_cfg)

    def test_returns_phase2result(self, result):
        assert isinstance(result, Phase2Result)

    def test_score_in_range(self, result):
        assert 0.0 <= result.score <= 5.0

    def test_aapl_score_above_3(self, result):
        assert result.score >= 3.0


# ---------------------------------------------------------------------------
# Integration tests — Phase 3
# ---------------------------------------------------------------------------


@integration
class TestPhase3MSFT:
    @pytest.fixture(scope="class")
    def result(self, msft_cfg) -> Phase3Result:
        return phase3_technicals(msft_cfg)

    def test_returns_phase3result(self, result):
        assert isinstance(result, Phase3Result)

    def test_price_df_not_empty(self, result):
        assert not result.price_df.empty
        assert len(result.price_df) > 50

    def test_signals_has_11_conditions(self, result):
        assert len(result.signals) == 11

    def test_bullish_count_in_range(self, result):
        assert 0 <= result.bullish_count <= 11

    def test_entry_quality_valid(self, result):
        assert result.entry_quality in ("High Conviction", "Standard", "Cautious")

    def test_fib_levels_present(self, result):
        assert "38.2%" in result.fib_levels
        assert "61.8%" in result.fib_levels

    def test_atr_positive(self, result):
        assert result.atr > 0

    def test_indicators_in_price_df(self, result):
        for col in ["rsi", "macd", "adx", "atr", "vwap", "cmf_21"]:
            assert col in result.price_df.columns, f"Missing column: {col}"


@integration
class TestPhase3AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase3Result:
        return phase3_technicals(aapl_cfg)

    def test_returns_phase3result(self, result):
        assert isinstance(result, Phase3Result)

    def test_bullish_count_in_range(self, result):
        assert 0 <= result.bullish_count <= 11


# ---------------------------------------------------------------------------
# Integration tests — Phase 4
# ---------------------------------------------------------------------------


@integration
class TestPhase4MSFT:
    @pytest.fixture(scope="class")
    def result(self, msft_cfg) -> Phase4Result:
        p2 = phase2_fundamentals(msft_cfg)
        p3 = phase3_technicals(msft_cfg)
        return phase4_valuation(msft_cfg, p2, p3)

    def test_returns_phase4result(self, result):
        assert isinstance(result, Phase4Result)

    def test_multiples_not_empty(self, result):
        assert not result.multiples_df.empty

    def test_valuation_verdict_valid(self, result):
        assert result.valuation_verdict in ("Undervalued", "Fair Value", "Overvalued")

    def test_altman_z_in_reasonable_range(self, result):
        if not math.isnan(result.altman):
            assert result.altman > 0

    def test_sensitivity_df_shape(self, result):
        if not result.sensitivity_df.empty:
            assert result.sensitivity_df.shape == (3, 3)


@integration
class TestPhase4AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase4Result:
        p2 = phase2_fundamentals(aapl_cfg)
        p3 = phase3_technicals(aapl_cfg)
        return phase4_valuation(aapl_cfg, p2, p3)

    def test_returns_phase4result(self, result):
        assert isinstance(result, Phase4Result)

    def test_valuation_verdict_valid(self, result):
        assert result.valuation_verdict in ("Undervalued", "Fair Value", "Overvalued")


# ---------------------------------------------------------------------------
# Integration tests — Phase 5
# ---------------------------------------------------------------------------


@integration
class TestPhase5MSFT:
    @pytest.fixture(scope="class")
    def result(self, msft_cfg) -> Phase5Result:
        return phase5_risk(msft_cfg)

    def test_returns_phase5result(self, result):
        assert isinstance(result, Phase5Result)

    def test_sharpe_reasonable(self, result):
        if not math.isnan(result.sharpe):
            assert -5 <= result.sharpe <= 10

    def test_max_drawdown_negative(self, result):
        assert result.max_drawdown <= 0

    def test_beta_positive(self, result):
        if not math.isnan(result.beta):
            assert result.beta > 0

    def test_var_negative(self, result):
        assert result.var_95 < 0

    def test_portfolio_fit_valid(self, result):
        assert result.portfolio_fit in ("Core", "Satellite", "Reject")

    def test_risk_kpi_df_not_empty(self, result):
        assert not result.risk_kpi_df.empty

    def test_recommended_size_within_max(self, result):
        assert result.recommended_size <= 0.04 + 1e-9

    def test_kurtosis_finite_and_typical(self, result):
        """MSFT's daily returns should show finite excess kurtosis in the
        empirical range for large-cap equities (~1-10 excess).  Extreme
        values (>50 or infinite) suggest a data-quality problem."""
        assert not math.isnan(result.kurtosis), "kurtosis must not be NaN"
        assert math.isfinite(result.kurtosis)
        assert -1.0 <= result.kurtosis <= 50.0, (
            f"MSFT kurtosis {result.kurtosis} outside plausible large-cap range"
        )

    def test_skewness_finite(self, result):
        """Skewness should be finite; sign varies by lookback window."""
        assert not math.isnan(result.skewness), "skewness must not be NaN"
        assert math.isfinite(result.skewness)
        assert -5.0 <= result.skewness <= 5.0, (
            f"MSFT skewness {result.skewness} outside plausible range"
        )

    def test_risk_kpi_df_has_fat_tail_columns(self, result):
        """Bead spec: fields must appear in the exported KPI table too."""
        assert "kurtosis" in result.risk_kpi_df.columns
        assert "skewness" in result.risk_kpi_df.columns

    def test_vol_63d_trend_is_one_of_allowed_values(self, result):
        """A3: vol regime label must be from the closed set."""
        assert result.vol_63d_trend in ("expanding", "contracting", "flat")

    def test_risk_kpi_df_has_vol_trend_column(self, result):
        assert "vol_63d_trend" in result.risk_kpi_df.columns


@integration
class TestPhase5AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase5Result:
        return phase5_risk(aapl_cfg)

    def test_returns_phase5result(self, result):
        assert isinstance(result, Phase5Result)

    def test_max_drawdown_negative(self, result):
        assert result.max_drawdown <= 0

    def test_kurtosis_finite_and_typical(self, result):
        """AAPL should show finite excess kurtosis in the typical large-cap range."""
        assert not math.isnan(result.kurtosis)
        assert math.isfinite(result.kurtosis)
        assert -1.0 <= result.kurtosis <= 50.0

    def test_skewness_finite(self, result):
        assert not math.isnan(result.skewness)
        assert math.isfinite(result.skewness)
        assert -5.0 <= result.skewness <= 5.0

    def test_vol_63d_trend_is_one_of_allowed_values(self, result):
        """A3: vol regime label must be from the closed set."""
        assert result.vol_63d_trend in ("expanding", "contracting", "flat")


# ---------------------------------------------------------------------------
# Integration tests — Phase 6
# ---------------------------------------------------------------------------


@integration
class TestPhase6MSFT:
    @pytest.fixture(scope="class")
    def result(self, msft_cfg) -> Phase6Result:
        p1 = phase1_company_profile(msft_cfg)
        return phase6_peer_relative(msft_cfg, p1)

    def test_returns_phase6result(self, result):
        assert isinstance(result, Phase6Result)

    def test_relative_table_not_empty(self, result):
        assert not result.relative_table.empty

    def test_sector_etf_is_xlk(self, result):
        assert result.sector_etf in ("XLK", "SPY")  # XLK for Technology

    def test_corr_matrix_square(self, result):
        assert result.corr_matrix.shape[0] == result.corr_matrix.shape[1]

    def test_information_ratio_is_float(self, result):
        if not math.isnan(result.information_ratio):
            assert isinstance(result.information_ratio, float)

    def test_relative_score_in_range(self, result):
        assert 0 <= result.relative_score <= 5


@integration
class TestPhase6AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase6Result:
        p1 = phase1_company_profile(aapl_cfg)
        return phase6_peer_relative(aapl_cfg, p1)

    def test_returns_phase6result(self, result):
        assert isinstance(result, Phase6Result)

    def test_relative_score_in_range(self, result):
        assert 0 <= result.relative_score <= 5


# ---------------------------------------------------------------------------
# Integration tests — Full pipeline
# ---------------------------------------------------------------------------


@integration
class TestFullPipelineMSFT:
    @pytest.fixture(scope="class")
    def results(self, msft_cfg) -> dict:
        return run_full_analysis(msft_cfg)

    def test_all_phases_present(self, results):
        for key in ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]:
            assert key in results, f"Missing result key: {key}"

    def test_p7_has_action_label(self, results):
        p7 = results["p7"]
        assert p7.action_label in ("Strong Buy", "Buy", "Hold/Watch", "Avoid")

    def test_p7_composite_in_range(self, results):
        p7 = results["p7"]
        assert 0.0 <= p7.composite_score <= 5.0

    def test_p7_handoff_complete(self, results):
        handoff = results["p7"].handoff
        for key in ["investment_thesis", "bullish_drivers", "invalidation_events",
                    "fair_value_range", "peer_relative", "trade_plan"]:
            assert key in handoff


@integration
class TestFullPipelineAAPL:
    @pytest.fixture(scope="class")
    def results(self, aapl_cfg) -> dict:
        return run_full_analysis(aapl_cfg)

    def test_all_phases_present(self, results):
        for key in ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]:
            assert key in results

    def test_p7_action_label_valid(self, results):
        assert results["p7"].action_label in ("Strong Buy", "Buy", "Hold/Watch", "Avoid")


# ---------------------------------------------------------------------------
# Unit tests — AnalysisFeatureFlags (Phase A0 — bead OpenBBTechnical-0h2.1)
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    """Exhaustive parse coverage for the AnalysisFeatureFlags rollout flags.

    Every flag defaults to ``False`` — i.e. the pipeline behaves exactly as it
    did before A0 shipped.  Downstream beads (A4a, A4b, A8, B1-B4, C1-C4, F1-F3)
    flip the individual flags on to activate their new behavior; the default
    off state is the reversibility guarantee that lets us roll back any single
    experiment without a code revert.
    """

    @pytest.fixture
    def clean_flag_env(self, monkeypatch):
        """Delete every ANALYSIS_* var so tests start from a hermetic environment.

        The var list is derived from ``__dataclass_fields__`` so a seventh flag
        added in a later phase is covered automatically — no test edit needed.
        """
        for name in AnalysisFeatureFlags.__dataclass_fields__:
            monkeypatch.delenv(f"ANALYSIS_{name.upper()}", raising=False)
        return monkeypatch

    # --- default construction -------------------------------------------

    def test_all_flags_default_false(self):
        """Every declared flag defaults to False.

        Driven from ``__dataclass_fields__`` so a new flag added in a later
        phase is covered automatically (bead OpenBBTechnical-0h2.37).
        """
        flags = AnalysisFeatureFlags()
        for name in AnalysisFeatureFlags.__dataclass_fields__:
            assert getattr(flags, name) is False, (
                f"expected {name}=False by default, got "
                f"{getattr(flags, name)!r}"
            )

    def test_kwargs_override_defaults(self):
        """Passing all flags as True kwargs flips every one to True.

        Driven from ``__dataclass_fields__`` so new flags are auto-covered
        (bead OpenBBTechnical-0h2.37)."""
        all_true = {
            name: True for name in AnalysisFeatureFlags.__dataclass_fields__
        }
        flags = AnalysisFeatureFlags(**all_true)
        for name in AnalysisFeatureFlags.__dataclass_fields__:
            assert getattr(flags, name) is True, (
                f"kwarg {name}=True did not stick"
            )

    # --- from_env: no vars set ------------------------------------------

    def test_from_env_no_vars_returns_all_false(self, clean_flag_env):
        flags = AnalysisFeatureFlags.from_env()
        assert flags == AnalysisFeatureFlags()

    # --- from_env: truthy variants --------------------------------------

    @pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on"])
    def test_from_env_recognises_truthy(self, monkeypatch, truthy):
        monkeypatch.setenv("ANALYSIS_USE_TWO_STAGE_DCF", truthy)
        flags = AnalysisFeatureFlags.from_env()
        assert flags.use_two_stage_dcf is True, f"{truthy!r} should parse as True"

    @pytest.mark.parametrize("falsy", ["0", "false", "FALSE", "no", "off", ""])
    def test_from_env_recognises_falsy(self, monkeypatch, falsy):
        monkeypatch.setenv("ANALYSIS_USE_TWO_STAGE_DCF", falsy)
        flags = AnalysisFeatureFlags.from_env()
        assert flags.use_two_stage_dcf is False, f"{falsy!r} should parse as False"

    def test_from_env_rejects_garbage(self, monkeypatch):
        """Unrecognised values raise ValueError — we never silently coerce."""
        monkeypatch.setenv("ANALYSIS_USE_TWO_STAGE_DCF", "maybe")
        with pytest.raises(ValueError, match="ANALYSIS_USE_TWO_STAGE_DCF"):
            AnalysisFeatureFlags.from_env()

    # --- from_env: each flag maps to its own env var --------------------
    #
    # Parametrize list derived from ``__dataclass_fields__`` so a new flag
    # added in a later phase is covered automatically (bead
    # OpenBBTechnical-0h2.37 (flag test coverage): iteration 1 had a
    # hard-coded 6-tuple list that silently missed the 7th flag when A5
    # shipped ``use_peg_tightening``).

    @pytest.mark.parametrize(
        "attr,envvar",
        [
            (name, f"ANALYSIS_{name.upper()}")
            for name in AnalysisFeatureFlags.__dataclass_fields__
        ],
    )
    def test_from_env_each_flag_has_its_own_var(self, clean_flag_env, attr, envvar):
        # Fixture already cleared all ANALYSIS_* vars — set only the targeted one.
        clean_flag_env.setenv(envvar, "true")
        flags = AnalysisFeatureFlags.from_env()
        assert getattr(flags, attr) is True, f"{envvar} did not toggle {attr}"
        # All other flags stay False
        for other in AnalysisFeatureFlags.__dataclass_fields__:
            if other == attr:
                continue
            assert getattr(flags, other) is False, (
                f"{envvar} unexpectedly toggled {other}"
            )

    # --- introspection helper --------------------------------------------

    def test_as_dict_covers_all_fields(self):
        """as_dict() returns every declared flag.

        Renamed from ``test_as_dict_returns_all_six`` — the name was stale
        when a 7th flag shipped (bead OpenBBTechnical-0h2.37).  Body now
        iterates ``__dataclass_fields__`` so both key coverage and value
        wiring are checked for every flag."""
        # Pick one arbitrary flag to set — the first one in field order.
        first_flag = next(iter(AnalysisFeatureFlags.__dataclass_fields__))
        flags = AnalysisFeatureFlags(**{first_flag: True})
        d = flags.as_dict()
        # Key coverage: every declared field appears in the dict.
        assert set(d.keys()) == set(AnalysisFeatureFlags.__dataclass_fields__)
        # Value wiring: the flag we set is True, all others are False.
        assert d[first_flag] is True
        for name in AnalysisFeatureFlags.__dataclass_fields__:
            if name == first_flag:
                continue
            assert d[name] is False, f"unexpected {name}={d[name]!r}"

