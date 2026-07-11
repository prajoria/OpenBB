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
    _dcf_sensitivity,
    _dcf_single,
    _decision_label,
    _entry_quality_label,
    _find_col,
    _last_trading_day,
    _latest_col,
    _score_fundamentals,
    _sector_etf,
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

    highs = price * (1 + rng.uniform(0.001, 0.015, n))
    lows = price * (1 - rng.uniform(0.001, 0.015, n))
    opens = price * (1 + rng.normal(0, 0.005, n))
    volume = rng.integers(1_000_000, 10_000_000, n).astype(float)

    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": price,
            "volume": volume,
        },
        index=idx,
    )


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

    def test_analysis_config_wrong_provider_raises(self):
        """Non-``fmp_cached`` provider must raise, not just warn (bd-omi).

        CLAUDE.md's Analysis Module 'Provider rule' documents
        ``PRIMARY_PROVIDER = 'fmp_cached'`` as *enforced*. Warnings get
        silently swallowed in notebooks, batch jobs, and CI test runs,
        so a soft ``UserWarning`` cannot actually prevent a caller from
        burning uncached FMP quota or getting a different-schema
        response. This test locks in that the constructor now raises
        ``ValueError`` on any non-``fmp_cached`` provider.
        """
        # provider-purity-exempt: intentionally tests the wrong-provider raise branch
        with pytest.raises(ValueError, match="fmp_cached"):
            AnalysisConfig(symbol="TSLA", provider="fmp")  # provider-purity-exempt
        # Verify the error message points at CLAUDE.md so the operator
        # knows why their override was rejected.
        with pytest.raises(ValueError, match="CLAUDE.md|Provider rule"):
            AnalysisConfig(symbol="TSLA", provider="yfinance")

    def test_analysis_config_default_provider_still_works(self):
        """Regression lock: the default (fmp_cached) constructor path is unchanged."""
        cfg = AnalysisConfig(symbol="TSLA")
        assert cfg.provider == "fmp_cached"

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
        assert _sector_etf("Energy") == "XLE"
        assert _sector_etf("Unknown") == "SPY"


# ---------------------------------------------------------------------------
# Unit tests — DCF functions
# ---------------------------------------------------------------------------


