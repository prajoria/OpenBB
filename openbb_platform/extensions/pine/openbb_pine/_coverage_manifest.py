"""Implemented-feature manifest consumed by the wild-corpus coverage metric.

This module is the single source of truth for **what is implemented** in the
``openbb-pine`` extension at any point in time. The wild-corpus coverage tool
(``tools/pine/measure_wild_corpus_coverage.py``) reads these three frozensets
to decide whether a given Pine script in the wild-corpus index would "run
unedited" against the current implementation.

PRD references:

* §3.4 — wild-corpus coverage methodology
* §8.1 — phase-gate targets (M1 ≥40%, M2 ≥70%, M3 ≥90%)
* §12 — 12-month success metric (L4 wild-corpus coverage ≥90%)

Lifecycle. At Phase 0 (this commit) every set is empty, so the baseline
metric is intentionally 0%. As stdlib beads land in Phase 1+, each PR
that implements a builtin (or a grammar feature, or adds a supported Pine
version) ADDS the corresponding identifier to the relevant frozenset here.
The wild-corpus-coverage CI job (``.github/workflows/wild-corpus-coverage.yml``)
then recomputes the coverage percentage and posts it as a PR comment with
the delta vs the main-branch baseline.

Contract.

* ``PINE_VERSIONS_SUPPORTED`` -- the set of ``//@version=`` integers the
  compiler accepts unedited. v5 scripts only count once the v5→v6 migration
  shim lands (PRD §8.1 Phase 1 gate (h)).
* ``BUILTINS_IMPLEMENTED`` -- fully-qualified Pine builtin identifiers
  (``ta.sma``, ``math.abs``, ``ta.crossover``, ...). MUST exclude any
  identifier that is only stubbed -- a script using a stub does NOT run
  unedited.
* ``FEATURES_IMPLEMENTED`` -- the closed vocabulary of grammar features the
  wild-corpus indexer (L0.4) records per script. See the wild-corpus index
  README for the exhaustive list; currently:
  ``{"request.security", "library", "drawings", "strategy", "indicator"}``.

These three sets MUST stay frozensets so they are hashable and cannot be
mutated at runtime by accident; tests assert their identity-type.
"""

from __future__ import annotations

PINE_VERSIONS_SUPPORTED: frozenset[int] = frozenset()
"""Pine ``//@version=`` integers the compiler accepts. Empty at Phase 0."""

BUILTINS_IMPLEMENTED: frozenset[str] = frozenset({
    # Wave 5B-1: moving averages (S-beads 0e9.5.16-19, 21).
    "ta.sma",
    "ta.ema",
    "ta.wma",
    "ta.rma",
    "ta.macd",
    # Wave 5B-2: momentum + oscillators (S-beads 0e9.5.20, 24-27).
    "ta.rsi",
    "ta.stoch",
    "ta.cci",
    "ta.adx",
    "ta.mfi",
    # Wave 5B-4: signals + transforms + rolling utilities
    # (S-beads 0e9.5.{30,31,32,33,35,36,37,40,41,42,43,44}). Parent recovery
    # after subagent partial-landing: bridges + fixtures shipped, coverage
    # manifest + tests added here.
    "ta.crossover",
    "ta.crossunder",
    "ta.highest",
    "ta.lowest",
    "ta.change",
    "ta.mom",
    "ta.roc",
    "ta.linreg",
    "ta.median",
    "ta.percentile_linear_interpolation",
    "ta.cum",
    "ta.barssince",
    # Wave 5B-5: math.* namespace (S-beads 0e9.5.45-51).
    "math.abs",
    "math.max",
    "math.min",
    "math.pow",
    "math.round",
    "math.sqrt",
    "math.sum",
    # Wave 5B-3: bands + volatility + volume (S-beads 0e9.5.{22,23,28,29,34,38,39}).
    "ta.bb",
    "ta.atr",
    "ta.tr",
    "ta.stdev",
    "ta.obv",
    "ta.vwap",
    "ta.sar",
})
"""Fully-qualified Pine builtin identifiers implemented (not stubbed)."""

FEATURES_IMPLEMENTED: frozenset[str] = frozenset()
"""Grammar features implemented. Subset of the wild-corpus indexer's vocabulary."""

__all__ = [
    "PINE_VERSIONS_SUPPORTED",
    "BUILTINS_IMPLEMENTED",
    "FEATURES_IMPLEMENTED",
]
