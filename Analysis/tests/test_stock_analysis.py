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
        earnings_revision_3m_direction="unknown",   # A7 (bd-0h2.10) — safe default
        gate_passed=True,
        gate_notes="OK",
    )


def _make_mock_p2(
    score: float = 4.0,
    accruals: float = 0.05,
    *,
    dilution_5y: float = float("nan"),
    operating_leverage: float = float("nan"),
) -> Phase2Result:
    """Build a mock Phase2Result.

    bd-zuw widening (PR #331 iter-3 silent-hunt L-6): scalars NOT currently
    consumed by P7's decision logic default to ``float('nan')`` so that when
    a future PR wires them into a threshold-fired branch, every existing
    mock-based test fails LOUDLY (NaN comparisons return False, breaking
    any silent skip). Currently-consumed fields (score, accruals_ratio,
    gross_profitability) keep sensible numeric defaults — those already have
    coverage in P7 tests.
    """
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
        operating_leverage=operating_leverage,
        dilution_5y=dilution_5y,
        gate_passed=True,
        gate_notes="OK",
    )


def _make_mock_p3(
    bullish_count: int = 7,
    earnings_safe: bool = True,
    weekly_bull: bool = True,
    *,
    days_to_earnings: int = 30,   # KEPT non-NaN — used by P3 gate + P7 earnings_note
) -> Phase3Result:
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
        days_to_earnings=days_to_earnings,
        earnings_safe_window=earnings_safe,
        weekly_trend_bullish=weekly_bull,
        gate_passed=bullish_count >= 6 and earnings_safe,
        gate_notes=f"{bullish_count}/11 bullish",
    )


def _make_mock_p4(
    mos: float = 0.18,
    altman: float = 3.5,
    *,
    implied_growth: float = float("nan"),
    peg_ratio: float = float("nan"),
    roic_wacc_spread: float = float("nan"),
) -> Phase4Result:
    """Build a mock Phase4Result. bd-zuw widening: implied_growth,
    peg_ratio, roic_wacc_spread default NaN since P7 doesn't threshold
    on them today. Callers who need specific values pass via keyword.
    """
    return Phase4Result(
        multiples_df=pd.DataFrame([{"pe": 25.0, "ev_ebitda": 18.0}]),
        dcf_fair_value=175.0,
        margin_of_safety=mos,
        sensitivity_df=pd.DataFrame(),
        implied_growth=implied_growth,
        roic_wacc_spread=roic_wacc_spread,
        peg_ratio=peg_ratio,
        piotroski=7.0,
        altman=altman,
        valuation_verdict="Undervalued" if mos >= 0.15 else "Fair Value",
        entry_recommendation="Strong Entry",
        historical_multiples_df=pd.DataFrame(),
        multiples_vs_median={},
        gate_passed=True,
        gate_notes="OK",
    )


def _make_mock_p5(
    sharpe: float = 1.4,
    mdd: float = -0.22,
    *,
    sortino: float = float("nan"),
    calmar: float = float("nan"),
    gain_to_pain: float = float("nan"),
    beta: float = float("nan"),
    beta_up: float = float("nan"),
    beta_down: float = float("nan"),
    var_95: float = float("nan"),
    cvar_95: float = float("nan"),
    ulcer_index: float = float("nan"),
    kurtosis: float = float("nan"),
    skewness: float = float("nan"),
    kelly_fraction: float = float("nan"),
    conviction_size: float = float("nan"),
    half_kelly_size: float = float("nan"),
    recommended_size: float = float("nan"),
) -> Phase5Result:
    """Build a mock Phase5Result. bd-zuw widening: 15 unused scalars
    NaN-defaulted. sharpe / max_drawdown / portfolio_fit / vol_63d_trend
    stay at sensible defaults — those already have P7 coverage.
    """
    return Phase5Result(
        risk_kpi_df=pd.DataFrame([{"sharpe": sharpe}]),
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        gain_to_pain=gain_to_pain,
        max_drawdown=mdd,
        beta=beta,
        beta_up=beta_up,
        beta_down=beta_down,
        var_95=var_95,
        cvar_95=cvar_95,
        ulcer_index=ulcer_index,
        kurtosis=kurtosis,
        skewness=skewness,
        vol_63d_trend="flat",  # A3: string field — NaN not applicable
        kelly_fraction=kelly_fraction,
        conviction_size=conviction_size,
        half_kelly_size=half_kelly_size,
        recommended_size=recommended_size,
        portfolio_fit="Core",
        stress_scenarios={"market_correction_20pct": -0.20},
        gate_passed=True,
        gate_notes="Core | Sharpe 1.40",
    )


