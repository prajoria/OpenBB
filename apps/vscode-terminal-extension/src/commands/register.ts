// Command palette registrations (#1822, extended for #1831).

import * as vscodeReal from "vscode";
import { openTerminalPanel } from "../webview/panel";
import type { LayoutManager } from "../layouts/manager";

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

const SYMBOL_RE = /^[A-Z]{1,5}(:[A-Z]+)?$/;

export function registerCommands(
  context: vscodeReal.ExtensionContext,
  vscodeApi: VsCodeApi = vscodeReal as unknown as VsCodeApi,
  analysisRunner?: AnalysisRunnerLike,
  layoutManager?: LayoutManager,
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
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const name = await vscodeApi.window.showInputBox({
      placeHolder: "Layout name",
    });
    if (!name) {
      return;
    }
    const builtins = (await layoutManager.listAll()).builtins;
    const items: { label: string; description?: string; id?: string }[] = [
      { label: "Empty", description: "Blank 12-col grid" },
      ...builtins.map((b) => ({
        label: b.name,
        description: `${b.slots.length} slots`,
        id: b.id,
      })),
    ];
    const picked = await vscodeApi.window.showQuickPick(items, {
      placeHolder: "Choose a template",
    });
    if (!picked) {
      return;
    }
    await layoutManager.createLayout(name, picked.id);
    await vscodeApi.window.showInformationMessage(`Layout "${name}" saved`);
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

  reg("openbb.exportLayout", async (arg: unknown) => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage("Layout manager not wired");
      return;
    }
    let id: string | undefined;
    if (arg && typeof arg === "object" && "layout" in arg) {
      id = (arg as { layout: { id: string } }).layout?.id;
    }
    if (!id) {
      const all = await layoutManager.listAll();
      const items = all.user.map((l) => ({ label: l.name, description: l.id, id: l.id }));
      if (items.length === 0) {
        await vscodeApi.window.showInformationMessage("No user layouts to export");
        return;
      }
      const picked = await vscodeApi.window.showQuickPick(items, {
        placeHolder: "Select a layout to export",
      });
      if (!picked) {
        return;
      }
      id = picked.id;
    }
    try {
      const uri = await layoutManager.exportToWorkspace(id);
      await vscodeReal.window.showTextDocument(uri);
      await vscodeApi.window.showInformationMessage(`Exported to ${uri.fsPath}`);
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Export failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.importLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage("Layout manager not wired");
      return;
    }
    const uris = await vscodeReal.window.showOpenDialog({
      canSelectMany: false,
      filters: { "Layout JSON": ["json"] },
      openLabel: "Import Layout",
    });
    if (!uris || uris.length === 0) {
      return;
    }
    try {
      const imported = await layoutManager.importFromFile(uris[0]);
      await vscodeApi.window.showInformationMessage(
        `Imported "${imported.name}"`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Import failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.renameLayout", async (arg: unknown) => {
    if (!layoutManager) {
      return;
    }
    let id: string | undefined;
    if (arg && typeof arg === "object" && "layout" in arg) {
      id = (arg as { layout: { id: string } }).layout?.id;
    }
    if (!id) {
      const all = await layoutManager.listAll();
      const picked = await vscodeApi.window.showQuickPick(
        all.user.map((l) => ({ label: l.name, description: l.id, id: l.id })),
        { placeHolder: "Select a layout to rename" },
      );
      if (!picked) {
        return;
      }
      id = picked.id;
    }
    const newName = await vscodeApi.window.showInputBox({
      placeHolder: "New name",
    });
    if (!newName) {
      return;
    }
    try {
      await layoutManager.renameLayout(id, newName);
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Rename failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.duplicateLayout", async (arg: unknown) => {
    if (!layoutManager) {
      return;
    }
    let id: string | undefined;
    if (arg && typeof arg === "object" && "layout" in arg) {
      id = (arg as { layout: { id: string } }).layout?.id;
    }
    if (!id) {
      const all = await layoutManager.listAll();
      const picked = await vscodeApi.window.showQuickPick(
        [...all.user, ...all.builtins].map((l) => ({
          label: l.name,
          description: l.id,
          id: l.id,
        })),
        { placeHolder: "Select a layout to duplicate" },
      );
      if (!picked) {
        return;
      }
      id = picked.id;
    }
    try {
      const dup = await layoutManager.duplicateLayout(id);
      await vscodeApi.window.showInformationMessage(
        `Duplicated as "${dup.name}"`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Duplicate failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.deleteLayout", async (arg: unknown) => {
    if (!layoutManager) {
      return;
    }
    let id: string | undefined;
    let name: string | undefined;
    if (arg && typeof arg === "object" && "layout" in arg) {
      const l = (arg as { layout: { id: string; name: string } }).layout;
      id = l?.id;
      name = l?.name;
    }
    if (!id) {
      const all = await layoutManager.listAll();
      const picked = await vscodeApi.window.showQuickPick(
        all.user.map((l) => ({ label: l.name, description: l.id, id: l.id })),
        { placeHolder: "Select a layout to delete" },
      );
      if (!picked) {
        return;
      }
      id = picked.id;
      name = picked.label;
    }
    const confirm = await vscodeReal.window.showWarningMessage(
      `Delete layout "${name ?? id}"? This cannot be undone.`,
      { modal: true },
      "Delete",
    );
    if (confirm !== "Delete") {
      return;
    }
    try {
      await layoutManager.deleteLayout(id);
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Delete failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  return disposables;
}
