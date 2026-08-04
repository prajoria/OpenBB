// Symbol context (#1823) — single source of truth for the "active
// symbol" across all open OpenBB Terminal panels + status bar.

import * as vscode from "vscode";
import { SymbolValidator } from "./validator";

export interface SetSymbolResult {
  accepted: boolean;
  reason?: string;
}

interface SymbolContextOptions {
  apiBase: string;
  statusBar: vscode.StatusBarItem;
}

export class SymbolContext {
  private activeSymbol: string | null = null;
  private readonly panels: Set<vscode.WebviewPanel> = new Set();
  private readonly validator: SymbolValidator;
  private readonly statusBar: vscode.StatusBarItem;

  constructor(opts: SymbolContextOptions) {
    this.validator = new SymbolValidator({ apiBase: opts.apiBase });
    this.statusBar = opts.statusBar;
    this.renderStatus();
  }

  registerPanel(panel: vscode.WebviewPanel): vscode.Disposable {
    this.panels.add(panel);
    const sub = panel.onDidDispose(() => {
      this.panels.delete(panel);
    });
    return {
      dispose: () => {
        this.panels.delete(panel);
        sub.dispose();
      },
    };
  }

  async setSymbol(
    symbol: string,
    _source: "widget" | "command" | "notebook" | "hover",
  ): Promise<SetSymbolResult> {
    const normalized = symbol.trim().toUpperCase();
    const result = await this.validator.validate(normalized);
    if (!result.accepted) {
      return { accepted: false, reason: result.reason };
    }
    this.activeSymbol = normalized;
    for (const panel of this.panels) {
      void panel.webview.postMessage({
        type: "symbolChange",
        symbol: normalized,
      });
    }
    this.renderStatus();
    return { accepted: true };
  }

  getActiveSymbol(): string | null {
    return this.activeSymbol;
  }

  private renderStatus(): void {
    if (this.activeSymbol) {
      this.statusBar.text = `$(symbol-parameter) ${this.activeSymbol}`;
    } else {
      this.statusBar.text = `$(dash) —`;
    }
  }
}
