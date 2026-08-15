# Terminal Financial Terminology and Help Audit Design

## Goal

Make every Portfolio Intelligence Terminal widget read like an analyst-facing
product rather than an API response. User-visible headers, chart series, and
metric-card labels must use precise financial terminology, and meaningful
domain terms must offer contextual help.

## Scope and Unit of Work

The audit covers all 39 unique widgets used by the 12 Terminal tabs. Each widget is classified as either passing or deficient. Every deficient
widget gets its own GitHub child issue under #1987 and is implemented, tested,
and reviewed separately in tab order. The live sweep may overturn a static
passing classification when inferred headers or runtime values expose API
names; those widgets receive their own child issues before the audit closes.

A widget passes when:

- no API field name or snake_case variable appears as a user-facing label;
- abbreviations include the accepted financial form and measurement basis;
- units and horizons are explicit where material;
- meaningful financial concepts have glossary-backed help; and
- identifiers, dates, names, free text, statuses, and simple operational
  fields are not cluttered with unnecessary help controls.

## Presentation Metadata

Widget definitions remain the authority for presentation. Tables declare
explicit column headers instead of relying on response keys. Charts declare
series names and glossary mappings. Metric widgets declare display labels and
glossary mappings for each card. Widgets with metric/value rows map the
displayed row label to a glossary key.

The viewer must not globally humanize snake_case. Automatic capitalization
cannot infer whether `var_95_1d` means one-day 95% Value at Risk, whether
`pe_fwd` uses next-twelve-month or fiscal-year estimates, or whether
`interaction` is a Brinson attribution effect. Explicit metadata makes those
decisions reviewable and testable.

## Help Behavior

The glossary introduced for F2 remains the single source of definitions.
Supported table headers, row labels, chart legends, and metric-card labels use
the same accessible help control:

- hover and keyboard focus show a concise explanation;
- click opens the same-origin detailed help page;
- the detailed page gives a definition, interpretation guidance, and a
  curated external education link; and
- unknown or unreviewed keys render no help control.

The renderer will be extended only where a presentation surface lacks glossary
support. It will not duplicate glossary content inside widget definitions.

## Issue and Delivery Workflow

The audit first records a machine-readable inventory of widget IDs, response
schema fields, configured labels, and glossary coverage. Passing widgets are
listed on #1987. A separate child issue is filed for each deficient widget
with:

- the exact current labels and approved replacements;
- glossary keys to add or reuse;
- the rendering surface involved;
- focused test requirements; and
- the Terminal tab where live verification occurs.

Child issues are implemented one at a time. Each child produces a focused
commit citing its issue. The stacked pull request closes the parent only after
all children pass targeted tests and the final 12-tab live sweep.

## Validation

Static contract tests assert explicit labels and glossary mappings for every
audited widget. Renderer tests cover each supported help surface and ensure
unknown terms remain plain. A browser sweep visits all 12 tabs and fails on
snake_case labels, missing expected help controls, empty widget states, or
console errors.
