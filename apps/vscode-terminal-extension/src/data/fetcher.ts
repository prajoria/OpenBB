// Widget endpoint fetcher (#1820).
//
// Loopback-only HTTP GET client. Per ADR
// `docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md`, this
// module MUST NOT emit a bearer-style auth header nor a token query
// parameter. Loopback binding is the primary auth control.
// `scripts/verify-auth-invariants.sh` guards these facts.

import type * as vscode from "vscode";

export interface WidgetFetcherConfig {
  apiBase: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  outputChannel?: vscode.OutputChannel;
}

export interface WidgetFetchResult {
  status: number;
  data: unknown;
  error?: string;
}

export class WidgetFetcher {
  private readonly apiBase: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly outputChannel?: vscode.OutputChannel;

  constructor(config: WidgetFetcherConfig) {
    this.apiBase = config.apiBase.replace(/\/$/, "");
    this.fetchImpl = config.fetchImpl ?? fetch;
    this.timeoutMs = config.timeoutMs ?? 5000;
    this.outputChannel = config.outputChannel;
  }

  async fetchWidget(
    endpoint: string,
    params?: Record<string, string>,
  ): Promise<WidgetFetchResult> {
    const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
    let url = `${this.apiBase}${path}`;
    if (params && Object.keys(params).length > 0) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) qs.append(k, v);
      url += `?${qs.toString()}`;
    }

    let signal: AbortSignal | undefined;
    try {
      signal = AbortSignal.timeout(this.timeoutMs);
    } catch {
      signal = undefined;
    }

    try {
      const res = await this.fetchImpl(url, { method: "GET", signal });
      const status = res.status;
      if (status < 200 || status >= 300) {
        const err = `HTTP ${status}`;
        return { status, data: null, error: err };
      }
      const data = await res.json().catch(() => null);
      this._loudEmpty(endpoint, data);
      return { status, data };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { status: 0, data: null, error: msg };
    }
  }

  private _loudEmpty(endpoint: string, data: unknown): void {
    const empty =
      (Array.isArray(data) && data.length === 0) ||
      (data !== null &&
        typeof data === "object" &&
        !Array.isArray(data) &&
        Object.keys(data as Record<string, unknown>).length === 0);
    if (empty) {
      this.outputChannel?.appendLine(
        `[widget-fetcher] WARNING: empty response from ${endpoint} — likely shape mismatch or missing data`,
      );
    }
  }
}
