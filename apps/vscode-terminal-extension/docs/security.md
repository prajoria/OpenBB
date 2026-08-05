# Security posture — OpenBB Terminal VS Code extension

Last updated: 0.0.32 (#1856).

## Workspace-trust model

The extension declares
`capabilities.untrustedWorkspaces = { supported: "limited" }` in
`package.json`. Both trusted and untrusted workspaces load the
extension, but the untrusted path is deliberately degraded:

| Behavior                                | Trusted | Untrusted |
| --------------------------------------- | ------- | --------- |
| `openbb.pythonPath` honored             | ✅       | ❌ ignored |
| `openbb.userSettingsPath` honored       | ✅       | ❌ ignored |
| `openbb.autoStartBackend` honored       | ✅       | ❌ forced off |
| Backend spawn (`BackendLifecycle.start`) | ✅       | ❌ refused (spawn-only; attach to a pre-running backend still works via readiness probe) |
| Webview panels / read-only widget UX     | ✅       | ✅ |

In an untrusted workspace the user can still open the terminal, browse
widgets, and connect to a backend that is already running on
`127.0.0.1` — but no Python process is spawned from workspace-supplied
paths, and no workspace-scoped credential file location is trusted.

## `openbb.apiBaseUrl` loopback constraint

Every activation runs `isSafeApiBaseUrl` (`src/security/validation.ts`).
A configured URL must:

- Parse via `new URL()`.
- Use `http:` or `https:`.
- Resolve to `127.0.0.1`, `::1`, or `localhost` (IPv6 brackets are
  stripped before comparison).

A rejection logs a `[security] rejected apiBaseUrl …` warning to the
extension console and falls the value back to
`http://127.0.0.1:${apiPort}`. To override the default per-machine, set
`openbb.apiBaseUrl` in **User** settings — the `machine` scope on the
property prevents workspace `settings.json` from overriding it.

## Machine-scope rationale

The following configuration properties are declared `"scope": "machine"`
so they cannot be silently overridden by a workspace `settings.json`:

- `openbb.pythonPath` — resolved to a spawn target
- `openbb.apiBaseUrl` — network target for readiness / health probes
- `openbb.userSettingsPath` — path to the credentials file
- `openbb.autoStartBackend` — controls whether spawn happens on
  `onStartupFinished`
- `openbb.autoRestartBackend` / `openbb.autoRestartMaxAttempts` — control
  the auto-restart loop

Users may still override any of these in User settings; the guard is
specifically against a cloned repo's `.vscode/settings.json`.

## Credentials file (`user_settings.json`) hardening

`ApiKeyManager.writeSettings` now:

- Writes the target with `mode: 0o600` and follows up with a chmod
  (defense-in-depth for platforms where the mode arg is ignored).
- `chmod 0600` on the `.bak` immediately after rename.
- Deletes the `.bak` once the new write succeeds (opt-out via
  `{ deleteBak: false }`, used by tests).

The credentials value itself is never accepted, echoed, or logged by
the extension — the user types the value directly into their editor.

## Findings closed in 0.0.32

- **HIGH** — arbitrary code execution via workspace-scoped `pythonPath`
  (closed by machine scope + untrusted-workspace clear + spawn refusal).
- **HIGH** — workspace-scoped `userSettingsPath` redirect (closed by
  machine scope + untrusted-workspace clear).
- **MEDIUM** — SSRF via `apiBaseUrl` (closed by `isSafeApiBaseUrl`
  loopback constraint + machine scope).
- **MEDIUM** — credentials file `.bak` left behind and world-readable
  (closed by 0o600 mode + chmod + post-write cleanup).

## Related ADRs / tickets

- ADR: `docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md` — the
  no-token, loopback-only webview auth model that this hardening
  protects.
- #1809 — original ADR discussion.
- #1819 — backend-spawn ticket that this issue extends.
