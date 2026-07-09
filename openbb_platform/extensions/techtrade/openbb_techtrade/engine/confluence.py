"""Weighted-confluence vote engine (issue #74, PRD §12, §20 Q4).

This is the brain of techtrade: it collapses a per-symbol :class:`IndicatorPanel`
(#72/#73) into a single, explainable directional call. Each indicator family maps
its readings to directional **votes** in ``[-1, +1]``; the three additive families
(trend / momentum / volatility) are fused into ``raw`` with the **Q4 weights**
(``trend 0.40``, ``momentum 0.25``, ``volatility 0.20``), and **volume ``0.15``
acts as a confirmation *multiplier*, never an additive vote** -- ``score =
clip(raw · volume_confirmation, -1, +1)``. Every vote that touched the score is
returned as an :class:`IndicatorVote` (family / name / vote / weight) so the
engine can always answer *"why long?"* and the votes fully reconcile the score.

The module is **pure and offline**: it depends only on
:mod:`openbb_techtrade.models`, never imports ``pandas`` / ``pandas_ta_classic`` /
``openbb`` / ``openbb_technical``, does no I/O, and holds no global state. All vote
math is closed-form and deterministic (no RNG), so identical ``(panel, weights)``
inputs yield byte-stable ``votes`` + ``score``. Missing panel keys (warm-up NaN
omitted upstream) simply drop that vote -- mirroring #72's omit-on-non-finite -- so
short-history symbols degrade gracefully rather than raising. Votes, weights, and
the score are all ``float`` per the engine-wide Decimal/float discipline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from openbb_techtrade.models import IndicatorPanel, IndicatorVote, MoverSignal


@dataclass(frozen=True)
class ConfluenceWeights:
    """Family weights for the composite score (PRD §12.2 / §20 Q4 — LOCKED).

    Mirrors the frozen :class:`~openbb_techtrade.engine.indicators.IndicatorConfig`
    pattern: immutable, hashable, and per-call overridable. The three additive
    families sum to ``0.85`` (volume is the multiplier, not an additive term), so
    reaching High conviction without volume confirmation requires near-unanimous
    families -- a deliberate "volume is needed for conviction" asymmetry.

    Parameters
    ----------
    trend : float
        Additive weight on the trend family (default ``0.40``).
    momentum : float
        Additive weight on the momentum family (default ``0.25``).
    volatility : float
        Additive weight on the volatility family (default ``0.20``).
    volume : float
        Amplitude of the volume confirmation multiplier (default ``0.15``); applied
        as ``1 + volume · mean(volume_votes)``, *not* as an additive family vote.
    """

    trend: float = 0.40
    momentum: float = 0.25
    volatility: float = 0.20
    volume: float = 0.15


#: The shipped Q4 default weights (un-tuned, honest baseline; #75 supplies presets).
DEFAULT_WEIGHTS = ConfluenceWeights()


def _clip(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into the closed interval ``[lo, hi]``.

    Parameters
    ----------
    value : float
        The value to clamp.
    lo, hi : float
        Inclusive lower and upper bounds.

    Returns
    -------
    float
        ``value`` bounded to ``[lo, hi]``.
    """
    return max(lo, min(hi, value))


def _sign(value: float) -> float:
    """Return the unit sign of ``value`` as a ``float`` (``-1.0`` / ``0.0`` / ``+1.0``).

    Distinct from :func:`openbb_techtrade.engine.indicators._sign` (which returns an
    ``int`` for candlestick flags): votes are ``float``, so this returns ``float``.

    Parameters
    ----------
    value : float
        The value to take the sign of.

    Returns
    -------
    float
        ``1.0`` if ``value > 0``, ``-1.0`` if ``value < 0``, else ``0.0``.
    """
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def _mean(values: Iterable[float]) -> float:
    """Return the arithmetic mean of ``values``, or ``0.0`` when empty.

    The empty-to-zero fold is what makes an absent family contribute ``0`` to
    ``raw`` (Q-C: present-only renormalization within a family, absent family left
    at zero) and an absent volume family yield a neutral ``1.0`` multiplier (Q-B).

    Parameters
    ----------
    values : Iterable[float]
        The values to average.

    Returns
    -------
    float
        The mean, or ``0.0`` if there are no values.
    """
    materialized = list(values)
    if not materialized:
        return 0.0
    return sum(materialized) / len(materialized)


