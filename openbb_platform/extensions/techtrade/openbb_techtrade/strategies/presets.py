"""Curated confluence presets + override resolution (issue #75, PRD §12.3, §20 Q4).

A **preset** is a named, curated :class:`~openbb_techtrade.engine.confluence.ConfluenceWeights`
profile that re-tilts the same four indicator families toward a trading style, so the
one #74 confluence engine produces different behaviour depending on the preset picked.
Three ship: ``trend_follow`` (the default, *identical* to the locked Q4 base),
``mean_revert`` (momentum-led, trend damped), and ``breakout`` (volatility-led).

Two invariants are load-bearing and pinned by the unit suite:

* **Additive ceiling preserved.** Every preset's additive trio (trend + momentum +
  volatility) sums to ``0.85`` -- the deliberate #74 "volume is needed for High
  conviction" asymmetry. Presets that renormalised to ``1.0`` would make their scores
  systematically larger, breaking cross-preset comparability (Q-B note 1).
* **Volume amplitude is engine-fixed at ``0.15``.** :func:`~openbb_techtrade.engine.confluence.volume_confirmation`
  applies ``DEFAULT_WEIGHTS.volume`` (``0.15``) regardless of the ``weights`` passed to
  ``composite_score``, and ``composite_score`` re-stamps every volume vote at that same
  fixed amplitude so the attribution reconciles the score. A preset (or override) that set
  a different ``volume`` would therefore be **inert end-to-end** -- ignored by both the
  multiplier and the vote stamping (which both hardcode ``DEFAULT_WEIGHTS.volume``) -- so
  every preset pins ``volume = 0.15`` to keep its declared weights honest, and the override
  validator confirms the merged volume stays within the multiplier's ``[0, 1]`` domain.

Presets are pure data (no I/O, no clock, no RNG), so a preset's golden is stable across
machines. The design's qualitative ``mean_revert`` regime-flip and ``breakout`` strict-ADX
knobs are *not* expressible through ``ConfluenceWeights`` (four floats per the locked
pipeline contract); presets here therefore differ by **weights only**, and the regime /
ADX-gate behaviour stays a #74 voter parameter for a later engine pass.
"""

from __future__ import annotations

from dataclasses import replace

from openbb_techtrade.engine.confluence import DEFAULT_WEIGHTS, ConfluenceWeights

#: The additive ceiling every preset's trend + momentum + volatility must sum to
#: (the #74 "volume confirms conviction" asymmetry; Q-B note 1). Kept comparable
#: across presets so ``score`` means the same thing regardless of which produced it.
ADDITIVE_SUM = 0.85

#: Engine-fixed volume amplitude. ``volume_confirmation`` always applies
#: ``DEFAULT_WEIGHTS.volume``; a preset cannot override it, so every preset pins it.
FIXED_VOLUME = DEFAULT_WEIGHTS.volume

#: The three named presets (PRD §12.3 / §20 Q4). ``trend_follow`` IS the Q4 base (L5);
#: ``mean_revert`` and ``breakout`` tilt the additive trio while preserving its 0.85 sum.
PRESETS: dict[str, ConfluenceWeights] = {
    "trend_follow": DEFAULT_WEIGHTS,
    "mean_revert": ConfluenceWeights(trend=0.20, momentum=0.40, volatility=0.25, volume=FIXED_VOLUME),
    "breakout": ConfluenceWeights(trend=0.25, momentum=0.15, volatility=0.45, volume=FIXED_VOLUME),
}

#: The additive family names (volume is the multiplier, validated separately).
_ADDITIVE_FAMILIES = ("trend", "momentum", "volatility")
_VALID_FAMILIES = frozenset(_ADDITIVE_FAMILIES + ("volume",))
#: Floating-point tolerance for the additive-sum equality check.
_SUM_TOL = 1e-9


def resolve_preset(
    preset: str = "trend_follow",
    weights: dict[str, float] | None = None,
) -> ConfluenceWeights:
    """Resolve a named preset, optionally merging a partial ``{family: weight}`` override.

    Looks up ``preset`` in :data:`PRESETS` (raising :class:`ValueError` that lists the
    valid names on a miss), then **merges** any ``weights`` override over it: only the
    families named in ``weights`` change, the rest keep the preset's value (Q-D merge,
    not replace). The merged weights are validated before return:

    * unknown family keys -> :class:`ValueError`;
    * every additive weight (``trend`` / ``momentum`` / ``volatility``) must be ``>= 0``;
    * ``volume`` must lie in ``[0, 1]`` (it is a multiplier strength, not an additive
      weight, so it is excluded from the additive-sum rule);
    * the additive trio must sum to :data:`ADDITIVE_SUM` (``0.85``) within tolerance --
      no silent renormalisation (Q-D: require exact sum, surprising-rescale-free).

    Parameters
    ----------
    preset : str, optional
        Name of the base preset (default ``"trend_follow"``).
    weights : dict[str, float] | None, optional
        Partial override merged over the preset. ``None`` (default) returns the preset
        unchanged.

    Returns
    -------
    ConfluenceWeights
        The resolved (and validated) family weights to feed the #74 scorer.

    Raises
    ------
    ValueError
        On an unknown preset name, an unknown override family, a negative additive
        weight, an out-of-range ``volume``, or an additive trio that does not sum to
        :data:`ADDITIVE_SUM`.
    """
    if preset not in PRESETS:
        valid = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown preset {preset!r}; valid presets are: {valid}.")

    base = PRESETS[preset]
    if not weights:
        return base

    unknown = set(weights) - _VALID_FAMILIES
    if unknown:
        valid = ", ".join(sorted(_VALID_FAMILIES))
        raise ValueError(f"Unknown weight family/families {sorted(unknown)}; valid families are: {valid}.")

    # Every key is now a known ConfluenceWeights field, so replace() merges the override
    # over the base (unset families keep the preset's value) -- the dataclass analogue of
    # the ``model_copy(update=...)`` merge used for MoverSignal in engine/signals.py.
    merged = replace(base, **{family: float(value) for family, value in weights.items()})

    for family in _ADDITIVE_FAMILIES:
        value = getattr(merged, family)
        if value < 0:
            raise ValueError(f"Additive weight {family!r} must be >= 0, got {value}.")
    if not 0.0 <= merged.volume <= 1.0:
        raise ValueError(f"volume must be in [0, 1], got {merged.volume}.")

    additive_sum = merged.trend + merged.momentum + merged.volatility
    if abs(additive_sum - ADDITIVE_SUM) > _SUM_TOL:
        raise ValueError(
            f"Additive weights (trend+momentum+volatility) must sum to {ADDITIVE_SUM}, "
            f"got {additive_sum}. Pass all three additive weights to change the ceiling intentionally."
        )

    return merged
