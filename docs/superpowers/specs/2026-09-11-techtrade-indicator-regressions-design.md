# TechTrade Extended Indicator Regression Design

## Scope

Resolve Project #4 issue #2078 without changing the public classic-panel contract:

- a classic request remains byte-compatible with the existing classic panel;
- an extended request remains a strict superset where extended indicators are available;
- every fallback preserves the caller's requested panel;
- Ichimoku audit keys and opt-in votes work with the installed
  `pandas-ta-classic` API while remaining compatible with the older tuple result shape.

The default ship configuration continues to exclude the correlated
`ichimoku_cloud` vote. This fix restores computation and explicit opt-in behavior; it
does not change scoring policy.

## Reproduced Failures

The focused suite currently reports 14 failures:

1. The technical-unavailable fallback returns an extended panel, while a stale
   equality assertion still expects classic and extended panels to be identical.
2. `pandas-ta-classic` returns the current Ichimoku frame directly as a
   `DataFrame`, but `_compute_trend_ext` only accepts the older two-element tuple
   shape. It therefore discards valid values and omits both Ichimoku keys.
3. The exception fallback in `technical_panel` omits `panel_config`, so a real
   technical-provider failure silently downgrades an extended request to classic.

## Approaches Considered

### Recommended: normalize dependency output and preserve selector through fallbacks

Accept either a current-value `DataFrame` or the older `(current, projection)` tuple,
then run the existing key extraction and confirmation logic unchanged. Forward
`panel_config` through the exception fallback. Replace the obsolete strict-equality
assertion with the established subset/value-parity contract and add a discriminating
test for failure after entering the technical leg.

This is the smallest production fix, supports both dependency contracts, and tests
the actual selector behavior rather than an implementation accident.

### Alternative: compute Ichimoku internally

Implement rolling highs/lows and displacement without `pandas-ta-classic`. This
would eliminate return-shape drift but duplicate a mature indicator implementation
and introduce a larger numerical-parity surface.

### Alternative: pin an older `pandas-ta-classic`

Restore the tuple shape through dependency pinning. This is fragile, blocks routine
dependency upgrades, and leaves the selector-loss bug in the exception fallback.

## Production Design

Add a private normalization helper in `indicators_ext` that:

- returns the object directly when it is frame-like;
- returns the first tuple element when that element is frame-like;
- returns `None` for unsupported or empty shapes.

Frame-like detection uses the interface consumed by this module (`columns`, `iloc`,
and length), avoiding a new hard import or version check.

In `technical_panel`, pass the original `panel_config` to
`build_indicator_panel` in both fallback branches. No fallback may reinterpret the
requested selector.

## Contract Tests

The tests will lock:

- classic keys and values are an invariant subset of the extended fallback panel;
- extended-only Aroon keys prove the requested selector reached the fallback;
- a technical-leg exception still returns the same extended panel as the direct
  deterministic builder;
- direct-frame and legacy tuple Ichimoku results are both accepted;
- sufficient histories populate raw and confirmed keys;
- opt-in votes remain signed and bounded;
- short histories omit Ichimoku keys;
- the default ship allowlist still excludes the Ichimoku vote.

## Verification

Run the two reproducer modules, all non-integration TechTrade tests, formatting and
lint diagnostics for changed Python files, and a real-path harness that builds
classic and extended panels from synthetic OHLCV data and forces the technical
exception fallback. Capture harness output under `.dev-cycle/`.

