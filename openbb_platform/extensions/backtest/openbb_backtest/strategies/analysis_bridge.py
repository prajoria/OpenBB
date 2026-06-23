"""``analysis_bridge`` — adapt the ``Analysis`` pipeline into a score provider (C10.5).

A thin adapter that turns a single-symbol ``Analysis.run_full_analysis`` result
into one scalar **factor score** suitable for
:class:`~openbb_backtest.strategies.factor_tilt.FactorTilt`. It blends three
phase outputs, all normalized onto a roughly 0–5 scale:

- **composite** — Phase 7 ``composite_score`` (overall 0–5 conviction),
- **quality**   — Phase 2 ``score`` (fundamental quality, 0–5),
- **valuation** — Phase 4 ``margin_of_safety`` (a fraction) rescaled by ×5 so a
  20% margin of safety contributes like a 1.0 quality point.

The default blend is ``0.5*composite + 0.3*quality + 0.2*valuation``.

This module deliberately performs **no** OpenBB or ``Analysis`` imports at module
load: the live ``run_full_analysis`` is *injected* as ``run_analysis`` so the
adapter is unit-testable with a stub and only reaches the network under the
integration-gated test. :func:`default_run_analysis` lazily wires the real
single-symbol pipeline for callers who want the batteries-included path.

**Look-ahead caveat.** ``run_full_analysis`` fetches *latest* fundamentals/prices
and is therefore not strictly point-in-time; treat scores from this bridge as
research signals, not historically faithful backtest inputs. A point-in-time
Pipeline-backed provider is deferred until component 05 lands (follow-up bead).

See ``docs/designs/backtest-design/10-strategy-library.md`` §3.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

#: A callable that runs the analysis pipeline for one symbol and returns its
#: ``{'p1'..'p7'}`` results dict (the shape of ``Analysis.run_full_analysis``).
RunAnalysis = Callable[[str], Mapping[str, Any]]

#: Default phase-blend weights (see module docstring).
DEFAULT_WEIGHTS: dict[str, float] = {"composite": 0.5, "quality": 0.3, "valuation": 0.2}

#: Phase 4 ``margin_of_safety`` is a fraction; ×5 puts it on the 0–5 phase scale.
_VALUATION_SCALE = 5.0


def _phase_value(results: Mapping[str, Any], key: str, attr: str) -> float:
    """Return ``results[key].attr`` as a float, or 0.0 if the phase is absent/NaN."""
    phase = results.get(key)
    if phase is None:
        return 0.0
    value = getattr(phase, attr, None)
    if value is None:
        return 0.0
    fvalue = float(value)
    return 0.0 if pd.isna(fvalue) else fvalue


def make_analysis_score_provider(
    *,
    run_analysis: RunAnalysis,
    weights: Mapping[str, float] | None = None,
) -> Callable[[str, pd.Timestamp], float]:
    """Build a ``factor_tilt`` score provider backed by ``run_analysis``.

    Parameters
    ----------
    run_analysis
        Callable mapping a symbol to an ``Analysis.run_full_analysis`` results
        dict (keys ``'p1'``..``'p7'``). Injected for testability.
    weights
        Optional override of the phase blend; keys must be a subset of
        ``{"composite", "quality", "valuation"}``. Missing keys default to 0.

    Returns
    -------
    Callable[[str, pandas.Timestamp], float]
        A point-in-time score provider ``(symbol, now) -> score``. ``now`` is
        accepted for the provider protocol but unused (see look-ahead caveat).
    """
    blend = dict(DEFAULT_WEIGHTS)
    if weights is not None:
        unknown = set(weights) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise ValueError(
                f"unknown weight key(s) {sorted(unknown)}; "
                f"allowed: {sorted(DEFAULT_WEIGHTS)}"
            )
        blend.update({k: float(v) for k, v in weights.items()})

    def _provider(symbol: str, now: pd.Timestamp) -> float:  # noqa: ARG001 - protocol arg
        results = run_analysis(symbol)
        composite = _phase_value(results, "p7", "composite_score")
        quality = _phase_value(results, "p2", "score")
        valuation = _phase_value(results, "p4", "margin_of_safety") * _VALUATION_SCALE
        score = (
            blend["composite"] * composite
            + blend["quality"] * quality
            + blend["valuation"] * valuation
        )
        logger.debug(
            "analysis_bridge %s: composite=%.3f quality=%.3f valuation=%.3f -> %.4f",
            symbol, composite, quality, valuation, score,
        )
        return score

    return _provider


def default_run_analysis(symbol: str) -> Mapping[str, Any]:
    """Lazily run the real single-symbol ``Analysis`` pipeline for ``symbol``.

    Imported on demand so importing this module never pulls in ``Analysis`` /
    OpenBB. Intended as the batteries-included ``run_analysis`` argument to
    :func:`make_analysis_score_provider`.
    """
    from stock_analysis import AnalysisConfig, run_full_analysis  # noqa: PLC0415

    return run_full_analysis(AnalysisConfig(symbol=symbol))
