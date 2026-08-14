# Task 3 Report

## Scope
- Implemented Task 3 only for `#1984 (feat(portfolio): add F2 metric glossary help)`.
- Added the same-origin metric documentation view at `/viewer/help?metric=...`.

## Files changed
- `openbb_platform/extensions/portfolio/assets/local_viewer/index.html`
- `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`
- `openbb_platform/extensions/portfolio/tests/test_local_viewer.py`
- `openbb_platform/extensions/portfolio/openbb_portfolio/local_viewer.py`

## TDD evidence
- Failing run:
  - Command: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`
  - Result: FAIL — `function metricHelpPageHtml not found in index.html`
- Passing run:
  - Command: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`
  - Result: PASS (77 tests)

## Implementation
- Added `metricHelpPageHtml(key)` to build a safe documentation page from the curated glossary.
- Added a local, inline-only help-page style treatment with no new remote assets, scripts, fonts, iframes, or stylesheets.
- Added a forgiving `net_margin -> net_margin_pct` alias so the help route tolerates the brief's shorthand while still serving the real widget key.
- Added `renderMetricHelpRoute()` so `/viewer/help` renders the help document before dashboard/chat boot and skips widget loading.
- Added the same HTML shell route at `/viewer/help` in the FastAPI router so the help page is truly same-origin and bookmarkable.
- Added Python contract coverage for the help route dispatch markers.

## Validation
- Command: `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`
  - Result: PASS (77 tests)
- Command: `.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/portfolio/tests/test_local_viewer.py -q`
  - Result: PASS (8 tests)

## Self-review
- Reviewed the scoped diff for the viewer asset, route, and focused tests.
- Confirmed unrelated pre-existing changes in `openbb_platform/core/openbb/assets/reference.json` and `openbb_platform/core/openbb/package/__init__.py` were left untouched.

## Commit
- Recorded in the latest commit on this branch.
- Message: `feat(portfolio): add metric help documentation view`
- Trailer: `Refs #1984`
- Trailer: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## Concerns
- The brief named only the viewer asset/tests, but serving `/viewer/help` same-origin required a minimal router update in `openbb_platform/extensions/portfolio/openbb_portfolio/local_viewer.py`; without it the new help URL would 404.
