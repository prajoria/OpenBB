"""Extended-panel indicator computation stubs (bd-7ct.2, bd-m8n).

**Pass-through in bd-7ct.** Every function here delegates directly to
its classic twin in ``engine/indicators.py``, returning the same dict
byte-identically. This proves the dispatcher plumbing (bd-nx3/ctt/xim)
works without introducing any indicator-selection risk.

**Family PRs replace these stubs one family at a time:**

- ``_compute_trend_ext`` → replaced by **bd-luy** (Aroon + Ichimoku + PSAR)
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
"""

from __future__ import annotations

from openbb_techtrade.engine.indicators import (
    IndicatorConfig,
    _compute_momentum,
    _compute_trend,
    _compute_volatility,
    _compute_volume,
)


def _compute_trend_ext(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Pass-through stub for the extended trend family (bd-7ct.2, bd-luy).

    Delegates to :func:`openbb_techtrade.engine.indicators._compute_trend`
    unchanged. Family PR **bd-luy** will replace this with the extended
    implementation adding Aroon (Up/Down/Osc), Ichimoku Cloud position,
    and Parabolic SAR direction — each gated on positive IC per R1.
    """
    return _compute_trend(df, config)


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
