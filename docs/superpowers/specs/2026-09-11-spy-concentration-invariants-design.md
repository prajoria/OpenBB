# SPY Concentration Integration Invariants Design

## Purpose

Make the live SPY concentration integration test resilient to legitimate provider-data
changes while preserving its ability to reject malformed concentration output. Production
behavior remains unchanged.

## Considered Approaches

1. **Widen the hard-coded HHI range.** Smallest edit, but any lower bound remains coupled to
   a changing holdings dataset and will eventually become stale again.
2. **Snapshot provider holdings.** Deterministic, but no longer verifies the live provider and
   duplicates the existing mocked unit coverage.
3. **Assert mathematical invariants (recommended).** Keep the live route call and verify the
   response's domain, reciprocal relationship, and monotonic top-weight aggregates. These
   properties remain stable as SPY constituents and weights change.

## Design

Only the risk-router test module changes. A shared SPY-specific assertion helper will
validate the live result, and a parametrized unit test will prove that representative
malformed values and the unresolved single-symbol fallback are rejected. The helper will
assert:

- `hhi` is finite and in `(0, 1]`;
- `effective_n` is finite and equals `1 / hhi` within floating-point tolerance;
- `top1`, `top5`, and `top10` are finite, positive, bounded by `1`, and monotonically
  non-decreasing;
- `top1` lies between HHI and HHI's square root, as required for non-negative
  normalized weights.
- SPY's `top5` is strictly greater than `top1`, proving that the provider resolved
  more than the route's single-symbol fallback without constraining live weights.

Together these checks reject NaN, infinity, zero/negative or over-unity concentration,
inconsistent effective-N, empty concentration aggregates, malformed ordering, unresolved SPY
fallback output, and impossible largest-weight output without imposing market-sensitive SPY
bounds.

## Testing

Follow RED-GREEN-REFACTOR by first expressing the durable assertions and confirming that a
locally substituted malformed result fails them. Then run the live integration test, the
complete risk-router unit module, and the portfolio-intel risk integration selection. A
real-path harness will call `obb.portfolio_intel.risk.concentration` with live SPY data and
record the validated metrics.
