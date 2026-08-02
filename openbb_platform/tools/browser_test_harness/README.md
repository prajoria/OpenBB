# openbb-browser-test-harness

Dual-mode browser test harness for the OpenBB Portfolio Intelligence Terminal (EPIC #1634) and Techtrade Trading-Desk (EPIC #1691) Workspace apps.

**EPIC:** [#1721](https://github.com/prajoria/OpenBB/issues/1721)
**Design spec:** [`docs/superpowers/specs/2026-08-01-browser-test-harness-design.md`](../../../docs/superpowers/specs/2026-08-01-browser-test-harness-design.md)

## What's shipped in this PR (B0–B4)

- ✅ **B0 (#1722)** Package scaffold + `Step` / `Story` / `StepResult` data model + `Driver` Protocol
- ✅ **B1 (#1723)** Standalone HTTP driver (dynamic port, readiness gate, process-group cleanup, subprocess-env auth safety)
- ✅ **B2 (#1724)** Portfolio story (16 steps, W0–W9 mapped to NB01–NB08)
- ✅ **B3 (#1725)** Techtrade story (12 steps, T1–T6 mapped to NB01–NB06)
- ✅ **B4 (#1726)** Fixture-directory scaffold + initial parity/schema tests

## Still pending

- ⏳ **B5 (#1727)** Manual guide generator with per-step screenshots
- ⏳ **B6 (#1728)** Playwright workspace driver (persistent-context + CDP)
- ⏳ **B7 (#1729)** CI integration + close-out of [#1713](https://github.com/prajoria/OpenBB/issues/1713)

## Quickstart

```powershell
# Activate the project venv
H:\masterswork\git\OpenBB-Portfolio\OpenBB\.venv_portfolio\Scripts\Activate.ps1

# Install (editable)
pip install -e openbb_platform/tools/browser_test_harness/

# Run the portfolio story (standalone HTTP mode)
python -m openbb_browser_test_harness.run --story portfolio --mode standalone

# Run the techtrade story
python -m openbb_browser_test_harness.run --story techtrade --mode standalone

# Reports written to .dev-cycle/browser-harness-report/ by default
```

## Standalone mode invariants

- Subprocess spawns uvicorn on a dynamically-allocated `127.0.0.1` port (prevents 6120 collisions in CI)
- Readiness gate polls `/widgets.json` before running any step (10s timeout)
- `Popen.poll()` checked before every step's HTTP call → silent-failure guard
- Process-group termination on teardown (Windows `CREATE_NEW_PROCESS_GROUP`, POSIX `setsid`) → no orphaned uvicorn workers
- Refuses to run if parent env has conflicting `PI_WIDGET_BACKEND_*` set → no silent auth disable

## Testing

```powershell
# Unit tests (no subprocess)
pytest openbb_platform/tools/browser_test_harness/tests/ -v

# Live subprocess smoke (opt-in — spawns uvicorn)
BROWSER_HARNESS_LIVE=1 pytest openbb_platform/tools/browser_test_harness/tests/test_standalone_driver.py::test_standalone_driver_end_to_end -v
```

## Narrative alignment

Every step anchors to a specific notebook cell. See:

- Portfolio: `notebooks/portfolio/01-getting-started-and-providers.ipynb` → `…08-analyst-recommendations-basket.ipynb`
- Techtrade: `notebooks/techtrade/01-foundations-techtrade-and-analysis.ipynb` → `…06-audit-and-replay.ipynb`

The preview manual guides at `docs/browser_test_harness/preview_guides/*.md` render the same story a human tester can walk today.
