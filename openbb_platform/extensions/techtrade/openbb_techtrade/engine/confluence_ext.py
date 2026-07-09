"""Extended-panel confluence vote emitters (bd-7ct.2, bd-m8n).

**Pass-through in bd-7ct.** Every function here delegates directly to
its classic twin in ``engine/confluence.py``, returning the same
``list[IndicatorVote]`` byte-identically. This proves the dispatcher
plumbing (bd-xim) works without introducing vote-mapping risk.

**Family PRs replace these stubs one family at a time** — see the
:mod:`openbb_techtrade.engine.indicators_ext` module docstring for
which indicators each family PR adds (and which the §10 expert review
dropped or reclassified before implementation).

The R1 acceptance gate — positive Information Coefficient on the
recorded basket, ``notebook 04 validate`` DSR delta ≥ 0, PBO-guarded —
must be cleared by every new vote before the family PR lands. See
:mod:`openbb_techtrade.engine.panel_eval` (bd-7ct.10) for the harness.

Full context:
- Design spec: docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md
- Foundation plan: docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md
"""

from __future__ import annotations

from typing import Literal

from openbb_techtrade.engine.confluence import (
    _volume_votes,
    momentum_votes,
    trend_votes,
    volatility_votes,
)
from openbb_techtrade.models import IndicatorPanel, IndicatorVote


def trend_votes_ext(
    panel: IndicatorPanel, *, adx_gate: float = 20.0
) -> list[IndicatorVote]:
    """Pass-through stub for the extended trend vote emitter (bd-7ct.2, bd-luy).

    Delegates to :func:`openbb_techtrade.engine.confluence.trend_votes`
    unchanged. Family PR **bd-luy** will replace this with vote mappers
    for Aroon oscillator, Ichimoku cloud position, and PSAR direction.
    ADX is being reclassified from a directional vote to a gate/confidence
    scaler per §10 C3 (it is a non-directional strength measure by
    Wilder's design; multiplying by ``sign(ema_cross)`` made it a scaled
    duplicate of the trend vote).
    """
    return trend_votes(panel, adx_gate=adx_gate)


def momentum_votes_ext(panel: IndicatorPanel) -> list[IndicatorVote]:
    """Pass-through stub for the extended momentum vote emitter (bd-7ct.2, bd-40v).

    Delegates to :func:`openbb_techtrade.engine.confluence.momentum_votes`
    unchanged. Family PR **bd-40v** will add ROC and CCI vote mappers
    (Williams %R and MACD signal-cross were dropped pre-implementation
    per §10 review — see :mod:`openbb_techtrade.engine.indicators_ext`).
    """
    return momentum_votes(panel)


def volatility_votes_ext(
    panel: IndicatorPanel, *, regime: Literal["trend", "range"] = "trend"
) -> list[IndicatorVote]:
    """Pass-through stub for the extended volatility vote emitter (bd-7ct.2, bd-z43).

    Delegates to :func:`openbb_techtrade.engine.confluence.volatility_votes`
    unchanged. Family PR **bd-z43** will add BB Bandwidth (regime detector)
    and Keltner channel position (ATR-normalized band position — a
    genuinely new signal vs BB %B). TTM Squeeze and Historical Volatility
    were reclassified as gates per §10 C3.

    The ``regime`` kwarg is forwarded so the dispatcher's replacement
    stays behavior-compatible for callers that pass ``regime="range"``.
    """
    return volatility_votes(panel, regime=regime)


def _volume_votes_ext(panel: IndicatorPanel) -> list[IndicatorVote]:
    """Pass-through stub for the extended volume vote emitter (bd-7ct.2, bd-alj).

    Delegates to :func:`openbb_techtrade.engine.confluence._volume_votes`
    unchanged. Family PR **bd-alj** will add MFI (Money Flow Index),
    A/D Line slope, and 20-day volume ratio — but is double-blocked by
    the foundation PR AND GitHub #75 (short-side multiplier inversion),
    because widening the volume family without #75 partially defeats the
    goal (bounded votes concentrate the multiplier mean near 1.0).

    Prefixed with an underscore to mirror the classic
    :func:`openbb_techtrade.engine.confluence._volume_votes` naming
    convention (volume is a multiplier, not an additive family vote —
    the underscore signals that internally-consumed status).
    """
    return _volume_votes(panel)
