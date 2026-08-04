// Single-widget preview panel (#1832).
//
// Renders a lone widget from the fixture manifest inside a webview.
// Reuses the Path-A renderer (media/renderer.js) so preview parity with
// the terminal canvas is guaranteed. CSP + nonce come from
// ../webview/csp.ts — same shape as the main panel.

import * as vscode from "vscode";
import { buildCsp, generateNonce } from "../webview/csp";
import type { WidgetMeta } from "../layouts/types";

const API_BASE = "http://127.0.0.1:6900";

function escapeHtml(s: string): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Build the preview panel HTML.
 *
 * Exported so tests can exercise the template without a live vscode
 * WebviewPanel instance.
 */
export function buildPreviewHtml(
  widgetMeta: WidgetMeta,
  nonce: string,
  cspSource: string,
  apiBase: string,
  rendererUri: string,
  previewUri: string,
): string {
  const csp = buildCsp({ apiBase, nonce });
  void cspSource;
  const name = escapeHtml(widgetMeta.name);
  const id = escapeHtml(widgetMeta.id);
  const type = escapeHtml(String(widgetMeta.type));
  const endpoint = escapeHtml(widgetMeta.endpoint);
  const category = escapeHtml(widgetMeta.category);
  const widgetJson = escapeHtml(JSON.stringify(widgetMeta));
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <title>Preview: ${name}</title>
  <style nonce="${nonce}">
    body { font-family: var(--vscode-font-family); padding: 12px; }
    header.preview-header { border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 8px; margin-bottom: 12px; }
    header.preview-header h1 { margin: 0 0 4px 0; font-size: 1.1em; }
    header.preview-header dl { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0; font-size: 0.9em; }
    header.preview-header dt { color: var(--vscode-descriptionForeground); }
    #widget-root { display: block; }
  </style>
</head>
<body>
  <header class="preview-header">
    <h1>${name}</h1>
    <dl>
      <dt>ID</dt><dd>${id}</dd>
      <dt>Type</dt><dd>${type}</dd>
      <dt>Endpoint</dt><dd>${endpoint}</dd>
      <dt>Category</dt><dd>${category}</dd>
    </dl>
  </header>
  <div id="widget-root"></div>
  <script nonce="${nonce}">
    window.__OPENBB_API_BASE__ = "${escapeHtml(apiBase)}";
    window.__OPENBB_PREVIEW_WIDGET__ = JSON.parse("${widgetJson}");
  </script>
  <script nonce="${nonce}" src="${rendererUri}"></script>
  <script nonce="${nonce}" src="${previewUri}"></script>
</body>
</html>`;
}

/**
 * Open a single-widget preview panel beside the current editor.
 */
export function openPreviewPanel(
  context: vscode.ExtensionContext,
  widgetMeta: WidgetMeta,
): vscode.WebviewPanel {
  const panel = vscode.window.createWebviewPanel(
    "openbb.previewWidget",
    `Preview: ${widgetMeta.name}`,
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [
        vscode.Uri.joinPath(context.extensionUri, "media"),
      ],
    },
  );
  const nonce = generateNonce();
  const rendererUri = panel.webview
    .asWebviewUri(
      vscode.Uri.joinPath(context.extensionUri, "media", "renderer.js"),
    )
    .toString();
  const previewUri = panel.webview
    .asWebviewUri(
      vscode.Uri.joinPath(context.extensionUri, "media", "preview.js"),
    )
    .toString();
  panel.webview.html = buildPreviewHtml(
    widgetMeta,
    nonce,
    panel.webview.cspSource,
    API_BASE,
    rendererUri,
    previewUri,
  );
  return panel;
}
