// Status-bar item reflecting BackendLifecycle state (#1819).

import * as vscode from "vscode";

import { BackendLifecycle } from "./lifecycle";
import { BackendState } from "./state";

export function registerStatusBar(
  context: vscode.ExtensionContext,
  lifecycle: BackendLifecycle,
): vscode.Disposable {
  const item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  item.command = "openbb.openBackendLogs";

  const render = (state: BackendState): void => {
    switch (state.status) {
      case "stopped":
        item.text = "$(circle-slash) OpenBB: stopped";
        item.backgroundColor = undefined;
        break;
      case "starting":
        item.text = "$(sync~spin) OpenBB: starting…";
        item.backgroundColor = undefined;
        break;
      case "running":
        item.text = "$(check) OpenBB";
        item.backgroundColor = new vscode.ThemeColor(
          "statusBarItem.prominentBackground",
        );
        break;
      case "error":
        item.text = "$(error) OpenBB: error";
        item.backgroundColor = new vscode.ThemeColor(
          "statusBarItem.errorBackground",
        );
        break;
    }
    const parts: string[] = [
      `port: ${state.port}`,
      state.lastHealthAt
        ? `lastHealthAt: ${state.lastHealthAt.toISOString()}`
        : "lastHealthAt: —",
    ];
    if (state.lastError) {
      parts.push(`lastError: ${state.lastError}`);
    }
    item.tooltip = parts.join("\n");
    item.show();
  };

  render(lifecycle.getState());
  const sub = lifecycle.subscribe(render);

  const disposable: vscode.Disposable = {
    dispose: () => {
      sub.dispose();
      item.dispose();
    },
  };
  context.subscriptions.push(disposable);
  return disposable;
}
