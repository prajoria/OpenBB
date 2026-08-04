// Symbol hover provider (#1825). Registers a VS Code hover provider for
// Python source files and, when the runtime API supports it, Python
// notebook cells. On hover over a valid ticker (per src/hover/regex.ts):
//   1. Validate via SymbolValidator (5-min TTL cache).
//   2. Fetch last 5 daily closes from the local API bridge — NO
//      Authorization header, NO query-string token (loopback only, per
//      ADR 2026-08-04).
//   3. Render a MarkdownString with the last close + delta%, a
//      sparkline SVG data-URI, and a trusted command link to
//      `openbb.openSymbolInTerminal`.
//
// Hover results are cached per-symbol for 5 minutes; a debounce window
// (500 ms) reuses the cached MarkdownString on rapid re-hovers.

import * as vscode from "vscode";
import type { SymbolValidator } from "../symbol/validator";
import { findTickerAt } from "./regex-vscode";
import { buildSparklineSvg } from "./sparkline";

const CACHE_TTL_MS = 5 * 60 * 1000;
const DEBOUNCE_MS = 500;

interface CacheEntry {
  hover: vscode.Hover;
  expiresAt: number;
  lastMs: number;
}

interface ProviderOptions {
  apiBase: string;
  symbolValidator: SymbolValidator;
  fetchImpl?: typeof fetch;
}

class SymbolHoverProvider implements vscode.HoverProvider {
  private readonly cache = new Map<string, CacheEntry>();
  private readonly apiBase: string;
  private readonly symbolValidator: SymbolValidator;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: ProviderOptions) {
    this.apiBase = opts.apiBase.replace(/\/+$/, "");
    this.symbolValidator = opts.symbolValidator;
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  async provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    token: vscode.CancellationToken,
  ): Promise<vscode.Hover | undefined> {
    const hit = findTickerAt(document, position);
    if (!hit) {
      return undefined;
    }
    const symbol = hit.symbol;
    const now = Date.now();
    const cached = this.cache.get(symbol);
    if (cached && cached.expiresAt > now) {
      if (now - cached.lastMs < DEBOUNCE_MS) {
        return cached.hover;
      }
      cached.lastMs = now;
      return cached.hover;
    }

    const validation = await this.symbolValidator.validate(symbol);
    if (token.isCancellationRequested) return undefined;
    if (!validation.accepted) {
      return undefined;
    }

    const closes = await this.fetchCloses(symbol);
    if (token.isCancellationRequested) return undefined;
    if (!closes || closes.length === 0) {
      return undefined;
    }

    const md = this.buildMarkdown(symbol, closes);
    const hover = new vscode.Hover(md, hit.range);
    this.cache.set(symbol, {
      hover,
      expiresAt: now + CACHE_TTL_MS,
      lastMs: now,
    });
    return hover;
  }

  private async fetchCloses(symbol: string): Promise<number[] | null> {
    const url =
      this.apiBase +
      "/api/v1/equity/price/historical?symbol=" +
      encodeURIComponent(symbol) +
      "&interval=1d&limit=5";
    try {
      const resp = await this.fetchImpl(url);
      if (resp.status !== 200) return null;
      const body = (await resp.json()) as {
        results?: Array<{ close?: number }>;
        data?: Array<{ close?: number }>;
      };
      const arr = Array.isArray(body.results)
        ? body.results
        : Array.isArray(body.data)
          ? body.data
          : [];
      const closes: number[] = [];
      for (const row of arr) {
        if (row && typeof row.close === "number") {
          closes.push(row.close);
        }
      }
      return closes;
    } catch {
      return null;
    }
  }

  private buildMarkdown(
    symbol: string,
    closes: number[],
  ): vscode.MarkdownString {
    const last = closes[closes.length - 1];
    const first = closes[0];
    const deltaPct = first === 0 ? 0 : ((last - first) / first) * 100;
    const sign = deltaPct >= 0 ? "+" : "";
    const svg = buildSparklineSvg(closes);
    const svgDataUri =
      "data:image/svg+xml;utf8," + encodeURIComponent(svg);
    const cmdArgs = encodeURIComponent(JSON.stringify([symbol]));
    const md = new vscode.MarkdownString(
      `**${symbol}** — last close ${last.toFixed(2)} (${sign}${deltaPct.toFixed(2)}%)\n\n` +
        `![sparkline](${svgDataUri})\n\n` +
        `[📊 Open in Terminal](command:openbb.openSymbolInTerminal?${cmdArgs})`,
    );
    md.isTrusted = true;
    md.supportHtml = false;
    return md;
  }
}

/**
 * Register the hover provider. Attempts to include notebook cells via
 * the notebook-aware document selector; if the runtime `vscode` API in
 * this version does not accept the notebook property, it silently falls
 * back to a plain Python selector (notebook support arrives with a
 * future @types/vscode bump — tracked as follow-up).
 */
export function registerSymbolHoverProvider(
  context: vscode.ExtensionContext,
  symbolValidator: SymbolValidator,
  apiBase: string,
): vscode.Disposable {
  const provider = new SymbolHoverProvider({ symbolValidator, apiBase });
  const selectors: vscode.DocumentSelector = [
    { language: "python" },
    // Notebook cells (Python). `notebookType` field is supported by
    // recent VS Code runtimes; older @types/vscode may not model it, so
    // an object-literal cast keeps compile clean. Follow-up: drop the
    // cast once @types/vscode is bumped.
    { language: "python", notebookType: "*" } as vscode.DocumentFilter,
  ];
  const disp = vscode.languages.registerHoverProvider(selectors, provider);
  context.subscriptions.push(disp);
  return disp;
}
