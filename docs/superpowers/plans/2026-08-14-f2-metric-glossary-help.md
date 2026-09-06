# F2 Metric Glossary Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add accessible, field-level glossary help to F2 Financials metrics and chart series, backed by a same-origin documentation view.

**Architecture:** A static viewer-owned glossary supplies curated, safe definitions while F2 widget metadata maps displayed labels and series to stable glossary keys. The renderer uses those mappings to add context-specific controls and routes click-through documentation to `/viewer/help`; unmapped content continues to render unchanged.

**Tech Stack:** Self-contained HTML/CSS/JavaScript local viewer, Node built-in test runner, Python pytest viewer contracts.

## Global Constraints

- Keep the viewer self-contained; add no dependency or remote runtime request.
- F2-only mappings: Market Cap, P/E (TTM), EV/EBITDA, P/S (TTM), EPS (TTM), Beta, Dividend Yield, Revenue, Net Income, and Net Margin.
- Help controls must work with pointer, keyboard, and focus; clicking one must not start tile dragging.
- External learning links are curated static URLs and must open with `rel="noopener noreferrer"`.
- Do not display help for an unknown metric key.

---

### Task 1: Add glossary data and F2 metadata mappings

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html`
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets.json`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Produces: `METRIC_GLOSSARY`, keyed by a stable metric slug with `label`, `summary`, `definition`, `interpretation`, and `source`.
- Consumes: optional `data.metricGlossary` object in a widget definition, mapping rendered labels/series names to glossary slugs.

- [ ] **Step 1: Write failing glossary lookup tests**

```javascript
test("metricGlossaryEntry returns a curated F2 record", () => {
  const metric = H.metricGlossaryEntry("pe_ttm");
  assert.equal(metric.label, "P/E (TTM)");
  assert.match(metric.summary, /price.*earnings/i);
});

test("metricGlossaryEntry ignores an unknown key", () => {
  assert.equal(H.metricGlossaryEntry("unreviewed_metric"), null);
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

Expected: FAIL because `metricGlossaryEntry` is not exported by the test helper.

- [ ] **Step 3: Add the static glossary and lookup function**

```javascript
const METRIC_GLOSSARY = Object.freeze({
  pe_ttm: Object.freeze({
    label: "P/E (TTM)",
    summary: "Price divided by trailing twelve-month earnings per share.",
    definition: "The price-to-earnings ratio compares the current share price with earnings generated over the most recent four reported quarters.",
    interpretation: "Compare it with profitable peers and the company’s own history; it is not meaningful when trailing earnings are negative.",
    source: "https://www.investopedia.com/terms/p/price-earningsratio.asp",
  }),
});

function metricGlossaryEntry(key) {
  const entry = METRIC_GLOSSARY[String(key || "")];
  return entry || null;
}
```

Populate the remaining nine explicitly scoped glossary records with reviewed plain-language text and the appropriate curated education URL. Add `data.metricGlossary` mappings to the F2 key-stat and financial-chart widget definitions; use display labels as map keys so the renderer does not need backend changes.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

Expected: PASS, including the two glossary tests.

- [ ] **Step 5: Commit the data-model change**

```bash
git add openbb_platform/extensions/portfolio/assets/local_viewer/index.html openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets.json openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs
git commit -m "feat(portfolio): add F2 metric glossary data" -m "Refs #1984"
```

### Task 2: Render contextual table and chart help

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Consumes: `metricGlossaryEntry(key)` and `widget.data.metricGlossary`.
- Produces: `metricHelpButtonHtml(key)` and label/legend markup that adds a control only for a known mapped metric.

- [ ] **Step 1: Write failing markup tests**

```javascript
test("metricHelpButtonHtml labels a known metric accessibly", () => {
  const html = H.metricHelpButtonHtml("market_cap");
  assert.match(html, /aria-label="Learn about Market Cap"/);
  assert.match(html, /data-metric-help="market_cap"/);
});

