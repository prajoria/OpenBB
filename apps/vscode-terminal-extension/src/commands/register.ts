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
import type { LayoutManager } from "../layouts/manager";

interface PreviewQuickPickItem {
  label: string;
  description: string;
  detail: string;
  widget: WidgetMeta;
}

interface UserLayoutQuickPickItem {
  label: string;
  description: string;
  id: string;
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
        value?: string;
        validateInput?: (v: string) => string | undefined;
      },
    ): Thenable<string | undefined>;
    showInformationMessage(msg: string): Thenable<string | undefined>;
    showWarningMessage(
      msg: string,
      ...args: unknown[]
    ): Thenable<string | undefined>;
    showErrorMessage(msg: string): Thenable<string | undefined>;
    showQuickPick<T extends { label: string }>(
      items: T[] | Thenable<T[]>,
      options?: { placeHolder?: string; matchOnDescription?: boolean; matchOnDetail?: boolean },
    ): Thenable<T | undefined>;
    showOpenDialog?(opts?: {
      canSelectMany?: boolean;
      filters?: Record<string, string[]>;
      openLabel?: string;
    }): Thenable<vscodeReal.Uri[] | undefined>;
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

async function pickUserLayout(
  vscodeApi: VsCodeApi,
  layoutManager: LayoutManager,
  placeHolder: string,
): Promise<string | undefined> {
  const buckets = await layoutManager.listAll();
  if (buckets.user.length === 0) {
    await vscodeApi.window.showInformationMessage(
      "No user layouts yet — create one with 'OpenBB: New Layout'.",
    );
    return undefined;
  }
  const items: UserLayoutQuickPickItem[] = buckets.user.map((l) => ({
    label: l.name,
    description: l.id,
    id: l.id,
  }));
  const picked = await vscodeApi.window.showQuickPick(items, {
    placeHolder,
  });
  return picked?.id;
}

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
    const name = await vscodeApi.window.showInputBox({
      placeHolder: "Layout name",
    });
    if (!name) {
      return;
    }
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const layout = await layoutManager.createLayout(name);
    await vscodeApi.window.showInformationMessage(
      `Created layout "${layout.name}" (${layout.id}).`,
    );
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

  reg("openbb.exportLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const id = await pickUserLayout(
      vscodeApi,
      layoutManager,
      "Select a layout to export to workspace",
    );
    if (!id) {
      return;
    }
    try {
      const uri = await layoutManager.exportToWorkspace(id);
      await vscodeApi.window.showInformationMessage(
        `Exported layout to ${uri.fsPath}`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Export failed: ${(err as Error).message}`,
      );
    }
  });

  reg("openbb.importLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const dialog = vscodeApi.window.showOpenDialog;
    if (!dialog) {
      await vscodeApi.window.showWarningMessage(
        "File picker unavailable in this environment.",
      );
      return;
    }
    const picked = await dialog({
      canSelectMany: false,
      filters: { "JSON layout": ["json"] },
      openLabel: "Import layout",
    });
    if (!picked || picked.length === 0) {
      return;
    }
    try {
      const layout = await layoutManager.importFromFile(picked[0]);
      await vscodeApi.window.showInformationMessage(
        `Imported layout "${layout.name}".`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Import failed: ${(err as Error).message}`,
      );
    }
  });

  reg("openbb.renameLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const id = await pickUserLayout(
      vscodeApi,
      layoutManager,
      "Select a layout to rename",
    );
    if (!id) {
      return;
    }
    const newName = await vscodeApi.window.showInputBox({
      placeHolder: "New layout name",
      prompt: "Enter the new name for this layout",
    });
    if (!newName) {
      return;
    }
    try {
      await layoutManager.renameLayout(id, newName);
      await vscodeApi.window.showInformationMessage(
        `Renamed layout to "${newName}".`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Rename failed: ${(err as Error).message}`,
      );
    }
  });

  reg("openbb.duplicateLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const id = await pickUserLayout(
      vscodeApi,
      layoutManager,
      "Select a layout to duplicate",
    );
    if (!id) {
      return;
    }
    try {
      const copy = await layoutManager.duplicateLayout(id);
      await vscodeApi.window.showInformationMessage(
        `Duplicated layout as "${copy.name}".`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Duplicate failed: ${(err as Error).message}`,
      );
    }
  });

  reg("openbb.deleteLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — extension activation is incomplete",
      );
      return;
    }
    const id = await pickUserLayout(
      vscodeApi,
      layoutManager,
      "Select a layout to delete",
    );
    if (!id) {
      return;
    }
    const confirm = await vscodeApi.window.showWarningMessage(
      `Delete layout ${id}? This cannot be undone.`,
      { modal: true },
      "Delete",
    );
    if (confirm !== "Delete") {
      return;
    }
    try {
      await layoutManager.deleteLayout(id);
      await vscodeApi.window.showInformationMessage("Layout deleted.");
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Delete failed: ${(err as Error).message}`,
      );
    }
  });

  return disposables;
}
