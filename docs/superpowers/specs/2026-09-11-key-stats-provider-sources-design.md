# Key-Stats Provider Sources

## Scope and verified capabilities

Resolve #1959 by adding only fields backed by the real `fmp_cached` provider.
A live AAPL probe on 2026-09-11 established:

- `equity.ownership.share_statistics(provider="fmp_cached")` returns
  `float_shares`, `free_float`, and `outstanding_shares`.
- `equity.estimates.forward_eps(provider="fmp_cached")` returns dated annual
  consensus EPS estimates, including a non-zero `mean`.
- `fmp_cached` does not register `EquityShortInterest`.
- The FMP share-statistics response contains no insider-ownership field.

Therefore this change will add Shares Float and a derived Forward P/E only.
Short Interest and Insider Ownership remain omitted, with the concrete provider
evidence recorded on the issue. No value will be inferred or fabricated.

## Considered approaches

1. **Restore all four rows with constants or estimates.** Rejected because it
   would misrepresent fabricated data as live provider output.
2. **Use mixed providers such as FINRA or yfinance.** Technically possible for
   some fields, but violates this issue's `fmp_cached` provenance and would make
   the current single-tier source badge misleading.
3. **Wire only verified `fmp_cached` sources (chosen).** Fetch share statistics
   and forward EPS as best-effort enrichment. Derive Forward P/E as current
   price divided by the first positive annual consensus EPS estimate.

## Design

The existing key-stats tier will gain two small fetch helpers using established
`_safe_first_row` behavior. `_shape_key_stats` will accept optional
share-statistics and forward-EPS rows. It will emit:

- `Shares Float`, formatted with the existing human-readable count helper, only
  when `float_shares` is present.
- `Forward P/E`, rounded to two decimals, only when both current price and a
  positive consensus EPS `mean` are present.

Existing calls remain source-compatible through optional parameters. Provider
errors continue to degrade to omission rather than blanking the entire grid.
No frontend viewer, execution, configuration, snapshot, or risk files change.

## Validation

TDD covers shaping, missing/zero inputs, provider call paths, degradation, and
the endpoint's live-tier result. The real provider harness will record the
returned source fields and verify that the computed Forward P/E equals the
observed quote divided by the observed EPS estimate.
