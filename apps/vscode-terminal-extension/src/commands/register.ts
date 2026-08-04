// Command palette registrations (#1822).
//
// Registers the non-backend-lifecycle commands from PRD §12.1. The
// backend lifecycle commands (openbb.startBackend/stopBackend/
// restartBackend/openBackendLogs) are owned by #1819 and are NOT
// registered here.

import * as vscodeReal from "vscode";
import { openTerminalPanel } from "../webview/panel";

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
      opts?: { placeHolder?: string; prompt?: string },
    ): Thenable<string | undefined>;
    showInformationMessage(msg: string): Thenable<string | undefined>;
    showWarningMessage(msg: string): Thenable<string | undefined>;
  };
}

const SYMBOL_RE = /^[A-Z]{1,5}(:[A-Z]+)?$/;

export function registerCommands(
  context: vscodeReal.ExtensionContext,
  vscodeApi: VsCodeApi = vscodeReal as unknown as VsCodeApi,
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
    await vscodeApi.window.showInformationMessage(
      "Widget preview ships in #1832",
    );
  });

  reg("openbb.paperBuyActive", async () => {
    await vscodeApi.window.showInformationMessage(
      "Paper buy ships in #1835",
    );
  });

  reg("openbb.paperSellActive", async () => {
    await vscodeApi.window.showInformationMessage(
      "Paper sell ships in #1835",
    );
  });

  reg("openbb.runAnalysis", async () => {
    await vscodeApi.window.showInformationMessage(
      "Analysis run ships in #1828",
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
