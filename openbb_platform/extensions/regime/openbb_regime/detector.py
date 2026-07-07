"""Market regime detector — classifies the current market state.

Reviewer P7 recommendation Q-1 (bd-0h2.13): the Analysis pipeline's
composite scoring and position sizing should adapt to the current
market regime. A high-quality stock in a crisis regime should still be
avoided — the correlations go to 1.0 and every long trade bleeds. This
module provides the classifier; consumers (Analysis, techtrade, future)
adjust their behavior based on the returned :class:`MarketRegime`.

Classification logic
--------------------

Four regimes are distinguished by two signals:

1. **SPY trend vs 200d SMA** — is the market above or below its long-term
   trend? Below-and-falling is bearish; above-and-rising is bullish.
2. **VIX level** — is fear compressed (< 20 = complacent bull), moderate
   (20-30 = uncertain range), or elevated (> 30 = crisis)?

============= ============== =====================================
 SPY vs 200d   VIX level      Regime
============= ============== =====================================
 Above         < 20            ``TRENDING_BULL``
 Around (±3%)  20-30           ``RANGING``
 Below         < 30            ``TRENDING_BEAR``
 Below         >= 30           ``CRISIS``
============= ============== =====================================

Hysteresis
----------

A regime switch requires the new classification to persist for 3
consecutive trading days. This prevents whipsaw at the boundaries
(e.g. VIX at 30.1 on Monday, 29.9 on Tuesday, 30.5 on Wednesday would
NOT toggle CRISIS ↔ BEAR three times — the last-persisting regime holds
until 3 consecutive days confirm the change).

Golden fixtures
---------------

* March 2020 (COVID crash): SPY -34% from 200d, VIX peak > 80 → ``CRISIS``
* November 2020 (post-election rally): SPY +9% above 200d, VIX ~22 → after
  hysteresis settles, ``TRENDING_BULL``

Both are load-bearing regression anchors in the test suite. Any refactor
that changes the thresholds must re-verify these classify correctly.
"""

from __future__ import annotations

import logging
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification thresholds (module scope per R7.10 / bd-zuw pattern).
# Refactor implications: changing these changes the regime boundaries and
# should be paired with an update to the golden-fixture tests.
# ---------------------------------------------------------------------------
_SPY_TREND_LOOKBACK: int = 200        # 200-day SMA — standard long-term trend
_SPY_ABOVE_THRESHOLD_PCT: float = 0.03  # 3% above 200d = clearly "above"
_SPY_BELOW_THRESHOLD_PCT: float = -0.03  # 3% below 200d = clearly "below"
_VIX_LOW_THRESHOLD: float = 20.0      # < 20 = complacent bull
_VIX_HIGH_THRESHOLD: float = 30.0     # >= 30 = crisis / panic
_HYSTERESIS_DAYS: int = 3             # regime switch requires 3-day persistence
_MIN_HISTORY_DAYS: int = 200          # need at least 200 days for the SMA


class MarketRegime(str, Enum):
    """Coarse classification of current market state.

    Enum values are strings for cheap serialization (JSON / logs / REST).
    """

    TRENDING_BULL = "TRENDING_BULL"
    RANGING = "RANGING"
    TRENDING_BEAR = "TRENDING_BEAR"
    CRISIS = "CRISIS"
    UNKNOWN = "UNKNOWN"
    """Returned when input data is insufficient (< 200 days of SPY or missing
    columns) — distinguishes 'no data' from 'genuinely ranging'. R7.3 loud-
    empty pattern: emit a WARNING at each UNKNOWN branch so operators can
    tell why the classifier degraded."""


def _classify_raw(spy_close: float, spy_sma200: float, vix: float) -> MarketRegime:
    """Instantaneous classification without hysteresis (pure function).

    Encapsulates the threshold table so hysteresis logic can call it per
    day without duplicating the branch logic.
    """
    if spy_sma200 == 0 or np.isnan(spy_sma200):
        return MarketRegime.UNKNOWN
    spy_vs_sma = (spy_close - spy_sma200) / spy_sma200
    if np.isnan(vix) or np.isnan(spy_vs_sma):
        return MarketRegime.UNKNOWN

    # CRISIS takes precedence — high VIX regardless of trend means correlations
    # go to 1.0 and every long trade bleeds together.
    if spy_vs_sma <= _SPY_BELOW_THRESHOLD_PCT and vix >= _VIX_HIGH_THRESHOLD:
        return MarketRegime.CRISIS
    if spy_vs_sma >= _SPY_ABOVE_THRESHOLD_PCT and vix < _VIX_LOW_THRESHOLD:
        return MarketRegime.TRENDING_BULL
    if spy_vs_sma <= _SPY_BELOW_THRESHOLD_PCT:
        return MarketRegime.TRENDING_BEAR
    # In the middle — SPY around 200d, or VIX in the 20-30 zone — call it
    # RANGING. This is the "no clear directional edge" default.
    return MarketRegime.RANGING


