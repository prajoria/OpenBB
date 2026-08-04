// OpenBB Terminal VS Code extension — activation shell.
//
// Phase 1 wiring: webview host (#1814), theme bridge (#1815), layouts
// (#1816), CSP hardening (#1817). Phase 2 wiring: back-end lifecycle
// (#1819) — spawn `openbb-api`, poll `/widgets.json`, and reflect state
// in a status-bar item. Symbol context v1 (#1823) — widget selectors
// broadcast into all panels; validation via /api/v1/equity/search.

import * as vscode from "vscode";

import { openTerminalPanel } from "./webview/panel";
import { BackendLifecycle } from "./backend/lifecycle";
import { registerStatusBar } from "./backend/statusBar";
import { BackendState } from "./backend/state";
import { SymbolContext } from "./symbol/context";
import { registerNotebookSymbolWatcher } from "./notebook/watcher";
import { SymbolValidator } from "./symbol/validator";
import { registerSymbolHoverProvider } from "./hover/provider";
import { createSymbolStatusBarItem } from "./symbol/statusBar";
import { attachSymbolBridge } from "./symbol/panel-glue";
import { registerCommands } from "./commands/register";
import { registerSelectionCodeAction } from "./editor/codeAction";
import { registerPanelFocusContext } from "./commands/context";
import { DataModeController } from "./data/mode";
import { WidgetFetcher } from "./data/fetcher";
import { attachDataModeToPanel } from "./data/mode-glue";
import { AnalysisRunner } from "./analysis/runner";
import { registerGoldenCommands } from "./golden/command";
import { registerWidgetBrowser } from "./widget-browser/browser";
import { getFixtureWidgetsManifest } from "./layouts/registry";

/**
 * Simple TreeItem-returning stub used for all three sidebar views until
 * the real providers land in later Phase 1 issues.
 */
class PlaceholderTreeProvider
  implements vscode.TreeDataProvider<vscode.TreeItem>
{
  private readonly _label: string;

  constructor(label: string) {
    this._label = label;
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): Thenable<vscode.TreeItem[]> {
    if (element) {
      return Promise.resolve([]);
    }
    const item = new vscode.TreeItem(
      this._label,
      vscode.TreeItemCollapsibleState.None,
    );
    item.tooltip = "Placeholder — full implementation coming in #1830.";
    return Promise.resolve([item]);
  }
}

export function activate(context: vscode.ExtensionContext): void {
  console.log("OpenBB Terminal activated");

  const outputChannel = vscode.window.createOutputChannel("OpenBB Terminal");
  context.subscriptions.push(outputChannel);

  const cfg = vscode.workspace.getConfiguration("openbb");
  const pythonPath = cfg.get<string>("pythonPath", "");
  const apiPort = cfg.get<number>("apiPort", 6900);
  const apiBase = cfg.get<string>("apiBaseUrl", `http://127.0.0.1:${apiPort}`);
  const autoStart = cfg.get<boolean>("autoStartBackend", false);
  const autoRestartOnError = cfg.get<boolean>("autoRestartBackend", false);
  const autoRestartMaxAttempts = cfg.get<number>("autoRestartMaxAttempts", 3);

  const dataMode = new DataModeController({ outputChannel });
  // Host-side WidgetFetcher instance for future host-driven fetches; the
  // webview currently does its own fetches via window.__OPENBB_API_BASE__.
  const widgetFetcher = new WidgetFetcher({ apiBase, outputChannel });
  void widgetFetcher;

  const lifecycle = new BackendLifecycle(context, {
    pythonPath,
    port: apiPort,
    apiBase,
    outputChannel,
    autoRestartOnError,
    autoRestartMaxAttempts,
    onStateChange: (s: BackendState): void => {
      outputChannel.appendLine(
        `[state] status=${s.status} pid=${s.pid ?? "-"} lastError=${
          s.lastError ?? "-"
        }`,
      );
      dataMode.updateFromBackendState(s);
    },
  });
  context.subscriptions.push(lifecycle);

  context.subscriptions.push(
    vscode.commands.registerCommand("openbb.startBackend", async () => {
      await lifecycle.start();
    }),
    vscode.commands.registerCommand("openbb.stopBackend", async () => {
      await lifecycle.stop();
    }),
    vscode.commands.registerCommand("openbb.restartBackend", async () => {
      await lifecycle.stop();
      await lifecycle.start();
    }),
    vscode.commands.registerCommand("openbb.openBackendLogs", () => {
      outputChannel.show(true);
    }),
  );

  registerStatusBar(context, lifecycle);
  context.subscriptions.push(lifecycle.startHealthMonitor());

  if (autoStart) {
    void lifecycle.start().catch((err: unknown) => {
      outputChannel.appendLine(`autoStart failed: ${String(err)}`);
    });
  }

  const symbolStatusBar = createSymbolStatusBarItem();
  context.subscriptions.push(symbolStatusBar);
  const symbolContext = new SymbolContext({ apiBase, statusBar: symbolStatusBar });

  const notebookWatcher = registerNotebookSymbolWatcher(context, symbolContext);
  context.subscriptions.push(notebookWatcher);

  const wb = registerWidgetBrowser(context, () =>
    getFixtureWidgetsManifest(context),
  );
  context.subscriptions.push(wb.disposable);

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "openbb.previewWidgetFromBrowser",
      (node: { meta?: { id?: string } } | undefined) => {
        void vscode.window.showInformationMessage(
          `Preview widget: ${node?.meta?.id ?? "unknown"}`,
        );
      },
    ),
    vscode.commands.registerCommand(
      "openbb.addWidgetToActiveLayout",
      (node: { meta?: { id?: string } } | undefined) => {
        void vscode.window.showInformationMessage(
          `Add ${node?.meta?.id ?? "unknown"} to layout: coming in #1831`,
        );
      },
    ),
  );

  // Hover provider (#1825) — Python + notebook cells. Independent
  // SymbolValidator instance so hover lookups don't perturb the
  // SymbolContext validator's cache lifecycle.
  const hoverValidator = new SymbolValidator({ apiBase });
  registerSymbolHoverProvider(context, hoverValidator, apiBase);

  const openTerminalCmd = vscode.commands.registerCommand(
    "openbb.openTerminal",
    () => {
      const panel = openTerminalPanel(context);
      const bridge = attachSymbolBridge(panel, symbolContext);
      context.subscriptions.push(bridge);
      const focusSub = registerPanelFocusContext(panel);
      context.subscriptions.push(focusSub);
      const dataModeSub = attachDataModeToPanel(panel, dataMode);
      context.subscriptions.push(dataModeSub);
    },
  );
  context.subscriptions.push(openTerminalCmd);

  const analysisRunner = new AnalysisRunner({
    pythonPath,
    workspaceRoot: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
    outputChannel,
  });
  registerCommands(context, undefined, analysisRunner);
  registerSelectionCodeAction(context);
  registerGoldenCommands(context, outputChannel);

  const layoutsView = vscode.window.registerTreeDataProvider(
    "openbbLayouts",
    new PlaceholderTreeProvider("Coming in #1830"),
  );
  const backendView = vscode.window.registerTreeDataProvider(
    "openbbBackend",
    new PlaceholderTreeProvider("Coming in #1830"),
  );
  context.subscriptions.push(layoutsView, backendView);
}

export function deactivate(): void {
  // no-op
}
