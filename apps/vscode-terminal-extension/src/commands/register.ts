// Command palette registrations (#1822).
//
// Registers the non-backend-lifecycle commands from PRD §12.1. The
// backend lifecycle commands (openbb.startBackend/stopBackend/
// restartBackend/openBackendLogs) are owned by #1819 and are NOT
// registered here.

import * as vscodeReal from "vscode";
import { openTerminalPanel } from "../webview/panel";
import { openPreviewPanel } from "../preview/panel";
import { getFixtureWidgetsManifest } from "../layouts/registry";
import type { WidgetMeta } from "../layouts/types";

interface PreviewQuickPickItem {
  label: string;
  description: string;
  detail: string;
  widget: WidgetMeta;
}

/** Minimal subset of the vscode API this module depends on. */
export interface VsCodeApi {
  commands: {
    registerCommand(
      id: string,
      handler: (...args: unknown[]) => unknown,
    ): { dispose(): void };
  };
  window: {
    showInputBox(
      opts?: {
        placeHolder?: string;
        prompt?: string;
        validateInput?: (v: string) => string | undefined;
      },
    ): Thenable<string | undefined>;
    showInformationMessage(msg: string): Thenable<string | undefined>;
    showWarningMessage(msg: string): Thenable<string | undefined>;
    showErrorMessage(msg: string): Thenable<string | undefined>;
    showQuickPick<T extends { label: string }>(
      items: T[] | Thenable<T[]>,
      options?: { placeHolder?: string; matchOnDescription?: boolean; matchOnDetail?: boolean },
    ): Thenable<T | undefined>;
  };
}

/** Minimal AnalysisRunner surface used by openbb.runAnalysis (#1828). */
export interface AnalysisRunnerLike {
  runForSymbol(symbol: string): Promise<{
    notebookUri: unknown;
    error?: string;
  }>;
}

/** Minimal PaperOrderHandler surface used by paper buy/sell (#1835). */
export interface PaperOrderHandlerLike {
  placeOrder(
    side: "BUY" | "SELL",
    opts?: { quantity?: number; confirmOverride?: boolean },
  ): Promise<{ ok: boolean; message: string; endpoint?: string }>;
}

const SYMBOL_RE = /^[A-Z]{1,5}(:[A-Z]+)?$/;

export function registerCommands(
  context: vscodeReal.ExtensionContext,
  vscodeApi: VsCodeApi = vscodeReal as unknown as VsCodeApi,
  analysisRunner?: AnalysisRunnerLike,
  _layoutManager?: unknown,
  paperOrderHandler?: PaperOrderHandlerLike,
): { dispose(): void }[] {
  const disposables: { dispose(): void }[] = [];

  const reg = (
    id: string,
    handler: (...args: unknown[]) => unknown,
  ): void => {
    const d = vscodeApi.commands.registerCommand(id, handler);
    disposables.push(d);
    context.subscriptions.push(d as vscodeReal.Disposable);
  };

  reg("openbb.newLayout", async () => {
    const name = await vscodeApi.window.showInputBox({
      placeHolder: "Layout name",
    });
    if (name) {
      await vscodeApi.window.showInformationMessage(
        `Layout "${name}" saved (placeholder — persistence in #1831)`,
      );
    }
  });

  reg("openbb.openSymbolInTerminal", async () => {
    const sym = await vscodeApi.window.showInputBox({
      placeHolder: "Symbol (e.g. AAPL)",
    });
    if (!sym) {
      return;
    }
    if (!SYMBOL_RE.test(sym)) {
      await vscodeApi.window.showWarningMessage(
        `Invalid symbol: "${sym}" (expected e.g. AAPL or AAPL:NASDAQ)`,
      );
      return;
    }
    openTerminalPanel(context, "equity-deep-dive");
  });

  reg("openbb.openPortfolio", () => {
    openTerminalPanel(context, "portfolio-overview");
  });

  reg("openbb.openTradingDesk", async () => {
    await vscodeApi.window.showInformationMessage(
      "Trading Desk layout ships in #1821",
    );
  });

  reg("openbb.openRisk", async () => {
    await vscodeApi.window.showInformationMessage(
      "Portfolio Risk layout ships in #1821",
    );
  });

  reg("openbb.openChart", async () => {
    const sym = await vscodeApi.window.showInputBox({
      placeHolder: "Symbol (e.g. AAPL)",
    });
    if (!sym) {
      return;
    }
    await vscodeApi.window.showInformationMessage(
      `Chart layout ships in #1821 (symbol: ${sym})`,
    );
  });

  reg("openbb.setApiKey", async () => {
    await vscodeApi.window.showInformationMessage(
      "API key configuration ships in #1836",
    );
  });

  reg("openbb.previewWidget", async () => {
    const widgets = await getFixtureWidgetsManifest(context);
    const items: PreviewQuickPickItem[] = widgets.map((w) => ({
      label: w.name,
      description: `${w.id} · ${w.type}`,
      detail: w.endpoint,
      widget: w,
    }));
    const picked = await vscodeApi.window.showQuickPick(items, {
      placeHolder: "Select a widget to preview",
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (!picked) {
      return;
    }
    openPreviewPanel(context, picked.widget);
  });

  reg("openbb.paperBuyActive", async () => {
    if (!paperOrderHandler) {
      await vscodeApi.window.showInformationMessage(
        "Paper buy ships in #1835",
      );
      return;
    }
    const result = await paperOrderHandler.placeOrder("BUY");
    if (result.ok) {
      await vscodeApi.window.showInformationMessage(result.message);
    } else {
      await vscodeApi.window.showWarningMessage(result.message);
    }
  });

  reg("openbb.paperSellActive", async () => {
    if (!paperOrderHandler) {
      await vscodeApi.window.showInformationMessage(
        "Paper sell ships in #1835",
      );
      return;
    }
    const result = await paperOrderHandler.placeOrder("SELL");
    if (result.ok) {
      await vscodeApi.window.showInformationMessage(result.message);
    } else {
      await vscodeApi.window.showWarningMessage(result.message);
    }
  });

  reg("openbb.runAnalysis", async () => {
    const sym = await vscodeApi.window.showInputBox({
      placeHolder: "Symbol (e.g. MSFT)",
      validateInput: (v) =>
        SYMBOL_RE.test(v) ? undefined : "Uppercase letters, 1-5 chars",
    });
    if (!sym) {
      return;
    }
    if (!analysisRunner) {
      await vscodeApi.window.showWarningMessage(
        "Analysis runner not wired — extension activation is incomplete",
      );
      return;
    }
    const result = await analysisRunner.runForSymbol(sym);
    if (result.error || !result.notebookUri) {
      await vscodeApi.window.showErrorMessage(
        `Analysis failed: ${result.error ?? "unknown error"}`,
      );
      return;
    }
    await vscodeApi.window.showInformationMessage(
      `Opened 7-phase analysis notebook for ${sym}`,
    );
  });

  reg("openbb.exportLayout", async () => {
    await vscodeApi.window.showInformationMessage(
      "Layout export ships in #1831",
    );
  });

  reg("openbb.importLayout", async () => {
    await vscodeApi.window.showInformationMessage(
      "Layout import ships in #1831",
    );
  });

  return disposables;
}
