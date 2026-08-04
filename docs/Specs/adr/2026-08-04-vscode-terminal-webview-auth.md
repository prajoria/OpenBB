# ADR: VS Code Terminal — Webview → openbb-api Authentication Model

**Status:** Accepted
**Date:** 2026-08-04
**Decision owner:** Portfolio Intelligence Engine (Project #4)
**Closes:** #1809
**Related:** #1807 (Feature — Phase 0), #1806 (EPIC), #1808 (backend spawn ADR — picks `openbb-api`), #1810 (rendering-model ADR)

---

## 1. Context

PRD `docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md` §21.3 flagged
"Webview ↔ backend security" as a **Phase-1 gate, not a footnote,** on the
assumption that the extension would talk to the PI widget backend
(`main.py` on `:6120`). That surface locks CORS to
`https://pro.openbb.co` and requires a bearer token
(`PI_WIDGET_BACKEND_TOKEN`, or explicit `PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev`
opt-out — see
`openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/_app.py:15`
and `_shared.py:23`). A `vscode-webview://…` origin would be CORS-rejected
against that list.

**ADR #1808 changed the target surface.** The canonical backend spawn is
`openbb-api --host 127.0.0.1 --port 6900` (the same binary the Tauri
desktop app spawns). `openbb-api` is the core FastAPI app in
`openbb_platform/core/openbb_core/api/rest_api.py` — its CORS defaults are
set at
`openbb_platform/core/openbb_core/app/model/api_settings.py:11`:

```python
allow_origins: list[str] = Field(default_factory=lambda: ["*"])
```

`allow_origins=["*"]` combined with loopback binding **removes the CORS
rejection entirely**, and the core app does **not** require a bearer token
by default. That is the entire security surface the extension inherits.
The Phase-0 spike planned in §21.3 therefore has a different shape than
the PRD anticipated: instead of proving the auth challenge can be solved,
it needs to record that the ADR-#1808 choice made the challenge disappear
and decide whether defense-in-depth is worth adding back.

## 2. Decision

The VS Code extension's webview authenticates against `openbb-api` on
`http://127.0.0.1:6900` using **no token** in v1. The security posture is:

| Layer | Control |
|---|---|
| Network reachability | `openbb-api` binds `127.0.0.1` only — inaccessible from the local network. Loopback is the primary security boundary. |
| CORS | Core-API default `allow_origins=["*"]`; unchanged. `vscode-webview://…` origin is not rejected. |
| Token / bearer | **None required.** The extension does not inject `Authorization: Bearer …` on any `fetch` or `EventSource` in v1. |
| Multi-user contention | Single user per machine; concurrent VS Code + Tauri desktop sessions share the backend by design (see ADR-#1808 §2.2 trade-off). |

### 2.1 Rationale

- **Loopback is the primary control.** An attacker with local process
  execution can already read `~/.openbb_platform/user_settings.json`
  (containing FMP/FRED keys), so a per-request bearer against a loopback
  socket does not raise the bar. It only adds config complexity.
- **`vscode-webview://` origin has no cross-site risk against loopback.**
  Standard-web CSRF concerns assume an attacker page can trigger a
  cross-origin request. A `vscode-webview://` context is opened only by
  the extension host on the user's machine; there is no attacker page in
  the trust model.
- **ADR-#1808 already committed to the desktop-parity spawn.** The Tauri
  desktop app does not inject a token either. Requiring one in the VS Code
  extension would fragment behaviour between the two hosts and break the
  "attach to already-running backend" ergonomics that motivated the port-6900
  reuse in ADR-#1808 §2.2.

### 2.2 CSP

The webview CSP (PRD §17.3, updated by #1817) MUST include:

```
connect-src http://127.0.0.1:6900 ws://127.0.0.1:6900
script-src 'nonce-{nonce}'
style-src 'nonce-{nonce}' 'unsafe-inline'
```

`connect-src` is loopback-only. `style-src 'unsafe-inline'` is required
by Recharts / Plotly per PRD review comment #10 (#1817).

### 2.3 SSE

For streaming endpoints (paper execution status, live price feed —
PRD §9.4), the webview uses `EventSource` directly:

```typescript
const es = new EventSource("http://127.0.0.1:6900/api/v1/portfolio_intel/paper/stream");
```

No token, no query-parameter workaround. `EventSource` cannot set custom
headers, but with no auth required, the standard usage suffices. If a
future ADR reverts this decision, the query-parameter transport pattern
from PRD Appendix C7 becomes the fallback.

## 3. Consequences

- **PRD §14, §15, §17.3 update** — extension host does NOT read a token
  from `user_settings.json`; PRD §15.1 sentence "The extension does not
  store credentials itself" is stronger under this ADR — the extension
  neither stores nor forwards credentials.
- **Risk register** — PRD §19 R1 "Webview CSP blocks live data fetch"
  drops from Medium/High to **Low/Medium** (only real CSP concerns remain,
  covered by §2.2 above).
- **Trade-off explicitly accepted**: any user with local process execution
  on the machine can hit `http://127.0.0.1:6900` and read any widget
  endpoint. This is the same posture the Tauri desktop app has today, and
  is judged acceptable for the v1 fork-internal audience (see PRD §3 N4:
  no VS Code Marketplace publish; no untrusted-user threat model).
- **Extension test discipline** — because no auth code runs on the happy
  path, the Phase-1 CI harness (#1817 CSP + this ADR) will fail if a future
  PR silently adds bearer injection without also adding coverage for the
  no-token loopback case. Explicit test in the extension test runner
  (#1840) MUST assert no `Authorization` header is sent by default.

## 4. Rejected alternatives

### 4.1 Add `PI_WIDGET_BACKEND_TOKEN`-style auth to `openbb-api`

**Rejected.** It fragments from the Tauri desktop path (which doesn't
require it), doubles the config surface for zero real threat reduction
against a loopback-only socket, and creates the URL-parameter-in-SSE
smell that PRD Appendix C7 flagged. Revisit only if:

- The extension is published to the VS Code Marketplace (v2+, currently a
  hard PRD Non-Goal N4), OR
- The backend acquires a non-loopback bind for cloud/remote scenarios, OR
- A concrete threat surfaces from another local process on the same host
  that we cannot dismiss.

### 4.2 Retarget the PI widget backend on `:6120` (locked CORS + required token)

**Rejected by ADR-#1808.** The widget backend does not merge the core
`/api/v1/*` routes; without those routes, PRD §12.1 commands like
`openbb.runAnalysis` cannot POST to core endpoints. Reproducing the
route-merge inside the widget backend would duplicate what `openbb-api`
already does correctly.

### 4.3 A per-session ephemeral token minted by the extension host on backend spawn

**Rejected as v1 gold-plating.** Attractive in theory (token lives only
as long as the VS Code session) but requires either (a) a new
`openbb-api` config flag to accept a random token at boot, or (b)
retrofitting a middleware. Both are out of scope until a threat justifies
the code cost. Keep the design open by not shipping a token — adding one
later is strictly easier than removing one.

## 5. Verification

The following assertions MUST hold on every future PR touching the
extension:

1. `grep -rE 'Authorization:\s*Bearer' apps/vscode-terminal-extension/` returns
   nothing on the default happy path (a match indicates an ADR-drift PR).
2. Webview `fetch` calls target `http://127.0.0.1:${openbb.apiPort}` only.
3. `EventSource` connections do not carry a query-parameter token.
4. The `connect-src` CSP entry references only loopback.

These are enforced by the Phase-1 extension test runner scaffolded in
#1840.

## 6. Follow-ups

- **#1817** — CSP: the `connect-src` / `style-src` values in this ADR
  become the exact values that ticket ships.
- **#1819** — Backend lifecycle: uses this ADR's "no token" outcome to
  simplify the spawn command (no env-var injection needed for auth).
- **#1820** — Live-data mode: does NOT need a token-injection strategy;
  the widgets talk to loopback directly.

## 7. References

- ADR-#1808 — canonical backend spawn (chose `openbb-api :6900`)
- ADR-#1810 — Path A widgets.json renderer (defines how widgets are called)
- PRD `docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md` §14, §15, §17.3, §21.3
- `openbb_platform/core/openbb_core/app/model/api_settings.py:11` — CORS default
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/_app.py:15` — widget backend CORS (rejected target)
- `desktop/src-tauri/src/tauri_handlers/startup.rs` — Tauri desktop spawn (parity reference)
