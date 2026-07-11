"""
stock_analysis.py
=================
Single-module implementation of the 7-phase single-stock investment analysis
pipeline documented in ``Analysis/docs/PHASED_ANALYSIS_MASTER_PLAN.md``.

Design principles
-----------------
* ``fmp_cached`` is the **only** provider used.  No ``fmp`` fallback.
* All derived calculations use pandas / numpy — no FinanceToolkit dependency.
* Each phase function is pure: it accepts an ``AnalysisConfig`` (plus prior-phase
  results where needed) and returns a typed ``PhaseNResult`` dataclass.
* Private helpers are prefixed with ``_``.
* The module is importable without a live OpenBB session; functions will raise
  ``RuntimeError`` when ``obb`` is unavailable.

Usage
-----
    from openbb import obb
    obb.user.credentials.fmp_cached_api_key = "<your_fmp_api_key>"

    from stock_analysis import AnalysisConfig, run_full_analysis
    results = run_full_analysis(AnalysisConfig(symbol="MSFT"))

    # Or phase-by-phase:
    from stock_analysis import (
        AnalysisConfig,
        phase1_company_profile,
        phase2_fundamentals,
        phase3_technicals,
        phase4_valuation,
        phase5_risk,
        phase6_peer_relative,
        phase7_decision,
    )
    cfg = AnalysisConfig(symbol="MSFT")
    p1  = phase1_company_profile(cfg)
    p2  = phase2_fundamentals(cfg)
    p3  = phase3_technicals(cfg)
    p4  = phase4_valuation(cfg, p2, p3, p1=p1)
    p5  = phase5_risk(cfg)
    p6  = phase6_peer_relative(cfg, p1)
    p7  = phase7_decision(cfg, p1, p2, p3, p4, p5, p6)
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import kurtosis as _scipy_kurtosis, percentileofscore, skew as _scipy_skew

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _last_trading_day(reference: datetime.date | None = None) -> datetime.date:
    """Return the most recent completed trading day (Mon–Fri) before *reference*.

    If *reference* is ``None`` (the default), uses ``datetime.date.today()``.

    Rules:
    - Always rolls back at least one day so the *current* (potentially
      incomplete) trading day is never included.
    - Continues rolling back over weekends so that Monday's ``end_date`` is
      the previous Friday, not Saturday or Sunday.

    Examples
    --------
    - Called on a Tuesday  → Monday
    - Called on a Monday   → last Friday
    - Called on a Saturday → last Friday
    - Called on a Sunday   → last Friday
    """
    base = reference if reference is not None else datetime.date.today()
    # Step back one day first (never include today's partial session)
    candidate = base - datetime.timedelta(days=1)
    # Skip weekend days
    while candidate.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        candidate -= datetime.timedelta(days=1)
    return candidate


# ---------------------------------------------------------------------------
# Provider constant
# ---------------------------------------------------------------------------
PRIMARY_PROVIDER: str = "fmp_cached"

# ---------------------------------------------------------------------------
# Peer-relative window constants (bd 0h2.9, PR #331 iter-3 MEDIUM-2)
# ---------------------------------------------------------------------------
# Shared minimum observations-per-63d-window for peer inclusion in both
# ``rolling_3m_rank`` (phase6_peer_relative) and ``momentum_accel_63d``
# (_compute_momentum_accel_63d). Kept at module scope so both sites use the
# same threshold, preserving the "same peer universe" invariant the docstrings
# claim.  ``sum(min_count=_MIN_OBS_PER_WINDOW)`` drops a peer whose window is
# too sparse (e.g. mid-window IPO) rather than including it with a shrunk-
# to-tiny cumulative that would guarantee it the low-rank extreme.
_MIN_OBS_PER_WINDOW: int = 42  # 2/3 of a 63-day window

# ---------------------------------------------------------------------------
# Stop-cap constant (bd 0h2.11 / PR #343 iter-1 silent-hunt F6)
# ---------------------------------------------------------------------------
# Fraction-of-entry ceiling for stop distance when
# ``AnalysisFeatureFlags.use_stop_cap`` is True. Chosen so 2*ATR is capped
# roughly at the retail day-trader risk-of-ruin threshold — position
# sizing downstream uses risk_per_share as the divisor, so a stop
# distance > 5% of entry demands impossibly-small share counts. Changing
# this materially affects downstream sizing; a future refactor should
# have a specific numerical rationale.
_STOP_CAP_PCT_OF_ENTRY: float = 0.05

# ---------------------------------------------------------------------------
# Trailing-stop protocol defaults (bd 0h2.11 / A8)
# ---------------------------------------------------------------------------
# Protocol parameters emitted to Phase7Result.trailing_stop_rules when
# ``AnalysisFeatureFlags.use_trailing_stop`` is True. The Analysis
# pipeline emits these as documentation for the execution layer; it does
# not simulate trailing behavior itself. All values are in units of R
# (risk_per_share multiples), so they scale with the stock's own ATR.
_TRAILING_STOP_DEFAULTS: dict[str, float] = {
    "breakeven_at_r":    1.0,   # move stop to entry when price reaches +1R
    "trail_at_r":        2.0,   # activate trailing stop at +2R
    "trail_distance_r":  1.0,   # trail 1R behind price
}

# ---------------------------------------------------------------------------
# Regime-adjusted composite weights (bd 0h2.14 / B2)
# ---------------------------------------------------------------------------
# Reviewer P7 Q-1: the P7 composite scoring should adapt to the current
# market regime. In TRENDING_BULL, technical momentum is the higher-
# probability signal (correlations break, individual stock strength
# matters more) — bias weight toward the technicals block. In CRISIS,
# individual stock quality dominates less than the ability to weather
# a drawdown — bias toward risk_fit (Sharpe / MaxDD / drawdown history).
#
# RANGING and TRENDING_BEAR keep the default table — the reviewer's spec
# only distinguishes the two extreme regimes.
#
# INVARIANT: each regime's weight table MUST sum to 1.0. Otherwise the
# composite scale drifts and Avoid/Hold/Buy cutoffs become meaningless
# (see test_regime_weights_sum_to_one_bull / _crisis, R7.4 seam contract).
# Values shift the technicals ↔ risk_fit pair AND rebalance the remaining
# blocks proportionally to preserve the sum-to-1.0 invariant.
_DEFAULT_COMPOSITE_WEIGHTS: dict[str, float] = {
    "business_quality": 0.08,
    "fundamentals":     0.25,
    "technicals":       0.15,
    "valuation":        0.20,
    "risk_fit":         0.12,
    "peer_relative":    0.20,
}

# Bull: technicals up (0.15 → 0.30), risk_fit down (0.12 → 0.10). Net delta
# +0.13, redistributed by shrinking the four unchanged blocks proportionally
# (each takes -0.13 / 0.73 ≈ 17.8% haircut relative to their default).
_BULL_COMPOSITE_WEIGHTS: dict[str, float] = {
    "business_quality": 0.0657,
    "fundamentals":     0.2055,
    "technicals":       0.30,
    "valuation":        0.1644,
    "risk_fit":         0.10,
    "peer_relative":    0.1644,
}

# Crisis: risk_fit up (0.12 → 0.30), technicals down (0.15 → 0.10). Net delta
# +0.13, redistributed the same way.
_CRISIS_COMPOSITE_WEIGHTS: dict[str, float] = {
    "business_quality": 0.0657,
    "fundamentals":     0.2055,
    "technicals":       0.10,
    "valuation":        0.1644,
    "risk_fit":         0.30,
    "peer_relative":    0.1644,
}

# ---------------------------------------------------------------------------
# Regime tranche multipliers (bd 0h2.15 / B3)
# ---------------------------------------------------------------------------
# Reviewer P7 Q-1 continued: staged_entry.tranche_* should scale by regime.
# BULL / RANGING: full size (no scaling).
# BEAR: half size (uncertainty premium — the tape is against you).
# CRISIS: zero (never open a new position while correlations are at 1.0
# and every trade bleeds together — the pre-existing position management
# is what stops/targets are for).
# UNKNOWN: fall back to 1.0 (behave like the flag is off — the R7.3
# loud-empty path handles the WARNING at the caller layer, this table
# just needs a defined value so `[regime]` dict lookup doesn't KeyError).
#
# iter-1 code-reviewer + silent-hunter HIGH F1: TRULY LAZY. Previous
# version invoked _make_regime_tranche_multiplier() at module scope
# (line 214), defeating the "lazy import" docstring — any environment
# without openbb_regime installed broke `import stock_analysis` even
# with use_regime_input=False. Now: cache is populated on first call
# to _regime_tranche_multiplier(), preserving the flag-off default-
# reversibility guarantee.
_REGIME_TRANCHE_MULTIPLIER_CACHE: dict | None = None


def _regime_tranche_multiplier() -> dict:
    """Return the regime → tranche-multiplier lookup table.

    Lazy: only imports openbb_regime on first call, so environments
    without the regime extension can still ``import stock_analysis``
    as long as ``use_regime_input`` stays False.
    """
    global _REGIME_TRANCHE_MULTIPLIER_CACHE
    if _REGIME_TRANCHE_MULTIPLIER_CACHE is None:
        from openbb_regime import MarketRegime
        _REGIME_TRANCHE_MULTIPLIER_CACHE = {
            MarketRegime.TRENDING_BULL:  1.0,
            MarketRegime.RANGING:        1.0,
            MarketRegime.TRENDING_BEAR:  0.5,
            MarketRegime.CRISIS:         0.0,
            MarketRegime.UNKNOWN:        1.0,
        }
    return _REGIME_TRANCHE_MULTIPLIER_CACHE


def _regime_weights(regime) -> dict[str, float]:
    """Return the composite-weight table for a given regime.

    Parameters
    ----------
    regime : MarketRegime
        The current market regime.

    Returns
    -------
    dict[str, float]
        The 6-block weight table for that regime; always sums to 1.0.

    Raises
    ------
    TypeError
        If ``regime`` is not a :class:`MarketRegime` instance. iter-1
        silent-hunt F4 fix: reject garbage rather than silently return
        default (which would mask the caller's bug + then KeyError on
        the downstream tranche lookup). ``MarketRegime`` extends ``str``
        so ``regime="crisis"`` would silently equality-compare against
        no enum member (all values are UPPERCASE), fall through, and
        return default weights + KeyError on the tranche dict lookup.
        Rejecting non-enum types at the seam prevents both.
    """
    from openbb_regime import MarketRegime
    if not isinstance(regime, MarketRegime):
        raise TypeError(
            f"_regime_weights: expected MarketRegime instance, got "
            f"{type(regime).__name__} ({regime!r}). Use MarketRegime "
            f"lookup (e.g. MarketRegime('CRISIS') or MarketRegime.CRISIS) "
            f"to coerce external inputs — do not pass raw strings."
        )
    if regime == MarketRegime.TRENDING_BULL:
        return dict(_BULL_COMPOSITE_WEIGHTS)
    if regime == MarketRegime.CRISIS:
        return dict(_CRISIS_COMPOSITE_WEIGHTS)
    # RANGING, TRENDING_BEAR, UNKNOWN → default weights
    return dict(_DEFAULT_COMPOSITE_WEIGHTS)


# ---------------------------------------------------------------------------
# Feature flags (Phase A0 — bead OpenBBTechnical-0h2.1)
# ---------------------------------------------------------------------------
# Every flag defaults to ``False`` so the pipeline behaves exactly as it did
# before A0 shipped.  Downstream beads flip individual flags on to activate
# their new behavior; the default-off state is the reversibility guarantee
# that lets us roll back any single experiment without a code revert.
#
# Envvar convention: each flag maps 1:1 to ``ANALYSIS_<UPPER_ATTR>``.
# Truthy: "1", "true", "yes", "on" (case-insensitive).  Falsy: "0", "false",
# "no", "off", "" (empty).  Any other string raises ValueError — we never
# silently coerce garbage input.

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV = frozenset({"0", "false", "no", "off", ""})


def _parse_env_bool(envvar: str, raw: str) -> bool:
    """Parse an env-var string to bool with strict recognition.

    Raises ValueError if *raw* is not in the truthy/falsy vocabulary.  The
    *envvar* name is included in the error message for actionable diagnostics
    ("which flag did I typo?").
    """
    lowered = raw.strip().lower()
    if lowered in _TRUTHY_ENV:
        return True
    if lowered in _FALSY_ENV:
        return False
    raise ValueError(
        f"{envvar}={raw!r} is not a recognised boolean; "
        f"use one of {sorted(_TRUTHY_ENV)} or {sorted(_FALSY_ENV - {''})}."
    )


@dataclass
class AnalysisFeatureFlags:
    """Rollout flags for phase A-G behavior changes (per plan Q-4).

    Every flag defaults to ``False`` — old pipeline behavior is preserved
    on a default construction, so ``AnalysisConfig(symbol=...)`` alone
    causes no observable output change.

    Attributes
    ----------
    use_two_stage_dcf : bool
        Phase A4a — enable the 5Y-explicit → 8Y-taper → terminal DCF fade
        in place of the current single-stage Gordon Growth model.
    use_sector_wacc : bool
        Phase A4b — when ``ratios_df["wacc"]`` is NaN, fall back to a
        sector-mapped default (tech 9 %, healthcare 11 %, crypto-adj 15 %)
        instead of the current flat 9 % fallback.
    use_confluence_engine : bool
        Phase C2 — route the P3 11-condition binary count through the
        weighted continuous confluence engine at ``techtrade.engine.confluence``.
    use_regime_input : bool
        Phase B2 — feed ``MarketRegime`` (from the new shared regime extension)
        into the P7 composite weight adjustment table.
    use_trailing_stop : bool
        Phase A8 (part 2) — attach trailing-stop rules to the P7 execution
        plan output (move to break-even after 1R, 1.5× ATR trail after 2R).
    use_stop_cap : bool
        Phase A8 (part 1) — cap the initial stop at ``min(2 * ATR, 5 % * entry)``
        instead of the current unbounded ``entry − 2 * ATR``.
    use_peg_tightening : bool
        Phase A5 (post-review) — apply Peter Lynch's PEG tiebreaker to the
        ``valuation_verdict`` when DCF-MOS lands in the "Fair Value" band:
        PEG < 1.0 upgrades to "Undervalued", PEG > 2.0 downgrades to
        "Overvalued".  Because ``valuation_verdict`` feeds ``gate_passed``,
        this can flip a stock from gate-pass to gate-fail — hence gated
        behind a flag (see PR #304 review C1/I1 / bead OpenBBTechnical-0h2.35).
    use_extended_confluence_panel : bool
        Phase-Confluence-Expansion foundation (bd-7ct) — opt in to the
        extended techtrade confluence panel. Default False preserves the
        14-key / 7-vote classic panel byte-identically. When True, the
        techtrade engine builds an extended panel (currently a pass-through
        stub in bd-7ct; family PRs bd-luy/40v/z43/alj will populate it with
        best-of-class industry-standard indicators, each gated on measured
        out-of-sample forward IC from the bd-7ct.10 harness). See:
        docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md
        and docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md.

    Env-var overrides
    -----------------
    Each field is overridable via the matching ``ANALYSIS_<UPPER_ATTR>``
    environment variable, resolved by :meth:`from_env`.  Callers who want the
    behavior of ``AnalysisConfig`` to reflect the environment should pass
    ``feature_flags=AnalysisFeatureFlags.from_env()`` explicitly — the default
    factory returns an all-``False`` instance so pytest never picks up shell
    state accidentally.
    """

    use_two_stage_dcf: bool = False
    use_sector_wacc: bool = False
    use_confluence_engine: bool = False
    use_regime_input: bool = False
    use_trailing_stop: bool = False
    use_stop_cap: bool = False
    use_peg_tightening: bool = False
    use_extended_confluence_panel: bool = False

    @classmethod
    def from_env(cls) -> "AnalysisFeatureFlags":
        """Build an instance from ``ANALYSIS_*`` environment variables.

        Unset vars keep the field default (``False``).  Set vars must parse
        as bool via :func:`_parse_env_bool`; unrecognised values raise
        ``ValueError`` with the offending envvar name.

        Returns
        -------
        AnalysisFeatureFlags
        """
        kwargs: dict[str, bool] = {}
        for f in cls.__dataclass_fields__.values():
            envvar = "ANALYSIS_" + f.name.upper()
            if envvar in os.environ:
                kwargs[f.name] = _parse_env_bool(envvar, os.environ[envvar])
        return cls(**kwargs)

    def as_dict(self) -> dict[str, bool]:
        """Introspection helper — every flag as a plain dict.

        Delegates to :func:`dataclasses.asdict` so newly-added flags in phases
        B-G surface automatically without editing this method.  Used for
        dev-time logging (``logger.info("flags: %s", flags.as_dict())``) and
        for the P7 handoff artifact so a reader can reproduce a run.
        """
        return asdict(self)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class AnalysisConfig:
    """Central configuration object passed to every phase function.

    Parameters
    ----------
    symbol : str
        Upper-case ticker symbol, e.g. ``"MSFT"``.
    benchmark : str
        Market benchmark ticker for risk calculations, default ``"SPY"``.
    start_fundamentals : str
        ISO date string for the start of the fundamental data window (5Y back).
    start_technicals : str
        ISO date string for the start of the technical price data window (1Y back).
    end_date : str
        ISO date string for the analysis end date.  Defaults to the most recent
        completed trading day (yesterday, rolled back over weekends) so that a
        partial/incomplete current session is never included in either price
        history or fundamental data windows.
    provider : str
        OpenBB provider.  Must be ``"fmp_cached"`` — no other value is supported.
    risk_free_rate : float
        Annual risk-free rate used in Sharpe / Sortino / Jensen calculations.
    max_portfolio_allocation : float
        Maximum single-position size as fraction of portfolio (for Kelly sizing).
    feature_flags : AnalysisFeatureFlags
        Rollout switches for Phase A-G behavior changes (see
        :class:`AnalysisFeatureFlags`).  Defaults to all-``False`` so behavior
        matches pre-A0 exactly.  Pass ``AnalysisFeatureFlags.from_env()`` to
        pick up ``ANALYSIS_*`` env vars, or construct an explicit instance
        for programmatic overrides.
    """

    symbol: str
    benchmark: str = "SPY"
    start_fundamentals: str = field(
        default_factory=lambda: (
            datetime.date.today() - datetime.timedelta(days=365 * 6)
        ).isoformat()
    )
    start_technicals: str = field(
        default_factory=lambda: (
            datetime.date.today() - datetime.timedelta(days=365 + 90)
        ).isoformat()
    )
    end_date: str = field(
        default_factory=lambda: _last_trading_day().isoformat()
    )
    provider: str = PRIMARY_PROVIDER
    risk_free_rate: float = 0.02
    max_portfolio_allocation: float = 0.04  # 4 % hard cap
    enforce_gates: bool = False             # Stop pipeline on gate failure
    feature_flags: AnalysisFeatureFlags = field(default_factory=AnalysisFeatureFlags)

    def __post_init__(self) -> None:
        # CLAUDE.md's Analysis Module 'Provider rule' declares fmp_cached
        # as *enforced* — every phase function propagates cfg.provider
        # through to live obb.* calls, so a soft warning cannot actually
        # prevent a caller from burning uncached FMP quota or getting a
        # different-schema response. Raise instead of warn (bd-omi).
        if self.provider != PRIMARY_PROVIDER:
            raise ValueError(
                f"provider={self.provider!r} is not supported. "
                f"Analysis/stock_analysis.py requires provider={PRIMARY_PROVIDER!r} "
                f"(see CLAUDE.md 'Analysis Module → Provider rule')."
            )


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Phase1Result:
    """Outputs of Phase 1: Company Profile & Tradeability Screen.

    Named "tradeability" (not "business quality") because these fields answer
    'can a meaningful position actually be entered and exited?' — raw market
    cap alone overstates liquidity for stocks with heavy insider or founder
    ownership.  ``free_float_pct * market_cap`` yields the float-adjusted
    market cap, which is the more honest liquidity signal (bead
    OpenBBTechnical-0h2.3 / GH #300, per reviewer P1 recommendation).
    """

    profile_df: pd.DataFrame
    quote_df: pd.DataFrame
    metrics_df: pd.DataFrame
    peers: list[str]
    geo_df: pd.DataFrame
    insider_df: pd.DataFrame
    institutional_df: pd.DataFrame
    price_targets_df: pd.DataFrame
    sector: str
    industry: str
    market_cap: float
    free_float_pct: float | None
    """Fraction of shares publicly tradeable (0.0-1.0) from
    ``obb.equity.share_statistics``.  ``None`` if the provider returned no
    data.  Multiply by ``market_cap`` for float-adjusted market cap."""
    short_interest_pct: float | None
    """Fraction of the float sold short (0.0-1.0).  Currently always ``None``
    because ``fmp_cached`` does not expose short-interest data — follow-up
    bead will add a secondary provider (finra or similar) if we want to lift
    the single-provider constraint here."""
    earnings_revision_3m_direction: str
    """Net direction of analyst price-target revisions over the trailing 90d
    (bd-0h2.10 / A7, reviewer's structural gap #2 — forward-looking inputs).
    One of ``"up"`` / ``"down"`` / ``"flat"`` / ``"unknown"``. Computed from
    ``price_targets_df`` via :func:`_compute_earnings_revision_3m_direction`."""
    gate_passed: bool
    gate_notes: str


@dataclass
class Phase2Result:
    """Outputs of Phase 2: 5-Year Fundamental Analysis."""

    income_df: pd.DataFrame
    balance_df: pd.DataFrame
    cash_df: pd.DataFrame
    ratios_df: pd.DataFrame
    kpi_df: pd.DataFrame            # Summary KPI table (latest values)
    roe_decomp_df: pd.DataFrame     # DuPont decomposition
    score: float                    # Weighted 0-5 score
    accruals_ratio: float           # Sloan accruals ratio (latest)
    gross_profitability: float      # Novy-Marx ratio (latest)
    operating_leverage: float       # 5Y average operating leverage
    dilution_5y: float              # Net share change over 5Y
    gate_passed: bool
    gate_notes: str


@dataclass
class Phase3Result:
    """Outputs of Phase 3: Technical Analysis & Trade Timing."""

    price_df: pd.DataFrame          # OHLCV + all computed indicators
    signals: dict[str, bool]        # Boolean signal map (11 conditions)
    bullish_count: int              # Number of True signals (gate: >= 6)
    entry_quality: str              # "High Conviction" / "Standard" / "Cautious"
    fib_levels: dict[str, float]    # Fibonacci retracement levels
    atr: float                      # Latest ATR(14)
    days_to_earnings: int           # Trading days to next earnings
    earnings_safe_window: bool      # True if > 5 days away
    weekly_trend_bullish: bool      # Weekly chart regime check
    gate_passed: bool
    gate_notes: str
    #: bd-85w (2026-07-11): the techtrade extended panel snapshot at the last
    #: bar, populated when ``AnalysisFeatureFlags.use_extended_confluence_panel``
    #: is True. ``None`` when the flag is False (default) — preserves pre-bd-85w
    #: shape for every existing consumer. When populated it carries the
    #: ``IndicatorPanel`` returned by ``techtrade.build_indicator_panel(..., panel_config=PANEL_EXTENDED)``:
    #: last-bar-finite scalar values per family (trend / momentum / volatility /
    #: volume). Notebooks and R&D code can read it directly; downstream Analysis
    #: signal computation is UNCHANGED and still driven by the inline
    #: ``_compute_technicals`` pipeline. Option A of the bd-85w design.
    extended_panel: Any = None


@dataclass
class Phase4Result:
    """Outputs of Phase 4: Valuation & Fair Value Estimation."""

    multiples_df: pd.DataFrame      # Current multiples table
    dcf_fair_value: float
    margin_of_safety: float         # (dcf_fair_value - price) / dcf_fair_value
    sensitivity_df: pd.DataFrame    # 3x3 WACC x g_term grid
    implied_growth: float           # Reverse-DCF implied short-term growth
    roic_wacc_spread: float         # ROIC - WACC (latest)
    peg_ratio: float                # PE / (revenue CAGR × 100); NaN if growth <= 0
    """Peter Lynch's PEG.  Rule of thumb: < 1.0 cheap, > 2.0 expensive.
    Used as a tiebreaker to tighten the Fair Value verdict only; strong
    DCF signals (Undervalued/Overvalued) are not overwritten by PEG
    (bead OpenBBTechnical-0h2.8)."""
    piotroski: float
    altman: float
    valuation_verdict: str          # "Undervalued" / "Fair Value" / "Overvalued"
    entry_recommendation: str       # Combined valuation+technical verdict
    historical_multiples_df: pd.DataFrame  # 5Y annual multiples trend
    multiples_vs_median: dict[str, float]  # current / 5Y median - 1
    gate_passed: bool
    gate_notes: str


@dataclass
class Phase5Result:
    """Outputs of Phase 5: Risk Assessment & Portfolio Context."""

    risk_kpi_df: pd.DataFrame       # All risk KPIs in one table
    sharpe: float
    sortino: float
    calmar: float
    gain_to_pain: float
    max_drawdown: float
    beta: float
    beta_up: float
    beta_down: float
    var_95: float
    cvar_95: float
    ulcer_index: float
    kurtosis: float
    """Fisher (excess) kurtosis of daily returns.  0 = normal distribution;
    positive = fat tails (extreme moves more likely than a normal would
    predict).  Empirically ~3-8 for daily large-cap equity returns
    (bead OpenBBTechnical-0h2.4)."""
    skewness: float
    """Third-moment asymmetry of daily returns.  Negative = left tail
    longer/fatter (crashes worse than rallies); positive = right tail
    dominant.  Equity returns typically show mild negative skew."""
    vol_63d_trend: str              # "expanding" / "contracting" / "flat"
    """Direction of the trailing 63-day realized volatility vs. the prior
    63-day window (bead OpenBBTechnical-0h2.5, reviewer P5 rec).  Hysteresis
    of ±10 % keeps the label stable across small fluctuations."""
    kelly_fraction: float
    conviction_size: float          # Conviction-based position size (%)
    half_kelly_size: float          # Half-Kelly position size (%)
    recommended_size: float         # Lower of conviction vs half-Kelly
    portfolio_fit: str              # "Core" / "Satellite" / "Reject"
    stress_scenarios: dict[str, float]
    gate_passed: bool
    gate_notes: str


@dataclass
class Phase6Result:
    """Outputs of Phase 6: Market Segment, ETF Benchmark & Peer Relative Analysis."""

    relative_table: pd.DataFrame    # Annualised metrics for universe
    corr_matrix: pd.DataFrame
    sector_etf: str
    information_ratio: float
    relative_score: float           # 5-block score (0-5)
    peer_fundamental_df: pd.DataFrame
    relative_valuation_score: float  # 0-100 quality-value rank
    rolling_3m_rank: float          # Percentile rank of 63-day return vs peers
    momentum_accel_63d: float       # Δ percentile-rank vs 63d ago, /100 → [-1, +1]
    """Change in peer-percentile-rank over the trailing 63 trading days,
    normalised to ``[-1, +1]`` (bead OpenBBTechnical-0h2.9, reviewer P6 rec).

    Static ``rolling_3m_rank`` tells you *where* the symbol sits vs. peers
    right now; ``momentum_accel_63d`` tells you *how it got there* — climbing
    the peer ladder (positive) or falling off it (negative).  Computed as
    ``(rank_t - rank_{t-63}) / 100`` where each rank is the same
    :func:`scipy.stats.percentileofscore` calculation used for
    ``rolling_3m_rank`` (so drift between the two is zero by construction).
    Requires >= 126 daily-return rows; degrades to ``0.0`` (neutral) below
    that threshold or when the target symbol is absent from the peer
    returns frame.
    """
    gate_passed: bool
    gate_notes: str


@dataclass
class Phase7Result:
    """Outputs of Phase 7: Decision, Execution & Monitoring."""

    composite_score: float
    action_label: str               # "Strong Buy" / "Buy" / "Hold/Watch" / "Avoid"
    score_breakdown: dict[str, float]
    entry_quality: str
    atr_stop: float
    risk_per_share: float
    target_1r: float
    target_2r: float
    target_3r: float
    staged_entry: dict[str, float]  # Tranche sizes (% of target)
    time_stop_date: str             # Entry + 63 calendar days
    hard_override: str | None
    monitoring_triggers: dict[str, Any]
    handoff: dict[str, Any]
    trailing_stop_rules: dict[str, float] = field(default_factory=dict)
    """Trailing-stop protocol parameters (bd-0h2.11 / A8, reviewer P7 rec).

    Empty dict ``{}`` when ``AnalysisFeatureFlags.use_trailing_stop`` is
    False (default) — preserves pre-A8 behavior. When the flag is on,
    populated with:

      * ``breakeven_at_r`` — move stop to entry when price reaches +NR
        (default 1.0 — protect against giving back gains)
      * ``trail_at_r`` — activate trailing stop when price reaches +NR
        (default 2.0 — start locking in profits after 2R move)
      * ``trail_distance_r`` — trailing stop distance in R units
        (default 1.0 — move stop up by 1R for every 1R price move)

    These are protocol parameters for the execution layer to interpret;
    the Analysis pipeline does not simulate the trailing behavior itself.
    """

    regime: Any = None
    """MarketRegime input recorded on the result (bd-0h2.14 / B2).

    Defaults to ``MarketRegime.UNKNOWN`` in ``phase7_decision`` when no
    regime is supplied (via the ``__post_init__`` hook — the field
    default is ``None`` at the dataclass level to avoid importing
    ``openbb_regime`` at Analysis-module import time).

    When ``AnalysisFeatureFlags.use_regime_input`` is True, this field
    records the regime that was used to select the composite-weight
    table and staged_entry multiplier. Present for auditability and
    downstream logging — the actual behavior change lives in the
    composite score and staged_entry tranches.

    Typed as ``Any`` to keep the dataclass free of openbb_regime import
    cycles; the runtime value is always a ``MarketRegime`` enum member.
    """

    def __post_init__(self) -> None:
        """Coerce None → MarketRegime.UNKNOWN so downstream consumers
        can safely dict-lookup on ``result.regime``.

        iter-1 silent-hunt F5: also coerce any non-MarketRegime input
        (int, str, other enum) → UNKNOWN with a WARNING. Silent
        acceptance of typed garbage is worse than silent acceptance of
        None because downstream .regime lookups would fail unpredictably.
        """
        from openbb_regime import MarketRegime
        if self.regime is None:
            self.regime = MarketRegime.UNKNOWN
        elif not isinstance(self.regime, MarketRegime):
            logger.warning(
                "Phase7Result: regime field received non-MarketRegime "
                "value %r (type=%s); coercing to MarketRegime.UNKNOWN. "
                "Callers should pass a MarketRegime instance — see "
                "stock_analysis.phase7_decision docstring.",
                self.regime, type(self.regime).__name__,
            )
            self.regime = MarketRegime.UNKNOWN


# ---------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------


def _to_df(result: Any) -> pd.DataFrame:
    """Safely call ``.to_df()`` on an OpenBB result object.

    Returns an empty DataFrame on failure rather than raising.
    """
    try:
        df = result.to_df()
        if df is None or not isinstance(df, pd.DataFrame):
            return pd.DataFrame()
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("_to_df failed: %s", exc)
        return pd.DataFrame()


def _latest_col(df: pd.DataFrame, candidates: list[str], default: float = float("nan")) -> float:
    """Return the latest non-null value from the first matching column."""
    for col in candidates:
        if col in df.columns:
            series = df[col].dropna()
            if not series.empty:
                return float(series.iloc[-1])
    return default


def _cagr(series: pd.Series, years: int = 5) -> float:
    """Compute compound annual growth rate from a time-ordered series.

    Parameters
    ----------
    series : pd.Series
        Values in chronological order (oldest first).
    years : int
        Number of periods (assumed annual).

    Returns
    -------
    float
        CAGR as a decimal (0.12 = 12 %).  NaN on failure.
    """
    try:
        clean = series.dropna()
        if len(clean) < 2:
            return float("nan")
        start = clean.iloc[0]
        end = clean.iloc[-1]
        n = min(len(clean) - 1, years)
        if start <= 0 or end <= 0 or n <= 0:
            return float("nan")
        return float((end / start) ** (1 / n) - 1)
    except Exception:  # noqa: BLE001
        return float("nan")


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute ADX(period) using Wilder smoothing."""
    up_move = high.diff()
    dn_move = -low.diff()
    pos_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)

    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)

    alpha = 1 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    pdm_w = pd.Series(pos_dm, index=high.index).ewm(alpha=alpha, adjust=False).mean()
    ndm_w = pd.Series(neg_dm, index=high.index).ewm(alpha=alpha, adjust=False).mean()

    pdi = 100 * pdm_w / atr_w.replace(0, np.nan)
    ndi = 100 * ndm_w / atr_w.replace(0, np.nan)
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder smoothing."""
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs   = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _compute_vol_trend(
    returns: pd.Series,
    window: int = 63,
    threshold: float = 0.10,
) -> str:
    """Classify the direction of the rolling *window*-day realized volatility.

    Compares the mean of the most recent *window* days of rolling-vol
    against the prior *window* days.  Returns one of:

    * ``"expanding"``    — recent vol > prior vol by more than *threshold*
    * ``"contracting"``  — recent vol < prior vol by more than *threshold*
    * ``"flat"``         — change within ±*threshold*, or insufficient data

    The *threshold* provides hysteresis so tiny fluctuations don't flip the
    label between two consecutive analysis runs.  Defaults (63d window,
    10 % threshold) match the reviewer's P5 recommendation: "Recent
    volatility (3-6 months) may be very different from 15-month vol."

    Parameters
    ----------
    returns : pd.Series
        Daily returns series (typically ``price.pct_change().dropna()``).
    window : int, default 63
        Number of trading days per rolling-vol window.  63 ≈ 3 months.
    threshold : float, default 0.10
        Fractional change required to leave the "flat" band.

    Returns
    -------
    str
        One of ``"expanding"``, ``"contracting"``, ``"flat"``.  Never NaN
        or None — downstream code can rely on the closed set.
    """
    if returns is None or len(returns) < 2 * window:
        return "flat"

    rolling_vol = returns.rolling(window).std().dropna()
    if len(rolling_vol) < 2 * window:
        return "flat"

    recent_mean = float(rolling_vol.iloc[-window:].mean())
    prior_mean  = float(rolling_vol.iloc[-2 * window:-window].mean())

    if prior_mean <= 0 or not np.isfinite(prior_mean) or not np.isfinite(recent_mean):
        return "flat"

    change = (recent_mean - prior_mean) / prior_mean
    if change > threshold:
        return "expanding"
    if change < -threshold:
        return "contracting"
    return "flat"


def _compute_momentum_accel_63d(
    returns_df: pd.DataFrame,
    symbol: str,
) -> float:
    """Change in peer-percentile-rank over the trailing 63 trading days.

    Reviewer P6 recommendation (bead ``OpenBBTechnical-0h2.9``): a static
    ``rolling_3m_rank`` tells you *where* the symbol sits vs. peers today
    but says nothing about *trajectory*.  Two symbols may share
    ``rolling_3m_rank == 60`` but the one that climbed from 20 → 60 is a
    very different setup than the one that fell from 90 → 60.

    Computes the percentile rank of the earlier 63-day cumulative return
    (rows ``-126:-63``) and the later 63-day cumulative return (rows
    ``-63:``) — both against the peer universe of the same window — then
    returns ``(rank_t - rank_{t-63}) / 100``, a scalar in ``[-1.0, +1.0]``.

    Uses the same :func:`scipy.stats.percentileofscore` machinery as
    ``phase6_peer_relative``'s ``rolling_3m_rank`` calculation, so drift
    between the two values is zero by construction.

    Parameters
    ----------
    returns_df : pd.DataFrame
        Daily returns for the target symbol + peer columns.  Rows are
        chronologically ascending; columns are symbols.
    symbol : str
        Target symbol; must appear as a column in ``returns_df``.

    Returns
    -------
    float
        ``rank_delta / 100`` where each rank is a percentile in ``[0, 100]``,
        so the return is bounded in ``[-1.0, +1.0]``.  Returns ``0.0``
        (neutral) when insufficient history (< 126 rows) or when
        ``symbol`` is absent from ``returns_df`` — never raises.
    """
    if len(returns_df) < 126 or symbol not in returns_df.columns:
        return 0.0

    # Units sanity (bd 0h2.9 / PR #331 iter-1): median |daily return| > 10 %
    # almost always means the caller passed prices / levels instead of returns.
    # iter-2 (SEV-D): use max across per-column medians so a SINGLE column in
    # the wrong units triggers the clamp, not just the majority-of-columns case.
    recent_slice = returns_df.iloc[-126:]
    per_col_median = recent_slice.abs().median()
    max_col_median = float(per_col_median.max())  # NaN-safe: NaN cols excluded
    if not np.isnan(max_col_median) and max_col_median > 0.10:
        logger.warning(
            "_compute_momentum_accel_63d(%s): max column median |daily| = %.3f > 0.10 — "
            "at least one column looks like prices/levels, not returns; returning 0.0",
            symbol,
            max_col_median,
        )
        return 0.0

    # NaN handling (bd 0h2.9 / PR #331 iter-1 SEV-1 + iter-2 SEV-C + iter-3
    # MEDIUM-2): pd.DataFrame.sum() without min_count returns 0.0 for all-NaN
    # columns, NOT NaN — so a peer with no history in a window would phantom-
    # compete with cumulative=0.0. Bumped from min_count=1 to the module-level
    # _MIN_OBS_PER_WINDOW constant so peers with sparse data (e.g. mid-window
    # IPO with only a handful of bars) are EXCLUDED rather than included with
    # a systematically-shrunk cumulative. iter-3 promoted the constant to
    # module scope so the sibling rolling_3m_rank calculation uses the SAME
    # threshold — restoring the "shared peer universe" property the docstring
    # claims.
    later_cum = returns_df.iloc[-63:].sum(min_count=_MIN_OBS_PER_WINDOW).dropna()
    earlier_cum = returns_df.iloc[-126:-63].sum(min_count=_MIN_OBS_PER_WINDOW).dropna()

    if symbol not in later_cum.index or symbol not in earlier_cum.index:
        # R7.3 loud-empty: target column had insufficient observations in one
        # or both windows — cannot compute a rank; degrade to neutral loudly.
        logger.warning(
            "_compute_momentum_accel_63d(%s): target absent from cumulative "
            "returns after NaN filter (later=%s, earlier=%s) — likely <%d "
            "non-NaN observations in one window; returning neutral 0.0",
            symbol,
            symbol in later_cum.index,
            symbol in earlier_cum.index,
            _MIN_OBS_PER_WINDOW,
        )
        return 0.0
    # iter-2 (SEV-E) + iter-3 (LOW-1 comment fix): require >= 3 items in each
    # cumulative Series (target + at least 2 peers). ``percentileofscore`` on
    # 3 items gives a {0, 50, 100} lattice — coarse but at least admits
    # non-zero movement between windows. 2 items would only give {50, 100}
    # so accel would discretize to ±0.5, meaningless as a rank movement.
    if len(later_cum) < 3 or len(earlier_cum) < 3:
        logger.warning(
            "_compute_momentum_accel_63d(%s): peer set too thin after NaN "
            "filter (later=%d, earlier=%d, min=3) — percentile lattice too "
            "coarse for meaningful accel; returning neutral 0.0",
            symbol,
            len(later_cum),
            len(earlier_cum),
        )
        return 0.0

    later_rank = float(percentileofscore(later_cum.tolist(), later_cum[symbol]))
    earlier_rank = float(percentileofscore(earlier_cum.tolist(), earlier_cum[symbol]))
    return (later_rank - earlier_rank) / 100.0


# Regex patterns for analyst-revision news title parsing (bd-0h2.10 / A7).
# FMP price_target news_titles follow a family of patterns like:
#   "<Firm> price target raised to $<X> from $<Y>"
#   "<Firm> price target lowered/cut/reduced/trimmed/slashed to $<X> from $<Y>"
#   "<Firm> price target hiked/boosted/increased to $<X> from $<Y>"
# iter-2 (CR1 phrase-anchoring): require the verb to be adjacent to "target"
# or "price target" to avoid false positives like "raised concerns" /
# "raised recession worries" / "raised outlook on downside" which match a
# bare \braised\b but are NOT directional revisions.
# iter-2 (CR2 vocabulary): broadened patterns to cover the common FMP verbs
# beyond the original raised/lowered/cut/reduced set. Reiterated ratings
# ("Buy reiterated", "maintained at Overweight") stay excluded — they don't
# move the target.
_REVISION_UP_PATTERN = re.compile(
    # Verb + target within 60 chars, EITHER order (FMP titles are typically
    # "price target raised to $NNN" — target first, verb second — but some
    # headlines use "raised the price target to $NNN" — verb first).
    r"(?:"
    r"\b(?:raised|raising|hiked|hiking|boosted|boosting|increased|increasing|"
    r"upgraded|upgrading)\b[^.]{0,60}?\b(?:price\s+target|target|PT)\b"
    r"|"
    r"\b(?:price\s+target|target|PT)\b[^.]{0,60}?"
    r"\b(?:raised|raising|hiked|hiking|boosted|boosting|increased|increasing|"
    r"upgraded|upgrading)\b"
    r")",
    re.IGNORECASE,
)
_REVISION_DOWN_PATTERN = re.compile(
    r"(?:"
    r"\b(?:lowered|lowering|cut|cutting|reduced|reducing|trimmed|trimming|"
    r"slashed|slashing|downgraded|downgrading)\b[^.]{0,60}?"
    r"\b(?:price\s+target|target|PT)\b"
    r"|"
    r"\b(?:price\s+target|target|PT)\b[^.]{0,60}?"
    r"\b(?:lowered|lowering|cut|cutting|reduced|reducing|trimmed|trimming|"
    r"slashed|slashing|downgraded|downgrading)\b"
    r")",
    re.IGNORECASE,
)


def _compute_earnings_revision_3m_direction(
    price_targets_df: pd.DataFrame,
    *,
    window_days: int = 90,
    min_revisions: int = 3,
    net_threshold: float = 0.20,
) -> str:
    """Classify the net direction of analyst price-target revisions.

    Reviewer's structural gap #2 (bd-0h2.10 / A7): the pipeline lacks
    forward-looking inputs. Analyst revisions are the earliest signal of
    consensus estimate changes — a stock with a majority-up revision
    stream in the last 3 months has forward-looking momentum that pure-
    price data can't capture.

    Parameters
    ----------
    price_targets_df : pd.DataFrame
        Output of ``obb.equity.estimates.price_target(...).to_df()``, with
        columns ``published_date`` and ``news_title``. Both must be present;
        empty / malformed frames return ``"unknown"``.
    window_days : int, default 90
        Trailing-days window for the revision count. 90 ≈ 3 months.
    min_revisions : int, default 3
        Minimum directional (raised or lowered) revisions in the window
        for a non-``unknown`` verdict. Reiterated ratings are excluded.
    net_threshold : float, default 0.20
        Minimum ``|ups - downs| / (ups + downs)`` for a non-``flat``
        verdict. Boundary is *exclusive*: exactly ``0.20`` returns
        ``"up"``/``"down"``, not ``"flat"``.

    Returns
    -------
    str
        One of ``"up"``, ``"down"``, ``"flat"``, ``"unknown"``. Never raises.

    Notes
    -----
    Direction is binary — a stock with 10 raises averaging +$1 and 3 cuts
    averaging −$50 returns ``"up"`` despite negative net dollar impact
    (iter-1 silent-hunt F4). Magnitude-weighted direction is deferred to
    Phase D per the original bead scope. Consumers should treat this
    field as a categorical signal, not a magnitude.
    """
    # iter-2 (CR5 R7.3 loud-empty): each of the 5 degenerate paths now
    # emits a WARNING with the specific reason so an operator can
    # distinguish "no data" from "schema drift" from "insufficient signal".
    if price_targets_df is None or price_targets_df.empty:
        logger.warning(
            "_compute_earnings_revision_3m_direction: price_targets_df is "
            "%s — returning 'unknown' (upstream fetcher may have failed)",
            "None" if price_targets_df is None else "empty",
        )
        return "unknown"
    if "published_date" not in price_targets_df.columns:
        logger.warning(
            "_compute_earnings_revision_3m_direction: 'published_date' column "
            "missing from price_targets_df (schema drift?) — returning 'unknown'"
        )
        return "unknown"
    if "news_title" not in price_targets_df.columns:
        logger.warning(
            "_compute_earnings_revision_3m_direction: 'news_title' column "
            "missing from price_targets_df (schema drift?) — returning 'unknown'"
        )
        return "unknown"

    # Filter to the trailing window.
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=window_days)
    df = price_targets_df.copy()
    # Normalise any date/datetime → tz-aware datetime for comparison.
    n_before = len(df)
    df["_pub"] = pd.to_datetime(df["published_date"], utc=True, errors="coerce")
    df = df.dropna(subset=["_pub"])
    # iter-2 (F5): warn when a significant fraction of dates were coerced
    # to NaT — usually a schema/format-drift signal.
    dropped_nat = n_before - len(df)
    if dropped_nat > 0 and dropped_nat * 2 >= n_before:  # >= 50% dropped
        logger.warning(
            "_compute_earnings_revision_3m_direction: dropped %d/%d rows "
            "with unparseable published_date — check FMP schema",
            dropped_nat, n_before,
        )
    df = df[df["_pub"] >= cutoff]

    if df.empty:
        logger.warning(
            "_compute_earnings_revision_3m_direction: no revisions within "
            "%dd window after date filter — returning 'unknown'",
            window_days,
        )
        return "unknown"

    # iter-2 (CR1 double-count fix): compute row-level up/down masks
    # separately, then take mutually-exclusive per-row classification. A row
    # matching BOTH patterns (e.g. "Barclays raised target to $X, Morgan
    # Stanley cut target to $Y" — a multi-analyst rollup) is AMBIGUOUS and
    # excluded from the directional count entirely, rather than double-
    # counting into both ups and downs.
    titles = df["news_title"].astype(str)
    up_mask = titles.str.contains(_REVISION_UP_PATTERN, na=False)
    down_mask = titles.str.contains(_REVISION_DOWN_PATTERN, na=False)
    up_only_mask = up_mask & ~down_mask
    down_only_mask = down_mask & ~up_mask
    ambiguous_count = int((up_mask & down_mask).sum())
    ups = int(up_only_mask.sum())
    downs = int(down_only_mask.sum())
    total_directional = ups + downs

    if total_directional < min_revisions:
        # R7.3 loud-empty: not enough signal to call direction.
        logger.warning(
            "_compute_earnings_revision_3m_direction: insufficient analyst "
            "revisions in %dd window (%d directional, %d ambiguous, need "
            ">= %d) — returning 'unknown'",
            window_days,
            total_directional,
            ambiguous_count,
            min_revisions,
        )
        return "unknown"

    net_ratio = (ups - downs) / total_directional
    if abs(net_ratio) < net_threshold:
        return "flat"
    return "up" if net_ratio > 0 else "down"


def _compute_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to a daily OHLCV DataFrame.

    Expects columns: open, high, low, close, volume.
    Returns the same DataFrame with indicator columns added in-place.
    """
    df = df.copy()

    # --- Normalise column names (OpenBB returns lowercase) ---
    df.columns = [c.lower() for c in df.columns]
    for alias in [("adj_close", "close"), ("adjusted_close", "close")]:
        if alias[0] in df.columns and alias[1] not in df.columns:
            df[alias[1]] = df[alias[0]]

    c = df["close"]
    h = df["high"]
    lo = df["low"]
    v = df["volume"]

    # --- Trend ---
    df["sma_50"]  = c.rolling(50).mean()
    df["sma_200"] = c.rolling(200).mean()
    df["adx"]     = _compute_adx(h, lo, c, 14)
    df["atr"]     = _compute_atr(h, lo, c, 14)

    # VWAP (cumulative from start of window)
    typical = (h + lo + c) / 3
    df["vwap"] = (typical * v).cumsum() / v.cumsum()

    # Ichimoku (9, 26, 52)
    df["tenkan"] = (h.rolling(9).max()  + lo.rolling(9).min())  / 2
    df["kijun"]  = (h.rolling(26).max() + lo.rolling(26).min()) / 2
    df["span_a"] = ((df["tenkan"] + df["kijun"]) / 2).shift(26)
    df["span_b"] = ((h.rolling(52).max() + lo.rolling(52).min()) / 2).shift(26)
    df["chikou"] = c.shift(-26)

    # --- Momentum ---
    df["rsi"]     = _compute_rsi(c, 14)

    # MACD (12, 26, 9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # Stochastic (14, 3, 3)
    low14  = lo.rolling(14).min()
    high14 = h.rolling(14).max()
    df["stoch_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    # Rate of Change
    df["roc_20"]  = c.pct_change(20)  * 100
    df["roc_60"]  = c.pct_change(60)  * 100
    df["roc_120"] = c.pct_change(120) * 100

    # 52-week high proximity
    df["high_52w"]        = c.rolling(252).max()
    df["dist_52w_high"]   = (df["high_52w"] - c) / df["high_52w"]

    # --- Volatility ---
    # Bollinger Bands (20, 2)
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma20.replace(0, np.nan)

    # --- Volume ---
    # OBV
    obv_vals = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["obv"]       = obv_vals
    df["obv_slope"] = obv_vals.diff(20)  # 20-day OBV change

    # Breakout Volume Ratio
    vol_20_avg         = v.rolling(20).mean()
    df["vol_ratio"]    = v / vol_20_avg.replace(0, np.nan)

    # Chaikin Money Flow CMF(21)
    mfm = ((c - lo) - (h - c)) / (h - lo).replace(0, np.nan)
    df["cmf_21"] = (mfm * v).rolling(21).sum() / v.rolling(21).sum()

    return df


def _dcf_single(
    fcf0: float,
    g_short: float,
    g_term: float,
    wacc: float,
    shares: float,
) -> float:
    """Compute a single DCF fair value per share.

    Uses a 5-year explicit FCF projection plus a Gordon Growth terminal value.
    """
    if wacc <= g_term:
        g_term = wacc - 0.01

    pv_explicit = sum(
        fcf0 * (1 + g_short) ** t / (1 + wacc) ** t for t in range(1, 6)
    )
    fcf_5 = fcf0 * (1 + g_short) ** 5
    tv    = fcf_5 * (1 + g_term) / (wacc - g_term)
    pv_tv = tv / (1 + wacc) ** 5

    if shares <= 0:
        return float("nan")
    return (pv_explicit + pv_tv) / shares


def _dcf_two_stage(
    fcf0: float,
    g_short: float,
    g_term: float,
    wacc: float,
    shares: float,
    explicit_years: int = 5,
    fade_years: int = 8,
) -> float:
    """Compute a two-stage DCF fair value per share (bead OpenBBTechnical-0h2.6).

    Improvement over :func:`_dcf_single`: instead of jumping straight from
    ``g_short`` at year 5 to ``g_term`` at year 6 (single-stage Gordon),
    growth **linearly fades** from ``g_short`` down to ``g_term`` across
    *fade_years* additional years.  This matches the Damodaran/McKinsey
    three-stage template and empirically better reflects corporate growth
    mean-reversion — a 15 % grower doesn't drop to 2.5 % overnight, but it
    also can't sustain 15 % forever.

    The signature is deliberately compatible with :func:`_dcf_single` so
    ``phase4_valuation`` can pick one at the top and route every DCF call
    (fair value, sensitivity, reverse-DCF) through the chosen callable.

    Parameters
    ----------
    fcf0 : float
        Trailing free cash flow (year 0).
    g_short : float
        Growth rate for the explicit projection (years 1..explicit_years).
    g_term : float
        Terminal growth rate (year explicit_years + fade_years + 1 and beyond).
    wacc : float
        Weighted average cost of capital (discount rate).
    shares : float
        Diluted shares outstanding.
    explicit_years : int, default 5
        Years of explicit high-growth projection.  Matches ``_dcf_single``.
    fade_years : int, default 8
        Years over which growth linearly fades from g_short to g_term.

    Returns
    -------
    float
        Fair value per share.  NaN if shares <= 0.

    Notes
    -----
    The terminal value is computed at the END of the fade period (year
    ``explicit_years + fade_years``) using the year-N FCF and terminal
    growth, discounted back to today.  Same wacc <= g_term guard as
    _dcf_single applies (clamps g_term to wacc - 0.01).
    """
    if wacc <= g_term:
        g_term = wacc - 0.01

    if shares <= 0:
        return float("nan")

    # Stage 1: explicit high growth for years 1..explicit_years
    fcf = fcf0
    pv_total = 0.0
    for t in range(1, explicit_years + 1):
        fcf = fcf * (1 + g_short)
        pv_total += fcf / (1 + wacc) ** t

    # Stage 2: linear fade from g_short to g_term over fade_years
    # Year (explicit + 1) uses g_short + step * 1, ..., year (explicit + fade_years)
    # uses g_short + step * fade_years = g_term (i.e., fully faded by end).
    if fade_years > 0:
        step = (g_term - g_short) / fade_years
        for k in range(1, fade_years + 1):
            growth_k = g_short + step * k
            fcf = fcf * (1 + growth_k)
            year = explicit_years + k
            pv_total += fcf / (1 + wacc) ** year

    # Terminal at end of fade (year N = explicit_years + fade_years)
    n = explicit_years + fade_years
    tv    = fcf * (1 + g_term) / (wacc - g_term)
    pv_tv = tv / (1 + wacc) ** n
    pv_total += pv_tv

    return pv_total / shares


def _dcf_sensitivity(
    fcf0: float,
    g_short: float,
    wacc_base: float,
    g_term_base: float,
    shares: float,
    dcf_fn: "callable | None" = None,
) -> pd.DataFrame:
    """Build a 3×3 sensitivity table: rows = WACC ±1%, cols = g_term ±0.5%.

    *dcf_fn* selects which DCF model to use for each cell; defaults to
    :func:`_dcf_single` for backward-compat.  Pass :func:`_dcf_two_stage`
    to build a sensitivity table under the fade model (bead 0h2.6).
    """
    fn = dcf_fn if dcf_fn is not None else _dcf_single
    wacc_steps   = [wacc_base - 0.01, wacc_base, wacc_base + 0.01]
    g_term_steps = [g_term_base - 0.005, g_term_base, g_term_base + 0.005]
    rows = {}
    for w in wacc_steps:
        row = {}
        for g in g_term_steps:
            row[f"g_term={g:.3f}"] = round(fn(fcf0, g_short, g, w, shares), 2)
        rows[f"wacc={w:.3f}"] = row
    return pd.DataFrame(rows).T


def _entry_quality_label(mos: float, bullish_count: int) -> str:
    """Map margin-of-safety + bullish_count to entry quality tier."""
    if mos >= 0.20 and bullish_count >= 6:
        return "High Conviction"
    elif mos >= 0.20 and bullish_count >= 3:
        return "Value Entry"
    elif mos >= 0.05 and bullish_count >= 6:
        return "Momentum Entry"
    return "Wait"


def _decision_label(score: float) -> str:
    """Map composite score to action label."""
    if score >= 4.2:
        return "Strong Buy"
    elif score >= 3.6:
        return "Buy"
    elif score >= 2.8:
        return "Hold/Watch"
    return "Avoid"


def _score_phase1(p1: Phase1Result) -> float:
    """Phase 1 proxy score: market cap tier + data coverage + peer count."""
    score = 2.5  # baseline
    cap = p1.market_cap
    if cap >= 100e9:
        score += 0.75
    elif cap >= 10e9:
        score += 0.5
    elif cap >= 1e9:
        score += 0.25
    if len(p1.peers) >= 5:
        score += 0.5
    if not p1.geo_df.empty:
        score += 0.25
    return min(score, 5.0)


def _score_phase4(p4: Phase4Result) -> float:
    """Phase 4 valuation score from MOS + Piotroski + Altman."""
    score = 2.5
    mos   = p4.margin_of_safety
    if mos >= 0.25:
        score += 1.0
    elif mos >= 0.15:
        score += 0.5
    elif mos >= 0.05:
        score += 0.0
    else:
        score -= 0.5
    if p4.piotroski >= 7:
        score += 0.5
    elif p4.piotroski <= 3:
        score -= 0.5
    if p4.altman < 1.81:
        score = 1.0  # distress hard cap
    return float(np.clip(score, 0.0, 5.0))


def _score_phase5(p5: Phase5Result) -> float:
    """Phase 5 risk score from Sharpe, Calmar, MaxDD."""
    score = 2.5
    if p5.sharpe > 1.5:
        score += 1.0
    elif p5.sharpe > 1.0:
        score += 0.5
    elif p5.sharpe < 0.3:
        score -= 0.5
    if p5.calmar > 2.0:
        score += 0.5
    elif p5.calmar < 0.5:
        score -= 0.5
    if p5.max_drawdown < -0.5:
        score -= 0.5
    return float(np.clip(score, 0.0, 5.0))


def _build_handoff(
    p1: Phase1Result,
    p2: Phase2Result,
    p3: Phase3Result,
    p4: Phase4Result,
    p5: Phase5Result,
    p6: Phase6Result,
    composite: float,
) -> dict[str, Any]:
    """Build the 6-item handoff template."""
    return {
        "investment_thesis": (
            f"{p1.sector} — {p1.industry} with "
            f"Phase 2 fundamental score {p2.score:.2f}/5.0"
        ),
        "bullish_drivers": [
            f"DCF fair value ${p4.dcf_fair_value:.2f} with MOS {p4.margin_of_safety:.1%}",
            f"Phase 2 score {p2.score:.2f}/5.0; gross profitability {p2.gross_profitability:.2%}",
            f"Technical bullish conditions {p3.bullish_count}/11; entry quality '{p3.entry_quality}'",
        ],
        "invalidation_events": [
            "Two consecutive quarterly revenue misses > 5%",
            "Weekly SMA50 crosses below weekly SMA200 (Death Cross on weekly)",
            "Altman Z drops below 1.81 (distress zone)",
        ],
        "fair_value_range": {
            "dcf": round(p4.dcf_fair_value, 2),
            "margin_of_safety": round(p4.margin_of_safety, 4),
            "valuation_verdict": p4.valuation_verdict,
        },
        "peer_relative": {
            "information_ratio": round(p6.information_ratio, 3),
            "relative_score": round(p6.relative_score, 2),
            "peer_verdict": p6.gate_notes,
        },
        "trade_plan": {
            "composite_score": round(composite, 3),
            "action_label": _decision_label(composite),
            "entry_quality": p3.entry_quality,
            "atr": round(p3.atr, 4),
            "portfolio_fit": p5.portfolio_fit,
        },
    }


# ---------------------------------------------------------------------------
# Sector ETF map
# ---------------------------------------------------------------------------
_SECTOR_ETF_MAP: dict[str, str] = {
    "Technology":             "XLK",
    "Financial Services":     "XLF",
    "Financial":              "XLF",
    "Healthcare":             "XLV",
    "Health Care":            "XLV",
    "Industrials":            "XLI",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Energy":                 "XLE",
    "Basic Materials":        "XLB",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
    "Communication Services": "XLC",
}


def _sector_etf(sector: str) -> str:
    return _SECTOR_ETF_MAP.get(sector, "SPY")


# ---------------------------------------------------------------------------
# Sector-adjusted WACC fallback map (bead OpenBBTechnical-0h2.7).
# ---------------------------------------------------------------------------
# Used only as a FALLBACK when the ratios provider returns no wacc.  A live
# ratios_df.wacc always wins over this default (see phase4_valuation).
#
# Rates are empirical-calibrated averages from sector-level cost-of-capital
# studies (Damodaran; McKinsey Valuation, 7th ed. Ch. 15).  Reviewer P4
# (item #10 in expert priority table) flagged the flat 9 % fallback as
# 'too aggressive for a utility, too generous for a crypto name'.
#
# All sector strings that appear in _SECTOR_ETF_MAP are covered here so
# the two lookups stay in sync as the map grows.
_SECTOR_WACC_MAP: dict[str, float] = {
    "Technology":             0.09,   # baseline — unchanged from flat fallback
    "Communication Services": 0.09,   # similar risk profile to tech
    "Financial Services":     0.10,   # banks/insurers — rate-sensitive
    "Financial":              0.10,   # alias for FMP inconsistency
    "Healthcare":             0.11,   # R&D + FDA + patent-cliff risk
    "Health Care":            0.11,   # alias for FMP inconsistency
    "Consumer Cyclical":      0.10,   # discretionary-spend cyclicality
    "Consumer Defensive":     0.07,   # recession-resilient (staples)
    "Industrials":            0.09,   # middle of road
    "Basic Materials":        0.11,   # commodity-price exposure
    "Energy":                 0.12,   # commodity + geopolitical
    "Utilities":              0.06,   # regulated, low vol, div-heavy
    "Real Estate":            0.08,   # REITs, moderate leverage
    "Crypto":                 0.15,   # bead-title exemplar: highest vol
}


def _sector_wacc_default(sector: str, default: float = 0.09) -> float:
    """Return the sector-calibrated WACC fallback (bead OpenBBTechnical-0h2.7).

    Used only when ratios_df.wacc is NaN or non-positive.  A live provider
    WACC always wins over this default in phase4_valuation.

    Parameters
    ----------
    sector : str
        Sector name as returned by ``obb.equity.profile`` (FMP-style).
        Unknown sectors return *default*.
    default : float, default 0.09
        Fallback when sector isn't in ``_SECTOR_WACC_MAP``.  Set to the
        flat pre-A4b rate so uncovered sectors don't shift silently.

    Returns
    -------
    float
        WACC as a decimal (0.09 = 9 %).
    """
    return _SECTOR_WACC_MAP.get(sector, default)


# ---------------------------------------------------------------------------
# Phase 1: Company Profile & Business Quality Screen
# ---------------------------------------------------------------------------


def phase1_company_profile(cfg: AnalysisConfig) -> Phase1Result:
    """Phase 1 — Retrieve company profile, quote, ownership, and analyst targets.

    OpenBB endpoints used (all provider="fmp_cached"):
    - ``obb.equity.profile``
    - ``obb.equity.price.quote``
    - ``obb.equity.fundamental.metrics``
    - ``obb.equity.compare.peers``
    - ``obb.equity.fundamental.revenue_per_geography``
    - ``obb.equity.ownership.insider_trading``
    - ``obb.equity.ownership.institutional``
    - ``obb.equity.estimates.price_target``

    The ``fmp_cached`` provider for institutional ownership handles a three-tier
    fallback internally: FMP API -> yfinance -> SEC EDGAR 13F.  Results are
    cached in MySQL regardless of source.

    Returns
    -------
    Phase1Result
    """
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError("openbb package not installed") from exc

    sym = cfg.symbol
    prv = cfg.provider

    profile_df = _to_df(obb.equity.profile(symbol=sym, provider=prv))
    quote_df   = _to_df(obb.equity.price.quote(symbol=sym, provider=prv))
    metrics_df = _to_df(
        obb.equity.fundamental.metrics(symbol=sym, period="annual", limit=5, provider=prv)
    )

    # Peers
    try:
        peers_raw = _to_df(obb.equity.compare.peers(symbol=sym, provider=prv))
        if "peers_list" in peers_raw.columns:
            raw_peers = peers_raw["peers_list"].iloc[0]
            peers = raw_peers if isinstance(raw_peers, list) else str(raw_peers).split(",")
            peers = [p.strip() for p in peers if p.strip() and p.strip() != sym]
        else:
            peers = list(peers_raw.get("symbol", pd.Series([])).tolist())
    except Exception:  # noqa: BLE001
        peers = []

    # Geography revenue
    try:
        geo_df = _to_df(
            obb.equity.fundamental.revenue_per_geography(
                symbol=sym, period="annual", provider=prv
            )
        )
    except Exception:  # noqa: BLE001
        geo_df = pd.DataFrame()

    # Insider trading
    try:
        insider_df = _to_df(
            obb.equity.ownership.insider_trading(symbol=sym, limit=20, provider=prv)
        )
    except Exception:  # noqa: BLE001
        insider_df = pd.DataFrame()

    # Institutional ownership (fmp_cached handles fallback: FMP -> yfinance -> SEC)
    try:
        institutional_df = _to_df(
            obb.equity.ownership.institutional(symbol=sym, provider=prv)
        )
    except Exception:  # noqa: BLE001
        institutional_df = pd.DataFrame()

    # Analyst price targets
    try:
        price_targets_df = _to_df(
            obb.equity.estimates.price_target(symbol=sym, provider=prv)
        )
    except Exception:  # noqa: BLE001
        price_targets_df = pd.DataFrame()

    # Tradeability: free float from share_statistics (bead OpenBBTechnical-0h2.3).
    # The FMPShareStatisticsData validator returns free_float already normalised
    # to a 0-1 fraction (raw percent / 100).  Fallback path derives it from
    # float_shares / outstanding_shares if the primary field is empty.
    free_float_pct: float | None = None
    try:
        share_stats_df = _to_df(
            obb.equity.share_statistics(symbol=sym, provider=prv)
        )
        primary = _latest_col(share_stats_df, ["free_float"])
        if not np.isnan(primary):
            free_float_pct = float(primary)
        else:
            float_shares = _latest_col(share_stats_df, ["float_shares"])
            outstanding = _latest_col(share_stats_df, ["outstanding_shares"])
            if not np.isnan(float_shares) and not np.isnan(outstanding) and outstanding > 0:
                free_float_pct = float(float_shares) / float(outstanding)
    except Exception:  # noqa: BLE001
        free_float_pct = None

    # Short interest: fmp_cached does not expose it today.  Preserved on the
    # dataclass so downstream phases can consume the field once a follow-up
    # bead adds a secondary provider (finra_cached or similar).
    short_interest_pct: float | None = None

    # Extract key fields
    sector   = _safe_str(profile_df, ["sector"])
    industry = _safe_str(profile_df, ["industry"])
    mktcap   = _latest_col(quote_df, ["market_cap", "marketCap"], default=0.0)
    if mktcap == 0.0:
        mktcap = _latest_col(metrics_df, ["market_cap", "marketCap"], default=0.0)

    # Gate: pass if business is understandable (we have profile + sector)
    gate_passed = bool(sector and not profile_df.empty)
    gate_notes  = "OK" if gate_passed else "Profile data missing — do not proceed"

    # Forward-looking analyst-revision direction (bd-0h2.10 / A7,
    # reviewer's structural gap #2). Reuses the price_targets_df fetched
    # above — no additional provider call.
    earnings_revision_3m_direction = _compute_earnings_revision_3m_direction(
        price_targets_df
    )

    return Phase1Result(
        profile_df=profile_df,
        quote_df=quote_df,
        metrics_df=metrics_df,
        peers=peers[:12],
        geo_df=geo_df,
        insider_df=insider_df,
        institutional_df=institutional_df,
        price_targets_df=price_targets_df,
        sector=sector,
        industry=industry,
        market_cap=mktcap,
        free_float_pct=free_float_pct,
        short_interest_pct=short_interest_pct,
        earnings_revision_3m_direction=earnings_revision_3m_direction,
        gate_passed=gate_passed,
        gate_notes=gate_notes,
    )


def _safe_str(df: pd.DataFrame, candidates: list[str], default: str = "") -> str:
    """Return first non-null string value from candidate columns."""
    for col in candidates:
        if col in df.columns:
            val = df[col].dropna()
            if not val.empty:
                return str(val.iloc[0])
    return default


# ---------------------------------------------------------------------------
# Phase 2: 5-Year Fundamental Analysis
# ---------------------------------------------------------------------------


def phase2_fundamentals(cfg: AnalysisConfig) -> Phase2Result:
    """Phase 2 — Five-year fundamental analysis, scorecard, and earnings quality.

    OpenBB endpoints used (all provider="fmp_cached"):
    - ``obb.equity.fundamental.income``
    - ``obb.equity.fundamental.balance``
    - ``obb.equity.fundamental.cash``
    - ``obb.equity.fundamental.ratios``

    Returns
    -------
    Phase2Result
    """
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError("openbb package not installed") from exc

    sym = cfg.symbol
    prv = cfg.provider

    income_df  = _to_df(obb.equity.fundamental.income( symbol=sym, period="annual", limit=5, provider=prv))
    balance_df = _to_df(obb.equity.fundamental.balance(symbol=sym, period="annual", limit=5, provider=prv))
    cash_df    = _to_df(obb.equity.fundamental.cash(   symbol=sym, period="annual", limit=5, provider=prv))
    ratios_df  = _to_df(obb.equity.fundamental.ratios( symbol=sym, period="annual", limit=5, provider=prv))

    # Ensure chronological order (oldest first for CAGR)
    for df in [income_df, balance_df, cash_df, ratios_df]:
        if "date" in df.columns:
            df.sort_values("date", inplace=True)
            df.reset_index(drop=True, inplace=True)

    # --- Growth KPIs ---
    rev_col  = _find_col(income_df,  ["revenue", "total_revenue"])
    eps_col  = _find_col(income_df,  ["eps_diluted", "eps", "basic_earnings_per_share"])
    fcf_col  = _find_col(cash_df,    ["free_cash_flow", "freeCashFlow"])

    revenue_cagr = _cagr(income_df[rev_col], 5)  if rev_col  else float("nan")
    eps_cagr     = _cagr(income_df[eps_col], 5)  if eps_col  else float("nan")
    fcf_cagr     = _cagr(cash_df[fcf_col],   5)  if fcf_col  else float("nan")

    # --- Profitability ---
    gp_col   = _find_col(income_df, ["gross_profit", "grossProfit"])
    oi_col   = _find_col(income_df, ["operating_income", "operatingIncome"])
    ni_col   = _find_col(income_df, ["net_income", "netIncome"])
    ta_col   = _find_col(balance_df,["total_assets", "totalAssets"])

    gross_margin   = _pct_last(income_df, gp_col,  income_df, rev_col)
    op_margin      = _pct_last(income_df, oi_col,  income_df, rev_col)
    net_margin     = _pct_last(income_df, ni_col,  income_df, rev_col)
    roic           = _latest_col(ratios_df, ["roic", "return_on_invested_capital"])

    # Gross profitability (Novy-Marx): gross_profit / total_assets
    gross_profitability = float("nan")
    if gp_col and ta_col and not income_df.empty and not balance_df.empty:
        n = min(len(income_df), len(balance_df))
        gross_profitability = float(
            income_df[gp_col].iloc[-1] / balance_df[ta_col].iloc[-1]
        )

    # --- Balance Sheet ---
    de_ratio    = _latest_col(ratios_df, ["debt_equity_ratio", "debtEquityRatio", "debt_to_equity"])
    curr_ratio  = _latest_col(ratios_df, ["current_ratio",     "currentRatio"])
    int_cov     = _latest_col(ratios_df, ["interest_coverage", "interestCoverage"])

    # Net Debt / EBITDA (derived)
    ebitda_col = _find_col(income_df, ["ebitda", "EBITDA"])
    debt_col   = _find_col(balance_df,["total_debt", "totalDebt", "long_term_debt"])
    cash_eq    = _find_col(balance_df,["cash_and_equivalents", "cashAndCashEquivalents", "cash"])
    net_debt_ebitda = float("nan")
    if debt_col and cash_eq and ebitda_col:
        net_debt  = balance_df[debt_col].iloc[-1] - balance_df[cash_eq].iloc[-1]
        ebitda_v  = income_df[ebitda_col].iloc[-1]
        net_debt_ebitda = float(net_debt / ebitda_v) if ebitda_v != 0 else float("nan")

    # --- Cash Flow Quality ---
    cfo_col  = _find_col(cash_df, ["operating_cash_flow", "netCashProvidedByOperatingActivities"])
    cfo_ni   = float("nan")
    fcf_margin = float("nan")
    capex_rev  = float("nan")
    if cfo_col and ni_col:
        cfo_v  = cash_df[cfo_col].iloc[-1]
        ni_v   = income_df[ni_col].iloc[-1]
        cfo_ni = float(cfo_v / ni_v) if ni_v != 0 else float("nan")
    if fcf_col and rev_col:
        fcf_margin = float(cash_df[fcf_col].iloc[-1] / income_df[rev_col].iloc[-1])
    capex_col = _find_col(cash_df, ["capital_expenditures", "capitalExpenditures"])
    if capex_col and rev_col:
        capex_rev = float(abs(cash_df[capex_col].iloc[-1]) / income_df[rev_col].iloc[-1])

    # --- Accruals Ratio (Sloan) ---
    accruals_ratio = float("nan")
    try:
        if ni_col and cfo_col and ta_col and cash_eq and debt_col:
            accruals    = income_df[ni_col] - cash_df[cfo_col]
            noa         = (balance_df[ta_col] - balance_df[cash_eq]) - \
                          (balance_df[_find_col(balance_df, ["total_liabilities", "totalLiabilities"])] -
                           balance_df[debt_col])
            noa_avg     = noa.rolling(2, min_periods=1).mean()
            accruals_ratio = float((accruals / noa_avg).iloc[-1])
    except Exception:  # noqa: BLE001
        pass

    # --- DuPont ROE Decomposition ---
    te_col = _find_col(balance_df, ["total_equity", "totalEquity", "stockholders_equity"])
    roe_decomp_df = pd.DataFrame()
    try:
        if ni_col and rev_col and ta_col and te_col:
            nm   = income_df[ni_col].values / income_df[rev_col].replace(0, np.nan).values
            ta   = balance_df[ta_col].values
            at   = income_df[rev_col].values / ((ta[:-1] + ta[1:]) / 2 + 1e-9)  # rolling avg
            te   = balance_df[te_col].values
            em   = ta / (te + 1e-9)
            n    = min(len(nm), len(em), len(te))
            roe_decomp_df = pd.DataFrame({
                "net_margin":       nm[:n],
                "asset_turnover":   np.pad(at, (1, 0), constant_values=np.nan)[:n],
                "equity_multiplier": em[:n],
                "roe_check":        nm[:n] * np.pad(at, (1, 0), constant_values=np.nan)[:n] * em[:n],
            })
    except Exception:  # noqa: BLE001
        pass

    asset_turn_trend = float("nan")
    if not roe_decomp_df.empty and "asset_turnover" in roe_decomp_df.columns:
        asset_turn_trend = float(roe_decomp_df["asset_turnover"].diff().mean())

    # --- Share Dilution ---
    shares_col   = _find_col(income_df, ["shares_outstanding", "weighted_average_shares",
                                          "weighted_average_diluted_shares_outstanding"])
    shares_col2  = _find_col(ratios_df,  ["shares_outstanding"])
    dilution_5y  = float("nan")
    if shares_col and len(income_df) >= 2:
        s = income_df[shares_col].dropna()
        if len(s) >= 2:
            dilution_5y = float(s.iloc[-1] / s.iloc[0] - 1)
    elif shares_col2 and len(ratios_df) >= 2:
        s = ratios_df[shares_col2].dropna()
        if len(s) >= 2:
            dilution_5y = float(s.iloc[-1] / s.iloc[0] - 1)

    # --- Operating Leverage ---
    operating_leverage = float("nan")
    try:
        if oi_col and rev_col:
            pct_ebit = income_df[oi_col].pct_change().replace([np.inf, -np.inf], np.nan)
            pct_rev  = income_df[rev_col].pct_change().replace([np.inf, -np.inf], np.nan)
            operating_leverage = float((pct_ebit / pct_rev).mean())
    except Exception:  # noqa: BLE001
        pass

    # --- SG&A Efficiency Trend ---
    sga_col = _find_col(income_df, ["selling_general_administrative_expenses",
                                     "sga", "selling_and_marketing_expenses"])
    sga_trend = float("nan")
    if sga_col and rev_col:
        try:
            sga_ratio = income_df[sga_col] / income_df[rev_col]
            sga_trend = float(sga_ratio.diff().mean())
        except Exception:  # noqa: BLE001
            pass

    # --- Dividend FCF Payout ---
    div_col  = _find_col(cash_df, ["dividends_paid", "common_stock_dividends_paid"])
    fcf_payout_ratio = float("nan")
    if div_col and fcf_col:
        try:
            divs = cash_df[div_col].abs()
            fcfs = cash_df[fcf_col]
            if divs.sum() > 0:
                fcf_payout_ratio = float((divs / fcfs).replace([np.inf, -np.inf], np.nan).iloc[-1])
        except Exception:  # noqa: BLE001
            pass

    # --- Build KPI summary DataFrame ---
    kpi_data = {
        "revenue_cagr_5y":       revenue_cagr,
        "eps_cagr_5y":           eps_cagr,
        "fcf_cagr_5y":           fcf_cagr,
        "gross_margin":          gross_margin,
        "operating_margin":      op_margin,
        "net_margin":            net_margin,
        "roic":                  roic,
        "gross_profitability":   gross_profitability,
        "debt_equity":           de_ratio,
        "current_ratio":         curr_ratio,
        "interest_coverage":     int_cov,
        "net_debt_ebitda":       net_debt_ebitda,
        "cfo_net_income":        cfo_ni,
        "fcf_margin":            fcf_margin,
        "capex_revenue":         capex_rev,
        "accruals_ratio_sloan":  accruals_ratio,
        "dilution_5y":           dilution_5y,
        "operating_leverage":    operating_leverage,
        "sga_trend":             sga_trend,
        "fcf_payout_ratio":      fcf_payout_ratio,
    }
    kpi_df = pd.DataFrame([kpi_data])

    # --- Scoring (simplified weighted 0-5) ---
    score = _score_fundamentals(kpi_data, accruals_ratio, gross_profitability)

    # Gate
    gate_passed = score >= 3.5 and (
        np.isnan(accruals_ratio) or accruals_ratio < 0.20
    )
    gate_notes = (
        f"Score {score:.2f}/5.0 — {'PASS' if gate_passed else 'FAIL'}"
        + (f"; Accruals ratio {accruals_ratio:.2%} ELEVATED" if (not np.isnan(accruals_ratio) and accruals_ratio > 0.15) else "")
    )

    return Phase2Result(
        income_df=income_df,
        balance_df=balance_df,
        cash_df=cash_df,
        ratios_df=ratios_df,
        kpi_df=kpi_df,
        roe_decomp_df=roe_decomp_df,
        score=score,
        accruals_ratio=accruals_ratio,
        gross_profitability=gross_profitability,
        operating_leverage=operating_leverage,
        dilution_5y=dilution_5y,
        gate_passed=gate_passed,
        gate_notes=gate_notes,
    )


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first candidate column name present in df, or None."""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _pct_last(
    num_df: pd.DataFrame, num_col: str | None,
    den_df: pd.DataFrame, den_col: str | None,
) -> float:
    """Compute ratio of last values across two DataFrames."""
    if num_col and den_col:
        try:
            n = num_df[num_col].dropna().iloc[-1]
            d = den_df[den_col].dropna().iloc[-1]
            return float(n / d) if d != 0 else float("nan")
        except Exception:  # noqa: BLE001
            pass
    return float("nan")


def _score_fundamentals(kpis: dict, accruals_ratio: float, gross_profitability: float) -> float:
    """Produce a simplified weighted Phase 2 composite score (0-5 scale).

    Weights (v1.1):
        Growth quality       20%
        Profitability        20%
        Capital efficiency   20%
        Balance sheet        15%
        Cash flow quality    15%
        Structural           10%
    """
    def clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    def band(val: float, thresholds: list[tuple[float, float]]) -> float:
        """Map a value to a score using ascending threshold bands."""
        for threshold, score in thresholds:
            if val <= threshold:
                return score
        return thresholds[-1][1]

    # Growth (0-5)
    rev_cagr = kpis.get("revenue_cagr_5y", float("nan"))
    eps_cagr = kpis.get("eps_cagr_5y", float("nan"))
    fcf_cagr = kpis.get("fcf_cagr_5y", float("nan"))
    growth_scores = [v for v in [rev_cagr, eps_cagr, fcf_cagr] if not np.isnan(v)]
    growth_sc = float(np.mean([clamp((g + 0.05) / 0.20 * 4 + 1, 1, 5) for g in growth_scores])) \
        if growth_scores else 2.5

    # Profitability (0-5)
    gm   = kpis.get("gross_margin", float("nan"))
    om   = kpis.get("operating_margin", float("nan"))
    roic = kpis.get("roic", float("nan"))
    gp   = gross_profitability
    prof_parts = []
    if not np.isnan(gm):
        prof_parts.append(clamp(gm / 0.40 * 4 + 1, 1, 5))
    if not np.isnan(om):
        prof_parts.append(clamp(om / 0.20 * 4 + 1, 1, 5))
    if not np.isnan(roic):
        prof_parts.append(clamp(roic / 0.20 * 4 + 1, 1, 5))
    if not np.isnan(gp):
        prof_parts.append(clamp(gp / 0.40 * 4 + 1, 1, 5))
    prof_sc = float(np.mean(prof_parts)) if prof_parts else 2.5

    # Capital efficiency
    dil   = kpis.get("dilution_5y", float("nan"))
    dil_sc = 5.0 - clamp((dil + 0.10) / 0.20 * 4, 0, 4) if not np.isnan(dil) else 2.5
    cap_sc = (prof_sc + dil_sc) / 2

    # Balance sheet
    de     = kpis.get("debt_equity", float("nan"))
    ic     = kpis.get("interest_coverage", float("nan"))
    nde    = kpis.get("net_debt_ebitda", float("nan"))
    bs_parts = []
    if not np.isnan(de):
        bs_parts.append(clamp(4.0 - de * 0.8, 1, 5))
    if not np.isnan(ic):
        bs_parts.append(clamp((ic - 1) / 6 * 4 + 1, 1, 5))
    if not np.isnan(nde):
        bs_parts.append(clamp(4.5 - nde * 0.5, 1, 5))
    bs_sc = float(np.mean(bs_parts)) if bs_parts else 2.5

    # Cash flow quality
    cfo_ni  = kpis.get("cfo_net_income",    float("nan"))
    fcf_mg  = kpis.get("fcf_margin",        float("nan"))
    cf_parts = []
    if not np.isnan(cfo_ni):
        cf_parts.append(clamp((cfo_ni - 0.5) / 0.7 * 4 + 1, 1, 5))
    if not np.isnan(fcf_mg):
        cf_parts.append(clamp(fcf_mg / 0.15 * 4 + 1, 1, 5))
    if not np.isnan(accruals_ratio):
        cf_parts.append(clamp(4.5 - accruals_ratio * 25, 1, 5))
    cf_sc = float(np.mean(cf_parts)) if cf_parts else 2.5

    # Structural (10%)
    op_lev = kpis.get("operating_leverage", float("nan"))
    struct_sc = clamp(4.0 - max(0.0, op_lev - 1.0), 1, 5) if not np.isnan(op_lev) else 2.5

    # Hard floor: if any category <= 1.5, cap final at 3.8
    categories = [growth_sc, prof_sc, cap_sc, bs_sc, cf_sc, struct_sc]
    composite = (
        growth_sc * 0.20
        + prof_sc  * 0.20
        + cap_sc   * 0.20
        + bs_sc    * 0.15
        + cf_sc    * 0.15
        + struct_sc * 0.10
    )
    if any(sc <= 1.5 for sc in categories):
        composite = min(composite, 3.8)

    return round(float(np.clip(composite, 0, 5)), 3)


# ---------------------------------------------------------------------------
# Phase 3: Technical Analysis & Trade Timing
# ---------------------------------------------------------------------------


def phase3_technicals(cfg: AnalysisConfig) -> Phase3Result:
    """Phase 3 — Compute all technical indicators and evaluate the 11-condition setup.

    OpenBB endpoints used (all provider="fmp_cached"):
    - ``obb.equity.price.historical``
    - ``obb.equity.calendar.earnings`` (for earnings date proximity guard)

    Returns
    -------
    Phase3Result
    """
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError("openbb package not installed") from exc

    sym = cfg.symbol
    prv = cfg.provider

    price_raw = _to_df(
        obb.equity.price.historical(
            symbol=sym,
            start_date=cfg.start_technicals,
            end_date=cfg.end_date,
            interval="1d",
            provider=prv,
        )
    )

    if price_raw.empty:
        raise RuntimeError(f"No price data returned for {sym}")

    price_df = _compute_technicals(price_raw)

    # --- Earnings date proximity ---
    days_to_earnings = 999
    try:
        earnings_cal = _to_df(obb.equity.calendar.earnings(symbol=sym, provider=prv))
        if not earnings_cal.empty:
            date_col = _find_col(earnings_cal, ["date", "earnings_date", "report_date"])
            if date_col:
                future_dates = pd.to_datetime(earnings_cal[date_col]).dropna()
                today = pd.Timestamp.today().normalize()
                future_dates = future_dates[future_dates >= today]
                if not future_dates.empty:
                    days_to_earnings = int((future_dates.min() - today).days)
    except Exception:  # noqa: BLE001
        pass

    earnings_safe_window = days_to_earnings > 5

    # --- Weekly resampled indicators ---
    weekly_trend_bullish = False
    try:
        weekly_df = price_df.resample("W").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna(subset=["close"])
        if len(weekly_df) >= 20:
            weekly_sma20 = weekly_df["close"].rolling(20).mean()
            weekly_adx   = _compute_adx(weekly_df["high"], weekly_df["low"], weekly_df["close"], 14)
            last_close_w = weekly_df["close"].iloc[-1]
            last_sma20_w = weekly_sma20.iloc[-1]
            last_adx_w   = weekly_adx.iloc[-1]
            weekly_trend_bullish = bool(
                not np.isnan(last_sma20_w)
                and last_close_w > last_sma20_w
                and not np.isnan(last_adx_w)
                and last_adx_w > 20
            )
    except Exception:  # noqa: BLE001
        pass

    # --- Latest values ---
    last = price_df.iloc[-1]
    c    = last["close"]

    # Fibonacci levels
    swing_high = float(price_df["close"].rolling(min(252, len(price_df))).max().iloc[-1])
    swing_low  = float(price_df["close"].rolling(min(252, len(price_df))).min().iloc[-1])
    fib_range  = swing_high - swing_low
    fib_levels = {
        "23.6%": round(swing_high - 0.236 * fib_range, 4),
        "38.2%": round(swing_high - 0.382 * fib_range, 4),
        "50.0%": round(swing_high - 0.500 * fib_range, 4),
        "61.8%": round(swing_high - 0.618 * fib_range, 4),
        "78.6%": round(swing_high - 0.786 * fib_range, 4),
    }

    # --- 11-condition trade setup ---
    def safe_bool(expr):
        try:
            return bool(expr)
        except Exception:  # noqa: BLE001
            return False

    s = price_df
    signals = {
        "sma_golden_cross": safe_bool(
            not np.isnan(last.get("sma_50", np.nan))
            and not np.isnan(last.get("sma_200", np.nan))
            and last["sma_50"] > last["sma_200"]
        ),
        "adx_trending": safe_bool(
            not np.isnan(last.get("adx", np.nan)) and last["adx"] >= 20
        ),
        "rsi_pullback": safe_bool(
            not np.isnan(last.get("rsi", np.nan))
            and 40 <= last["rsi"] <= 60
        ),
        "macd_bullish": safe_bool(
            not np.isnan(last.get("macd", np.nan))
            and not np.isnan(last.get("macd_signal", np.nan))
            and last["macd"] > last["macd_signal"]
        ),
        "obv_rising": safe_bool(
            not np.isnan(last.get("obv_slope", np.nan)) and last["obv_slope"] > 0
        ),
        "volume_ratio_normal": safe_bool(
            not np.isnan(last.get("vol_ratio", np.nan))
            and last["vol_ratio"] <= 2.5
        ),
        "above_vwap": safe_bool(
            not np.isnan(last.get("vwap", np.nan)) and c > last["vwap"]
        ),
        "above_cloud": safe_bool(
            not np.isnan(last.get("span_a", np.nan))
            and not np.isnan(last.get("span_b", np.nan))
            and c > max(last["span_a"], last["span_b"])
        ),
        "momentum_positive": safe_bool(
            not np.isnan(last.get("roc_60", np.nan))
            and not np.isnan(last.get("roc_120", np.nan))
            and last["roc_60"] > 0
            and last["roc_120"] > 0
        ),
        "cmf_positive": safe_bool(
            not np.isnan(last.get("cmf_21", np.nan)) and last["cmf_21"] > 0
        ),
        "weekly_trend_bullish": weekly_trend_bullish,
        "stochastic_bullish": safe_bool(
            not np.isnan(last.get("stoch_k", np.nan))
            and not np.isnan(last.get("stoch_d", np.nan))
            and last["stoch_k"] > last["stoch_d"]
            and last["stoch_k"] < 80
        ),
        "bb_squeeze_breakout": safe_bool(
            "bb_width" in price_df.columns
            and not np.isnan(last.get("bb_width", np.nan))
            and not np.isnan(last.get("bb_upper", np.nan))
            and len(price_df) >= 120
            and last["bb_width"] < price_df["bb_width"].rolling(120, min_periods=60).quantile(0.20).iloc[-1]
            and c > last["bb_upper"]
        ),
    }

    bullish_count = sum(signals.values())

    # Entry quality label
    high_conviction_conditions = ["above_vwap", "above_cloud", "momentum_positive", "weekly_trend_bullish"]
    high_conviction = all(signals.get(c, False) for c in high_conviction_conditions)
    if high_conviction and bullish_count >= 6:
        entry_quality = "High Conviction"
    elif bullish_count >= 6:
        entry_quality = "Standard"
    else:
        entry_quality = "Cautious"

    atr_latest = float(last.get("atr", price_df["atr"].dropna().iloc[-1] if "atr" in price_df.columns else 0.0))

    gate_passed = bullish_count >= 6 and earnings_safe_window
    gate_notes  = (
        f"{bullish_count}/{len(signals)} bullish conditions"
        + (" — EARNINGS RISK" if not earnings_safe_window else "")
        + (" — WEEKLY TREND BEARISH" if not weekly_trend_bullish else "")
    )

    # bd-85w (2026-07-11): opt-in techtrade extended-panel snapshot. Option A
    # per bd-85w design — this is an ADDITIVE augmentation, not a replacement.
    # The inline _compute_technicals pipeline above still drives every existing
    # signal + gate. The extended panel is exposed as Phase3Result.extended_panel
    # for notebooks / R&D code to inspect. Deferred to flag-on to preserve
    # pre-bd-85w wall-clock on the default path (build_indicator_panel adds
    # ~50-150ms on a typical 5y history; not free even though the seams are lazy).
    extended_panel: Any = None
    if cfg.feature_flags.use_extended_confluence_panel:
        try:
            from openbb_techtrade.engine.indicators import build_indicator_panel  # noqa: PLC0415
            from openbb_techtrade.engine.panel_config import PANEL_EXTENDED  # noqa: PLC0415
            # Build the OHLCV records shape build_indicator_panel expects:
            # list of dicts with a 'timestamp' key + lowercase OHLCV columns.
            # price_raw is the pre-augmentation DataFrame; use that (not
            # price_df which has all the indicator columns bolted on) to keep
            # the seam shape narrow.
            ohlcv_rows = price_raw.reset_index().to_dict(orient="records")
            # Normalize the index-column name to 'timestamp' as the panel
            # builder expects. reset_index() typically uses 'date' or 'index'
            # depending on how the DataFrame was constructed.
            for r in ohlcv_rows:
                for candidate in ("date", "index"):
                    if candidate in r and "timestamp" not in r:
                        r["timestamp"] = r.pop(candidate)
                        break
            as_of_dt = price_raw.index[-1].date() if len(price_raw) else None
            if as_of_dt is not None:
                extended_panel = build_indicator_panel(
                    symbol=sym,
                    as_of=as_of_dt,
                    ohlcv_rows=ohlcv_rows,
                    panel_config=PANEL_EXTENDED,
                )
        except Exception as exc:  # noqa: BLE001
            # R7.3 loud-empty: the flag was ON but the extended panel didn't
            # build. Log at WARNING so the user knows their opt-in silently
            # produced None instead of pretending nothing happened. Analysis
            # continues with the inline pipeline unchanged — no regression.
            logger.warning(
                "phase3_technicals: use_extended_confluence_panel=True for %s "
                "but build_indicator_panel raised %s: %s — extended_panel=None; "
                "classic technicals pipeline unaffected",
                sym, type(exc).__name__, exc,
            )

    return Phase3Result(
        price_df=price_df,
        signals=signals,
        bullish_count=bullish_count,
        entry_quality=entry_quality,
        fib_levels=fib_levels,
        atr=atr_latest,
        days_to_earnings=days_to_earnings,
        earnings_safe_window=earnings_safe_window,
        weekly_trend_bullish=weekly_trend_bullish,
        gate_passed=gate_passed,
        gate_notes=gate_notes,
        extended_panel=extended_panel,
    )


# ---------------------------------------------------------------------------
# Phase 4: Valuation & Fair Value Estimation
# ---------------------------------------------------------------------------


def phase4_valuation(
    cfg: AnalysisConfig,
    p2: Phase2Result,
    p3: Phase3Result,
    p1: Phase1Result | None = None,
) -> Phase4Result:
    """Phase 4 — DCF fair value, margin of safety, reverse-DCF, quality overlays.

    Uses data already fetched in Phase 2 — no new API calls for core valuation.
    Additional endpoint (fmp_cached):
    - None required: all data reused from p2 income_df, balance_df, cash_df, ratios_df.

    Parameters
    ----------
    cfg, p2, p3 : as usual.
    p1 : Phase1Result | None, default None
        Optional so pre-A4b callers still work.  When provided AND
        ``cfg.feature_flags.use_sector_wacc`` is True, the WACC fallback
        (used when ratios_df.wacc is missing) is drawn from
        :func:`_sector_wacc_default` using ``p1.sector``.  Without p1,
        the fallback silently degrades to the flat 9 % (pre-A4b behavior).

    Returns
    -------
    Phase4Result
    """
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError("openbb package not installed") from exc

    sym = cfg.symbol
    prv = cfg.provider

    income_df  = p2.income_df
    balance_df = p2.balance_df
    cash_df    = p2.cash_df
    ratios_df  = p2.ratios_df

    # --- Current price from Phase 3 ---
    current_price = float(p3.price_df["close"].iloc[-1])

    # --- Extract multiples from ratios_df ---
    pe        = _latest_col(ratios_df, ["price_earnings_ratio",   "pe_ratio", "pe"])
    ev_ebitda = _latest_col(ratios_df, ["enterprise_value_multiple", "ev_to_ebitda", "ev_ebitda"])
    p_fcf     = _latest_col(ratios_df, ["price_to_free_cash_flow", "price_to_free_cash_flow_ratio"])
    p_s       = _latest_col(ratios_df, ["price_to_sales", "price_to_sales_ratio"])
    piotroski = _latest_col(ratios_df, ["piotroski_score", "piotroski"])
    altman    = _latest_col(ratios_df, ["altman_z_score", "altman"])

    # --- EV/EBIT ---
    oi_col = _find_col(income_df, ["operating_income", "operatingIncome"])
    ev_col = _find_col(ratios_df, ["enterprise_value", "enterpriseValue"])
    ev_val = _latest_col(ratios_df, ["enterprise_value", "enterpriseValue"])
    ev_ebit = float("nan")
    if oi_col and not np.isnan(ev_val):
        oi_v = income_df[oi_col].dropna().iloc[-1]
        ev_ebit = float(ev_val / oi_v) if oi_v != 0 else float("nan")

    # --- Price-to-Gross-Profit ---
    gp_col     = _find_col(income_df, ["gross_profit", "grossProfit"])
    shares_col = _find_col(income_df, ["shares_outstanding", "weighted_average_diluted_shares_outstanding"])
    p_gross    = float("nan")
    if gp_col and shares_col:
        gp_v = income_df[gp_col].dropna().iloc[-1]
        sh_v = income_df[shares_col].dropna().iloc[-1]
        if gp_v != 0 and sh_v > 0:
            mktcap_v = current_price * sh_v
            p_gross  = float(mktcap_v / gp_v)

    # --- Earnings Yield ---
    eps_col = _find_col(income_df, ["eps_diluted", "eps", "basic_earnings_per_share"])
    earnings_yield = float("nan")
    if eps_col:
        eps_v = income_df[eps_col].dropna().iloc[-1]
        if current_price > 0 and not np.isnan(eps_v):
            earnings_yield = float(eps_v / current_price)

    multiples_df = pd.DataFrame([{
        "price":          current_price,
        "pe":             pe,
        "ev_ebitda":      ev_ebitda,
        "ev_ebit":        ev_ebit,
        "p_fcf":          p_fcf,
        "p_s":            p_s,
        "p_gross_profit": p_gross,
        "earnings_yield": earnings_yield,
        "piotroski":      piotroski,
        "altman_z":       altman,
    }])

    # --- DCF ---
    fcf_col  = _find_col(cash_df, ["free_cash_flow", "freeCashFlow"])
    wacc     = _latest_col(ratios_df, ["wacc", "weighted_average_cost_of_capital"])
    if np.isnan(wacc) or wacc <= 0:
        # Fallback: flat 9 % (pre-A4b) unless use_sector_wacc flag is on AND
        # we have a p1 to read the sector from.  Live-provider wacc always
        # wins over this fallback — this branch only fires when ratios_df.wacc
        # is missing (bead OpenBBTechnical-0h2.7).
        if cfg.feature_flags.use_sector_wacc and p1 is not None:
            wacc = _sector_wacc_default(p1.sector)
        else:
            wacc = 0.09

    fcf0   = float("nan")
    if fcf_col:
        fcf_v = cash_df[fcf_col].dropna()
        if not fcf_v.empty:
            fcf0 = float(fcf_v.iloc[-1])

    shares_out = float("nan")
    if shares_col:
        sv = income_df[shares_col].dropna()
        if not sv.empty:
            shares_out = float(sv.iloc[-1])
    if np.isnan(shares_out) or shares_out <= 0:
        # Fallback: market cap / price
        try:
            shares_out = float(_latest_col(p2.metrics_df if hasattr(p2, "metrics_df") else pd.DataFrame(),
                                            ["shares_outstanding"], default=float("nan")))
        except Exception:  # noqa: BLE001
            shares_out = float("nan")

    # Revenue CAGR as g_short proxy
    rev_col   = _find_col(income_df, ["revenue", "total_revenue"])
    g_short   = _cagr(income_df[rev_col], 5) if rev_col else 0.05
    if np.isnan(g_short) or g_short < -0.10:
        g_short = 0.05
    g_short   = min(g_short, 0.25)  # cap heroic growth
    g_term    = 0.025

    dcf_fair_value = float("nan")
    margin_of_safety = float("nan")
    sensitivity_df = pd.DataFrame()
    implied_growth = float("nan")

    # Pick DCF model per AnalysisFeatureFlags.use_two_stage_dcf (bead 0h2.6).
    # Default False -> _dcf_single (single-stage Gordon, pre-A4a behavior).
    # True -> _dcf_two_stage (5Y explicit -> 8Y fade -> terminal).  Routing
    # via a local dcf_fn ensures fair value, sensitivity, and reverse-DCF
    # all use the SAME model — no silent inconsistency between them.
    dcf_fn = _dcf_two_stage if cfg.feature_flags.use_two_stage_dcf else _dcf_single

    if not np.isnan(fcf0) and fcf0 > 0 and not np.isnan(shares_out) and shares_out > 0:
        dcf_fair_value = dcf_fn(fcf0, g_short, g_term, wacc, shares_out)
        if not np.isnan(dcf_fair_value) and dcf_fair_value > 0:
            margin_of_safety = (dcf_fair_value - current_price) / dcf_fair_value
        sensitivity_df = _dcf_sensitivity(fcf0, g_short, wacc, g_term, shares_out, dcf_fn=dcf_fn)
        # Reverse-DCF
        try:
            implied_growth = brentq(
                lambda g: dcf_fn(fcf0, g, g_term, wacc, shares_out) - current_price,
                -0.10, 0.30,
                xtol=1e-6,
            )
        except Exception:  # noqa: BLE001
            pass

    # --- ROIC - WACC Spread ---
    roic_val = _latest_col(ratios_df, ["roic", "return_on_invested_capital"])
    roic_wacc_spread = float(roic_val - wacc) if not np.isnan(roic_val) else float("nan")

    # --- PEG ratio (bead OpenBBTechnical-0h2.8) ---
    # PEG = PE / (revenue CAGR × 100).  Peter Lynch's classic:
    #   < 1.0 = cheap (growth outpaces earnings multiple)
    #   > 2.0 = expensive (paying too much for the growth)
    # Undefined when growth is <= 0 or PE is missing; return NaN in that case.
    # NB: uses the RAW revenue CAGR, not the DCF-floored g_short (which
    # gets bumped to 5 % for declining-revenue names to keep the DCF
    # sensible).  For PEG we want the honest growth signal.
    peg_ratio = float("nan")
    raw_cagr = _cagr(income_df[rev_col], 5) if rev_col else float("nan")
    if not np.isnan(pe) and pe > 0 and not np.isnan(raw_cagr) and raw_cagr > 0:
        peg_ratio = float(pe / (raw_cagr * 100))

    # --- Valuation verdict ---
    mos = margin_of_safety if not np.isnan(margin_of_safety) else 0.0
    if mos >= 0.15:
        valuation_verdict = "Undervalued"
    elif mos >= -0.05:
        valuation_verdict = "Fair Value"
    else:
        valuation_verdict = "Overvalued"

    # PEG tightens ONLY the Fair Value verdict — the ambiguous middle case.
    # Strong DCF signals (Undervalued/Overvalued) are not overwritten;
    # DCF-first is the design intent per bead 0h2.8 (add peg_ratio to P4).
    #
    # Gated behind use_peg_tightening (default False) because a Fair→Overvalued
    # flip flows through gate_passed = valuation_verdict in {Undervalued, Fair
    # Value} — a firm decision shift.  PR #304 review C1/I1 caught this as an
    # unflagged behavior change; bead OpenBBTechnical-0h2.35 tracks the fix.
    #
    # When the flag is on but peg_ratio is NaN (declining revenue or missing
    # PE), we surface a diagnostic in peg_note so the user knows their opt-in
    # was silently skipped for THIS symbol.  Bead OpenBBTechnical-0h2.39.
    peg_note = ""
    # bd-3xq.6 (QC-F) fix: track whether PEG *actually* tightened the verdict.
    # The flag-ON verdict-keyed entry_rec branch is now gated on this bool
    # instead of use_peg_tightening alone, so opting into PEG tightening no
    # longer silently swaps the entry_rec ladder from raw-mos to verdict-
    # keyed on stocks where PEG lands in [1.0, 2.0]. The pre-fix asymmetry
    # was: flag OFF gave 'Avoid' on mos in [-0.05, 0), flag ON gave
    # 'Opportunistic Entry' on the same stock — the flag name ('PEG
    # tightening') implied PEG-related changes only, but the effect was
    # unconditionally re-keying the entry ladder.
    peg_tightened_verdict = False
    if cfg.feature_flags.use_peg_tightening and valuation_verdict == "Fair Value":
        if np.isnan(peg_ratio):
            peg_note = " (PEG unavailable — tightening skipped)"
            logger.info(
                "use_peg_tightening=True for %s but peg_ratio is NaN "
                "(growth<=0 or PE missing); tightening skipped",
                cfg.symbol,
            )
        elif peg_ratio < 1.0:
            valuation_verdict = "Undervalued"
            peg_note = f" (PEG {peg_ratio:.2f} < 1.0 → cheap growth)"
            peg_tightened_verdict = True
        elif peg_ratio > 2.0:
            valuation_verdict = "Overvalued"
            peg_note = f" (PEG {peg_ratio:.2f} > 2.0 → expensive growth)"
            peg_tightened_verdict = True

    # Combined valuation-technical entry recommendation.
    #
    # Three cases, chosen for strict default-off parity AND to prevent the
    # bd-3xq.6 (QC-F) asymmetry:
    #
    # * Flag OFF (default): use the pre-A5 raw-mos cascade unchanged.  This
    #   is bit-for-bit what pre-A5 produced.  MOS-based decisions like
    #   'mos < 0 → Avoid' carry through even when they slightly disagree
    #   with the DCF-only valuation_verdict.
    #
    # * Flag ON AND PEG actually tightened (peg_tightened_verdict=True):
    #   key on the (post-tightening) valuation_verdict.  Needed for
    #   coherence — bead OpenBBTechnical-0h2.36 (entry_rec coherence).
    #   The PEG Fair Value → Overvalued flip must flow into entry_rec too,
    #   otherwise Phase4Result would say verdict=Overvalued AND
    #   entry_rec=Opportunistic Entry, a silent incoherence.
    #
    # * Flag ON but PEG did NOT tighten (verdict still Fair Value OR PEG
    #   NaN): fall back to the raw-mos cascade. This is the bd-3xq.6 fix.
    #   Previously (iter-4) this branch also ran the verdict-keyed ladder,
    #   which silently changed entry_rec vs flag-OFF for the same stock
    #   when PEG landed in the moderate [1.0, 2.0] band. The flag-name
    #   contract is now: "PEG tightening" only affects entry_rec when PEG
    #   actually tightens something.
    #
    # Iter-3 initially made the verdict-keyed branch unconditional, which
    # silently changed default-off behavior for mos in [-0.05, 0) (they
    # used to hit 'Avoid' via mos<0, now hit 'Opportunistic Entry' /
    # 'Watchlist').  QC-A (bead OpenBBTechnical-3xq.1) caught it as a
    # regression in the fix itself; iter-4 restored parity by gating on
    # use_peg_tightening. QC-F (bead OpenBBTechnical-3xq.6) then found
    # iter-4's gating still applied unconditionally within flag-ON —
    # this final gate on peg_tightened_verdict is the semantic fix.
    bull = p3.bullish_count
    if peg_tightened_verdict:
        # Verdict-keyed branch: needed for coherence when PEG tightens verdict
        if valuation_verdict == "Overvalued":
            entry_rec = "Avoid — overvalued regardless of technicals"
        elif valuation_verdict == "Undervalued":
            # Within Undervalued, bullish_count refines the wording.
            if bull >= 6:
                entry_rec = "Strong Entry — value and timing aligned"
            elif bull >= 3:
                entry_rec = "Partial Entry — fundamental case strong; wait for technical improvement"
            else:
                entry_rec = "Wait — cheap but technically broken"
        else:  # "Fair Value" — should not happen when peg_tightened_verdict=True
            # Defensive fallback: assign a neutral entry_rec. In practice
            # this branch is unreachable — peg_tightened_verdict is only
            # set True after valuation_verdict was flipped to Undervalued
            # or Overvalued (never Fair Value). Kept as a safety net for
            # a future refactor that accidentally sets the flag without
            # flipping the verdict.
            entry_rec = "Watchlist — no asymmetric opportunity"
    else:
        # Flag OFF, OR flag ON but PEG did not tighten:
        # Pre-A5 raw-mos cascade — preserved bit-for-bit for default-off parity.
        if mos >= 0.15 and bull >= 6:
            entry_rec = "Strong Entry — value and timing aligned"
        elif mos >= 0.15 and bull >= 3:
            entry_rec = "Partial Entry — fundamental case strong; wait for technical improvement"
        elif mos >= 0.15 and bull < 3:
            entry_rec = "Wait — cheap but technically broken"
        elif 0.0 <= mos < 0.15 and bull >= 6:
            entry_rec = "Opportunistic Entry — fair value but strong technicals"
        elif mos < 0.0:
            entry_rec = "Avoid — overvalued regardless of technicals"
        else:
            entry_rec = "Watchlist — no asymmetric opportunity"

    gate_passed = (
        not np.isnan(margin_of_safety)
        and (np.isnan(altman) or altman > 1.81)
        and valuation_verdict in ("Undervalued", "Fair Value")
    )
    # peg_gate_str is gated on use_peg_tightening to preserve bit-for-bit
    # gate_notes parity when the flag is off — otherwise a user opting out
    # of PEG still sees the value in gate_notes and could reasonably infer
    # PEG was consulted. Bead OpenBBTechnical-0h2.38 (peg_gate_str leak).
    peg_gate_str = ""
    if cfg.feature_flags.use_peg_tightening and not np.isnan(peg_ratio):
        peg_gate_str = f" | PEG {peg_ratio:.2f}"
    gate_notes = (
        f"MOS {margin_of_safety:.1%} | {valuation_verdict}{peg_note} | "
        f"Altman Z {altman:.2f}{peg_gate_str} | {entry_rec}"
    )

    # --- 5Y Historical Multiple Trends ---
    hist_mult_cols = {
        "pe": ["price_earnings_ratio", "pe_ratio", "pe"],
        "ev_ebitda": ["enterprise_value_multiple", "ev_to_ebitda", "ev_ebitda"],
        "p_s": ["price_to_sales", "price_to_sales_ratio"],
        "p_fcf": ["price_to_free_cash_flow", "price_to_free_cash_flow_ratio"],
    }
    hist_rows = []
    for _, row in ratios_df.iterrows():
        entry = {}
        if "date" in ratios_df.columns:
            entry["date"] = row.get("date", None)
        for key, candidates in hist_mult_cols.items():
            val = float("nan")
            for cand in candidates:
                if cand in ratios_df.columns and not pd.isna(row.get(cand)):
                    val = float(row[cand])
                    break
            entry[key] = val
        hist_rows.append(entry)
    historical_multiples_df = pd.DataFrame(hist_rows)

    multiples_vs_median: dict[str, float] = {}
    for key in hist_mult_cols:
        if key in historical_multiples_df.columns:
            median_val = historical_multiples_df[key].dropna().median()
            current_val = multiples_df[key].iloc[0] if key in multiples_df.columns else pe if key == "pe" else float("nan")
            if key == "ev_ebitda":
                current_val = ev_ebitda
            elif key == "p_s":
                current_val = _latest_col(ratios_df, hist_mult_cols[key])
            elif key == "p_fcf":
                current_val = p_fcf
            elif key == "pe":
                current_val = pe
            if not np.isnan(median_val) and median_val != 0 and not np.isnan(current_val):
                multiples_vs_median[key] = float(current_val / median_val - 1)
            else:
                multiples_vs_median[key] = float("nan")

    return Phase4Result(
        multiples_df=multiples_df,
        dcf_fair_value=dcf_fair_value,
        margin_of_safety=margin_of_safety,
        sensitivity_df=sensitivity_df,
        implied_growth=implied_growth,
        roic_wacc_spread=roic_wacc_spread,
        peg_ratio=peg_ratio,
        piotroski=piotroski,
        altman=altman,
        valuation_verdict=valuation_verdict,
        entry_recommendation=entry_rec,
        historical_multiples_df=historical_multiples_df,
        multiples_vs_median=multiples_vs_median,
        gate_passed=gate_passed,
        gate_notes=gate_notes,
    )


# ---------------------------------------------------------------------------
# Phase 5: Risk Assessment & Portfolio Context
# ---------------------------------------------------------------------------


def phase5_risk(cfg: AnalysisConfig) -> Phase5Result:
    """Phase 5 — Comprehensive risk KPIs, position sizing, and portfolio fit.

    OpenBB endpoints used (all provider="fmp_cached"):
    - ``obb.equity.price.historical`` (symbol + benchmark SPY)

    Returns
    -------
    Phase5Result
    """
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError("openbb package not installed") from exc

    sym = cfg.symbol
    prv = cfg.provider
    rf  = cfg.risk_free_rate

    sym_df   = _to_df(obb.equity.price.historical(
        symbol=sym, start_date=cfg.start_technicals, end_date=cfg.end_date,
        interval="1d", provider=prv))
    bench_df = _to_df(obb.equity.price.historical(
        symbol=cfg.benchmark, start_date=cfg.start_technicals, end_date=cfg.end_date,
        interval="1d", provider=prv))

    sym_df.columns   = [c.lower() for c in sym_df.columns]
    bench_df.columns = [c.lower() for c in bench_df.columns]

    # Returns
    sym_ret   = sym_df["close"].pct_change().dropna()
    bench_ret = bench_df["close"].pct_change().dropna()

    # Align
    idx = sym_ret.index.intersection(bench_ret.index)
    sym_ret   = sym_ret.loc[idx]
    bench_ret = bench_ret.loc[idx]

    annual_ret = float(sym_ret.mean() * 252)
    annual_vol = float(sym_ret.std() * np.sqrt(252))

    # Sharpe
    sharpe = (annual_ret - rf) / annual_vol if annual_vol > 0 else float("nan")

    # Sortino
    downside_vol = float(sym_ret[sym_ret < 0].std() * np.sqrt(252))
    sortino = (annual_ret - rf) / downside_vol if downside_vol > 0 else float("nan")

    # Beta
    cov    = float(sym_ret.cov(bench_ret))
    var_b  = float(bench_ret.var())
    beta   = cov / var_b if var_b > 0 else float("nan")

    # Jensen's Alpha
    bench_ann_ret = float(bench_ret.mean() * 252)
    alpha = annual_ret - (rf + beta * (bench_ann_ret - rf)) if not np.isnan(beta) else float("nan")

    # Regime-conditional beta
    up_mask   = bench_ret > 0
    dn_mask   = bench_ret < 0
    beta_up   = float(sym_ret[up_mask].cov(bench_ret[up_mask]) / bench_ret[up_mask].var()) \
                if bench_ret[up_mask].var() > 0 else float("nan")
    beta_down = float(sym_ret[dn_mask].cov(bench_ret[dn_mask]) / bench_ret[dn_mask].var()) \
                if bench_ret[dn_mask].var() > 0 else float("nan")

    # VaR / CVaR (95%)
    var_95  = float(sym_ret.quantile(0.05))
    cvar_95 = float(sym_ret[sym_ret <= var_95].mean())

    # Max Drawdown & Ulcer Index
    equity_curve = (1 + sym_ret).cumprod()
    rolling_max  = equity_curve.cummax()
    drawdown_ser = (equity_curve / rolling_max) - 1
    max_drawdown = float(drawdown_ser.min())
    ulcer_index  = float(np.sqrt((drawdown_ser ** 2).mean()))

    # Distributional shape — fat-tail awareness (bead OpenBBTechnical-0h2.4).
    # Fisher's excess kurtosis (fisher=True is scipy default): 0 = normal,
    # positive = fatter tails than normal.  Skew: negative = left-tailed
    # (crashes worse than rallies).  Both operate on the same returns
    # series used for Sharpe/Sortino/etc — no new data fetch required.
    kurtosis_val = float(_scipy_kurtosis(sym_ret, fisher=True, bias=True))
    skewness_val = float(_scipy_skew(sym_ret, bias=True))

    # Volatility regime — 63-day rolling vol trend (bead OpenBBTechnical-0h2.5).
    # Recent vs. prior 63-day windows; ±10 % hysteresis prevents whipsaw.
    vol_63d_trend = _compute_vol_trend(sym_ret, window=63, threshold=0.10)

    # Calmar
    calmar = (annual_ret / abs(max_drawdown)) if max_drawdown != 0 else float("nan")

    # Gain-to-Pain
    gains  = float(sym_ret[sym_ret > 0].sum())
    pains  = float(sym_ret[sym_ret < 0].abs().sum())
    gain_to_pain = gains / pains if pains > 0 else float("nan")

    # Kelly criterion
    win_rate = float((sym_ret > 0).mean())
    avg_win  = float(sym_ret[sym_ret > 0].mean())
    avg_loss = float(sym_ret[sym_ret < 0].abs().mean())
    kelly_fraction = float("nan")
    if avg_loss > 0:
        rr = avg_win / avg_loss
        kelly_fraction = (win_rate * rr - (1 - win_rate)) / rr

    # Position sizing
    conviction_score_proxy = min(max(sharpe, 0), 5)  # repurposed as proxy
    conviction_size = max(0.01, min(0.01 + max(0.0, conviction_score_proxy - 2) * 0.01, cfg.max_portfolio_allocation))
    half_kelly_size = float("nan")
    if not np.isnan(kelly_fraction) and kelly_fraction > 0:
        half_kelly_size = 0.5 * kelly_fraction * cfg.max_portfolio_allocation

    recommended_size = float(min(
        v for v in [conviction_size, half_kelly_size] if not np.isnan(v)
    ))

    # Fundamental risk adjustments (applied externally after Phase 2 is known)
    # Computed here as notes only; caller applies them after having p2
    # (reduces coupling; Phase 7 can apply the final adjustments)

    # Portfolio fit
    core_candidate = (
        not np.isnan(sharpe)     and sharpe > 1.0
        and abs(max_drawdown)    < 0.35
        and not np.isnan(beta_down) and (np.isnan(beta_up) or beta_down <= beta_up * 1.2)
        and not np.isnan(calmar) and calmar > 0.8
    )
    reject = abs(max_drawdown) > 0.60 or (not np.isnan(cvar_95) and cvar_95 < -0.08)
    if reject:
        portfolio_fit = "Reject"
    elif core_candidate:
        portfolio_fit = "Core"
    else:
        portfolio_fit = "Satellite"

    # Stress scenarios (estimated)
    stress_scenarios = {
        "market_correction_20pct": float(-0.20 * (beta_down if not np.isnan(beta_down) else beta)),
        "rates_up_100bps":         float(-0.10),   # approximate sector-neutral estimate
        "sector_shock_30pct":      float(-0.30 * 0.85),  # assuming ~0.85 sector correlation
    }

    # Assemble KPI table
    risk_kpi_df = pd.DataFrame([{
        "sharpe":        round(sharpe, 4),
        "sortino":       round(sortino, 4),
        "jensen_alpha":  round(alpha, 4),
        "beta":          round(beta, 4),
        "beta_up":       round(beta_up, 4),
        "beta_down":     round(beta_down, 4),
        "calmar":        round(calmar, 4),
        "gain_to_pain":  round(gain_to_pain, 4),
        "var_95":        round(var_95, 4),
        "cvar_95":       round(cvar_95, 4),
        "max_drawdown":  round(max_drawdown, 4),
        "ulcer_index":   round(ulcer_index, 4),
        "kurtosis":      round(kurtosis_val, 4),
        "skewness":      round(skewness_val, 4),
        "vol_63d_trend": vol_63d_trend,
        "annual_return": round(annual_ret, 4),
        "annual_vol":    round(annual_vol, 4),
    }])

    gate_passed = portfolio_fit != "Reject"
    gate_notes  = (
        f"Portfolio fit: {portfolio_fit} | "
        f"Sharpe {sharpe:.2f} | MaxDD {max_drawdown:.1%} | "
        f"Rec. size {recommended_size:.1%}"
    )

    return Phase5Result(
        risk_kpi_df=risk_kpi_df,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        gain_to_pain=gain_to_pain,
        max_drawdown=max_drawdown,
        beta=beta,
        beta_up=beta_up,
        beta_down=beta_down,
        var_95=var_95,
        cvar_95=cvar_95,
        ulcer_index=ulcer_index,
        kurtosis=kurtosis_val,
        skewness=skewness_val,
        vol_63d_trend=vol_63d_trend,
        kelly_fraction=kelly_fraction,
        conviction_size=conviction_size,
        half_kelly_size=half_kelly_size,
        recommended_size=recommended_size,
        portfolio_fit=portfolio_fit,
        stress_scenarios=stress_scenarios,
        gate_passed=gate_passed,
        gate_notes=gate_notes,
    )


# ---------------------------------------------------------------------------
# Phase 6: Market Segment, ETF Benchmark & Peer Relative Analysis
# ---------------------------------------------------------------------------


def phase6_peer_relative(cfg: AnalysisConfig, p1: Phase1Result) -> Phase6Result:
    """Phase 6 — Peer relative analysis, Information Ratio, fundamental overlay.

    OpenBB endpoints used (all provider="fmp_cached"):
    - ``obb.equity.price.historical`` (universe: symbol + peers + sector ETF + SPY)
    - ``obb.equity.fundamental.metrics`` (per peer — for fundamental quality overlay)

    Returns
    -------
    Phase6Result
    """
    try:
        from openbb import obb
    except ImportError as exc:
        raise RuntimeError("openbb package not installed") from exc

    sym = cfg.symbol
    prv = cfg.provider
    rf  = cfg.risk_free_rate

    sector_etf_sym = _sector_etf(p1.sector)
    peers          = p1.peers[:8]   # cap at 8 for API efficiency
    universe       = [sym] + peers + [sector_etf_sym, "SPY"]
    universe       = list(dict.fromkeys(universe))  # deduplicate preserving order

    # Fetch prices for universe
    price_map: dict[str, pd.Series] = {}
    for ticker in universe:
        try:
            df = _to_df(obb.equity.price.historical(
                symbol=ticker,
                start_date=cfg.start_technicals,
                end_date=cfg.end_date,
                interval="1d",
                provider=prv,
            ))
            df.columns = [c.lower() for c in df.columns]
            if "close" in df.columns and not df.empty:
                price_map[ticker] = df["close"]
        except Exception:  # noqa: BLE001
            logger.warning("Failed to fetch price for %s", ticker)

    if sym not in price_map:
        raise RuntimeError(f"Could not fetch prices for target symbol {sym}")

    # Align all to common dates
    prices_df  = pd.DataFrame(price_map).dropna(how="all")
    returns_df = prices_df.pct_change().dropna(how="all")

    # Per-symbol annualised metrics
    rows = []
    for ticker in prices_df.columns:
        ret_s = returns_df[ticker].dropna()
        if ret_s.empty:
            continue
        ann_ret  = float(ret_s.mean() * 252)
        ann_vol  = float(ret_s.std()  * np.sqrt(252))
        sharpe   = (ann_ret - rf) / ann_vol if ann_vol > 0 else float("nan")
        dv       = float(ret_s[ret_s < 0].std() * np.sqrt(252))
        sortino  = (ann_ret - rf) / dv if dv > 0 else float("nan")
        eq_c     = (1 + ret_s).cumprod()
        mdd      = float((eq_c / eq_c.cummax() - 1).min())
        var95    = float(ret_s.quantile(0.05))
        cvar95   = float(ret_s[ret_s <= var95].mean())
        calmar   = ann_ret / abs(mdd) if mdd != 0 else float("nan")
        rows.append({
            "symbol":     ticker,
            "ann_return": ann_ret,
            "ann_vol":    ann_vol,
            "sharpe":     sharpe,
            "sortino":    sortino,
            "calmar":     calmar,
            "max_dd":     mdd,
            "var_95":     var95,
            "cvar_95":    cvar95,
        })
    relative_table = pd.DataFrame(rows).set_index("symbol")

    # Rolling 3-month (63-day) cumulative return.
    # PR #331 iter-2 (SEV-B) + iter-3 (MEDIUM-2): use module-level
    # _MIN_OBS_PER_WINDOW so this calculation and _compute_momentum_accel_63d
    # share the SAME peer universe. iter-2 shipped min_count=1 which was
    # asymmetric with the helper's min_count=42, breaking the "drift-zero"
    # property the docstring claims. iter-3 promoted the constant to module
    # scope and aligned both sites on 42.
    rolling_3m_rank = 50.0  # default
    if len(returns_df) >= 63:
        rolling_3m = returns_df.iloc[-63:].sum(min_count=_MIN_OBS_PER_WINDOW)
        relative_table["rolling_3m_return"] = rolling_3m.reindex(relative_table.index)
        rolling_3m_clean = rolling_3m.dropna()
        if sym in rolling_3m_clean.index and len(rolling_3m_clean) > 1:
            rolling_3m_rank = float(percentileofscore(
                rolling_3m_clean.tolist(), rolling_3m_clean[sym]
            ))

    # Momentum acceleration — Δ percentile-rank over the trailing 63d
    # (bead OpenBBTechnical-0h2.9, reviewer P6 rec).  Positive = climbing
    # the peer ladder, negative = falling.  Neutral 0.0 when < 126 rows.
    momentum_accel_63d = _compute_momentum_accel_63d(returns_df, sym)

    # Correlation matrix
    corr_matrix = returns_df.corr()

    # Information Ratio vs sector ETF
    information_ratio = float("nan")
    if sector_etf_sym in returns_df.columns and sym in returns_df.columns:
        active = returns_df[sym] - returns_df[sector_etf_sym]
        active = active.dropna()
        if len(active) > 10:
            ir_ann_excess = float(active.mean() * 252)
            te            = float(active.std() * np.sqrt(252))
            information_ratio = ir_ann_excess / te if te > 0 else float("nan")

    # --- Peer fundamental quality overlay ---
    peer_metrics_list = []
    for peer in peers:
        try:
            m = _to_df(obb.equity.fundamental.metrics(
                symbol=peer, period="annual", limit=1, provider=prv
            ))
            if not m.empty:
                m["symbol"] = peer
                peer_metrics_list.append(m.iloc[[0]])
        except Exception:  # noqa: BLE001
            pass

    peer_fundamental_df = (
        pd.concat(peer_metrics_list, ignore_index=True).set_index("symbol")
        if peer_metrics_list else pd.DataFrame()
    )

    # Target metrics for relative valuation
    target_metrics = _to_df(obb.equity.fundamental.metrics(
        symbol=sym, period="annual", limit=1, provider=prv
    ))
    target_pe   = _latest_col(target_metrics,   ["price_earnings_ratio",  "pe_ratio"])
    target_ev   = _latest_col(target_metrics,   ["ev_to_ebitda"])
    target_roic = _latest_col(target_metrics,   ["roic",  "return_on_invested_capital"])
    target_fcfm = _latest_col(target_metrics,   ["free_cash_flow_yield"])

    # Relative valuation score (0-100): low PE + high ROIC = best
    relative_valuation_score = 50.0   # default if no peer data
    if not peer_fundamental_df.empty:
        pe_col  = _find_col(peer_fundamental_df, ["pe_ratio", "price_earnings_ratio"])
        roic_col = _find_col(peer_fundamental_df, ["roic", "return_on_invested_capital"])
        if pe_col and not np.isnan(target_pe) and roic_col and not np.isnan(target_roic):
            pe_vals   = peer_fundamental_df[pe_col].dropna().tolist()
            roic_vals = peer_fundamental_df[roic_col].dropna().tolist()
            pe_rank   = percentileofscore(pe_vals,   target_pe)   if pe_vals   else 50.0
            roic_rank = percentileofscore(roic_vals, target_roic) if roic_vals else 50.0
            # Low PE percentile = cheap (invert), high ROIC = quality
            relative_valuation_score = (100 - pe_rank) * 0.5 + roic_rank * 0.5

    # --- 5-block relative scorecard ---
    relative_score = _score_relative(
        sym=sym,
        relative_table=relative_table,
        returns_df=returns_df,
        sector_etf_sym=sector_etf_sym,
        information_ratio=information_ratio,
        peer_fundamental_df=peer_fundamental_df,
        relative_valuation_score=relative_valuation_score,
        target_metrics=target_metrics,
    )

    gate_passed = relative_score >= 3.5
    gate_notes  = (
        f"Relative score {relative_score:.2f}/5.0 | "
        f"IR vs ETF {information_ratio:.2f} | "
        + ("ETF may be superior — consider passive alternative"
           if not np.isnan(information_ratio) and information_ratio < 0.0
           else "Active premium justified")
    )

    return Phase6Result(
        relative_table=relative_table,
        corr_matrix=corr_matrix,
        sector_etf=sector_etf_sym,
        information_ratio=information_ratio,
        relative_score=relative_score,
        peer_fundamental_df=peer_fundamental_df,
        relative_valuation_score=relative_valuation_score,
        rolling_3m_rank=rolling_3m_rank,
        momentum_accel_63d=momentum_accel_63d,
        gate_passed=gate_passed,
        gate_notes=gate_notes,
    )


def _score_relative(
    sym: str,
    relative_table: pd.DataFrame,
    returns_df: pd.DataFrame,
    sector_etf_sym: str,
    information_ratio: float,
    peer_fundamental_df: pd.DataFrame,
    relative_valuation_score: float,
    target_metrics: pd.DataFrame,
) -> float:
    """Compute 5-block relative scorecard (0-5 scale)."""
    scores: list[float] = []

    peer_syms = [s for s in relative_table.index if s not in (sym, sector_etf_sym, "SPY")]

    # Block 1: Return rank (20%)
    if "ann_return" in relative_table.columns and sym in relative_table.index:
        all_ret = relative_table["ann_return"].dropna()
        if len(all_ret) > 1:
            pct = percentileofscore(all_ret.tolist(), float(all_ret.get(sym, all_ret.median())))
            scores.append(1 + pct / 25)  # 0th → 1, 100th → 5
        else:
            scores.append(2.5)
    else:
        scores.append(2.5)

    # Block 2: Risk-adjusted rank — Sharpe (20%)
    if "sharpe" in relative_table.columns and sym in relative_table.index:
        sh_vals = relative_table["sharpe"].dropna()
        if len(sh_vals) > 1:
            pct = percentileofscore(sh_vals.tolist(), float(relative_table.loc[sym, "sharpe"]))
            scores.append(1 + pct / 25)
        else:
            scores.append(2.5)
    else:
        scores.append(2.5)

    # Block 3: Downside risk rank — MDD + CVaR (20%)
    if "max_dd" in relative_table.columns and sym in relative_table.index:
        dd_vals = relative_table["max_dd"].dropna()
        if len(dd_vals) > 1:
            # Lower MDD = better = higher percentile rank (invert)
            pct = 100 - percentileofscore(dd_vals.tolist(), float(relative_table.loc[sym, "max_dd"]))
            scores.append(1 + pct / 25)
        else:
            scores.append(2.5)
    else:
        scores.append(2.5)

    # Block 4: Consistency (20%) — % rolling 30D windows target beats ETF
    consistency_score = 2.5
    if sector_etf_sym in returns_df.columns and sym in returns_df.columns:
        active = returns_df[sym] - returns_df[sector_etf_sym]
        window_results = [
            float(active.iloc[i:i+30].sum()) > 0
            for i in range(0, max(1, len(active) - 30), 5)
        ]
        if window_results:
            win_pct = sum(window_results) / len(window_results)
            consistency_score = 1 + win_pct * 4
    scores.append(consistency_score)

    # Block 5: Relative fundamental quality (20%)
    fund_score = 1 + relative_valuation_score / 25  # 0-100 → 1-5
    scores.append(min(fund_score, 5.0))

    weights = [0.20, 0.20, 0.20, 0.20, 0.20]
    return round(float(sum(s * w for s, w in zip(scores, weights))), 3)


# ---------------------------------------------------------------------------
# Phase 7: Decision, Execution & Monitoring
# ---------------------------------------------------------------------------


def phase7_decision(
    cfg: AnalysisConfig,
    p1: Phase1Result,
    p2: Phase2Result,
    p3: Phase3Result,
    p4: Phase4Result,
    p5: Phase5Result,
    p6: Phase6Result,
    *,
    regime: Any = None,
) -> Phase7Result:
    """Phase 7 — Composite score, action label, execution plan, monitoring triggers.

    No new API calls — uses prior phase results only.

    Parameters
    ----------
    regime : MarketRegime | None, keyword-only
        Current market regime (bd-0h2.14 / B2). When
        ``cfg.feature_flags.use_regime_input`` is True and this is a
        concrete regime (not None, not ``MarketRegime.UNKNOWN``), the
        composite-weight table shifts (BULL biases toward technicals,
        CRISIS biases toward risk_fit) and the staged_entry tranches
        scale by the regime multiplier (BEAR halves, CRISIS zeros).

        When the flag is on but ``regime`` is ``None`` or ``UNKNOWN``,
        the function emits a WARNING and falls back to the default
        weight table + no tranche scaling (R7.3 loud-empty).

        When the flag is off, this parameter is ignored (still recorded
        on ``Phase7Result.regime`` for audit trail).

    Returns
    -------
    Phase7Result
    """
    # --- Raw block scores ---
    tech_raw = p3.bullish_count / len(p3.signals) * 5

    scores: dict[str, float] = {
        "business_quality": _score_phase1(p1),
        "fundamentals":     p2.score,
        "technicals":       tech_raw,
        "valuation":        _score_phase4(p4),
        "risk_fit":         _score_phase5(p5),
        "peer_relative":    p6.relative_score,
    }

    # bd-0h2.14 / B2 — regime-adjusted composite weights. Default table
    # applies unless use_regime_input is True AND a concrete regime is
    # supplied. Loud-empty (R7.3) on flag-on-but-degenerate-regime:
    # WARNING + fall back to default so ops can distinguish "regime
    # feature disabled" from "regime detector returned nothing usable".
    from openbb_regime import MarketRegime as _MarketRegime  # local to avoid top-level cycle
    if cfg.feature_flags.use_regime_input:
        if regime is None:
            logger.warning(
                "phase7_decision: use_regime_input=True but regime input "
                "is None — falling back to default composite weights + "
                "no tranche scaling. Caller should supply a concrete "
                "MarketRegime (or pass regime=MarketRegime.UNKNOWN "
                "explicitly to acknowledge the degraded state)."
            )
            weights = _regime_weights(_MarketRegime.UNKNOWN)
            _effective_regime_for_tranche = _MarketRegime.UNKNOWN
        elif regime == _MarketRegime.UNKNOWN:
            logger.warning(
                "phase7_decision: use_regime_input=True but regime is "
                "UNKNOWN (regime detector returned no confident "
                "classification) — falling back to default composite "
                "weights + no tranche scaling."
            )
            weights = _regime_weights(_MarketRegime.UNKNOWN)
            _effective_regime_for_tranche = _MarketRegime.UNKNOWN
        else:
            weights = _regime_weights(regime)
            _effective_regime_for_tranche = regime
    else:
        weights = dict(_DEFAULT_COMPOSITE_WEIGHTS)
        _effective_regime_for_tranche = _MarketRegime.UNKNOWN  # inert path

    composite = sum(scores[k] * weights[k] for k in weights)


    # --- Hard overrides ---
    hard_override: str | None = None

    # bd-29n fix: track the tightest cap applied so the weekly-trend
    # recompute below can reapply it. Prior code let the recompute
    # unconditionally overwrite `composite`, silently discarding earlier
    # min() caps — a distressed stock (Altman<1.81, cap 2.0) with
    # bearish weekly trend would carry a "forced Avoid" hard_override
    # label but a recomputed composite well above the 2.0 cap.
    #
    # INVARIANT (bd-29n / R7.11 reviewer NIT): every composite cap
    # below MUST update BOTH `composite` and `composite_cap` — the
    # weekly-trend recompute at the bottom of this block relies on
    # `composite_cap` to reapply the tightest cap post-recompute.
    # Adding a new cap without updating `composite_cap` silently
    # reintroduces bd-29n for that override. If you're adding a cap,
    # write the pair (`composite = min(...)` + `composite_cap = min(...)`).
    composite_cap: float = float("inf")   # inf = no cap applied yet

    altman = p4.altman
    if not np.isnan(altman) and altman < 1.81:
        composite = min(composite, 2.0)
        composite_cap = min(composite_cap, 2.0)
        hard_override = "Altman Z-Score < 1.81 — distress risk; forced Avoid"

    if not np.isnan(p2.accruals_ratio) and p2.accruals_ratio > 0.20:
        composite = min(composite, 2.8)
        composite_cap = min(composite_cap, 2.8)
        hard_override = (hard_override or "") + " | Accruals Ratio > 20% — capped at Hold/Watch"

    # Balance sheet safety cap
    bs_safety_score = scores.get("fundamentals", 2.5)  # proxy via fundamentals
    if p2.score >= 3.5 and (not np.isnan(p2.accruals_ratio) and p2.accruals_ratio > 0.10):
        composite = min(composite, 3.8)
        composite_cap = min(composite_cap, 3.8)
        hard_override = (hard_override or "") + " | Leverage quality cap applied (accruals > 10% with high P2 score)"

    # Earnings override
    earnings_note = ""
    if not p3.earnings_safe_window:
        scores["technicals"] = min(scores["technicals"], 2.5)
        earnings_note = "⚠ EARNINGS WITHIN 5 DAYS — defer entry"

    # Weekly trend override
    if not p3.weekly_trend_bullish:
        scores["technicals"] = min(scores["technicals"], 2.0)
        # Recompute composite with capped technicals — then REAPPLY the
        # composite_cap so an earlier Altman/accruals/BS-safety hard-
        # override still bites (bd-29n fix). Without the min(..., cap)
        # here, a distressed stock's composite would silently lift back
        # above the cap and the action_label cutoffs would give the
        # wrong label despite hard_override saying "forced Avoid".
        composite = min(sum(scores[k] * weights[k] for k in weights), composite_cap)
        hard_override = (hard_override or "") + " | Weekly trend bearish — technical score capped at 2.0"

    # Information Ratio override
    ir_note = ""
    if not np.isnan(p6.information_ratio) and p6.information_ratio < 0 and p6.relative_score < 3.0:
        ir_note = f"⚠ Consider ETF {p6.sector_etf} — stock underperforms benchmark on risk-adjusted basis (IR={p6.information_ratio:.2f})"

    action_label = _decision_label(composite)

    # --- Execution plan ---
    price = float(p3.price_df["close"].iloc[-1])
    # PR #343 iter-1 silent-hunt F3: guard against corrupted price feeds.
    # Negative price + use_stop_cap silently inverts the stop-cap arithmetic
    # (min(2*ATR, negative-cap) picks the negative, giving a stop ABOVE
    # entry). Fail loudly rather than emit a bad execution plan.
    assert price > 0, (
        f"phase7_decision: price must be positive, got {price!r} "
        f"(check p3.price_df['close'] for data corruption)"
    )
    atr   = p3.atr
    # bd-0h2.11 / A8 — stop cap: min(2*ATR, 5% * entry) prevents oversized
    # stops on high-vol stocks. Gated by AnalysisFeatureFlags.use_stop_cap
    # so default behavior is unchanged (2*ATR only). Per reviewer P7 rec.
    #
    # INVARIANT (iter-1 code-reviewer F1): 2*atr MUST remain the first
    # argument to min(). Python's built-in min is order-dependent for NaN:
    # `min(NaN, x)` returns NaN (propagates the failure downstream —
    # desired) but `min(x, NaN)` returns x (silently masks NaN ATR to
    # the cap — WRONG, would emit a bogus stop). Do not reorder.
    stop_distance = 2 * atr
    if cfg.feature_flags.use_stop_cap:
        capped = min(stop_distance, _STOP_CAP_PCT_OF_ENTRY * price)
        # iter-1 silent-hunt F2: log when the cap actually bites so ops
        # can distinguish a 5%-capped stop from a 2*ATR stop that happens
        # to equal the same value. INFO level (not WARNING) — a cap
        # firing is intended behavior, not degradation.
        if capped < stop_distance:
            logger.info(
                "phase7_decision: stop-cap fired (2*ATR=%.4f capped to "
                "%.1f%% * price=%.4f)",
                stop_distance,
                _STOP_CAP_PCT_OF_ENTRY * 100,
                capped,
            )
        stop_distance = capped
    stop  = price - stop_distance
    r     = price - stop
    t1    = price + r
    t2    = price + 2 * r
    t3    = price + 3 * r

    # bd-0h2.11 / A8 — trailing-stop protocol (populated as protocol
    # parameters for the execution layer; the Analysis pipeline itself
    # does not simulate trailing behavior). Empty dict when the flag is
    # off — preserves pre-A8 Phase7Result shape for existing consumers.
    #
    # iter-1 silent-hunt F1 (VERIFIED merge blocker): also force empty
    # when action_label == 'Avoid'. Without this, the pipeline emits a
    # full execution plan (staged_entry, stop, trailing rules) for a
    # stock it itself says to avoid — a downstream automated executor
    # reading trailing_stop_rules without cross-checking action_label
    # would open a position on a distressed stock. Mirroring the flag-
    # off semantics ("no protocol for a non-trade") makes the intent
    # explicit at the field level rather than requiring every consumer
    # to remember the cross-check.
    if cfg.feature_flags.use_trailing_stop and action_label != "Avoid":
        trailing_stop_rules = dict(_TRAILING_STOP_DEFAULTS)
    else:
        trailing_stop_rules = {}

    # Staged entry tranches based on entry quality
    mos = p4.margin_of_safety if not np.isnan(p4.margin_of_safety) else 0.0
    eq  = _entry_quality_label(mos, p3.bullish_count)

    tranche_map = {
        "High Conviction": {"tranche_1": 0.50, "tranche_2": 0.25, "tranche_3": 0.25},
        "Value Entry":     {"tranche_1": 0.33, "tranche_2": 0.33, "tranche_3": 0.34},
        "Momentum Entry":  {"tranche_1": 0.40, "tranche_2": 0.30, "tranche_3": 0.30},
        "Wait":            {"tranche_1": 0.00, "tranche_2": 0.00, "tranche_3": 0.00},
    }
    staged_entry = tranche_map.get(eq, tranche_map["Wait"])

    # bd-0h2.15 / B3 — regime-scaled tranche sizes. BULL/RANGING keep
    # full size; BEAR halves position; CRISIS zeros all tranches.
    # Applied ONLY when use_regime_input is True — flag-off path uses
    # the raw tranche_map to preserve pre-B3 behavior exactly.
    if cfg.feature_flags.use_regime_input:
        multiplier = _regime_tranche_multiplier()[_effective_regime_for_tranche]
        if multiplier != 1.0:
            staged_entry = {
                k: v * multiplier for k, v in staged_entry.items()
            }


    # Time stop — 63 calendar days from the analysis end date (last completed
    # trading day), not from today, so the window is anchored to the data.
    time_stop_date = (
        datetime.date.fromisoformat(cfg.end_date) + datetime.timedelta(days=63)
    ).isoformat()

    # Monitoring triggers
    monitoring_triggers: dict[str, Any] = {
        "revenue_miss_threshold":    -0.05,
        "gross_margin_decline":      -0.02,
        "dilution_12m":               0.03,
        "mos_negative":               0.00,
        "weekly_death_cross":         True,
        "peer_sharpe_rank_threshold": 0.50,
        "earnings_note":              earnings_note or "OK",
        "ir_note":                    ir_note or "OK",
    }

    handoff = _build_handoff(p1, p2, p3, p4, p5, p6, composite)

    return Phase7Result(
        composite_score=round(composite, 4),
        action_label=action_label,
        score_breakdown=scores,
        entry_quality=eq,
        atr_stop=round(stop, 4),
        risk_per_share=round(r, 4),
        target_1r=round(t1, 4),
        target_2r=round(t2, 4),
        target_3r=round(t3, 4),
        staged_entry=staged_entry,
        time_stop_date=time_stop_date,
        hard_override=hard_override,
        monitoring_triggers=monitoring_triggers,
        handoff=handoff,
        trailing_stop_rules=trailing_stop_rules,
        regime=regime,   # bd-0h2.14 / B2 — always recorded (audit trail)
    )


# ---------------------------------------------------------------------------
# Convenience: run full pipeline
# ---------------------------------------------------------------------------


def run_full_analysis(cfg: AnalysisConfig, *, regime: Any = None) -> dict[str, Any]:
    """Run all 7 phases in sequence and return a results dictionary.

    Parameters
    ----------
    cfg : AnalysisConfig
    regime : MarketRegime | None, keyword-only
        Current market regime (bd-0h2.14 / B2). When
        ``cfg.feature_flags.use_regime_input`` is True, this value is
        threaded into ``phase7_decision`` to select the composite-weight
        table and staged_entry multiplier. Downstream callers (CLI /
        REST router / Workspace widget) should fetch SPY + VIX daily
        bars and call ``openbb_regime.detect_market_regime()`` to
        compute this argument. When the flag is off, this value is
        ignored (still recorded on ``Phase7Result.regime`` for audit).

    Returns
    -------
    dict with keys 'p1' through 'p7', and optionally 'stopped_at' if
    ``cfg.enforce_gates`` is True and a phase gate fails.
    """

    def _gate_check(phase_name: str, result: Any, results: dict) -> bool:
        """Return True if gate failed and pipeline should stop."""
        if cfg.enforce_gates and hasattr(result, "gate_passed") and not result.gate_passed:
            logger.warning(
                "Gate FAILED at %s: %s — stopping pipeline",
                phase_name, getattr(result, "gate_notes", ""),
            )
            results["stopped_at"] = phase_name
            # Synthesize a P7 result indicating gate failure
            results["p7"] = Phase7Result(
                composite_score=0.0,
                action_label="Gate Failed",
                score_breakdown={},
                entry_quality="Wait",
                atr_stop=0.0,
                risk_per_share=0.0,
                target_1r=0.0,
                target_2r=0.0,
                target_3r=0.0,
                staged_entry={"tranche_1": 0.0, "tranche_2": 0.0, "tranche_3": 0.0},
                time_stop_date=cfg.end_date,
                hard_override=f"Pipeline stopped at {phase_name}: {getattr(result, 'gate_notes', '')}",
                monitoring_triggers={},
                handoff={"stopped_at": phase_name},
                # PR #343 iter-1 code-reviewer F2: explicit empty rules on
                # the gate-failure synth path. default_factory=dict would
                # also produce {} but being explicit here pins the intent
                # ("gate failed — no execution plan applies") for a future
                # reader who greps for trailing_stop_rules and expects to
                # find every construction site.
                trailing_stop_rules={},
                # PR #B2 iter-1 code-reviewer NIT: explicit UNKNOWN on
                # the synth path so the intent is pinned at the call
                # site (a gate-failure result never carries a real
                # regime). The __post_init__ would coerce None→UNKNOWN
                # anyway, but future-proof against the coercion being
                # removed as part of an F5 refactor.
                regime=_gate_check_unknown_regime(),
            )
            return True
        return False

    def _gate_check_unknown_regime():
        """Return MarketRegime.UNKNOWN; wraps the import so the gate-
        failure synth path doesn't force openbb_regime at module load.
        """
        from openbb_regime import MarketRegime
        return MarketRegime.UNKNOWN

    results: dict[str, Any] = {}

    logger.info("Phase 1 — Company Profile: %s", cfg.symbol)
    p1 = phase1_company_profile(cfg)
    results["p1"] = p1
    if _gate_check("p1", p1, results):
        return results

    logger.info("Phase 2 — Fundamentals")
    p2 = phase2_fundamentals(cfg)
    results["p2"] = p2
    if _gate_check("p2", p2, results):
        return results

    logger.info("Phase 3 — Technicals")
    p3 = phase3_technicals(cfg)
    results["p3"] = p3
    if _gate_check("p3", p3, results):
        return results

    logger.info("Phase 4 — Valuation")
    p4 = phase4_valuation(cfg, p2, p3, p1=p1)
    results["p4"] = p4
    if _gate_check("p4", p4, results):
        return results

    logger.info("Phase 5 — Risk")
    p5 = phase5_risk(cfg)
    results["p5"] = p5
    if _gate_check("p5", p5, results):
        return results

    logger.info("Phase 6 — Peer Relative")
    p6 = phase6_peer_relative(cfg, p1)
    results["p6"] = p6
    if _gate_check("p6", p6, results):
        return results

    logger.info("Phase 7 — Decision")
    # iter-1 pr-test HIGH F3: thread regime through so callers can enable
    # use_regime_input meaningfully. Without this the top-level entry
    # always hits the None→WARNING+fallback branch even when the flag
    # is on. Downstream (CLI, REST router in B4) fetches SPY+VIX and
    # calls openbb_regime.detect_market_regime() then passes the result.
    p7 = phase7_decision(cfg, p1, p2, p3, p4, p5, p6, regime=regime)
    results["p7"] = p7

    logger.info(
        "Analysis complete: %s — %s (score %.3f)",
        cfg.symbol, p7.action_label, p7.composite_score
    )

    return results
