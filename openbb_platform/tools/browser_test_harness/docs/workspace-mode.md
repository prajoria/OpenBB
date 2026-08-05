# Workspace mode (Playwright driver)

Workspace mode drives the real OpenBB Workspace UI at `pro.openbb.co` via a
Playwright-controlled Chromium session with a persistent user profile.

Tracked in [#1789](https://github.com/prajoria/OpenBB/issues/1789).

## Contract

- **Persistent Chrome profile.** Cookies live under
  `~/.openbb_browser_test_harness/chrome_profile/`. First run opens
  Chromium visibly so the operator can log in to `pro.openbb.co`;
  subsequent runs reuse the session.
- **Random ephemeral backend port.** When `backend_url` is not passed,
  `WorkspaceDriver.setup()` calls `_pick_random_port()`
  (`socket.bind((127.0.0.1, 0))`) and spawns
  `uvicorn openbb_portfolio_intel.widget_backend.main:app` on it. The URL
  is appended as a `?backend_url=` query param on the Workspace
  navigation so the UI resolves widget requests against the isolated
  backend.
- **Attach mode.** Passing an explicit `backend_url=` (for example, when
  the operator is already running `openbb.sh api` on a known port)
  skips the spawn — the driver only owns the browser.
- **Teardown owns what it spawned.** The backend uvicorn is terminated
  on teardown only if the driver spawned it; attach-mode processes are
  left alone.

## Why random ports?

The manual dev loop uses `openbb.sh api` bound to port `8000`. Hardcoding
the harness to the same port would collide with a running dev server
(mysterious 401s, mismatched CORS, cross-session state) or with a
concurrent harness invocation. `bind(0)` asks the kernel for a
guaranteed-free ephemeral port per run — no collision surface.

## Local run

```powershell
.\.venv_portfolio\Scripts\Activate.ps1
pip install -e openbb_platform/tools/browser_test_harness/[workspace]
python -m playwright install chromium

# Unit-level tests (no Chromium required)
pytest openbb_platform/tools/browser_test_harness/tests/test_workspace_driver.py -v -m "not integration"

# Live smoke — requires operator login on first run
$env:RUN_WORKSPACE_HARNESS = "1"
pytest openbb_platform/tools/browser_test_harness/tests/test_workspace_driver.py -v
```

## Debugging

Insert `await page.pause()` inside a step and re-run non-headless. This
opens the Playwright Inspector so you can step through selectors and
network traffic interactively.

For CI runs, the `workspace-harness` job in
`.github/workflows/browser-harness.yml` is `workflow_dispatch`-only and
reads the workspace URL from the `OPENBB_WORKSPACE_URL` repo secret;
the secret is **never** written into this file or committed anywhere.

## See also

- Manual guide: [`guides/portfolio-manual-guide.md`](../guides/portfolio-manual-guide.md)
- Standalone driver: `src/openbb_browser_test_harness/drivers/standalone_driver.py`
