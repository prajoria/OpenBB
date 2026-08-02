# openbb-browser-test-harness

Dual-mode browser test harness for the OpenBB Portfolio Intelligence Terminal (EPIC #1634) and Techtrade Trading-Desk (EPIC #1691) Workspace apps.

**EPIC:** [#1721](https://github.com/prajoria/OpenBB/issues/1721)
**Design spec:** [`docs/superpowers/specs/2026-08-01-browser-test-harness-design.md`](../../../docs/superpowers/specs/2026-08-01-browser-test-harness-design.md)

## What's shipped

- ✅ **B0 (#1722)** Package scaffold + `Step` / `Story` / `StepResult` data model + `Driver` Protocol
- ✅ **B1 (#1723)** Standalone HTTP driver (dynamic port, readiness gate, process-group cleanup, subprocess-env auth safety)
- ✅ **B2 (#1724)** Portfolio story (16 steps, W0–W9 mapped to NB01–NB08)
- ✅ **B3 (#1725)** Techtrade story (12 steps, T1–T6 mapped to NB01–NB06)
- ✅ **B4 (#1726)** Fixture capture command + staleness enforcement tests
- ✅ **B5 (#1727)** Manual guide generator with per-step screenshot embedding
- ✅ **B6 (#1728)** Playwright workspace driver (persistent-context + CDP attach)

## Still pending

- ⏳ **B7 (#1729)** CI integration + close-out of [#1713](https://github.com/prajoria/OpenBB/issues/1713)

## Quickstart

```powershell
# Activate the project venv
H:\masterswork\git\OpenBB-Portfolio\OpenBB\.venv_portfolio\Scripts\Activate.ps1

# Install (editable, with playwright)
pip install -e openbb_platform/tools/browser_test_harness/[workspace]
python -m playwright install chromium

# Run the portfolio story (standalone HTTP mode, CI-friendly)
python -m openbb_browser_test_harness.run --story portfolio --mode standalone

# Run the techtrade story
python -m openbb_browser_test_harness.run --story techtrade --mode standalone

# Run against a real Workspace (opens Chromium; log in on first run)
python -m openbb_browser_test_harness.run --story portfolio --mode workspace

# Capture screenshots for the manual guide (workspace mode)
python -m openbb_browser_test_harness.run \
    --story portfolio --mode workspace --capture-guide-screenshots

# Regenerate the manual guide from the Story
python -m openbb_browser_test_harness.emit_guide --story both

# Capture fresh endpoint fixture snapshots
python -m openbb_browser_test_harness.snapshot
```

## Standalone mode invariants

- Subprocess spawns uvicorn on a dynamically-allocated `127.0.0.1` port (prevents 6120 collisions in CI)
- Readiness gate polls `/widgets.json` before running any step (10s timeout)
- `Popen.poll()` checked before every step's HTTP call → silent-failure guard
- Process-group termination on teardown (Windows `CREATE_NEW_PROCESS_GROUP`, POSIX `setsid`) → no orphaned uvicorn workers
- Refuses to run if parent env has conflicting `PI_WIDGET_BACKEND_*` set → no silent auth disable

## Workspace mode invariants

- **persistent-context (default):** Chromium profile at `~/.openbb_browser_test_harness/chrome_profile/`. First-run opens a browser window for user login; auth cookies persist.
- **cdp-attach:** user launches Chrome with `--remote-debugging-port=9222`; harness attaches without owning the browser.
- **Screenshot capture:** `page.screenshot()` only — never OS-level. Browser chrome (tab title, URL bar) is outside the frame by construction.
- **SHA-256 per screenshot** recorded in `report.json` for future baseline diff.
- **PII guard on output path** — refuses to write a screenshot whose path contains a `daaji`/`Users/<username>` fragment.

## Testing

```powershell
# Unit tests (no subprocess, no browser)
pytest openbb_platform/tools/browser_test_harness/tests/ -v

# Live subprocess smoke (opt-in — spawns uvicorn)
$env:BROWSER_HARNESS_LIVE = "1"
pytest openbb_platform/tools/browser_test_harness/tests/test_standalone_driver.py::test_standalone_driver_end_to_end -v

# Live fixture staleness (opt-in — spawns uvicorn + diffs fixtures)
pytest openbb_platform/tools/browser_test_harness/tests/test_fixtures_are_current.py::test_fixtures_are_current -v
```

## Narrative alignment

Every step anchors to a specific notebook cell. See:

- Portfolio: `notebooks/portfolio/01-getting-started-and-providers.ipynb` → `…08-analyst-recommendations-basket.ipynb`
- Techtrade: `notebooks/techtrade/01-foundations-techtrade-and-analysis.ipynb` → `…06-audit-and-replay.ipynb`

The auto-generated manual guides at `guides/*.md` render the same story a human tester can walk.