def detect_market_regime(
    spy_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    *,
    as_of: pd.Timestamp | str | None = None,
) -> MarketRegime:
    """Classify the current market regime from SPY + VIX daily history.

    Parameters
    ----------
    spy_df : pd.DataFrame
        Daily SPY OHLCV with a ``close`` column and datetime index.
        Must have at least ``_MIN_HISTORY_DAYS`` rows for the 200d SMA.
    vix_df : pd.DataFrame
        Daily VIX with a ``close`` column and datetime index. Only the
        most recent ``_HYSTERESIS_DAYS + 1`` rows are consulted.
    as_of : pd.Timestamp | str | None, optional
        Snap the classification to this date; defaults to the last row.
        Useful for backtests + golden-fixture tests (Mar 2020, Nov 2020).

    Returns
    -------
    MarketRegime
        One of the enum values. ``UNKNOWN`` on insufficient / malformed
        input (emits a WARNING with the reason).

    Notes
    -----
    Hysteresis: a switch from the previous regime to a new one only
    fires if the new classification held for ``_HYSTERESIS_DAYS``
    consecutive trading days. This prevents whipsaw at threshold
    boundaries. The function itself is stateless — hysteresis is
    computed from the trailing window of SPY + VIX inputs each call.
    """
    # R7.3 loud-empty: each UNKNOWN branch says WHY so ops can distinguish
    # "no data" from "insufficient history" from "column missing".
    if spy_df is None or spy_df.empty:
        logger.warning(
            "detect_market_regime: spy_df is %s — returning UNKNOWN",
            "None" if spy_df is None else "empty",
        )
        return MarketRegime.UNKNOWN
    if vix_df is None or vix_df.empty:
        logger.warning(
            "detect_market_regime: vix_df is %s — returning UNKNOWN",
            "None" if vix_df is None else "empty",
        )
        return MarketRegime.UNKNOWN
    if "close" not in spy_df.columns or "close" not in vix_df.columns:
        logger.warning(
            "detect_market_regime: 'close' column missing "
            "(spy=%s, vix=%s) — returning UNKNOWN",
            "close" in spy_df.columns,
            "close" in vix_df.columns,
        )
        return MarketRegime.UNKNOWN
    if len(spy_df) < _MIN_HISTORY_DAYS:
        logger.warning(
            "detect_market_regime: spy_df has %d rows, need >= %d for the "
            "%dd SMA — returning UNKNOWN",
            len(spy_df), _MIN_HISTORY_DAYS, _SPY_TREND_LOOKBACK,
        )
        return MarketRegime.UNKNOWN

    # Slice to as_of if specified. Both dfs must be indexed on trading day.
    spy = spy_df.copy()
    vix = vix_df.copy()
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        spy = spy.loc[spy.index <= cutoff]
        vix = vix.loc[vix.index <= cutoff]
        if len(spy) < _MIN_HISTORY_DAYS:
            logger.warning(
                "detect_market_regime: after as_of=%s filter, spy_df has "
                "%d rows (< %d needed) — returning UNKNOWN",
                cutoff.isoformat(), len(spy), _MIN_HISTORY_DAYS,
            )
            return MarketRegime.UNKNOWN

    # Compute the trailing SMA and per-day classification for the
    # hysteresis window (last _HYSTERESIS_DAYS + 1 days).
    spy_sma = spy["close"].rolling(_SPY_TREND_LOOKBACK).mean()

    # Align SPY + VIX on the trailing window. If VIX has fewer aligned
    # rows than SPY (holiday mismatch, delayed close), degrade gracefully.
    window = _HYSTERESIS_DAYS + 1
    recent_dates = spy.index[-window:]
    aligned_vix = vix["close"].reindex(recent_dates)
    if aligned_vix.isna().sum() >= window:
        logger.warning(
            "detect_market_regime: VIX has no data aligned to the trailing "
            "%dd SPY window (all NaN) — returning UNKNOWN",
            window,
        )
        return MarketRegime.UNKNOWN

    # Per-day classification across the hysteresis window.
    daily_regimes: list[MarketRegime] = []
    for date in recent_dates:
        close = float(spy.loc[date, "close"])
        sma = float(spy_sma.loc[date]) if not np.isnan(spy_sma.loc[date]) else float("nan")
        vix_val = float(aligned_vix.loc[date]) if not np.isnan(aligned_vix.loc[date]) else float("nan")
        daily_regimes.append(_classify_raw(close, sma, vix_val))

    # Hysteresis: the "confirmed" regime is the LAST regime that held for
    # _HYSTERESIS_DAYS consecutive days. If nothing has held that long,
    # return the first (oldest) daily classification as the fallback —
    # this handles the initial-startup case.
    #
    # Read the tail backwards; the current regime is confirmed iff the
    # last _HYSTERESIS_DAYS daily classifications all match.
    latest = daily_regimes[-1]
    hysteresis_window = daily_regimes[-_HYSTERESIS_DAYS:]
    if len(set(hysteresis_window)) == 1:
        # All _HYSTERESIS_DAYS agree on the latest classification.
        return latest
    # Whipsaw: latest hasn't persisted. Fall back to the most recent
    # classification that DID hold for _HYSTERESIS_DAYS consecutive days,
    # walking backwards. If none, return the oldest observation
    # (approximates "the regime we were in before the whipsaw started").
    for i in range(len(daily_regimes) - _HYSTERESIS_DAYS, -1, -1):
        window_slice = daily_regimes[i : i + _HYSTERESIS_DAYS]
        if len(set(window_slice)) == 1:
            return window_slice[0]
    return daily_regimes[0]
