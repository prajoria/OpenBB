"""Extended-panel confluence vote emitters (bd-7ct.2, bd-m8n, bd-luy).

**Pass-through in bd-7ct.** Every function here delegates directly to
its classic twin in ``engine/confluence.py``, returning the same
``list[IndicatorVote]`` byte-identically. This proves the dispatcher
plumbing (bd-xim) works without introducing vote-mapping risk.

**bd-luy update (Aroon + Ichimoku shipped):**
``trend_votes_ext`` is no longer a pass-through — it emits the classic
votes PLUS an ``aroon_osc`` vote AND an ``ichimoku_cloud`` vote (when
the panel has each key). The other 3 family vote-mappers remain
pass-throughs pending bd-40v/z43/alj.

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
- bd-luy plan: docs/superpowers/plans/2026-07-09-bd-luy-trend-family-expansion.md
"""

from __future__ import annotations

from typing import Literal

from openbb_techtrade.engine.confluence import (
    DEFAULT_WEIGHTS,
    _volume_votes,
    momentum_votes,
    trend_votes,
    volatility_votes,
)
from openbb_techtrade.models import IndicatorPanel, IndicatorVote


def trend_votes_ext(
    panel: IndicatorPanel, *, adx_gate: float = 20.0
) -> list[IndicatorVote]:
    """Extended trend votes: classic votes PLUS aroon_osc PLUS ichimoku_cloud.

    bd-luy Step 1 (bd-b6k5) added Aroon. Step 2 (bd-7gwh, this commit)
    added Ichimoku Cloud with 3-bar confirmation.

    **Aroon vote formula** (per design spec §D5):

    ``sign(aroon_up - aroon_down) * min(1, |aroon_up - aroon_down|/100)``

    Since ``aroon_osc = aroon_up - aroon_down`` (both in [0, 100]), this
    simplifies to ``clip(aroon_osc / 100, -1, +1)``. Bounded in [-1, +1],
    direction-preserving, deterministic. Weight: family default.

    **Ichimoku Cloud vote:** reads ``ichimoku_confirmed_position`` (NOT
    the raw ``ichimoku_price_vs_cloud``) — the confirmed key already
    embeds the 3-bar-confirmation buffer, so the vote formula is a
    trivial identity: the vote value equals the confirmed position.
    In {-1, 0, +1}; bounded, direction-preserving.

    **Absent panel key ⇒ no vote emitted** (graceful degrade on short
    histories; the caller's vote list is simply shorter, no None slot).
    """
    votes = list(trend_votes(panel, adx_gate=adx_gate))

    aroon_osc = panel.trend.get("aroon_osc")
    if aroon_osc is not None:
        # aroon_osc ∈ [-100, +100]; vote ∈ [-1, +1]
        vote_value = max(-1.0, min(1.0, aroon_osc / 100.0))
        votes.append(
            IndicatorVote(
                family="trend",
                name="aroon_osc",
                vote=vote_value,
                weight=DEFAULT_WEIGHTS.trend,
            )
        )

    ichimoku_confirmed = panel.trend.get("ichimoku_confirmed_position")
    if ichimoku_confirmed is not None:
        # Confirmed position already in {-1, 0, +1}; clip defensively.
        vote_value = max(-1.0, min(1.0, float(ichimoku_confirmed)))
        votes.append(
            IndicatorVote(
                family="trend",
                name="ichimoku_cloud",
                vote=vote_value,
                weight=DEFAULT_WEIGHTS.trend,
            )
        )

    return votes


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
