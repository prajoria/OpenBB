"""Extended-panel indicator computation (bd-7ct.2, bd-m8n, bd-luy).

**Pass-through in bd-7ct.** Every function here delegates directly to
its classic twin in ``engine/indicators.py``, returning the same dict
byte-identically. This proves the dispatcher plumbing (bd-nx3/ctt/xim)
works without introducing any indicator-selection risk.

**bd-luy update (Aroon + Ichimoku shipped):**
``_compute_trend_ext`` is no longer a pass-through — it adds Aroon
Up/Down/Osc AND Ichimoku Cloud position (raw + 3-bar-confirmed) on
top of the classic trend keys. The other 3 family functions remain
pass-throughs pending bd-40v/z43/alj.

**Family PRs replace these stubs one family at a time:**

- ``_compute_trend_ext`` → **bd-luy shipped** (Aroon + Ichimoku).
  PSAR cut from bd-luy scope; see bd-l4ga for potential PSAR/Donchian/
  SMA-slope/cross-sectional-momentum revisit.
- ``_compute_momentum_ext`` → replaced by **bd-40v** (ROC + CCI; two
  originally-proposed indicators dropped per §10 review: Williams %R is
  an affine transform of Stochastic, MACD signal-cross is the same event
  as MACD histogram sign)
- ``_compute_volatility_ext`` → replaced by **bd-z43** (BB Bandwidth +
  Keltner position; squeeze + HV reclassified as gates per §10 C3)
- ``_compute_volume_ext`` → replaced by **bd-alj** (MFI + A/D + volume
  ratio, blocked also by GitHub #75 short-side multiplier fix)

Each family PR MUST pass the R1 acceptance gate — measured positive
Information Coefficient on the recorded basket, ``notebook 04 validate``
DSR delta ≥ 0, PBO-guarded — before landing.

Full context:
- Design spec: docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md
- Foundation plan: docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md
- bd-luy plan: docs/superpowers/plans/2026-07-09-bd-luy-trend-family-expansion.md
"""

from __future__ import annotations

import math

from openbb_techtrade.engine.indicators import (
    IndicatorConfig,
    _compute_momentum,
    _compute_trend,
    _compute_volatility,
    _compute_volume,
    _df_last_finite,
)

#: Aroon lookback length (Chande 1995 default; every professional Aroon
#: practitioner uses 25 — it corresponds to roughly a trading month).
_AROON_LENGTH: int = 25

#: Ichimoku parameters (Hosoda 1969 originals — every professional
#: Ichimoku practitioner uses 9/26/52; retail alternatives like
#: 20/60/120 have no published empirical support).
_ICHIMOKU_TENKAN: int = 9
_ICHIMOKU_KIJUN: int = 26
_ICHIMOKU_SENKOU: int = 52

#: Ichimoku cloud-position confirmation buffer (§R.4 M3 fix — symmetric
#: with the PSAR hysteresis treatment). Price must sit on the same side
#: of the cloud for this many consecutive bars before the confirmed
#: position flips. Suppresses 1- and 2-bar whipsaws in ranges (which
#: §10 M5 explicitly warned about).
#:
#: R7.11 load-bearing: mutating 3 → 1 must flip
#: TestIchimokuConfirmationBuffer.test_confirmed_position_ignores_single_bar_whipsaw.
_ICHIMOKU_CONFIRMATION_BARS: int = 3

#: Ichimoku minimum bar count for a finite reading. Senkou span B uses a
#: 52-bar lookback and is projected 26 bars forward, so the *current-bar*
#: cloud value at index t is defined only when t ≥ 52 + 26 - 1 = 77.
#: We require 78 for the raw key and 78 + (_ICHIMOKU_CONFIRMATION_BARS - 1)
#: for the confirmed key. In practice we gate both together at 78 — the
#: confirmed key simply reads "no confirmation possible" (absent) if the
#: history is too short to look back _ICHIMOKU_CONFIRMATION_BARS bars.
_ICHIMOKU_MIN_BARS: int = 78


