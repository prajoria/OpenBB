// CSP builder for the OpenBB Terminal webview (#1817).
//
// Extracted from panel.ts so the directive set is a single, testable
// source of truth. Directive values match ADR
// 2026-08-04-vscode-terminal-webview-auth.md §2.2.

import { randomBytes } from "node:crypto";

export interface CspConfig {
  apiBase: string;
  nonce: string;
}

/**
 * Build the Content-Security-Policy meta content string.
 *
 * The `connect-src` derivation swaps `http` for `ws` so an
 * `http://127.0.0.1:6900` apiBase yields both the HTTP origin and its
 * `ws://127.0.0.1:6900` websocket peer (and `https` -> `wss`).
 */
export function buildCsp(config: CspConfig): string {
  const { apiBase, nonce } = config;
  const wsBase = apiBase.replace("http", "ws");
  const directives = [
    `default-src 'none'`,
    `script-src 'nonce-${nonce}'`,
    `style-src 'nonce-${nonce}' 'unsafe-inline'`,
    `connect-src ${apiBase} ${wsBase}`,
    `img-src 'self' data:`,
    `font-src 'self'`,
    `frame-src 'none'`,
    `object-src 'none'`,
    `base-uri 'none'`,
  ];
  return directives.join("; ") + ";";
}

/** Cryptographically random per-panel nonce (base64, >=32 chars). */
export function generateNonce(): string {
  return randomBytes(24).toString("base64");
}
