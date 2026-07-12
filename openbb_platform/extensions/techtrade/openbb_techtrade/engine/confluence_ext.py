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

#: Ship-config allowlist of extended trend votes emitted from ``trend_votes_ext``
#: when no explicit override is passed.
#:
#: **bd-hpxh decision (2026-07-11):** ``ichimoku_cloud`` is EXCLUDED from the
#: ship config. The bd-8332 decorrelation gate found |Spearman ρ| = 0.839
#: between ``ema_cross`` (classic trend vote) and ``ichimoku_cloud`` on the
#: 5-year basket — above the §R.4 M4 ceiling of 0.70. Two trend-direction
#: crossover votes agreeing 84% of the time would double-count evidence in
#: the composite score.
#:
#: **Panel keys still emit** — ``_compute_trend_ext`` populates
#: ``ichimoku_price_vs_cloud`` (raw) and ``ichimoku_confirmed_position``
#: (3-bar-confirmed) regardless of this allowlist. R&D notebooks and audit
#: code can read those keys directly; the allowlist only gates whether an
#: IndicatorVote is emitted into the composite-score input list.
#:
#: **Overriding**: callers pass ``enabled_extended_votes=`` to
#: :func:`trend_votes_ext` to opt Ichimoku (or any subset) back in for
#: R&D / IC studies / backtests. See docstring for use cases.
#:
#: **Re-adding to ship** requires resolving the ρ=0.839 violation first —
#: options: drop ``ema_cross`` from classic panel, reweight one of the
#: overlapping pair, widen the gate with documented rationale. Any of these
#: is a design-doc change under §R.4 M4.
SHIP_ENABLED_EXTENDED_TREND_VOTES: frozenset[str] = frozenset({"aroon_osc"})


def trend_votes_ext(
    panel: IndicatorPanel,
    *,
    adx_gate: float = 20.0,
    enabled_extended_votes: frozenset[str] | None = None,
) -> list[IndicatorVote]:
    """Extended trend votes: classic votes PLUS the enabled extended-vote subset.

    bd-luy Step 1 (bd-b6k5) added Aroon. Step 2 (bd-7gwh) added Ichimoku Cloud
    with 3-bar confirmation. bd-hpxh (2026-07-11) narrowed the SHIP-CONFIG
    subset to ``{"aroon_osc"}`` after the bd-8332 decorrelation gate found
    ``ichimoku_cloud`` at ρ=0.839 with ``ema_cross`` (see
    :data:`SHIP_ENABLED_EXTENDED_TREND_VOTES` for the full rationale).

    **Aroon vote formula** (per design spec §D5):

    ``sign(aroon_up - aroon_down) * min(1, |aroon_up - aroon_down|/100)``

    Since ``aroon_osc = aroon_up - aroon_down`` (both in [0, 100]), this
    simplifies to ``clip(aroon_osc / 100, -1, +1)``. Bounded in [-1, +1],
    direction-preserving, deterministic. Weight: family default.

    **Ichimoku Cloud vote** (only emitted when opted in via
    ``enabled_extended_votes``): reads ``ichimoku_confirmed_position``
    (NOT the raw ``ichimoku_price_vs_cloud``) — the confirmed key already
    embeds the 3-bar-confirmation buffer, so the vote formula is a
    trivial identity: the vote value equals the confirmed position.
    In {-1, 0, +1}; bounded, direction-preserving.

    **Absent panel key ⇒ no vote emitted** (graceful degrade on short
    histories; the caller's vote list is simply shorter, no None slot).

    Parameters
    ----------
    panel : IndicatorPanel
        The panel to derive votes from. ``panel.trend`` is expected to carry
        classic trend keys plus (optionally) extended-family keys.
    adx_gate : float, optional
        Forwarded to :func:`~openbb_techtrade.engine.confluence.trend_votes`
        for the classic votes. Defaults to 20.0.
    enabled_extended_votes : frozenset[str] | None, optional
        Override the ship-config allowlist of extended votes. Pass ``None``
        (default) to use :data:`SHIP_ENABLED_EXTENDED_TREND_VOTES`. Pass an
        explicit frozenset for R&D scenarios:

        - ``frozenset({"aroon_osc", "ichimoku_cloud"})`` — opt Ichimoku back
          in alongside Aroon (e.g. incremental-IC backtests)
        - ``frozenset({"ichimoku_cloud"})`` — isolate Ichimoku only
          (single-signal contribution studies)
        - ``frozenset()`` — extended path with ONLY classic votes (pure-
          classic baseline under PANEL_EXTENDED config, e.g. shadow-mode
          A/B comparisons)

        Panel-key emission is UNAFFECTED by this argument; only vote-list
        composition changes.
    """
    enabled = (
        enabled_extended_votes
        if enabled_extended_votes is not None
        else SHIP_ENABLED_EXTENDED_TREND_VOTES
    )

    votes = list(trend_votes(panel, adx_gate=adx_gate))

    if "aroon_osc" in enabled:
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

    if "ichimoku_cloud" in enabled:
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
