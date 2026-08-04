// Status bar entry (#1823).

import * as vscode from "vscode";
import { SymbolContext } from "./context";

export function createSymbolStatusBarItem(): vscode.StatusBarItem {
  const item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    200,
  );
  item.tooltip = "Active symbol — click to change";
  item.command = "openbb.openSymbolInTerminal";
  item.text = `$(dash) —`;
  item.show();
  return item;
}

export function registerSymbolStatusBar(
  context: vscode.ExtensionContext,
  symbolContext: SymbolContext,
): vscode.Disposable {
  const item = createSymbolStatusBarItem();
  const sym = symbolContext.getActiveSymbol();
  if (sym) {
    item.text = `$(symbol-parameter) ${sym}`;
  }
  context.subscriptions.push(item);
  return item;
}