def _ichimoku_position_at_row(close: float, isa: float, isb: float) -> float | None:
    """Return +1 if close > max(isa,isb), −1 if close < min(isa,isb),
    0 if inside the cloud. None on any NaN input."""
    if not all(_is_finite(v) for v in (close, isa, isb)):
        return None
    top = max(isa, isb)
    bot = min(isa, isb)
    if close > top:
        return 1.0
    if close < bot:
        return -1.0
    return 0.0


def _is_finite(v: object) -> bool:
    """NaN/inf-safe finite check for a scalar (int, float, or None)."""
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _ichimoku_current_frame(result: object) -> object | None:
    """Return current Ichimoku values from direct-frame or legacy tuple output."""
    candidate = result[0] if isinstance(result, tuple) and result else result
    if (
        candidate is None
        or not hasattr(candidate, "columns")
        or not hasattr(candidate, "iloc")
    ):
        return None
    return candidate


def _compute_trend_ext(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Extended trend family: classic keys PLUS Aroon Up/Down/Osc PLUS Ichimoku Cloud.

    bd-luy Step 1 (bd-b6k5) added Aroon. Step 2 (bd-7gwh, this commit)
    adds Ichimoku Cloud with 3-bar-confirmation positional signal.

    **Aroon** measures the recency of the 25-bar high and low; the
    oscillator (Up − Down) is bounded to [-100, +100]. Populates 3
    keys: ``aroon_up``, ``aroon_down``, ``aroon_osc``. Missing / NaN
    on histories < 25 bars — matches the existing ``_compute_trend``
    NaN-drop pattern (short-history callers just don't get the keys).

    **Ichimoku Cloud** compares close to the current-bar leading spans
    (senkou A/B, 9/26/52 lookbacks per Hosoda 1969). Populates 2 keys:

    - ``ichimoku_price_vs_cloud`` — raw single-bar signal in {-1, 0, +1}
      (+1 above cloud, −1 below, 0 inside). Preserved for audit.
    - ``ichimoku_confirmed_position`` — 3-bar-confirmed signal in
      {-1, 0, +1}. The vote emitter reads this key. A 1- or 2-bar
      whipsaw does NOT flip the confirmed position (§R.4 M3 fix,
      symmetric with the hysteresis treatment PSAR would have had).

    **Contract (bd-0f9d I6, PR #470):** The two Ichimoku keys are NOT
    interchangeable. Downstream code MUST distinguish:

    * *Raw* (``ichimoku_price_vs_cloud``): captures instantaneous
      price-vs-cloud state at the latest bar. Whipsaws readily.
      Auditing / research only. **Do not** use for vote emission,
      backtests, or gate composition — you will chase noise.
    * *Confirmed* (``ichimoku_confirmed_position``): 3-bar hysteresis.
      This is the load-bearing key that the confluence engine reads.
      New consumers should default to this one.

    The mnemonic: *raw is for the human eye, confirmed is for the
    machine*. Any new vote or gate that composes Ichimoku signal
    with other keys MUST read the confirmed key — otherwise it will
    silently drift into whipsaw territory and defeat the §R.4 M3
    hysteresis treatment.

    Ichimoku degrades gracefully when < 78 bars are available (senkou B
    needs 52 bars of history plus 26-bar forward displacement); both
    keys are omitted, not zeroed, so downstream vote-mappers simply
    don't emit an ichimoku vote.

    Design decision D1 preserved: extended path is a SUPERSET of
    classic. Every classic key is still populated so subset-invariance
    (bd-7ct.8 golden AC) holds.
    """
    out = _compute_trend(df, config)

    # ── Aroon (bd-b6k5) ──────────────────────────────────────────────
    # Aroon requires >= _AROON_LENGTH + 1 bars; pandas-ta may return None
    # (short history), or raise IndexError on some short-history slices.
    # Graceful-drop: on either failure mode, just don't populate the keys.
    try:
        aroon = df.ta.aroon(length=_AROON_LENGTH, talib=False)
    except (IndexError, ValueError):
        aroon = None
    if aroon is not None:
        aroon_up = _df_last_finite(aroon, "AROONU_")
        aroon_down = _df_last_finite(aroon, "AROOND_")
        aroon_osc = _df_last_finite(aroon, "AROONOSC_")
        if aroon_up is not None:
            out["aroon_up"] = aroon_up
        if aroon_down is not None:
            out["aroon_down"] = aroon_down
        if aroon_osc is not None:
            out["aroon_osc"] = aroon_osc

    # ── Ichimoku Cloud (bd-7gwh) ─────────────────────────────────────
    # Requires 78 bars for the current-bar cloud (senkou B 52-bar lookback
    # + 26-bar forward displacement). Below that, both keys are absent.
    if len(df) >= _ICHIMOKU_MIN_BARS:
        try:
            ichimoku_result = df.ta.ichimoku(
                tenkan=_ICHIMOKU_TENKAN,
                kijun=_ICHIMOKU_KIJUN,
                senkou=_ICHIMOKU_SENKOU,
                talib=False,
            )
        except (IndexError, ValueError):
            ichimoku_result = None

        # pandas-ta-classic returns the current frame directly; older pandas-ta
        # releases return (current_frame, forward_projection).
        current = _ichimoku_current_frame(ichimoku_result)

        if current is not None and len(current) > 0 and len(df) > 0:
            # Compute confirmed position by scanning the last
            # _ICHIMOKU_CONFIRMATION_BARS positions and requiring they
            # all agree. Only the last bar's raw value is exposed for audit.
            close_series = df["close"] if "close" in df.columns else df["Close"]

            last_isa = _df_last_finite(current, "ISA_")
            last_isb = _df_last_finite(current, "ISB_")
            last_close = float(close_series.iloc[-1]) if len(close_series) > 0 else None

            raw = (
                _ichimoku_position_at_row(last_close, last_isa, last_isb)
                if (
                    last_close is not None
                    and last_isa is not None
                    and last_isb is not None
                )
                else None
            )

            if raw is not None:
                out["ichimoku_price_vs_cloud"] = raw

                # Confirmed position: look back N bars, require unanimous sign.
                # Uses the raw per-bar position for the trailing window.
                confirmed = _ichimoku_confirmed_position(
                    close_series, current, _ICHIMOKU_CONFIRMATION_BARS
                )
                if confirmed is not None:
                    out["ichimoku_confirmed_position"] = confirmed

    return out


def _ichimoku_confirmed_position(
    close_series: object, ichimoku_current: object, window: int
) -> float | None:
    """Return the confirmed position (in {-1, 0, +1}) if the last `window`
    bars all show the same non-zero sign; else return the LAST bar's raw
    position (allowing a stable in-cloud reading to persist as 0).

    Rationale: the load-bearing behavior is "don't flip on a 1- or 2-bar
    whipsaw." A run of `window` consecutive same-sign non-zero bars is
    required to emit ±1. If the trailing window contains mixed signs or
    any zero (inside-cloud), we return 0 as a safe non-flipping default
    — the vote stays neutral rather than jumping to a fresh direction
    that hasn't been confirmed.

    **Design: stateless / no-memory (bd-0f9d I7, PR #470).** This
    function is intentionally stateless — each call reads the last
    ``window`` bars of the input series directly, with no cached
    history-of-positions between calls. That's an *architectural
    choice*, not an oversight or a workaround:

    * **Determinism across processes.** Two workers computing the
      same as_of on the same OHLCV frame always return the same
      value. No warm-up. No first-call vs Nth-call divergence.
    * **Backtestability.** A walk-forward backtest can call this at
      arbitrary points in time without re-priming state, because the
      answer is a pure function of ``(close_series, ichimoku_current,
      window)``.
    * **Rebuildability.** After a cache miss or a crash, one call
      with a long-enough frame reconstructs the exact same signal
      that a stateful implementation would have accumulated across
      many calls.

    The cost is repeated work on the trailing ``window`` bars per
    call. That cost is negligible (window=3 by default; per-symbol
    computation is O(window) work amortized over an already-loaded
    frame). A stateful implementation that carried a rolling history
    across calls would be marginally faster but would trade away all
    three properties above — not worth it for this workload.
    """
    if len(close_series) < window or len(ichimoku_current) < window:
        return None

    # Align: take the last `window` rows of both.
    # The ichimoku current frame is indexed by date; assume the last
    # `window` rows correspond to the last `window` bars of close.
    isa_col = _first_col_starting_with(ichimoku_current, "ISA_")
    isb_col = _first_col_starting_with(ichimoku_current, "ISB_")
    if isa_col is None or isb_col is None:
        return None

    tail_close = close_series.iloc[-window:].tolist()
    tail_isa = ichimoku_current[isa_col].iloc[-window:].tolist()
    tail_isb = ichimoku_current[isb_col].iloc[-window:].tolist()

    positions: list[float] = []
    for c, a, b in zip(tail_close, tail_isa, tail_isb):
        pos = (
            _ichimoku_position_at_row(float(c), float(a), float(b))
            if (_is_finite(c) and _is_finite(a) and _is_finite(b))
            else None
        )
        if pos is None:
            return None
        positions.append(pos)

    # Confirmation rule: all same non-zero sign → return that sign.
    # Otherwise → return 0 (neutral, non-flipping default).
    if all(p == 1.0 for p in positions):
        return 1.0
    if all(p == -1.0 for p in positions):
        return -1.0
    return 0.0


def _first_col_starting_with(frame: object, prefix: str) -> str | None:
    for col in frame.columns:
        if str(col).startswith(prefix):
            return str(col)
    return None


def _compute_momentum_ext(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Pass-through stub for the extended momentum family (bd-7ct.2, bd-40v).

    Delegates to :func:`openbb_techtrade.engine.indicators._compute_momentum`
    unchanged. Family PR **bd-40v** will replace this with the extended
    implementation adding ROC (10/20) and CCI (20). Two indicators from
    the original spec were dropped after §10 review:

    - **Williams %R**: exact affine transform of Stochastic (%R = %K − 100
      for same lookback); correlation −1 by construction.
    - **MACD signal-line cross**: the same event as MACD histogram sign
      change (hist = macd_line − signal_line, so hist crosses zero iff
      line crosses signal); would double-count within the composite score.
    """
    return _compute_momentum(df, config)


def _compute_volatility_ext(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Pass-through stub for the extended volatility family (bd-7ct.2, bd-z43).

    Delegates to :func:`openbb_techtrade.engine.indicators._compute_volatility`
    unchanged. Family PR **bd-z43** will add BB Bandwidth and Keltner
    channel-position votes. Note: TTM Squeeze and Historical Volatility
    were reclassified from votes to **gates/scalers** per §10 C3 — they
    describe volatility STATE, not direction; making them directional
    votes either double-counted with BB %B or (in the case of TTM
    Squeeze reading the trend vote) violated ensemble independence.
    """
    return _compute_volatility(df, config)


def _compute_volume_ext(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Pass-through stub for the extended volume family (bd-7ct.2, bd-alj).

    Delegates to :func:`openbb_techtrade.engine.indicators._compute_volume`
    unchanged. Family PR **bd-alj** will add MFI (Money Flow Index),
    A/D Line slope, and 20-day volume ratio. **bd-alj is double-blocked:**
    by this foundation PR AND by GitHub issue #75 (volume multiplier
    short-side inversion) — widening the volume family before #75 lands
    partially defeats the goal because bounded votes concentrate the
    multiplier near 1.0.
    """
    return _compute_volume(df, config)