test("metricHelpButtonHtml omits unknown metrics", () => {
  assert.equal(H.metricHelpButtonHtml("unreviewed_metric"), "");
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

Expected: FAIL because `metricHelpButtonHtml` does not exist.

- [ ] **Step 3: Add help control rendering and bindings**

```javascript
function metricHelpButtonHtml(key) {
  const entry = metricGlossaryEntry(key);
  if (!entry) return "";
  return `<button type="button" class="mhelp" data-metric-help="${escapeHtml(key)}" `
    + `aria-label="Learn about ${escapeHtml(entry.label)}" title="${escapeHtml(entry.summary)}">?</button>`;
}
```

Add `.mhelp` styling that matches the existing muted header help affordance, with visible hover and focus states. Update `renderTable` to use the F2 label mapping for first-column values and add the button beside an eligible row label. Update SVG legend generation to use the same mapping for named combo series. Attach a shared click handler that uses `/viewer/help?metric=` plus `encodeURIComponent(key)`; stop propagation on pointer-down and click so widget dragging remains unaffected.

- [ ] **Step 4: Extend the renderer test extraction and run tests**

Add `metricHelpButtonHtml` to `loadHelpers()` and assert that mapped table/legend markup contains a help control while an unmapped label remains plain text.

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

Expected: PASS.

- [ ] **Step 5: Commit the renderer change**

```bash
git add openbb_platform/extensions/portfolio/assets/local_viewer/index.html openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs
git commit -m "feat(portfolio): add contextual F2 metric help" -m "Refs #1984"
```

### Task 3: Add safe same-origin metric documentation view

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html`
- Modify: `openbb_platform/extensions/portfolio/tests/test_local_viewer.py`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Consumes: query parameter `metric` and `metricGlossaryEntry(metric)`.
- Produces: `metricHelpPageHtml(key)` returning a safe, complete local documentation page or the unknown-metric state.

- [ ] **Step 1: Write failing documentation-page tests**

```javascript
test("metricHelpPageHtml renders a curated external resource safely", () => {
  const html = H.metricHelpPageHtml("net_margin");
  assert.match(html, /Net Margin/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
});

test("metricHelpPageHtml reports an unknown metric without interpolating it", () => {
  assert.match(H.metricHelpPageHtml("<script>"), /Metric documentation is unavailable/);
  assert.doesNotMatch(H.metricHelpPageHtml("<script>"), /<script>/);
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

Expected: FAIL because `metricHelpPageHtml` does not exist.

- [ ] **Step 3: Implement page rendering and route dispatch**

```javascript
function metricHelpPageHtml(key) {
  const entry = metricGlossaryEntry(key);
  if (!entry) return "<main><h1>Metric documentation is unavailable</h1><p>Return to the viewer and select a documented metric.</p></main>";
  return `<main><a href="/viewer">Back to viewer</a><h1>${escapeHtml(entry.label)}</h1>`
    + `<p>${escapeHtml(entry.definition)}</p><h2>How to interpret it</h2>`
    + `<p>${escapeHtml(entry.interpretation)}</p><p><a href="${escapeHtml(entry.source)}" `
    + `target="_blank" rel="noopener noreferrer">Open external learning resource</a></p></main>`;
}
```

Before normal dashboard startup, detect `/viewer/help` with `location.pathname`, parse `metric` through `URLSearchParams`, replace `document.body.innerHTML` with this function’s result, and skip widget loading. Add a small, local stylesheet for the document page; do not add a remote font, stylesheet, script, or iframe.

- [ ] **Step 4: Verify Node and Python contracts**

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

Expected: PASS.

Run: `.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/portfolio/tests/test_local_viewer.py -q`

Expected: PASS; update the static viewer contract only if it requires explicit coverage of `/viewer/help`.

- [ ] **Step 5: Commit the documentation view**

```bash
git add openbb_platform/extensions/portfolio/assets/local_viewer/index.html openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs openbb_platform/extensions/portfolio/tests/test_local_viewer.py
git commit -m "feat(portfolio): add metric help documentation view" -m "Refs #1984"
```

### Task 4: Validate the reported F2 workflow and publish feedback resolution

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html` only if validation finds a scoped regression.

**Interfaces:**
- Consumes: final F2 layout, Node tests, Python viewer tests, and the local `/viewer` service.
- Produces: a BugContext status update and fix link for session `019ffdcb-1d5c-7190-b490-973405d4e917`.

- [ ] **Step 1: Run the complete focused test suite**

Run: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs && .venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/portfolio/tests/test_local_viewer.py -q`

Expected: both suites pass.

- [ ] **Step 2: Verify the reported F2 view live**

Open `http://127.0.0.1:6120/viewer`, choose F2: Financials, and verify that every scoped key-stat row and each of the Revenue, Net Income, and Net Margin legend items has a visible/focusable `?` control. Verify hover shows a short explanation; verify click opens `/viewer/help?metric=<key>` and the external resource link is labelled and opens separately.

- [ ] **Step 3: Check source safety and review the diff**

Run: `git grep -n -E "ak_[A-Za-z0-9]+" -- . ':!docs/superpowers/plans/2026-08-14-f2-metric-glossary-help.md' ; git diff origin/fix/pi-viewer-combo-recolor-lwc-nulls-gh-1982...HEAD --check`

Expected: no token matches and no whitespace errors.

- [ ] **Step 4: Commit any scoped validation correction**

```bash
git add <only files corrected during validation>
git commit -m "fix(portfolio): correct F2 metric help validation" -m "Refs #1984"
```

Only create this commit if a validation-discovered correction is necessary.

- [ ] **Step 5: Push and open the stacked pull request**

```bash
git push -u origin feat/pi-f2-metric-help-gh-1984
gh pr create --repo prajoria/OpenBB --base fix/pi-viewer-combo-recolor-lwc-nulls-gh-1982 --head feat/pi-f2-metric-help-gh-1984 --title "feat(portfolio): add F2 metric glossary help (#1984)" --body "## Summary
- Add contextual F2 metric explanations and a same-origin documentation view.
- Preserve existing widget-level help and omit uncurated metric mappings.

Closes #1984."
```

- [ ] **Step 6: Resolve BugContext feedback after the fix is published**

Set the feedback status to `fixed`, comment with the F2 behavior changed, and add the resulting commit and pull-request links.
