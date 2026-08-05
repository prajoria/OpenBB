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
import { ApiKeyManager, KNOWN_KEYS, type KnownKey } from "../apikey/manager";
import type { LayoutManager } from "../layouts/manager";
import type { Layout } from "../layouts/types";

const KEY_LABELS: Record<KnownKey, string> = {
  fmp_api_key: "FMP API key",
  fmp_cached_api_key: "FMP Cached API key",
  fred_api_key: "FRED API key",
  polygon_api_key: "Polygon API key",
  intrinio_api_key: "Intrinio API key",
  tiingo_api_key: "Tiingo API key",
};

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
    showInformationMessage(
      msg: string,
      ...items: string[]
    ): Thenable<string | undefined>;
    showInformationMessage(
      msg: string,
      options: { modal?: boolean },
      ...items: string[]
    ): Thenable<string | undefined>;
    showWarningMessage(msg: string): Thenable<string | undefined>;
    showErrorMessage(msg: string): Thenable<string | undefined>;
    showQuickPick<T extends { label: string }>(
      items: T[] | Thenable<T[]>,
      options?: { placeHolder?: string; matchOnDescription?: boolean; matchOnDetail?: boolean },
    ): Thenable<T | undefined>;
    showOpenDialog(
      opts?: {
        canSelectMany?: boolean;
        filters?: Record<string, string[]>;
        openLabel?: string;
      },
    ): Thenable<vscodeReal.Uri[] | undefined>;
    showTextDocument(uri: vscodeReal.Uri): Thenable<unknown>;
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
  layoutManager?: LayoutManager,
  paperOrderHandler?: PaperOrderHandlerLike,
  apiKeyManager?: ApiKeyManager,
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

  interface LayoutPickItem {
    label: string;
    description?: string;
    id: string | undefined;
  }

  async function pickUserLayout(
    placeholder: string,
  ): Promise<Layout | undefined> {
    if (!layoutManager) {
      return undefined;
    }
    const all = await layoutManager.listAll();
    if (all.user.length === 0) {
      await vscodeApi.window.showInformationMessage("No user layouts yet.");
      return undefined;
    }
    const items = all.user.map((l) => ({
      label: l.name,
      description: l.id,
      id: l.id,
    }));
    const picked = (await vscodeApi.window.showQuickPick(items, {
      placeHolder: placeholder,
    })) as LayoutPickItem | undefined;
    if (!picked || !picked.id) {
      return undefined;
    }
    return all.user.find((l) => l.id === picked.id);
  }

  reg("openbb.newLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — see extension activation",
      );
      return;
    }
    const name = await vscodeApi.window.showInputBox({
      placeHolder: "Layout name",
    });
    if (!name || !name.trim()) {
      return;
    }
    const all = await layoutManager.listAll();
    const templateItems: LayoutPickItem[] = [
      { label: "Empty", id: undefined },
      ...all.builtins.map((b) => ({ label: b.name, description: b.id, id: b.id })),
    ];
    const picked = (await vscodeApi.window.showQuickPick(templateItems, {
      placeHolder: "Template (optional)",
    })) as LayoutPickItem | undefined;
    if (!picked) {
      return;
    }
    try {
      const layout = await layoutManager.createLayout(name.trim(), picked.id);
      await vscodeApi.window.showInformationMessage(
        `Layout "${layout.name}" created`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Create layout failed: ${err instanceof Error ? err.message : String(err)}`,
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
    interface KeyPickItem {
      label: string;
      description: string;
      key: KnownKey;
    }
    const items: KeyPickItem[] = KNOWN_KEYS.map((k) => ({
      label: KEY_LABELS[k],
      description: k,
      key: k,
    }));
    const picked = (await vscodeApi.window.showQuickPick(items, {
      placeHolder: "Select which API key to configure",
      matchOnDescription: true,
    })) as KeyPickItem | undefined;
    if (!picked) {
      return;
    }
    const mgr = apiKeyManager ?? new ApiKeyManager();
    const existing = await mgr.readSettings();
    if (existing.content === "") {
      await mgr.writeSettings(
        JSON.stringify({ credentials: {} }, null, 2) + "\n",
      );
    }
    await mgr.openInEditor(vscodeReal);
    await vscodeApi.window.showInformationMessage(
      `Edit the value for "${picked.key}" in the opened settings.json, then save.`,
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

  reg("openbb.exportLayout", async (...args: unknown[]) => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — see extension activation",
      );
      return;
    }
    const arg = args[0] as { layout?: { id: string } } | undefined;
    let id = arg?.layout?.id;
    if (!id) {
      const picked = await pickUserLayout("Layout to export");
      if (!picked) {
        return;
      }
      id = picked.id;
    }
    try {
      const uri = await layoutManager.exportToWorkspace(id);
      await vscodeApi.window.showTextDocument(uri);
      await vscodeApi.window.showInformationMessage(
        `Exported layout to ${uri.fsPath}`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Export failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.importLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — see extension activation",
      );
      return;
    }
    const picked = await vscodeApi.window.showOpenDialog({
      canSelectMany: false,
      filters: { "Layout JSON": ["json"] },
      openLabel: "Import Layout",
    });
    if (!picked || picked.length === 0) {
      return;
    }
    try {
      const layout = await layoutManager.importFromFile(picked[0]);
      await vscodeApi.window.showInformationMessage(
        `Imported "${layout.name}"`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Import failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.renameLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — see extension activation",
      );
      return;
    }
    const picked = await pickUserLayout("Layout to rename");
    if (!picked) {
      return;
    }
    const newName = await vscodeApi.window.showInputBox({
      placeHolder: "New name",
      prompt: `Rename "${picked.name}"`,
    });
    if (!newName || !newName.trim()) {
      return;
    }
    try {
      await layoutManager.renameLayout(picked.id, newName.trim());
      await vscodeApi.window.showInformationMessage(
        `Renamed to "${newName.trim()}"`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Rename failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.duplicateLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — see extension activation",
      );
      return;
    }
    const picked = await pickUserLayout("Layout to duplicate");
    if (!picked) {
      return;
    }
    try {
      const copy = await layoutManager.duplicateLayout(picked.id);
      await vscodeApi.window.showInformationMessage(
        `Duplicated as "${copy.name}"`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Duplicate failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  reg("openbb.deleteLayout", async () => {
    if (!layoutManager) {
      await vscodeApi.window.showWarningMessage(
        "Layout manager not wired — see extension activation",
      );
      return;
    }
    const picked = await pickUserLayout("Layout to delete");
    if (!picked) {
      return;
    }
    const confirmed = await vscodeApi.window.showInformationMessage(
      `Delete "${picked.name}"?`,
      { modal: true },
      "Yes",
    );
    if (confirmed !== "Yes") {
      return;
    }
    try {
      await layoutManager.deleteLayout(picked.id);
      await vscodeApi.window.showInformationMessage(
        `Deleted "${picked.name}"`,
      );
    } catch (err) {
      await vscodeApi.window.showErrorMessage(
        `Delete failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  return disposables;
}
