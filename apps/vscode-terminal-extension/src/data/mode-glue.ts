// Glue between DataModeController and a webview panel (#1820).

import * as vscode from "vscode";
import { DataModeController } from "./mode";

export function attachDataModeToPanel(
  panel: vscode.WebviewPanel,
  controller: DataModeController,
): vscode.Disposable {
  controller.registerPanel(panel);
  const sub = panel.onDidDispose(() => {
    controller.unregisterPanel(panel);
  });
  return new vscode.Disposable(() => {
    controller.unregisterPanel(panel);
    sub.dispose();
  });
}
