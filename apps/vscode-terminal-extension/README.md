# OpenBB Terminal — VS Code Extension

Phase 1 scaffold for the OpenBB Trading Terminal running inside VS Code.
See the PRD (`docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md`) §1
for the product vision.

At this checkpoint (#1813) the extension provides only:

- an activation entry point,
- the `OpenBB: Open Terminal` command (stub — shows a placeholder
  information message),
- an activity-bar container with three empty tree views (Layouts,
  Widget Browser, Back-end Status).

The webview host, theme bridge, layout engine, and CSP hardening land in
follow-up Phase 1 issues (#1814-#1817). Backend spawn, rendering model,
and auth posture are locked by the Phase 0 ADRs:

- `docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md`
- `docs/Specs/adr/2026-08-04-vscode-terminal-rendering-model.md`
- `docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md`

## Development

```bash
cd apps/vscode-terminal-extension
npm install
npm run compile
# then press F5 in VS Code to launch an Extension Development Host
```
