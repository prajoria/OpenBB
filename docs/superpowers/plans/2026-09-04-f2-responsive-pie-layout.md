# F2 Responsive Pie Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use wide pie-widget space for a readable side-by-side plot and legend while preserving a stacked narrow-widget fallback.

**Architecture:** Keep pie geometry and data shaping unchanged. Add pie-specific markup classes in the shared inline renderer, then use container-query CSS to switch between a two-column desktop layout and a stacked narrow layout.

**Tech Stack:** Plain HTML, CSS container queries, inline SVG, Node.js built-in test runner.

## Global Constraints

- Preserve the current pie data model, colors, slice titles, and glossary summaries.
- Apply the behavior through the shared local-viewer pie renderer rather than F2-only markup.
- Do not change generic chart layouts or widget grid coordinates.
- Wide widgets use a plot column plus vertical legend; narrow widgets stack without horizontal overflow.

---

### Task 1: Add responsive pie renderer contracts

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs:183-195`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Consumes: `svgForChart(model, widgetDef) -> string`
- Produces: A load-bearing contract for `pie-chart`, `pie-plot`, and `pie-legend` markup hooks.

- [ ] **Step 1: Strengthen the pie renderer test**

Add these assertions to `svgForChart draws one slice per pie datum`:

```javascript
assert.match(svg, /class="chart pie-chart"/);
assert.match(svg, /class="pie-plot"/);
assert.match(svg, /class="legend pie-legend"/);
```

- [ ] **Step 2: Run the test and verify the new contract fails**

Run:

```powershell
node --test --test-name-pattern "svgForChart draws one slice per pie datum" openbb_platform\extensions\portfolio\assets\local_viewer\tests\viewer_render.test.mjs
```

Expected: FAIL because the current renderer emits only `class="chart"` and `class="legend"`.

### Task 2: Implement the responsive plot-and-legend layout

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html:218-221`
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html:795-816`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Consumes: The markup class contract from Task 1.
- Produces: Shared responsive pie HTML/CSS used by all local-viewer pie widgets.

- [ ] **Step 1: Add pie-specific responsive CSS**

After the generic `.chart` and `.legend` declarations, add:

```css
.widget { container-type: inline-size; }
.chart.pie-chart {
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(180px, 42%) minmax(0, 1fr);
  align-items: center;
  gap: 18px;
}
.pie-plot {
  width: min(100%, 240px);
  height: auto;
  justify-self: center;
}
.pie-legend {
  min-width: 0;
  flex-direction: column;
  align-content: stretch;
}
.pie-legend .lg { justify-content: space-between; }
@container (max-width: 520px) {
  .chart.pie-chart {
    grid-template-columns: minmax(0, 1fr);
    align-content: start;
  }
  .pie-plot { width: min(100%, 220px); }
  .pie-legend {
    flex-direction: row;
    justify-content: center;
  }
  .pie-legend .lg { justify-content: flex-start; }
}
```

If `.widget` already has a declaration, add `container-type: inline-size` to
that declaration rather than creating a duplicate selector.

- [ ] **Step 2: Emit the pie-specific class hooks**

Change the pie return string to:

```javascript
return `<div class="chart pie-chart"><svg class="pie-plot" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="pie chart">${paths}</svg><div class="legend pie-legend">${legend}</div></div>`;
```

- [ ] **Step 3: Run the focused test**

Run:

```powershell
node --test --test-name-pattern "svgForChart draws one slice per pie datum" openbb_platform\extensions\portfolio\assets\local_viewer\tests\viewer_render.test.mjs
```

Expected: PASS.

- [ ] **Step 4: Run the complete local-viewer renderer suite**

Run:

```powershell
node --test openbb_platform\extensions\portfolio\assets\local_viewer\tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit the implementation**

```powershell
git add openbb_platform\extensions\portfolio\assets\local_viewer\index.html openbb_platform\extensions\portfolio\assets\local_viewer\tests\viewer_render.test.mjs
git commit -m "fix(portfolio): balance responsive pie layouts" -m "Closes #2019" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Verify the live F2 workspace

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: The running local viewer at `http://127.0.0.1:6120/viewer`.
- Produces: Visual evidence that both F2 pie widgets use the new layout and no runtime errors occur.

- [ ] **Step 1: Reload the live viewer**

Reload `http://127.0.0.1:6120/viewer`, select `Portfolio Intelligence - Terminal`,
then select `F2: Financials`.

- [ ] **Step 2: Verify both revenue pie widgets**

Confirm `Revenue Per Business Line` and `Revenue Per Geography` place the pie
and legend side by side, use the widget width evenly, and keep all labels and
percentages visible.

- [ ] **Step 3: Verify the narrow fallback**

Resize one revenue pie widget below 520 pixels of content width. Confirm the
pie centers above a wrapped legend and the widget has no horizontal overflow.

- [ ] **Step 4: Check browser diagnostics**

Confirm the browser console contains no new error and neither pie widget enters
a failed or empty state.
