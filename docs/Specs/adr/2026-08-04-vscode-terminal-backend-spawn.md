# ADR: Canonical Backend Spawn + Readiness Endpoint for VS Code Terminal

- **Status:** Accepted
- **Date:** 2026-08-04
- **Deciders:** Portfolio Intelligence Engine team
- **Refs:** EPIC #1806 (VS Code Trading Terminal Extension), Feature #1807
  (Phase-0 hard-gate docs), Issue #1808 (this ADR).
- **Supersedes text in:** `docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md`
  §7 architecture diagram and §14.1 back-end lifecycle.

## 1. Context

The VS Code Trading Terminal extension (EPIC #1806) needs to spawn a local
OpenBB backend that serves every widget the terminal renders — the 60+
`pi_*` Portfolio-Intelligence widgets, the `tt_*` TechTrade widgets, and the
core REST surface used by notebook / Python integrations. The PRD's original
§7 diagram collapsed this into a single `uvicorn :8000` — but the codebase
actually ships **three** distinct backend surfaces today:

1. **Core REST API** — `openbb_core.api.rest_api:app`. This is what
   `desktop/src/pi/sdk/client.ts` defaults to at
   `http://127.0.0.1:8000`. It exposes `/api/v1/…` but does **not**
   mount the widget routers (`/widgets.json`, `/pi/*`, `/tt/*`).
2. **Portfolio-Intel widget backend** — a separate FastAPI app at
   `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/main.py`,
   serving `/widgets.json`, `/apps.json`, `/pi/*` on **port 6120** with
   CORS locked to `https://pro.openbb.co` and bearer-token auth.
3. **MCP server** — `openbb-mcp` on `:8001`, spawned alongside the desktop
   app.

The Tauri desktop app (`desktop/src-tauri/src/tauri_handlers/startup.rs`)
sidesteps this fragmentation by spawning `openbb-api --host 127.0.0.1
--port 6900`, which **merges the widget routers** into the core app. That
merged binary is the only one that can serve `/widgets.json` and every
`pi_*` / `tt_*` widget from a single port.

The PRD also referenced a `GET /healthz` route as the readiness gate. That
route does not exist in the platform today.

## 2. Decision

### 2.1 Canonical spawn

The VS Code extension's back-end lifecycle (PRD §14.1) MUST spawn:

```bash
openbb-api --host 127.0.0.1 --port 6900
```

- Binary: `openbb-api` (installed by `openbb_platform/pyproject.toml`
  extras), resolved via the configured `openbb.pythonPath`'s
  `Scripts/openbb-api` (Windows) or `bin/openbb-api` (POSIX).
- Host: `127.0.0.1` — loopback only, never bind `0.0.0.0`.
- Port: **6900** (fixed default; configurable via `openbb.apiPort`).

### 2.2 Port choice — 6900 vs 8765

We considered both. **6900 wins.** Rationale:

- 6900 is the port the Tauri desktop app already spawns. Reusing it means
  a user who has the desktop app already running has an already-warm
  backend the extension can attach to (readiness probe returns 200
  immediately; no double-spawn). This is the entire point of aligning
  with the desktop path.
- 6900 avoids the 8000 collision with manual `uvicorn openbb_core.api.rest_api:app`
  invocations that developers routinely run in a terminal — which was the
  strongest argument for 8765. The alternative port 8765 would sidestep
  8000 but *also* fragment from the desktop app, forcing a second
  parallel backend if both are open.
- Trade-off accepted: if a user runs Tauri + VS Code simultaneously with
  different backend configurations (e.g. distinct API keys), they must
  either accept a shared backend or override `openbb.apiPort`. Documented
  in PRD §14.1.

### 2.3 Readiness gate

The extension's health probe MUST be:

```
GET http://127.0.0.1:6900/widgets.json
```

- **Ready** iff HTTP 200 with a JSON body that parses.
- Poll interval: 2 s during startup (timeout 60 s), 10 s while running.
- Two consecutive non-200 or non-JSON responses → state transitions to
  `error` (PRD §14.1 stop/error paths unchanged).

Rationale: `/widgets.json` is the readiness gate the existing browser
test harness uses
(`openbb_platform/tools/browser_test_harness/src/openbb_browser_test_harness/drivers/standalone_driver.py`).
Reusing it means the VS Code extension and the harness share one probe
contract — a `/widgets.json` regression breaks both at once, not silently
in only one.

### 2.4 Provider-health surface

For provider-tier / API-key / rate-limit visibility (used by the "Back-end
Status" TreeView, PRD §8.4), the extension MUST call:

```
GET http://127.0.0.1:6900/pi/health/providers
```

- Route: defined in
  `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py`.
- Response: markdown body summarising provider tier / plan-limited state.
- Poll interval: on-demand (TreeView refresh), not a continuous poll.

The extension MUST NOT treat `/pi/health/providers` as a liveness probe —
it is a diagnostic surface layered on top of the `/widgets.json`
readiness gate.

## 3. Rejected Alternatives

### 3.1 `python -m uvicorn openbb_core.api.rest_api:app` (bare core)

Rejected. The bare core REST app does not mount the widget routers, so
`/widgets.json` returns 404 and every `pi_*` / `tt_*` widget endpoint is
unreachable. This is the topology the PRD's original §7 diagram implied
and it does not satisfy the terminal's Path-A widget-rendering
requirement.

### 3.2 Spawn the standalone PI widget backend on `:6120`

Rejected. The `widget_backend/main.py` app is deliberately CORS-locked
to `https://pro.openbb.co` and requires bearer-token auth. Repurposing
it for a loopback VS Code Webview would require weakening its CORS
policy and auth expectations for a use case it was not designed for.
The `openbb-api` merged spawn achieves the same widget coverage without
disturbing the pro.openbb.co-facing surface.

### 3.3 Spawn all three servers (core :8000, PI :6120, MCP :8001)

Rejected. Three lifecycles to monitor, three failure modes to surface in
the status bar, three ports to configure, three CORS surfaces to
reconcile. Users would see triple resource cost with no incremental
capability over the single `openbb-api` spawn.

### 3.4 Invent a new `/healthz` route

Rejected. Adding a new route for a probe when `/widgets.json` already
provides the exact same signal (200 + parseable JSON iff the app is
serving) creates two liveness contracts that will drift.

## 4. Consequences

### 4.1 PRD updates required (tracked under Feature #1807)

- **§7 architecture diagram.** Replace the `uvicorn :8000` box with an
  `openbb-api :6900` box that explicitly shows the widget-router merge.
  Remove the standalone `:6120` and `:8001` boxes from the extension's
  spawn scope; if depicted, mark them as *external / desktop-app-owned*.
- **§14.1 lifecycle text.** Rewrite the start sequence to spawn
  `openbb-api --host 127.0.0.1 --port {port}` (default 6900). Replace
  every `/healthz` reference with `/widgets.json` for liveness and
  `/pi/health/providers` for provider health. Update the poll cadence
  wording to match §2.3 above.
- **§14.2 API base URL.** Change default `openbb.apiBaseUrl` from
  `http://127.0.0.1:8000` to `http://127.0.0.1:6900`.

### 4.2 Extension implementation impact

- Back-end lifecycle module resolves `openbb-api` from the configured
  Python interpreter's `Scripts/` or `bin/` directory rather than
  invoking `python -m uvicorn`.
- Health poller uses `/widgets.json` as the probe; response parser MUST
  validate that the body is JSON (not just HTTP 200), because a
  misconfigured reverse proxy could return 200 + HTML.
- "Back-end Status" TreeView (§8.4) gains a provider-health section
  backed by `/pi/health/providers`.
- If `openbb-api` is not present in the interpreter, the extension MUST
  surface a specific error ("openbb-api CLI not found — install with
  `pip install openbb[api]`") rather than a generic spawn failure.

### 4.3 Non-consequences

- No change to widget SDK registry (`desktop/src/pi/sdk/registry.ts`).
- No change to the pro.openbb.co-facing PI widget backend or its CORS
  posture.
- No change to MCP `:8001` spawn ownership — that remains desktop-only
  for now; a future ADR may extend it to VS Code.