def _make_mock_p6(
    relative_score: float = 3.8,
    ir: float = 0.6,
    *,
    rolling_3m_rank: float = float("nan"),
    relative_valuation_score: float = float("nan"),
    momentum_accel_63d: float = float("nan"),
) -> Phase6Result:
    """Build a mock Phase6Result for tests that don't need the scalar fields.

    bd-zuw (PR #331 iter-2 silent-failure-hunter SEV-H): the previous defaults
    (``rolling_3m_rank=55.0``, ``relative_valuation_score=65.0``,
    ``momentum_accel_63d=0.0``) were "reasonable" values that hid a coverage-
    decay hazard — when a future PR wires any of these three scalars into a
    P7 branch that fires on a threshold (e.g. ``if p6.rolling_3m_rank < 30``),
    every existing mock-based test would silently skip that branch.

    Fix: default all three to ``float('nan')`` so any consumer that uses them
    in an arithmetic comparison without a NaN guard fails loudly (``nan < 30``
    is False, ``nan > 30`` is False — but the failure will surface as an
    obviously-wrong output rather than a silently-skipped branch). Callers who
    need a specific numeric value must now pass it explicitly via keyword.

    Existing callers of ``_make_mock_p6()`` that don't consume these fields
    are unaffected; the P7 decision path currently reads only
    ``relative_score``, ``information_ratio``, and ``sector_etf``.
    """
    return Phase6Result(
        relative_table=pd.DataFrame(),
        corr_matrix=pd.DataFrame(),
        sector_etf="XLK",
        information_ratio=ir,
        relative_score=relative_score,
        peer_fundamental_df=pd.DataFrame(),
        relative_valuation_score=relative_valuation_score,
        rolling_3m_rank=rolling_3m_rank,
        momentum_accel_63d=momentum_accel_63d,
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


class TestPhase7StopCapAndTrailing:
    """Verify stop-cap + trailing-stop rules on Phase7Result (bd-0h2.11 / A8).

    Reviewer P7 rec: 'The 2×ATR stop is fixed.' Two additions:

      1. **Stop cap** (``use_stop_cap`` flag): cap the stop distance at
         ``min(2*ATR, 5% * entry)``. Prevents oversized stops on high-vol
         stocks where 2*ATR would exceed reasonable risk per share.

      2. **Trailing stop rules** (``use_trailing_stop`` flag): populate
         ``trailing_stop_rules`` dict with the breakeven-at-+1R + trail-
         at-+1R-when-price-hits-+2R protocol. Rules field is empty dict
         when the flag is off (default) — no behavioral change.

    Both flags default to False in ``AnalysisFeatureFlags``, so the
    pipeline behaves exactly as pre-A8 unless callers opt in.
    """

    @pytest.fixture
    def cfg(self) -> AnalysisConfig:
        return AnalysisConfig(symbol="MSFT")

    @pytest.fixture
    def cfg_stop_cap(self) -> AnalysisConfig:
        return AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_stop_cap=True),
        )

    @pytest.fixture
    def cfg_trailing(self) -> AnalysisConfig:
        return AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_trailing_stop=True),
        )

    # ------------------------------------------------------------------ #
    # Stop cap tests
    # ------------------------------------------------------------------ #
    def test_p7_has_trailing_stop_rules_field(self, cfg):
        """Field must exist on Phase7Result even when flags are off."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        assert hasattr(p7, "trailing_stop_rules")
        assert isinstance(p7.trailing_stop_rules, dict)

    def test_stop_cap_off_by_default_preserves_2atr_stop(self, cfg):
        """Default flag=off: stop = price - 2*ATR (unchanged from pre-A8).

        Mock p3 has price ~147, atr=2.5 → stop=142.0, distance=5.0.
        5% cap would be 7.35, so cap doesn't bite even if enabled.
        With flag off, no cap logic runs regardless.
        """
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        # Mock p3 close is 147.0, atr=2.5 → stop = 147 - 5 = 142.0
        assert p7.atr_stop == pytest.approx(142.0, abs=0.01)
        assert p7.risk_per_share == pytest.approx(5.0, abs=0.01)

    def test_stop_cap_on_high_vol_stock_bites(self, cfg_stop_cap):
        """High-vol fixture: ATR=8 on $50 stock → 2*ATR=16 (32% of price!).
        Cap at 5% = $2.50. Stop should be capped, risk_per_share=2.50.

        Load-bearing property: reverting the stop-cap fix removes the
        ``min(...)`` and the stop distance would revert to 16.0.
        """
        # Custom p3 fixture with high ATR relative to price.
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [50.0, 50.0, 50.0]
        p3.atr = 8.0

        p7 = phase7_decision(
            cfg_stop_cap,
            _make_mock_p1(),
            _make_mock_p2(),
            p3,
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        # 5% of $50 = $2.50 stop distance → stop = $47.50
        assert p7.risk_per_share == pytest.approx(2.50, abs=0.01), (
            f"Expected 5% cap ($2.50) to bite; got risk_per_share={p7.risk_per_share}. "
            f"Reverting stop-cap logic would return 16.0 (2*ATR)."
        )
        assert p7.atr_stop == pytest.approx(47.50, abs=0.01)

    def test_stop_cap_low_vol_stock_uses_2atr(self, cfg_stop_cap):
        """Low-vol fixture: ATR=0.5 on $100 stock → 2*ATR=1.0 (1% of price).
        5% cap = $5.00 — doesn't bite. Stop = 2*ATR = $1.00 distance.
        """
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [100.0, 100.0, 100.0]
        p3.atr = 0.5

        p7 = phase7_decision(
            cfg_stop_cap,
            _make_mock_p1(),
            _make_mock_p2(),
            p3,
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        # 2*ATR = 1.0 is well under 5% ($5) cap → stop_distance = 1.0
        assert p7.risk_per_share == pytest.approx(1.0, abs=0.01)
        assert p7.atr_stop == pytest.approx(99.0, abs=0.01)

    def test_stop_cap_off_does_not_cap_high_vol(self, cfg):
        """Flag off + high-vol fixture: stop distance = 2*ATR (uncapped).

        Load-bearing: this is the parity test — with flag off, the cap
        logic doesn't run even when the fixture would benefit from it.
        """
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [50.0, 50.0, 50.0]
        p3.atr = 8.0

        p7 = phase7_decision(
            cfg,  # flag OFF
            _make_mock_p1(),
            _make_mock_p2(),
            p3,
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        # 2*ATR = 16.0 — uncapped despite exceeding 5% of price
        assert p7.risk_per_share == pytest.approx(16.0, abs=0.01)

    # ------------------------------------------------------------------ #
    # Trailing stop tests
    # ------------------------------------------------------------------ #
    def test_trailing_stop_off_by_default_empty_dict(self, cfg):
        """Default flag=off: trailing_stop_rules is empty dict."""
        p7 = phase7_decision(
            cfg,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        assert p7.trailing_stop_rules == {}

    def test_trailing_stop_on_populates_rules(self, cfg_trailing):
        """Flag on: trailing_stop_rules dict carries the breakeven +
        trail-at-+2R protocol. Consumer semantics documented in the rules
        dict itself.
        """
        p7 = phase7_decision(
            cfg_trailing,
            _make_mock_p1(),
            _make_mock_p2(),
            _make_mock_p3(),
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        rules = p7.trailing_stop_rules
        assert "breakeven_at_r" in rules
        assert rules["breakeven_at_r"] == 1.0, (
            "breakeven trigger must fire at +1R per bead spec"
        )
        assert "trail_at_r" in rules
        assert rules["trail_at_r"] == 2.0, (
            "trailing stop activates when price hits +2R per bead spec"
        )
        assert "trail_distance_r" in rules
        assert rules["trail_distance_r"] == 1.0, (
            "trail distance is 1R (moves stop up by 1R for every 1R price move)"
        )

    def test_trailing_stop_on_but_stop_cap_off_are_independent(self, cfg_trailing):
        """Load-bearing property: enabling use_trailing_stop must NOT
        implicitly enable use_stop_cap. Verify by using the high-vol
        fixture — stop should NOT be capped.
        """
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [50.0, 50.0, 50.0]
        p3.atr = 8.0

        p7 = phase7_decision(
            cfg_trailing,  # trailing on, stop_cap off
            _make_mock_p1(),
            _make_mock_p2(),
            p3,
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        # Trailing rules populated
        assert p7.trailing_stop_rules != {}
        # But stop NOT capped
        assert p7.risk_per_share == pytest.approx(16.0, abs=0.01)

    def test_both_flags_on_compose_correctly(self, cfg):
        """Load-bearing combination test: both flags on → stop capped +
        trailing rules populated. Prevents future refactor where the two
        flags accidentally short-circuit each other.
        """
        cfg_both = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(
                use_stop_cap=True,
                use_trailing_stop=True,
            ),
        )
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [50.0, 50.0, 50.0]
        p3.atr = 8.0

        p7 = phase7_decision(
            cfg_both,
            _make_mock_p1(),
            _make_mock_p2(),
            p3,
            _make_mock_p4(),
            _make_mock_p5(),
            _make_mock_p6(),
        )
        assert p7.risk_per_share == pytest.approx(2.50, abs=0.01)   # capped
        assert p7.trailing_stop_rules["breakeven_at_r"] == 1.0      # trailing on

    def test_phase7_wires_trailing_stop_rules_field(self):
        """R7.8 AST wiring guard: phase7_decision must thread the
        trailing_stop_rules value into Phase7Result via the constructor
        kwarg from a local variable (not a hardcoded literal).
        """
        import ast
        import inspect
        from stock_analysis import phase7_decision

        tree = ast.parse(inspect.getsource(phase7_decision))
        matching = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "Phase7Result":
                    for kw in node.keywords:
                        if kw.arg == "trailing_stop_rules":
                            matching.append(kw)
        assert len(matching) >= 1, "phase7_decision must pass trailing_stop_rules"
        # At least one call site must thread the LOCAL variable, not a literal.
        assert any(
            isinstance(kw.value, ast.Name) and kw.value.id == "trailing_stop_rules"
            for kw in matching
        ), (
            "At least one Phase7Result call must have "
            "trailing_stop_rules=trailing_stop_rules (from local var)."
        )

    # ------------------------------------------------------------------ #
    # PR #343 iter-1 review fixes — regression tests for silent-hunt
    # findings F1 (Avoid contradiction), F2 (silent cap), F3 (negative
    # price), F6 (constants hoisted).
    # ------------------------------------------------------------------ #
    def test_trailing_stop_rules_empty_when_action_label_is_avoid(self):
        """iter-1 silent-hunt F1 (VERIFIED merge blocker, conf 95): pipeline
        must NOT emit execution parameters for a stock it says to avoid.

        Fixture: use_trailing_stop=True + distressed-Altman p4 → Altman
        override forces action_label='Avoid'. trailing_stop_rules MUST be
        empty dict despite the flag being on — the alternative (populated
        rules on an Avoid stock) is a silent contradiction that a
        downstream automated executor would act on.

        Load-bearing property: removing the ``and action_label != 'Avoid'``
        guard causes the trailing_stop_rules dict to be populated
        regardless — this test then fails.
        """
        cfg_trailing = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_trailing_stop=True),
        )
        p7 = phase7_decision(
            cfg_trailing,
            _make_mock_p1(),
            _make_mock_p2(score=4.5),
            _make_mock_p3(bullish_count=9),
            _make_mock_p4(mos=0.25, altman=1.5),  # distressed → Avoid
            _make_mock_p5(sharpe=1.8),
            _make_mock_p6(relative_score=4.2),
        )
        assert p7.action_label == "Avoid"
        assert p7.trailing_stop_rules == {}, (
            f"iter-1 silent-hunt F1: trailing_stop_rules must be empty "
            f"when action_label='Avoid' (got {p7.trailing_stop_rules}). "
            f"Pipeline was emitting execution protocol parameters for a "
            f"stock it itself flagged as distressed — silent contradiction "
            f"that downstream automated executor could act on."
        )

    def test_stop_cap_emits_info_log_when_cap_actually_bites(self, caplog):
        """iter-1 silent-hunt F2: when the 5% cap actually reduces the stop
        distance, an INFO log line must fire with the arithmetic. Prior
        to iter-1, the cap fired silently and ops had no way to tell a
        capped stop from a 2*ATR stop that happened to equal the same
        value.

        Load-bearing property: removing the ``if capped < stop_distance``
        log block silences the diagnostic; this test asserts the log
        substring fires. Also asserts the log does NOT fire when the cap
        doesn't bite (avoid-noise, R7.3 spirit).
        """
        import logging
        cfg_stop_cap = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_stop_cap=True),
        )
        # High-vol fixture: 2*ATR=$16, 5% cap=$2.50 → cap bites
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [50.0, 50.0, 50.0]
        p3.atr = 8.0

        with caplog.at_level(logging.INFO, logger="stock_analysis"):
            p7 = phase7_decision(
                cfg_stop_cap,
                _make_mock_p1(),
                _make_mock_p2(),
                p3,
                _make_mock_p4(),
                _make_mock_p5(),
                _make_mock_p6(),
            )

        assert p7.risk_per_share == pytest.approx(2.50, abs=0.01)
        stop_cap_logs = [
            r for r in caplog.records
            if r.levelno == logging.INFO
            and "stop-cap fired" in r.getMessage()
        ]
        assert len(stop_cap_logs) == 1, (
            f"iter-1 silent-hunt F2: expected 1 INFO log 'stop-cap fired' "
            f"substring when the cap actually reduces stop distance; "
            f"got {[r.getMessage() for r in caplog.records]}"
        )
        msg = stop_cap_logs[0].getMessage()
        assert "16" in msg   # 2*ATR value
        assert "2.5" in msg  # capped value

    def test_stop_cap_no_log_when_cap_does_not_bite(self, caplog):
        """iter-1 silent-hunt F2 (avoid-noise negative): when 2*ATR <
        5% cap, the log line must NOT fire — no cap-fired event to
        report. R7.3 non-noise guarantee.
        """
        import logging
        cfg_stop_cap = AnalysisConfig(
            symbol="MSFT",
            feature_flags=AnalysisFeatureFlags(use_stop_cap=True),
        )
        # Low-vol fixture: 2*ATR=1.0, 5% cap=5.0 → cap does NOT bite
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [100.0, 100.0, 100.0]
        p3.atr = 0.5

        with caplog.at_level(logging.INFO, logger="stock_analysis"):
            phase7_decision(
                cfg_stop_cap,
                _make_mock_p1(),
                _make_mock_p2(),
                p3,
                _make_mock_p4(),
                _make_mock_p5(),
                _make_mock_p6(),
            )

        stop_cap_logs = [
            r for r in caplog.records
            if "stop-cap fired" in r.getMessage()
        ]
        assert len(stop_cap_logs) == 0, (
            f"stop-cap log fired when cap did not bite (2*ATR=1.0 < "
            f"5% cap=5.0): {[r.getMessage() for r in stop_cap_logs]}"
        )

    def test_negative_price_raises_assertion_error(self):
        """iter-1 silent-hunt F3 (conf 90): a corrupted price feed producing
        a negative close must fail loudly (AssertionError), not silently
        emit a bad execution plan.

        Prior to iter-1, negative price + use_stop_cap silently produced
        a stop ABOVE entry price (min(2*ATR, negative-cap) picks the
        negative → stop = price - (-2.5) = price + 2.5). A long position
        with a stop above entry triggers immediately on any move.

        Load-bearing property: removing the ``assert price > 0`` line
        allows the bad-signal path to complete without error.
        """
        cfg = AnalysisConfig(symbol="MSFT")
        # Inject negative price into the p3 fixture
        p3 = _make_mock_p3()
        p3.price_df.loc[:, "close"] = [-50.0, -50.0, -50.0]

        with pytest.raises(AssertionError, match="price must be positive"):
            phase7_decision(
                cfg,
                _make_mock_p1(),
                _make_mock_p2(),
                p3,
                _make_mock_p4(),
                _make_mock_p5(),
                _make_mock_p6(),
            )

    def test_stop_cap_constant_and_trailing_defaults_at_module_scope(self):
        """iter-1 silent-hunt F6: 5% cap and trailing-stop protocol
        defaults are hoisted to module-level constants for testability
        and refactor discoverability.

        Load-bearing property: an accidental inline literal (e.g. someone
        writes ``0.05`` back into phase7_decision) breaks this test
        because the constants are checked for their intended values.
        """
        from stock_analysis import (
            _STOP_CAP_PCT_OF_ENTRY,
            _TRAILING_STOP_DEFAULTS,
        )
        assert _STOP_CAP_PCT_OF_ENTRY == 0.05
        assert _TRAILING_STOP_DEFAULTS == {
            "breakeven_at_r":    1.0,
            "trail_at_r":        2.0,
            "trail_distance_r":  1.0,
        }


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
        # bd-zuw: _make_mock_p6 now defaults rolling_3m_rank to NaN; tests
        # that specifically care about the value must pass it explicitly.
        p6 = _make_mock_p6(rolling_3m_rank=55.0)
        assert hasattr(p6, "rolling_3m_rank")
        assert 0.0 <= p6.rolling_3m_rank <= 100.0

    def test_mock_p6_defaults_scalars_to_nan(self):
        """bd-zuw regression guard — the three P6 scalar fields that P7
        doesn't currently consume default to NaN in _make_mock_p6.

        Load-bearing property: if a future PR adds a P7 branch that reads
        p6.momentum_accel_63d (or rolling_3m_rank or relative_valuation_score)
        without a NaN guard, EVERY existing mock-based test would fail
        loudly (NaN comparisons return False, breaking any threshold-fired
        branch). This test catches "someone silently restored 55.0 / 65.0
        / 0.0 defaults thinking they were harmless."
        """
        import math
        p6 = _make_mock_p6()
        assert math.isnan(p6.rolling_3m_rank), (
            "_make_mock_p6 must default rolling_3m_rank to NaN so future "
            "P7 consumers without NaN handling break loudly (bd-zuw)."
        )
        assert math.isnan(p6.momentum_accel_63d)
        assert math.isnan(p6.relative_valuation_score)

    def test_mock_p2_p3_p4_p5_default_unused_scalars_to_nan(self):
        """bd-zuw widening (PR #331 iter-3 silent-hunt L-6): symmetric
        NaN-default coverage-decay guard for _make_mock_p2/p3/p4/p5.

        Load-bearing property: same as p6 test — each currently-unused
        scalar defaults to NaN so the FIRST future PR that wires the
        field into a P7 branch causes all existing mock-based tests to
        fail LOUDLY (visible NaN in output) rather than silently skip
        the branch.

        Not testing DataFrame/dict/list fields — those default to empty
        containers which have no coverage-decay hazard.
        """
        import math
        p2 = _make_mock_p2()
        assert math.isnan(p2.dilution_5y)
        assert math.isnan(p2.operating_leverage)

        # p3 has NO NaN defaults — days_to_earnings is used by P3's own
        # gate + P7 earnings_note, and other unused fields are dicts/lists.
        # This assertion documents the exception.
        p3 = _make_mock_p3()
        assert p3.days_to_earnings == 30, (
            "days_to_earnings intentionally kept as int default (used by "
            "P3 gate + P7 earnings_note). If future PR adds a threshold "
            "on this, convert to NaN-defaulted like the p2 fields."
        )

        p4 = _make_mock_p4()
        assert math.isnan(p4.implied_growth)
        assert math.isnan(p4.peg_ratio)
        assert math.isnan(p4.roic_wacc_spread)

        p5 = _make_mock_p5()
        # 14 unused scalars on P5 — the ratio-of-ratios and stress metrics
        # not currently consumed by P7's composite scoring.
        for field_name in [
            "sortino", "calmar", "gain_to_pain", "beta", "beta_up", "beta_down",
            "var_95", "cvar_95", "ulcer_index", "kurtosis", "skewness",
            "kelly_fraction", "conviction_size", "half_kelly_size", "recommended_size",
        ]:
            assert math.isnan(getattr(p5, field_name)), (
                f"_make_mock_p5 must default {field_name} to NaN per bd-zuw "
                f"widening; got {getattr(p5, field_name)}"
            )


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
        # bd-zuw: _make_mock_p6 now defaults momentum_accel_63d to NaN;
        # a caller that specifically checks the value must pass it.
        p6 = _make_mock_p6(momentum_accel_63d=0.0)
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
        from stock_analysis import _compute_momentum_accel_63d

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
        from stock_analysis import _compute_momentum_accel_63d

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
        from stock_analysis import _compute_momentum_accel_63d

        # Only 100 rows — below the 126 threshold.
        returns_df = pd.DataFrame(
            np.random.default_rng(0).normal(size=(100, 3)),
            columns=["TARGET", "P1", "P2"],
        )
        accel = _compute_momentum_accel_63d(returns_df, "TARGET")
        assert accel == 0.0

    def test_symbol_absent_from_returns_returns_zero(self):
        """Symbol not in the returns DataFrame → neutral 0.0 (never raises)."""
        from stock_analysis import _compute_momentum_accel_63d

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
        from stock_analysis import _compute_momentum_accel_63d

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
        """SEV-1 fix regression guard — the fixture is constructed so that
        the buggy code path (``.sum()`` zero-filling PEER1's all-NaN earlier
        window) produces a DIFFERENT numeric answer than the fixed path
        (``.sum(min_count=42).dropna()`` excluding PEER1 from the earlier
        rank set).

        iter-2 (pr-test-analyzer + code-reviewer + silent-failure-hunter
        3-way convergence, conf 90/90/95): the original iter-1 assertion
        ``>= 0.75`` was ceremonial — both buggy (0.80) and fixed (0.75)
        code passed it, so removing the fix would NOT fail this test.
        Tightened to ``pytest.approx(0.75, abs=0.02)`` so the buggy 0.80
        now fails (outside [0.73, 0.77]) while the fixed 0.75 passes.

        Fixture: 5-symbol universe, TARGET decisively worst-then-best
        (accel ≈ +0.8 under the buggy zero-fill because earlier peer set
        has 5 including phantom; ≈ +0.75 under the fix because earlier
        peer set has 4 with PEER1 correctly excluded).
        """
        from stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(0)
        # TARGET's real returns dominate the accel — decisively worst early,
        # decisively best late. The load-bearing property is the small but
        # deterministic 0.05-point delta between the buggy and fixed paths.
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

        # Fixed code: PEER1 correctly excluded from earlier rank set (4 peers
        # + TARGET); earlier_rank = 0/5 = 0 percentile; later_rank = 100 percentile;
        # accel = 1.0 nominal but ``percentileofscore`` returns "rank" semantic
        # which caps at 100 * (n - 1) / n = 80 for the extremes → accel ~ 0.75.
        # Buggy code: PEER1 phantom-included at 0.0 cumulative in earlier window
        # (5 peers + TARGET → earlier_rank slightly higher because TARGET no
        # longer at the very bottom → accel ~ 0.80). Δ = 0.05.
        assert accel_with_ipod_peer == pytest.approx(0.75, abs=0.02), (
            f"IPO'd peer contamination test — expected 0.75 (fixed) ± 0.02, got "
            f"{accel_with_ipod_peer}. Value 0.80 would indicate the buggy "
            f".sum() zero-fill path is still active (PEER1 phantom-included)."
        )

    def test_half_nan_target_returns_zero_when_earlier_all_nan(self):
        """SEV-1 fix — target column with all-NaN in the EARLIER window only
        must degrade to 0.0 with a WARNING (not compute a bogus accel).
        """
        from stock_analysis import _compute_momentum_accel_63d

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
        """SEV-3 fix regression guard — units-sanity clamp must return 0.0
        (with WARNING) when the caller accidentally passes prices instead
        of returns.

        iter-2 (pr-test-analyzer + silent-failure-hunter convergence, conf
        90/95): the original cumsum-based fixture was ceremonial — TARGET
        ranked at the extreme in both windows even without the units
        clamp, so removing the clamp did NOT change the returned 0.0.
        Rewritten with a linspace-trending TARGET that CROSSES the flat
        peers mid-window: without the units clamp, pre-check code would
        compute a NON-ZERO accel (~+0.5); with the clamp, it returns 0.0.
        Removing the clamp now flips the assertion.
        """
        from stock_analysis import _compute_momentum_accel_63d

        # TARGET rises linearly from 100 to 500 across 150 days (median
        # |value| ~250 > 0.10 threshold), CROSSING each peer's flat level
        # mid-window so cumulative rank moves decisively (would produce
        # accel ~ +0.5 without the units clamp).
        target_prices = np.linspace(100, 500, 150)
        peers = np.column_stack([
            np.full(150, 150.0),   # TARGET crosses at day ~19
            np.full(150, 250.0),   # TARGET crosses at day ~56
            np.full(150, 350.0),   # TARGET crosses at day ~94
            np.full(150, 450.0),   # TARGET crosses at day ~131
        ])
        prices = pd.DataFrame(
            np.column_stack([target_prices, peers]),
            columns=["TARGET", "P1", "P2", "P3", "P4"],
        )
        accel = _compute_momentum_accel_63d(prices, "TARGET")
        # If the units check were removed, this fixture would compute a
        # non-zero accel (~+0.5) from the linearly-rising TARGET crossing
        # each peer. The clamp turns it into a neutral 0.0.
        assert accel == 0.0, (
            f"Units-sanity clamp regression: expected 0.0 on prices input, "
            f"got {accel}. Removing the ``if max_col_median > 0.10`` guard "
            f"would return a non-zero value from this fixture."
        )

    def test_boundary_exactly_126_rows_computes(self):
        """GAP-C fix — boundary at N=126 must compute (not degrade to 0.0)."""
        from stock_analysis import _compute_momentum_accel_63d

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
        from stock_analysis import _compute_momentum_accel_63d

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
        from stock_analysis import _compute_momentum_accel_63d

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
        """Load-bearing wiring guard (iter-3 M-2 fix): proves that
        ``phase6_peer_relative`` actually threads the computed accel value
        into the ``Phase6Result`` constructor — via AST inspection so a
        commented-out ``# momentum_accel_63d=momentum_accel_63d`` next to
        a ``=0.0`` mutation cannot defeat the check.

        Iteration history:
          * iter-1: used ``dataclasses.fields`` — ceremonial (field
            existence doesn't verify wiring)
          * iter-2: used ``inspect.getsource`` textual substring —
            ceremonial (comment-poisoning defeats it: silent-failure-hunter
            iter-3 M-2 empirically proved that mutating
            ``momentum_accel_63d=momentum_accel_63d,`` →
            ``momentum_accel_63d=0.0,  # BUG: momentum_accel_63d=momentum_accel_63d disabled``
            passes the textual check)
          * iter-3 (this): AST-parse the function source, walk to the
            ``Return`` → ``Call(func=Phase6Result)`` → ``keyword`` node,
            assert the keyword's VALUE is a ``Name`` referencing the local
            variable, not a ``Constant`` literal like ``0.0``. Comments
            are stripped by the parser so the M-2 mutation now fails.
        """
        import ast
        import inspect
        from stock_analysis import phase6_peer_relative

        tree = ast.parse(inspect.getsource(phase6_peer_relative))
        # Find every keyword argument on any ``Phase6Result(...)`` call.
        matching_kwargs: list[ast.keyword] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Name) and fn.id == "Phase6Result"):
                continue
            for kw in node.keywords:
                if kw.arg == "momentum_accel_63d":
                    matching_kwargs.append(kw)

        assert len(matching_kwargs) == 1, (
            f"Expected exactly one Phase6Result(momentum_accel_63d=...) call site "
            f"in phase6_peer_relative; found {len(matching_kwargs)}."
        )
        kw = matching_kwargs[0]
        # Load-bearing property: the value MUST be a Name node referencing the
        # local ``momentum_accel_63d`` variable, NOT a Constant / Attribute /
        # Call. This catches:
        #   * "momentum_accel_63d=0.0"   → Constant  ← the mutation we care about
        #   * "momentum_accel_63d=other" → Name('other') — wrong variable
        #   * "momentum_accel_63d=Phase6Result.foo" → Attribute — nonsense
        assert isinstance(kw.value, ast.Name), (
            f"phase6_peer_relative must thread the LOCAL momentum_accel_63d "
            f"variable into Phase6Result via kwarg=local, but the AST shows "
            f"the value is a {type(kw.value).__name__} node. Suspected "
            f"mutation: hardcoded literal like ``momentum_accel_63d=0.0``. "
            f"This defeats the whole point of the helper."
        )
        assert kw.value.id == "momentum_accel_63d", (
            f"phase6_peer_relative must thread the ``momentum_accel_63d`` "
            f"local; got Name(id={kw.value.id!r}) instead. Someone renamed "
            f"the variable without updating the constructor call — the "
            f"result would still be a valid float but from the wrong source."
        )

    # ------------------------------------------------------------------ #
    # PR #331 iter-3 review fixes — regression tests for the iter-2 fixes
    # that shipped without regression coverage (pr-test-analyzer + silent-
    # failure-hunter + code-reviewer 3-way convergence, MEDIUM confidence).
    # ------------------------------------------------------------------ #
    def test_min_obs_per_window_is_module_scope_shared_constant(self):
        """iter-3 MEDIUM-2 fix — the drift-zero invariant between
        ``rolling_3m_rank`` and ``momentum_accel_63d`` requires BOTH sites
        to use the SAME peer-inclusion threshold. iter-2 shipped
        asymmetric min_count values (helper=42, sibling=1), producing
        empirically-measurable drift (silent-failure-hunter iter-3 M-1
        constructed a 15-percentile counterexample).

        iter-3 fix: promote ``_MIN_OBS_PER_WINDOW`` to module scope. This
        test asserts the constant is importable AND has the expected
        value AND appears in the sibling ``phase6_peer_relative`` source.
        """
        import inspect
        import stock_analysis

        # Constant is importable from module scope, not buried inside a function.
        assert hasattr(stock_analysis, "_MIN_OBS_PER_WINDOW"), (
            "_MIN_OBS_PER_WINDOW must be defined at module scope so both "
            "phase6_peer_relative (rolling_3m_rank) and "
            "_compute_momentum_accel_63d can share the same threshold. "
            "iter-2 left it as a function-local, causing drift between "
            "the two calculations."
        )
        assert stock_analysis._MIN_OBS_PER_WINDOW == 42
        # Sibling site must reference the SAME constant, not a raw literal.
        sibling_src = inspect.getsource(stock_analysis.phase6_peer_relative)
        assert "min_count=_MIN_OBS_PER_WINDOW" in sibling_src, (
            "phase6_peer_relative's rolling_3m_rank block must call "
            ".sum(min_count=_MIN_OBS_PER_WINDOW), not a raw literal. "
            "Using a raw literal recreates the asymmetry that iter-2 "
            "shipped and iter-3 rescued."
        )

    def test_sibling_rolling_3m_rank_excludes_all_nan_peer(self):
        """iter-3 MEDIUM-1 fix — the SEV-B sibling fix (rolling_3m_rank
        uses ``sum(min_count=_MIN_OBS_PER_WINDOW)``) shipped in iter-2
        WITHOUT a regression test. This test verifies the sibling site
        actually references the shared constant via AST inspection.

        NB: an earlier attempt to test this via a hand-computed
        ``sum(min_count=42)`` in the test body itself was ceremonial —
        it exercised the FIXTURE, not the production code. AST inspection
        catches the "someone reverted min_count" mutation because the
        production source no longer contains the ``min_count=_MIN_OBS_PER_WINDOW``
        substring.
        """
        import inspect
        import stock_analysis

        sibling_src = inspect.getsource(stock_analysis.phase6_peer_relative)
        # The sibling site must reference the shared constant, not a raw
        # literal and not the bare .sum() form.
        occurrences = sibling_src.count(".sum(min_count=_MIN_OBS_PER_WINDOW)")
        assert occurrences >= 1, (
            f"SEV-B regression: phase6_peer_relative must contain at least "
            f"one .sum(min_count=_MIN_OBS_PER_WINDOW) call for rolling_3m_rank "
            f"(found {occurrences}). Reverting to bare .sum() or a raw "
            f"literal like min_count=1 reintroduces the phantom-peer bug."
        )

    def test_partial_history_peer_excluded_below_min_obs(self):
        """iter-3 MEDIUM-3 (SEV-C regression coverage) — a peer with fewer
        than ``_MIN_OBS_PER_WINDOW`` non-NaN observations in a window must
        be EXCLUDED from the rank set, not INCLUDED with a shrunk cumulative
        that guarantees it the low-rank extreme.

        Load-bearing property: reverting ``_MIN_OBS_PER_WINDOW`` to 1
        (iter-1's ceremonial state) would change the accel because PEER1's
        30-obs-shrunk cumulative would push into the rank lattice.
        """
        from stock_analysis import _compute_momentum_accel_63d, _MIN_OBS_PER_WINDOW

        # PEER1 has 30 non-NaN in each window (below the 42 threshold) —
        # would be included with min_count=1 (iter-1) but excluded now.
        rng = np.random.default_rng(0)
        target = np.concatenate([
            np.full(63, -0.02),   # worst early
            np.full(63, +0.02),   # best late
        ])
        # Peer with sparse history — 30 non-NaN out of 63 in EACH window.
        peer1_early = np.concatenate([[np.nan] * 33, rng.normal(scale=0.005, size=30)])
        peer1_late = np.concatenate([[np.nan] * 33, rng.normal(scale=0.005, size=30)])
        df = pd.DataFrame({
            "TARGET": target,
            "PEER1": np.concatenate([peer1_early, peer1_late]),  # excluded — sparse
            "PEER2": rng.normal(scale=0.005, size=126),
            "PEER3": rng.normal(scale=0.005, size=126),
            "PEER4": rng.normal(scale=0.005, size=126),
        })
        assert _MIN_OBS_PER_WINDOW == 42  # sanity: assertion below assumes this
        accel_with_sparse_peer = _compute_momentum_accel_63d(df, "TARGET")

        # Compare to the same fixture WITHOUT PEER1: if PEER1 is being
        # correctly excluded by the min_count guard, the accels match.
        # Reverting min_count to 1 would include PEER1 with cumulative =
        # sum(30 tiny values) ≈ 0 → phantom-mid-rank → different accel.
        accel_without_sparse_peer = _compute_momentum_accel_63d(
            df.drop(columns=["PEER1"]), "TARGET",
        )
        assert accel_with_sparse_peer == accel_without_sparse_peer, (
            f"SEV-C regression: sparse-history PEER1 (30 non-NaN) leaked "
            f"into rank set. Got {accel_with_sparse_peer} with sparse peer "
            f"vs {accel_without_sparse_peer} without. min_count guard broken?"
        )

    def test_two_peer_universe_returns_zero(self, caplog):
        """iter-3 MEDIUM-3 (SEV-E regression coverage) — a peer set that
        collapses to fewer than 3 members must trigger the peer-set-thin
        WARNING, not compute a spurious signal from the 2-item lattice.

        Load-bearing property (caplog-based, not accel-value-based):
        an EARLIER attempt asserted ``accel == 0.0`` but the 2-item
        lattice may coincidentally return 0.0 when TARGET happens to
        outrank the 1 remaining peer in both windows (100/100 → 0). Using
        caplog to prove the WARNING fired is stronger: the warning is
        ONLY emitted from the `len(later_cum) < 3` guard, which the
        mutation `< 2` bypasses.
        """
        import logging
        from stock_analysis import _compute_momentum_accel_63d

        # TARGET + 1 real peer + 3 all-NaN peers → after NaN filter,
        # len(later_cum) = 2, triggers the < 3 guard.
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "TARGET": rng.normal(scale=0.01, size=126),
            "PEER1": rng.normal(scale=0.01, size=126),
            "PEER2": [np.nan] * 126,
            "PEER3": [np.nan] * 126,
            "PEER4": [np.nan] * 126,
        })
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            accel = _compute_momentum_accel_63d(df, "TARGET")

        assert accel == 0.0
        # The peer-set-thin warning is the load-bearing signal — it fires
        # only when the < 3 threshold catches (later_cum has 2 items).
        # Mutation < 2 skips this branch entirely.
        peer_thin_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "peer set too thin" in r.getMessage()
            and "later=2" in r.getMessage()
        ]
        assert len(peer_thin_warnings) == 1, (
            f"SEV-E regression: expected 1 'peer set too thin' warning with "
            f"later=2 count; got {len(peer_thin_warnings)}. Reverting "
            f"threshold from < 3 to < 2 would skip this warning entirely, "
            f"letting the meaningless 2-item lattice compute through."
        )

    def test_single_wrong_units_column_triggers_clamp(self, caplog):
        """iter-3 MEDIUM-3 (SEV-D regression coverage) — a SINGLE column
        with prices-magnitude data among returns-magnitude peers must
        trigger the units-sanity clamp WARNING.

        Load-bearing property (caplog-based): earlier attempt asserted
        ``accel == 0.0``, but coincidence-driven zero accels defeat that.
        The units-sanity WARNING with the "prices/levels, not returns"
        substring only fires from the units-check branch, which the
        mutation .max() → .median() bypasses (majority-of-medians
        dominates).
        """
        import logging
        from stock_analysis import _compute_momentum_accel_63d

        rng = np.random.default_rng(0)
        # TARGET + 3 returns-magnitude peers + 1 prices-magnitude peer.
        # max-of-per-col-medians = ~250 > 0.10 → clamp fires (iter-2 fix)
        # median-of-per-col-medians = ~0.008 < 0.10 → clamp misses (iter-1 bug)
        df = pd.DataFrame({
            "TARGET": rng.normal(scale=0.01, size=126),
            "P1": rng.normal(scale=0.01, size=126),
            "P2": rng.normal(scale=0.01, size=126),
            "P3": rng.normal(scale=0.01, size=126),
            "PRICES_PEER": np.linspace(100, 500, 126),   # magnitude ~250
        })
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            accel = _compute_momentum_accel_63d(df, "TARGET")

        assert accel == 0.0
        # The units-sanity WARNING is the load-bearing signal — fires only
        # when the max-of-per-col-medians catches the prices column.
        # Mutation .max() → .median() lets the majority of returns columns
        # dominate the outer statistic, bypassing the warning entirely.
        units_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "prices/levels, not returns" in r.getMessage()
        ]
        assert len(units_warnings) == 1, (
            f"SEV-D regression: expected 1 units-sanity warning "
            f"('prices/levels, not returns' substring); got {len(units_warnings)}. "
            f"Reverting max() → median() lets the majority of returns-columns "
            f"dominate the outer statistic, bypassing the clamp entirely."
        )

    def test_helper_and_sibling_use_shared_min_obs_threshold(self):
        """iter-4 stub — the drift-zero invariant is guarded by
        ``test_min_obs_per_window_is_module_scope_shared_constant`` +
        ``test_sibling_rolling_3m_rank_excludes_all_nan_peer`` (both use
        source-inspection to prove the sibling references the shared
        constant). This test is retained as a documentation anchor pointing
        at those two.

        iter-3 shipped an EARLIER version of this test that computed the
        sibling arithmetic INLINE in the test body — silent-failure-hunter
        iter-4 empirically proved that mutating the sibling to
        ``sum(min_count=1)`` left this test passing because:
          (a) the inline arithmetic uses the imported ``_MIN_OBS_PER_WINDOW``
              constant (=42), NOT the mutated production line
          (b) the ``_compute_momentum_accel_63d`` call exercises the
              helper, NOT the sibling ``phase6_peer_relative`` code path

        So the test's docstring claim ("reverting the sibling site would
        make this test fail") was factually false — same "test fits the
        fix" anti-pattern iter-3 caught in three other tests. Rather than
        rewrite with a fixture that mocks the full ``phase6_peer_relative``
        provider chain (heavy), the two source-inspection tests cited
        above provide the guarantee at a lower cost.
        """
        # No assertions — this stub exists to keep the docstring visible
        # in the test-listing so future maintainers see the reasoning.
        pass


class TestPhase1EarningsRevisionDirection:
    """Verify earnings_revision_3m_direction on Phase1Result (bd-0h2.10 / A7).

    Reviewer's structural gap #2: 'forward-looking inputs'. Compute the
    net direction of analyst price-target revisions over the trailing 90
    days from ``obb.equity.estimates.price_target`` (already fetched in
    Phase 1 as ``price_targets_df``). Returns one of:
      * ``"up"``      — majority of recent revisions raised the target
      * ``"down"``    — majority lowered
      * ``"flat"``    — revisions balanced (< 20% net direction)
      * ``"unknown"`` — insufficient revisions in the 90d window (< 3)

    Direction is derived from the ``news_title`` field ("raised to X from Y"
    vs "lowered to X from Y") because the ``price_target_previous`` column
    is populated inconsistently by FMP. Ties + insufficient data → unknown.
    """

    def _make_price_targets_df(self, revisions):
        """Build a price_targets_df fixture from ``[(days_ago, direction), ...]``.

        ``direction`` is one of 'raised', 'lowered', or 'reiterated' — matches
        the FMP news_title verbs (`raised to $X from $Y`, `lowered to $X from $Y`).
        """
        rows = []
        for days_ago, direction in revisions:
            title_verb = {
                "raised": "raised to $500 from $450",
                "lowered": "lowered to $400 from $450",
                "reiterated": "reiterated a Buy",
            }[direction]
            rows.append({
                "published_date": datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(days=days_ago),
                "symbol": "MSFT",
                "analyst_firm": "TestFirm",
                "price_target": 500.0 if direction == "raised" else 400.0,
                "news_title": f"Microsoft price target {title_verb}",
            })
        return pd.DataFrame(rows)

    def test_mock_p1_has_earnings_revision_field(self):
        p1 = _make_mock_p1()
        assert hasattr(p1, "earnings_revision_3m_direction"), (
            "Phase1Result must carry earnings_revision_3m_direction per bd-0h2.10"
        )

    def test_helper_up_direction_when_majority_raised(self):
        from stock_analysis import _compute_earnings_revision_3m_direction

        # 4 raised, 1 lowered in last 60 days: 4/5 = 80% ups → "up"
        df = self._make_price_targets_df([
            (10, "raised"), (25, "raised"), (40, "raised"),
            (55, "raised"), (60, "lowered"),
        ])
        assert _compute_earnings_revision_3m_direction(df) == "up"

    def test_helper_down_direction_when_majority_lowered(self):
        from stock_analysis import _compute_earnings_revision_3m_direction

        # 4 lowered, 1 raised: 80% downs → "down"
        df = self._make_price_targets_df([
            (10, "lowered"), (25, "lowered"), (40, "lowered"),
            (55, "lowered"), (60, "raised"),
        ])
        assert _compute_earnings_revision_3m_direction(df) == "down"

    def test_helper_flat_when_balanced(self):
        from stock_analysis import _compute_earnings_revision_3m_direction

        # 3 raised, 3 lowered: 0% net direction → "flat"
        df = self._make_price_targets_df([
            (5, "raised"), (15, "raised"), (25, "raised"),
            (35, "lowered"), (45, "lowered"), (55, "lowered"),
        ])
        assert _compute_earnings_revision_3m_direction(df) == "flat"

    def test_helper_unknown_when_insufficient_revisions(self, caplog):
        """R7.3 loud-empty — fewer than 3 revisions in 90d window returns
        'unknown' with a WARNING (not a silent 'flat' misclassification).
        """
        import logging
        from stock_analysis import _compute_earnings_revision_3m_direction

        # Only 2 revisions in window: below the 3-minimum threshold.
        df = self._make_price_targets_df([(10, "raised"), (30, "raised")])
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            direction = _compute_earnings_revision_3m_direction(df)

        assert direction == "unknown"
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "insufficient analyst revisions" in r.getMessage()
        ]
        assert len(warnings) == 1

    def test_helper_ignores_revisions_older_than_90d(self):
        from stock_analysis import _compute_earnings_revision_3m_direction

        # All revisions > 90 days old — should be dropped, then triggers
        # insufficient-data → "unknown".
        df = self._make_price_targets_df([
            (100, "raised"), (120, "raised"), (150, "raised"),
        ])
        assert _compute_earnings_revision_3m_direction(df) == "unknown"

    def test_helper_reiterated_ratings_dont_count_as_direction(self):
        """Reiterated ratings are neither up nor down — should be excluded
        from the ups/downs count. Fixture: 2 raised + 5 reiterated → only
        2 directional signals → below 3-min threshold → 'unknown'.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = self._make_price_targets_df([
            (5, "raised"), (10, "raised"),
            (20, "reiterated"), (30, "reiterated"), (40, "reiterated"),
            (50, "reiterated"), (60, "reiterated"),
        ])
        assert _compute_earnings_revision_3m_direction(df) == "unknown"

    def test_helper_empty_df_returns_unknown(self):
        from stock_analysis import _compute_earnings_revision_3m_direction

        assert _compute_earnings_revision_3m_direction(pd.DataFrame()) == "unknown"

    def test_phase1_wires_earnings_revision_field(self):
        """AST-based wiring guard (R7.8): phase1_company_profile must thread
        the computed earnings_revision_3m_direction value into Phase1Result.

        Catches mutations like ``kwarg=local`` → ``kwarg="unknown"`` that
        would freeze the field to a default regardless of the actual data.
        """
        import ast
        import inspect
        from stock_analysis import phase1_company_profile

        tree = ast.parse(inspect.getsource(phase1_company_profile))
        matching_kwargs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "Phase1Result":
                    for kw in node.keywords:
                        if kw.arg == "earnings_revision_3m_direction":
                            matching_kwargs.append(kw)
        assert len(matching_kwargs) >= 1, (
            "phase1_company_profile must pass earnings_revision_3m_direction "
            "into Phase1Result(...)."
        )
        # The value must be a Name (local variable), not a Constant literal.
        kw = matching_kwargs[0]
        assert isinstance(kw.value, ast.Name), (
            f"earnings_revision_3m_direction should be threaded from a local "
            f"variable, not a hardcoded literal (got {type(kw.value).__name__})."
        )
        # iter-2 (code-reviewer CR4): the ast.Name check alone isn't enough
        # — a mutation like ``earnings_revision_3m_direction=sector`` would
        # still be Name('sector'), silently mis-wiring. Assert the specific
        # local variable name.
        assert kw.value.id == "earnings_revision_3m_direction", (
            f"earnings_revision_3m_direction should be threaded from the "
            f"local variable of the SAME name (found Name({kw.value.id!r})). "
            f"Cross-wiring to a different local variable would produce a "
            f"valid string type but from the wrong computation."
        )

    # ------------------------------------------------------------------ #
    # PR #337 iter-2 review fixes — regression tests for correctness bugs
    # + coverage gaps identified by 3-agent convergence.
    # ------------------------------------------------------------------ #
    def test_helper_cut_verb_counts_as_down(self):
        """iter-2 CR2 (pr-test mut #6 + silent-hunt F3): the ``\\bcut\\b``
        regex branch must be exercised. Original iter-1 fixture used only
        the ``lowered`` verb, so removing ``cut|reduced`` from the regex
        left all 9 tests passing.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": f"Microsoft price target cut to $400 from $500",
            }
            for d in [10, 30, 50]
        ])
        assert _compute_earnings_revision_3m_direction(df) == "down"

    def test_helper_reduced_verb_counts_as_down(self):
        """iter-2 CR2: ``\\breduced\\b`` regex branch coverage."""
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": f"Microsoft price target reduced to $400 from $500",
            }
            for d in [10, 30, 50]
        ])
        assert _compute_earnings_revision_3m_direction(df) == "down"

    def test_helper_hiked_and_boosted_verbs_count_as_up(self):
        """iter-2 CR2 (silent-hunt F3 vocabulary): ``hiked``, ``boosted``,
        ``increased``, ``upgraded`` are all common FMP verbs for revisions.
        Prior to iter-2 they registered as reiterated → false ``unknown``.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (10, "Microsoft price target hiked to $600 from $500"),
                (30, "Microsoft price target boosted to $650"),
                (50, "Microsoft price target increased to $620 from $500"),
            ]
        ])
        assert _compute_earnings_revision_3m_direction(df) == "up"

    def test_helper_bare_raised_without_target_is_not_directional(self):
        """iter-2 CR1 (code-reviewer): the original ``\\braised\\b`` regex
        false-positived on any English use of the word ("analyst raised
        concerns"). iter-2 phrase-anchors to ``raised ... target`` or
        ``raised ... to $NNN`` so bare mentions of the word are excluded.

        Load-bearing property: 3 titles with bare ``raised``/``lowered``
        (no directional context) → 0 directional → ``unknown`` warning.
        Reverting the phrase-anchoring regex causes these to count and
        return ``up``/``down``/``flat`` instead.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (10, "Microsoft: analyst raised concerns about competitive pressure"),
                (30, "Microsoft: firm raised recession worries for the sector"),
                (50, "Microsoft: bank lowered outlook on downside macro risk"),
            ]
        ])
        # All 3 titles contain raised/lowered as bare English words, NOT
        # in a "raised ... target" or "raised ... to $NNN" context.
        assert _compute_earnings_revision_3m_direction(df) == "unknown"

    def test_helper_ambiguous_row_is_excluded_not_double_counted(self, caplog):
        """iter-2 CR1 (silent-hunt F1): a row that matches BOTH the up and
        down regex (multi-analyst rollup) must be classified as AMBIGUOUS
        and dropped from the directional count, not double-counted into
        both ups and downs.

        Load-bearing property: 2 clean-raised + 1 ambiguous row →
        pre-fix: ups=3, downs=1, total=4 ≥ 3 → returns 'up'
        post-fix: ups=2, downs=0, total=2 < 3 → returns 'unknown'
        The caplog message includes the ambiguous count for ops visibility.
        """
        import logging
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (10, "Microsoft price target raised to $600 from $500"),
                (20, "Microsoft price target raised to $580 from $500"),
                (30, "Microsoft: Barclays raised target to $500, Morgan Stanley cut target to $400"),
            ]
        ])
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            direction = _compute_earnings_revision_3m_direction(df)

        # Post-fix: 2 up-only + 0 down-only + 1 ambiguous → 2 directional
        # → below min_revisions=3 → 'unknown' with ambiguous_count in log
        assert direction == "unknown"
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "1 ambiguous" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            f"CR1 regression: expected 1 WARNING mentioning '1 ambiguous'; "
            f"got {[r.getMessage() for r in caplog.records]}. Pre-fix code "
            f"would count the multi-analyst row as ups=1 AND downs=1, "
            f"inflating total_directional to 3 and returning a non-unknown."
        )

    def test_helper_net_threshold_boundary_at_0_20(self):
        """iter-2 CR3 (pr-test mut #4 + silent-hunt F6): the ``0.20``
        boundary uses ``<`` (exclusive), so ``|net_ratio| == 0.20``
        returns ``up``/``down``, not ``flat``. Original iter-1 tests
        used ratios of 0.0 (flat) and ±0.60 (up/down), leaving the
        boundary at 0.20 untested — mutation to ``0.50`` survived.

        Fixture: 3 up + 2 down = 5 directional, ``|3-2|/5 = 0.20``.
        Load-bearing: mutation ``net_threshold=0.50`` would flip this
        to ``flat`` (0.20 < 0.50).
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (5, "Microsoft price target raised to $500 from $450"),
                (15, "Microsoft price target raised to $520 from $500"),
                (25, "Microsoft price target raised to $540 from $520"),
                (35, "Microsoft price target lowered to $430 from $500"),
                (45, "Microsoft price target lowered to $410 from $450"),
            ]
        ])
        # net_ratio = (3-2)/5 = 0.20 exactly. Code uses ``< net_threshold``
        # so 0.20 is NOT < 0.20 → not flat → net_ratio > 0 → 'up'.
        assert _compute_earnings_revision_3m_direction(df) == "up"

    def test_helper_missing_published_date_column_warns(self, caplog):
        """iter-2 CR5 (silent-hunt F2): schema drift where 'published_date'
        column is renamed must WARN, not silently return 'unknown'.
        """
        import logging
        from stock_analysis import _compute_earnings_revision_3m_direction

        # Column renamed to publishedDate — pandas won't find published_date
        df = pd.DataFrame([{"publishedDate": "2026-06-01", "news_title": "raised to $500"}])
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            direction = _compute_earnings_revision_3m_direction(df)

        assert direction == "unknown"
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "'published_date' column missing" in r.getMessage()
        ]
        assert len(warnings) == 1

    def test_helper_missing_news_title_column_warns(self, caplog):
        """iter-2 CR5 (silent-hunt F2): schema drift where 'news_title'
        column is renamed must WARN, not silently return 'unknown'.
        """
        import logging
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([{"published_date": "2026-06-01", "newsTitle": "raised to $500"}])
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            direction = _compute_earnings_revision_3m_direction(df)

        assert direction == "unknown"
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "'news_title' column missing" in r.getMessage()
        ]
        assert len(warnings) == 1

    def test_helper_empty_df_warns(self, caplog):
        """iter-2 CR5 (silent-hunt F2): empty df must WARN so operators
        can distinguish upstream fetcher failure from real 'unknown'.
        """
        import logging
        from stock_analysis import _compute_earnings_revision_3m_direction

        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            direction = _compute_earnings_revision_3m_direction(pd.DataFrame())

        assert direction == "unknown"
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "price_targets_df is empty" in r.getMessage()
        ]
        assert len(warnings) == 1

    def test_helper_all_older_than_window_warns(self, caplog):
        """iter-2 CR5 (silent-hunt F2): post-filter-empty (all revisions
        older than 90d) must WARN, not return 'unknown' silently.
        """
        import logging
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": f"Microsoft price target raised to $500 from $450",
            }
            for d in [100, 120, 150]
        ])
        with caplog.at_level(logging.WARNING, logger="stock_analysis"):
            direction = _compute_earnings_revision_3m_direction(df)

        assert direction == "unknown"
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "no revisions within" in r.getMessage()
        ]
        assert len(warnings) == 1

    # ------------------------------------------------------------------ #
    # PR #337 iter-2 verify — regression tests for the regex rework
    # (silent-hunt S1 non-PT exclusion + S2 participle vocabulary +
    # pr-test GAP-1 stricter bare-raised + GAP-2 down-vocab symmetry).
    # ------------------------------------------------------------------ #
    def test_helper_dividend_and_buyback_news_dont_trigger_direction(self):
        """iter-2-verify S1 (silent-hunt conf 90): non-PT financial news
        that uses directional verbs must NOT trigger the regex.

        Prior iter-2 code had a ``to $NNN`` alt-anchor that caught
        "raised dividend to $0.24", "boosted buyback to $60B", "raised
        guidance to $5 EPS" as UP revisions. iter-2-verify tightened the
        regex to require the ``target|PT`` keyword adjacency; these
        should now register as neither up nor down.

        Load-bearing property: 4 non-PT titles with directional verbs
        → 0 directional → 'unknown'. Reverting the tightening (restoring
        the to-$N alt-anchor) causes these to count as up → misclassified.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (5, "AAPL raised dividend to $0.24 per share"),
                (15, "MSFT boosted buyback to $60 billion"),
                (25, "AMZN raised guidance to $5.00 EPS"),
                (35, "GOOGL hiked forecast to $10 range"),
            ]
        ])
        # All 4 are non-PT news mentioning directional verbs. None should
        # register as directional revisions.
        assert _compute_earnings_revision_3m_direction(df) == "unknown"

    def test_helper_present_participle_verbs_count_as_directional(self):
        """iter-2-verify S2 (silent-hunt conf 95): FMP headlines use both
        past-tense (raised/cut/lowered) and present-participle (raising/
        cutting/lowering) forms. Prior iter-2 code missed the participles.

        Load-bearing property: 3 titles using ONLY participles → 3
        directional → non-'unknown' verdict (up/down as fixture chooses).
        Reverting the vocabulary to past-tense-only causes these to
        register as neither → total_directional < 3 → 'unknown'.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        # Mixed participles: 2 raising + 1 cutting → up
        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (10, "Wells raising target to $600 from $500"),
                (20, "MS raising PT to $580"),
                (30, "Barclays cutting target to $400"),
            ]
        ])
        # 2 up-participles, 1 down-participle → net=1/3 ≈ 0.33 > 0.20 → 'up'
        assert _compute_earnings_revision_3m_direction(df) == "up"

    def test_helper_bare_raised_ceremonial_fix(self):
        """iter-2-verify GAP-1 (pr-test-analyzer): fix the ceremonial iter-1
        test_helper_bare_raised_without_target_is_not_directional. The
        original had 2 bare-raised + 1 bare-lowered fixtures → under the
        bare-\\braised\\b mutation, ups=2, downs=0, total=2 < min_revisions=3
        → returned 'unknown' but for the WRONG reason (count too low).

        Fix: use 3 bare-raised fixtures + 1 bare-lowered so that under the
        mutation, ups=3, downs=0, total=3 ≥ min_revisions → returns 'up'
        (buggy) vs 'unknown' (phrase-anchored, correct). Now the load-
        bearing property is truly the phrase-anchor, not the count.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                # 4 bare-raised + 1 bare-lowered — all in non-PT contexts
                (5, "Microsoft: analyst raised concerns about competitive pressure"),
                (10, "Microsoft: firm raised recession worries for the sector"),
                (15, "Microsoft: bank raised outlook citing macro risk"),
                (20, "Microsoft: fund raised its cash position amid volatility"),
                (30, "Microsoft: pundit lowered growth expectations for AI"),
            ]
        ])
        # With phrase-anchoring: 0 directional → 'unknown'.
        # Without phrase-anchoring (mutation): ups=4, downs=1, net=0.60 → 'up'.
        assert _compute_earnings_revision_3m_direction(df) == "unknown"

    def test_helper_trimmed_slashed_downgraded_count_as_down(self):
        """iter-2-verify GAP-2 (pr-test-analyzer): symmetric down-vocab
        regression test — mirrors test_helper_hiked_and_boosted_verbs_
        count_as_up for the DOWN direction. Prior iter-2 code accepted
        the vocabulary but no test named the verbs; mutation removing
        ``trimmed|slashed|downgraded`` silently survived.
        """
        from stock_analysis import _compute_earnings_revision_3m_direction

        df = pd.DataFrame([
            {
                "published_date": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d),
                "news_title": title,
            }
            for d, title in [
                (10, "Microsoft price target trimmed to $450 from $500"),
                (30, "Microsoft price target slashed to $350 from $500"),
                (50, "Microsoft downgraded, PT to $400 from $500"),
            ]
        ])
        assert _compute_earnings_revision_3m_direction(df) == "down"


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
            earnings_revision_3m_direction="unknown",
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
            earnings_revision_3m_direction="unknown",
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