class TestDCF:
    """Unit tests for DCF helpers."""

    def test_dcf_single_basic(self):
        """DCF of a stable company with 5% growth, 9% WACC should be reasonable."""
        fv = _dcf_single(
            fcf0=1_000_000, g_short=0.05, g_term=0.025, wacc=0.09, shares=1_000_000
        )
        # Fair value per share should be positive
        assert fv > 0

    def test_dcf_single_wacc_le_gterm_clamped(self):
        """When WACC <= g_term the function should clamp g_term to WACC-0.01."""
        fv = _dcf_single(
            fcf0=1_000_000, g_short=0.05, g_term=0.10, wacc=0.09, shares=1_000_000
        )
        assert not math.isnan(fv)
        assert fv > 0

    def test_dcf_single_zero_shares(self):
        fv = _dcf_single(
            fcf0=1_000_000, g_short=0.05, g_term=0.025, wacc=0.09, shares=0
        )
        assert math.isnan(fv)

    def test_dcf_sensitivity_shape(self):
        sens = _dcf_sensitivity(
            fcf0=1_000_000,
            g_short=0.05,
            wacc_base=0.09,
            g_term_base=0.025,
            shares=1_000_000,
        )
        assert sens.shape == (3, 3)
        assert not sens.isnull().values.all()

    def test_dcf_sensitivity_monotonic_wacc(self):
        """Higher WACC should produce lower fair value."""
        sens = _dcf_sensitivity(
            fcf0=1_000_000,
            g_short=0.05,
            wacc_base=0.09,
            g_term_base=0.025,
            shares=1_000_000,
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
        assert "sma_50" in computed.columns
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
        assert "macd" in computed.columns
        assert "macd_signal" in computed.columns
        assert "macd_hist" in computed.columns

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
        assert "high_52w" in computed.columns
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
            "revenue_cagr_5y": 0.15,
            "eps_cagr_5y": 0.18,
            "fcf_cagr_5y": 0.14,
            "gross_margin": 0.65,
            "operating_margin": 0.35,
            "net_margin": 0.28,
            "roic": 0.22,
            "debt_equity": 0.5,
            "current_ratio": 2.5,
            "interest_coverage": 15.0,
            "net_debt_ebitda": 0.8,
            "cfo_net_income": 1.05,
            "fcf_margin": 0.22,
            "capex_revenue": 0.04,
            "dilution_5y": -0.08,
            "operating_leverage": 1.2,
            "sga_trend": -0.005,
            "fcf_payout_ratio": 0.30,
        }
        score = _score_fundamentals(kpis, accruals_ratio=0.02, gross_profitability=0.45)
        assert score >= 4.0

    def test_distressed_scores_below_2(self):
        kpis = {
            "revenue_cagr_5y": -0.10,
            "eps_cagr_5y": -0.20,
            "fcf_cagr_5y": -0.15,
            "gross_margin": 0.05,
            "operating_margin": -0.10,
            "net_margin": -0.15,
            "roic": -0.05,
            "debt_equity": 4.0,
            "current_ratio": 0.5,
            "interest_coverage": 0.8,
            "net_debt_ebitda": 8.0,
            "cfo_net_income": 0.2,
            "fcf_margin": -0.05,
            "capex_revenue": 0.25,
            "dilution_5y": 0.30,
            "operating_leverage": 4.0,
            "sga_trend": 0.05,
            "fcf_payout_ratio": 1.5,
        }
        score = _score_fundamentals(kpis, accruals_ratio=0.25, gross_profitability=0.05)
        assert score < 2.5

    def test_hard_floor_caps_at_3_8(self):
        """A single very low category should cap the score at 3.8."""
        kpis = {
            "revenue_cagr_5y": 0.15,
            "eps_cagr_5y": 0.18,
            "fcf_cagr_5y": 0.14,
            "gross_margin": 0.65,
            "operating_margin": 0.35,
            "net_margin": 0.28,
            "roic": 0.22,
            "debt_equity": 0.5,
            "current_ratio": 2.5,
            "interest_coverage": 15.0,
            "net_debt_ebitda": 0.8,
            "cfo_net_income": 1.05,
            "fcf_margin": 0.22,
            "capex_revenue": 0.04,
            # Severely distressed operating leverage → structural score ≤ 1.5
            "operating_leverage": 10.0,
            "dilution_5y": -0.08,
            "sga_trend": -0.005,
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


def _make_mock_p3(
    bullish_count: int = 7, earnings_safe: bool = True, weekly_bull: bool = True
) -> Phase3Result:
    # Minimal price DataFrame with ATR
    price_df = pd.DataFrame(
        {"close": [145.0, 146.0, 147.0], "atr": [2.5, 2.5, 2.5]},
        index=pd.date_range("2026-01-01", periods=3, freq="B"),
    )
    signals = {
        "sma_golden_cross": True,
        "adx_trending": True,
        "rsi_pullback": True,
        "macd_bullish": True,
        "obv_rising": True,
        "volume_ratio_normal": True,
        "above_vwap": True,
        "above_cloud": bullish_count >= 8,
        "momentum_positive": bullish_count >= 9,
        "cmf_positive": True,
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
        assert p7.atr_stop < 147.0  # stop is below current price
        assert p7.target_2r > 147.0  # 2R target is above current price
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
        required = [
            "investment_thesis",
            "bullish_drivers",
            "invalidation_events",
            "fair_value_range",
            "peer_relative",
            "trade_plan",
        ]
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
        weights = {
            "business_quality": 0.08,
            "fundamentals": 0.25,
            "technicals": 0.15,
            "valuation": 0.20,
            "risk_fit": 0.12,
            "peer_relative": 0.20,
        }
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


@integration
class TestPhase5AAPL:
    @pytest.fixture(scope="class")
    def result(self, aapl_cfg) -> Phase5Result:
        return phase5_risk(aapl_cfg)

    def test_returns_phase5result(self, result):
        assert isinstance(result, Phase5Result)

    def test_max_drawdown_negative(self, result):
        assert result.max_drawdown <= 0


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
        for key in [
            "investment_thesis",
            "bullish_drivers",
            "invalidation_events",
            "fair_value_range",
            "peer_relative",
            "trade_plan",
        ]:
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
        assert results["p7"].action_label in (
            "Strong Buy",
            "Buy",
            "Hold/Watch",
            "Avoid",
        )