def trend_votes(panel: IndicatorPanel, *, adx_gate: float = 20.0) -> list[IndicatorVote]:
    """Emit the trend-family votes: ADX-gated ``macd_hist`` and ``ema_cross`` (PRD §12.1).

    ``macd_hist`` votes its sign, damped by trend strength: full strength when
    ``adx > adx_gate`` (or ``adx`` absent), else scaled by ``clip(adx/adx_gate, 0, 1)``
    -- a smooth, cliff-free damp rather than a hard on/off gate. ``ema_cross`` votes
    ``+1`` on a golden cross (``> 0``) / ``-1`` on a death cross. ``ema_fast`` /
    ``ema_slow`` and ``adx`` are inputs/gates, **not** voters. Absent keys drop their
    vote.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.
    adx_gate : float, optional
        ADX level above which ``macd_hist`` votes at full strength (default ``20.0``).

    Returns
    -------
    list[IndicatorVote]
        Zero to two trend votes, each ``family="trend"``, ``weight=DEFAULT_WEIGHTS.trend``.
    """
    votes: list[IndicatorVote] = []
    trend = panel.trend

    if "macd_hist" in trend:
        adx = trend.get("adx")
        gate = 1.0 if (adx is None or adx > adx_gate) else _clip(adx / adx_gate, 0.0, 1.0)
        votes.append(
            IndicatorVote(
                family="trend",
                name="macd_hist",
                vote=_sign(trend["macd_hist"]) * gate,
                weight=DEFAULT_WEIGHTS.trend,
            )
        )

    if "ema_cross" in trend:
        votes.append(
            IndicatorVote(
                family="trend",
                name="ema_cross",
                vote=_sign(trend["ema_cross"]),
                weight=DEFAULT_WEIGHTS.trend,
            )
        )

    return votes


def momentum_votes(panel: IndicatorPanel) -> list[IndicatorVote]:
    """Emit the momentum-family votes: saturating ``rsi`` and the stoch K/D cross (PRD §12.1).

    ``rsi`` votes ``0`` in the ``[45, 55]`` deadband, ramps linearly to ``+1`` by
    ``70`` (and ``-1`` by ``30``), and saturates beyond. ``stoch`` is a single
    combined vote ``sign(stoch_k - stoch_d)`` (the K/D cross confirms sign), emitted
    only when **both** stoch keys are present. Absent keys drop their vote.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.

    Returns
    -------
    list[IndicatorVote]
        Zero to two momentum votes, each ``family="momentum"``,
        ``weight=DEFAULT_WEIGHTS.momentum``.
    """
    votes: list[IndicatorVote] = []
    momentum = panel.momentum

    if "rsi" in momentum:
        rsi = momentum["rsi"]
        if rsi >= 55.0:
            vote = _clip((rsi - 55.0) / 15.0, 0.0, 1.0)
        elif rsi <= 45.0:
            vote = -_clip((45.0 - rsi) / 15.0, 0.0, 1.0)
        else:
            vote = 0.0
        votes.append(
            IndicatorVote(family="momentum", name="rsi", vote=vote, weight=DEFAULT_WEIGHTS.momentum)
        )

    if "stoch_k" in momentum and "stoch_d" in momentum:
        votes.append(
            IndicatorVote(
                family="momentum",
                name="stoch",
                vote=_sign(momentum["stoch_k"] - momentum["stoch_d"]),
                weight=DEFAULT_WEIGHTS.momentum,
            )
        )

    return votes


def volatility_votes(
    panel: IndicatorPanel, *, regime: Literal["trend", "range"] = "trend"
) -> list[IndicatorVote]:
    """Emit the volatility-family vote: regime-aware Bollinger ``bb_pctb`` (PRD §12.1).

    In a **trend** regime, ``%B`` votes breakout-continuation: ``clip(2·(%B-0.5), -1, 1)``
    (``%B > 0.5`` → positive). In a **range** regime, the sign flips to mean-revert.
    ``regime`` is a parameter, not auto-detected here (the signals layer / #75 may
    pass an ADX-derived regime). ATR never votes (it sets stops in §13); the Keltner
    levels carry no ``close`` so they cannot form a directional vote. Absent
    ``bb_pctb`` drops the vote.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.
    regime : {"trend", "range"}, optional
        ``"trend"`` (default) → breakout-continuation; ``"range"`` → mean-revert flip.

    Returns
    -------
    list[IndicatorVote]
        Zero or one volatility vote, ``family="volatility"``,
        ``weight=DEFAULT_WEIGHTS.volatility``.
    """
    volatility = panel.volatility
    if "bb_pctb" not in volatility:
        return []

    base = _clip(2.0 * (volatility["bb_pctb"] - 0.5), -1.0, 1.0)
    vote = base if regime == "trend" else -base
    return [
        IndicatorVote(family="volatility", name="bb_pctb", vote=vote, weight=DEFAULT_WEIGHTS.volatility)
    ]


