// Webview host for the OpenBB Terminal (#1814).
//
// Owns the panel lifecycle, the placeholder CSP (real one lands in
// #1817), the API-base-URL injection (§14.2), and the extension-host
// <-> webview postMessage bridge. The real React canvas mounts in
// #1816; for now, `media/canvas.js` proves the round-trip.

import { randomBytes } from "node:crypto";
import * as vscode from "vscode";

const API_BASE = "http://127.0.0.1:6900";
const WS_BASE = "ws://127.0.0.1:6900";

interface WebviewMessage {
  type: string;
  [key: string]: unknown;
}

let outputChannel: vscode.OutputChannel | undefined;

function getOutputChannel(): vscode.OutputChannel {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel("OpenBB Terminal");
  }
  return outputChannel;
}

/** Per-panel cryptographic nonce for the placeholder CSP. */
function makeNonce(): string {
  return randomBytes(16).toString("hex");
}

/**
 * Build the Content-Security-Policy meta content string. Exported so
 * unit tests can assert the shape without spinning up a webview.
 * Full CSP tightening is tracked by #1817.
 */
export function computeCsp(nonce: string): string {
  return (
    `default-src 'none'; ` +
    `script-src 'nonce-${nonce}'; ` +
    `style-src 'nonce-${nonce}' 'unsafe-inline'; ` +
    `connect-src ${API_BASE} ${WS_BASE}; ` +
    `img-src 'self' data:;`
  );
}

function handleMessage(msg: WebviewMessage): void {
  const channel = getOutputChannel();
  channel.appendLine(`webview -> host: ${msg.type}`);
}

function renderHtml(
  context: vscode.ExtensionContext,
  panel: vscode.WebviewPanel,
): string {
  const nonce = makeNonce();
  const csp = computeCsp(nonce);
  const mediaUri = panel.webview.asWebviewUri(
    vscode.Uri.joinPath(context.extensionUri, "media"),
  );
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <!-- TODO(#1817): CSP finalized in #1817 -->
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <title>OpenBB Terminal</title>
  <script nonce="${nonce}">
    window.__OPENBB_API_BASE__ = "${API_BASE}";
  </script>
</head>
<body>
  <div>Webview host ready — canvas mounted in #1816</div>
  <div id="root"></div>
  <script nonce="${nonce}" src="${mediaUri}/canvas.js"></script>
</body>
</html>`;
}

/**
 * Open (or focus) the OpenBB Terminal webview panel.
 *
 * `layoutId` is currently unused; the layouts registry lands in #1816
 * and will drive the initial view once available.
 */
export function openTerminalPanel(
  context: vscode.ExtensionContext,
  layoutId?: string,
): vscode.WebviewPanel {
  void layoutId;
  const panel = vscode.window.createWebviewPanel(
    "openbb.terminal",
    "OpenBB Terminal",
    vscode.ViewColumn.One,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [
        vscode.Uri.joinPath(context.extensionUri, "media"),
      ],
    },
  );

  panel.webview.html = renderHtml(context, panel);
  panel.webview.onDidReceiveMessage((msg: WebviewMessage) =>
    handleMessage(msg),
  );

  return panel;
}

/** Post a symbol-change event to the webview (host -> webview). */
export function postSymbolChange(
  panel: vscode.WebviewPanel,
  symbol: string,
): Thenable<boolean> {
  return panel.webview.postMessage({ type: "symbolChange", symbol });
}

/** Post a theme-change event carrying design tokens to the webview. */
export function postThemeChange(
  panel: vscode.WebviewPanel,
  tokens: Record<string, string>,
): Thenable<boolean> {
  return panel.webview.postMessage({ type: "themeChange", tokens });
}
