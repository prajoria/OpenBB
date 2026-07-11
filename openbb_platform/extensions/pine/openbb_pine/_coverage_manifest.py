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

Post-extraction module map (E4.2, 2026-07-10; bd-or5). The Pine compiler +
core runtime were extracted to ``prajoria/pynecore`` (vendored here at
``third_party/pynecore/``) as the ``pyne_compiler`` sibling package:

* ``pyne_compiler.compiler.*`` — lexer / parser / IR / type checker / codegen
  / compile cache / v5→v6 migration (formerly ``openbb_pine.compiler.*``)
* ``pyne_compiler.runtime.*`` — executor_core, security_dispatcher,
  secondary_cache, security_hook, strategy_types, restricted, limits,
  _pynecore_glue, pynecore_bridge (formerly ``openbb_pine.runtime.*``)
* ``pyne_compiler.errors.*`` — compiler+runtime error hierarchy (formerly
  ``openbb_pine.compiler_errors``)
* ``openbb_pine.*`` — provider-side glue only: FMP + BYO providers, REST
  routers, MCP tools, telemetry, attribution, CLI, this manifest

Legacy ``openbb_pine.compiler.*`` / ``openbb_pine.runtime.*`` import paths
remain as ``DeprecationWarning`` shims through the next minor release
(§13.5). Coverage entries below are portable across the rename because they
key on Pine identifier names (``ta.sma``), not Python module locations.

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
  unedited. Entries whose ``builtin_signatures.Signature`` carries
  ``notes="SIGNATURE_ONLY"`` are C3-typechecked but codegen-deferred; they
  MUST NOT appear here until the bridge lands and ``notes`` flips to
  ``"IMPLEMENTED"`` -- otherwise a script that uses them would be
  mis-attributed as "would run unedited" when in fact it crashes at codegen.
* ``FEATURES_IMPLEMENTED`` -- the closed vocabulary of grammar features the
  wild-corpus indexer (L0.4) records per script. See the wild-corpus index
  README for the exhaustive list; currently:
  ``{"request.security", "library", "drawings", "strategy", "indicator"}``.

These three sets MUST stay frozensets so they are hashable and cannot be
mutated at runtime by accident; tests assert their identity-type.
"""

from __future__ import annotations

PINE_VERSIONS_SUPPORTED: frozenset[int] = frozenset({5, 6})
"""Pine ``//@version=`` integers the compiler accepts.

v6 is native (C1-C8 chain); v5 is auto-migrated to v6 via the C7 shim
(0e9.5.7, commit 0d2765ad4) before parse. See PRD §8.1 M1 gate (h)."""

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
    # Post-Wave-5B curated-corpus alignment (bead 0e9.13): input.* + color.*
    # constants ARE implicitly supported by the codegen (emits `from
    # pynecore.lib import input, color`; PyneCore ships the full input/color
    # namespaces). Add to BUILTINS_IMPLEMENTED so the L0.5 coverage metric
    # doesn't misattribute them to "unsupported builtin" against real
    # community scripts. Same reasoning for the essential str/math/na sugar.
    "input.int",
    "input.float",
    "input.bool",
    "input.string",
    "input.source",
    "color.blue",
    "color.red",
    "color.green",
    "color.orange",
    "color.purple",
    "color.gray",
    "color.white",
    "color.black",
    "color.yellow",
    "color.new",
    "str.tostring",
    "str.tonumber",
    "math.log",
    "math.exp",
    "math.sign",
})
"""Fully-qualified Pine builtin identifiers implemented (not stubbed)."""

FEATURES_IMPLEMENTED: frozenset[str] = frozenset({
    # Top-level declarations (C2 parser + C3 type checker + C5 codegen).
    "indicator",              # @script.indicator via C5 codegen
    # "strategy",             # deferred to Phase 2 (bead 0e9.5.6)
    # "library",              # deferred to Phase 3 (bead 0e9.5.7 P3)
    # Grammar features (C1 lexer + C2 parser + C3 type checker).
    "var",                    # var x = ...
    "varip",                  # varip x = ...
    "if_else",                # if/else if/else statements
    "for_loop",               # for i = ...
    "while_loop",             # while cond
    "ternary",                # cond ? a : b
    "history_ref",            # x[n] history operator
    "function_def",           # named function definitions
    "type_annotation",        # : simple int, : series float, etc.
    # Common input.* forms (C3 signatures + C5 codegen).
    "input.int",
    "input.float",
    "input.bool",
    "input.string",
    "input.source",
    # Plot/alert primitives (C5 codegen).
    "plot",
    "plotshape",
    "hline",
    "alert",
    # OHLCV sources (C3 signatures + C5 codegen).
    "close",
    "open",
    "high",
    "low",
    "volume",
    "time",
    # NA / nz sentinel handling (PyneCore runtime + C3).
    "na",
    "nz",
})
"""Grammar features implemented. Subset of the wild-corpus indexer's vocabulary.

Populated post-Wave-5B as part of bead 0e9.5.62 (L0.4b wild-corpus strategy)
to unblock the L0.5 coverage metric — an empty features set was misattributing
every wild-corpus script's use of ``indicator()`` / ``plot()`` / ``input.int``
as "unsupported feature" and dragging the coverage percentage to 0.

Deferred to later phases (still missing):
- ``strategy`` (Phase 2 — bead 0e9.5.6 / #pine-P2)
- ``library`` (Phase 3 — bead 0e9.5.7 / #pine-P3)
- ``request.security`` (Phase 2)
- Drawings (``line.new``, ``label.new``, ``box.new``, ``table.new``; Phase 3)
- Import statements (Phase 3 library support)
"""

__all__ = [
    "PINE_VERSIONS_SUPPORTED",
    "BUILTINS_IMPLEMENTED",
    "FEATURES_IMPLEMENTED",
]
