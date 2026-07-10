"""Extended-panel indicator computation stubs (bd-7ct.2, bd-m8n).

**Pass-through in bd-7ct.** Every function here delegates directly to
its classic twin in ``engine/indicators.py``, returning the same dict
byte-identically. This proves the dispatcher plumbing (bd-nx3/ctt/xim)
works without introducing any indicator-selection risk.

**bd-luy update (Aroon shipped, Ichimoku pending):**
``_compute_trend_ext`` is no longer a pure pass-through — it adds Aroon
Up/Down/Osc keys on top of the classic trend keys. The other 3 family
functions remain pass-throughs pending bd-40v/z43/alj.

**Family PRs replace these stubs one family at a time:**

- ``_compute_trend_ext`` → **bd-luy in progress** (Aroon done, Ichimoku next).
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


def _compute_trend_ext(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Extended trend family: classic keys PLUS Aroon Up/Down/Osc.

    This is no longer a pass-through — bd-luy Step 1 (bd-b6k5) added
    Aroon to the extended trend panel. Family PR bd-luy Step 2
    (bd-7gwh) will add Ichimoku Cloud with 3-bar-confirmation
    positional signal.

    **Aroon** measures the recency of the 25-bar high and low; the
    oscillator (Up − Down) is bounded to [-100, +100]. Populates 3
    keys: ``aroon_up``, ``aroon_down``, ``aroon_osc``. Missing / NaN
    on histories < 25 bars — matches the existing ``_compute_trend``
    NaN-drop pattern (short-history callers just don't get the keys).

    Design decision D1 preserved: extended path is a SUPERSET of
    classic. Every classic key is still populated so subset-invariance
    (bd-7ct.8 golden AC) holds.
    """
    out = _compute_trend(df, config)

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

    return out


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
