# OpenBB Terminal — VS Code Extension

Embeds the OpenBB trading terminal inside VS Code: activity-bar tree
views for Layouts, Widget Browser, and Back-end Status; a webview-hosted
terminal panel with 5 built-in and 4 curated golden layouts; a
symbol-context bus tied to widget inputs, Python hovers, notebook
source text, and editor selections; and a loopback-only Python back-end
supervised by the extension.

## Install

The end-user walkthrough — prerequisites, installation, first run,
every command, keybinding, and setting, plus troubleshooting — lives in
[`docs/user-guide.md`](docs/user-guide.md).

Two supported install paths:

- **Extension Development Host.** `cd apps/vscode-terminal-extension &&
  npm install && npm run compile`, then press `F5` in VS Code.
- **Sideload.** `npm run package` produces a `.vsix`; install with
  `code --install-extension openbb-terminal-vscode-<version>.vsix`.

See the user guide for the full flow including Path B (attaching to a
user-managed `openbb-api` process on loopback port 6900).

## Develop

```bash
cd apps/vscode-terminal-extension
npm install
npm run compile
# then press F5 in VS Code to launch an Extension Development Host
npm test               # node:test unit suites
npm run test:all       # unit + snapshot + fixture round-trip + auth-invariant grep guards
```

Architecture, non-functional requirements, and the design rationale
are locked in the PRD and three ADRs:

- [`docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md`](../../docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md)
- [`docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md`](../../docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md)
- [`docs/Specs/adr/2026-08-04-vscode-terminal-rendering-model.md`](../../docs/Specs/adr/2026-08-04-vscode-terminal-rendering-model.md)
- [`docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md`](../../docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md)

## License

AGPL-3.0. This is a research and non-commercial-use extension — see
the repository root `LICENSE` for the full terms and the
non-commercial-use reminder.