def _volume_votes(panel: IndicatorPanel) -> list[IndicatorVote]:
    """Emit the volume-family votes: sign of ``obv_slope`` and ``cmf`` (internal).

    These feed the confirmation multiplier (:func:`volume_confirmation`), not the
    additive sum, but are still returned as ``IndicatorVote``s so the multiplier is
    auditable in the final attribution. Absent keys drop their vote.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.

    Returns
    -------
    list[IndicatorVote]
        Zero to two volume votes, each ``family="volume"``,
        ``weight=DEFAULT_WEIGHTS.volume``.
    """
    votes: list[IndicatorVote] = []
    volume = panel.volume
    for name in ("obv_slope", "cmf"):
        if name in volume:
            votes.append(
                IndicatorVote(
                    family="volume", name=name, vote=_sign(volume[name]), weight=DEFAULT_WEIGHTS.volume
                )
            )
    return votes


def volume_confirmation(panel: IndicatorPanel) -> float:
    """Return the volume confirmation multiplier ``1 + 0.15·mean(volume_votes)`` (PRD §12.2, Q-B).

    A *signed* (not direction-aware) volume factor: positive volume votes raise
    the multiplier above ``1.0`` and negative votes pull it below, with absent
    volume neutral (``1.0``). With each vote in ``[-1, 1]`` and the Q4 amplitude
    ``DEFAULT_WEIGHTS.volume = 0.15``, the multiplier ranges ``[0.85, 1.15]``.

    Because :func:`composite_score` applies it as a plain ``raw · multiplier`` with
    **no ``sign(raw)`` term**, this faithfully confirms/damps *long* (``raw > 0``)
    signals -- bullish volume amplifies, bearish volume damps -- but is inverted for
    *short* (``raw < 0``) signals. The approved design (Q-B) specified the
    direction-aware ``1 + k·sign(raw)·vol_vote`` form; the locked pipeline contract
    simplified it to this signed multiplier (a no-sign ``-> float`` that takes no
    ``raw``/``weights`` arg). Reconciling the short-side behavior and the volume
    amplitude is deferred to #75, which owns preset reweighting.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.

    Returns
    -------
    float
        The multiplier in ``[0.85, 1.15]``; exactly ``1.0`` when no volume keys.
    """
    return 1.0 + DEFAULT_WEIGHTS.volume * _mean([v.vote for v in _volume_votes(panel)])


def composite_score(
    panel: IndicatorPanel, *, weights: ConfluenceWeights = DEFAULT_WEIGHTS,
    panel_config=None,
) -> tuple[float, list[IndicatorVote]]:
    """Fuse a panel into a composite ``score ∈ [-1, +1]`` plus its full vote attribution.

    Gathers the trend / momentum / volatility / volume votes and **re-stamps** the
    additive families' ``.weight`` with ``weights.<family>`` (so the attribution
    reflects the weights actually used in ``raw`` -- a no-op under ``DEFAULT_WEIGHTS``,
    correct for #75 presets). Volume votes keep the fixed amplitude actually applied
    by :func:`volume_confirmation` (``DEFAULT_WEIGHTS.volume``), so the returned votes
    reconcile the score for *any* ``weights``. Then computes::

        raw   = weights.trend·mean(trend) + weights.momentum·mean(momentum)
                + weights.volatility·mean(volatility)
        score = clip(raw · volume_confirmation(panel), -1, +1)

    Volume enters as the **multiplier** (:func:`volume_confirmation`), *not* as an
    additive family term, but its votes are included in the returned list for full
    "why long?" attribution. The votes fully reconcile the score.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.
    weights : ConfluenceWeights, optional
        Family weights. Defaults to :data:`DEFAULT_WEIGHTS` (Q4).

    Returns
    -------
    tuple[float, list[IndicatorVote]]
        The composite ``score`` and every contributing :class:`IndicatorVote`.
    """
    # bd-7ct.6 (bd-xim): panel_config dispatch. Resolved ONCE per call
    # (per design spec §D1). Lazy imports so environments that never opt
    # into the extended panel don't pull the _ext modules at import time.
    if panel_config is None:
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC  # noqa: PLC0415
        panel_config = PANEL_CLASSIC
    if panel_config.panel == "extended":
        from openbb_techtrade.engine import confluence_ext  # noqa: PLC0415
        raw_votes = (
            confluence_ext.trend_votes_ext(panel)
            + confluence_ext.momentum_votes_ext(panel)
            + confluence_ext.volatility_votes_ext(panel)
            + confluence_ext._volume_votes_ext(panel)
        )
    else:
        raw_votes = (
            trend_votes(panel)
            + momentum_votes(panel)
            + volatility_votes(panel)
            + _volume_votes(panel)
        )
    votes = [
        IndicatorVote(
            family=v.family,
            name=v.name,
            vote=v.vote,
            # Additive families carry the weight used in ``raw``; volume carries the
            # fixed amplitude ``volume_confirmation`` actually applies, so the votes
            # reconcile the score for any ``weights`` (not just DEFAULT_WEIGHTS).
            weight=DEFAULT_WEIGHTS.volume if v.family == "volume" else getattr(weights, v.family),
        )
        for v in raw_votes
    ]

    def _family_mean(family: str) -> float:
        return _mean([v.vote for v in votes if v.family == family])

    raw = (
        weights.trend * _family_mean("trend")
        + weights.momentum * _family_mean("momentum")
        + weights.volatility * _family_mean("volatility")
    )
    score = _clip(raw * volume_confirmation(panel), -1.0, 1.0)
    return score, votes


