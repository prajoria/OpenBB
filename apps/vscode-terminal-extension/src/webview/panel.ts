// Webview host for the OpenBB Terminal.
//
// Owns the panel lifecycle, the API-base-URL injection (§14.2), and
// the extension-host <-> webview postMessage bridge. CSP directives
// live in ./csp.ts (#1817).

import * as vscode from "vscode";
import { buildCsp, generateNonce } from "./csp";

const API_BASE = "http://127.0.0.1:6900";

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

function handleMessage(msg: WebviewMessage): void {
  const channel = getOutputChannel();
  channel.appendLine(`webview -> host: ${msg.type}`);
}

function renderHtml(
  context: vscode.ExtensionContext,
  panel: vscode.WebviewPanel,
): string {
  const nonce = generateNonce();
  const csp = buildCsp({ apiBase: API_BASE, nonce });
  const mediaUri = panel.webview.asWebviewUri(
    vscode.Uri.joinPath(context.extensionUri, "media"),
  );
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
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
