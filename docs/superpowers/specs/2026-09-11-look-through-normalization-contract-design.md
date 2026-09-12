# Look-Through Normalization Contract Design

## Purpose

Guarantee that recursive ETF look-through preserves a normalized effective portfolio. This
prevents uniformly under-scaled provider holdings from producing internally consistent but
incorrect HHI, effective-N, and top-weight metrics.

## Considered Approaches

1. **Expose total weight in `ConcentrationSummary`.** This makes the defect observable but
   expands the public API and still leaves every consumer responsible for rejecting it.
2. **Always renormalize provider holdings.** This guarantees a unit sum but can turn a severely
   truncated response into a confidently wrong portfolio.
3. **Validate, then normalize at the analytics boundary (recommended).** Reject materially
   incomplete or invalid child vectors and normalize only bounded provider rounding drift.
   Every caller receives the same invariant without changing response schemas.

## Production Contract

`analytics.xray.look_through` owns the invariant because it is the shared recursive
composition boundary used by X-Ray, concentration, and What-If.

- Top-level portfolio weights retain their existing `0.0001` tolerance.
- Every non-empty underlying holdings vector must contain finite, non-negative weights.
- Its total must be positive and within `0.02` of one, matching the existing `fmp_cached`
  provider contract. This accepts the observed live SPY issuer total (`0.99775977`) and
  ordinary source rounding, while rejecting percent/fraction double-conversion and materially
  truncated datasets.
- Accepted child weights are divided by their total before recursion. This makes effective
  weights sum to the parent allocation within Decimal arithmetic precision rather than
  carrying provider rounding drift.
- Empty provider lists retain the existing unresolved-symbol fallback.
- Validation failures raise `ValueError` with the parent symbol and observed defect; they are
  not silently converted to unresolved data.

## Testing

Add pure unit regressions proving that a 1%-scaled child vector fails, small rounding drift is
normalized to one, and non-finite or negative child weights fail. Existing exact-weight,
unresolved, depth-limit, route, concentration, and What-If tests verify preserved semantics.
The real-path harness will run live SPY look-through and concentration and record normalized
effective total plus concentration metrics.
