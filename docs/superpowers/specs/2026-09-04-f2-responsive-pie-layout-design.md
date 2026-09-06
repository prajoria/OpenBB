# F2 Responsive Pie Layout Design

## Context

BugContext session `01a06eef-149d-74dd-9a9b-9a3db4794250` shows that
the F2 revenue pie charts leave a large unused area in wide widgets. The
shared viewer currently renders a fixed 220-pixel pie and places its legend
below the plot, regardless of available width.

## Considered Approaches

1. **Increase the pie diameter.** This reduces some empty space but creates
   an oversized plot, remains unbalanced, and can exceed the widget height.
2. **Center the existing stacked layout.** This improves symmetry but still
   wastes horizontal space and leaves long legend labels cramped below.
3. **Use a responsive plot-and-legend layout.** Place the pie and a vertical
   legend side by side when sufficient width is available, then stack them
   at narrow widths. This uses the space for information without distorting
   the chart.

Approach 3 is selected because it improves information density and scanning
while preserving the existing data and interaction model.

## Design

The shared pie renderer will emit pie-specific classes on the chart wrapper,
SVG, and legend. CSS will use a two-column grid with a bounded plot column and
an adaptive legend column. The plot remains a fixed-aspect-ratio circle and is
centered in its column. Legend items will form a vertical list so labels and
percentages can be scanned without competing with the plot.

A container query will switch the pie body to the existing stacked pattern
when its widget becomes narrow. This responds to widget resizing rather than
only the browser viewport. The generic chart and legend styles for other chart
types remain unchanged.

## Accessibility and Behavior

- The SVG keeps its `role="img"` and accessible pie-chart label.
- Slice titles and legend content remain unchanged.
- Existing glossary summaries on legend items remain available.
- The responsive change is presentation-only; endpoint data and widget
  metadata are unaffected.

## Validation

- Add renderer contracts for the pie-specific wrapper, SVG, and legend
  classes.
- Verify existing chart renderer tests remain green.
- In the live F2 workspace, confirm Revenue Per Business Line and Revenue Per
  Geography use balanced side-by-side layouts at desktop width.
- Resize a pie widget narrow enough to confirm the stacked fallback has no
  horizontal overflow.

## Scope

This change applies to the shared local-viewer pie renderer and therefore
improves every pie widget consistently. It does not alter the F2 grid layout,
pie data, color palette, or chart type.
