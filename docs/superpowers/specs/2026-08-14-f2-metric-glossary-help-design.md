# F2 Metric Glossary Help Design

## Goal

Make the F2: Financials view understandable without forcing a user to leave
the dashboard. Each supported financial metric will have concise contextual
help and a path to fuller, source-linked documentation.

## Scope

The first release covers the F2 key-stat table and financial-statement chart
series: Market Cap, P/E (TTM), EV/EBITDA, P/S (TTM), EPS (TTM), Beta,
Dividend Yield, Revenue, Net Income, and Net Margin. It leaves the existing
widget-level help popover in place and is designed to accept mappings from
future tabs without changing the renderer.

## Design

A viewer-owned glossary maps a stable metric key to a short tooltip, a
plain-language definition, interpretation notes, and an optional reputable
external learning URL. The F2 widget definitions declare which label or chart
series maps to each glossary key.

The renderer places an accessible help button next to mapped table row labels
and chart legend items. Hover and keyboard focus reveal the short explanation.
Clicking the button opens a same-origin Help page at `/viewer/help?metric=<key>`.
That page shows the complete definition, contextual interpretation, and a
clearly labelled external resource that opens in a new tab with
`noopener noreferrer`.

Unknown metrics remain unchanged: the table/chart renders normally without a
help control. This prevents unreviewed or fabricated explanations from being
shown for values that have not yet been curated.

## Accessibility and Safety

Help controls have descriptive `aria-label` text, work with mouse, keyboard,
and focus, and do not initiate a widget drag. The documentation page escapes
glossary text before rendering. External links use a curated allowlist embedded
in the glossary, are visibly identified as external, and never receive dynamic
URLs from API data.

## Validation

Unit tests cover glossary lookup, table-label help markup, chart-legend help
markup, safe documentation-page rendering, and the no-mapping fallback.
Existing viewer tests continue to verify no unintended external network
requests; the only links are user-initiated navigation.