def direction_for(score: float, *, entry_threshold: float = 0.4) -> Literal["long", "short", "flat"]:
    """Bucket a composite ``score`` into a trade direction (PRD §12.2, L5).

    The threshold edges are inclusive: ``score == +entry_threshold`` → ``"long"``.

    Parameters
    ----------
    score : float
        The composite score in ``[-1, +1]``.
    entry_threshold : float, optional
        Minimum ``|score|`` to open a position (default ``0.4``, the
        ``EntryExitRule.entry_threshold`` default).

    Returns
    -------
    {"long", "short", "flat"}
        ``"long"`` if ``score >= +t``, ``"short"`` if ``score <= -t``, else ``"flat"``.
    """
    if score >= entry_threshold:
        return "long"
    if score <= -entry_threshold:
        return "short"
    return "flat"


def conviction_for(score: float) -> Literal["High", "Medium", "Low"]:
    """Bucket ``|score|`` into a conviction label (PRD §14.2, L7).

    Lower-inclusive edges: ``Medium = [0.4, 0.7)``, ``High = [0.7, 1]``.

    Parameters
    ----------
    score : float
        The composite score in ``[-1, +1]``.

    Returns
    -------
    {"High", "Medium", "Low"}
        ``"High"`` if ``|score| >= 0.7``, ``"Medium"`` if ``>= 0.4``, else ``"Low"``.
    """
    magnitude = abs(score)
    if magnitude >= 0.7:
        return "High"
    if magnitude >= 0.4:
        return "Medium"
    return "Low"


def build_signal(
    panel: IndicatorPanel,
    segment: str,
    *,
    weights: ConfluenceWeights = DEFAULT_WEIGHTS,
    entry_threshold: float = 0.4,
    rank_in_segment: int = 0,
    panel_config=None,
) -> MoverSignal:
    """Assemble a :class:`MoverSignal` from a panel (score + direction + full votes).

    Thin orchestrator: scores the panel, buckets the direction, and packs the result
    (with the complete vote attribution) into the frozen :class:`MoverSignal`. The
    ``segment`` and ``rank_in_segment`` are caller-supplied -- the cross-symbol
    ranking concern lives in the signals layer (#75), not the scorer.

    Parameters
    ----------
    panel : IndicatorPanel
        The per-symbol indicator panel.
    segment : str
        The segment the symbol was ranked in (echoed onto the signal).
    weights : ConfluenceWeights, optional
        Family weights. Defaults to :data:`DEFAULT_WEIGHTS`.
    entry_threshold : float, optional
        Direction threshold (default ``0.4``).
    rank_in_segment : int, optional
        One-based rank within the segment; ``0`` until #75 ranks (default ``0``).

    Returns
    -------
    MoverSignal
        The composite signal carrying ``score`` / ``direction`` / ``votes``.
    """
    score, votes = composite_score(panel, weights=weights, panel_config=panel_config)
    return MoverSignal(
        symbol=panel.symbol,
        segment=segment,
        as_of=panel.as_of,
        score=score,
        direction=direction_for(score, entry_threshold=entry_threshold),
        votes=votes,
        rank_in_segment=rank_in_segment,
    )
