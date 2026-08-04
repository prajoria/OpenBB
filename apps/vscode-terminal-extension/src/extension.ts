// OpenBB Terminal VS Code extension — Phase 1 scaffold (#1813).
//
// This file intentionally contains only the activation shell and stub
// tree providers. The webview host lands in #1814, theme bridge in
// #1815, layouts in #1816, and CSP hardening in #1817.

import * as vscode from "vscode";

import { openTerminalPanel } from "./webview/panel";

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

  const openTerminalCmd = vscode.commands.registerCommand(
    "openbb.openTerminal",
    () => {
      openTerminalPanel(context);
    },
  );
  context.subscriptions.push(openTerminalCmd);

  const layoutsView = vscode.window.registerTreeDataProvider(
    "openbbLayouts",
    new PlaceholderTreeProvider("Coming in #1830"),
  );
  const widgetsView = vscode.window.registerTreeDataProvider(
    "openbbWidgets",
    new PlaceholderTreeProvider("Coming in #1830"),
  );
  const backendView = vscode.window.registerTreeDataProvider(
    "openbbBackend",
    new PlaceholderTreeProvider("Coming in #1830"),
  );
  context.subscriptions.push(layoutsView, widgetsView, backendView);
}

export function deactivate(): void {
  // no-op
}
